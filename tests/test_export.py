from __future__ import annotations

import csv
import io
import json

from app.exporters import csv_bytes, csv_safe, to_csv, to_json, to_wide_csv
from app.pipeline import apply_corrections, process_document
from app.schemas import FIELD_NAMES, ExtractionResult
from tests.conftest import SAMPLE_BL


def result():
    return process_document("bl.txt", SAMPLE_BL.encode())


def test_json_is_valid_and_roundtrips():
    text = to_json(result())
    payload = json.loads(text)
    assert payload["pages"] is None  # text excluded by default
    again = ExtractionResult.model_validate(payload)
    assert again.fields["vessel_name"].value == "NORDIC AURORA"


def test_json_can_include_text():
    assert json.loads(to_json(result(), include_text=True))["pages"][0]["text"].startswith(
        "BILL OF LADING"
    )


def test_csv_has_one_row_per_field_and_parses_back():
    rows = list(csv.DictReader(io.StringIO(to_csv(result()))))
    assert [r["field"] for r in rows] == list(FIELD_NAMES)
    by = {r["field"]: r for r in rows}
    assert by["cargo_quantity"]["value"] == "45000.0"
    assert by["discharge_date"]["value"] == "" and by["discharge_date"]["status"] == "missing"
    assert "Rotterdam" in by["origin_port"]["evidence_snippet"]


def test_wide_csv():
    rows = list(csv.DictReader(io.StringIO(to_wide_csv([result(), result()]))))
    assert len(rows) == 2 and rows[0]["origin_port"] == "Rotterdam"


def test_csv_formula_injection_is_neutralised():
    for bad in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx"):
        assert csv_safe(bad).startswith("'")
    assert csv_safe("Normal text") == "Normal text" and csv_safe(None) == ""
    r = process_document("x.txt", b'Vessel: =HYPERLINK("http://evil")\nShipper: Acme Trading Ltd\n')
    cells = [c for row in csv.reader(io.StringIO(to_csv(r))) for c in row]
    assert not any(c.startswith("=") for c in cells)


def test_csv_bytes_have_bom_for_excel():
    assert csv_bytes("a").startswith(b"\xef\xbb\xbf")


def test_human_correction_updates_status_and_validates():
    r = result()
    fixed, errors = apply_corrections(r, {"discharge_date": "2025-04-02", "origin_port": "Antwerp"})
    assert not errors
    assert fixed.fields["discharge_date"].value == "2025-04-02"
    assert fixed.fields["discharge_date"].status.value == "human_corrected"
    assert fixed.fields["origin_port"].status.value == "human_corrected"
    assert fixed.fields["vessel_name"].status.value != "human_corrected"
    assert r.fields["discharge_date"].value is None  # original untouched


def test_human_correction_rejects_invalid_input():
    fixed, errors = apply_corrections(
        result(), {"discharge_date": "2025-03-01", "cargo_quantity": "abc"}
    )
    assert fixed is None and errors
    fixed, errors = apply_corrections(result(), {"discharge_date": "2025-03-01"})
    assert fixed is None and any("discharge" in e for e in errors)  # before loading date 2025-03-12
