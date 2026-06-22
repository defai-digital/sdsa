# SDSA Quickstart

This guide gets SDSA running locally and walks through one browser run and one
API run.

## Requirements

- Python 3.11 or newer.
- `curl` for the API example.
- Docker, if you want to run the container deployment path.
- A shell from the repository root unless a command says otherwise.

## 1. Install

```bash
git clone https://github.com/defai-digital/sdsa.git
cd sdsa/backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

If you already cloned the repository, start from:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 2. Start SDSA

From `backend/`:

```bash
.venv/bin/uvicorn sdsa.main:app --port 8000
```

Open <http://127.0.0.1:8000/>.

## 3. Sanitize a File in the Browser

1. Upload `../samples/employees.csv`.
2. Review the detected columns and suggested policies.
3. Mark quasi-identifiers for k-anonymity, such as `dob`, `zip`, and
   `department`.
4. For numeric DP fields such as `salary`, set `epsilon`, `lower`, and `upper`
   bounds.
5. Check the preflight panel. If suppression is too high, uncheck a
   high-cardinality quasi-identifier or generalize it more aggressively.
6. Click **Process**.
7. Download the sanitized CSV and the JSON or Markdown privacy report.

The session stays in memory for 30 minutes by default. Re-upload the file after
the session expires.

## 4. Sanitize a File with the API

Keep the server running in one terminal. In another terminal, run these commands
from the repository root.

```bash
cat > /tmp/sdsa-people.csv <<'EOF'
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

SID=$(
  curl -sS -F "file=@/tmp/sdsa-people.csv" \
    http://127.0.0.1:8000/api/upload |
  python3 -c "import json, sys; print(json.load(sys.stdin)['session_id'])"
)
echo "$SID"
```

Run preflight before processing:

```bash
curl -sS -H "Content-Type: application/json" \
  -d '{
    "policies": [
      {"column": "email", "action": "hash"},
      {
        "column": "zip",
        "action": "string_truncate",
        "params": {"keep": 3},
        "is_quasi_identifier": true
      },
      {
        "column": "age",
        "action": "numeric_bin",
        "params": {"bin_width": 10},
        "is_quasi_identifier": true
      },
      {"column": "salary", "action": "dp_laplace"}
    ],
    "k": 5,
    "dp_params": {
      "salary": {"epsilon": 1.0, "lower": 40000, "upper": 100000}
    }
  }' \
  "http://127.0.0.1:8000/api/preflight/$SID"
```

Process and download the outputs:

```bash
curl -sS -H "Content-Type: application/json" \
  -d '{
    "policies": [
      {"column": "email", "action": "hash"},
      {
        "column": "zip",
        "action": "string_truncate",
        "params": {"keep": 3},
        "is_quasi_identifier": true
      },
      {
        "column": "age",
        "action": "numeric_bin",
        "params": {"bin_width": 10},
        "is_quasi_identifier": true
      },
      {"column": "salary", "action": "dp_laplace"}
    ],
    "k": 5,
    "dp_params": {
      "salary": {"epsilon": 1.0, "lower": 40000, "upper": 100000}
    }
  }' \
  "http://127.0.0.1:8000/api/process/$SID" > /tmp/sdsa-process.json

curl -sS "http://127.0.0.1:8000/api/download/$SID/data.csv" \
  > /tmp/sdsa-people-sanitized.csv
curl -sS "http://127.0.0.1:8000/api/download/$SID/report.md" \
  > /tmp/sdsa-people-report.md
curl -sS "http://127.0.0.1:8000/api/download/$SID/report.json" \
  > /tmp/sdsa-people-report.json

head /tmp/sdsa-people-sanitized.csv
head -20 /tmp/sdsa-people-report.md
```

Expected result:

- `email` becomes a 16-character HMAC hash.
- `zip` becomes a retained prefix such as `100**`.
- `age` becomes a range such as `[20, 30)`.
- `salary` receives bounded Laplace noise.
- The report records `k`, suppression, policies applied, and epsilon spend.

## 5. Common Actions

| Goal | Action | Required params |
|---|---|---|
| Keep a direct identifier hidden but joinable within a session | `hash` | none |
| Produce stable pseudonyms across sessions | `hash` or `tokenize` with `deterministic_key_name` | `SDSA_DEPLOYMENT_SALT` environment variable |
| Remove a column | `drop` | none |
| Replace values with a redaction marker | `redact` | none |
| Generalize ages or amounts | `numeric_bin` | `bin_width` |
| Generalize dates | `date_truncate` | `granularity`: `year`, `month`, or `day` |
| Generalize ZIP or postal codes | `string_truncate` | `keep` |
| Add bounded numeric noise | `dp_laplace` | `epsilon`, `lower`, `upper` in `dp_params` |

## 6. Run Tests

From `backend/`:

```bash
.venv/bin/pytest
.venv/bin/ruff check src tests
```

The current backend test suite reports `124 passed`.

## 7. Run with Docker

From the repository root:

```bash
cp .env.example .env
docker build -t defai-digital/sdsa:1.1.0 .
docker run --rm --env-file .env -p 8000:8000 defai-digital/sdsa:1.1.0
```

Or with Compose:

```bash
cp .env.example .env
docker compose up --build
```

Open <http://127.0.0.1:8000/>.

## 8. Production Compose

For a small production host, use the nginx-fronted Compose file:

```bash
cp .env.example .env
# edit .env for your environment
# place TLS files at deploy/certs/fullchain.pem and deploy/certs/privkey.pem
docker compose -f compose.prod.yml up -d --build
```

Health checks and logs:

```bash
curl -fsS https://YOUR_HOST/health
docker compose -f compose.prod.yml ps
docker compose -f compose.prod.yml logs -f sdsa
```

See [docs/deployment.md](docs/deployment.md) for the deployment design, nginx
configuration, policy-file mounting, and rollback notes.

Version tags publish images to GitHub Container Registry, for example
`ghcr.io/defai-digital/sdsa:v1.1.0`.

## 9. CI/CD

The repository includes [`.github/workflows/docker.yml`](.github/workflows/docker.yml).
On pull requests it runs pytest, Ruff, and a Docker image build without pushing.
On pushes to `main` or version tags, it publishes images to GitHub Container
Registry after tests pass.

## Troubleshooting

- `DP column needs declared bounds`: add `lower` and `upper` to `dp_params`.
- `epsilon outside allowed range`: use a value between `0.1` and `10.0`.
- `All rows were suppressed`: lower `k`, remove a high-cardinality
  quasi-identifier, or generalize QI columns more.
- `Deterministic mode requires SDSA_DEPLOYMENT_SALT`: set a hex salt before
  starting the server, for example
  `export SDSA_DEPLOYMENT_SALT=$(openssl rand -hex 32)`.
- `session not found or expired`: upload the file again; sessions are
  in-memory and expire after the configured TTL.

## Next Steps

- Read the full project overview in [README.md](README.md).
- Review the privacy model in [docs/privacy-model.md](docs/privacy-model.md).
- Customize field defaults with
  [`sdsa-policy.json.example`](sdsa-policy.json.example).
- Explore synthetic datasets in [samples/README.md](samples/README.md).
