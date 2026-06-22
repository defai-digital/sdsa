from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_runs_single_non_root_app_process():
    dockerfile = read_repo_file("Dockerfile")

    assert "FROM python:3.12-slim" in dockerfile
    assert "USER sdsa" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["sdsa-server", "start"]' in dockerfile
    assert "SDSA_HOST=0.0.0.0" in dockerfile
    assert "SDSA_FORWARDED_ALLOW_IPS=127.0.0.1" in dockerfile
    assert "--workers" not in dockerfile
    assert "gunicorn" not in dockerfile


def test_local_compose_uses_env_file_and_policy_mount_hint():
    compose = read_repo_file("compose.yml")

    assert "env_file:" in compose
    assert "- .env" in compose
    assert '"8000:8000"' in compose
    assert "./sdsa-policy.json:/app/sdsa-policy.json:ro" in compose


def test_production_compose_hardens_app_and_keeps_single_entrypoint():
    compose = read_repo_file("compose.prod.yml")

    assert "ghcr.io/defai-digital/sdsa:1.1.0" in compose
    assert "expose:" in compose
    assert '"8000"' in compose
    assert "read_only: true" in compose
    assert "/tmp:size=256m,mode=1777" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose
    assert "- ALL" in compose
    assert "pids_limit: 256" in compose
    assert "mem_limit: 1g" in compose
    assert "nginx:1.27-alpine" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose


def test_nginx_config_enforces_tls_upload_limits_and_rate_limits():
    nginx = read_repo_file("deploy/nginx/sdsa.conf")

    assert "return 301 https://$host$request_uri;" in nginx
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in nginx
    assert "client_max_body_size 300m;" in nginx
    assert "limit_req_zone $binary_remote_addr zone=sdsa_uploads" in nginx
    assert "limit_req_zone $binary_remote_addr zone=sdsa_api" in nginx
    assert "proxy_request_buffering off;" in nginx
    assert "X-Content-Type-Options nosniff" in nginx
    assert "proxy_pass http://sdsa:8000" in nginx


def test_env_template_documents_deployment_controls():
    env = read_repo_file(".env.example")

    for key in [
        "SDSA_SESSION_TTL",
        "SDSA_MAX_UPLOAD_BYTES",
        "SDSA_DEFAULT_K",
        "SDSA_ALLOWED_CORS_ORIGINS",
        "SDSA_DEPLOYMENT_SALT",
    ]:
        assert key in env

    assert "openssl rand -hex 32" in env


def test_cicd_workflow_tests_builds_and_publishes_container():
    workflow = read_repo_file(".github/workflows/docker.yml")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert '"v*"' in workflow
    assert "pytest" in workflow
    assert "ruff check src tests" in workflow
    assert "docker/build-push-action" in workflow
    assert "docker/login-action" in workflow
    assert "ghcr.io/${{ github.repository }}" in workflow
    assert "push: ${{ github.event_name != 'pull_request' }}" in workflow
