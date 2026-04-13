"""Preflight utility estimation for candidate k-anonymity settings."""
from __future__ import annotations

from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from .anonymize.policy import ColumnPolicy, PolicyApplicationError, apply_policy
from .core.config import get_config
from .dp.laplace import LaplaceParams, apply_laplace
from .kanon.enforce import enforce_k


class PreflightRequest(BaseModel):
    policies: list[ColumnPolicy]
    k: int = Field(default=5, ge=2, le=1000)
    dp_params: dict[str, dict] = Field(default_factory=dict)
    deterministic_key_name: str | None = None


def _qi_cardinality(df: pl.DataFrame, qi_columns: list[str]) -> list[dict[str, Any]]:
    rows = []
    total = df.height
    for col in qi_columns:
        if col not in df.columns:
            continue
        rows.append({
            "column": col,
            "n_unique": int(df[col].n_unique()),
            "row_count": total,
        })
    rows.sort(key=lambda row: row["n_unique"], reverse=True)
    return rows


def _drop_one_impacts(df: pl.DataFrame, qi_columns: list[str], k: int) -> list[dict[str, Any]]:
    impacts = []
    if len(qi_columns) <= 1:
        return impacts
    base = enforce_k(df, qi_columns, k)
    for col in qi_columns:
        reduced = [c for c in qi_columns if c != col]
        result = enforce_k(df, reduced, k)
        impacts.append({
            "column": col,
            "suppression_ratio": result.suppression_ratio,
            "rows_suppressed": result.rows_suppressed,
            "improvement": base.suppression_ratio - result.suppression_ratio,
        })
    impacts.sort(key=lambda item: item["improvement"], reverse=True)
    return impacts


def preflight_k_anonymity(
    original: pl.DataFrame,
    request: PreflightRequest,
    hmac_key: bytes,
) -> dict[str, Any]:
    cfg = get_config()
    df = original.clone()

    dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
    if request.deterministic_key_name and dp_columns:
        raise PolicyApplicationError(
            "Deterministic mode cannot be combined with DP columns (ADR-0008)."
        )

    for policy in request.policies:
        df = apply_policy(df, policy, hmac_key)

    for col in dp_columns:
        if col not in df.columns:
            continue
        params = request.dp_params.get(col)
        if not params or "epsilon" not in params:
            raise PolicyApplicationError(
                f"DP requested for column '{col}' without epsilon/bounds"
            )
        try:
            eps = float(params["epsilon"])
        except (TypeError, ValueError) as e:
            raise PolicyApplicationError(f"epsilon for '{col}' must be numeric") from e
        if not (cfg.epsilon_min <= eps <= cfg.epsilon_max):
            raise PolicyApplicationError(
                f"epsilon for '{col}' ({eps}) outside allowed range "
                f"[{cfg.epsilon_min}, {cfg.epsilon_max}]"
            )
        if "lower" not in params or "upper" not in params:
            raise PolicyApplicationError(
                f"DP column '{col}' needs declared bounds (lower, upper)"
            )
        try:
            lp = LaplaceParams(
                epsilon=eps,
                lower=float(params["lower"]),
                upper=float(params["upper"]),
            )
        except (TypeError, ValueError) as e:
            raise PolicyApplicationError(f"DP bounds for '{col}' must be numeric") from e
        try:
            noised = apply_laplace(df[col], lp)
        except ValueError as e:
            raise PolicyApplicationError(f"invalid DP params for '{col}': {e}") from e
        df = df.with_columns(noised.alias(col))

    qi_columns = [p.column for p in request.policies if p.is_quasi_identifier and p.column in df.columns]
    result = enforce_k(df, qi_columns, request.k)
    worst = _qi_cardinality(df, qi_columns)
    drop_impacts = _drop_one_impacts(df, qi_columns, request.k)

    suggestions: list[str] = []
    if result.suppression_ratio > cfg.hard_max_suppression_ratio:
        suggestions.append(
            f"Estimated suppression exceeds the hard utility cap of "
            f"{cfg.hard_max_suppression_ratio:.0%}; processing will be refused."
        )
        if drop_impacts and drop_impacts[0]["improvement"] > 0:
            best = drop_impacts[0]
            suggestions.append(
                f"Uncheck or generalize '{best['column']}' first; estimated suppression drops to "
                f"{best['suppression_ratio']:.1%}."
            )
        if worst:
            suggestions.append(
                f"Highest-cardinality QI: '{worst[0]['column']}' "
                f"({worst[0]['n_unique']}/{worst[0]['row_count']} unique)."
            )
    elif result.suppression_ratio > cfg.max_suppression_ratio:
        if drop_impacts and drop_impacts[0]["improvement"] > 0:
            best = drop_impacts[0]
            suggestions.append(
                f"Uncheck or generalize '{best['column']}' first; estimated suppression drops to "
                f"{best['suppression_ratio']:.1%}."
            )
        if worst:
            suggestions.append(
                f"Highest-cardinality QI: '{worst[0]['column']}' "
                f"({worst[0]['n_unique']}/{worst[0]['row_count']} unique)."
            )
    elif qi_columns:
        suggestions.append(
            f"Estimated suppression is {result.suppression_ratio:.1%}, within the {cfg.max_suppression_ratio:.0%} cap."
        )

    return {
        "k": request.k,
        "qi_columns": qi_columns,
        "rows_total": result.rows_total,
        "rows_suppressed": result.rows_suppressed,
        "suppression_ratio": result.suppression_ratio,
        "classes_total": result.classes_total,
        "classes_below_k": result.classes_below_k,
        "k_achieved_if_processed": result.k_achieved,
        "within_suppression_cap": result.suppression_ratio <= cfg.max_suppression_ratio,
        "within_hard_suppression_cap": result.suppression_ratio <= cfg.hard_max_suppression_ratio,
        "suppression_cap": cfg.max_suppression_ratio,
        "hard_suppression_cap": cfg.hard_max_suppression_ratio,
        "worst_qi_by_cardinality": worst,
        "drop_one_qi_impacts": drop_impacts,
        "suggestions": suggestions,
    }
