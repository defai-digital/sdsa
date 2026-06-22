"""k-anonymity (+ optional distinct l-diversity) enforcement via suppression.

ADR-0006. This is the simple, auditable variant: group by quasi-identifier
columns, drop rows belonging to equivalence classes that fail the privacy
constraint. No optimal generalization — that's a Phase 2/3 upgrade (Mondrian,
Incognito).

k-anonymity alone bounds *identity* disclosure (re-identification) but not
*attribute* disclosure: if every row in an equivalence class shares the same
value of a sensitive ("label") column, an attacker learns that value for every
member without singling anyone out (the homogeneity attack). To counter this we
also measure, and optionally enforce, distinct l-diversity over caller-declared
sensitive columns: a class is only released if it has at least `l` distinct
values in each sensitive column.
"""
from __future__ import annotations

from dataclasses import dataclass, field

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
    # l-diversity metrics, measured over classes that satisfy k (i.e. the
    # classes that would be released under k-anonymity alone). Empty when no
    # sensitive columns are declared.
    sensitive_columns: list[str] = field(default_factory=list)
    l_target: int = 1
    l_achieved: dict[str, int] = field(default_factory=dict)
    homogeneous_classes: dict[str, int] = field(default_factory=dict)
    classes_below_l: int = 0


def _unique_col_name(base: str, taken: set[str]) -> str:
    name = base
    while name in taken:
        name += "_"
    return name


def enforce_k(
    df: pl.DataFrame,
    qi_columns: list[str],
    k: int,
    *,
    sensitive_columns: list[str] | None = None,
    l: int = 1,
) -> KAnonResult:
    if k < 2:
        raise ValueError("k must be >= 2")
    if l < 1:
        raise ValueError("l must be >= 1")

    # Sensitive columns must exist and cannot be QIs: a QI has exactly one
    # distinct value per equivalence class by construction, so "diversity" on it
    # is meaningless and would suppress everything once l >= 2.
    qi_set = set(qi_columns)
    sensitive = [
        c for c in dict.fromkeys(sensitive_columns or [])
        if c in df.columns and c not in qi_set
    ]

    rows_total = df.height
    if not qi_columns:
        return KAnonResult(
            df, rows_total or 0, rows_total, 0, 0.0, 0, 0,
            sensitive_columns=sensitive, l_target=l,
        )

    missing = [c for c in qi_columns if c not in df.columns]
    if missing:
        raise ValueError(f"QI columns not in dataframe: {missing}")

    if rows_total == 0:
        return KAnonResult(
            df, 0, 0, 0, 0.0, 0, 0,
            sensitive_columns=sensitive, l_target=l,
        )

    # group_by treats all NULL QI values as one group, so we must match NULLs
    # in the join too — otherwise NULL-keyed rows get silently suppressed even
    # when their equivalence class is large enough. Polars renamed
    # `join_nulls` to `nulls_equal` in 1.24; accept either.
    #
    # Pick column names that cannot collide with user data.
    taken = set(df.columns)
    size_col = _unique_col_name("_sdsa_cls_size", taken)
    taken.add(size_col)
    div_cols: dict[str, str] = {}
    for c in sensitive:
        name = _unique_col_name(f"_sdsa_div_{c}", taken)
        div_cols[c] = name
        taken.add(name)

    aggs = [pl.len().alias(size_col)]
    aggs += [pl.col(c).n_unique().alias(div_cols[c]) for c in sensitive]
    class_stats = df.group_by(qi_columns).agg(aggs)

    def _join(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
        try:
            return left.join(right, on=qi_columns, how="left", nulls_equal=True)
        except TypeError:
            return left.join(right, on=qi_columns, how="left", join_nulls=True)

    joined = _join(df, class_stats)

    # Survival predicate: class meets k, and meets l on every sensitive column.
    # When l == 1 the diversity terms are always true (a non-empty class has at
    # least one distinct value), so behaviour matches plain k-anonymity.
    keep_pred = pl.col(size_col) >= k
    for c in sensitive:
        keep_pred = keep_pred & (pl.col(div_cols[c]) >= l)

    kept_with_sizes = joined.filter(keep_pred)
    kept = kept_with_sizes.drop([size_col, *div_cols.values()])

    suppressed = rows_total - kept.height
    classes_total = class_stats.height
    classes_below_k = class_stats.filter(pl.col(size_col) < k).height

    # Measure l-diversity over the classes that satisfy k (what k-anonymity
    # alone would release), so the report can flag attribute disclosure even
    # when l-diversity is not being enforced (l == 1).
    k_surviving = class_stats.filter(pl.col(size_col) >= k)
    l_achieved: dict[str, int] = {}
    homogeneous_classes: dict[str, int] = {}
    below_l_pred = pl.lit(False)
    for c in sensitive:
        col = div_cols[c]
        l_achieved[c] = int(k_surviving[col].min() or 0) if k_surviving.height else 0
        homogeneous_classes[c] = k_surviving.filter(pl.col(col) == 1).height
        below_l_pred = below_l_pred | (pl.col(col) < l)
    classes_below_l = (
        k_surviving.filter(below_l_pred).height if sensitive and l >= 2 else 0
    )

    if kept.height == 0:
        k_achieved = 0
    else:
        k_achieved = int(kept_with_sizes[size_col].min() or 0)

    return KAnonResult(
        df=kept,
        k_achieved=k_achieved,
        rows_total=rows_total,
        rows_suppressed=suppressed,
        suppression_ratio=suppressed / rows_total if rows_total else 0.0,
        classes_total=classes_total,
        classes_below_k=classes_below_k,
        sensitive_columns=sensitive,
        l_target=l,
        l_achieved=l_achieved,
        homogeneous_classes=homogeneous_classes,
        classes_below_l=classes_below_l,
    )
