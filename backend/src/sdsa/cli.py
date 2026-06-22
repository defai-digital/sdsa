"""Command-line entry points for running SDSA."""
from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn

from . import __version__


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{name} must be an integer, got {raw!r}") from e


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
    start.add_argument(
        "--port",
        type=int,
        default=_env_int("SDSA_PORT", 8000),
        help="Bind port. Defaults to SDSA_PORT or 8000.",
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
    uvicorn.run(
        "sdsa.main:app",
        host=args.host,
        port=args.port,
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
