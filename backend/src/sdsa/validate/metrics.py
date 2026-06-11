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
