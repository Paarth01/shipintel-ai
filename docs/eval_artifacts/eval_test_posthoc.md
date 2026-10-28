## Evaluation - split `test`

### rules (test)

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

### rules+spacy (test)

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

### Same-split comparison

| Method | Precision | Recall | F1 |
|---|---|---|---|
| rules | 99.8% | 96.7% | 98.2% |
| rules+spacy | 99.5% | 97.2% | 98.3% |