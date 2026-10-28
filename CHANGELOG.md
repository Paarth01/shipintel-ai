# Changelog

## 0.2.0 — audit remediation

**Security / reliability**
- Fixed a quadratic-time regex DoS (`_REF_INLINE`, `_CARGO_INLINE`; plus latent `_PORT_SUFFIX`, `_VESSEL_CUT`), capped whitespace runs,
  bounded fuzzy matching, added a cooperative deadline.
- Extraction now runs in isolated worker processes: hard timeout, memory cap, crash containment, concurrency cap with 503 backpressure,
  transparent replacement of workers that died while idle.
- API keys (digest-only, constant-time), failed-auth lockout, per-client rate limiting, streaming request-size limit (incl. chunked),
  server-side OCR/NLP policy (clients can only switch off), security headers, consistent JSON errors, docs disabled in production,
  production mode refuses to start without keys.
- OCR: pixel cap with DPI reduction, page/time caps, grayscale render (peak memory −67%), cached availability.
- Structured JSON logging with request IDs (never document content), `/ready`, `/metrics`.
- UI: removed the user-controlled API URL, no document text rendered as Markdown/HTML, capped session history.

**Correctness**
- Ranges/multiple dates and quantities, negative quantities, `Port of Spain`, reference-from-prose, hyphen casing, unrelated edits on
  flagged documents, evidence offsets, oversized-text status code (see `docs/audit_remediation.md`).

**Engineering**
- `rules.py` split into a package; mypy clean; split runtime/dev requirements; hash-pinned lockfiles; Dockerfile (unbuilt here),
  docker-compose, GitHub Actions CI (+ weekly `pip-audit`), Dependabot, `scripts/ci_local.sh`.
- OCR accuracy evaluation (`scripts/evaluate_ocr.py`); OCR evidence scored lower.
- Tests: 123 → 293 (regression, adversarial, security, sandbox, UI, logging, stub-based NLP).

## 0.1.0 — initial build
Rule-based extraction with evidence, validation, human review, JSON/CSV export, FastAPI + Streamlit, synthetic dataset and evaluation.
