from __future__ import annotations

import json

from sdsa.policy_config import build_policy_suggestions


def test_field_override_wins_over_pii_defaults(monkeypatch, tmp_path):
    policy_file = tmp_path / "custom-policy.json"
    policy_file.write_text(json.dumps({
        "fields": {
            "salary": {
                "action": "dp_laplace",
                "dp_params": {"epsilon": 0.5, "lower": 0, "upper": 200000},
                "is_quasi_identifier": False,
            },
            "dob": {
                "action": "date_truncate",
                "params": {"granularity": "year"},
                "is_quasi_identifier": True,
            },
        }
    }), encoding="utf-8")
    monkeypatch.setenv("SDSA_POLICY_FILE", str(policy_file))

    schema = [
        {"name": "salary", "kind": "numeric", "row_count": 100, "n_unique": 90, "min": 1.0, "max": 10.0},
        {"name": "dob", "kind": "datetime", "row_count": 100, "n_unique": 90},
        {"name": "email", "kind": "string", "row_count": 100, "n_unique": 100},
    ]
    pii = {
        "salary": {"kind": "none"},
        "dob": {"kind": "date_of_birth"},
        "email": {"kind": "email"},
    }

    out = build_policy_suggestions(schema, pii)
    assert out["salary"]["action"] == "dp_laplace"
    assert out["salary"]["dp_params"]["epsilon"] == 0.5
    assert out["salary"]["source"] == "field"
    assert out["dob"]["params"]["granularity"] == "year"
    assert out["dob"]["is_quasi_identifier"] is True
    assert out["email"]["action"] == "hash"
    assert out["email"]["source"] == "pii_kind"
