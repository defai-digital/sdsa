"""Utility metrics: before/after comparison.

Computes per-column univariate stats plus numeric pairwise correlation.
Histograms use fixed 10 bins on numeric columns.
"""
from __future__ import annotations

from typing import Any

import math
import polars as pl


def _clean_numeric(s: pl.Series) -> pl.Series:
    clean = s.drop_nulls()
    if clean.dtype.is_float():
        clean = clean.filter(~clean.is_nan())
    return clean


def _numeric_stats(s: pl.Series) -> dict[str, Any]:
    clean = _clean_numeric(s)
    if s.len() == 0 or clean.len() == 0:
        return {"mean": None, "std": None, "min": None, "max": None, "null_ratio": 1.0}
    return {
        "mean": _f(clean.mean()),
        "std": _f(clean.std()),
        "min": _f(clean.min()),
        "max": _f(clean.max()),
        "null_ratio": s.null_count() / s.len(),
    }


def _histogram(s: pl.Series, bins: int = 10) -> dict[str, Any]:
    clean = _clean_numeric(s)
    if clean.len() == 0:
        return {"edges": [], "counts": []}
    lo = float(clean.min())
    hi = float(clean.max())
    if lo == hi:
        return {"edges": [lo, hi], "counts": [clean.len()]}
    hist = clean.cast(pl.Float64).hist(bin_count=bins)
    return {
        "edges": [lo] + [float(v) for v in hist["breakpoint"].to_list()],
        "counts": [int(v) for v in hist["count"].to_list()],
    }


def _categorical_stats(s: pl.Series) -> dict[str, Any]:
    n = s.len()
    return {
        "cardinality": int(s.drop_nulls().n_unique()),
        "null_ratio": s.null_count() / n if n else 1.0,
    }


def _f(v):
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def compare_column(name: str, before: pl.Series, after: pl.Series | None) -> dict[str, Any]:
    report: dict[str, Any] = {"column": name}
    if before.dtype.is_numeric():
        report["kind"] = "numeric"
        report["before"] = _numeric_stats(before)
        report["before_histogram"] = _histogram(before)
        if after is not None and after.dtype.is_numeric():
            report["after"] = _numeric_stats(after)
            report["after_histogram"] = _histogram(after)
        elif after is not None:
            # e.g., numeric column was binned into strings
            report["after"] = _categorical_stats(after)
            report["after_kind"] = "categorical"
    else:
        report["kind"] = "categorical"
        report["before"] = _categorical_stats(before)
        if after is not None:
            if after.dtype.is_numeric():
                report["after"] = _numeric_stats(after)
            else:
                report["after"] = _categorical_stats(after)
    if after is None:
        report["dropped"] = True
    return report


# --- utility (information-loss) summary --------------------------------------
#
# A scalar summary of how much analytic value the sanitization removed. It is
# built from source-side metadata, then build_report strips exact source-side
# counts before export. DP fidelity is derived from operator-declared bounds and
# epsilon, not from the data distribution.

# Fidelity weights for transforms that fully obscure a value. hash/tokenize keep
# rows joinable (equality is preserved) but the value itself is opaque; redact
# destroys the value outright. These are deliberate, documented heuristics — the
# utility score is an information-loss *proxy*, not a formal metric.
_JOINABLE_FIDELITY = 0.3
_REDACT_FIDELITY = 0.0
_GENERALIZE_ACTIONS = frozenset({"mask", "numeric_bin", "date_truncate", "string_truncate"})


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _dp_fidelity(entry: dict[str, Any], params: dict[str, Any]) -> float:
    """Fidelity of a DP-noised numeric column from declared bounds + epsilon.

    Laplace scale b = sensitivity/epsilon where sensitivity = upper - lower.
    The noise-to-range ratio is b / range = 1/epsilon; fidelity decays as
    1/(1+noise_to_range) so larger epsilon (less noise) scores higher. Uses
    only operator-declared values, so it never leaks the true distribution.
    """
    try:
        eps = float(params["epsilon"])
        lo = float(params["lower"])
        hi = float(params["upper"])
    except (KeyError, TypeError, ValueError):
        return 0.5
    rng = hi - lo
    if rng <= 0.0 or eps <= 0.0:
        return 0.0
    noise_scale = rng / eps
    noise_to_range = noise_scale / rng
    entry["noise_scale"] = round(noise_scale, 6)
    entry["noise_to_range"] = round(noise_to_range, 6)
    return 1.0 / (1.0 + noise_to_range)


def build_utility_summary(
    schema: list[dict],
    after_df: pl.DataFrame,
    policies_applied: list[dict],
    dp_params: dict[str, dict],
    rows_before: int,
    rows_after: int,
) -> dict[str, Any]:
    """Summarize information loss between the original and released data.

    `schema` describes the *original* columns (name + n_unique, as inferred at
    upload). `after_df` is the released frame. Exact source-side helper fields
    are removed by the report builder before export.
    """
    actions = {p["column"]: p.get("action", "retain") for p in policies_applied}
    row_retention = (rows_after / rows_before) if rows_before else 0.0

    columns: list[dict[str, Any]] = []
    dropped: list[str] = []
    kept_fidelities: list[float] = []

    for col in schema:
        name = col["name"]
        action = actions.get(name, "retain")
        distinct_before = col.get("n_unique")
        entry: dict[str, Any] = {
            "column": name,
            "action": action,
            "distinct_before": distinct_before,
        }

        if name not in after_df.columns:
            dropped.append(name)
            entry.update(
                disposition="dropped", distinct_after=None,
                distinct_retention=0.0, fidelity=0.0,
            )
            columns.append(entry)
            continue

        distinct_after = int(after_df[name].n_unique())
        entry["distinct_after"] = distinct_after
        dret = _clamp01(distinct_after / distinct_before) if distinct_before else None
        entry["distinct_retention"] = round(dret, 4) if dret is not None else None

        if action == "retain":
            disposition, fidelity = "retained", 1.0
        elif action in _GENERALIZE_ACTIONS:
            disposition = "generalized"
            fidelity = dret if dret is not None else 0.5
        elif action in ("hash", "tokenize"):
            disposition, fidelity = "pseudonymized", _JOINABLE_FIDELITY
        elif action == "redact":
            disposition, fidelity = "redacted", _REDACT_FIDELITY
        elif action == "dp_laplace":
            disposition = "noised"
            fidelity = _dp_fidelity(entry, dp_params.get(name) or {})
        else:
            disposition = "transformed"
            fidelity = dret if dret is not None else 0.5

        entry["disposition"] = disposition
        entry["fidelity"] = round(_clamp01(fidelity), 4)
        kept_fidelities.append(entry["fidelity"])
        columns.append(entry)

    total_cols = len(schema)
    kept_cols = total_cols - len(dropped)
    column_retention = (kept_cols / total_cols) if total_cols else 0.0
    mean_fidelity = (sum(kept_fidelities) / len(kept_fidelities)) if kept_fidelities else 0.0
    overall = 100.0 * row_retention * column_retention * mean_fidelity

    return {
        "overall_score": round(overall, 1),
        "row_retention": round(row_retention, 4),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "column_retention": round(column_retention, 4),
        "columns_total": total_cols,
        "columns_kept": kept_cols,
        "columns_dropped": dropped,
        "mean_column_fidelity": round(mean_fidelity, 4),
        "columns": columns,
        "method_note": (
            "Heuristic utility proxy in [0,100]: "
            "100 x row_retention x column_retention x mean(kept-column fidelity). "
            "Per-column fidelity is 1.0 for retained columns, the surviving "
            "distinct-value ratio for generalized columns, 1/(1+noise/range) for "
            "DP-noised columns, 0.3 for hashed/tokenized (joinable but opaque), "
            "and 0 for redacted or dropped columns. It estimates analytic "
            "information loss and is not a formal guarantee."
        ),
    }


def correlation_matrix(df: pl.DataFrame) -> dict[str, dict[str, float | None]]:
    num_cols = [c for c in df.columns if df[c].dtype.is_numeric()]
    out: dict[str, dict[str, float | None]] = {}
    for a in num_cols:
        out[a] = {}
        for b in num_cols:
            try:
                val = pl.DataFrame({"a": df[a], "b": df[b]}) \
                        .drop_nulls().select(pl.corr("a", "b")).item()
                # Polars returns NaN when either column has zero variance
                # (e.g. all rows identical). NaN is not valid JSON, so
                # coerce to None — downstream consumers treat None as
                # "undefined / not computable".
                if val is None or math.isnan(val) or math.isinf(val):
                    out[a][b] = None
                else:
                    out[a][b] = float(val)
            except Exception:
                out[a][b] = None
    return out


_CORRELATION_SAMPLE = 10_000


def build_validation(before: pl.DataFrame, after: pl.DataFrame) -> dict[str, Any]:
    if after.height == 0:
        per_col = [compare_column(name, before[name], None) for name in before.columns]
        return {
            "columns": per_col,
            "correlation_before": correlation_matrix(before) if before.height > 0 else {},
            "correlation_after": {},
            "rows_before": before.height,
            "rows_after": 0,
        }
    per_col = []
    for name in before.columns:
        after_series = after[name] if name in after.columns else None
        per_col.append(compare_column(name, before[name], after_series))
    before_sample = before.sample(min(_CORRELATION_SAMPLE, before.height), seed=0) \
        if before.height > _CORRELATION_SAMPLE else before
    after_sample = after.sample(min(_CORRELATION_SAMPLE, after.height), seed=0) \
        if after.height > _CORRELATION_SAMPLE else after
    return {
        "columns": per_col,
        "correlation_before": correlation_matrix(before_sample),
        "correlation_after": correlation_matrix(after_sample),
        "rows_before": before.height,
        "rows_after": after.height,
    }
