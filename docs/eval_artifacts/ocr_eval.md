## OCR evaluation (synthetic rendered scans, `test` split, 29 documents)

Baseline: the same documents read from text (no OCR): **P 99.6% / R 95.0% / F1 97.2%**, all-10-fields-correct 62.1%.

| Level | WER (mean) | Char similarity | Precision | Recall | F1 | Docs all correct | s/page (median) | Failures |
|---|---|---|---|---|---|---|---|---|
| clean | 11.5% | 95.6% | 98.3% | 73.5% | 84.1% | 41.4% | 1.0 | 0 |
| mild | 10.4% | 96.1% | 100.0% | 72.7% | 84.2% | 41.4% | 1.1 | 0 |
| heavy | 28.2% | 87.9% | 95.0% | 55.5% | 70.0% | 20.7% | 1.0 | 0 |

Environment: Linux-6.18.44-fc-v114-x86_64-with-glibc2.39, 1 CPU, Python 3.12.3, tesseract 5.3.4.
