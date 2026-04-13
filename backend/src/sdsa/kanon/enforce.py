"""k-anonymity enforcement via suppression (ADR-0006).

This is the simple, auditable variant: group by quasi-identifier columns,
drop rows belonging to equivalence classes smaller than k. No optimal
generalization — that's a Phase 2/3 upgrade (Mondrian, Incognito).
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass
class KAnonResult:
    df: pl.DataFrame
    k_achieved: int
    rows_total: int
    rows_suppressed: int
    suppression_ratio: float
    classes_total: int
    classes_below_k: int


def enforce_k(
    df: pl.DataFrame,
    qi_columns: list[str],
    k: int,
) -> KAnonResult:
    if k < 2:
        raise ValueError("k must be >= 2")
    rows_total = df.height
    if not qi_columns or rows_total == 0:
        # No QIs → no k-anon applied; k_achieved is rows_total (trivially satisfied)
        return KAnonResult(df, rows_total or 0, rows_total, 0, 0.0, 0, 0)

    missing = [c for c in qi_columns if c not in df.columns]
    if missing:
        raise ValueError(f"QI columns not in dataframe: {missing}")

    class_sizes = df.group_by(qi_columns).len().rename({"len": "_cls_size"})
    joined = df.join(class_sizes, on=qi_columns, how="left")
    kept = joined.filter(pl.col("_cls_size") >= k).drop("_cls_size")

    suppressed = rows_total - kept.height
    classes_total = class_sizes.height
    classes_below_k = class_sizes.filter(pl.col("_cls_size") < k).height

    if kept.height == 0:
        k_achieved = 0
    else:
        # achieved = min equivalence-class size among surviving rows
        kept_class_sizes = kept.group_by(qi_columns).len()
        k_achieved = int(kept_class_sizes["len"].min() or 0)

    return KAnonResult(
        df=kept,
        k_achieved=k_achieved,
        rows_total=rows_total,
        rows_suppressed=suppressed,
        suppression_ratio=suppressed / rows_total if rows_total else 0.0,
        classes_total=classes_total,
        classes_below_k=classes_below_k,
    )
