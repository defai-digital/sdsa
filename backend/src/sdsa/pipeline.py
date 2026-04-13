"""End-to-end pipeline orchestration.

Order:
  1. apply non-DP policies (mask/hash/tokenize/redact/generalize/drop)
  2. apply DP Laplace where configured
  3. enforce k-anonymity over the declared QI columns
  4. compute before/after validation
  5. build privacy report
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from .anonymize.policy import ColumnPolicy, PolicyApplicationError, apply_policy
from .core.config import get_config
from .dp.accountant import Accountant
from .dp.laplace import LaplaceParams, apply_laplace
from .kanon.enforce import enforce_k
from .report import build_report
from .validate.metrics import build_validation


class ProcessRequest(BaseModel):
    policies: list[ColumnPolicy]
    k: int = Field(default=5, ge=2, le=1000)
    dp_params: dict[str, dict] = Field(default_factory=dict)
    # dp_params: {column_name: {"epsilon": float, "lower": float, "upper": float}}
    deterministic_key_name: str | None = None
    accept_weaker_guarantee: bool = False


@dataclass
class ProcessResult:
    df: pl.DataFrame
    report: dict[str, Any]


class PipelineError(ValueError):
    pass


def _qi_cardinality_report(df: pl.DataFrame, qi_cols: list[str]) -> str:
    """Return a short human-readable summary of per-QI cardinality, worst first."""
    rows: list[tuple[str, int, int]] = []
    n = df.height
    for c in qi_cols:
        if c in df.columns:
            rows.append((c, int(df[c].n_unique()), n))
    rows.sort(key=lambda r: r[1], reverse=True)
    parts = [f"'{c}' ({u}/{n} unique)" for c, u, _ in rows]
    return ", ".join(parts) if parts else "(none)"


def _zero_rows_message(df: pl.DataFrame, qi_cols: list[str], k: int) -> str:
    if not qi_cols:
        return (
            f"k-anonymity enforcement produced zero rows with k={k} "
            f"but no QI columns were declared. This indicates an internal "
            f"error — please report."
        )
    return (
        f"All {df.height} rows were suppressed: no equivalence class of "
        f"size >= k={k} exists under the chosen QIs. "
        f"QI columns by cardinality (worst first): "
        f"{_qi_cardinality_report(df, qi_cols)}. "
        f"Fix by (a) unchecking high-cardinality QIs, "
        f"(b) generalizing them further (broader bins, year-only dates, "
        f"shorter string prefixes), or (c) lowering k."
    )


def _high_suppression_message(
    df: pl.DataFrame, qi_cols: list[str], k: int,
    suppression: float, cap: float,
) -> str:
    return (
        f"k={k} requires suppressing {suppression:.1%} of rows "
        f"(cap: {cap:.0%}). "
        f"QI columns by cardinality (worst first): "
        f"{_qi_cardinality_report(df, qi_cols)}. "
        f"Reduce suppression by unchecking high-cardinality QIs or "
        f"generalizing them further. "
        f"Set accept_weaker_guarantee=true only if partial loss is acceptable "
        f"(zero-row output will still be refused)."
    )


def _hard_suppression_message(
    df: pl.DataFrame, qi_cols: list[str], k: int,
    suppression: float, cap: float,
) -> str:
    return (
        f"k={k} would suppress {suppression:.1%} of rows, exceeding the hard "
        f"utility cap of {cap:.0%}. "
        f"QI columns by cardinality (worst first): "
        f"{_qi_cardinality_report(df, qi_cols)}. "
        f"This output is refused even with accept_weaker_guarantee=true. "
        f"Reduce the QI set, generalize high-cardinality fields, or lower k."
    )


def run_pipeline(
    original: pl.DataFrame,
    request: ProcessRequest,
    session_id: str,
    hmac_key: bytes,
    schema: list[dict],
    pii_suggestions: dict[str, dict],
) -> ProcessResult:
    cfg = get_config()
    df = original.clone()
    accountant = Accountant()
    policies_applied: list[dict] = []

    dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
    if request.deterministic_key_name and dp_columns:
        raise PipelineError(
            "Deterministic mode cannot be combined with DP columns (ADR-0008)."
        )

    # 1. non-DP transforms
    for p in request.policies:
        try:
            df = apply_policy(df, p, hmac_key)
        except PolicyApplicationError as e:
            raise PipelineError(str(e)) from e
        policies_applied.append({
            "column": p.column,
            "action": p.action,
            "params": p.params,
            "is_quasi_identifier": p.is_quasi_identifier,
        })

    # 2. DP pass
    for col in dp_columns:
        if col not in df.columns:
            continue
        params = request.dp_params.get(col)
        if not params or "epsilon" not in params:
            raise PipelineError(
                f"DP requested for column '{col}' without epsilon/bounds"
            )
        try:
            eps = float(params["epsilon"])
        except (TypeError, ValueError) as e:
            raise PipelineError(f"epsilon for '{col}' must be numeric") from e
        if not (cfg.epsilon_min <= eps <= cfg.epsilon_max):
            raise PipelineError(
                f"epsilon for '{col}' ({eps}) outside allowed range "
                f"[{cfg.epsilon_min}, {cfg.epsilon_max}]"
            )
        if "lower" not in params or "upper" not in params:
            raise PipelineError(
                f"DP column '{col}' needs declared bounds (lower, upper)"
            )
        try:
            lp = LaplaceParams(
                epsilon=eps,
                lower=float(params["lower"]),
                upper=float(params["upper"]),
            )
        except (TypeError, ValueError) as e:
            raise PipelineError(f"DP bounds for '{col}' must be numeric") from e
        try:
            noised = apply_laplace(df[col], lp)
        except ValueError as e:
            raise PipelineError(f"invalid DP params for '{col}': {e}") from e
        df = df.with_columns(noised.alias(col))
        accountant.charge(col, eps)

    # 3. k-anonymity
    qi_cols = [p.column for p in request.policies
               if p.is_quasi_identifier and p.column in df.columns]
    k_result = enforce_k(df, qi_cols, request.k)

    # Always refuse zero-row output — an empty dataset is never a useful result,
    # regardless of the accept_weaker_guarantee flag.
    if k_result.df.height == 0:
        raise PipelineError(_zero_rows_message(df, qi_cols, request.k))

    if k_result.suppression_ratio > cfg.hard_max_suppression_ratio:
        raise PipelineError(_hard_suppression_message(
            df, qi_cols, request.k, k_result.suppression_ratio,
            cfg.hard_max_suppression_ratio,
        ))

    if (k_result.suppression_ratio > cfg.max_suppression_ratio
            and not request.accept_weaker_guarantee):
        raise PipelineError(_high_suppression_message(
            df, qi_cols, request.k, k_result.suppression_ratio,
            cfg.max_suppression_ratio,
        ))
    df = k_result.df

    # 4. validation
    validation = build_validation(original, df)

    # 5. report
    kanon_report = {
        "k_target": request.k,
        "k_achieved": k_result.k_achieved,
        "rows_total": k_result.rows_total,
        "rows_suppressed": k_result.rows_suppressed,
        "suppression_ratio": k_result.suppression_ratio,
        "classes_total": k_result.classes_total,
        "classes_below_k": k_result.classes_below_k,
        "qi_columns": qi_cols,
    }
    report = build_report(
        session_id=session_id,
        schema=schema,
        pii_suggestions=pii_suggestions,
        policies_applied=policies_applied,
        dp_spent=accountant.snapshot(),
        kanon=kanon_report,
        validation=validation,
        deterministic_key_name=request.deterministic_key_name,
    )
    return ProcessResult(df=df, report=report)
