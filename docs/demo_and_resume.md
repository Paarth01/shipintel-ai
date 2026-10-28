# Demo script and portfolio notes

## 5-minute demo

1. **Frame it (30 s).** "Independent portfolio project: shipping documents in, structured fields out — with evidence, validation and human
   review. Rule-based baseline, local-first, synthetic data."
2. **Start it** (two terminals): `uvicorn app.api:app` and `streamlit run app/ui.py`.
3. **Happy path (60 s).** Sidebar sample *D1 bill of lading* → **Extract**. Show the field table: value, status text, heuristic score, evidence
   snippet and page. Open *Evidence in source text* and pick `origin_port` — the value is highlighted in the page.
4. **Don't-guess behaviour (60 s).** Sample *ambiguous date*: `loading_date` is `null`, `needs review`, `AMBIGUOUS_DATE`. Sample *date order*:
   values kept, `DISCHARGE_BEFORE_LOADING` flagged. Sample *non shipping*: no fields, `NO_FIELDS_FOUND`.
5. **Review loop (45 s).** *Review and correct values* → fix a field → status becomes `human_corrected`; an impossible value is rejected by the
   strict Pydantic model. Export JSON and CSV.
6. **API (45 s).** Swagger at `/docs`; `curl -F file=@data/samples/SI-0001.txt localhost:8000/extract`; upload a `.docx` to show the clean 415 error.
7. **The evaluation story (60 s).** `python scripts/evaluate.py --split test`. "Dev F1 99.6%, but 77.2% on unseen templates — the rules overfit.
   One layout caused 115 of 157 errors. Here is how I separated tuned, held-out and contaminated numbers."

## Talking points / likely questions

* **Why rules instead of an LLM or trained model?** Deterministic, explainable, no training data or paid API, instant. It gives a measurable baseline
  to beat; the optional spaCy comparison showed a pretrained NER helps only where rules fail and costs ~12× latency.
* **What did the evaluation teach you?** The dev score was misleading (overfit). I split by template, froze the rules, ran held-out once, and
  reported the contaminated post-fix number separately instead of replacing the honest one.
* **How do you handle uncertainty?** Null + status + warning rather than a guess; ambiguity is represented, not resolved silently. The heuristic
  score is explicitly *not* calibrated, and I measured that wrong values are not reliably flagged — a stated next step.
* **How would you make it production-ready?** Real, authorised documents and labels; a larger port database; learned layout features or an LLM
  fallback behind the same evidence schema; calibration; auth, rate limits, timeouts, audit history, CI.

## Resume bullets (numbers are measured, on synthetic data)

* Built an end-to-end maritime document-intelligence prototype (Python, FastAPI, Streamlit, PyMuPDF, optional Tesseract/spaCy) that extracts
  10 shipping fields from PDF/TXT with page-level evidence, validation warnings, human-in-the-loop correction and JSON/CSV export; 293 automated tests.
* Designed a leakage-aware evaluation on 150 synthetic documents split by template: rule baseline reached 99.6% F1 on the tuning split but
  **77.2% F1 (99.6% precision / 63.1% recall) on unseen templates**; traced 115 of 157 errors (73%) to one layout, fixed generic gaps, and reported
  the post-fix 98.2% separately as contaminated rather than as a held-out result.
* Compared a spaCy NER add-on against the rule baseline on identical data (+3.9 F1 points when rules failed, +0.1 after fixes, ~12× slower),
  and kept it optional; engineered null-over-guess handling for ambiguous/invalid dates, quantities and units, plus CSV-injection and upload hardening.

* Hardened the service after a self-audit: reproduced and fixed a quadratic-time regex DoS (one 16 KB request stalled the server for
  ~5 s; now milliseconds), a chunked-upload size bypass (150 MB accepted, now cut off at the limit), client-controlled OCR and an
  unbounded OCR render (+461 MB, now +152 MB); added API-key auth, rate limiting, process-isolated workers with hard timeouts, structured
  logging/metrics, hash-pinned lockfiles and CI with `pip-audit`; measured OCR accuracy on rendered scans (F1 97.2% as text vs 84.1% on
  clean OCR). Verified with live `SIGKILL`/flood/chunked-upload tests and 92% branch coverage (293 tests).

Say "independent portfolio project on synthetic data". Do not say it was built for, endorsed by, or evaluated on data from any company.
