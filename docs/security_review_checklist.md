# Security review package (for an INDEPENDENT reviewer)

**Status: an independent review has NOT been performed.** The author of this code also performed the
audit and the fixes described in `audit_remediation.md`; that is a useful first pass, not a
substitute. This document makes an external review fast and specific.

## 1. Scope and assets

| Asset | Where | Notes |
|---|---|---|
| Uploaded shipping documents | RAM only (request → worker process → response) | Never written to disk by the app; not logged. |
| API keys | Environment / secrets manager | Held only as SHA-256 digests in memory. |
| Extracted fields | HTTP response / browser session | May be commercially sensitive. |

**Trust boundaries:** (1) Internet/proxy → API (`HardeningMiddleware`); (2) API process → worker process (pickled job/result over a pipe; job targets are allow-listed to `app.*`); (3) worker → PyMuPDF/Tesseract (native code, untrusted input); (4) UI → API (operator-configured URL + key); (5) document text → UI rendering.

## 2. Threats considered and where they are controlled

| Threat | Control | Test |
|---|---|---|
| Unauthenticated use / brute-forced keys | API keys (≥ 24 chars, constant-time check), failed-auth lockout per IP, auth *before* the body is read | `test_api_security.py` (auth, lockout, "checked before body is read") |
| Resource exhaustion by request size | Streaming size limit incl. chunked bodies; `Content-Length` pre-check | `test_chunked_upload_is_cut_off_at_the_limit` |
| CPU exhaustion by crafted text (ReDoS, label floods) | Linear regexes, whitespace-run cap, fuzzy-label memo + budget, cooperative deadline, **hard kill** of worker | `test_adversarial.py` (every compiled regex × pathological inputs; pipeline floods), `test_sandbox.py` |
| Memory exhaustion (OCR page size, allocations) | Pixel cap + DPI reduction, OCR page/time caps, per-worker `RLIMIT_AS` | `test_sandbox.py::memory_cap`, OCR bound tests |
| Native-parser crash | Process isolation; worker replaced; pool stays up | `test_a_native_crash_is_contained`; 600-mutation PDF fuzz (audit) |
| Client enabling expensive features | Server policy: client may only switch features **off** | `test_client_cannot_enable_ocr_or_nlp...` |
| Rate abuse | Per-client sliding window, bounded memory | `test_rate_limit_*`, `test_rate_limiter_window_and_bounded_memory` |
| Spoofed client IP | `X-Forwarded-For` ignored unless `TRUST_PROXY`; rightmost hop only | `test_client_ip_ignores_forwarded_header...` |
| SSRF via UI | No user-controlled URL; operator `SHIPINTEL_API_URL` validated as http(s) | `test_ui_has_no_user_controlled_api_url` |
| Markup injection in UI | Document text rendered with `st.text`/`st.code`; no `unsafe_allow_html` anywhere | `test_document_text_is_never_rendered_as_markdown`, `test_app_never_uses_unsafe_html` |
| CSV/spreadsheet formula injection | Risky leading characters prefixed with `'` | `test_export.py` |
| Information leakage via errors/logs | Generic 500, exception types only, no document content in logs | `test_unexpected_error_log_has_type_only`, `test_logs_contain_request_ids_but_never_document_content` |
| Header injection / log injection | `X-Request-ID` validated against `[A-Za-z0-9._-]{8,64}` | `test_request_id_is_echoed...` |
| Clickjacking / MIME sniffing / caching | `X-Frame-Options`, CSP `default-src 'none'`, `nosniff`, `no-store` | `test_security_headers_on_every_response` |
| Unsafe production config | Production mode refuses to start without keys; docs disabled | `test_production_refuses_to_start_without_keys` |
| Vulnerable dependencies | Hash-pinned locks, `pip-audit` in CI (also weekly), Dependabot | CI `security` job |

**Not applicable:** SQL/NoSQL injection, session/JWT/CSRF issues (no database, no cookies, no sessions; API-key header auth), file download authorization (nothing is stored), multi-tenant data isolation (stateless).

## 3. Residual risks the reviewer should challenge

1. **Rate limiter is per process.** Several replicas multiply the limit. Use a gateway limiter for a global cap.
2. **Slow-body (slowloris) attacks** are not handled by the app; uvicorn/h11 has no request-read timeout. Terminate at a proxy with `client_body_timeout`/`client_header_timeout`.
3. **TLS and UI authentication are not built in.** The UI has no login; protect it with a reverse proxy/SSO. API keys travel in headers: use TLS.
4. **Native code surface:** MuPDF and Tesseract parse untrusted input. Isolation limits the blast radius (separate process, memory cap) but is not a sandbox: add container seccomp/gVisor or a dedicated low-privilege host for hostile input. `RLIMIT_AS` is Linux-only.
5. **Worker memory cap vs. Tesseract:** the cap is inherited by the Tesseract subprocess; very large legitimate pages may need `SHIPINTEL_WORKER_MEMORY_MB` raised.
6. **Pickle over the worker pipe** is used between two processes of the same application (job targets allow-listed). If workers were ever moved to separate hosts, replace it with a schema-based format.
7. **`pip-audit` uses PyPI's advisory data only;** native-library CVEs (MuPDF, Tesseract, OS packages in the image) need an image scanner (Trivy in CI).
8. **Heuristic scores are uncalibrated,** and wrong values are not reliably flagged (see the evaluation report): do not use scores as a security or compliance control.
9. **Docker image was never built here.** Review `Dockerfile`/`docker-compose.yml` and the CI `docker` job output.
10. **Extraction can be steered by a crafted document** (it is untrusted input by definition). Values carry evidence and a review step; they are not authoritative.

## 4. How to reproduce every check

```bash
pip install --require-hashes -r requirements-dev.lock
python -m pytest                                   # unit, API, security, sandbox, UI, adversarial
coverage run --branch --source=app -m pytest && coverage report --fail-under=85
ruff check app tests scripts && ruff format --check app tests scripts
mypy app
bandit -r app -ll
pip-audit -r requirements.lock --require-hashes --no-deps --disable-pip
python scripts/evaluate.py --split dev ; python scripts/evaluate.py --split test
python scripts/evaluate_ocr.py                     # needs Tesseract
bash scripts/ci_local.sh                           # everything above except Docker, in one go
```
Live checks used in the audit: `curl`/chunked upload against a running `uvicorn`, concurrent `/health`
latency during a hostile upload, `Content-Length` bypass, `?ocr=true` as an anonymous client. See
`audit_remediation.md` for the before/after results.
