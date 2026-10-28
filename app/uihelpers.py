"""Presentation helpers for the Streamlit UI (no Streamlit import, so they are unit-testable)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.schemas import FIELD_NAMES, ExtractionResult, FieldResult

STATUS_LABEL = {
    "extracted": "✅ extracted",
    "normalized": "✅ normalized",
    "missing": "⚪ missing",
    "invalid": "❌ invalid",
    "needs_review": "⚠️ needs review",
    "human_corrected": "✏️ corrected",
}


def display_value(f: FieldResult) -> str:
    if f.value is None:
        return ""
    return f"{f.value:g}" if isinstance(f.value, float) else str(f.value)


def field_rows(result: ExtractionResult) -> list[dict]:
    rows = []
    for name in FIELD_NAMES:
        f = result.fields[name]
        ev = f.evidence[0] if f.evidence else None
        shown = [w for w in f.warnings if w.code != "FIELD_NOT_FOUND"]
        rows.append(
            {
                "Field": name,
                "Value": display_value(f),
                "Status": STATUS_LABEL[f.status.value],
                "Heuristic score": f.heuristic_score,
                "Page": ev.page if ev else None,
                "Evidence": ev.snippet if ev else "",
                "Warnings": "; ".join(w.code for w in shown),
            }
        )
    return rows


def excerpt_with_markers(text: str, start: int, end: int, context: int = 400) -> str:
    """Plain-text excerpt of `text` with the evidence span wrapped in ⟦ ⟧. No HTML, no Markdown:
    render with st.code / st.text so document content can never be interpreted as markup."""
    a, b = max(0, start - context), min(len(text), end + context)
    prefix = "…" if a > 0 else ""
    suffix = "…" if b < len(text) else ""
    return f"{prefix}{text[a:start]}⟦{text[start:end]}⟧{text[end:b]}{suffix}"


def sample_documents(root: Path) -> list[tuple[str, Path]]:
    """A small, varied menu of dev-split synthetic samples (one per template + special cases)."""
    ann = root / "data" / "annotations" / "dev.jsonl"
    if not ann.is_file():
        return []
    recs = [
        json.loads(line) for line in ann.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    seen_templates: set[str] = set()
    picks: list[dict] = []
    for r in recs:
        if r["template"] not in seen_templates and r["kind"] == "normal":
            seen_templates.add(r["template"])
            picks.append(r)
    for kind in ("ambiguous_date", "date_order", "invalid_date", "zero_qty", "non_shipping"):
        match = next((r for r in recs if r["kind"] == kind), None)
        if match:
            picks.append(match)
    out = []
    for r in picks:
        suffix = "" if r["kind"] == "normal" else f" - {r['kind'].replace('_', ' ')}"
        out.append(
            (
                f"{r['document_id']} · {r['template'].split('_', 1)[1].replace('_', ' ')}"
                f" ({r['file'].rsplit('.', 1)[-1]}){suffix}",
                root / "data" / "samples" / r["file"],
            )
        )
    return out


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def md_escape(text: str, limit: int = 120) -> str:
    """Neutralise Markdown in untrusted text used where Streamlit renders Markdown (e.g. button labels).

    Every ASCII punctuation character is backslash-escaped (valid CommonMark), control characters
    are dropped and the length is capped. Document-derived warning text is NOT rendered through
    Markdown at all (st.text is used); this helper covers the remaining label cases.
    """
    text = _CONTROL.sub(" ", text)[:limit]
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", text)


def trim_history(history: list, keep: int) -> list:
    """Keep only the newest `keep` results (each holds the full page text)."""
    return history[-keep:] if keep > 0 else history
