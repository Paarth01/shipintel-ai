# ShipIntel AI

[![CI](https://github.com/Paarth01/shipintel-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Paarth01/shipintel-ai/actions/workflows/ci.yml)

Maritime shipping **document intelligence** prototype: upload a PDF or TXT shipping document and get
structured fields back — with the **evidence** for every value, **validation warnings**, a
**human review** step, and JSON/CSV export. Local-first: no paid APIs and no outbound network calls;
documents are processed in memory in isolated worker processes and never written to disk.

> **Status & honesty notes (please read)**
> - An **independent portfolio project**, not an official product of any company.
> - Extraction is a **rule-based baseline** (label dictionaries + regular expressions + a small port
>   gazetteer), **not** a trained model. An optional spaCy NER adapter exists and is evaluated.
> - All sample documents and ground truth are **synthetic**. There is **no real-world accuracy claim**.
> - The "heuristic score" is a rule-confidence indicator, **not a calibrated probability**.
> - A security audit of this project was performed and its findings fixed
>   ([docs/audit_remediation.md](docs/audit_remediation.md)). It was done by the code's author, so an
>   **independent review has not happened**; [docs/security_review_checklist.md](docs/security_review_checklist.md)
>   prepares one. The Dockerfile was written and statically checked but **not built** in the authoring
>   environment (no Docker); CI builds it.

## What it extracts

`vessel_name`, `origin_port`, `destination_port`, `cargo_type`, `cargo_quantity`, `cargo_unit`,
`loading_date`, `discharge_date`, `document_reference`, `counterparty`.

Each field returns: `value`, `raw_value`, `status` (`extracted | normalized | missing | invalid |
needs_review | human_corrected`), `heuristic_score`, `evidence` (page, character offsets, snippet, label,
method) and `warnings`. **Missing, ambiguous, ranged or invalid values are `null` — never guessed**
(`12-15 March 2025`, `45,000 - 50,000 MT`, `-500 MT`, `03/04/2025` all return `null` with a warning).

## Results (synthetic data, rule-based baseline)

| Evaluation | Documents | Precision | Recall | F1 | How to read it |
|---|---|---|---|---|---|
| Dev split (templates D1–D6) | 96 | 100.0% | 99.1% | 99.6% | Rules were **tuned on this split** — optimistic |
| **Held-out templates T1–T3, first run (rules frozen)** | 54 | 99.6% | 63.1% | **77.2%** | The honest generalisation estimate |
| Held-out, after generic fixes informed by its errors | 54 | 99.8% | 96.7% | 98.2% | **Not clean held-out** (its errors were studied) |
| **OCR** on rendered synthetic scans, clean / mild / heavy degradation | 29 | 98.3 / 100 / 95.0% | 73.5 / 72.7 / 55.5% | **84.1 / 84.2 / 70.0%** | vs 97.2% for the same docs read as text; *rendered*, not photographed, scans |

OCR costs ~13 F1 points even on clean renderings, mostly as **missing** values (precision stays high),
and OCR-derived values are scored lower and carry an `OCR_TEXT` note. Details, per-field tables, the
spaCy comparison and error analysis: [docs/evaluation_report.md](docs/evaluation_report.md);
raw outputs: [docs/eval_artifacts/](docs/eval_artifacts/).

## Quick start

Requires Python 3.11 or 3.12.

```bash
python3 -m venv .venv && source .venv/bin/activate         # Windows: py -3.12 -m venv .venv ; .venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements-dev.lock      # exact, hash-verified versions (dev + test tooling)
# runtime only:   pip install --require-hashes -r requirements.lock
# loose ranges:   pip install -r requirements-dev.txt
python -m pytest                                           # 293 tests
```

Run the API (Swagger at http://127.0.0.1:8000/docs in development) and the UI:
```bash
uvicorn app.api:app --host 127.0.0.1 --port 8000 --no-access-log --no-server-header
streamlit run app/ui.py                                    # http://localhost:8501
```
The UI runs the pipeline in-process unless the **operator** sets `SHIPINTEL_API_URL` (+ `SHIPINTEL_API_KEY`):
users cannot pick a target URL. Use the sidebar **sample picker** to try synthetic documents.

```bash
curl -F "file=@data/samples/SI-0001.txt" "http://127.0.0.1:8000/extract?include_text=false"
# with authentication enabled:
curl -H "X-API-Key: $KEY" -F "file=@data/samples/SI-0001.txt" http://127.0.0.1:8000/extract
```

**Production-like run** (refuses to start without keys; docs off; hard timeouts and memory caps on):
```bash
export SHIPINTEL_ENV=production SHIPINTEL_API_KEYS="ui:$(openssl rand -hex 24)"
uvicorn app.api:app --host 127.0.0.1 --port 8000 --no-access-log --no-server-header
# or:  cp .env.example .env  (set the keys)  &&  docker compose up --build
```
Terminate TLS and (for the UI) authentication at a reverse proxy. Full operator guide:
[docs/operations.md](docs/operations.md).

Regenerate data and re-run evaluations:
```bash
python scripts/generate_synthetic_data.py            # 150 synthetic docs, seed 42 (deterministic)
python scripts/evaluate.py --split dev               # tuned split
python scripts/evaluate.py --split test [--nlp]      # held-out templates (run sparingly)
python scripts/evaluate_ocr.py                       # OCR accuracy on rendered scans (needs Tesseract)
bash scripts/ci_local.sh                             # lint, types, security, tests+coverage, determinism
```

## Security & reliability features

| Area | What the code does |
|---|---|
| Authentication | API keys (≥ 24 chars, stored as SHA-256 digests, constant-time check), checked **before** the upload is read; failed-auth lockout per IP; production mode refuses to start without keys |
| Abuse limits | Per-key/IP rate limit (429 + `Retry-After`); streaming upload limit that also stops **chunked** bodies at the limit; page/text/OCR caps |
| Isolation | Extraction runs in worker processes: **hard timeout** (killed + replaced), memory cap, crash containment, bounded concurrency with 503 backpressure, transparent recovery from workers that died while idle |
| Server policy | OCR/NLP are operator settings; a request can switch them **off**, never on (403 otherwise) |
| Hardening | Security headers, no CORS unless allow-listed, docs off in production, consistent JSON errors, no stack traces or document text in logs |
| Observability | `/health` (liveness), `/ready`, `/metrics` (Prometheus text), JSON logs with request IDs |
| Supply chain | Hash-pinned lockfiles, `pip-audit` in CI (also weekly), Dependabot, `bandit`, `mypy`, coverage gate |
| UI | No user-controlled URLs; document text never rendered as Markdown/HTML; capped session history |

## API

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness |
| `GET /ready` | none | Readiness (workers alive) |
| `GET /metrics` | key (if enabled) | Prometheus metrics |
| `POST /extract` | key (if enabled) | Multipart `file` (+ `ocr`/`nlp` = `false` to disable, `include_text`) → `ExtractionResult` |

Errors are `{"error": {"code", "message"}}`: `400 EMPTY_FILE` · `401 UNAUTHORIZED` · `403 FEATURE_DISABLED` ·
`413 FILE_TOO_LARGE / TEXT_TOO_LARGE / TOO_MANY_PAGES / PAGE_TOO_LARGE / RESOURCE_LIMIT_EXCEEDED` ·
`415 UNSUPPORTED_FILE_TYPE` · `422 UNREADABLE_DOCUMENT / PDF_ENCRYPTED / SCANNED_PDF_NO_TEXT / NO_TEXT_FOUND /
DOCUMENT_PROCESSING_FAILED / INVALID_REQUEST` · `429 RATE_LIMITED` · `503 SERVER_BUSY / OCR_UNAVAILABLE` ·
`504 PROCESSING_TIMEOUT` · `500 INTERNAL_ERROR` (nothing leaked).

## Optional extras

**OCR** — install Tesseract (`apt install tesseract-ocr`, `brew install tesseract`, or the Windows installer;
set `SHIPINTEL_TESSERACT_CMD` on Windows), `pip install -r requirements-ocr.txt`, then set
`SHIPINTEL_OCR_ENABLED=true`. Pages are rendered in grayscale under a pixel cap, with page-count and time limits.
Without OCR a scanned PDF returns `SCANNED_PDF_NO_TEXT`.
**spaCy NER** — `pip install -r requirements-nlp.txt && python -m spacy download en_core_web_sm`, then
`SHIPINTEL_NLP_ENABLED=true`. Suggestions only fill empty fields and are always marked `needs_review`.

## Project layout

```
app/
  api.py              # FastAPI app factory + HardeningMiddleware (auth, limits, headers, logging)
  sandbox.py          # isolated worker pool (hard timeout, memory cap, crash containment)
  security.py         # API-key auth, rate limiter, server-side feature policy
  pipeline.py         # validate -> extract text -> clean -> rules -> normalise -> validate -> package
  extractors/         # pdf_text.py, txt_text.py, ocr.py, nlp.py, rules/{labels,values,inline}.py
  normalizers.py gazetteer.py evidence.py validators.py schemas.py exporters.py
  config.py errors.py deadline.py metrics.py logging_config.py textnorm.py
  ui.py uihelpers.py client.py        # Streamlit UI
scripts/              # generate_synthetic_data.py, evaluate.py, evaluate_ocr.py, ci_local.sh
data/                 # samples/ (150 synthetic docs), annotations/ (dev.jsonl, test.jsonl)
tests/                # 293 tests: unit, API/security, sandbox, adversarial, UI, evaluation
docs/                 # operations, architecture, evaluation, audit remediation, dataset card, ...
Dockerfile docker-compose.yml .github/workflows/ci.yml requirements*.txt requirements*.lock
```

## Documentation

[Operations](docs/operations.md) · [Architecture](docs/architecture.md) · [Evaluation report](docs/evaluation_report.md) ·
[Audit remediation](docs/audit_remediation.md) · [Security review package](docs/security_review_checklist.md) ·
[Dataset card](docs/dataset_card.md) · [Limitations & verification](docs/limitations_and_security.md) ·
[Demo script & resume notes](docs/demo_and_resume.md) · [Changelog](CHANGELOG.md)

## License

MIT (see `LICENSE`). Sample data is synthetic and free to use.
