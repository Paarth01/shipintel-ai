## Evaluation - split `dev`

### rules (dev)

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

### rules+spacy (dev)

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

### Same-split comparison

| Method | Precision | Recall | F1 |
|---|---|---|---|
| rules | 100.0% | 99.1% | 99.6% |
| rules+spacy | 100.0% | 99.3% | 99.6% |