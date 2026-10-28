"""JSON / CSV export. Output is valid JSON, and CSV cells are protected against formula injection."""

from __future__ import annotations

import csv
import io
import json

from app.schemas import FIELD_NAMES, ExtractionResult

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
CSV_COLUMNS = [
    "document_id",
    "filename",
    "field",
    "value",
    "raw_value",
    "status",
    "heuristic_score",
    "evidence_page",
    "evidence_snippet",
    "warnings",
]


def csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection (OWASP): prefix risky leading characters."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_json(result: ExtractionResult, include_text: bool = False, indent: int = 2) -> str:
    payload = result.model_dump(mode="json")
    if not include_text:
        payload["pages"] = None
    return json.dumps(payload, indent=indent, ensure_ascii=False)


def to_csv(results: ExtractionResult | list[ExtractionResult]) -> str:
    """Long format: one row per (document, field). Missing fields have an empty value."""
    items = [results] if isinstance(results, ExtractionResult) else results
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)
    for r in items:
        for name in FIELD_NAMES:
            f = r.fields[name]
            ev = f.evidence[0] if f.evidence else None
            writer.writerow(
                [
                    csv_safe(r.document_id),
                    csv_safe(r.metadata.filename),
                    name,
                    csv_safe(f.value),
                    csv_safe(f.raw_value),
                    f.status.value,
                    "" if f.heuristic_score is None else f.heuristic_score,
                    ev.page if ev else "",
                    csv_safe(ev.snippet if ev else ""),
                    csv_safe("; ".join(w.code for w in f.warnings if w.code != "FIELD_NOT_FOUND")),
                ]
            )
    return buf.getvalue()


def to_wide_csv(results: list[ExtractionResult]) -> str:
    """Wide format: one row per document, one column per field (values only)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["document_id", "filename", "status", *FIELD_NAMES])
    for r in results:
        writer.writerow(
            [
                csv_safe(r.document_id),
                csv_safe(r.metadata.filename),
                r.status.value,
                *[csv_safe(r.fields[n].value) for n in FIELD_NAMES],
            ]
        )
    return buf.getvalue()


def csv_bytes(text: str) -> bytes:
    """UTF-8 with BOM so Excel on Windows reads non-ASCII characters correctly."""
    return text.encode("utf-8-sig")
