from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app as api_app
from app.client import APIError, extract_via_api
from app.pipeline import process_document
from app.uihelpers import excerpt_with_markers, field_rows, sample_documents
from tests.conftest import SAMPLE_BL

ROOT = Path(__file__).resolve().parent.parent


def test_field_rows_cover_all_fields_and_show_status_text():
    rows = field_rows(process_document("bl.txt", SAMPLE_BL.encode()))
    assert len(rows) == 10
    by = {r["Field"]: r for r in rows}
    assert by["vessel_name"]["Value"] == "NORDIC AURORA"
    assert "extracted" in by["origin_port"]["Status"]
    assert by["cargo_quantity"]["Value"] == "45000"
    assert "missing" in by["discharge_date"]["Status"]  # status is text, not colour alone


def test_excerpt_is_plain_text_with_markers():
    out = excerpt_with_markers("<script>alert(1)</script> Vessel: X", 26, 34)
    assert (
        out.startswith("<script>") and "⟦" in out and "⟧" in out
    )  # raw text, rendered by st.code (no markup parsing)


def test_excerpt_marks_exact_value():
    r = process_document("bl.txt", SAMPLE_BL.encode())
    ev = r.fields["origin_port"].evidence[0]
    assert "⟦Rotterdam⟧" in excerpt_with_markers(r.pages[0].text, ev.start, ev.end)


def test_app_never_uses_unsafe_html():
    src = (ROOT / "app" / "ui.py").read_text()
    assert "unsafe_allow_html" not in src and "unsafe_allow_javascript" not in src


def test_client_roundtrip_through_api():
    http = TestClient(api_app)
    res = extract_via_api("http://x", "bl.txt", SAMPLE_BL.encode(), client=http)
    assert res.fields["vessel_name"].value == "NORDIC AURORA"


def test_client_surfaces_api_error_message():
    http = TestClient(api_app)
    with pytest.raises(APIError) as exc:
        extract_via_api("http://x", "notes.docx", b"hello", client=http)
    assert exc.value.code == "UNSUPPORTED_FILE_TYPE"


def test_client_unreachable_server():
    with pytest.raises(APIError) as exc:
        extract_via_api("http://127.0.0.1:9", "a.txt", b"hello world", timeout=2)
    assert exc.value.code == "API_UNREACHABLE"


@pytest.mark.skipif(
    not (ROOT / "data" / "annotations" / "dev.jsonl").exists(), reason="no sample data"
)
def test_sample_menu_is_varied_and_files_exist():
    menu = sample_documents(ROOT)
    assert len(menu) >= 8 and all(p.exists() for _, p in menu)


@pytest.mark.skipif(
    not (ROOT / "data" / "annotations" / "dev.jsonl").exists(), reason="no sample data"
)
def test_streamlit_app_runs_headless_with_a_sample():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "ui.py"), default_timeout=60).run()
    assert not at.exception
    sample_box = next(s for s in at.sidebar.selectbox if "sample" in s.label.lower())
    sample_box.select(sample_box.options[1]).run()
    next(b for b in at.button if b.label == "Extract").click().run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert len(at.dataframe) >= 1
    assert any("Completed" in s.value or "Needs review" in s.value for s in at.subheader)


@pytest.mark.skipif(
    not (ROOT / "data" / "annotations" / "dev.jsonl").exists(), reason="no sample data"
)
def test_streamlit_extract_without_input_shows_friendly_error():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "ui.py"), default_timeout=60).run()
    next(b for b in at.button if b.label == "Extract").click().run()
    assert not at.exception and any("Choose a file" in e.value for e in at.error)


@pytest.mark.skipif(
    not (ROOT / "data" / "annotations" / "dev.jsonl").exists(), reason="no sample data"
)
def test_streamlit_review_form_saves_a_correction():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "ui.py"), default_timeout=60).run()
    box = next(s for s in at.sidebar.selectbox if "sample" in s.label.lower())
    box.select(box.options[1]).run()
    next(b for b in at.button if b.label == "Extract").click().run()
    next(t for t in at.text_input if t.label == "counterparty").set_value("Corrected Trading Ltd")
    next(b for b in at.button if b.label == "Save corrections").click().run()
    assert not at.exception and not at.error
    df = at.dataframe[0].value
    row = df[df["Field"] == "counterparty"].iloc[0]
    assert row["Value"] == "Corrected Trading Ltd" and "corrected" in row["Status"]


# ---------------------------------------------------------------- audit S6 / S7 / session growth
MALICIOUS = (
    b"Reference: ![tracking](http://attacker.invalid/p.png?id=1)\n"
    b"Loading Date: [click here](http://attacker.invalid/login)\n"
)


def _app(**env):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(ROOT / "app" / "ui.py"), default_timeout=60)


def _pick_sample_and_extract(at, index=1):
    box = next(s for s in at.sidebar.selectbox if "sample" in s.label.lower())
    box.select(box.options[index])
    next(b for b in at.button if b.label == "Extract").click().run()


def test_ui_has_no_user_controlled_api_url():
    at = _app().run()
    assert not [t for t in at.sidebar.text_input if "api" in t.label.lower()]
    assert not at.sidebar.text_input  # nothing a user can type a URL into


def test_api_target_comes_only_from_the_operator_setting(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_API_URL", "http://127.0.0.1:9")  # closed port
    at = _app().run()
    assert any("set by the operator" in c.value for c in at.sidebar.caption)
    _pick_sample_and_extract(at)
    assert not at.exception and any("Could not reach the API" in e.value for e in at.error)


def test_api_url_must_be_http(monkeypatch):
    from app.config import ConfigError, get_settings

    monkeypatch.setenv("SHIPINTEL_API_URL", "file:///etc/passwd")
    with pytest.raises(ConfigError):
        get_settings()


def test_document_text_is_never_rendered_as_markdown():
    from app.pipeline import process_document

    res = process_document("[x](http:attacker.invalid).txt", MALICIOUS)
    at = _app()
    at.session_state["history"] = [res]
    at.session_state["current"] = res.document_id
    at.run()
    assert not at.exception
    markdown_like = (
        [m.value for m in at.markdown]
        + [w.value for w in at.warning]
        + [s.value for s in at.subheader]
    )
    assert not [v for v in markdown_like if "attacker.invalid" in v]  # nothing parsed as Markdown
    assert any(
        "attacker.invalid" in t.value for t in at.text
    )  # still visible to the reviewer, as plain text


def test_history_buttons_escape_markdown_in_filenames():
    from app.pipeline import process_document

    evil = process_document("[a](http:attacker.invalid).txt", MALICIOUS)
    good = process_document("ok.txt", b"Vessel: MV ALPHA ONE\n")
    at = _app()
    at.session_state["history"] = [evil, good]
    at.session_state["current"] = good.document_id
    at.run()
    labels = [b.label for b in at.button if "attacker" in b.label]
    assert labels and not any("](" in label for label in labels)


def test_session_history_is_capped(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_UI_MAX_HISTORY", "2")
    at = _app().run()
    for i in (1, 2, 3):
        _pick_sample_and_extract(at, index=i)
    assert len(at.session_state["history"]) == 2


def test_trim_history_and_md_escape():
    from app.uihelpers import md_escape, trim_history

    assert trim_history([1, 2, 3, 4], 2) == [3, 4] and trim_history([1], 5) == [1]
    out = md_escape("[click](http://e/x) ![i](u) **b**\n\x00" + "a" * 500, limit=60)
    assert "](" not in out.replace("\\]\\(", "") and len(out) < 200 and "\n" not in out


def test_ocr_and_nlp_boxes_follow_server_policy():
    at = _app().run()
    ocr = next(c for c in at.sidebar.checkbox if "OCR" in c.label)
    nlp = next(c for c in at.sidebar.checkbox if "spaCy" in c.label)
    assert ocr.value is False and nlp.value is False  # server default off => off and locked
