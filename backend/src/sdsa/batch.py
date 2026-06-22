"""Headless batch sanitization — the same pipeline the web app runs, no server.

Used by the `sdsa process` / `sdsa-server process` CLI command so SDSA can run
inside CI/CD or data pipelines. A run reads one CSV/TXT/SQL file, applies a
process request (loaded from JSON or auto-derived from detection), and writes a
sanitized CSV plus JSON and Markdown privacy reports next to each other.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from .anonymize.policy import ColumnPolicy
from .core.config import get_config
from .detect.pii import detect_dataframe
from .detect.schema import infer_schema
from .ingest import parse_upload
from .pipeline import ProcessRequest, run_pipeline
from .policy_config import build_policy_suggestions
from .report import render_markdown


class BatchError(ValueError):
    """Raised for any user-facing batch failure (bad input, policy, pipeline)."""


@dataclass
class BatchResult:
    csv_path: Path
    report_json_path: Path
    report_md_path: Path
    report: dict[str, Any]
    rows_before: int
    rows_after: int


def _pii_to_dict(suggestions) -> dict[str, dict]:
    return {
        name: {"kind": s.kind, "confidence": round(s.confidence, 3), "reason": s.reason}
        for name, s in suggestions.items()
    }


def _detection_sample(df: pl.DataFrame, limit: int) -> pl.DataFrame:
    """Bounded sample for PII detection: both ends plus a deterministic middle.

    Mirrors the web upload path so headless and browser runs detect the same
    fields. PII concentrated only at the head or tail of a sorted file would be
    missed by a plain head sample.
    """
    if limit <= 0 or df.height <= limit:
        return df if limit > 0 else df.head(0)
    edge = max(1, limit // 3)
    head_count = min(edge, df.height)
    tail_count = min(edge, df.height - head_count)
    middle_budget = limit - head_count - tail_count
    parts = [df.head(head_count)]
    middle_len = df.height - head_count - tail_count
    if middle_budget > 0 and middle_len > 0:
        middle = df.slice(head_count, middle_len)
        parts.append(middle.sample(min(middle_budget, middle.height), seed=0))
    if tail_count > 0:
        parts.append(df.tail(tail_count))
    return pl.concat(parts)


def build_auto_request(
    schema: list[dict],
    pii_suggestions: dict[str, dict],
    *,
    k: int | None = None,
) -> ProcessRequest:
    """Derive a ProcessRequest from detection + the project policy catalog.

    This is the no-`--policy` default: every column gets its suggested action,
    quasi-identifier flag, and (for DP columns) epsilon/bounds.
    """
    cfg = get_config()
    suggestions = build_policy_suggestions(schema, pii_suggestions)
    policies: list[ColumnPolicy] = []
    dp_params: dict[str, dict] = {}
    for name, s in suggestions.items():
        action = s.get("action", "retain")
        policies.append(ColumnPolicy(
            column=name,
            action=action,
            params=dict(s.get("params") or {}),
            is_quasi_identifier=bool(s.get("is_quasi_identifier")),
        ))
        if action == "dp_laplace":
            dp_params[name] = dict(s.get("dp_params") or {})
    return ProcessRequest(policies=policies, k=k or cfg.default_k, dp_params=dp_params)


def load_request(path: Path) -> ProcessRequest:
    """Load a process request from a JSON file (same shape as POST /api/process)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise BatchError(f"policy file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise BatchError(f"policy file {path} is not valid JSON: {e}") from e
    try:
        return ProcessRequest.model_validate(data)
    except Exception as e:  # pydantic ValidationError and friends
        raise BatchError(f"invalid policy file {path}: {e}") from e


def process_file(
    input_path: str | Path,
    *,
    policy_path: str | Path | None = None,
    out_dir: str | Path = ".",
    k: int | None = None,
    accept_weaker_guarantee: bool = False,
    deterministic_key: str | None = None,
) -> BatchResult:
    """Run the full sanitization pipeline on one file and write the outputs."""
    input_path = Path(input_path)
    cfg = get_config()

    try:
        raw = input_path.read_bytes()
    except FileNotFoundError as e:
        raise BatchError(f"input file not found: {input_path}") from e
    if len(raw) > cfg.max_upload_bytes:
        raise BatchError(
            f"input file is {len(raw)} bytes, exceeding the max of "
            f"{cfg.max_upload_bytes} (set SDSA_MAX_UPLOAD_BYTES to raise it)"
        )

    from .ingest import ParseError
    try:
        parsed = parse_upload(input_path.name, raw)
    except ParseError as e:
        raise BatchError(str(e)) from e

    df = parsed.df
    schema = infer_schema(df)
    sample = _detection_sample(df, cfg.sample_rows_for_detection)
    pii = _pii_to_dict(detect_dataframe(sample))

    if policy_path is not None:
        request = load_request(Path(policy_path))
        if k is not None:
            request = request.model_copy(update={"k": k})
    else:
        request = build_auto_request(schema, pii, k=k)
    overrides: dict[str, Any] = {}
    if accept_weaker_guarantee:
        overrides["accept_weaker_guarantee"] = True
    if deterministic_key is not None:
        overrides["deterministic_key_name"] = deterministic_key
    if overrides:
        request = request.model_copy(update=overrides)

    hmac_key = secrets.token_bytes(32)
    from .pipeline import PipelineError
    from .anonymize.policy import PolicyApplicationError
    try:
        result = run_pipeline(
            original=df,
            request=request,
            session_id="cli-" + secrets.token_hex(8),
            hmac_key=hmac_key,
            schema=schema,
            pii_suggestions=pii,
            prior_dp_spent=None,
            epsilon_budget=cfg.epsilon_session_budget,
        )
    except (PipelineError, PolicyApplicationError) as e:
        raise BatchError(str(e)) from e

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    csv_path = out_dir / f"{stem}.sanitized.csv"
    json_path = out_dir / f"{stem}.report.json"
    md_path = out_dir / f"{stem}.report.md"

    result.df.write_csv(csv_path)
    json_path.write_text(json.dumps(result.report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result.report), encoding="utf-8")

    return BatchResult(
        csv_path=csv_path,
        report_json_path=json_path,
        report_md_path=md_path,
        report=result.report,
        rows_before=df.height,
        rows_after=result.df.height,
    )
