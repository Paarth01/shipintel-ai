## Evaluation - split `test`

### rules (test)

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

### rules+spacy (test)

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

### Same-split comparison

| Method | Precision | Recall | F1 |
|---|---|---|---|
| rules | 99.6% | 63.1% | 77.2% |
| rules+spacy | 98.3% | 68.9% | 81.1% |