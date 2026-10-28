"""Core pipeline. No UI or HTTP imports: Streamlit and FastAPI are thin layers over this module."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app import PIPELINE_VERSION
from app.config import Settings, get_settings
from app.deadline import Deadline, FuzzyBudget
from app.errors import (
    NoTextError,
    OCRUnavailableError,
    ScannedPDFError,
    ShipIntelError,
    TextTooLargeError,
)
from app.evidence import package_fields
from app.extractors.ocr import ocr_available, ocr_pdf_pages
from app.extractors.pdf_text import RawPage, extract_pdf_pages, pages_without_text
from app.extractors.rules import extract_candidates
from app.extractors.txt_text import extract_txt_pages
from app.schemas import (
    DocumentMetadata,
    ExtractionResult,
    FieldStatus,
    PageText,
    ProcessingStatus,
    Severity,
    WarningItem,
)
from app.textnorm import clean_text
from app.validators import build_record, coerce_value, validate_fields, validate_upload

log = logging.getLogger("shipintel")

__all__ = [
    "ShipIntelError",
    "TextExtraction",
    "extract_document_text",
    "process_document",
    "apply_corrections",
]


@dataclass
class TextExtraction:
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    text_source: str
    ocr_used: bool
    pages: list[PageText]
    warnings: list[WarningItem]

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)


def extract_document_text(
    filename: str | None,
    data: bytes,
    settings: Settings | None = None,
    ocr: bool | None = None,
    deadline: Deadline | None = None,
) -> TextExtraction:
    """Stages 1-3: validate upload -> extract text (PDF / TXT / optional OCR) -> clean text.

    ocr=None uses settings.ocr_enabled; True/False overrides it per request.
    """
    settings = settings or get_settings()
    safe_name, file_type = validate_upload(filename, data, settings)
    want_ocr = settings.ocr_enabled if ocr is None else ocr
    warnings: list[WarningItem] = []
    ocr_used = False

    if file_type == "txt":
        raw_pages = extract_txt_pages(data)
        source = "txt"
    else:
        raw_pages = extract_pdf_pages(data, settings, deadline)
        source = "pdf_text"
        empty = pages_without_text(raw_pages, settings.min_chars_per_page)
        if empty:
            has_images = any(p.image_count for p in empty)
            if want_ocr:
                if not ocr_available(settings):
                    raise OCRUnavailableError(
                        "OCR was requested but Tesseract is not available. "
                        "See the README section 'Optional OCR'."
                    )
                by_number = {p.page: p for p in raw_pages}
                for ocr_page in ocr_pdf_pages(data, [p.page for p in empty], settings, deadline):
                    by_number[ocr_page.page] = ocr_page
                raw_pages = [by_number[p.page] for p in raw_pages]
                ocr_used = True
                source = "pdf_ocr" if len(empty) == len(raw_pages) else "pdf_text+ocr"
                warnings.append(
                    WarningItem(
                        code="OCR_USED",
                        message=f"OCR was applied to {len(empty)} page(s); OCR text can contain "
                        "recognition errors, so review extracted values carefully.",
                        severity=Severity.WARNING,
                    )
                )
            elif len(empty) == len(raw_pages):
                if has_images:
                    raise ScannedPDFError(
                        "This PDF appears to be scanned (images without a text layer). "
                        "Enable the optional OCR module (see README) or upload a digital PDF."
                    )
                raise NoTextError("No text could be found in this PDF.")
            else:
                warnings.append(
                    WarningItem(
                        code="PAGES_WITHOUT_TEXT",
                        message=f"{len(empty)} page(s) have no text layer and were skipped "
                        f"(pages {', '.join(str(p.page) for p in empty)}). Enable OCR to read them.",
                        severity=Severity.WARNING,
                    )
                )

    pages = _clean_pages(raw_pages)
    total = sum(len(p.text) for p in pages)
    if not any(p.text.strip() for p in pages):
        raise NoTextError("The document contains no readable text.")
    if total > settings.max_text_chars:
        raise TextTooLargeError(
            f"The document text has {total:,} characters; the limit is {settings.max_text_chars:,}."
        )
    return TextExtraction(
        filename=safe_name,
        file_type=file_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        text_source=source,
        ocr_used=ocr_used,
        pages=pages,
        warnings=warnings,
    )


def _clean_pages(raw_pages: list[RawPage]) -> list[PageText]:
    return [
        PageText(
            page=p.page,
            text=clean_text(p.text),
            raw_char_count=len(p.text),
            ocr_used=p.ocr_used,
        )
        for p in raw_pages
    ]


OCR_SCORE_PENALTY = 0.15


def _apply_ocr_penalty(candidates, pages: list[PageText]) -> None:
    """Values read from OCR text are less trustworthy (measured: see docs/evaluation_report.md).

    Their heuristic score is lowered, so weak (inline) matches fall under the review threshold, and
    each carries an INFO note. Values are never altered.
    """
    ocr_pages = {p.page for p in pages if p.ocr_used}
    if not ocr_pages:
        return
    for c in candidates:
        if c.page in ocr_pages and c.method != "spacy_ner":
            c.score = max(0.0, c.score - OCR_SCORE_PENALTY)
            c.notes.append(
                ("OCR_TEXT", "Read from OCR text; verify against the page image.", Severity.INFO)
            )


def process_document(
    filename: str | None,
    data: bytes,
    settings: Settings | None = None,
    ocr: bool | None = None,
    nlp: bool | None = None,
    include_text: bool = True,
) -> ExtractionResult:
    """Full pipeline: validate -> extract text -> clean -> extract fields -> normalise ->
    validate -> evidence/score packaging. Raises ShipIntelError subclasses for bad input."""
    started = time.perf_counter()
    settings = settings or get_settings()
    deadline = Deadline(settings.processing_timeout_s)
    text = extract_document_text(filename, data, settings, ocr, deadline)

    candidates = extract_candidates(text.pages, deadline, FuzzyBudget(settings.fuzzy_label_budget))
    deadline.check()
    _apply_ocr_penalty(candidates, text.pages)
    extractor = "rules"
    if settings.nlp_enabled if nlp is None else nlp:
        from app.extractors.nlp import nlp_candidates  # optional dependency

        extra = nlp_candidates(text.pages, candidates, settings)
        if extra is not None:
            candidates.extend(extra)
            extractor = "rules+spacy"
        else:
            text.warnings.append(
                WarningItem(
                    code="NLP_UNAVAILABLE",
                    message="spaCy NER was requested but is not installed or its model is "
                    "missing; rule-based extraction only. See README 'Optional NLP'.",
                    severity=Severity.INFO,
                )
            )

    page_text = {p.page: p.text for p in text.pages}
    fields = package_fields(candidates, page_text, settings)
    validate_fields(fields)

    doc_warnings = list(text.warnings)
    found = [f for f in fields.values() if f.value is not None]
    if not found:
        doc_warnings.append(
            WarningItem(
                code="NO_FIELDS_FOUND",
                message="No shipping fields were recognised. This may not be a shipping document, "
                "or its layout is not covered by the rules.",
                severity=Severity.WARNING,
            )
        )
    needs_review = (
        any(f.status in (FieldStatus.NEEDS_REVIEW, FieldStatus.INVALID) for f in fields.values())
        or not found
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = ExtractionResult(
        document_id=uuid.uuid4().hex[:12],
        status=ProcessingStatus.NEEDS_REVIEW if needs_review else ProcessingStatus.COMPLETED,
        metadata=DocumentMetadata(
            filename=text.filename,
            file_type=text.file_type,  # type: ignore[arg-type]
            size_bytes=text.size_bytes,
            sha256=text.sha256,
            page_count=len(text.pages),
            char_count=text.char_count,
            text_source=text.text_source,
            ocr_used=text.ocr_used,
            extractor=extractor,
            pipeline_version=PIPELINE_VERSION,
            processing_ms=round(elapsed_ms, 2),
        ),
        fields=fields,
        warnings=doc_warnings,
        pages=text.pages if include_text else None,
    )
    # Never log document text or extracted values - only counts and ids.
    log.info(
        "processed id=%s type=%s pages=%d fields_found=%d ms=%.0f",
        result.document_id,
        text.file_type,
        len(text.pages),
        len(found),
        elapsed_ms,
    )
    return result


def apply_corrections(
    result: ExtractionResult, corrections: Mapping[str, object]
) -> tuple[ExtractionResult | None, list[str]]:
    """Apply human edits (field -> text/value). Returns (new_result, errors).

    Only fields whose value actually changed become 'human_corrected'. The whole corrected
    record is validated with the strict Pydantic model; on any error nothing is applied.
    """
    errors: list[str] = []
    typed: dict[str, str | float | None] = {}
    for name, raw in corrections.items():
        if name not in result.fields:
            errors.append(f"{name}: unknown field")
            continue
        value, err = coerce_value(name, raw)
        if err:
            errors.append(err)
        typed[name] = value
    merged = {n: f.value for n, f in result.fields.items()}
    merged.update(typed)
    changed = {n for n, v in typed.items() if n in result.fields and v != result.fields[n].value}
    _, record_errors = build_record(
        merged, check_date_order=bool(changed & {"loading_date", "discharge_date"})
    )
    errors.extend(record_errors)
    if errors:
        return None, errors
    updated = result.model_copy(deep=True)
    for name, value in typed.items():
        field = updated.fields[name]
        if value == field.value:
            continue
        field.value = value
        field.status = FieldStatus.HUMAN_CORRECTED
        field.warnings = [
            WarningItem(
                code="HUMAN_CORRECTED",
                message="Value was edited by a reviewer.",
                field=name,
                severity=Severity.INFO,
            )
        ]
    updated.status = (
        ProcessingStatus.NEEDS_REVIEW
        if any(
            f.status in (FieldStatus.NEEDS_REVIEW, FieldStatus.INVALID)
            for f in updated.fields.values()
        )
        else ProcessingStatus.COMPLETED
    )
    return updated, []
