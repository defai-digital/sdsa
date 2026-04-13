"""Utility metrics: before/after comparison.

Computes per-column univariate stats plus numeric pairwise correlation.
Histograms use fixed 10 bins on numeric columns.
"""
from __future__ import annotations

from typing import Any

import polars as pl


def _numeric_stats(s: pl.Series) -> dict[str, Any]:
    if s.len() == 0 or s.drop_nulls().len() == 0:
        return {"mean": None, "std": None, "min": None, "max": None, "null_ratio": 1.0}
    return {
        "mean": _f(s.mean()),
        "std": _f(s.std()),
        "min": _f(s.min()),
        "max": _f(s.max()),
        "null_ratio": s.null_count() / s.len(),
    }


def _histogram(s: pl.Series, bins: int = 10) -> dict[str, Any]:
    clean = s.drop_nulls()
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
        "cardinality": int(s.n_unique()),
        "null_ratio": s.null_count() / n if n else 1.0,
    }


def _f(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


def correlation_matrix(df: pl.DataFrame) -> dict[str, dict[str, float]]:
    num_cols = [c for c in df.columns if df[c].dtype.is_numeric()]
    out: dict[str, dict[str, float]] = {}
    for a in num_cols:
        out[a] = {}
        for b in num_cols:
            try:
                out[a][b] = float(pl.DataFrame({"a": df[a], "b": df[b]})
                                  .drop_nulls().select(pl.corr("a", "b")).item() or 0.0)
            except Exception:
                out[a][b] = 0.0
    return out


def build_validation(before: pl.DataFrame, after: pl.DataFrame) -> dict[str, Any]:
    per_col = []
    for name in before.columns:
        after_series = after[name] if name in after.columns else None
        per_col.append(compare_column(name, before[name], after_series))
    return {
        "columns": per_col,
        "correlation_before": correlation_matrix(before),
        "correlation_after": correlation_matrix(after),
        "rows_before": before.height,
        "rows_after": after.height,
    }
