# SDSA — Secure Data Sanitization App

> Pseudonymization + bounded differential privacy for tabular data.
> Built for compliance-driven teams that need to share test data without leaking PII.

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-73%20passing-brightgreen)](backend/tests/)

SDSA is a self-hostable web app that takes a CSV / TXT / SQL dump, detects
sensitive columns automatically, applies per-column anonymization (masking,
hashing, tokenization, generalization), adds calibrated Laplace noise to
numeric columns, enforces k-anonymity, and hands back a sanitized file plus
a machine-readable privacy report.

SDSA should be positioned as an enterprise-oriented data sanitization layer:
explicit field policies, bounded privacy mechanisms, operator review before
release, and an auditable report for every run. It is not a black-box
"make this anonymous" button, and it does not claim guarantees the system
does not actually provide.

**What SDSA does NOT claim:** dataset-level (ε,δ)-differential privacy.
Every report says so explicitly. See [Privacy claim](#privacy-claim).
For the longer explanation, see [docs/privacy-model.md](docs/privacy-model.md).

---

## Features

| | |
|---|---|
| **Multi-format input** | CSV · delimited TXT (tab / pipe / semicolon auto-sniff) · single-table SQL `INSERT` dumps |
| **Auto-detection** | Regex + libphonenumber + multilingual column-name heuristics (email, phone, credit card, government ID, DOB, name, address). Every suggestion is confirmable — never silent. |
| **Per-column actions** | `mask` · `hash` (HMAC-SHA256) · `tokenize` · `redact` · `numeric_bin` · `date_truncate` · `string_truncate` · `drop` |
| **Differential privacy** | Laplace mechanism on numeric columns with per-column ε accountant. Bounded sensitivity via declared min/max. ε ∈ [0.1, 10]. |
| **k-anonymity** | Suppression-based enforcement. Default k=5. Zero-row output always refused. Hard 50% suppression cap. |
| **Live preflight** | Estimates suppression impact as you toggle QIs. One-click remediation (`Uncheck X`, `Uncheck all QIs`). |
| **Privacy report** | JSON + Markdown, auto-bundled with the download. Contains ε per column, k achieved, prosecutor risk bound, policy applied, and an explicit claim statement. |
| **Zero-persistence** | In-memory session store. 30-minute TTL. Best-effort zeroization on delete. No raw row values in logs. |
| **Policy file** | Optional `sdsa-policy.json` for project-wide field-level rules. |

## What We Mean By "Data Obfuscation"

In SDSA, "data obfuscation" means controlled transformation of sensitive
fields so the output remains useful for engineering, analytics, and vendor
workflows without exposing the original direct identifiers.

- Direct identifiers can be masked, hashed, tokenized, redacted, or dropped.
- Quasi-identifiers can be generalized with binning, date truncation, and
  string truncation before k-anonymity enforcement.
- Numeric measures can receive bounded Laplace noise where differential
  privacy is configured.

This is an enterprise workflow because the treatment is explicit, reviewable,
and reproducible. The operator can see which fields are transformed, which
fields are treated as quasi-identifiers, how much suppression k-anonymity
requires, and what privacy claim is attached to the exported file.

For the full model, tradeoffs, and limits, see
[docs/privacy-model.md](docs/privacy-model.md).

## Screenshots

The UI has three steps, accessible from the top stepper:

```
 ┌─ 1. Upload ─────┐   ┌─ 2. Configure ──────┐   ┌─ 3. Review ─────┐
 │  drag & drop    │ → │  per-column policy  │ → │  stats + files  │
 │  CSV/TXT/SQL    │   │  live preflight     │   │  privacy report │
 └─────────────────┘   └─────────────────────┘   └─────────────────┘
```

---

## Quick start

```bash
git clone https://github.com/defai-digital/sdsa.git
cd sdsa/backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn sdsa.main:app --port 8000
```

Open <http://127.0.0.1:8000/>.

For step-by-step examples (browser + CLI), see **[QUICKSTART.md](QUICKSTART.md)**.

---

## Repository layout

```
backend/              Python 3.11+ FastAPI app
  src/sdsa/
    api/              FastAPI routes (upload, process, preflight, download)
    core/             config, structured logging, session store
    detect/           schema + PII detection
    anonymize/        mask/hash/tokenize/redact/generalize primitives
    kanon/            k-anonymity enforcer (suppression)
    dp/               Laplace mechanism + per-column ε accountant
    validate/         before/after utility metrics (stats, histograms, correlation)
    ingest.py         CSV / TXT / SQL dispatch + parsers
    pipeline.py       end-to-end orchestration
    report.py         privacy report builder (JSON + Markdown)
    preflight.py      equivalence-class impact estimator
  tests/              73 pytest cases
frontend/             Vanilla HTML/CSS/JS (served by FastAPI at `/`)
docs/                 Product and privacy-model documentation
samples/              Synthetic demo data — small + large + huge (200 MB)
sdsa-policy.default.json   Shipped default rule catalog
sdsa-policy.json.example   Starting point for project overrides
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/upload` | multipart upload (CSV / TXT / SQL) |
| `POST` | `/api/preflight/{session_id}` | estimate k-anonymity suppression before Process |
| `POST` | `/api/process/{session_id}` | apply policies, run pipeline |
| `GET`  | `/api/download/{session_id}/data.csv` | sanitized output |
| `GET`  | `/api/download/{session_id}/report.json` | privacy report (machine-readable) |
| `GET`  | `/api/download/{session_id}/report.md` | privacy report (human-readable) |
| `DELETE` | `/api/session/{session_id}` | zeroize + drop session |
| `GET`  | `/health` | healthcheck |

---

## Field policy file

Declare project-wide privacy treatment in a repo-root JSON file instead of
configuring per-upload. The backend merges suggestions from:

1. exact field overrides in `sdsa-policy.json`
2. defaults by detected PII kind / column kind
3. heuristic QI fallback only when the config does not say otherwise

Example `sdsa-policy.json`:

```json
{
  "fields": {
    "dob": {
      "action": "date_truncate",
      "params": { "granularity": "year" },
      "is_quasi_identifier": true
    },
    "salary": {
      "action": "dp_laplace",
      "dp_params": { "epsilon": 0.8, "lower": 40000, "upper": 180000 }
    }
  }
}
```

`sdsa-policy.json.example` is a starting point; `sdsa-policy.default.json` is
the shipped catalog that triggers if you don't provide your own.

---

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---:|---|
| `SDSA_MAX_UPLOAD_BYTES` | `314572800` (300 MB) | Hard cap on upload size |
| `SDSA_SESSION_TTL` | `1800` (30 min) | Seconds a session stays in memory |
| `SDSA_SAMPLE_ROWS` | `10000` | Rows sampled for schema + PII detection |
| `SDSA_DEFAULT_K` | `5` | Default k-anonymity target |
| `SDSA_DEFAULT_EPSILON` | `1.0` | Default per-column ε |
| `SDSA_EPSILON_MIN` / `_MAX` | `0.1` / `10` | ε clamp |
| `SDSA_MAX_SUPPRESSION` | `0.10` | Soft cap; needs `accept_weaker_guarantee=true` to exceed |
| `SDSA_HARD_MAX_SUPPRESSION` | `0.50` | Hard cap; always refused |
| `SDSA_DEPLOYMENT_SALT` | *(random per-process)* | Hex. Stabilizes deterministic-mode hashes across restarts. Keep secret. |

---

## Privacy claim

Verbatim from every generated report:

> Pseudonymized microdata with per-column local-DP noise where configured.
> This output is NOT dataset-level (ε,δ)-differentially private. Linkage
> attacks using auxiliary data may still succeed. k-anonymity bounds
> prosecutor re-identification risk to at most 1/k.

SDSA is honest about what it does and does not guarantee. Dataset-level DP
synthesis (PrivBayes / DP-GAN / MST) is out of scope for v1.

For a more detailed explanation of the data-obfuscation model, local DP
usage, k-anonymity role, and enterprise positioning, see
[docs/privacy-model.md](docs/privacy-model.md).

---

## Tests

```bash
cd backend
.venv/bin/pytest            # 73 passing
.venv/bin/pytest -v         # with individual names
```

Covers: ingest (CSV/TXT/SQL), PII detection, anonymization primitives,
k-anonymity, DP Laplace, pipeline, API, and preflight.

---

## Performance

Measured on an Apple Silicon Mac (local uvicorn), default config:

| Input | Upload + detect | Full pipeline |
|---|---:|---:|
| 25 rows | <10 ms | <10 ms |
| 5,000 rows (CSV) | ~80 ms | ~80 ms |
| 1.68 M rows (200 MB CSV) | ~500 ms | ~10 s |

Regenerate large samples with `python3 samples/generate.py --all`.

---

## Deployment notes

Not implemented in v1, but required for real production:

- TLS termination at reverse proxy (nginx / envoy).
- Run with swap disabled and no persistent volume mounts.
- Rate-limiting / CAPTCHA at the proxy layer.
- For multi-worker gunicorn, promote the in-process session store to Redis
  (session affinity is a short-term workaround).

---

## License

**AGPL-3.0**. Copyright © 2026 DEFAI Private Limited. See [LICENSE](LICENSE).

The AGPL applies if you run SDSA as a service: users interacting with the
service over a network must be able to obtain the corresponding source
under the same terms.

For commercial licensing (alternative terms without AGPL obligations),
contact DEFAI Private Limited.

---

## Contributing

Issues and PRs welcome at
<https://github.com/defai-digital/sdsa>. By contributing, you agree to
license your contribution under AGPL-3.0.
