"""Shared constants and helpers for the rule-based extractor."""

from __future__ import annotations

# Base heuristic scores by evidence type (see docs/architecture.md)
S_LABEL, S_NEXT, S_INLINE, FUZZY_PENALTY = 0.90, 0.85, 0.65, 0.15


def collapse(s: str) -> str:
    return " ".join(s.split())


def same_text(raw: str, value: str) -> bool:
    return collapse(raw).casefold() == collapse(value).casefold()
