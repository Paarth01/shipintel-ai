# syntax=docker/dockerfile:1.7
# ShipIntel AI - API (default CMD) or UI (override command, see docker-compose.yml).
# Build:  docker build -t shipintel-ai .                 (add --build-arg WITH_OCR=true for Tesseract)
# NOTE: this file was written and statically checked but NOT built in the authoring environment
#       (no Docker available); CI builds it (see .github/workflows/ci.yml).
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
ARG WITH_OCR=false
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY requirements.lock requirements-ocr.lock ./
# --require-hashes: only the exact, hash-verified artefacts from the lock files can be installed
RUN python -m venv /opt/venv \
 && if [ "$WITH_OCR" = "true" ]; then \
      /opt/venv/bin/pip install --require-hashes -r requirements-ocr.lock; \
    else \
      /opt/venv/bin/pip install --require-hashes -r requirements.lock; \
    fi

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG WITH_OCR=false
# hadolint ignore=DL3008  (Debian package versions in the slim base image move with security updates; pinning would break rebuilds)
RUN if [ "$WITH_OCR" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
      && rm -rf /var/lib/apt/lists/*; \
    fi \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /tmp --shell /usr/sbin/nologin app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp \
    SHIPINTEL_ENV=production SHIPINTEL_LOG_FORMAT=json \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Code is owned by root and read-only to the runtime user.
COPY app ./app
COPY .streamlit ./.streamlit
COPY LICENSE README.md ./
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"
# Production mode refuses to start without SHIPINTEL_API_KEYS (see docs/operations.md).
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
