from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from sdsa.main import create_app
import sdsa.core.config as config_module

app = create_app()
client = TestClient(app)


CSV_SAMPLE = b"""email,zip,age,salary
alice@example.com,10001,25,50000
bob@example.com,10001,26,51000
carol@example.com,10001,24,52000
dave@example.com,10001,28,53000
eve@example.com,10001,29,54000
frank@example.com,10002,35,60000
grace@example.com,10002,36,61000
heidi@example.com,10002,34,62000
ivan@example.com,10002,38,63000
judy@example.com,10002,39,64000
"""


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_full_flow():
    # 1. Upload
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    data = r.json()
    sid = data["session_id"]
    assert data["session_ttl_seconds"] == 1800
    assert data["row_count"] == 10
    assert data["column_count"] == 4
    assert data["policy_suggestions"]["email"]["action"] == "hash"

    # 2. Process
    req = {
        "policies": [
            {"column": "email", "action": "hash"},
            {"column": "zip", "action": "string_truncate",
             "params": {"keep": 3}, "is_quasi_identifier": True},
            {"column": "age", "action": "numeric_bin",
             "params": {"bin_width": 10}, "is_quasi_identifier": True},
            {"column": "salary", "action": "retain"},
        ],
        "k": 5,
        "dp_params": {},
    }
    r = client.post(f"/api/process/{sid}", json=req)
    assert r.status_code == 200, r.text
    report = r.json()["report"]
    assert report["k_anonymity"]["k_achieved"] >= 5

    # 3. Downloads
    r = client.get(f"/api/download/{sid}/data.csv")
    assert r.status_code == 200
    assert b"email" in r.content.splitlines()[0]

    r = client.get(f"/api/download/{sid}/report.json")
    assert r.status_code == 200
    assert r.json()["claim"]

    r = client.get(f"/api/download/{sid}/report.md")
    assert r.status_code == 200
    assert b"SDSA Privacy Report" in r.content

    # 4. Delete
    r = client.delete(f"/api/session/{sid}")
    assert r.status_code == 200
    # Downloads now 404
    r = client.get(f"/api/download/{sid}/data.csv")
    assert r.status_code == 404


def test_upload_rejects_empty():
    r = client.post("/api/upload", files={"file": ("empty.csv", b"", "text/csv")})
    assert r.status_code == 400


def test_upload_reports_configured_session_ttl(monkeypatch):
    monkeypatch.setenv("SDSA_SESSION_TTL", "90")
    config_module._config = None
    try:
        r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["session_ttl_seconds"] == 90
    finally:
        config_module._config = None


def test_upload_schema_uses_full_dataframe_not_detection_sample(monkeypatch):
    monkeypatch.setenv("SDSA_SAMPLE_ROWS", "5")
    config_module._config = None
    try:
        rows = ["code"] + (["A"] * 5) + [f"U{i}" for i in range(5)]
        sample = ("\n".join(rows) + "\n").encode("utf-8")
        r = client.post("/api/upload", files={"file": ("sample.csv", sample, "text/csv")})
        assert r.status_code == 200, r.text
        schema = {col["name"]: col for col in r.json()["schema"]}
        assert schema["code"]["row_count"] == 10
        assert schema["code"]["n_unique"] == 6
    finally:
        config_module._config = None


def test_upload_rejects_invalid_policy_file(monkeypatch, tmp_path):
    policy_file = tmp_path / "sdsa-policy.json"
    policy_file.write_text("{ bad json", encoding="utf-8")
    monkeypatch.setenv("SDSA_POLICY_FILE", str(policy_file))

    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 400
    assert "invalid policy config" in r.text


def test_upload_uses_custom_policy_file(monkeypatch, tmp_path):
    policy_file = tmp_path / "sdsa-policy.json"
    policy_file.write_text(
        """
        {
          "fields": {
            "salary": {
              "action": "dp_laplace",
              "dp_params": {"epsilon": 0.7, "lower": 40000, "upper": 70000}
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("SDSA_POLICY_FILE", str(policy_file))

    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    policy = r.json()["policy_suggestions"]["salary"]
    assert policy["action"] == "dp_laplace"
    assert policy["dp_params"]["epsilon"] == 0.7
    assert policy["dp_params"]["lower"] == 40000
    assert policy["dp_params"]["upper"] == 70000


def test_upload_parses_dates_and_dp_download_is_bounded():
    sample = b"""email,dob,zip,salary
alice@example.com,1990-03-14,10001,50000
bob@example.com,1985-07-22,10001,51000
carol@example.com,1992-11-05,10001,52000
dave@example.com,1988-01-30,10001,53000
eve@example.com,1995-06-18,10001,54000
frank@example.com,1980-09-12,10002,60000
grace@example.com,1987-12-02,10002,61000
heidi@example.com,1991-04-25,10002,62000
ivan@example.com,1983-10-08,10002,63000
judy@example.com,1993-02-14,10002,64000
"""
    r = client.post("/api/upload", files={"file": ("sample.csv", sample, "text/csv")})
    assert r.status_code == 200, r.text
    data = r.json()
    sid = data["session_id"]
    kinds = {col["name"]: col["kind"] for col in data["schema"]}
    assert kinds["dob"] == "datetime"

    req = {
        "policies": [
            {"column": "email", "action": "hash"},
            {"column": "dob", "action": "date_truncate", "params": {"granularity": "month"}},
            {"column": "zip", "action": "string_truncate",
             "params": {"keep": 3}, "is_quasi_identifier": True},
            {"column": "salary", "action": "dp_laplace"},
        ],
        "k": 5,
        "dp_params": {"salary": {"epsilon": 1.0, "lower": 40000, "upper": 70000}},
    }
    r = client.post(f"/api/process/{sid}", json=req)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/download/{sid}/data.csv")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8"))))
    assert rows
    assert all(40000.0 <= float(row["salary"]) <= 70000.0 for row in rows)
    assert all(len(row["dob"]) == 7 for row in rows)  # YYYY-MM


def test_preflight_endpoint_estimates_suppression():
    sample = b"""city,zip,membership_tier
A,10001,gold
A,10002,gold
A,10003,gold
A,10004,gold
A,10005,gold
A,10006,silver
A,10007,silver
A,10008,silver
A,10009,silver
A,10010,silver
B,20001,gold
B,20002,gold
B,20003,gold
B,20004,gold
B,20005,gold
B,20006,silver
B,20007,silver
B,20008,silver
B,20009,silver
B,20010,silver
"""
    r = client.post("/api/upload", files={"file": ("sample.csv", sample, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "city", "action": "retain", "is_quasi_identifier": True},
            {"column": "zip", "action": "retain", "is_quasi_identifier": True},
            {"column": "membership_tier", "action": "retain", "is_quasi_identifier": True}
        ],
        "k": 5
    }
    r = client.post(f"/api/preflight/{sid}", json=req)
    assert r.status_code == 200, r.text
    preflight = r.json()["preflight"]
    assert preflight["within_suppression_cap"] is False
    assert preflight["within_hard_suppression_cap"] is False
    assert preflight["worst_qi_by_cardinality"][0]["column"] == "zip"
    assert preflight["drop_one_qi_impacts"][0]["column"] == "zip"


def test_preflight_rejects_invalid_policy_params():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "age", "action": "numeric_bin", "params": {}, "is_quasi_identifier": True},
        ],
        "k": 5,
    }
    r = client.post(f"/api/preflight/{sid}", json=req)
    assert r.status_code == 400
    assert "bin_width" in r.text


def test_preflight_honors_dp_constraints():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "salary", "action": "dp_laplace", "is_quasi_identifier": True},
        ],
        "k": 5,
        "dp_params": {"salary": {"epsilon": 100.0, "lower": 0, "upper": 100000}},
    }
    r = client.post(f"/api/preflight/{sid}", json=req)
    assert r.status_code == 400
    assert "outside allowed range" in r.text


def test_preflight_rejects_non_numeric_dp_params():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "salary", "action": "dp_laplace", "is_quasi_identifier": True},
        ],
        "k": 5,
        "dp_params": {"salary": {"epsilon": "nope", "lower": 0, "upper": 100000}},
    }
    r = client.post(f"/api/preflight/{sid}", json=req)
    assert r.status_code == 400
    assert "must be numeric" in r.text


def test_preflight_rejects_invalid_dp_bounds():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "salary", "action": "dp_laplace", "is_quasi_identifier": True},
        ],
        "k": 5,
        "dp_params": {"salary": {"epsilon": 1.0, "lower": 100000, "upper": 100000}},
    }
    r = client.post(f"/api/preflight/{sid}", json=req)
    assert r.status_code == 400
    assert "invalid DP params" in r.text


def test_process_refuses_extreme_suppression_even_with_override():
    sample = b"""city,zip
A,10001
A,10001
A,10001
A,10001
A,10001
A,10006
A,10007
A,10008
A,10009
A,10010
B,20001
B,20002
B,20003
B,20004
B,20005
B,20006
B,20007
B,20008
B,20009
B,20010
"""
    r = client.post("/api/upload", files={"file": ("sample.csv", sample, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "city", "action": "retain", "is_quasi_identifier": True},
            {"column": "zip", "action": "retain", "is_quasi_identifier": True}
        ],
        "k": 5,
        "dp_params": {},
        "accept_weaker_guarantee": True
    }
    r = client.post(f"/api/process/{sid}", json=req)
    assert r.status_code == 400
    assert "hard utility cap" in r.text


def test_process_rejects_invalid_policy_params():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "age", "action": "numeric_bin", "params": {}, "is_quasi_identifier": False},
        ],
        "k": 5,
        "dp_params": {},
    }
    r = client.post(f"/api/process/{sid}", json=req)
    assert r.status_code == 400
    assert "bin_width" in r.text


def test_process_rejects_non_numeric_dp_params():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "salary", "action": "dp_laplace", "is_quasi_identifier": False},
        ],
        "k": 5,
        "dp_params": {"salary": {"epsilon": "nope", "lower": 0, "upper": 100000}},
    }
    r = client.post(f"/api/process/{sid}", json=req)
    assert r.status_code == 400
    assert "must be numeric" in r.text


def test_process_rejects_invalid_dp_bounds():
    r = client.post("/api/upload", files={"file": ("sample.csv", CSV_SAMPLE, "text/csv")})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    req = {
        "policies": [
            {"column": "salary", "action": "dp_laplace", "is_quasi_identifier": False},
        ],
        "k": 5,
        "dp_params": {"salary": {"epsilon": 1.0, "lower": 100000, "upper": 100000}},
    }
    r = client.post(f"/api/process/{sid}", json=req)
    assert r.status_code == 400
    assert "invalid DP params" in r.text
