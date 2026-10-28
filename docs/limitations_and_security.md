# Limitations and verification record

Security design, threats and residual risks: [security_review_checklist.md](security_review_checklist.md).
Findings and fixes: [audit_remediation.md](audit_remediation.md). Operator settings: [operations.md](operations.md).

## What was verified (all actually run)

Environment: Linux VM (1 CPU), Python 3.12.3, hash-pinned dependencies (PyMuPDF 1.28.2, FastAPI 0.143.1, Starlette 1.8.0,
Streamlit 1.66.0, pytest 9.1.1), Tesseract 5.3.4.

* **`pytest`: 293 passed** both in the working environment and in a *clean* environment built only from
  `requirements-dev.lock` with `--require-hashes`, running a clean copy of the project. Branch coverage **92%** (gate 85%):
  `api.py` 98%, `pipeline.py` 97%, `nlp.py` 97% (stub-model tests; spaCy is not needed), `security.py` 96%, `labels.py` 95%,
  `inline.py` 93%, `normalizers.py` 90%, `config.py` 87%, `values.py` 85%, `ocr.py` 82%, **`sandbox.py` 77%** (the code that
  runs *inside* worker processes is invisible to the coverage tool; it is exercised by the sandbox tests and live runs).
* **Local CI** (`scripts/ci_local.sh`, mirrors `.github/workflows/ci.yml` except the Docker job): ruff check + format, **mypy
  (31 files, no issues)**, bandit (no medium/high), `pip-audit` on both lockfiles (**no known vulnerabilities**), tests + coverage
  gate, generator determinism.
* **Live servers:** a real `uvicorn` in production mode (auth, rate limit, chunked 150 MB upload, `/health` during a heavy
  request, `SIGKILL` of a worker, startup refusal without keys, log hygiene) and a real `streamlit run` boot; UI behaviour
  checked with Streamlit's headless `AppTest`, **not by a person in a browser**.
* **Evaluations:** [evaluation_report.md](evaluation_report.md) (rules, spaCy comparison, **OCR on rendered scans**).
* **Fuzz:** 600 mutated PDFs (audit): no crash, hang or untyped exception. (Re-run was not repeated after the changes; the
  worker pool now contains any such fault.)

## NOT verified

Windows/macOS execution · the **Docker image and compose file** (no Docker here; CI builds, hadolint-lints and Trivy-scans
them) · UI look and feel in a real browser · OCR on *real* scans (only rendered synthetic ones) · load/soak testing beyond the
single-request stall demonstration · multi-replica behaviour · an **independent security review** · accessibility.

## Functional limitations

* **Rule-based and layout-sensitive.** New wording/layouts need new rules (77.2% F1 on the first unseen-template run).
* **Ports:** a built-in list of 84 ports (not UN/LOCODE). Unknown ports are accepted from labelled fields (flagged) but not
  from prose.
* **One value per field**; multi-leg voyages, several cargoes or vessels are not modelled. Ranges and multiple values are
  returned as `null` + warning rather than modelled.
* **Dates:** no two-digit years or time zones; ambiguous numeric dates are `null`. **Units:** `tons` ambiguous (flagged),
  no conversion; comma-thousands assumed.
* **English only.** PDFs: text layer (tables become lines); scanned pages need OCR (measured: precision stays high, recall
  drops 20–40 points on rendered scans).
* **Heuristic score uncalibrated**; wrong values are not reliably flagged.
* **No persistence** (stateless by design); session history lives in the browser session (newest 10).
* **spaCy** adapter: optional, not locked; no measurable benefit after the rule fixes (see evaluation report).
