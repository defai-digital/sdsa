"""Schema inference from a Polars DataFrame."""
from __future__ import annotations

from typing import Literal

import polars as pl

ColumnKind = Literal["string", "numeric", "categorical", "datetime", "boolean"]

CATEGORICAL_CARDINALITY_RATIO = 0.05  # <=5% unique values on a non-numeric col => categorical
CATEGORICAL_ABS_MAX = 100


def infer_column_kind(series: pl.Series) -> ColumnKind:
    dtype = series.dtype
    if dtype == pl.Boolean:
        return "boolean"
    if dtype.is_numeric():
        return "numeric"
    if dtype in (pl.Date, pl.Datetime, pl.Time):
        return "datetime"
    # String-ish: decide categorical vs string by cardinality
    n = series.len()
    if n == 0:
        return "string"
    n_unique = series.n_unique()
    if n_unique <= CATEGORICAL_ABS_MAX and n_unique / max(n, 1) <= CATEGORICAL_CARDINALITY_RATIO:
        return "categorical"
    return "string"


def infer_schema(df: pl.DataFrame) -> list[dict]:
    schema = []
    for col in df.columns:
        series = df[col]
        kind = infer_column_kind(series)
        info = {
            "name": col,
            "dtype": str(series.dtype),
            "kind": kind,
            "n_unique": int(series.n_unique()),
            "null_count": int(series.null_count()),
            "row_count": int(series.len()),
        }
        if kind == "numeric":
            info["min"] = _scalar(series.min())
            info["max"] = _scalar(series.max())
        schema.append(info)
    return schema


def _scalar(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
