"""Validation: (1) untrusted upload checks, (2) field-level rules and cross-field checks."""

from __future__ import annotations

import ntpath
import posixpath
from collections.abc import Mapping

from app.config import Settings
from app.errors import EmptyFileError, FileTooLargeError, UnsupportedFileTypeError

# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


def sanitize_filename(filename: str | None) -> str:
    """Return a display-safe base name (no directories, no control characters)."""
    name = ntpath.basename(posixpath.basename((filename or "").replace("\\", "/")))
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:120] or "upload"


def validate_upload(filename: str | None, data: bytes, settings: Settings) -> tuple[str, str]:
    """Check extension, size and magic bytes. Returns (safe_filename, file_type)."""
    safe = sanitize_filename(filename)
    ext = posixpath.splitext(safe.lower())[1]
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(settings.allowed_extensions)
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or 'none'}'. Allowed types: {allowed}."
        )
    if len(data) == 0:
        raise EmptyFileError("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise FileTooLargeError(
            f"The file is {len(data) / 1_048_576:.1f} MB; the limit is "
            f"{settings.max_upload_bytes // 1_048_576} MB."
        )
    if ext == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise UnsupportedFileTypeError(
                "The file has a .pdf extension but its content is not a PDF."
            )
        return safe, "pdf"
    if data.lstrip()[:5] == b"%PDF-":
        raise UnsupportedFileTypeError(
            "The file has a .txt extension but its content is a PDF. Rename it to .pdf."
        )
    return safe, "txt"


# ---------------------------------------------------------------------------
# Field-level and cross-field validation (runs after extraction + normalisation)
# ---------------------------------------------------------------------------
from datetime import date  # noqa: E402

from pydantic import ValidationError  # noqa: E402

from app.schemas import (  # noqa: E402
    ExtractedRecord,
    FieldResult,
    FieldStatus,
    Severity,
    WarningItem,
)

MAX_PLAUSIBLE_QUANTITY = 5_000_000.0  # in the stated unit; larger values are flagged, not rejected


def _warn(f: FieldResult, code: str, message: str, severity: Severity = Severity.WARNING) -> None:
    f.warnings.append(WarningItem(code=code, message=message, field=f.name, severity=severity))


def _flag(f: FieldResult) -> None:
    if f.status in (FieldStatus.EXTRACTED, FieldStatus.NORMALIZED):
        f.status = FieldStatus.NEEDS_REVIEW


def validate_fields(fields: dict[str, FieldResult]) -> None:
    """Apply field rules and cross-field consistency checks in place."""
    qty, unit = fields["cargo_quantity"], fields["cargo_unit"]
    if isinstance(qty.value, float):
        if qty.value <= 0:
            _warn(
                qty,
                "NONPOSITIVE_QUANTITY",
                "Quantity must be greater than zero; value rejected.",
                Severity.ERROR,
            )
            qty.value, qty.status = None, FieldStatus.INVALID
        elif qty.value > MAX_PLAUSIBLE_QUANTITY:
            _warn(qty, "QUANTITY_IMPLAUSIBLE", f"Quantity {qty.value:,.0f} is unusually large.")
            _flag(qty)
        if unit.value is None and qty.value is not None:
            _warn(qty, "UNIT_MISSING", "A quantity was found but no unit; verify before use.")
            _flag(qty)
    elif unit.value is not None and qty.status == FieldStatus.MISSING:
        _warn(unit, "UNIT_WITHOUT_QUANTITY", "A unit was found without a quantity.", Severity.INFO)

    load, disch = fields["loading_date"], fields["discharge_date"]
    if isinstance(load.value, str) and isinstance(disch.value, str):
        if date.fromisoformat(disch.value) < date.fromisoformat(load.value):
            _warn(
                disch,
                "DISCHARGE_BEFORE_LOADING",
                f"Discharge date {disch.value} is earlier than loading date {load.value}.",
                Severity.ERROR,
            )
            _flag(disch)
            _flag(load)

    origin, dest = fields["origin_port"], fields["destination_port"]
    if (
        isinstance(origin.value, str)
        and isinstance(dest.value, str)
        and origin.value.casefold() == dest.value.casefold()
    ):
        _warn(dest, "SAME_PORT", "Origin and destination ports are identical; verify.")
        _flag(origin)
        _flag(dest)


def build_record(
    values: Mapping[str, object], check_date_order: bool = True
) -> tuple[ExtractedRecord | None, list[str]]:
    """Validate a dict of field values (e.g. human corrections) with the strict Pydantic model.

    Returns (record, errors). Empty strings are treated as null. `check_date_order=False` is used
    when a reviewer edits unrelated fields of a document whose dates were already flagged: the
    pre-existing DISCHARGE_BEFORE_LOADING warning must not block saving an unrelated correction.
    """
    cleaned = {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in values.items()}
    try:
        record = ExtractedRecord.model_validate(cleaned)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "record"
            errors.append(f"{loc}: {err['msg']}")
        return None, errors
    if (
        check_date_order
        and record.loading_date
        and record.discharge_date
        and record.discharge_date < record.loading_date
    ):
        return None, ["discharge_date: is earlier than loading_date"]
    return record, []


def coerce_value(field_name: str, text: object) -> tuple[str | float | None, str | None]:
    """Convert a human-entered form value to the field's type. Returns (value, error)."""
    from app.normalizers import normalize_unit, parse_date, parse_number

    if text is None or (isinstance(text, str) and not text.strip()):
        return None, None
    if field_name in ("loading_date", "discharge_date"):
        d = parse_date(str(text))
        if d.status == "ok" and d.value is not None:
            return d.value.isoformat(), None
        return (
            None,
            f"{field_name}: use an unambiguous date such as 2025-03-12 ({d.message or 'not recognised'})",
        )
    if field_name == "cargo_quantity":
        if isinstance(text, int | float):
            return float(text), None
        value, ambiguous = parse_number(str(text))
        if value is None or ambiguous:
            return None, "cargo_quantity: enter a plain number such as 45000 or 45,000.5"
        return value, None
    if field_name == "cargo_unit":
        unit, _ = normalize_unit(str(text))
        return (unit, None) if unit else (None, "cargo_unit: use MT, kg, bbl, TEU or m3")
    return " ".join(str(text).split()), None
