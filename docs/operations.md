# Operations guide

How to run ShipIntel AI safely. Every setting below is an environment variable (a local `.env` file is
read as well; real environment variables win). Defaults are safe for a **local, single-user** run;
**production mode** adds hard requirements.

## 1. Modes

| | development (default) | production (`SHIPINTEL_ENV=production`) |
|---|---|---|
| API keys | optional; without them the API is **open** (a startup warning is logged) | **required**: the process refuses to start without `SHIPINTEL_API_KEYS` |
| `/docs`, `/openapi.json` | enabled | disabled unless `SHIPINTEL_ENABLE_DOCS=true` |
| Extraction isolation | worker processes (`SHIPINTEL_ISOLATION=process`) | same |

## 2. Configuration reference

**Authentication & abuse protection**

| Variable | Default | Meaning |
|---|---|---|
| `SHIPINTEL_API_KEYS` | – | `name1:secret1,name2:secret2` (or bare secrets). Each secret ≥ 24 chars or startup fails. Held only as SHA-256 digests, compared in constant time. Send as `X-API-Key` or `Authorization: Bearer`. |
| `SHIPINTEL_RATE_LIMIT_PER_MIN` | 60 | Per API key (or per client IP when auth is off); `0` disables. 429 + `Retry-After`. |
| `SHIPINTEL_AUTH_FAIL_LIMIT_PER_MIN` | 10 | Failed authentications per client IP before that IP is locked out (even with a correct key) for the rest of the window. |
| `SHIPINTEL_TRUST_PROXY` | false | Use the **rightmost** `X-Forwarded-For` hop as the client IP. Enable only behind exactly one proxy you control; otherwise clients can spoof it. |
| `SHIPINTEL_CORS_ORIGINS` | – | Comma-separated allow-list. No CORS headers at all when unset. No wildcard, no credentials. |
| `SHIPINTEL_HSTS` | false | Send `Strict-Transport-Security` (turn on when served over TLS). |

The rate limiter is in-process: with several replicas, each enforces its own limit. Put a shared limiter at the gateway for a global limit.

**Resource limits**

| Variable | Default | Meaning |
|---|---|---|
| `SHIPINTEL_MAX_UPLOAD_MB` | 10 | Enforced **while streaming** (also for chunked bodies): reading stops at the limit and the request answers 413. |
| `SHIPINTEL_MAX_PAGES` / `SHIPINTEL_MAX_TEXT_CHARS` | 100 / 1,000,000 | PDF pages / extracted characters (413 `TOO_MANY_PAGES` / `TEXT_TOO_LARGE`). |
| `SHIPINTEL_PROCESSING_TIMEOUT_S` | 30 | Per document. A cooperative deadline fires first; the worker is **killed** 5 s later if it is still running. 504 `PROCESSING_TIMEOUT`. |
| `SHIPINTEL_WORKERS` | 2 | Parallel extraction workers (= concurrency cap). |
| `SHIPINTEL_WORKER_MEMORY_MB` | 2048 | Address-space cap per worker (Linux). Exceeding it → 413 `RESOURCE_LIMIT_EXCEEDED`. |
| `SHIPINTEL_QUEUE_TIMEOUT_S` | 10 | Wait for a free worker before answering 503 `SERVER_BUSY` (+ `Retry-After`). |
| `SHIPINTEL_FUZZY_LABEL_BUDGET` | 300 | Distinct fuzzy label lookups per document (bounds CPU on label floods). |
| `SHIPINTEL_ISOLATION` | process | `inline` runs in the request thread: **tests/dev only** (no hard timeout, no memory cap). |

**OCR / NLP (operator policy)**

| Variable | Default | Meaning |
|---|---|---|
| `SHIPINTEL_OCR_ENABLED` / `SHIPINTEL_NLP_ENABLED` | false | Clients can pass `?ocr=false` / `?nlp=false` to switch a feature **off** for one request; `?ocr=true` is refused with 403 `FEATURE_DISABLED` unless the operator enabled it. |
| `SHIPINTEL_OCR_MAX_PIXELS` | 25,000,000 | Pixel cap per rendered page. The DPI is lowered to fit; below `ocr_min_dpi` (100) the page is refused (413 `PAGE_TOO_LARGE`). A tiny PDF can declare a huge page, so the declared size is never trusted. |
| `SHIPINTEL_OCR_MAX_PAGES` | 20 | Pages needing OCR per document (413 `RESOURCE_LIMIT_EXCEEDED` beyond it). |
| `SHIPINTEL_OCR_TIMEOUT_S` | 60 | Tesseract time per page. |
| `SHIPINTEL_OCR_TOTAL_TIMEOUT_S` | 120 | OCR time per document (504 `PROCESSING_TIMEOUT`). |
| `SHIPINTEL_OCR_DPI` | 200 | Render resolution (reduced automatically to respect the pixel cap). |
| `SHIPINTEL_OCR_LANG` | eng | Tesseract language(s). |
| `SHIPINTEL_TESSERACT_CMD` | – | Full path to the Tesseract binary (needed on Windows). |
| `SHIPINTEL_SPACY_MODEL` | en_core_web_sm | Model used when NLP is enabled. |

**Logging**

| Variable | Default | Meaning |
|---|---|---|
| `SHIPINTEL_LOG_LEVEL` | INFO | |
| `SHIPINTEL_LOG_FORMAT` | text | `json` for log shippers. |

**UI**: `SHIPINTEL_API_URL` + `SHIPINTEL_API_KEY` (operator-set; users cannot pick a target), `SHIPINTEL_UI_MAX_HISTORY` (default 10).

## 3. Endpoints for operators

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | **Liveness**: process is up (cheap; never spawns subprocesses). |
| `GET /ready` | none | **Readiness**: ≥ 1 healthy worker; reports isolation mode and cached OCR availability. 503 when no worker is alive. |
| `GET /metrics` | API key (when auth is on) | Prometheus text: request counts/latency by method+path+status (unknown paths collapse to `other`), `auth_failures`, `auth_lockout`, `rate_limited`, `body_too_large`, extraction outcomes, worker `timeouts`/`crashes`/`busy`/`replaced`, `shipintel_workers_healthy`. |

**Suggested alerts**: `shipintel_workers_healthy < SHIPINTEL_WORKERS` for 5 min · rate of `worker_events_total{event="timeouts"}` or `crashes` > 0 sustained · 5xx ratio > 1% · `events_total{event="auth_lockout"}` spike (credential stuffing) · p95 `request_duration_seconds` on `/extract`.

## 4. Logs

One line per request (structured when `LOG_FORMAT=json`): `ts, level, request_id, method, path, status, duration_ms, client, principal`. The request ID is returned as `X-Request-ID`; a caller-supplied ID is honoured only if it matches `[A-Za-z0-9._-]{8,64}` (no log injection).
**Never logged**: document text, extracted values, filenames, API keys, exception messages (only exception *types* and stack frames). A test asserts this.

## 5. Running

```bash
# development (open API on localhost)
uvicorn app.api:app --host 127.0.0.1 --port 8000 --no-access-log --no-server-header

# production-like
export SHIPINTEL_ENV=production
export SHIPINTEL_API_KEYS="ui:$(openssl rand -hex 24),partner:$(openssl rand -hex 24)"
uvicorn app.api:app --host 127.0.0.1 --port 8000 --no-access-log --no-server-header
```
Terminate TLS and (for the UI) authentication at a reverse proxy. `docker compose up` (see `docker-compose.yml`) runs both services with a read-only root filesystem, all capabilities dropped, `no-new-privileges`, memory/PID limits and loopback-only ports. The container image has not been built in the authoring environment: CI builds, lints (hadolint) and scans (Trivy) it.

## 6. Key rotation

Configure the new key next to the old one (`SHIPINTEL_API_KEYS=old:...,new:...`), roll clients over, then remove the old entry and restart. Keys can be revoked individually by removing their entry.

## 7. Incident runbook (short)

| Symptom | Likely cause | Action |
|---|---|---|
| Many 504 | A pathological document or an undersized `PROCESSING_TIMEOUT_S` | Check `timeouts` metric and request IDs; a killed worker is replaced automatically; do **not** raise the timeout to hide it. |
| 503 `SERVER_BUSY` | All workers busy | Raise `SHIPINTEL_WORKERS` (mind CPU/RAM) or rate-limit upstream. |
| 429 `RATE_LIMITED` from one key | Client loop | Contact the key owner; lower their limit at the gateway. |
| `auth_lockout` spike | Key guessing | Block the source at the proxy; rotate keys if any success followed failures. |
| `workers_healthy` < configured | Native crash / OOM kills | Check `crashes` and container memory limit; the pool respawns workers. |
| Startup fails with `SHIPINTEL_API_KEYS` message | Production mode without keys | Set keys (≥ 24 chars). |

## 8. Backups / disaster recovery

The service is **stateless**: no database, no uploads on disk, results only in HTTP responses. Back up configuration (`.env`/secrets manager) and the container image tag. Recovery = redeploy.
