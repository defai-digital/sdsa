from __future__ import annotations

import threading
import time

import sdsa.core.config as config_module
import sdsa.core.session as session_module
from sdsa.core.config import ConfigError
from sdsa.core.session import Session, SessionStore, _zeroize


def test_zeroize_clears_hmac_key_reference():
    session = Session(
        session_id="s1",
        created_at=0.0,
        output_bytes=b"abc",
        output_report={"ok": True},
        hmac_key=b"super-secret",
    )
    _zeroize(session)
    assert session.output_bytes is None
    assert session.output_report is None
    assert session.hmac_key is None


def test_get_config_initializes_once_under_race(monkeypatch):
    config_module._config = None
    calls: list[int] = []
    start = threading.Event()
    original = config_module.Config.from_env.__func__

    def fake_from_env(cls):
        time.sleep(0.01)
        calls.append(1)
        return original(cls)

    monkeypatch.setattr(config_module.Config, "from_env", classmethod(fake_from_env))

    results = []

    def worker():
        start.wait()
        results.append(config_module.get_config())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len({id(result) for result in results}) == 1
    config_module._config = None


def test_get_store_initializes_once_under_race(monkeypatch):
    session_module._store = None
    calls: list[int] = []
    start = threading.Event()
    original_cls = session_module.SessionStore

    class CountingStore(original_cls):
        def __init__(self) -> None:
            time.sleep(0.01)
            calls.append(1)
            super().__init__()

    monkeypatch.setattr(session_module, "SessionStore", CountingStore)

    results = []

    def worker():
        start.wait()
        results.append(session_module.get_store())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len({id(result) for result in results}) == 1
    session_module._store = None
    monkeypatch.setattr(session_module, "SessionStore", original_cls)


def test_get_expired_session_removes_and_zeroizes():
    store = SessionStore()
    session = Session(
        session_id="expired",
        created_at=time.time() - 10_000,
        hmac_key=b"dead-key",
    )
    store._sessions[session.session_id] = session

    assert store.get(session.session_id) is None
    assert session.session_id not in store._sessions
    assert session.hmac_key is None


def test_checkout_returns_stable_snapshot_after_live_session_mutates():
    store = SessionStore()
    session = Session(session_id="s1", created_at=time.time(), df=None, hmac_key=b"k")
    session.output_bytes = b"csv"
    store._sessions[session.session_id] = session

    snap = store.checkout(session.session_id)
    assert snap is not None
    session.output_bytes = None
    session.hmac_key = None

    assert snap.output_bytes == b"csv"
    assert snap.hmac_key == b"k"


def test_config_rejects_invalid_numeric_env(monkeypatch):
    monkeypatch.setenv("SDSA_SESSION_TTL", "18O0")
    config_module._config = None
    try:
        try:
            config_module.get_config()
        except ConfigError as e:
            assert "SDSA_SESSION_TTL" in str(e)
        else:
            raise AssertionError("expected ConfigError")
    finally:
        config_module._config = None


def test_config_rejects_wildcard_cors_origin(monkeypatch):
    monkeypatch.setenv("SDSA_ALLOWED_CORS_ORIGINS", "*")
    config_module._config = None
    try:
        try:
            config_module.get_config()
        except ConfigError as e:
            assert "SDSA_ALLOWED_CORS_ORIGINS" in str(e)
        else:
            raise AssertionError("expected ConfigError")
    finally:
        config_module._config = None
