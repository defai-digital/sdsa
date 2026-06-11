"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
import secrets
import threading
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigError(ValueError):
    pass


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"environment variable {key} must be an integer, got {raw!r}") from e


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ConfigError(f"environment variable {key} must be a number, got {raw!r}") from e


def _parse_csv_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_cors_origins(value: str | None) -> tuple[str, ...]:
    origins = _parse_csv_list(value)
    if "*" in origins:
        raise ConfigError(
            "environment variable SDSA_ALLOWED_CORS_ORIGINS must not contain '*'"
        )
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(
                f"environment variable SDSA_ALLOWED_CORS_ORIGINS contains an invalid origin: {origin!r}"
            )
    return origins


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
    allowed_cors_origins: tuple[str, ...]
    deployment_salt: bytes
    deployment_salt_is_ephemeral: bool

    @classmethod
    def from_env(cls) -> "Config":
        salt_hex = os.environ.get("SDSA_DEPLOYMENT_SALT")
        if salt_hex:
            salt = bytes.fromhex(salt_hex)
            salt_is_ephemeral = False
        else:
            salt = secrets.token_bytes(32)
            salt_is_ephemeral = True

        default_k = _env_int("SDSA_DEFAULT_K", 5)
        if default_k < 2:
            raise ConfigError("SDSA_DEFAULT_K must be >= 2 (k-anonymity minimum is 2)")

        epsilon_min = _env_float("SDSA_EPSILON_MIN", 0.1)
        epsilon_max = _env_float("SDSA_EPSILON_MAX", 10.0)
        if epsilon_min >= epsilon_max:
            raise ConfigError("SDSA_EPSILON_MIN must be < SDSA_EPSILON_MAX")

        max_suppression = _env_float("SDSA_MAX_SUPPRESSION", 0.10)
        hard_max_suppression = _env_float("SDSA_HARD_MAX_SUPPRESSION", 0.50)
        if max_suppression >= hard_max_suppression:
            raise ConfigError("SDSA_MAX_SUPPRESSION must be < SDSA_HARD_MAX_SUPPRESSION")

        return cls(
            max_upload_bytes=_env_int("SDSA_MAX_UPLOAD_BYTES", 300 * 1024 * 1024),
            session_ttl_seconds=_env_int("SDSA_SESSION_TTL", 1800),
            sample_rows_for_detection=_env_int("SDSA_SAMPLE_ROWS", 10_000),
            default_k=default_k,
            default_epsilon=_env_float("SDSA_DEFAULT_EPSILON", 1.0),
            epsilon_min=epsilon_min,
            epsilon_max=epsilon_max,
            max_suppression_ratio=max_suppression,
            hard_max_suppression_ratio=hard_max_suppression,
            allowed_cors_origins=_parse_cors_origins(os.environ.get("SDSA_ALLOWED_CORS_ORIGINS")),
            deployment_salt=salt,
            deployment_salt_is_ephemeral=salt_is_ephemeral,
        )


_config: Config | None = None
_config_lock = threading.Lock()


def get_config() -> Config:
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = Config.from_env()
    return _config
