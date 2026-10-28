from __future__ import annotations

from app.pipeline import process_document
from app.validators import build_record, sanitize_filename


def run(text: str):
    return process_document("t.txt", text.encode())


def codes(result) -> set[str]:
    return {w.code for w in result.all_warnings()}


def test_discharge_before_loading_flagged():
    r = run("Loading Date: 20 March 2025\nDischarge Date: 05 March 2025\n")
    assert "DISCHARGE_BEFORE_LOADING" in codes(r)
    assert r.fields["discharge_date"].status.value == "needs_review"
    assert r.fields["loading_date"].status.value == "needs_review"
    assert r.fields["discharge_date"].value == "2025-03-05"  # evidence-backed; not altered


def test_valid_date_order_has_no_warning():
    r = run("Loading Date: 05 March 2025\nDischarge Date: 20 March 2025\n")
    assert "DISCHARGE_BEFORE_LOADING" not in codes(r)


def test_same_port_flagged():
    r = run("Port of Loading: Singapore\nPort of Discharge: Singapore\n")
    assert "SAME_PORT" in codes(r)


def test_nonpositive_quantity_rejected():
    f = run("Quantity: 0 MT").fields["cargo_quantity"]
    assert f.value is None and f.status.value == "invalid"
    assert any(w.code == "NONPOSITIVE_QUANTITY" for w in f.warnings)


def test_quantity_without_unit_needs_review():
    f = run("Quantity: 45,000").fields["cargo_quantity"]
    assert f.value == 45000.0 and f.status.value == "needs_review"
    assert any(w.code == "UNIT_MISSING" for w in f.warnings)


def test_implausible_quantity_flagged():
    f = run("Quantity: 900,000,000 MT").fields["cargo_quantity"]
    assert any(w.code == "QUANTITY_IMPLAUSIBLE" for w in f.warnings)


def test_build_record_accepts_valid_values():
    rec, errors = build_record(
        {
            "vessel_name": "X",
            "cargo_quantity": 10,
            "cargo_unit": "MT",
            "loading_date": "2025-03-12",
            "discharge_date": "",
        }
    )
    assert not errors and rec.discharge_date is None and rec.cargo_unit == "MT"


def test_build_record_rejects_bad_values():
    _, errors = build_record(
        {"cargo_quantity": -5, "cargo_unit": "furlongs", "loading_date": "12/13/2025"}
    )
    joined = " ".join(errors)
    assert "cargo_quantity" in joined and "cargo_unit" in joined and "loading_date" in joined


def test_build_record_rejects_date_order():
    _, errors = build_record({"loading_date": "2025-03-20", "discharge_date": "2025-03-01"})
    assert errors


def test_sanitize_filename():
    assert sanitize_filename("..\\..\\evil/../bl.pdf") == "bl.pdf"
    assert sanitize_filename("") == "upload"
    assert sanitize_filename("a\x00b.txt") == "ab.txt"
