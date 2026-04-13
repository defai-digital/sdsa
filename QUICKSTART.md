# SDSA Quickstart

Sanitize your first CSV in about **two minutes**.

---

## 1 · Install (one time)

Requires Python 3.11 or later.

```bash
git clone https://github.com/defai-digital/sdsa.git
cd sdsa/backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 2 · Start the server

```bash
.venv/bin/uvicorn sdsa.main:app --port 8000
```

The UI and API both serve on <http://127.0.0.1:8000/>.

---

## 3 · Try it in the browser

1. **Drag a file** onto the dropzone (CSV, TXT, or SQL).
   Or click to browse — a sample file is at `samples/employees.csv`.
2. **Configure per column.** Detected PII is pre-selected with reasonable
   defaults. Hover any `?` to see what the control does.
3. **Check QI** on columns you want k-anonymity to enforce. The live
   **preflight panel** shows estimated suppression; one click unchecks the
   worst offender.
4. **Set k** (default 5). For any `dp_laplace` column, fill in ε and bounds.
5. Click **Process** → download the **sanitized CSV** + **privacy report**
   (JSON & Markdown).

To start over: click the **"1 Upload"** step in the header, or the
**"Sanitize another file"** button at the bottom of the review step.

---

## 4 · Try it from the CLI

```bash
# Sample CSV
cat > /tmp/people.csv << 'EOF'
email,zip,age,salary
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
EOF

# Upload
SID=$(curl -sS -F "file=@/tmp/people.csv" http://127.0.0.1:8000/api/upload \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
echo "session: $SID"

# Process: hash emails, generalize zip + age (QIs), Laplace-noise salary
curl -sS -H "Content-Type: application/json" \
  -d '{
    "policies": [
      {"column": "email",  "action": "hash"},
      {"column": "zip",    "action": "string_truncate", "params": {"keep": 3}, "is_quasi_identifier": true},
      {"column": "age",    "action": "numeric_bin",     "params": {"bin_width": 10}, "is_quasi_identifier": true},
      {"column": "salary", "action": "dp_laplace"}
    ],
    "k": 5,
    "dp_params": {"salary": {"epsilon": 1.0, "lower": 40000, "upper": 100000}}
  }' \
  http://127.0.0.1:8000/api/process/$SID > /dev/null

# Download artifacts
curl -sS http://127.0.0.1:8000/api/download/$SID/data.csv    > /tmp/people-sanitized.csv
curl -sS http://127.0.0.1:8000/api/download/$SID/report.md   > /tmp/people-report.md
curl -sS http://127.0.0.1:8000/api/download/$SID/report.json > /tmp/people-report.json

echo "--- sanitized CSV ---"
head /tmp/people-sanitized.csv
echo "--- privacy report (Markdown) ---"
head -20 /tmp/people-report.md
```

Expected: emails become 16-char HMAC hashes; `zip` → `100**`; `age` → `[20, 30)`;
`salary` values are Laplace-noised; report states `k achieved = 5`, `max ε = 1.0`.

---

## 5 · Run the tests

```bash
cd backend
.venv/bin/pytest
# 64 passed
```

---

## Action cheat sheet

| Goal | Action | Params |
|---|---|---|
| Hide emails, keep joinable within a session | `hash` | HMAC with per-session key |
| Hide emails, join across exports | `tokenize` + deterministic key | set `deterministic_key_name` |
| Drop direct identifiers entirely | `redact` or `drop` | — |
| Generalize ZIP / postal codes | `string_truncate` | `keep: 3` |
| Generalize ages | `numeric_bin` | `bin_width: 10` |
| Generalize dates | `date_truncate` | `granularity: year` (or `month` / `day`) |
| Add DP noise to a numeric column | `dp_laplace` | `epsilon`, `lower`, `upper` (all required) |

---

## Gotchas

- **Deterministic mode + DP on the same column is rejected.** Pick one.
- **DP columns need declared `lower` / `upper`** — sensitivity comes from
  those bounds, not from the data. Without them → 400.
- **k-anonymity with > 10% suppression is rejected by default.**
  Lower `k`, generalize more, or set `accept_weaker_guarantee: true`.
- **Outputs with > 50% suppression are refused even with the override.**
  This hard cap protects utility; reduce the QI set or generalize further.
- **ε must be in [0.1, 10].** Outside that range is either uselessly noisy
  or uselessly weak.
- **Sessions auto-expire after 30 minutes** and are zeroized. Re-upload to
  continue.

---

## What next?

- Browse the full feature list and API reference in [README.md](README.md).
- Declare project-wide field rules in `sdsa-policy.json` (see the
  [Field policy file](README.md#field-policy-file) section).
- Regenerate large / huge samples with `python3 samples/generate.py --all`.

---

## License

SDSA is licensed under **AGPL-3.0**. Copyright © 2026 DEFAI Private Limited.
See [LICENSE](LICENSE) for full terms.
