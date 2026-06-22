FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend/src \
    SDSA_HOST=0.0.0.0 \
    SDSA_PORT=8000 \
    SDSA_FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app

RUN addgroup --system sdsa \
    && adduser --system --ingroup sdsa --home /app sdsa

COPY backend /app/backend
COPY frontend /app/frontend
COPY sdsa-policy.default.json /app/sdsa-policy.default.json
COPY sdsa-policy.json.example /app/sdsa-policy.json.example

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e /app/backend \
    && chown -R sdsa:sdsa /app

USER sdsa

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)).get('ok') is True"

CMD ["sh", "-c", "uvicorn sdsa.main:app --host \"${SDSA_HOST}\" --port \"${SDSA_PORT}\" --proxy-headers --forwarded-allow-ips \"${SDSA_FORWARDED_ALLOW_IPS}\""]
