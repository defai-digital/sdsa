from __future__ import annotations

import polars as pl
import pytest

from sdsa.anonymize.policy import ColumnPolicy, PolicyApplicationError
from sdsa.preflight import PreflightRequest, preflight_k_anonymity


def test_preflight_flags_high_suppression_and_drop_one_relief():
    df = pl.DataFrame({
        "city": (["A"] * 30) + (["B"] * 30),
        "zip": [f"{10000 + i}" for i in range(60)],
        "tier": (["gold"] * 15) + (["silver"] * 15) + (["gold"] * 15) + (["silver"] * 15),
    })
    req = PreflightRequest(
        policies=[
            ColumnPolicy(column="city", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="tier", action="retain", is_quasi_identifier=True),
        ],
        k=5,
    )
    out = preflight_k_anonymity(df, req, b"\x00" * 32)
    assert out["within_suppression_cap"] is False
    assert out["within_hard_suppression_cap"] is False
    assert out["worst_qi_by_cardinality"][0]["column"] == "zip"
    assert out["drop_one_qi_impacts"][0]["column"] == "zip"
    assert out["drop_one_qi_impacts"][0]["improvement"] > 0
    assert out["greedy_drop_plan"]["steps"][0]["column"] == "zip"
    assert out["greedy_drop_plan"]["reaches_target"] is True


def test_preflight_rejects_deterministic_mode_with_dp():
    df = pl.DataFrame({"salary": [10, 11, 12, 13, 14]})
    req = PreflightRequest(
        policies=[ColumnPolicy(column="salary", action="dp_laplace", is_quasi_identifier=True)],
        k=2,
        dp_params={"salary": {"epsilon": 1.0, "lower": 0, "upper": 20}},
        deterministic_key_name="shared-key",
    )
    try:
        preflight_k_anonymity(df, req, b"\x00" * 32)
    except ValueError as e:
        assert "Deterministic mode cannot be combined with DP" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_preflight_skips_non_qi_transforms():
    """Regression: preflight used to apply every policy (hash, mask, tokenize)
    regardless of whether the column was a QI. k-anonymity only reads QI
    columns, so only QI-column transforms should be applied. Verify the
    result is consistent when the non-QI policy would otherwise rewrite
    values."""
    import polars as pl
    from sdsa.anonymize.policy import ColumnPolicy
    from sdsa.preflight import PreflightRequest, preflight_k_anonymity

    df = pl.DataFrame({
        "email": [f"u{i}@x.com" for i in range(20)],
        "dept": ["A"] * 10 + ["B"] * 10,
    })
    # email is hashed (non-QI); dept is QI. Only dept values affect k-anon.
    policies = [
        ColumnPolicy(column="email", action="hash"),
        ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
    ]
    req = PreflightRequest(policies=policies, k=5)
    result = preflight_k_anonymity(df, req, b"\x00" * 32)
    # Two classes of size 10 each → no suppression at k=5.
    assert result["suppression_ratio"] == 0.0
    assert result["k_achieved_if_processed"] == 10


def test_greedy_drop_plan_can_find_multi_step_relief():
    rows = []
    for city in ["A", "B"]:
        for tier in ["gold", "silver"]:
            for i in range(28):
                rows.append({
                    "city": city,
                    "tier": tier,
                    "team": f"t{i % 7}",
                    "level": f"l{i % 8}",
                })
    df = pl.DataFrame(rows)
    req = PreflightRequest(
        policies=[
            ColumnPolicy(column="city", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="tier", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="team", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="level", action="retain", is_quasi_identifier=True),
        ],
        k=5,
    )

    out = preflight_k_anonymity(df, req, b"\x00" * 32)

    assert out["suppression_ratio"] == 1.0
    assert out["drop_one_qi_impacts"][0]["improvement"] == 0.0
    plan = out["greedy_drop_plan"]
    assert plan["reaches_target"] is True
    assert [step["column"] for step in plan["steps"]] == ["level", "team"]
    assert plan["final_suppression_ratio"] == 0.0


def test_preflight_rejects_incomplete_dp_config():
    df = pl.DataFrame({
        "salary": list(range(100)),
        "dept": ["A"] * 50 + ["B"] * 50,
    })
    req = PreflightRequest(
        policies=[
            ColumnPolicy(column="salary", action="dp_laplace", is_quasi_identifier=True),
            ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
        ],
        k=5,
        dp_params={},
    )
    with pytest.raises(PolicyApplicationError):
        preflight_k_anonymity(df, req, b"\x00" * 32)


def test_preflight_rejects_invalid_dp_bounds():
    df = pl.DataFrame({"salary": list(range(100)), "dept": ["A"] * 100})
    req = PreflightRequest(
        policies=[
            ColumnPolicy(column="salary", action="dp_laplace", is_quasi_identifier=True),
            ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
        ],
        k=5,
        dp_params={"salary": {"epsilon": 1.0, "lower": 100, "upper": 50}},
    )
    with pytest.raises(PolicyApplicationError):
        preflight_k_anonymity(df, req, b"\x00" * 32)
