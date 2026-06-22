"""Command-line entry points for running SDSA."""
from __future__ import annotations

import argparse
import os
import secrets
import socket
from collections.abc import Sequence

import uvicorn

from . import __version__


MIN_RANDOM_PORT = 10001
MAX_RANDOM_PORT = 65535


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{name} must be an integer, got {raw!r}") from e


def _find_available_port(host: str, *, attempts: int = 100) -> int:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    last_error: OSError | None = None
    for _ in range(attempts):
        port = MIN_RANDOM_PORT + secrets.randbelow(MAX_RANDOM_PORT - MIN_RANDOM_PORT + 1)
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
            return port
        except OSError as e:
            last_error = e
    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(
        f"could not find an available port between {MIN_RANDOM_PORT} and {MAX_RANDOM_PORT}{detail}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdsa-server",
        description="Run the Secure Data Sanitization App server.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command", required=True)
    start = subcommands.add_parser("start", help="Start the SDSA web server.")
    start.add_argument(
        "--host",
        default=os.environ.get("SDSA_HOST", "127.0.0.1"),
        help="Bind host. Defaults to SDSA_HOST or 127.0.0.1.",
    )
    port_group = start.add_mutually_exclusive_group()
    port_group.add_argument(
        "--port",
        type=int,
        default=_env_int("SDSA_PORT", 8000),
        help="Bind port. Defaults to SDSA_PORT or 8000.",
    )
    port_group.add_argument(
        "--random-port",
        action="store_true",
        help=f"Bind to an available random port from {MIN_RANDOM_PORT} to {MAX_RANDOM_PORT}.",
    )
    start.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn reload for local development.",
    )
    start.add_argument(
        "--proxy-headers",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("SDSA_PROXY_HEADERS", "true").lower() not in {"0", "false", "no"},
        help="Trust proxy headers. Enabled by default.",
    )
    start.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("SDSA_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        help="Allowed proxy IPs for forwarded headers.",
    )
    start.set_defaults(func=start_server)
    return parser


def start_server(args: argparse.Namespace) -> int:
    port = _find_available_port(args.host) if args.random_port else args.port
    uvicorn.run(
        "sdsa.main:app",
        host=args.host,
        port=port,
        reload=args.reload,
        proxy_headers=args.proxy_headers,
        forwarded_allow_ips=args.forwarded_allow_ips,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
