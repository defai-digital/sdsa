# SDSA - Secure Data Sanitization App

SDSA is a self-hostable web app for sanitizing tabular data before it leaves a
trusted environment. It ingests CSV, delimited TXT, and single-table SQL
`INSERT` dumps; detects likely sensitive fields; applies explicit per-column
privacy policies; enforces k-anonymity; and exports a sanitized CSV with a JSON
and Markdown privacy report.

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](backend/pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-118%20passing-brightgreen)](backend/tests/)

SDSA is designed for compliance-oriented engineering, analytics, and vendor data
sharing workflows where transformations must be reviewable and reproducible. It
is not a black-box anonymization service, and it does not claim dataset-level
`(epsilon, delta)` differential privacy.

For a first run, start with [QUICKSTART.md](QUICKSTART.md).

## What SDSA Does

- Upload CSV, TXT, or SQL data through a browser UI or REST API.
- Infer schema and detect likely PII such as email, phone, card number,
  government ID, date of birth, name, and address fields.
- Suggest field policies from detection results and optional project policy
  files.
- Apply masking, HMAC hashing, tokenization, redaction, dropping, numeric
  binning, date truncation, string truncation, and bounded Laplace noise.
- Enforce k-anonymity over operator-selected quasi-identifiers.
- Estimate suppression before processing through a preflight endpoint and UI.
- Export a sanitized CSV plus machine-readable and human-readable privacy
  reports.
- Keep uploaded data in an in-memory session store with a 30-minute default TTL.

## Privacy Model

SDSA produces pseudonymized microdata with optional per-column local-DP style
Laplace noise on numeric fields. Numeric DP requires declared `lower` and
`upper` bounds so sensitivity is explicit rather than inferred silently from the
uploaded data.

k-anonymity is enforced through suppression over declared quasi-identifiers. The
default `k` is 5. SDSA refuses zero-row output, refuses outputs above the hard
suppression cap, and requires an explicit override to exceed the soft
suppression cap.

Every generated report includes this claim:

> Pseudonymized microdata with per-column local-DP noise where configured.
> This output is NOT dataset-level (epsilon, delta)-differentially private.
> Linkage attacks using auxiliary data may still succeed. k-anonymity bounds
> prosecutor re-identification risk to at most 1/k.

See [docs/privacy-model.md](docs/privacy-model.md) for the longer explanation,
limits, and tradeoffs.

## Quick Start

```bash
git clone https://github.com/defai-digital/sdsa.git
cd sdsa/backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn sdsa.main:app --port 8000
```

Open <http://127.0.0.1:8000/> and upload one of the files in
[`samples/`](samples/), such as [`samples/employees.csv`](samples/employees.csv).

For browser and CLI walkthroughs, see [QUICKSTART.md](QUICKSTART.md).

## Repository Layout

```text
backend/                    FastAPI backend package
  src/sdsa/
    api/                    upload, preview, preflight, process, download routes
    anonymize/              policy application and primitive transforms
    core/                   config, logging, in-memory session store
    detect/                 schema inference and PII detection
    dp/                     Laplace mechanism and epsilon accountant
    kanon/                  k-anonymity enforcement
    validate/               before/after utility metrics
    ingest.py               CSV, TXT, and SQL parsing
    pipeline.py             end-to-end processing orchestration
    policy_config.py        default and project policy suggestion logic
    preflight.py            k-anonymity impact estimation
    report.py               JSON and Markdown privacy reports
  tests/                    pytest suite
frontend/                   vanilla HTML, CSS, and JS served by FastAPI
docs/                       privacy model and product documentation
samples/                    synthetic CSV, TXT, and SQL demo datasets
sdsa-policy.default.json    built-in field policy catalog
sdsa-policy.json.example    starter policy override file
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/upload` | Upload a CSV, TXT, or SQL file as multipart form data. |
| `POST` | `/api/preview/{session_id}` | Return a small before/after sample for selected policies. |
| `POST` | `/api/preflight/{session_id}` | Estimate k-anonymity suppression before processing. |
| `POST` | `/api/process/{session_id}` | Apply policies, DP, k-anonymity, validation, and reporting. |
| `GET` | `/api/download/{session_id}/data.csv` | Download the sanitized CSV. |
| `GET` | `/api/download/{session_id}/report.json` | Download the machine-readable privacy report. |
| `GET` | `/api/download/{session_id}/report.md` | Download the Markdown privacy report. |
| `DELETE` | `/api/session/{session_id}` | Zeroize and delete the in-memory session. |
| `GET` | `/health` | Health check. |

Processing requests use this shape:

```json
{
  "policies": [
    {"column": "email", "action": "hash"},
    {
      "column": "zip",
      "action": "string_truncate",
      "params": {"keep": 3},
      "is_quasi_identifier": true
    },
    {"column": "salary", "action": "dp_laplace"}
  ],
  "k": 5,
  "dp_params": {
    "salary": {"epsilon": 1.0, "lower": 40000, "upper": 180000}
  },
  "accept_weaker_guarantee": false
}
```

Supported actions are `retain`, `mask`, `hash`, `tokenize`, `redact`,
`numeric_bin`, `date_truncate`, `string_truncate`, `drop`, and `dp_laplace`.

## Field Policy Files

Place `sdsa-policy.json` at the repository root to override default policy
suggestions for known fields. The backend merges suggestions in this order:

1. Exact field overrides in `sdsa-policy.json`.
2. Built-in defaults by detected PII kind or column kind.
3. Heuristic quasi-identifier fallback when no explicit rule exists.

Example:

```json
{
  "fields": {
    "dob": {
      "action": "date_truncate",
      "params": {"granularity": "year"},
      "is_quasi_identifier": true
    },
    "salary": {
      "action": "dp_laplace",
      "dp_params": {"epsilon": 0.8, "lower": 40000, "upper": 180000}
    }
  }
}
```

Use [`sdsa-policy.json.example`](sdsa-policy.json.example) as a starting point.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `SDSA_MAX_UPLOAD_BYTES` | `314572800` | Maximum upload size, 300 MB by default. |
| `SDSA_SESSION_TTL` | `1800` | Session lifetime in seconds. |
| `SDSA_SAMPLE_ROWS` | `10000` | Rows sampled for schema and PII detection. |
| `SDSA_DEFAULT_K` | `5` | Default k-anonymity target. |
| `SDSA_DEFAULT_EPSILON` | `1.0` | Default epsilon used in policy suggestions. |
| `SDSA_EPSILON_MIN` | `0.1` | Minimum allowed epsilon. |
| `SDSA_EPSILON_MAX` | `10.0` | Maximum allowed epsilon. |
| `SDSA_MAX_SUPPRESSION` | `0.10` | Soft row-suppression cap. |
| `SDSA_HARD_MAX_SUPPRESSION` | `0.50` | Hard row-suppression cap. |
| `SDSA_ALLOWED_CORS_ORIGINS` | empty | Comma-separated allowed browser origins. `*` is rejected. |
| `SDSA_DEPLOYMENT_SALT` | random per process | Hex salt for deterministic cross-session hashing/tokenization. Keep secret. |

Deterministic mode requires `SDSA_DEPLOYMENT_SALT`. SDSA rejects deterministic
mode when the same request also contains `dp_laplace` columns.

## Testing

```bash
cd backend
.venv/bin/pytest
.venv/bin/ruff check src tests
```

The test suite covers ingestion, PII detection, anonymization primitives,
k-anonymity, DP Laplace validation, policy configuration, API routes, preflight,
reporting, and utility metrics.

## Samples

The [`samples/`](samples/) directory contains fabricated data for manual and
load testing:

- `employees.csv`, `transactions.csv`, `customers_cjk.csv`, `access_logs.txt`,
  and `users.sql` for small manual exercises.
- Larger CSV, TXT, and SQL samples for suppression and performance testing.
- `employees_huge.csv`, generated on demand, for a roughly 200 MB load test.

Regenerate sample data with:

```bash
python3 samples/generate.py
python3 samples/generate.py --all
```

## Deployment Notes

SDSA currently uses an in-memory session store and is best treated as a
single-process service unless you replace session storage with shared
infrastructure. For production use, put it behind TLS, avoid persistent raw-data
volumes, restrict CORS to trusted origins, add proxy-level rate limits, and set
a stable secret `SDSA_DEPLOYMENT_SALT` only if deterministic exports are needed.

## License

SDSA is licensed under [AGPL-3.0](LICENSE). Copyright (c) 2026 DEFAI Private
Limited.
