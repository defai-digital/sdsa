"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    max_upload_bytes: int
    session_ttl_seconds: int
    sample_rows_for_detection: int
    default_k: int
    default_epsilon: float
    epsilon_min: float
    epsilon_max: float
    max_suppression_ratio: float
    hard_max_suppression_ratio: float
    deployment_salt: bytes

    @classmethod
    def from_env(cls) -> "Config":
        salt_hex = os.environ.get("SDSA_DEPLOYMENT_SALT")
        if salt_hex:
            salt = bytes.fromhex(salt_hex)
        else:
            salt = secrets.token_bytes(32)
        return cls(
            max_upload_bytes=int(os.environ.get("SDSA_MAX_UPLOAD_BYTES", 300 * 1024 * 1024)),
            session_ttl_seconds=int(os.environ.get("SDSA_SESSION_TTL", 1800)),
            sample_rows_for_detection=int(os.environ.get("SDSA_SAMPLE_ROWS", 10_000)),
            default_k=int(os.environ.get("SDSA_DEFAULT_K", 5)),
            default_epsilon=float(os.environ.get("SDSA_DEFAULT_EPSILON", 1.0)),
            epsilon_min=float(os.environ.get("SDSA_EPSILON_MIN", 0.1)),
            epsilon_max=float(os.environ.get("SDSA_EPSILON_MAX", 10.0)),
            max_suppression_ratio=float(os.environ.get("SDSA_MAX_SUPPRESSION", 0.10)),
            hard_max_suppression_ratio=float(os.environ.get("SDSA_HARD_MAX_SUPPRESSION", 0.50)),
            deployment_salt=salt,
        )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config
