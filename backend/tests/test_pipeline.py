from __future__ import annotations

import polars as pl
import pytest

import sdsa.core.config as config_module
from sdsa.anonymize.policy import ColumnPolicy
from sdsa.pipeline import PipelineError, ProcessRequest, run_pipeline


def _sample_df():
    return pl.DataFrame({
        "email": [f"user{i}@example.com" for i in range(30)],
        "zip": (["10001"] * 10) + (["10002"] * 10) + (["10003"] * 10),
        "age": [25, 30, 35, 40, 45] * 6,
        "salary": [50000, 60000, 70000, 80000, 90000, 55000] * 5,
    })


def _policies(dp_on_salary: bool = False):
    return [
        ColumnPolicy(column="email", action="hash"),
        ColumnPolicy(column="zip", action="string_truncate",
                     params={"keep": 3}, is_quasi_identifier=True),
        ColumnPolicy(column="age", action="numeric_bin",
                     params={"bin_width": 10}, is_quasi_identifier=True),
        ColumnPolicy(column="salary",
                     action="dp_laplace" if dp_on_salary else "retain"),
    ]


def test_end_to_end_no_dp():
    df = _sample_df()
    req = ProcessRequest(policies=_policies(), k=5)
    res = run_pipeline(df, req, "s1", b"\x00" * 32, schema=[], pii_suggestions={})
    assert res.df.height > 0
    assert res.df.height <= df.height
    assert res.report["k_anonymity"]["k_achieved"] >= 5
    # email column was hashed → not the original values
    assert not any("@" in v for v in res.df["email"].to_list())


def test_dp_column_adds_noise():
    df = _sample_df()
    req = ProcessRequest(
        policies=_policies(dp_on_salary=True),
        k=5,
        dp_params={"salary": {"epsilon": 1.0, "lower": 40_000, "upper": 100_000}},
    )
    res = run_pipeline(df, req, "s2", b"\x00" * 32, schema=[], pii_suggestions={})
    # DP-spent should reflect salary
    assert res.report["privacy"]["mechanism_per_column"] == {"salary": 1.0}
    # Output salary should differ from input (noise added)
    after = res.df["salary"].to_list()
    # Pick any surviving row and confirm it's not an exact input value w.h.p.
    assert any(abs(v - int(v)) > 0 for v in after)


def test_deterministic_mode_rejects_dp_combination():
    df = _sample_df()
    req = ProcessRequest(
        policies=_policies(dp_on_salary=True),
        k=5,
        dp_params={"salary": {"epsilon": 1.0, "lower": 0, "upper": 100_000}},
        deterministic_key_name="test-key",
    )
    with pytest.raises(PipelineError):
        run_pipeline(df, req, "s3", b"\x00" * 32, schema=[], pii_suggestions={})


def test_suppression_cap_blocks_without_override():
    df = pl.DataFrame({
        "a": list(range(20)),  # all unique → all suppressed at k>=2
        "b": list(range(20)),
    })
    req = ProcessRequest(
        policies=[ColumnPolicy(column="a", action="retain", is_quasi_identifier=True)],
        k=5,
    )
    with pytest.raises(PipelineError):
        run_pipeline(df, req, "s4", b"\x00" * 32, schema=[], pii_suggestions={})


def test_zero_row_output_refused_even_with_override():
    # accept_weaker_guarantee lets you accept partial loss, but never zero rows.
    df = pl.DataFrame({"a": list(range(20))})
    req = ProcessRequest(
        policies=[ColumnPolicy(column="a", action="retain", is_quasi_identifier=True)],
        k=5,
        accept_weaker_guarantee=True,
    )
    with pytest.raises(PipelineError) as exc:
        run_pipeline(df, req, "s5", b"\x00" * 32, schema=[], pii_suggestions={})
    assert "zero" in str(exc.value).lower() or "suppressed" in str(exc.value).lower()


def test_suppression_cap_allows_partial_loss_with_override():
    # Mix of classes: some size >= k, some < k. Override lets us keep the ones that qualify.
    df = pl.DataFrame({
        "dept": (["A"] * 6) + (["B"] * 6) + ["C", "D"],  # A=6, B=6, C=1, D=1
    })
    req = ProcessRequest(
        policies=[ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True)],
        k=5,
        accept_weaker_guarantee=True,
    )
    res = run_pipeline(df, req, "s5b", b"\x00" * 32, schema=[], pii_suggestions={})
    assert res.df.height == 12  # A and B survive; C and D dropped


def test_hard_suppression_cap_refused_even_with_override():
    df = pl.DataFrame({
        "zip": ([10001] * 5) + [20000 + i for i in range(95)],
        "city": (["A"] * 50) + (["B"] * 50),
    })
    req = ProcessRequest(
        policies=[
            ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="city", action="retain", is_quasi_identifier=True),
        ],
        k=5,
        accept_weaker_guarantee=True,
    )
    with pytest.raises(PipelineError) as exc:
        run_pipeline(df, req, "s5hard", b"\x00" * 32, schema=[], pii_suggestions={})
    assert "hard utility cap" in str(exc.value)


def test_error_message_names_worst_qi_column():
    df = pl.DataFrame({"good": ["x"] * 20, "bad": list(range(20))})
    req = ProcessRequest(
        policies=[
            ColumnPolicy(column="good", action="retain", is_quasi_identifier=True),
            ColumnPolicy(column="bad", action="retain", is_quasi_identifier=True),
        ],
        k=5,
    )
    with pytest.raises(PipelineError) as exc:
        run_pipeline(df, req, "s5c", b"\x00" * 32, schema=[], pii_suggestions={})
    msg = str(exc.value)
    assert "'bad'" in msg and "20/20" in msg


def test_dp_epsilon_out_of_range():
    df = _sample_df()
    req = ProcessRequest(
        policies=_policies(dp_on_salary=True),
        k=5,
        dp_params={"salary": {"epsilon": 100.0, "lower": 0, "upper": 100_000}},
    )
    with pytest.raises(PipelineError):
        run_pipeline(df, req, "s6", b"\x00" * 32, schema=[], pii_suggestions={})


def test_dp_laplace_rejected_on_non_numeric_column():
    """Regression: applying action=dp_laplace to a string column used to
    crash inside map_elements with ValueError → 500. Now rejected with
    a clear PipelineError at the boundary."""
    import polars as pl
    from sdsa.anonymize.policy import ColumnPolicy
    from sdsa.pipeline import PipelineError, ProcessRequest, run_pipeline

    df = pl.DataFrame({"name": ["alice", "bob", "carol"] * 5, "dept": ["A"] * 15})
    req = ProcessRequest(
        policies=[
            ColumnPolicy(column="name", action="dp_laplace"),
            ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
        ],
        k=5,
        dp_params={"name": {"epsilon": 1.0, "lower": 0, "upper": 10}},
    )
    with pytest.raises(PipelineError) as exc:
        run_pipeline(df, req, "sNum", b"\x00" * 32, schema=[], pii_suggestions={})
    assert "dp_laplace requires a numeric column" in str(exc.value)


def test_deterministic_mode_actually_deterministic():
    """Regression: deterministic_key_name was accepted by the API but had no
    effect — hashing still used the session-random hmac_key. Joining two
    sanitized exports that both enabled deterministic mode with the same key
    was broken. Now the key is derived from (deployment_salt, key_name), so
    the same key on the same deployment produces the same hashes."""
    import polars as pl
    from sdsa.anonymize.policy import ColumnPolicy
    from sdsa.pipeline import ProcessRequest, run_pipeline

    df = pl.DataFrame({"email": ["alice@x.com", "bob@x.com", "carol@x.com"] * 5,
                        "dept": ["A"] * 15})
    req = ProcessRequest(
        policies=[
            ColumnPolicy(column="email", action="hash"),
            ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
        ],
        k=5,
        deterministic_key_name="shared-project-2026",
    )
    config_module._config = None
    try:
        import os
        os.environ["SDSA_DEPLOYMENT_SALT"] = "11" * 32
        r1 = run_pipeline(df, req, "s1", b"\x00" * 32, schema=[], pii_suggestions={})
        r2 = run_pipeline(df, req, "s2", b"\xff" * 32, schema=[], pii_suggestions={})
        assert r1.df["email"].to_list() == r2.df["email"].to_list()
    finally:
        os.environ.pop("SDSA_DEPLOYMENT_SALT", None)
        config_module._config = None


def test_deterministic_mode_different_keys_produce_different_hashes():
    """Two different key names must yield distinct hashes — otherwise the
    deployment couldn't segregate projects."""
    import os
    import polars as pl
    from sdsa.anonymize.policy import ColumnPolicy
    from sdsa.pipeline import ProcessRequest, run_pipeline

    df = pl.DataFrame({"email": ["alice@x.com"] * 10, "dept": ["A"] * 10})
    base = dict(
        policies=[
            ColumnPolicy(column="email", action="hash"),
            ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
        ],
        k=5,
    )
    config_module._config = None
    try:
        os.environ["SDSA_DEPLOYMENT_SALT"] = "22" * 32
        r1 = run_pipeline(df, ProcessRequest(**base, deterministic_key_name="alpha"),
                          "s1", b"\x00" * 32, schema=[], pii_suggestions={})
        r2 = run_pipeline(df, ProcessRequest(**base, deterministic_key_name="beta"),
                          "s2", b"\x00" * 32, schema=[], pii_suggestions={})
        assert r1.df["email"][0] != r2.df["email"][0]
    finally:
        os.environ.pop("SDSA_DEPLOYMENT_SALT", None)
        config_module._config = None


def test_report_omits_original_before_statistics():
    """The shareable report must not leak pre-sanitization statistics (exact
    min/max, histograms, original correlations) of the input data."""
    df = _sample_df()
    req = ProcessRequest(policies=_policies(), k=5)
    res = run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={})
    val = res.report["validation"]
    assert "correlation_before" not in val
    for col in val["columns"]:
        assert "before" not in col
        assert "before_histogram" not in col
    # After-stats (describing the already-released CSV) are retained.
    assert "correlation_after" in val


def test_dp_budget_blocks_repeated_release():
    """A second full-strength release of the same DP column is refused once the
    per-column session budget is exhausted (averaging-attack defence)."""
    df = _sample_df()
    req = ProcessRequest(
        policies=_policies(dp_on_salary=True),
        k=5,
        dp_params={"salary": {"epsilon": 1.0, "lower": 40_000, "upper": 100_000}},
    )
    r1 = run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={},
                      prior_dp_spent={}, epsilon_budget=1.0)
    assert r1.dp_spent_cumulative == {"salary": 1.0}
    assert r1.report["privacy"]["cumulative_epsilon_per_column"] == {"salary": 1.0}
    with pytest.raises(PipelineError) as exc:
        run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={},
                     prior_dp_spent=r1.dp_spent_cumulative, epsilon_budget=1.0)
    assert "budget" in str(exc.value).lower()


def test_homogeneous_sensitive_column_warns():
    df = pl.DataFrame({"zip": ["100"] * 10, "disease": ["flu"] * 10})
    req = ProcessRequest(policies=[
        ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
        ColumnPolicy(column="disease", action="retain"),
    ], k=5)
    res = run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={})
    assert res.report["warnings"]
    assert "disease" in res.report["warnings"][0]
    ld = res.report["k_anonymity"]["l_diversity"]
    assert ld["sensitive_columns"] == ["disease"]
    assert ld["homogeneous_classes"]["disease"] == 1
    assert ld["enforced"] is False


def test_pipeline_enforces_l_diversity():
    df = pl.DataFrame({
        "zip":     ["1"] * 6 + ["2"] * 6,
        "disease": ["flu"] * 6 + ["flu", "cold"] * 3,
    })
    req = ProcessRequest(policies=[
        ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
        ColumnPolicy(column="disease", action="retain"),
    ], k=5, l=2, accept_weaker_guarantee=True)
    res = run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={})
    assert set(res.df["zip"].to_list()) == {"2"}  # homogeneous class removed
    assert res.report["k_anonymity"]["l_diversity"]["enforced"] is True
    # Enforced + diverse output → no residual attribute-disclosure warning.
    assert res.report["warnings"] == []


def test_hidden_declared_sensitive_column_not_used_for_l_diversity():
    df = pl.DataFrame({
        "zip": ["1"] * 6,
        "disease": ["flu"] * 6,
    })
    req = ProcessRequest(policies=[
        ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
        ColumnPolicy(column="disease", action="redact"),
    ], k=5, l=2, sensitive_columns=["disease"])

    res = run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={})

    assert res.df.height == 6
    assert res.df["disease"].to_list() == ["[REDACTED]"] * 6
    assert res.report["k_anonymity"]["l_diversity"]["sensitive_columns"] == []


def test_markdown_renders_warnings_and_l_diversity():
    from sdsa.report import render_markdown
    df = pl.DataFrame({"zip": ["100"] * 10, "disease": ["flu"] * 10})
    req = ProcessRequest(policies=[
        ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
        ColumnPolicy(column="disease", action="retain"),
    ], k=5)
    res = run_pipeline(df, req, "s", b"\x00" * 32, schema=[], pii_suggestions={})
    md = render_markdown(res.report)
    assert "Warnings" in md
    assert "l-Diversity" in md


def test_exported_report_strips_source_schema_and_utility_counts():
    from sdsa.report import render_markdown

    df = pl.DataFrame({
        "zip": ["10001"] * 6,
        "age": [21, 22, 23, 24, 25, 26],
    })
    schema = [
        {
            "name": "zip",
            "dtype": "String",
            "kind": "string",
            "n_unique": 1,
            "null_count": 0,
            "row_count": 6,
        },
        {
            "name": "age",
            "dtype": "Int64",
            "kind": "numeric",
            "n_unique": 6,
            "null_count": 0,
            "row_count": 6,
            "min": 21.0,
            "max": 26.0,
        },
    ]
    req = ProcessRequest(policies=[
        ColumnPolicy(column="zip", action="retain", is_quasi_identifier=True),
        ColumnPolicy(column="age", action="numeric_bin", params={"bin_width": 10}),
    ], k=2)

    res = run_pipeline(df, req, "s", b"\x00" * 32, schema=schema, pii_suggestions={})

    assert res.report["schema"] == [
        {"name": "zip", "dtype": "String", "kind": "string"},
        {"name": "age", "dtype": "Int64", "kind": "numeric"},
    ]
    assert all("distinct_before" not in c for c in res.report["utility"]["columns"])
    assert all("noise_scale" not in c for c in res.report["utility"]["columns"])

    md = render_markdown(res.report)
    assert "Distinct before" not in md
    assert "21.0" not in md
    assert "26.0" not in md


def test_deterministic_mode_requires_configured_deployment_salt():
    df = pl.DataFrame({"email": ["alice@x.com"] * 10, "dept": ["A"] * 10})
    req = ProcessRequest(
        policies=[
            ColumnPolicy(column="email", action="hash"),
            ColumnPolicy(column="dept", action="retain", is_quasi_identifier=True),
        ],
        k=5,
        deterministic_key_name="shared-project-2026",
    )
    config_module._config = None
    try:
        with pytest.raises(PipelineError) as exc:
            run_pipeline(df, req, "s1", b"\x00" * 32, schema=[], pii_suggestions={})
        assert "SDSA_DEPLOYMENT_SALT" in str(exc.value)
    finally:
        config_module._config = None
