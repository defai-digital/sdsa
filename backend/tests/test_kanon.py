from __future__ import annotations

import polars as pl

from sdsa.kanon.enforce import enforce_k


def test_suppresses_classes_below_k():
    df = pl.DataFrame({
        "zip": ["10001", "10001", "10001", "10002", "20003"],
        "age_bin": ["20s", "20s", "20s", "30s", "40s"],
        "salary": [50000, 52000, 51000, 70000, 90000],
    })
    res = enforce_k(df, qi_columns=["zip", "age_bin"], k=3)
    assert res.df.height == 3
    assert res.k_achieved == 3
    assert res.rows_suppressed == 2
    assert res.classes_below_k == 2


def test_k_of_1_equivalent_to_no_suppression():
    df = pl.DataFrame({"a": [1, 2, 3], "b": [1, 2, 3]})
    res = enforce_k(df, qi_columns=["a"], k=2)
    # All classes size 1 → all suppressed
    assert res.df.height == 0


def test_no_qi_columns_returns_input():
    df = pl.DataFrame({"a": [1, 2, 3]})
    res = enforce_k(df, qi_columns=[], k=5)
    assert res.df.height == 3
    assert res.rows_suppressed == 0


def test_null_qi_rows_are_not_silently_dropped():
    """Regression: rows with NULL in a QI column used to be suppressed even
    when their NULL equivalence class was large enough to satisfy k."""
    df = pl.DataFrame({
        "zip":   [None, None, None, None, None, "10001", "10001", "10001"],
        "sal":   [50, 55, 60, 65, 70, 80, 85, 90],
    })
    # 5 rows with zip=None form one class; 3 rows with zip=10001 form another.
    # At k=4: the NULL class qualifies; the "10001" class does not.
    res = enforce_k(df, qi_columns=["zip"], k=4)
    assert res.df.height == 5
    assert set(res.df["zip"].to_list()) == {None}
    assert res.rows_suppressed == 3
