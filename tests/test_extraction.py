from __future__ import annotations

import pytest

from app.pipeline import process_document
from tests.conftest import SAMPLE_BL


def run(text: str, name: str = "t.txt"):
    return process_document(name, text.encode())


def vals(text: str) -> dict:
    return run(text).values()


def test_bill_of_lading_all_fields():
    v = vals(SAMPLE_BL)
    assert v["vessel_name"] == "NORDIC AURORA"
    assert v["origin_port"] == "Rotterdam" and v["destination_port"] == "Singapore"
    assert v["cargo_type"] == "Thermal Coal"
    assert v["cargo_quantity"] == 45000.0 and v["cargo_unit"] == "MT"
    assert v["loading_date"] == "2025-03-12"
    assert v["discharge_date"] is None  # absent in the document -> null, not guessed
    assert v["document_reference"] == "MSK2025-04417"
    assert v["counterparty"] == "Meridian Bulk Trading Ltd"


def test_missing_fields_are_null_with_warning_never_invented():
    r = run("Vessel: MV OCEAN PIONEER\nSome unrelated paragraph about weather.")
    assert r.fields["vessel_name"].value == "OCEAN PIONEER"
    for name in ("origin_port", "cargo_type", "loading_date", "counterparty"):
        f = r.fields[name]
        assert f.value is None and f.status.value == "missing"
        assert any(w.code == "FIELD_NOT_FOUND" for w in f.warnings)


def test_aligned_columns_without_colons():
    text = (
        "SHIPPING INSTRUCTION\n"
        "VESSEL             PACIFIC TRADER\n"
        "LOADING PORT       Port Hedland\n"
        "DISCHARGE PORT     Qingdao\n"
        "COMMODITY          Iron Ore\n"
        "QUANTITY           150,000 MT\n"
    )
    v = vals(text)
    assert (v["vessel_name"], v["origin_port"], v["destination_port"]) == (
        "PACIFIC TRADER",
        "Port Hedland",
        "Qingdao",
    )
    assert (v["cargo_type"], v["cargo_quantity"], v["cargo_unit"]) == ("Iron Ore", 150000.0, "MT")


def test_value_on_next_line_like_pdf_tables():
    text = (
        "Vessel Name\nGOLDEN HORIZON\nOrigin\nSantos\nDestination\nHamburg\nCommodity\nSoybeans\n"
    )
    v = vals(text)
    assert v["vessel_name"] == "GOLDEN HORIZON"
    assert v["origin_port"] == "Santos" and v["destination_port"] == "Hamburg"
    assert v["cargo_type"] == "Soybeans"


def test_empty_cell_does_not_steal_next_label():
    v = vals("Vessel Name\nOrigin\nSantos\n")
    assert v["vessel_name"] is None and v["origin_port"] == "Santos"


def test_pipe_separated_pairs_on_one_line():
    v = vals("Vessel: MV STAR HARMONY | Ref: CP-2025-0098\nFrom: Houston | To: Rotterdam\n")
    assert v["vessel_name"] == "STAR HARMONY" and v["document_reference"] == "CP-2025-0098"
    assert v["origin_port"] == "Houston" and v["destination_port"] == "Rotterdam"


def test_prose_inline_patterns():
    text = (
        "Dear Sirs,\nM/V Atlantic Spirit, chartered by Orion Commodities Ltd, is carrying "
        "32,500 MT of Wheat. She will be loading at Santos and discharging at Durban. "
        "Loading commenced on 3 June 2025 and discharge on 21 June 2025.\n"
    )
    r = run(text)
    v = r.values()
    assert v["vessel_name"] == "ATLANTIC SPIRIT"
    assert v["counterparty"] == "Orion Commodities Ltd"
    assert (v["cargo_quantity"], v["cargo_unit"], v["cargo_type"]) == (32500.0, "MT", "Wheat")
    assert (v["origin_port"], v["destination_port"]) == ("Santos", "Durban")
    assert v["loading_date"] == "2025-06-03" and v["discharge_date"] == "2025-06-21"
    assert r.fields["origin_port"].evidence[0].method == "inline_pattern"


def test_inline_ports_require_gazetteer_hit():
    v = vals("Please arrange loading at Monday Morning Station and delivery to Friday Harbour.")
    assert v["origin_port"] is None and v["destination_port"] is None


def test_distractor_dates_are_not_used():
    text = (
        "Date of Issue: 02 March 2025\nInvoice date: 05 March 2025\nPayment due 04 April 2025\n"
        "Delivery terms: FOB. Invoice date: 12 March 2025\n"
    )
    v = vals(text)
    assert v["loading_date"] is None and v["discharge_date"] is None


def test_typo_in_label_uses_fuzzy_match_and_says_so():
    r = run("Vessei Name: MV BLUE FORTUNE\nPort of Loadinq: Busan\n")
    assert r.fields["vessel_name"].value == "BLUE FORTUNE"
    assert r.fields["origin_port"].value == "Busan"
    assert r.fields["vessel_name"].evidence[0].method == "label_fuzzy"
    assert any(w.code == "LABEL_FUZZY_MATCH" for w in r.fields["vessel_name"].warnings)


def test_port_spelling_noise_is_fuzzy_matched():
    f = run("Port of Loading: Rotterdarn\n").fields["origin_port"]
    assert f.value == "Rotterdam"
    assert any(w.code == "PORT_FUZZY_MATCH" for w in f.warnings)


def test_unknown_port_kept_with_warning():
    f = run("Port of Loading: Vizhinjam\n").fields["origin_port"]
    assert f.value == "Vizhinjam"
    assert any(w.code == "UNRECOGNIZED_PORT" for w in f.warnings)


def test_country_suffix_and_locode_are_stripped():
    v = vals("Port of Loading: Rotterdam, Netherlands\nPort of Discharge: Port Hedland (AUPHE)\n")
    assert v["origin_port"] == "Rotterdam" and v["destination_port"] == "Port Hedland"
    assert vals("Loading Port: NLRTM\n")["origin_port"] == "Rotterdam"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Loading Date: 12 March 2025", "2025-03-12"),
        ("Loading Date: March 12, 2025", "2025-03-12"),
        ("Loading Date: 12-Mar-2025", "2025-03-12"),
        ("Loading Date: 2025-03-12", "2025-03-12"),
        ("Loading Date: 12th March 2025 0600 LT", "2025-03-12"),
        ("Loading Date: 12.03.2025", "2025-03-12"),
        ("Loading Date: 25/03/2025", "2025-03-25"),
    ],
)
def test_date_formats(text, expected):
    assert vals(text)["loading_date"] == expected


def test_ambiguous_numeric_date_is_null_and_needs_review():
    f = run("Loading Date: 03/04/2025").fields["loading_date"]
    assert f.value is None and f.status.value == "needs_review"
    assert any(w.code == "AMBIGUOUS_DATE" for w in f.warnings)
    assert f.evidence and "03/04/2025" in f.evidence[0].snippet


def test_impossible_date_is_invalid():
    f = run("Loading Date: 31 February 2025").fields["loading_date"]
    assert f.value is None and f.status.value == "invalid"
    assert any(w.code == "INVALID_DATE" for w in f.warnings)


@pytest.mark.parametrize(
    "text,qty,unit",
    [
        ("Quantity: 45,000 MT", 45000.0, "MT"),
        ("Quantity: 32.500,5 metric tons", 32500.5, "MT"),
        ("Quantity: 45 000 tonnes", 45000.0, "MT"),
        ("Quantity: 1,200,000 bbl", 1200000.0, "bbl"),
        ("Quantity: 4,500 TEU", 4500.0, "TEU"),
        ("Quantity: 170,000 cbm", 170000.0, "m3"),
        ("Quantity (MT): 52,000", 52000.0, "MT"),
    ],
)
def test_quantity_and_unit_normalisation(text, qty, unit):
    v = vals(text)
    assert (v["cargo_quantity"], v["cargo_unit"]) == (qty, unit)


def test_ambiguous_thousands_separator_is_not_guessed():
    f = run("Quantity: 45.000 MT").fields["cargo_quantity"]
    assert f.value is None and f.status.value == "needs_review"
    assert any(w.code == "QUANTITY_AMBIGUOUS" for w in f.warnings)


def test_tons_unit_flagged_ambiguous():
    f = run("Quantity: 40,000 tons").fields["cargo_unit"]
    assert f.value == "MT" and any(w.code == "UNIT_AMBIGUOUS" for w in f.warnings)


def test_cargo_with_tolerance_and_bulk_wording():
    v = vals("Cargo: approx. 55,000 MT Thermal coal in bulk +/- 10%")
    assert v["cargo_type"] == "Thermal Coal" and v["cargo_quantity"] == 55000.0


def test_counterparty_priority_charterer_over_shipper():
    r = run(
        "Shipper: Alpha Exports Ltd\nConsignee: Gamma Imports GmbH\nCharterers: Beta Chartering Pte Ltd\n"
    )
    assert r.fields["counterparty"].value == "Beta Chartering Pte Ltd"
    assert any(w.code == "OTHER_PARTIES_FOUND" for w in r.fields["counterparty"].warnings)


def test_address_is_cut_from_counterparty():
    v = vals("Shipper: Baltic Coal Trading Ltd., 12 Harbour Road, London\n")
    assert v["counterparty"] == "Baltic Coal Trading Ltd."


def test_placeholder_values_are_not_extracted():
    r = run("Vessel: TBN\nDischarge Port: TBA\nLoading Date: to be advised\n")
    for name in ("vessel_name", "destination_port", "loading_date"):
        assert r.fields[name].value is None
        assert r.fields[name].status.value == "needs_review"


def test_conflicting_values_flagged():
    r = run("Vessel: MV ALPHA ONE\nVessel Name: MV BRAVO TWO\n")
    f = r.fields["vessel_name"]
    assert f.status.value == "needs_review"
    assert any(w.code == "CONFLICTING_VALUES" for w in f.warnings)


def test_non_shipping_text_yields_no_fields_and_warning():
    r = run("Meeting notes: buy printer paper and stamps. Lunch at noon.")
    assert all(v is None for v in r.values().values())
    assert any(w.code == "NO_FIELDS_FOUND" for w in r.warnings)
    assert r.status.value == "needs_review"


def test_evidence_offsets_point_at_value_in_cleaned_text():
    r = run(SAMPLE_BL)
    page_text = r.pages[0].text
    for name in ("vessel_name", "origin_port", "document_reference", "counterparty"):
        ev = r.fields[name].evidence[0]
        assert page_text[ev.start : ev.end].strip() == r.fields[name].raw_value.strip()
        assert ev.page == 1 and ev.snippet


def test_pdf_page_numbers_in_evidence(pdf_factory):
    data = pdf_factory(
        ["Cover page with no fields at all, just a title line", "Vessel: MV NORDIC AURORA"]
    )
    r = process_document("two.pdf", data)
    assert r.fields["vessel_name"].value == "NORDIC AURORA"
    assert r.fields["vessel_name"].evidence[0].page == 2


def test_heuristic_score_is_bounded_and_named_honestly():
    r = run(SAMPLE_BL)
    for f in r.fields.values():
        assert f.heuristic_score is None or 0 <= f.heuristic_score <= 1


def test_inline_name_patterns_do_not_cross_label_lines():
    # regression: 'Quantity: 15 000 MT' followed by a 'Date Loaded:' line must not yield a cargo type
    v = vals("Quantity: 15 000 MT\nDate Loaded: 12 June 2025\n")
    assert v["cargo_type"] is None and v["cargo_quantity"] == 15000.0
    # regression: vessel name must stop at the end of its line
    v = vals("Vessel Name   MV Ocean Aurora\nOrigin   Tianjin (CNTSN)\n")
    assert v["vessel_name"] == "OCEAN AURORA" and v["origin_port"] == "Tianjin"


def test_wrapped_prose_is_handled():
    text = (
        "Please be advised that MV Cape Endeavour has arrived and is ready to load at Colombo.\n"
        "She is chartered by Zenith Logistics Co.\nLtd and is carrying 173300 MT of\niron ore. "
        "Loading commenced on 15 November 2025.\n"
    )
    v = vals(text)
    assert v["counterparty"] == "Zenith Logistics Co. Ltd"
    assert (v["cargo_type"], v["cargo_quantity"]) == ("Iron Ore", 173300.0)
    assert v["loading_date"] == "2025-11-15" and v["origin_port"] == "Colombo"


def test_dotted_legal_suffix_and_trailing_and():
    v = vals(
        "M/V Atlantic Spirit, chartered by Aldgate Resources S.A. and is carrying 5,000 MT of Wheat.\n"
    )
    assert v["counterparty"] == "Aldgate Resources S.A."


def test_bare_vessel_name_in_notice_prose():
    assert (
        vals("Please be advised that NORDIC PROVIDENCE V.12E has arrived at the berth.\n")[
            "vessel_name"
        ]
        == "NORDIC PROVIDENCE"
    )
    assert vals("Please be advised that Delivery has been delayed.\n")["vessel_name"] is None


def test_typo_in_aligned_label_is_fuzzy_matched():
    v = vals(
        "Vessle Name             MV Ocean Aurora\nShipper                 Granite Agri Exports B.V.\n"
    )
    assert v["vessel_name"] == "OCEAN AURORA"


def test_cargo_synonym_and_origin_label_with_unknown_port():
    v = vals("Commodity: Liquefied Natural Gas\nOrigin: Vizhinjam\n")
    assert v["cargo_type"] == "LNG"
    r = run("Origin: Malaysia\n")
    assert (
        r.fields["origin_port"].status.value == "needs_review"
    )  # country-of-origin style value is flagged


def test_wrap_guard_stops_at_aligned_label_lines_without_colons():
    text = (
        "Quantity                     36 000 tonnes\nDate Loaded                  8 August 2024\n"
    )
    v = vals(text)
    assert (
        v["cargo_type"] is None
        and v["cargo_quantity"] == 36000.0
        and v["loading_date"] == "2024-08-08"
    )


def test_wrapped_multiword_cargo_is_not_cut_at_line_end():
    v = vals(
        "She is carrying 4600 TEUs of Containerised\nGeneral Cargo. Loading commenced on 3 June 2025.\n"
    )
    assert v["cargo_type"] == "Containerised General Cargo"


def test_numbered_clause_labels():
    v = vals(
        "1. Vessel: MV STAR HARMONY\n2. Load Port: Houston\n(a) Discharge Port: Rotterdam\n- Quantity: 5,000 MT\n"
    )
    assert v["vessel_name"] == "STAR HARMONY" and v["origin_port"] == "Houston"
    assert v["destination_port"] == "Rotterdam" and v["cargo_quantity"] == 5000.0


def test_lift_quantity_at_port_and_reference_sentence():
    v = vals(
        "MV Ocean Pioneer will lift 32,500 MT of Wheat at Santos for delivery to Durban. Our reference is CP2024/9108.\n"
    )
    assert (v["origin_port"], v["destination_port"]) == ("Santos", "Durban")
    assert v["document_reference"] == "CP2024/9108"


def test_reference_inline_ignores_prose_without_id():
    assert (
        vals("Please see the reference section below for details.\n")["document_reference"] is None
    )


def test_lift_at_port_wrapped_after_preposition():
    v = vals(
        "MV Ocean Pioneer will lift 1,271,400.5 BBLS of Crude Oil at\nKAOHSIUNG for delivery to ANTWERP.\n"
    )
    assert (v["origin_port"], v["destination_port"]) == ("Kaohsiung", "Antwerp")
