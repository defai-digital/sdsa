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
            "n_unique": int(df[col].n_unique()),
            "suppression_ratio": result.suppression_ratio,
            "rows_suppressed": result.rows_suppressed,
            "improvement": base.suppression_ratio - result.suppression_ratio,
        })
    impacts.sort(key=lambda item: item["improvement"], reverse=True)
    return impacts


def _greedy_drop_plan(
    df: pl.DataFrame,
    qi_columns: list[str],
    k: int,
    target_cap: float,
) -> dict[str, Any] | None:
    if not qi_columns:
        return None

    current_qis = list(qi_columns)
    current_result = enforce_k(df, current_qis, k)
    if current_result.suppression_ratio <= target_cap:
        return None

    steps: list[dict[str, Any]] = []
    start_ratio = current_result.suppression_ratio

    while current_qis and current_result.suppression_ratio > target_cap:
        impacts = []
        for col in current_qis:
            reduced = [c for c in current_qis if c != col]
            result = enforce_k(df, reduced, k)
            impacts.append({
                "column": col,
                "n_unique": int(df[col].n_unique()),
                "suppression_ratio": result.suppression_ratio,
                "rows_suppressed": result.rows_suppressed,
                "improvement": current_result.suppression_ratio - result.suppression_ratio,
                "remaining_qi_columns": reduced,
            })

        impacts.sort(
            key=lambda item: (
                item["suppression_ratio"],
                -item["improvement"],
                -item["n_unique"],
                item["column"],
            )
        )
        best = impacts[0]
        steps.append({
            "column": best["column"],
            "n_unique": best["n_unique"],
            "suppression_ratio": best["suppression_ratio"],
            "rows_suppressed": best["rows_suppressed"],
            "remaining_qi_columns": best["remaining_qi_columns"],
        })
        current_qis = best["remaining_qi_columns"]
        current_result = enforce_k(df, current_qis, k)

    return {
        "target_cap": target_cap,
        "start_suppression_ratio": start_ratio,
        "final_suppression_ratio": current_result.suppression_ratio,
        "final_rows_suppressed": current_result.rows_suppressed,
        "remaining_qi_columns": current_qis,
        "reaches_target": current_result.suppression_ratio <= target_cap,
        "steps": steps,
    }


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

    # k-anonymity only inspects QI columns. Transforms and DP noise applied to
    # non-QI columns cannot change equivalence-class sizes, so we skip them.
    # This is what made preflight feel slow on large files — it was hashing
    # every email and tokenizing every identifier before running the only
    # operation that reads QI values.
    qi_names = {p.column for p in request.policies if p.is_quasi_identifier}

    for policy in request.policies:
        if policy.column not in qi_names:
            continue
        df = apply_policy(df, policy, hmac_key)

    for col in dp_columns:
        if col not in df.columns or col not in qi_names:
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
            lower = float(params["lower"])
            upper = float(params["upper"])
        except (TypeError, ValueError) as e:
            raise PolicyApplicationError(f"DP bounds for '{col}' must be numeric") from e
        try:
            noised = apply_laplace(df[col], LaplaceParams(eps, lower, upper))
        except ValueError as e:
            raise PolicyApplicationError(f"invalid DP params for '{col}': {e}") from e
        df = df.with_columns(noised.alias(col))

    qi_columns = [p.column for p in request.policies if p.is_quasi_identifier and p.column in df.columns]
    result = enforce_k(df, qi_columns, request.k)
    worst = _qi_cardinality(df, qi_columns)
    drop_impacts = _drop_one_impacts(df, qi_columns, request.k)
    target_cap = (
        cfg.hard_max_suppression_ratio
        if result.suppression_ratio > cfg.hard_max_suppression_ratio
        else cfg.max_suppression_ratio
    )
    greedy_drop_plan = _greedy_drop_plan(df, qi_columns, request.k, target_cap)

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

    if greedy_drop_plan and greedy_drop_plan["steps"]:
        plan_cols = ", ".join(f"'{step['column']}'" for step in greedy_drop_plan["steps"])
        if greedy_drop_plan["reaches_target"]:
            suggestions.append(
                f"Greedy QI plan: uncheck {plan_cols} to reach "
                f"{greedy_drop_plan['final_suppression_ratio']:.1%} suppression."
            )
        else:
            suggestions.append(
                f"Greedy QI plan: uncheck {plan_cols} to reduce suppression to "
                f"{greedy_drop_plan['final_suppression_ratio']:.1%}, but it still misses the cap."
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
        "greedy_drop_plan": greedy_drop_plan,
        "suggestions": suggestions,
    }
