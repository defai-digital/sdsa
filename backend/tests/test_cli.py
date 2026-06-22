from __future__ import annotations

import argparse

from sdsa import cli


def test_start_command_runs_uvicorn_with_defaults(monkeypatch):
    calls: list[dict] = []

    def fake_run(app, **kwargs):
        calls.append({"app": app, **kwargs})

    monkeypatch.delenv("SDSA_HOST", raising=False)
    monkeypatch.delenv("SDSA_PORT", raising=False)
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    assert cli.main(["start"]) == 0
    assert calls == [{
        "app": "sdsa.main:app",
        "host": "127.0.0.1",
        "port": 8000,
        "reload": False,
        "proxy_headers": True,
        "forwarded_allow_ips": "127.0.0.1",
    }]


def test_start_command_honors_flags(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))

    assert cli.main([
        "start",
        "--host", "0.0.0.0",
        "--port", "9000",
        "--reload",
        "--no-proxy-headers",
        "--forwarded-allow-ips", "*",
    ]) == 0

    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 9000
    assert calls[0]["reload"] is True
    assert calls[0]["proxy_headers"] is False
    assert calls[0]["forwarded_allow_ips"] == "*"


def test_start_command_can_use_random_high_port(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(cli, "_find_available_port", lambda host: 12345)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))

    assert cli.main(["start", "--random-port"]) == 0

    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 12345


def test_find_available_port_uses_port_above_10000():
    port = cli._find_available_port("127.0.0.1")

    assert cli.MIN_RANDOM_PORT <= port <= cli.MAX_RANDOM_PORT


def test_start_command_honors_environment(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setenv("SDSA_HOST", "0.0.0.0")
    monkeypatch.setenv("SDSA_PORT", "8080")
    monkeypatch.setenv("SDSA_FORWARDED_ALLOW_IPS", "10.0.0.1")
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))

    assert cli.main(["start"]) == 0

    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 8080
    assert calls[0]["forwarded_allow_ips"] == "10.0.0.1"


def test_invalid_env_port_fails_parser_construction(monkeypatch):
    monkeypatch.setenv("SDSA_PORT", "nope")

    try:
        cli.build_parser()
    except argparse.ArgumentTypeError as e:
        assert "SDSA_PORT" in str(e)
    else:
        raise AssertionError("expected invalid SDSA_PORT to fail")
