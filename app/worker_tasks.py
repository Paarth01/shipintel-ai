"""Functions executed inside sandbox workers (must be importable, picklable arguments only)."""

from __future__ import annotations

from app.config import Settings
from app.pipeline import process_document
from app.schemas import ExtractionResult


def extract(
    settings: Settings,
    filename: str | None,
    data: bytes,
    ocr: bool | None,
    nlp: bool | None,
    include_text: bool,
) -> ExtractionResult:
    return process_document(
        filename, data, settings=settings, ocr=ocr, nlp=nlp, include_text=include_text
    )
