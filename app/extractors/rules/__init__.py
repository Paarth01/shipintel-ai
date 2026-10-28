"""Rule-based field extraction (dictionaries + regular expressions). NOT a trained model.

Two evidence sources:
  1. Label scan: 'Label: value', aligned 'LABEL   value', pipe/column separated pairs, and a
     label whose value sits on the next line (typical PDF table extraction). Labels are matched
     against alias dictionaries (exact, then fuzzy for typos).
  2. Inline patterns for prose ('M/V X ... loading at A, discharging at B ...'). These get lower
     scores and, for ports, must hit the gazetteer so ordinary capitalised words are not taken.

Nothing is inferred: if a value is not in the text the field stays missing.
"""

from __future__ import annotations

from app.deadline import Deadline, FuzzyBudget
from app.evidence import Candidate
from app.extractors.rules.inline import inline_candidates
from app.extractors.rules.labels import scan_labels
from app.extractors.rules.values import candidates_from_kv
from app.schemas import PageText

__all__ = ["extract_candidates"]


def extract_candidates(
    pages: list[PageText],
    deadline: Deadline | None = None,
    fuzzy_budget: FuzzyBudget | None = None,
) -> list[Candidate]:
    cands: list[Candidate] = []
    for page in pages:
        if deadline is not None:
            deadline.check()
        for kv in scan_labels(page.text, fuzzy_budget, deadline):
            cands.extend(candidates_from_kv(page, kv))
        if deadline is not None:
            deadline.check()
        cands.extend(inline_candidates(page))
    return cands
