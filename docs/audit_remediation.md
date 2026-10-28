# Audit remediation report

Every finding from the audit of the original `shipintel-ai.zip`, what was changed, which tests lock the
fix in, and how it was verified. "Before" numbers were measured on the **original ZIP**, "after" on the
fixed tree, with the same script, on the same single-CPU machine. Lines of evidence: unit/regression tests,
adversarial tests, live runs against real `uvicorn`/`streamlit` processes, and a clean-room CI run from the
hash-pinned lockfiles.

**Scope caveat:** the author of the code performed both the audit and the fixes. See
[security_review_checklist.md](security_review_checklist.md) for the independent-review package. Nothing here
claims the system is secure, only that these specific findings were reproduced, fixed and re-tested.

## 1. Roadmap status

| # | Roadmap step | Status |
|---|---|---|
| 1 | Fix S1 (ReDoS) + adversarial/performance tests | **Done** — `tests/test_adversarial.py` sweeps every compiled regex and 10 pipeline floods |
| 2 | Server-side policy and body-size limits (S3–S5) | **Done** |
| 3 | Silent-wrong-value bugs (B1–B4, B5–B9) + regression tests | **Done** — `tests/test_regressions.py` |
| 4 | Authentication, rate limiting, request timeouts | **Done** — API keys, lockout, rate limits, hard-kill timeouts, concurrency cap. Residuals in §5 |
| 5 | Docker, CI, lockfile, `pip-audit` in CI | **Done, Docker not built here** — lockfiles install from hashes; CI pipeline passes locally; image unverified (no Docker available) |
| 6 | UI items (S6, S7), then logging and monitoring | **Done** — `/ready`, `/metrics`, JSON logs, request IDs |
| 7 | OCR accuracy evaluation and independent review | **OCR evaluation done** (29 documents × 3 degradation levels). **Independent review NOT done** (cannot be self-performed); package prepared |

## 2. Findings → fixes

| ID | Original severity | Fix | Locked in by | Verified |
|---|---|---|---|---|
| **S1** ReDoS in `_REF_INLINE`, `_CARGO_INLINE` | HIGH | Patterns rewritten so every optional part starts with a distinct literal (linear); runs of ≥4 spaces collapsed in `clean_text`; hard kill in worker | `test_no_regex_is_super_linear` (29 patterns × 17 inputs), `test_regex_cost_grows_roughly_linearly`, `test_pathological_documents_finish_quickly` | 16 KB attack: **7.75 s → 0.00 s**; `/health` during a heavy request **5.0 s → 1.2–5.7 ms** (live) |
| **S2** Linear CPU amplification (≈10 ms/KB) | MEDIUM | Fuzzy-label memo + per-document budget; cooperative deadline; process isolation with hard timeout; worker cap with 503 backpressure; rate limit | `test_fuzzy_label_budget_bounds_the_work`, `test_deadline_stops_a_large_document`, `test_api_timeout_returns_504...`, sandbox tests | ~930 KB label flood: **13.5 s → 1.1 s**; unique-label flood **14.0 s → 1.0 s** |
| **S3** Chunked upload bypasses size guard | MEDIUM | Pure-ASGI middleware counts bytes while streaming and stops reading at the limit (+ `Content-Length` pre-check) | `test_chunked_upload_is_cut_off_at_the_limit`, `test_declared_oversize_is_rejected...` | 150 MB chunked: server read **150.8 MB → 10.6 MB** (413); live: 413 in 0.04 s |
| **S4** Anonymous client can enable OCR/NLP | MEDIUM | `resolve_feature`: server policy decides; clients may only switch OFF; `true` → 403 `FEATURE_DISABLED` | `test_client_cannot_enable_ocr_or_nlp...`, `test_resolve_feature_truth_table` | `?ocr=true` anonymous: **200 (OCR ran) → 403** |
| **S5** Unbounded OCR render | MEDIUM | Pixel cap (default 25 Mpx, DPI reduced to fit, refuse below 100 DPI), page-count and total-time caps, grayscale render without PNG round trip, per-worker `RLIMIT_AS` | `test_ocr_render_dpi_is_reduced...`, `test_ocr_refuses_too_many_pages`, `test_memory_cap_turns_runaway_allocation...` | 3000×3000 pt page: peak RSS **+461 MB → +152 MB**; 14,400 pt page: **~4.8 GB → refused in 0.00 s**; OCR accuracy unchanged (same trial before/after) |
| **S6** UI "API URL" SSRF-class sink | MEDIUM* | Free-text field removed; only operator `SHIPINTEL_API_URL` (validated http/https) | `test_ui_has_no_user_controlled_api_url`, `test_api_url_must_be_http` | No text input in sidebar |
| **S7** Document text rendered as Markdown | LOW | Document-derived strings shown with `st.text`/`st.code`; `unsafe_allow_html` removed from the app; `md_escape` for labels | `test_document_text_is_never_rendered_as_markdown`, `test_app_never_uses_unsafe_html`, `test_history_buttons_escape...` | AppTest with a crafted document |
| **S8** No auth / rate limiting / TLS | MEDIUM* | API keys (digest-only, constant-time, ≥24 chars), pre-body auth, failed-auth lockout, sliding-window rate limit, production mode refuses to start without keys | `tests/test_api_security.py` (≈45 tests) | Live: 401/200, lockout, exactly 60 allowed then 429 in a burst |
| **S9** `/health` spawns Tesseract each call | LOW | Liveness never spawns; OCR availability cached 60 s (in `/ready`) | `test_ready_and_metrics` | 14.3 → 1.6 ms/call (OCR enabled) |
| **S10** `pytest<9` pin blocked CVE-2025-71176 fix | LOW | Pin relaxed (`>=8.4,<10`); lock resolves pytest **9.1.1** | CI `pip-audit` | `pip-audit`: **no known vulnerabilities** in runtime and dev locks |
| **S11** No security headers; non-JSON 404/405; docs public | INFO | Headers on every response (CSP `default-src 'none'`, nosniff, DENY, no-store, …); consistent JSON errors; docs off in production | `test_security_headers_on_every_response`, `test_unknown_route_and_wrong_method...`, `test_docs_are_disabled_in_production` | 0/4 → 4/4 headers |
| **B1** Ranges collapsed to one value | MEDIUM | Date ranges / multiple dates and quantity ranges / multiple quantities → `null`, `needs_review`, `DATE_RANGE` / `MULTIPLE_DATES` / `QUANTITY_RANGE` / `QUANTITY_MULTIPLE` | 14 tests in `test_regressions.py` | `12-15 March 2025`: **15 Mar → null**; `45,000 - 50,000 MT`: **50,000 → null** |
| **B2** Negative sign dropped | MEDIUM | Sign parsed and preserved; `NONPOSITIVE_QUANTITY` fires | `test_b2_*` | `-500 MT`: **+500 → invalid** |
| **B3** `Port of Spain` → `Spain` | MEDIUM | Gazetteer keeps "port of"; full name tried before generic prefix removal; 7 real "Port …" names added; lookups cached | `test_b3_*` | **`Spain` → `Port of Spain`**; a bare country is flagged, not mapped |
| **B4** Unrelated edit rejected on flagged docs | MEDIUM | Date-order check only when a date field is edited; `ExtractedRecord` no longer embeds it | `test_b4_*` | **REJECTED → saved** |
| **B5** Wrong evidence offsets / non-verbatim `raw_value` | LOW-MED | Inline quantity span from the real substring; `raw_value` is the verbatim value; mandatory separator before cargo name | `test_b5_*` (invariant over all 150 documents) | 0 violations for the best candidate's evidence |
| **B6** Oversized text → HTTP 500 | LOW | `TextTooLargeError` (413 `TEXT_TOO_LARGE`) | `test_b6_*`, `test_text_over_the_character_limit_is_413...` | **500 → 413** (audit observed the 500; the original code could not be configured to trigger it in my script) |
| **B7** Reference taken from prose | LOW | Must be the first token of the value | `test_b7_*` | `see clause 12345` **→ null** |
| **B8** `Ust-luga` casing | LOW | Title-case per `-`/`/` part | `test_b8_*` | `Ust-Luga` |
| **B9** `1,234 MT` read as 1234 | INFO | Accepted and documented as an assumption (dot-style `1.234` stays flagged) | `test_b9_*` | — |
| mypy debt (22 errors), `rules.py` size, session growth, security headers (P3) | LOW | All typed (mypy clean on 31 files); `rules.py` split into `rules/{labels,values,inline}.py` (largest module 519 lines vs 1,007); UI history capped (default 10) | CI `mypy`; `test_session_history_is_capped` | — |

\*Deployment-dependent: only a risk when the API/UI is shared with untrusted users.

## 3. Additional defects found *during* remediation

Fixing and re-testing surfaced issues the original audit did not list:

| # | Defect | Resolution |
|---|---|---|
| X1 | `_PORT_SUFFIX` and `_VESSEL_CUT` were quadratic in isolation (I had dismissed them as unreachable because `collapse_ws()` runs first) | Rewritten as linear patterns; the regex sweep test would now catch a reintroduction |
| X2 | An inline guess silently overrode a label-derived "multiple dates" flag | Label-derived ambiguity now outranks inline candidates (`AMBIGUITY_CODES`) |
| X3 | Inline cargo regex could split `barrels` into `barrel` + `s`, yielding a one-character-short evidence span | Separator before the cargo name is mandatory |
| X4 | **A worker that died while idle made the next request fail (HTTP 422)** — found only by a precise live `SIGKILL` test | Dead idle workers are replaced and the job retried (never retried after being sent: a poison document must not kill every worker). Live: request after kill is 200, `dead_idle=1`, `crashes=0` |
| X5 | `TextFormatter` (the default log format) would have appended exception **messages** to logs on any `exc_info` log call | `formatException` emits type + frames only; test added (nothing logged with `exc_info` today, so this was latent) |
| X6 | The local CI run found that `scripts/evaluate_ocr.py` failed `ruff format --check` | Formatted; CI would have failed on it |
| X7 | OCR measurably lowers accuracy (F1 97.2% → 84.1% on clean renderings) but OCR values were scored like digital text | OCR evidence gets a −0.15 score penalty and an `OCR_TEXT` note (values untouched) |

## 4. Process notes (honest)

- Two of my own edits misfired: a greedy regex edit deleted four functions from `normalizers.py` (caught immediately by the
  test suite and restored from the pristine audit copy), and several scripted string replacements silently did nothing after
  `ruff format` re-wrapped the target lines (found by tests/assertions; later edits assert that the pattern was found).
- The existing synthetic benchmark did **not** exercise any of B1–B3, B7, B8 (the evaluation numbers were bit-identical before
  and after). The fixes are protected by dedicated regression tests, not by the benchmark.
- Several of my first tests were wrong, not the code (an invalid multipart body, a handler attached before `setup_logging`
  reset it, a "secret" that sat on the source line of the `raise`). Where a test failure was not understood, it was investigated
  before changing anything.

## 5. Residual risks (not fixed — by design or by environment)

1. **Independent review not done.** 2. **Docker image never built here** (no Docker); CI builds, lints and scans it.
3. Rate limiter is **per process**; use a gateway limiter for a global limit. 4. **No TLS and no UI login** in the app: use a
reverse proxy. 5. **Slow-body (slowloris)** protection is the proxy's job. 6. Isolation is a process boundary with a memory cap,
**not a sandbox** (add seccomp/gVisor for hostile input); `RLIMIT_AS` is Linux-only; Windows/macOS were not tested.
7. `pip-audit` covers PyPI advisories only; the container image needs a scanner (Trivy in CI). 8. spaCy and its model are
**not locked**. 9. Heuristic scores remain **uncalibrated**; wrong values are not reliably flagged. 10. OCR was evaluated on
**rendered** scans only. 11. `sandbox.py` coverage (77%) under-reports because worker-process code is not seen by the coverage tool.

## 6. Live verification (real `uvicorn`, production mode, 2 workers)

| Check | Result |
|---|---|
| Production without `SHIPINTEL_API_KEYS` | Refuses to start with a `ConfigError` |
| No key / wrong key / right key | 401 / 401 / 200 |
| `/docs` in production; `/metrics` without key | 404; 401 |
| `?ocr=true` with a valid key, OCR off | 403 `FEATURE_DISABLED` |
| `/health` while a ~940 KB document is processed (1.56 s) | **1.2–5.7 ms** (idle: 1.1–1.2 ms) |
| 150 MB chunked upload | **413 in 0.04 s**, 17.5 MB sent before the server cut the connection |
| `SIGKILL` of a worker, then 3 requests | 200, 200, 200; worker respawned; `dead_idle=1`, `replaced=1`, `crashes=0`, `workers_healthy=2` |
| Limit 60/min, 1 heavy + 70 more requests | exactly 60 × 200 (1 + 59), then **11 × 429** |
| Logs | 78 JSON request lines, **0** lines containing document content |
