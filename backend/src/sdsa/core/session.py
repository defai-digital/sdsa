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
    hmac_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session_id = secrets.token_urlsafe(16)
        session = Session(session_id=session_id, created_at=time.time())
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        if self._is_expired(session):
            self.delete(session_id)
            return None
        return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            _zeroize(session)

    def sweep(self) -> int:
        now = time.time()
        ttl = get_config().session_ttl_seconds
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now - s.created_at > ttl]
            for sid in expired:
                session = self._sessions.pop(sid, None)
                if session is not None:
                    _zeroize(session)
        return len(expired)

    def _is_expired(self, session: Session) -> bool:
        return time.time() - session.created_at > get_config().session_ttl_seconds


def _zeroize(session: Session) -> None:
    # Best effort; Python does not guarantee memory clearing. Documented in ADR-0007.
    session.df = None
    session.detection = None
    if session.output_bytes is not None:
        try:
            ba = bytearray(session.output_bytes)
            for i in range(len(ba)):
                ba[i] = 0
        except Exception:
            pass
        session.output_bytes = None
    session.output_report = None
    try:
        ka = bytearray(session.hmac_key)
        for i in range(len(ka)):
            ka[i] = 0
    except Exception:
        pass


_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
