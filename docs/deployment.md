# SDSA Deployment Guide

This guide describes the supported Docker deployment for SDSA.

## Architecture

SDSA is deployed as one FastAPI application container. The container serves both
the REST API and the static frontend. Uploaded data, parsed dataframes, HMAC
keys, and generated outputs live in process memory and expire after
`SDSA_SESSION_TTL`.

Production TLS termination and request controls should sit in front of the app.
This repository includes an nginx Compose profile for that role:

```text
browser
  -> nginx: TLS, upload cap, simple rate limits
  -> sdsa: FastAPI, static frontend, in-memory sessions
```

Run exactly one SDSA application process per deployment unless the session store
is replaced with shared storage. Multiple uvicorn workers or multiple replicas
will break the upload -> process -> download flow because sessions are in-memory.

## Local Container

```bash
cp .env.example .env
docker compose up --build
```

Open <http://127.0.0.1:8000/>.

## Production Compose

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Review `.env`. Set `SDSA_DEPLOYMENT_SALT` only if deterministic
   cross-session pseudonyms are required:

   ```bash
   openssl rand -hex 32
   ```

3. Add TLS files for nginx:

   ```text
   deploy/certs/fullchain.pem
   deploy/certs/privkey.pem
   ```

4. Start the deployment:

   ```bash
   docker compose -f compose.prod.yml up -d --build
   ```

5. Check health:

   ```bash
   curl -fsS https://YOUR_HOST/health
   docker compose -f compose.prod.yml ps
   docker compose -f compose.prod.yml logs -f sdsa
   ```

## Published Images

The Docker workflow publishes images to GitHub Container Registry on pushes to
`main` and on version tags:

```text
ghcr.io/defai-digital/sdsa:main
ghcr.io/defai-digital/sdsa:v1.1.0
ghcr.io/defai-digital/sdsa:sha-...
```

`compose.prod.yml` already names the GHCR image. To deploy a published image
instead of building on the host, remove or ignore the `build` block and keep:

```yaml
image: ghcr.io/defai-digital/sdsa:v1.1.0
```

Pull requests run pytest, Ruff, and a Docker image build without publishing.
Pushes to `main` and version tags publish the image after tests pass.

## Policy Override

To deploy a project-specific policy catalog, copy
`sdsa-policy.json.example` to `sdsa-policy.json`, edit it, and mount it into
the app container:

```yaml
volumes:
  - ./sdsa-policy.json:/app/sdsa-policy.json:ro
```

The compose files already include this volume as a commented example.

## Operational Notes

- Keep `SDSA_MAX_UPLOAD_BYTES` aligned with nginx `client_max_body_size`.
- Keep the app single-process while sessions are in memory.
- Do not mount persistent raw-data volumes into the app container.
- Set `SDSA_ALLOWED_CORS_ORIGINS` only when a separate frontend origin calls the
  API. Leave it empty for the bundled same-origin frontend.
- Put the service behind an authenticated network boundary if it handles
  regulated or confidential data.
- Logs are structured and scrub known raw-data fields, but column names and
  session metadata are still emitted.

## Updates and Rollback

Build and deploy a new image tag:

```bash
docker compose -f compose.prod.yml build
docker compose -f compose.prod.yml up -d
```

Rollback by changing the `image` tag in `compose.prod.yml` to the previous
release and running:

```bash
docker compose -f compose.prod.yml up -d
```
