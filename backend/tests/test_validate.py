from __future__ import annotations

import math

import polars as pl

from sdsa.validate.metrics import _histogram, _numeric_stats, build_utility_summary


def test_histogram_excludes_nan_values():
    s = pl.Series("val", [1.0, 2.0, float("nan"), 3.0, 4.0])
    hist = _histogram(s)
    assert sum(hist["counts"]) == 4


def test_numeric_stats_do_not_emit_nan():
    s = pl.Series("val", [1.0, 2.0, float("nan"), 3.0, 4.0])
    stats = _numeric_stats(s)
    assert all(v is None or math.isfinite(v) for k, v in stats.items() if k != "null_ratio")


def test_utility_summary_scores_retention_and_fidelity():
    after = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "x", "y"]})
    schema = [
        {"name": "a", "n_unique": 5},
        {"name": "b", "n_unique": 4},
        {"name": "c", "n_unique": 3},  # dropped — not present in `after`
    ]
    policies = [
        {"column": "a", "action": "retain"},
        {"column": "b", "action": "mask"},
        {"column": "c", "action": "drop"},
    ]
    u = build_utility_summary(schema, after, policies, {}, rows_before=5, rows_after=3)

    assert u["rows_before"] == 5 and u["rows_after"] == 3
    assert u["columns_dropped"] == ["c"]
    assert u["columns_total"] == 3 and u["columns_kept"] == 2

    fid = {c["column"]: c["fidelity"] for c in u["columns"]}
    assert fid["a"] == 1.0          # retained
    assert fid["b"] == 0.5          # mask: distinct retention 2/4
    assert fid["c"] == 0.0          # dropped
    # 100 * (3/5) * (2/3) * mean(1.0, 0.5)
    assert u["overall_score"] == 30.0


def test_utility_summary_dp_fidelity_uses_declared_bounds_only():
    after = pl.DataFrame({"salary": [100.0, 200.0, 300.0]})
    schema = [{"name": "salary", "n_unique": 3}]
    policies = [{"column": "salary", "action": "dp_laplace"}]
    dp = {"salary": {"epsilon": 1.0, "lower": 0.0, "upper": 100.0}}

    u = build_utility_summary(schema, after, policies, dp, rows_before=3, rows_after=3)
    col = u["columns"][0]

    assert col["disposition"] == "noised"
    assert col["noise_to_range"] == 1.0   # 1 / epsilon
    assert col["fidelity"] == 0.5         # 1 / (1 + noise_to_range)
    # DP fidelity must not depend on the released values' distribution.
    assert "before" not in col


def test_utility_summary_empty_schema_is_safe():
    u = build_utility_summary([], pl.DataFrame({"a": [1]}), [], {}, 1, 1)
    assert u["overall_score"] == 0.0
    assert u["columns"] == []
