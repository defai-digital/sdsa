"""In-memory session store with TTL and best-effort zeroization (ADR-0007).

Sessions hold the parsed DataFrame and the detection report between the
upload and process calls. Data never touches disk in this MVP.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from .config import get_config


@dataclass
class Session:
    session_id: str
    created_at: float
    df: pl.DataFrame | None = None
    detection: dict[str, Any] | None = None
    output_bytes: bytes | None = None
    output_report: dict[str, Any] | None = None
    hmac_key: bytes | None = field(default_factory=lambda: secrets.token_bytes(32))
    # Cumulative per-column DP budget spent across every release in this
    # session. Persists across /process calls so repeated noisy releases of the
    # same data can't average the noise away (ADR-0002 budget enforcement).
    dp_spent: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    df: pl.DataFrame | None = None
    detection: dict[str, Any] | None = None
    output_bytes: bytes | None = None
    output_report: dict[str, Any] | None = None
    hmac_key: bytes | None = None
    dp_spent: dict[str, float] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        # Opportunistic reap — ensures abandoned sessions don't accumulate
        # even if no background sweeper is running (e.g. tests, single-shot
        # CLI usage).
        self.sweep()
        session_id = secrets.token_urlsafe(16)
        session = Session(session_id=session_id, created_at=time.time())
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        expired: Session | None = None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                expired = self._sessions.pop(session_id, None)
                session = None
        if expired is not None:
            _zeroize(expired)
            return None
        return session

    def checkout(self, session_id: str) -> SessionSnapshot | None:
        expired: Session | None = None
        snapshot: SessionSnapshot | None = None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                expired = self._sessions.pop(session_id, None)
            else:
                snapshot = SessionSnapshot(
                    session_id=session.session_id,
                    df=session.df.clone() if session.df is not None else None,
                    detection=dict(session.detection) if session.detection is not None else None,
                    output_bytes=session.output_bytes,
                    output_report=dict(session.output_report) if session.output_report is not None else None,
                    hmac_key=session.hmac_key,
                    dp_spent=dict(session.dp_spent),
                )
        if expired is not None:
            _zeroize(expired)
        return snapshot

    def clear_output(self, session_id: str) -> bool:
        expired: Session | None = None
        result = False
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                expired = self._sessions.pop(session_id, None)
            else:
                session.output_bytes = None
                session.output_report = None
                result = True
        if expired is not None:
            _zeroize(expired)
        return result

    def store_output(
        self,
        session_id: str,
        output_bytes: bytes,
        output_report: dict[str, Any],
        dp_spent: dict[str, float] | None = None,
    ) -> bool:
        expired: Session | None = None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                expired = self._sessions.pop(session_id, None)
            else:
                session.output_bytes = output_bytes
                session.output_report = output_report
                if dp_spent is not None:
                    session.dp_spent = dict(dp_spent)
                return True
        if expired is not None:
            _zeroize(expired)
        return False

    def set_dp_spent(self, session_id: str, dp_spent: dict[str, float]) -> bool:
        """Persist the cumulative per-column DP budget after a successful release."""
        expired: Session | None = None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if self._is_expired(session):
                expired = self._sessions.pop(session_id, None)
            else:
                session.dp_spent = dict(dp_spent)
                return True
        if expired is not None:
            _zeroize(expired)
        return False

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            _zeroize(session)
            return True
        return False

    def sweep(self) -> int:
        now = time.time()
        ttl = get_config().session_ttl_seconds
        expired_sessions: list[Session] = []
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now - s.created_at > ttl]
            for sid in expired:
                session = self._sessions.pop(sid, None)
                if session is not None:
                    expired_sessions.append(session)
        for session in expired_sessions:
            _zeroize(session)
        return len(expired)

    def _is_expired(self, session: Session) -> bool:
        return time.time() - session.created_at > get_config().session_ttl_seconds


def _zeroize(session: Session) -> None:
    # Best effort; Python does not guarantee memory clearing. Documented in ADR-0007.
    session.df = None
    session.detection = None
    session.dp_spent = {}
    if session.output_bytes is not None:
        try:
            ba = bytearray(session.output_bytes)
            ba[:] = b"\x00" * len(ba)
        except Exception:
            pass
        session.output_bytes = None
    session.output_report = None
    if session.hmac_key is not None:
        try:
            ka = bytearray(session.hmac_key)
            ka[:] = b"\x00" * len(ka)
        except Exception:
            pass
        session.hmac_key = None


_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_store() -> SessionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SessionStore()
    return _store
