from __future__ import annotations

import polars as pl

from sdsa.anonymize.policy import ColumnPolicy
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
