# SDSA

Secure Data Sanitization App (SDSA) is a self-hostable tool for sanitizing
tabular data before it leaves a trusted environment.

It ingests CSV, delimited TXT, and single-table SQL `INSERT` dumps; detects
likely sensitive fields; applies explicit per-column privacy policies; enforces
k-anonymity; measures or enforces l-diversity for sensitive cleartext
attributes; and exports a sanitized CSV with JSON and Markdown privacy reports.

![SDSA upload screen showing the three-step sanitization workflow](https://raw.githubusercontent.com/defai-digital/sdsa/main/docs/assets/sdsa-upload-screen.png)

## Install

```bash
pip install sdsa
sdsa-server start
```

Open <http://127.0.0.1:8000/>.

## What It Does

- Serves a browser UI and REST API from one FastAPI application.
- Detects likely PII such as email, phone, card number, government ID, date of
  birth, name, and address fields.
- Supports `retain`, `mask`, `hash`, `tokenize`, `redact`, `drop`,
  `numeric_bin`, `date_truncate`, `string_truncate`, and `dp_laplace` actions.
- Applies bounded Laplace noise to numeric columns when differential privacy is
  configured with explicit `epsilon`, `lower`, and `upper` values.
- Tracks cumulative per-column DP epsilon for the uploaded session to prevent
  repeated noisy releases from being averaged.
- Enforces k-anonymity over selected quasi-identifiers and can enforce
  l-diversity on sensitive cleartext attributes.
- Provides preflight suppression estimates before processing.
- Stores uploaded data in memory with a default 30-minute session TTL.

## CLI

```bash
sdsa-server start
sdsa-server start --host 0.0.0.0 --port 8000
sdsa-server start --random-port
sdsa-server start --reload
```

The package includes the static frontend, so no separate web build is required.

## Privacy Model

SDSA produces pseudonymized microdata with optional per-column local-DP style
noise. It does not claim dataset-level `(epsilon, delta)` differential privacy.
Linkage attacks using auxiliary data may still succeed.

k-anonymity bounds prosecutor re-identification risk to at most `1/k` for the
declared quasi-identifier set, subject to the limits described in each generated
privacy report.

l-diversity is measured by default for cleartext non-QI attributes and can be
enforced with `l >= 2`. Homogeneous sensitive groups appear as warnings in the
report when l-diversity is measured but not enforced.

## Deployment

For production, run `sdsa-server start` behind TLS termination and keep one SDSA
process per deployment unless you replace the in-memory session store with
shared infrastructure. The GitHub repository includes Docker, Compose, nginx,
and CI/CD examples.

## Links

- Source: <https://github.com/defai-digital/sdsa>
- Documentation: <https://github.com/defai-digital/sdsa/blob/main/README.md>
- Deployment guide: <https://github.com/defai-digital/sdsa/blob/main/docs/deployment.md>
- Privacy model: <https://github.com/defai-digital/sdsa/blob/main/docs/privacy-model.md>
