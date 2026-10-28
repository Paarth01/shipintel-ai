"""One regression test per audit finding (B1-B9 and S2/S8-style logic bugs)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import ProcessingTimeoutError, TextTooLargeError
from app.normalizers import clean_reference, find_dates, find_quantity, smart_title
from app.pipeline import apply_corrections, process_document
from app.validators import build_record

ROOT = Path(__file__).resolve().parent.parent


def run(text: str, **kw):
    return process_document("t.txt", text.encode(), **kw)


def field(text: str, name: str):
    return run(text).fields[name]


def codes(f) -> set[str]:
    return {w.code for w in f.warnings}


# ---------------------------------------------------------------- B1: ranges are never collapsed
@pytest.mark.parametrize(
    "text",
    [
        "Loading Date: 12-15 March 2025",
        "Loading Date: 10 March to 15 March 2025",
        "Loading Date: 2025-03-10 to 2025-03-15",
        "Loading Date: 12.03.2025 - 15.03.2025",
        "Loading Date: 10 March 2025 until 15 March 2025",
    ],
)
def test_b1_date_ranges_are_null_and_flagged(text):
    f = field(text, "loading_date")
    assert f.value is None and f.status.value == "needs_review"
    assert "DATE_RANGE" in codes(f)


def test_b1_two_unrelated_dates_in_one_value_are_flagged():
    f = field("Loading Date: 12 March 2025 (revised from 10 March 2025)", "loading_date")
    assert f.value is None and "MULTIPLE_DATES" in codes(f)


def test_b1_same_date_written_twice_is_still_one_date():
    assert field("Loading Date: 12 March 2025 (12-Mar-2025)", "loading_date").value == "2025-03-12"


def test_b1_range_in_prose_is_not_taken_as_a_single_date():
    r = run("Loading is scheduled for 10 March to 15 March 2025.\n")
    assert r.fields["loading_date"].value is None


def test_b1_single_dates_still_work():
    for text, iso in (
        ("12 March 2025", "2025-03-12"),
        ("05-Mar-2025", "2025-03-05"),
        ("March 12, 2025", "2025-03-12"),
    ):
        assert field(f"Loading Date: {text}", "loading_date").value == iso
    assert [d.status for d in find_dates("2025-03-10 – 2025-03-15 and 2025-04-01")] == [
        "range",
        "ok",
    ]


@pytest.mark.parametrize(
    "text",
    ["Quantity: 45,000 - 50,000 MT", "Quantity: 45,000-50,000 MT", "Quantity: 45,000 to 50,000 MT"],
)
def test_b1_quantity_ranges_are_null_and_flagged(text):
    f = field(text, "cargo_quantity")
    assert f.value is None and f.status.value == "needs_review" and "QUANTITY_RANGE" in codes(f)
    assert field(text, "cargo_unit").value == "MT"  # the unit is still reliable


def test_b1_conflicting_quantities_are_flagged_but_repeated_value_is_not():
    f = field("Quantity: 45,000 MT (max 50,000 MT)", "cargo_quantity")
    assert f.value is None and "QUANTITY_MULTIPLE" in codes(f)
    assert field("Quantity: 45,000 MT / 45000 MT", "cargo_quantity").value == 45000.0


# ---------------------------------------------------------------- B2: sign is preserved
def test_b2_negative_quantity_is_rejected_not_flipped():
    f = field("Quantity: -500 MT", "cargo_quantity")
    assert f.value is None and f.status.value == "invalid" and "NONPOSITIVE_QUANTITY" in codes(f)


def test_b2_dash_separators_are_not_signs():
    assert find_quantity("Thermal Coal - 45,000 MT").value == 45000.0
    assert find_quantity("BL-500 MT").value == 500.0  # hyphen glued to a word is a separator
    assert find_quantity("-500 MT").value == -500.0
    assert field("Quantity: -45,000", "cargo_quantity").value is None


# ---------------------------------------------------------------- B3: port names are not mangled
@pytest.mark.parametrize(
    "value,expected",
    [
        ("Port of Spain, Trinidad", "Port of Spain"),
        ("Port Elizabeth", "Port Elizabeth"),
        ("Port Louis", "Port Louis"),
        ("Port of Rotterdam", "Rotterdam"),
        ("Port Hedland (AUPHE)", "Port Hedland"),
    ],
)
def test_b3_port_names(value, expected):
    assert field(f"Port of Loading: {value}", "origin_port").value == expected


def test_b3_country_name_does_not_collide_with_a_port():
    f = field("Port of Loading: Spain", "origin_port")
    assert f.value == "Spain" and "UNRECOGNIZED_PORT" in codes(f)  # flagged, not silently mapped


# ---------------------------------------------------------------- B4: unrelated edits are allowed
def test_b4_unrelated_correction_is_not_blocked_by_flagged_dates():
    r = run(
        "Loading Date: 20 March 2025\nDischarge Date: 05 March 2025\nShipper: Acme Trading Ltd\n"
    )
    assert "DISCHARGE_BEFORE_LOADING" in {w.code for w in r.all_warnings()}
    fixed, errors = apply_corrections(r, {"counterparty": "Acme Trading Limited"})
    assert not errors and fixed.fields["counterparty"].value == "Acme Trading Limited"
    assert fixed.fields["counterparty"].status.value == "human_corrected"
    assert fixed.fields["discharge_date"].status.value == "needs_review"  # still flagged


def test_b4_editing_a_date_into_a_wrong_order_is_still_rejected():
    r = run("Loading Date: 20 March 2025\nDischarge Date: 25 March 2025\n")
    fixed, errors = apply_corrections(r, {"discharge_date": "2025-03-01"})
    assert fixed is None and any("earlier" in e for e in errors)
    fixed, errors = apply_corrections(
        run("Loading Date: 20 March 2025\nDischarge Date: 05 March 2025\n"),
        {"discharge_date": "2025-03-28"},
    )
    assert not errors and fixed.fields["discharge_date"].value == "2025-03-28"


def test_b4_build_record_default_still_checks_order():
    assert build_record({"loading_date": "2025-03-20", "discharge_date": "2025-03-01"})[1]
    assert not build_record(
        {"loading_date": "2025-03-20", "discharge_date": "2025-03-01"}, check_date_order=False
    )[1]


# ---------------------------------------------------------------- B5: evidence is verbatim and in place
def test_b5_inline_unit_offsets_with_irregular_spacing():
    text = "MV Ocean Pioneer will lift 323,100   barrels of Crude Oil at Santos for delivery to Durban.\n"
    r = run(text)
    page = r.pages[0].text
    for name in ("cargo_quantity", "cargo_unit", "cargo_type"):
        f = r.fields[name]
        ev = f.evidence[0]
        assert f.raw_value.strip() in page[ev.start : ev.end], (
            name,
            f.raw_value,
            page[ev.start : ev.end],
        )


@pytest.mark.skipif(
    not (ROOT / "data" / "annotations" / "dev.jsonl").exists(), reason="no sample data"
)
def test_b5_evidence_invariant_over_all_sample_documents():
    """For every field of every sample doc: the best candidate's evidence span (evidence[0])
    contains raw_value verbatim, and every span lies inside its page."""
    bad = []
    for split in ("dev", "test"):
        for line in (ROOT / "data" / "annotations" / f"{split}.jsonl").read_text().splitlines():
            rec = json.loads(line)
            res = process_document(
                rec["file"], (ROOT / "data" / "samples" / rec["file"]).read_bytes()
            )
            pages = {p.page: p.text for p in res.pages}
            for name, f in res.fields.items():
                for ev in f.evidence:
                    assert 0 <= ev.start <= ev.end <= len(pages[ev.page])
                if f.evidence and f.raw_value is not None:
                    ev = f.evidence[0]
                    seg = pages[ev.page][ev.start : ev.end]
                    if f.raw_value.strip() not in seg:
                        bad.append((rec["document_id"], name, f.raw_value[:30], seg[:30]))
    assert not bad, bad[:5]


def test_b5_unit_is_not_split_across_the_cargo_name():
    r = run("Quantity: 323,100 barrels\nCommodity: DIESEL\n")
    page = r.pages[0].text
    for ev in r.fields["cargo_unit"].evidence + r.fields["cargo_quantity"].evidence:
        assert "barrels" in page[ev.start : ev.end]


# ---------------------------------------------------------------- B6: oversized text is a 413-class error
def test_b6_oversized_text_has_a_specific_error():
    with pytest.raises(TextTooLargeError) as exc:
        process_document(
            "a.txt", ("Vessel: MV A ONE\n" * 100).encode(), settings=Settings(max_text_chars=500)
        )
    assert exc.value.http_status == 413 and exc.value.code == "TEXT_TOO_LARGE"


# ---------------------------------------------------------------- B7 / B8
@pytest.mark.parametrize(
    "text", ["see clause 12345 below", "Please quote 2024 on all papers", "refer to annex 99887"]
)
def test_b7_reference_is_not_taken_from_prose(text):
    f = field(f"Reference: {text}", "document_reference")
    assert f.value is None and f.status.value == "needs_review"
    assert clean_reference(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("MSK2025-04417", "MSK2025-04417"),
        ("No. BL-123456 (revised)", "BL-123456"),
        ("FX528178.", "FX528178"),
    ],
)
def test_b7_real_references_still_work(text, expected):
    assert clean_reference(text) == expected


def test_b8_title_case_keeps_hyphen_and_apostrophe_parts():
    assert smart_title("ust-luga") == "Ust-Luga"
    assert smart_title("st. john's") == "St. John's"
    assert smart_title("LNG carrier") == "LNG Carrier"
    assert field("Port of Loading: Ust-Luga", "origin_port").value == "Ust-Luga"


# ---------------------------------------------------------------- B9 (documented assumption)
def test_b9_comma_thousands_assumption_is_explicit():
    """'1,234 MT' is read as 1234 (US/UK style). Documented in docs/architecture.md; dot-style is flagged."""
    assert field("Quantity: 1,234 MT", "cargo_quantity").value == 1234.0
    assert field("Quantity: 1.234 MT", "cargo_quantity").value is None


# ---------------------------------------------------------------- S2: cooperative deadline
def test_deadline_stops_a_large_document():
    with pytest.raises(ProcessingTimeoutError):
        process_document(
            "a.txt",
            ("Vessel: MV ALPHA ONE\n" * 40000).encode(),
            settings=Settings(processing_timeout_s=0.001),
        )


# ---------------------------------------------------------------- OCR evidence is scored lower (measured precision < 100%)
def test_ocr_candidates_get_a_penalty_and_a_note():
    from app.evidence import Candidate
    from app.pipeline import OCR_SCORE_PENALTY, _apply_ocr_penalty
    from app.schemas import PageText, Severity

    pages = [
        PageText(page=1, text="x", raw_char_count=1, ocr_used=True),
        PageText(page=2, text="y", raw_char_count=1, ocr_used=False),
    ]
    on_ocr = Candidate("vessel_name", "A", "A", 1, 0, 1, "label_match", 0.9)
    on_text = Candidate("vessel_name", "A", "A", 2, 0, 1, "label_match", 0.9)
    _apply_ocr_penalty([on_ocr, on_text], pages)
    assert on_ocr.score == pytest.approx(0.9 - OCR_SCORE_PENALTY) and on_text.score == 0.9
    assert (
        any(n[0] == "OCR_TEXT" and n[2] == Severity.INFO for n in on_ocr.notes)
        and not on_text.notes
    )


def test_ocr_text_from_a_real_scan_is_flagged_lower_than_digital_text(scanned_pdf_factory):
    from app.extractors.ocr import ocr_available

    if not ocr_available(Settings()):
        pytest.skip("Tesseract not installed")
    scan = scanned_pdf_factory("Vessel: MV NORDIC AURORA\nPort of Loading: Rotterdam")
    scanned = process_document("s.pdf", scan, settings=Settings(ocr_enabled=True), ocr=True)
    digital = run("Vessel: MV NORDIC AURORA\nPort of Loading: Rotterdam\n")
    assert (
        scanned.fields["vessel_name"].heuristic_score
        < digital.fields["vessel_name"].heuristic_score
    )
    assert "OCR_TEXT" in codes(scanned.fields["vessel_name"])


# ---------------------------------------------------------------- S5: OCR memory is bounded by pixels, not by declared size
def test_ocr_render_dpi_is_reduced_to_fit_the_pixel_cap():
    from app.errors import PageTooLargeError
    from app.extractors.ocr import render_dpi

    s = Settings(ocr_dpi=200, ocr_max_pixels=25_000_000, ocr_min_dpi=100)
    assert render_dpi(595, 842, s, 1) == 200  # A4 at 200 dpi (3.9 Mpx): untouched
    reduced = render_dpi(3000, 3000, s, 1)  # 41.7 in square: would be 69 Mpx at 200 dpi
    assert 100 <= reduced < 200 and (3000 / 72 * reduced) ** 2 <= 25_000_000
    with pytest.raises(PageTooLargeError):
        render_dpi(14400, 14400, s, 1)  # a tiny PDF declaring a 200-inch page is refused outright


def test_ocr_refuses_too_many_pages():
    from app.errors import ResourceLimitError
    from app.extractors.ocr import ocr_pdf_pages

    with pytest.raises(ResourceLimitError):
        ocr_pdf_pages(b"%PDF-", list(range(1, 30)), Settings(ocr_max_pages=20))
