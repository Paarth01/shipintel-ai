# Evaluation report

**Everything below is measured on SYNTHETIC documents with a RULE-BASED extractor. It says nothing about
real shipping documents.** Numbers come from `scripts/evaluate.py`; raw JSON/Markdown outputs are in
[`eval_artifacts/`](eval_artifacts/). Re-run: `python scripts/evaluate.py --split dev|test [--nlp]`.

## 1. Summary

| Run | Docs | Precision | Recall | F1 | Status of the number |
|---|---|---|---|---|---|
| Dev split, first ever run (before any fixes) | 96 | 97.7% | 95.3% | 96.5% | Development feedback |
| Dev split, final rules | 96 | 100.0% | 99.1% | 99.6% | **Tuned on this split — optimistic** |
| **Held-out templates, first run, rules frozen** | 54 | 99.6% | 63.1% | **77.2%** | **Clean generalisation estimate** |
| Held-out templates, after 3 generic fixes made after studying its errors | 54 | 99.8% | 96.7% | 98.2% | **Contaminated**: not a held-out number |

Same-split comparison with the optional spaCy NER adapter (rules fill first, NER only fills empty fields):

| Split / state | Rules F1 | Rules+spaCy F1 | Median ms/doc (rules → +spaCy) |
|---|---|---|---|
| Held-out, first run | 77.2% (P 99.6 / R 63.1) | 81.1% (P 98.3 / R 68.9) | 1.1 → 14.2 |
| Held-out, post-hoc | 98.2% (P 99.8 / R 96.7) | 98.3% (P 99.5 / R 97.2) | 1.0 → 12.5 |
| Dev, final | 99.6% | 99.6% | – |

**Take-aways**

1. **The rules overfit the layouts they were written against.** F1 fell from 99.6% (dev) to 77.2% on templates
   I had not looked at. The dev number should not be quoted as expected performance.
2. **The system fails by returning `null`, not by returning wrong values.** On the first held-out run precision was
   99.6% (1 wrong non-null value among all predictions) while recall was 63.1%. All 115 absent cells returned `null`
   (missing-field handling 100%, 0 false values), and all 3 non-shipping documents in the held-out split returned all-null.
3. **One layout dominated the failure.** 115 of the 157 first-run field errors came from template T1 (numbered
   clauses like `1. Vessel: X`), which the label scanner could not parse at all (T1 F1 34.3%; T2 97.1%; T3 85.6%).
4. **spaCy NER helped only where the rules were failing, and costs ~12× the time.** First run: +3.9 F1 points
   (recall +5.8, precision −1.3). After the rules were fixed: +0.1 F1 point, which is far inside the noise of a
   54-document test set. The adapter is kept as an optional, documented extension, not as an improvement claim.
5. **Confidence flags are not yet reliable.** Of the few wrong non-null values (1 on the first run, 2 with spaCy
   post-hoc), 0/1 and 1/2 were marked `needs_review`; n is far too small to estimate a rate. I did not calibrate the score.

## 2. Data

* **150 synthetic documents** (98 TXT, 52 PDF) generated with seed 42 by `scripts/generate_synthetic_data.py`; every file carries a
  "SYNTHETIC SAMPLE" footer and every annotation has `"synthetic": true`. See [dataset_card.md](dataset_card.md).
* **Split by template, not by document.** Dev = D1–D6 (96 docs: bill of lading, fixture recap, manifest table, notice of
  readiness letter, shipping instruction, pipe-separated voyage summary). Held-out test = T1–T3 (54 docs: numbered
  charter-party summary, consignment advice with different label wording, voyage e-mail prose). No template appears in both splits.
* **Realism features:** label typos (4% per label), port spelling noise, country/LOCODE port forms, 7 date formats,
  5 number formats incl. European, ports outside the gazetteer (10% each), distractor dates/numbers, omitted fields
  (field-specific rates), document wrapping, plus injected problems: ambiguous date (18), invalid date (9),
  discharge-before-loading (18), same port (9), zero quantity (9), non-shipping documents (6).
* **Annotation rule for uninterpretable values:** ambiguous or impossible dates and zero quantities are annotated `null`
  (the system must not guess), with the expected warning code in `expected_warnings`.

## 3. Protocol (what was and was not done)

1. Rules were developed against the **dev** split only (several iterations; see §6).
2. The held-out split was **run once with the rules frozen** (the result in the first held-out row). The script's output files were
   not saved on that first run (I had piped the output through `head`, which killed the script before it wrote files), so I re-ran the
   identical frozen code purely to capture artifacts; the numbers were identical (77.2% / 81.1%).
3. After seeing the held-out errors I made **three generic fixes**: ignoring list markers (`1.`, `(a)`, `-`) before labels; an inline
   `Our reference is X` pattern; an inline `lift/load … at <port>` pattern (made wrap- and decimal-tolerant after my own regression
   test showed it was incomplete). I deliberately **did not** add test-driven vocabulary such as the alias `Carrier Vessel`.
   The second held-out row is therefore **post-hoc and contaminated**; a clean post-fix number needs a *new* set of templates.

## 4. Metric definitions

* A field cell is correct if the predicted value equals the expected value after normalisation (strings: case/whitespace-insensitive;
  numbers: equal within 1e-6; dates: ISO equality) **or both are null**.
* **TP** = expected non-null and correct. **FP** = predicted non-null where expected is null *or different*. **FN** = expected non-null
  and predicted null *or different* (a wrong value counts as both FP and FN). **TN** = both null.
* Precision/recall/F1 are **micro** over all 10 fields × documents; per-field and macro-F1 are also in the tables.
* *Document exact match*: all 10 fields correct. *Missing-field handling*: share of absent cells returned as null.
  *Validation detection*: share of injected problems for which the expected warning code was emitted;
  *false alarms*: share of documents without injected problems that emitted any of those codes.
* *Time per document* is the pipeline's own `processing_ms` (TXT/PDF text extraction + rules + validation) on a
  single-CPU Linux VM, Python 3.12.3, **OCR off**, no concurrency. It excludes HTTP/UI time.

## 5. Results by run

### 5.1 Held-out templates — first run (rules frozen)

#### rules (test)

- Documents: **54** (pipeline failures: 0)
- Micro P / R / F1: **99.6% / 63.1% / 77.2%**; macro-F1 75.4%
- Field-cell accuracy (null-aware exact match): 70.8%; documents with all 10 fields correct: 25.9%
- Missing-field handling (absent field -> null): 100.0% (0 wrong values on 115 absent cells)
- Validation-error detection: 85.7%; false alarms on documents without injected problems: 0.0%
- Non-shipping documents returned all-null: 100.0%
- Of wrong non-null values, flagged needs_review/invalid: 0.0% (0/1); correct values that were flagged anyway: 5.2%
- Time per document: median 1.0 ms, mean 1.9 ms (1 CPU, Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, Python 3.12.3, OCR off)

| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |
|---|---|---|---|---|---|---|---|---|
| vessel_name | 100.0% | 67.4% | 80.5% | 31 | 0 | 15 | 8 | 72.2% |
| origin_port | 91.7% | 26.2% | 40.7% | 11 | 1 | 31 | 12 | 42.6% |
| destination_port | 100.0% | 57.4% | 73.0% | 27 | 0 | 20 | 7 | 63.0% |
| cargo_type | 100.0% | 64.0% | 78.0% | 32 | 0 | 18 | 4 | 66.7% |
| cargo_quantity | 100.0% | 65.9% | 79.5% | 29 | 0 | 15 | 10 | 72.2% |
| cargo_unit | 100.0% | 66.0% | 79.5% | 31 | 0 | 16 | 7 | 70.4% |
| loading_date | 100.0% | 97.4% | 98.7% | 37 | 0 | 1 | 16 | 98.1% |
| discharge_date | 100.0% | 100.0% | 100.0% | 41 | 0 | 0 | 13 | 100.0% |
| document_reference | 100.0% | 33.3% | 50.0% | 16 | 0 | 32 | 6 | 40.7% |
| counterparty | 100.0% | 59.1% | 74.3% | 13 | 0 | 9 | 32 | 83.3% |

| Template | Precision | Recall | F1 |
|---|---|---|---|
| T1_charter_party_summary | 100.0% | 20.7% | 34.3% |
| T2_consignment_advice | 99.3% | 95.0% | 97.1% |
| T3_voyage_email | 100.0% | 74.8% | 85.6% |

| File type | Precision | Recall | F1 |
|---|---|---|---|
| pdf | 100.0% | 51.4% | 67.9% |
| txt | 99.5% | 68.8% | 81.3% |

| Injected problem | Detected | Expected | Rate |
|---|---|---|---|
| AMBIGUOUS_DATE | 6 | 6 | 100.0% |
| DISCHARGE_BEFORE_LOADING | 6 | 6 | 100.0% |
| INVALID_DATE | 3 | 3 | 100.0% |
| NONPOSITIVE_QUANTITY | 2 | 3 | 66.7% |
| SAME_PORT | 1 | 3 | 33.3% |

#### rules+spacy (test)

- Documents: **54** (pipeline failures: 0)
- Micro P / R / F1: **98.3% / 68.9% / 81.1%**; macro-F1 80.7%
- Field-cell accuracy (null-aware exact match): 74.9%; documents with all 10 fields correct: 25.9%
- Missing-field handling (absent field -> null): 100.0% (0 wrong values on 115 absent cells)
- Validation-error detection: 90.5%; false alarms on documents without injected problems: 0.0%
- Non-shipping documents returned all-null: 100.0%
- Of wrong non-null values, flagged needs_review/invalid: 80.0% (4/5); correct values that were flagged anyway: 13.3%
- Time per document: median 11.6 ms, mean 12.2 ms (1 CPU, Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, Python 3.12.3, OCR off)

| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |
|---|---|---|---|---|---|---|---|---|
| vessel_name | 100.0% | 67.4% | 80.5% | 31 | 0 | 15 | 8 | 72.2% |
| origin_port | 83.3% | 47.6% | 60.6% | 20 | 4 | 22 | 12 | 59.3% |
| destination_port | 97.4% | 78.7% | 87.1% | 37 | 1 | 10 | 7 | 81.5% |
| cargo_type | 100.0% | 64.0% | 78.0% | 32 | 0 | 18 | 4 | 66.7% |
| cargo_quantity | 100.0% | 65.9% | 79.5% | 29 | 0 | 15 | 10 | 72.2% |
| cargo_unit | 100.0% | 66.0% | 79.5% | 31 | 0 | 16 | 7 | 70.4% |
| loading_date | 100.0% | 97.4% | 98.7% | 37 | 0 | 1 | 16 | 98.1% |
| discharge_date | 100.0% | 100.0% | 100.0% | 41 | 0 | 0 | 13 | 100.0% |
| document_reference | 100.0% | 33.3% | 50.0% | 16 | 0 | 32 | 6 | 40.7% |
| counterparty | 100.0% | 86.4% | 92.7% | 19 | 0 | 3 | 32 | 94.4% |

| Template | Precision | Recall | F1 |
|---|---|---|---|
| T1_charter_party_summary | 94.3% | 34.5% | 50.5% |
| T2_consignment_advice | 99.3% | 95.0% | 97.1% |
| T3_voyage_email | 99.1% | 78.4% | 87.6% |

| File type | Precision | Recall | F1 |
|---|---|---|---|
| pdf | 100.0% | 60.7% | 75.6% |
| txt | 97.7% | 73.0% | 83.5% |

| Injected problem | Detected | Expected | Rate |
|---|---|---|---|
| AMBIGUOUS_DATE | 6 | 6 | 100.0% |
| DISCHARGE_BEFORE_LOADING | 6 | 6 | 100.0% |
| INVALID_DATE | 3 | 3 | 100.0% |
| NONPOSITIVE_QUANTITY | 2 | 3 | 66.7% |
| SAME_PORT | 2 | 3 | 66.7% |

#### Same-split comparison

| Method | Precision | Recall | F1 |
|---|---|---|---|
| rules | 99.6% | 63.1% | 77.2% |
| rules+spacy | 98.3% | 68.9% | 81.1% |

### 5.2 Held-out templates — post-hoc (contaminated)

#### rules (test)

- Documents: **54** (pipeline failures: 0)
- Micro P / R / F1: **99.8% / 96.7% / 98.2%**; macro-F1 98.3%
- Field-cell accuracy (null-aware exact match): 97.2%; documents with all 10 fields correct: 75.9%
- Missing-field handling (absent field -> null): 100.0% (0 wrong values on 115 absent cells)
- Validation-error detection: 95.2%; false alarms on documents without injected problems: 0.0%
- Non-shipping documents returned all-null: 100.0%
- Of wrong non-null values, flagged needs_review/invalid: 0.0% (0/1); correct values that were flagged anyway: 3.9%
- Time per document: median 1.0 ms, mean 2.0 ms (1 CPU, Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, Python 3.12.3, OCR off)

| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |
|---|---|---|---|---|---|---|---|---|
| vessel_name | 100.0% | 89.1% | 94.3% | 41 | 0 | 5 | 8 | 90.7% |
| origin_port | 97.4% | 90.5% | 93.8% | 38 | 1 | 4 | 12 | 92.6% |
| destination_port | 100.0% | 93.6% | 96.7% | 44 | 0 | 3 | 7 | 94.4% |
| cargo_type | 100.0% | 96.0% | 98.0% | 48 | 0 | 2 | 4 | 96.3% |
| cargo_quantity | 100.0% | 100.0% | 100.0% | 44 | 0 | 0 | 10 | 100.0% |
| cargo_unit | 100.0% | 100.0% | 100.0% | 47 | 0 | 0 | 7 | 100.0% |
| loading_date | 100.0% | 100.0% | 100.0% | 38 | 0 | 0 | 16 | 100.0% |
| discharge_date | 100.0% | 100.0% | 100.0% | 41 | 0 | 0 | 13 | 100.0% |
| document_reference | 100.0% | 100.0% | 100.0% | 48 | 0 | 0 | 6 | 100.0% |
| counterparty | 100.0% | 100.0% | 100.0% | 22 | 0 | 0 | 32 | 100.0% |

| Template | Precision | Recall | F1 |
|---|---|---|---|
| T1_charter_party_summary | 100.0% | 99.3% | 99.7% |
| T2_consignment_advice | 99.3% | 95.0% | 97.1% |
| T3_voyage_email | 100.0% | 95.7% | 97.8% |

| File type | Precision | Recall | F1 |
|---|---|---|---|
| pdf | 100.0% | 98.6% | 99.3% |
| txt | 99.6% | 95.8% | 97.7% |

| Injected problem | Detected | Expected | Rate |
|---|---|---|---|
| AMBIGUOUS_DATE | 6 | 6 | 100.0% |
| DISCHARGE_BEFORE_LOADING | 6 | 6 | 100.0% |
| INVALID_DATE | 3 | 3 | 100.0% |
| NONPOSITIVE_QUANTITY | 3 | 3 | 100.0% |
| SAME_PORT | 2 | 3 | 66.7% |

#### rules+spacy (test)

- Documents: **54** (pipeline failures: 0)
- Micro P / R / F1: **99.5% / 97.2% / 98.3%**; macro-F1 98.4%
- Field-cell accuracy (null-aware exact match): 97.4%; documents with all 10 fields correct: 79.6%
- Missing-field handling (absent field -> null): 100.0% (0 wrong values on 115 absent cells)
- Validation-error detection: 100.0%; false alarms on documents without injected problems: 0.0%
- Non-shipping documents returned all-null: 100.0%
- Of wrong non-null values, flagged needs_review/invalid: 50.0% (1/2); correct values that were flagged anyway: 4.6%
- Time per document: median 12.5 ms, mean 14.3 ms (1 CPU, Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, Python 3.12.3, OCR off)

| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |
|---|---|---|---|---|---|---|---|---|
| vessel_name | 100.0% | 89.1% | 94.3% | 41 | 0 | 5 | 8 | 90.7% |
| origin_port | 95.0% | 90.5% | 92.7% | 38 | 2 | 4 | 12 | 92.6% |
| destination_port | 100.0% | 97.9% | 98.9% | 46 | 0 | 1 | 7 | 98.1% |
| cargo_type | 100.0% | 96.0% | 98.0% | 48 | 0 | 2 | 4 | 96.3% |
| cargo_quantity | 100.0% | 100.0% | 100.0% | 44 | 0 | 0 | 10 | 100.0% |
| cargo_unit | 100.0% | 100.0% | 100.0% | 47 | 0 | 0 | 7 | 100.0% |
| loading_date | 100.0% | 100.0% | 100.0% | 38 | 0 | 0 | 16 | 100.0% |
| discharge_date | 100.0% | 100.0% | 100.0% | 41 | 0 | 0 | 13 | 100.0% |
| document_reference | 100.0% | 100.0% | 100.0% | 48 | 0 | 0 | 6 | 100.0% |
| counterparty | 100.0% | 100.0% | 100.0% | 22 | 0 | 0 | 32 | 100.0% |

| Template | Precision | Recall | F1 |
|---|---|---|---|
| T1_charter_party_summary | 100.0% | 99.3% | 99.7% |
| T2_consignment_advice | 99.3% | 95.0% | 97.1% |
| T3_voyage_email | 99.3% | 97.1% | 98.2% |

| File type | Precision | Recall | F1 |
|---|---|---|---|
| pdf | 100.0% | 98.6% | 99.3% |
| txt | 99.3% | 96.5% | 97.9% |

| Injected problem | Detected | Expected | Rate |
|---|---|---|---|
| AMBIGUOUS_DATE | 6 | 6 | 100.0% |
| DISCHARGE_BEFORE_LOADING | 6 | 6 | 100.0% |
| INVALID_DATE | 3 | 3 | 100.0% |
| NONPOSITIVE_QUANTITY | 3 | 3 | 100.0% |
| SAME_PORT | 3 | 3 | 100.0% |

#### Same-split comparison

| Method | Precision | Recall | F1 |
|---|---|---|---|
| rules | 99.8% | 96.7% | 98.2% |
| rules+spacy | 99.5% | 97.2% | 98.3% |

### 5.3 Dev split — final rules (tuned)

#### rules (dev)

- Documents: **96** (pipeline failures: 0)
- Micro P / R / F1: **100.0% / 99.1% / 99.6%**; macro-F1 99.6%
- Field-cell accuracy (null-aware exact match): 99.3%; documents with all 10 fields correct: 93.8%
- Missing-field handling (absent field -> null): 100.0% (0 wrong values on 143 absent cells)
- Validation-error detection: 97.6%; false alarms on documents without injected problems: 0.0%
- Non-shipping documents returned all-null: 100.0%
- Of wrong non-null values, flagged needs_review/invalid: n/a (0/0); correct values that were flagged anyway: 4.6%
- Time per document: median 1.4 ms, mean 2.8 ms (1 CPU, Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, Python 3.12.3, OCR off)

| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |
|---|---|---|---|---|---|---|---|---|
| vessel_name | 100.0% | 100.0% | 100.0% | 92 | 0 | 0 | 4 | 100.0% |
| origin_port | 100.0% | 96.5% | 98.2% | 83 | 0 | 3 | 10 | 96.9% |
| destination_port | 100.0% | 96.4% | 98.2% | 80 | 0 | 3 | 13 | 96.9% |
| cargo_type | 100.0% | 100.0% | 100.0% | 89 | 0 | 0 | 7 | 100.0% |
| cargo_quantity | 100.0% | 100.0% | 100.0% | 84 | 0 | 0 | 12 | 100.0% |
| cargo_unit | 100.0% | 100.0% | 100.0% | 90 | 0 | 0 | 6 | 100.0% |
| loading_date | 100.0% | 100.0% | 100.0% | 68 | 0 | 0 | 28 | 100.0% |
| discharge_date | 100.0% | 100.0% | 100.0% | 75 | 0 | 0 | 21 | 100.0% |
| document_reference | 100.0% | 100.0% | 100.0% | 87 | 0 | 0 | 9 | 100.0% |
| counterparty | 100.0% | 98.4% | 99.2% | 62 | 0 | 1 | 33 | 99.0% |

| Template | Precision | Recall | F1 |
|---|---|---|---|
| D1_bill_of_lading | 100.0% | 100.0% | 100.0% |
| D2_fixture_recap | 100.0% | 100.0% | 100.0% |
| D3_cargo_manifest | 100.0% | 100.0% | 100.0% |
| D4_notice_of_readiness | 100.0% | 97.8% | 98.9% |
| D5_shipping_instruction | 100.0% | 99.2% | 99.6% |
| D6_voyage_summary | 100.0% | 97.9% | 98.9% |

| File type | Precision | Recall | F1 |
|---|---|---|---|
| pdf | 100.0% | 99.3% | 99.7% |
| txt | 100.0% | 99.0% | 99.5% |

| Injected problem | Detected | Expected | Rate |
|---|---|---|---|
| AMBIGUOUS_DATE | 12 | 12 | 100.0% |
| DISCHARGE_BEFORE_LOADING | 12 | 12 | 100.0% |
| INVALID_DATE | 6 | 6 | 100.0% |
| NONPOSITIVE_QUANTITY | 6 | 6 | 100.0% |
| SAME_PORT | 5 | 6 | 83.3% |

#### rules+spacy (dev)

- Documents: **96** (pipeline failures: 0)
- Micro P / R / F1: **100.0% / 99.3% / 99.6%**; macro-F1 99.6%
- Field-cell accuracy (null-aware exact match): 99.4%; documents with all 10 fields correct: 94.8%
- Missing-field handling (absent field -> null): 100.0% (0 wrong values on 143 absent cells)
- Validation-error detection: 97.6%; false alarms on documents without injected problems: 0.0%
- Non-shipping documents returned all-null: 100.0%
- Of wrong non-null values, flagged needs_review/invalid: n/a (0/0); correct values that were flagged anyway: 4.7%
- Time per document: median 14.5 ms, mean 15.6 ms (1 CPU, Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, Python 3.12.3, OCR off)

| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |
|---|---|---|---|---|---|---|---|---|
| vessel_name | 100.0% | 100.0% | 100.0% | 92 | 0 | 0 | 4 | 100.0% |
| origin_port | 100.0% | 97.7% | 98.8% | 84 | 0 | 2 | 10 | 97.9% |
| destination_port | 100.0% | 96.4% | 98.2% | 80 | 0 | 3 | 13 | 96.9% |
| cargo_type | 100.0% | 100.0% | 100.0% | 89 | 0 | 0 | 7 | 100.0% |
| cargo_quantity | 100.0% | 100.0% | 100.0% | 84 | 0 | 0 | 12 | 100.0% |
| cargo_unit | 100.0% | 100.0% | 100.0% | 90 | 0 | 0 | 6 | 100.0% |
| loading_date | 100.0% | 100.0% | 100.0% | 68 | 0 | 0 | 28 | 100.0% |
| discharge_date | 100.0% | 100.0% | 100.0% | 75 | 0 | 0 | 21 | 100.0% |
| document_reference | 100.0% | 100.0% | 100.0% | 87 | 0 | 0 | 9 | 100.0% |
| counterparty | 100.0% | 98.4% | 99.2% | 62 | 0 | 1 | 33 | 99.0% |

| Template | Precision | Recall | F1 |
|---|---|---|---|
| D1_bill_of_lading | 100.0% | 100.0% | 100.0% |
| D2_fixture_recap | 100.0% | 100.0% | 100.0% |
| D3_cargo_manifest | 100.0% | 100.0% | 100.0% |
| D4_notice_of_readiness | 100.0% | 98.5% | 99.2% |
| D5_shipping_instruction | 100.0% | 99.2% | 99.6% |
| D6_voyage_summary | 100.0% | 97.9% | 98.9% |

| File type | Precision | Recall | F1 |
|---|---|---|---|
| pdf | 100.0% | 99.3% | 99.7% |
| txt | 100.0% | 99.2% | 99.6% |

| Injected problem | Detected | Expected | Rate |
|---|---|---|---|
| AMBIGUOUS_DATE | 12 | 12 | 100.0% |
| DISCHARGE_BEFORE_LOADING | 12 | 12 | 100.0% |
| INVALID_DATE | 6 | 6 | 100.0% |
| NONPOSITIVE_QUANTITY | 6 | 6 | 100.0% |
| SAME_PORT | 5 | 6 | 83.3% |

#### Same-split comparison

| Method | Precision | Recall | F1 |
|---|---|---|---|
| rules | 100.0% | 99.1% | 99.6% |
| rules+spacy | 100.0% | 99.3% | 99.6% |

## 6. Error analysis

**Held-out, first run (157 errors; T1 115 · T3 35 · T2 7):**

| Cause | Where | What happened |
|---|---|---|
| Numbered clause prefix (`1. Vessel: X`) | T1 (all 115) | Labels must start with a letter; every field on every T1 line was missed. Generic layout gap. |
| Prose phrasing `will lift <qty> of <cargo> at <port>` | T3 | `lift … at` not recognised as a loading port; `Our reference is X` not recognised as a reference. |
| Label vocabulary | T2 | `Carrier Vessel` is not an alias and is too far from `Carrying Vessel` for the 0.85 fuzzy cutoff. |
| Spelling noise / unknown ports in prose | T2, T3 | `Druban` (for Durban) passed as an *unrecognised port* rather than being matched; prose ports must match the gazetteer exactly. |

**Post-hoc (14 errors remaining):** 5 `Carrier Vessel` misses (T2); 6 unknown or misspelled ports inside prose (`Vizhinjam` ×2, `Klaipeda`, `Gdansk` are not in the gazetteer; `PIAREUS` and `Coombo` are generator-injected misspellings that the exact-match prose rule does not repair); 1 `Druban` (for Durban) that slipped past the fuzzy matcher and was returned as an unrecognised port; 2 cargo-type misses (one T1, one T2; I did not diagnose these further). The injected-problem detection missed one `SAME_PORT`, because one of the two ports was a misspelled prose port that was not extracted.

**Dev, final (7 errors):** 6 are ports outside the gazetteer in prose or after `From:`/`To:` (deliberately precision-first, see
architecture) and 1 is a typo on a six-letter label (`SHIPER`), which is intentionally not fuzzy-matched.

**Bugs found through evaluation and fixed (each has a regression test):** inline name patterns that crossed line breaks
(`OCEAN AURORA ORIGIN TIANJIN`, `Date Loadnd` taken as a cargo), `S.A.`/`and` handling in company names, a newline treated as
end of cargo name, typo'd labels in aligned layouts, decimals inside the `lift … at` pattern.

## 7. Threats to validity — read before quoting any number

* **Synthetic and self-authored.** I wrote both the generator and the rules. Test templates differ in layout and wording, but come
  from the same imagination as the rules; real documents will be messier. No real-world accuracy claim is made or implied.
* **Small n.** 54 held-out documents (≈540 field cells); no confidence intervals were computed. Differences of a few points,
  including the spaCy gain after fixes, are not statistically meaningful.
* **Gazetteer overlap.** Ports in the documents are drawn mostly from the same list the gazetteer uses, which inflates port recall
  for known ports. Real ports outside the list are only partly represented (10%).
* **Ground-truth conventions are mine** (e.g. counterparty priority, `null` for ambiguous dates).
* **Dev numbers are tuned**, and the post-hoc held-out numbers are contaminated (see §3).
* **Not evaluated:** OCR accuracy (only a smoke test on one rendered scan), multi-page real PDFs, non-English documents, tables
  spanning pages, concurrency/load, real vessel/port databases.
* **Heuristic score** was not calibrated; no calibration curve is claimed.


## 8. OCR evaluation (added during remediation)

`scripts/evaluate_ocr.py` renders held-out documents (templates T1-T3, 29 `.txt` documents; non-shipping documents excluded)
to images with DejaVu Sans Mono at 200 DPI, degrades them at three levels, wraps each in an **image-only PDF**, and runs the real
pipeline with OCR enabled (Tesseract 5.3.4). Levels: **clean**; **mild** (0.8° rotation, blur 0.8, noise σ=8, JPEG q70);
**heavy** (1.5° rotation, blur 1.4, noise σ=25, contrast 0.8, 70% resolution loss, JPEG q35). The baseline is the *same documents read
as text*, so the difference isolates OCR loss.

### 8.1 Results (synthetic rendered scans, `test` split, 29 documents)

Baseline: the same documents read from text (no OCR): **P 99.6% / R 95.0% / F1 97.2%**, all-10-fields-correct 62.1%.

| Level | WER (mean) | Char similarity | Precision | Recall | F1 | Docs all correct | s/page (median) | Failures |
|---|---|---|---|---|---|---|---|---|
| clean | 11.5% | 95.6% | 98.3% | 73.5% | 84.1% | 41.4% | 1.0 | 0 |
| mild | 10.4% | 96.1% | 100.0% | 72.7% | 84.2% | 41.4% | 1.1 | 0 |
| heavy | 28.2% | 87.9% | 95.0% | 55.5% | 70.0% | 20.7% | 1.0 | 0 |

Environment: Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, 1 CPU, Python 3.12.3, tesseract 5.3.4.
**Reading it**

* OCR costs **~13 F1 points even on clean renderings** (97.2% → 84.1%); heavy degradation costs ~27 (→ 70.0%). The loss is almost
  entirely **recall**: values go missing (`null`) rather than wrong (precision 95-100%), consistent with the design. The rules depend
  on exact label tokens and punctuation, which OCR perturbs (word error rate 10-28%).
* **Clean vs mild (84.1% vs 84.2%) is noise** at n=29, not an improvement from degradation.
* Values read from OCR text now carry an `OCR_TEXT` note and a −0.15 score penalty (so weak inline matches fall under the review
  threshold). This changes scores and flags, **not** values or the F1 above. The grayscale/pixel-cap change to the OCR render path was
  checked against the same trial before and after: identical WER, similarity and F1.
* **Limits:** *rendered*, not photographed, scans: one clean monospace font, simulated degradation, English, single page. They say
  little about phone-camera captures, skew beyond ±1.5°, stamps, handwriting, tables or multi-column layouts. ~1 s per page on one CPU.

## 9. What the benchmark does not cover

The audit fixes B1-B3, B7 and B8 (ranges, negative signs, `Port of Spain`, reference-from-prose, hyphen casing) change **no** cell of
the synthetic benchmark: dev and held-out results were bit-identical before and after, because the generator never produces those
inputs. Those behaviours are protected by dedicated regression tests (`tests/test_regressions.py`), not by the benchmark. A benchmark
that included them (and real documents) would be a more honest test of the rules.
