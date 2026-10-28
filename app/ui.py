"""Streamlit UI. Run with:  streamlit run app/ui.py

Security notes: the API target is operator-configured (SHIPINTEL_API_URL) and cannot be changed by
users; document-derived text is shown with st.text (never parsed as Markdown); OCR/NLP follow server
policy (a user can switch them off, never on); only the newest N results are kept per session.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import PIPELINE_VERSION, __version__  # noqa: E402
from app.client import extract_via_api  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.errors import ShipIntelError  # noqa: E402
from app.exporters import csv_bytes, to_csv, to_json, to_wide_csv  # noqa: E402
from app.extractors.nlp import nlp_available  # noqa: E402
from app.extractors.ocr import ocr_available  # noqa: E402
from app.pipeline import apply_corrections, process_document  # noqa: E402
from app.schemas import FIELD_NAMES, ExtractionResult  # noqa: E402
from app.uihelpers import (  # noqa: E402
    display_value,
    excerpt_with_markers,
    field_rows,
    md_escape,
    sample_documents,
    trim_history,
)

st.set_page_config(page_title="ShipIntel AI", page_icon="🚢", layout="wide")
settings = get_settings()
API_MODE = bool(settings.api_url)


@st.cache_data(show_spinner=False)
def _capabilities() -> tuple[bool, bool]:
    return ocr_available(settings), nlp_available(settings)


ocr_ok, nlp_ok = _capabilities()
ss = st.session_state
ss.setdefault("history", [])  # list[ExtractionResult], newest last, capped
ss.setdefault("current", None)  # document_id
ss.setdefault("error", None)

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    if API_MODE:
        st.caption(
            f"Mode: API service at **{md_escape(str(urlparse(settings.api_url or '').netloc))}** (set by the operator)"
        )
    else:
        st.caption("Mode: in-process pipeline")
    # Server policy: these can be switched OFF here, never ON beyond what the operator enabled.
    use_ocr = st.checkbox(
        "OCR for scanned PDFs",
        value=settings.ocr_enabled and (ocr_ok or API_MODE),
        disabled=not (settings.ocr_enabled and (ocr_ok or API_MODE)),
        help="Enabled by the operator (SHIPINTEL_OCR_ENABLED). See README 'Optional OCR'.",
    )
    use_nlp = st.checkbox(
        "Add spaCy NER suggestions",
        value=settings.nlp_enabled and (nlp_ok or API_MODE),
        disabled=not (settings.nlp_enabled and (nlp_ok or API_MODE)),
        help="Enabled by the operator (SHIPINTEL_NLP_ENABLED); suggestions are always marked for review.",
    )
    show_text = st.checkbox("Show page text with evidence highlight", value=True)
    st.divider()
    samples = sample_documents(ROOT)
    choice = st.selectbox("Or try a synthetic sample", ["-"] + [s[0] for s in samples])
    st.caption(f"v{__version__} · pipeline {PIPELINE_VERSION}")

st.title("🚢 ShipIntel AI")
st.caption(
    "Extract shipping fields from PDF/TXT documents with **evidence**, validation and review. "
    "Extraction is a **rule-based baseline** (not a trained model). The heuristic score is "
    "a rule-confidence indicator, **not a calibrated probability**. Sample documents are synthetic."
)

# ----------------------------------------------------------------------------- input
col_up, col_btn = st.columns([3, 1])
upload = col_up.file_uploader("Upload a .pdf or .txt shipping document", type=["pdf", "txt"])
run = col_btn.button("Extract", type="primary", width="stretch")

if run:
    ss.error = None
    name: str | None = None
    data: bytes | None = None
    if upload is not None:
        name, data = upload.name, upload.getvalue()
    elif choice != "-":
        path = dict(samples)[choice]
        name, data = path.name, path.read_bytes()
    else:
        ss.error = "Choose a file to upload or pick a sample first."
    if name is not None and data is not None:
        ocr_param = False if (settings.ocr_enabled and not use_ocr) else None
        nlp_param = False if (settings.nlp_enabled and not use_nlp) else None
        try:
            with st.spinner("Extracting..."):
                if settings.api_url:
                    fresh = extract_via_api(
                        settings.api_url,
                        name,
                        data,
                        ocr=ocr_param,
                        nlp=nlp_param,
                        api_key=settings.api_key,
                    )
                else:
                    fresh = process_document(
                        name, data, settings=settings, ocr=ocr_param, nlp=nlp_param
                    )
            ss.history = trim_history([*ss.history, fresh], settings.ui_max_history)
            ss.current = fresh.document_id
        except ShipIntelError as exc:
            ss.error = exc.message
        except Exception:  # noqa: BLE001 - never show a traceback to the user
            ss.error = "Something went wrong while processing this document."

if ss.error:
    st.error(ss.error)  # messages are fixed strings from this code base, not document text

result: ExtractionResult | None = next((r for r in ss.history if r.document_id == ss.current), None)
if result is None:
    st.info("Upload a document (or choose a sample in the sidebar) and press **Extract**.")
    st.stop()

# ----------------------------------------------------------------------------- results
m = result.metadata
st.subheader("⚠️ Needs review" if result.status.value == "needs_review" else "✅ Completed")
st.text(f"File: {m.filename}")  # plain text: a filename can contain Markdown
c1, c2, c3, c4 = st.columns(4)
c1.metric("Pages", m.page_count)
c2.metric("Text source", m.text_source)
c3.metric("Extractor", m.extractor)
c4.metric("Processing time", f"{m.processing_ms:.0f} ms")
for w in result.warnings:
    st.warning(w.code)
    st.text(w.message)

rows = field_rows(result)
st.dataframe(
    pd.DataFrame(rows),
    hide_index=True,
    width="stretch",
    column_config={
        "Heuristic score": st.column_config.ProgressColumn(
            "Heuristic score", min_value=0, max_value=1, format="%.2f"
        ),
        "Evidence": st.column_config.TextColumn("Evidence", width="large"),
    },
)

flagged = [
    w for w in result.all_warnings() if w.code != "FIELD_NOT_FOUND" and w.severity.value != "info"
]
if flagged:
    with st.expander(f"Warnings ({len(flagged)})", expanded=True):
        for w in flagged:
            # code and field come from this code base; the message may embed document text -> st.text
            st.markdown(f"**{w.field or 'document'}** · `{w.code}`")
            st.text(w.message)

if show_text and result.pages:
    with st.expander("Evidence in source text"):
        names = [n for n in FIELD_NAMES if result.fields[n].evidence]
        if names:
            pick = st.selectbox("Field", names, key=f"ev_{result.document_id}")
            ev = result.fields[pick].evidence[0]
            page = next(p for p in result.pages if p.page == ev.page)
            st.caption(f"Page {ev.page} · method: {ev.method}")
            st.code(
                excerpt_with_markers(page.text, ev.start, ev.end), language=None, wrap_lines=True
            )
        else:
            st.write("No field has evidence.")

# ----------------------------------------------------------------------------- review
with st.expander("Review and correct values"):
    st.caption(
        "Edit values, then save. Dates must be unambiguous (e.g. 2025-03-12); empty = no value."
    )
    with st.form(f"review_{result.document_id}"):
        edits = {}
        cols = st.columns(2)
        for i, name in enumerate(FIELD_NAMES):
            edits[name] = cols[i % 2].text_input(
                name, value=display_value(result.fields[name]), key=f"c_{result.document_id}_{name}"
            )
        if st.form_submit_button("Save corrections"):
            fixed, errors = apply_corrections(result, edits)
            if errors:
                for e in errors:
                    st.error(e)
            else:
                idx = next(
                    i for i, r in enumerate(ss.history) if r.document_id == result.document_id
                )
                ss.history[idx] = fixed
                st.rerun()

# ----------------------------------------------------------------------------- export
st.subheader("Export")
inc = st.checkbox("Include page text in JSON", value=False)
d1, d2, d3 = st.columns(3)
d1.download_button(
    "⬇ JSON", to_json(result, include_text=inc), f"{m.filename}.json", "application/json"
)
d2.download_button(
    "⬇ CSV (this document)", csv_bytes(to_csv(result)), f"{m.filename}.csv", "text/csv"
)
if len(ss.history) > 1:
    d3.download_button(
        "⬇ CSV (all, wide)", csv_bytes(to_wide_csv(ss.history)), "shipintel_session.csv", "text/csv"
    )

if len(ss.history) > 1:
    with st.expander(f"Session history ({len(ss.history)}, newest {settings.ui_max_history} kept)"):
        for r in reversed(ss.history):
            label = f"{md_escape(r.metadata.filename, 60)} · {r.status.value} · {r.document_id}"
            if st.button(label, key=f"h_{r.document_id}"):
                ss.current = r.document_id
                st.rerun()
        if st.button("Clear history"):
            ss.history, ss.current = [], None
            st.rerun()
st.caption(
    "Documents are processed in memory and are not stored on the server; history lives in this browser session "
    f"only (newest {settings.ui_max_history} kept)."
)
