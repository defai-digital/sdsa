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


def test_user_column_named_cls_size_does_not_collide():
    """Regression: enforce_k used a fixed internal column name '_cls_size'
    which would collide with any user-supplied column of that name and make
    the join raise. The fix uses a namespaced name and falls back to an
    alternative if the namespaced one is also taken."""
    df = pl.DataFrame({
        "dept":       ["A"] * 6 + ["B"] * 6,
        "_cls_size":  list(range(12)),        # user data happens to use this name
    })
    res = enforce_k(df, qi_columns=["dept"], k=5)
    assert res.df.height == 12
    # User's column must still be present and untouched.
    assert "_cls_size" in res.df.columns
    assert res.df["_cls_size"].to_list() == list(range(12))


def test_user_column_named_sdsa_cls_size_also_works():
    """Defense-in-depth: even the namespaced internal name shouldn't collide."""
    df = pl.DataFrame({
        "dept":           ["A"] * 6 + ["B"] * 6,
        "_sdsa_cls_size": list(range(12)),
    })
    res = enforce_k(df, qi_columns=["dept"], k=5)
    assert res.df.height == 12
    assert "_sdsa_cls_size" in res.df.columns


def _diversity_df():
    # zip=1: disease all 'flu' -> homogeneous (attribute disclosure)
    # zip=2: disease {flu, cold} -> diverse
    return pl.DataFrame({
        "zip":     ["1"] * 4 + ["2"] * 4,
        "disease": ["flu"] * 4 + ["flu", "cold", "cold", "flu"],
    })


def test_l_diversity_measured_without_enforcement():
    """l=1 enforces nothing but still reports homogeneity, so the user is warned
    that a cleartext column leaks via the homogeneity attack."""
    res = enforce_k(_diversity_df(), ["zip"], k=2, sensitive_columns=["disease"], l=1)
    assert res.df.height == 8  # nothing suppressed
    assert res.l_achieved["disease"] == 1  # worst class has a single value
    assert res.homogeneous_classes["disease"] == 1
    assert res.classes_below_l == 0  # not enforcing, so nothing is "below"


def test_l_diversity_suppresses_homogeneous_class():
    res = enforce_k(_diversity_df(), ["zip"], k=2, sensitive_columns=["disease"], l=2)
    assert set(res.df["zip"].to_list()) == {"2"}  # homogeneous zip=1 dropped
    assert res.df.height == 4
    assert res.classes_below_l == 1
    assert res.homogeneous_classes["disease"] == 1


def test_sensitive_column_that_is_a_qi_is_ignored():
    """Diversity on a grouping key is meaningless (always 1 distinct per class);
    it must not be treated as sensitive or everything would be suppressed."""
    df = pl.DataFrame({"zip": ["1"] * 4 + ["2"] * 4})
    res = enforce_k(df, ["zip"], k=2, sensitive_columns=["zip"], l=2)
    assert res.df.height == 8
    assert res.sensitive_columns == []


def test_l_must_be_at_least_one():
    import pytest
    with pytest.raises(ValueError):
        enforce_k(pl.DataFrame({"a": [1, 2]}), ["a"], k=2, l=0)
