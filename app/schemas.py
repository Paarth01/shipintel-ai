"""Pydantic models: extraction output, evidence, warnings, and the strict validated record."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator

FIELD_NAMES: tuple[str, ...] = (
    "vessel_name",
    "origin_port",
    "destination_port",
    "cargo_type",
    "cargo_quantity",
    "cargo_unit",
    "loading_date",
    "discharge_date",
    "document_reference",
    "counterparty",
)

CANONICAL_UNITS = ("MT", "kg", "bbl", "TEU", "m3")


class FieldStatus(StrEnum):
    EXTRACTED = "extracted"  # value copied from the text (whitespace/case cleanup only)
    NORMALIZED = (
        "normalized"  # value transformed (date -> ISO, quantity -> number, unit -> canonical)
    )
    MISSING = "missing"  # no evidence found; value is null
    INVALID = "invalid"  # evidence found but the value failed validation; value is null
    NEEDS_REVIEW = "needs_review"  # ambiguous / conflicting / low heuristic score
    HUMAN_CORRECTED = "human_corrected"  # set by a person in the review form


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ProcessingStatus(StrEnum):
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"


class WarningItem(BaseModel):
    code: str
    message: str
    field: str | None = None
    severity: Severity = Severity.WARNING


class Evidence(BaseModel):
    """Where a value came from. Offsets index into the cleaned text of `page` (see PageText)."""

    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    snippet: str
    label: str | None = None
    method: str  # label_match | label_next_line | label_fuzzy | inline_pattern | spacy_ner


class FieldResult(BaseModel):
    name: str
    value: str | float | None = None
    raw_value: str | None = None
    status: FieldStatus = FieldStatus.MISSING
    # Heuristic rule-confidence in [0, 1]. NOT a calibrated probability.
    heuristic_score: float | None = Field(default=None, ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)


class PageText(BaseModel):
    page: int
    text: str  # cleaned text (offsets in Evidence refer to this)
    raw_char_count: int
    ocr_used: bool = False


class DocumentMetadata(BaseModel):
    filename: str
    file_type: Literal["pdf", "txt"]
    size_bytes: int
    sha256: str
    page_count: int
    char_count: int
    text_source: str  # txt | pdf_text | pdf_ocr | pdf_text+ocr
    ocr_used: bool = False
    extractor: str = "rules"  # rules | rules+spacy
    pipeline_version: str
    processing_ms: float


class ExtractionResult(BaseModel):
    document_id: str
    status: ProcessingStatus
    metadata: DocumentMetadata
    fields: dict[str, FieldResult]
    warnings: list[WarningItem] = Field(default_factory=list)  # document-level warnings
    pages: list[PageText] | None = None

    @model_validator(mode="after")
    def _all_fields_present(self) -> ExtractionResult:
        missing = [n for n in FIELD_NAMES if n not in self.fields]
        if missing:
            raise ValueError(f"fields missing from result: {missing}")
        return self

    def all_warnings(self) -> list[WarningItem]:
        out = list(self.warnings)
        for f in self.fields.values():
            out.extend(f.warnings)
        return out

    def values(self) -> dict[str, str | float | None]:
        return {n: self.fields[n].value for n in FIELD_NAMES}


class ExtractedRecord(BaseModel):
    """Strictly typed record built from (possibly human-corrected) field values."""

    model_config = ConfigDict(extra="forbid")

    vessel_name: str | None = None
    origin_port: str | None = None
    destination_port: str | None = None
    cargo_type: str | None = None
    cargo_quantity: PositiveFloat | None = None
    cargo_unit: Literal["MT", "kg", "bbl", "TEU", "m3"] | None = None
    loading_date: date | None = None
    discharge_date: date | None = None
    document_reference: str | None = None
    counterparty: str | None = None
