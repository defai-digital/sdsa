"""Policy suggestion config loaded from repo-root JSON files."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError

from .core.config import get_config


class PolicyConfigError(ValueError):
    pass


class SuggestedPolicy(BaseModel):
    action: str = "retain"
    params: dict[str, Any] = Field(default_factory=dict)
    is_quasi_identifier: bool | None = None
    dp_params: dict[str, float] = Field(default_factory=dict)


class PolicyDefaults(BaseModel):
    by_pii_kind: dict[str, SuggestedPolicy] = Field(default_factory=dict)
    by_kind: dict[str, SuggestedPolicy] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    defaults: PolicyDefaults = Field(default_factory=PolicyDefaults)
    fields: dict[str, SuggestedPolicy] = Field(default_factory=dict)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _candidate_paths() -> tuple[Path | None, Path]:
    env_path = os.environ.get("SDSA_POLICY_FILE")
    configured = Path(env_path).expanduser() if env_path else _project_root() / "sdsa-policy.json"
    default = _project_root() / "sdsa-policy.default.json"
    return configured, default


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        raise PolicyConfigError(f"invalid policy config JSON at {path}: {e.msg}") from e
    if not isinstance(data, dict):
        raise PolicyConfigError(f"policy config at {path} must be a JSON object")
    return data


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_policy_config() -> PolicyConfig:
    configured_path, default_path = _candidate_paths()
    data: dict[str, Any] = {}
    if default_path.exists():
        data = _load_json(default_path)
    if configured_path and configured_path.exists():
        data = _merge_dicts(data, _load_json(configured_path))
    try:
        return PolicyConfig.model_validate(data)
    except ValidationError as e:
        raise PolicyConfigError(f"invalid policy config: {e.errors()[0]['msg']}") from e


def _default_qi(col: dict[str, Any], pii: dict[str, Any]) -> bool:
    if pii.get("kind") != "none":
        return False
    if col.get("kind") not in {"numeric", "datetime", "categorical"}:
        return False
    n = int(col.get("row_count") or 0)
    u = int(col.get("n_unique") or 0)
    if u == 0 or n == 0:
        return False
    return u * get_config().default_k <= n


def _field_lookup(fields: dict[str, SuggestedPolicy], column_name: str) -> SuggestedPolicy | None:
    if column_name in fields:
        return fields[column_name]
    lowered = column_name.lower()
    for key, value in fields.items():
        if key.lower() == lowered:
            return value
    return None


def build_policy_suggestions(
    schema: list[dict],
    pii_suggestions: dict[str, dict],
) -> dict[str, dict[str, Any]]:
    config = load_policy_config()
    suggestions: dict[str, dict[str, Any]] = {}
    for col in schema:
        name = col["name"]
        pii = pii_suggestions.get(name, {"kind": "none"})

        source = "fallback"
        suggestion = _field_lookup(config.fields, name)
        if suggestion is not None:
            source = "field"
        else:
            suggestion = config.defaults.by_pii_kind.get(pii.get("kind", "none"))
            if suggestion is not None:
                source = "pii_kind"
            else:
                suggestion = config.defaults.by_kind.get(col.get("kind", "string"))
                if suggestion is not None:
                    source = "column_kind"
                else:
                    suggestion = SuggestedPolicy()

        policy = suggestion.model_dump()
        if policy["is_quasi_identifier"] is None:
            policy["is_quasi_identifier"] = _default_qi(col, pii)

        dp_params = dict(policy.get("dp_params") or {})
        if policy["action"] == "dp_laplace":
            dp_params.setdefault("epsilon", get_config().default_epsilon)
            if "min" in col and col["min"] is not None:
                dp_params.setdefault("lower", float(col["min"]))
            if "max" in col and col["max"] is not None:
                dp_params.setdefault("upper", float(col["max"]))
        policy["dp_params"] = dp_params
        policy["source"] = source
        suggestions[name] = policy
    return suggestions
