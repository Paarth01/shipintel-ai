"""Candidates -> FieldResult packaging: evidence snippets, heuristic scores, conflicts, statuses."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field

from app.config import Settings
from app.schemas import (
    FIELD_NAMES,
    Evidence,
    FieldResult,
    FieldStatus,
    Severity,
    WarningItem,
)

Note = tuple[str, str, Severity]  # (code, message, severity)

AMBIGUITY_CODES = frozenset(
    {
        "DATE_RANGE",
        "MULTIPLE_DATES",
        "AMBIGUOUS_DATE",
        "INVALID_DATE",
        "QUANTITY_RANGE",
        "QUANTITY_MULTIPLE",
        "QUANTITY_AMBIGUOUS",
    }
)


@dataclass
class Candidate:
    field: str
    value: str | float | None
    raw: str | None
    page: int
    start: int  # value span in the cleaned page text
    end: int
    method: str  # label_match | label_next_line | label_fuzzy | inline_pattern | spacy_ner
    score: float
    label: str | None = None
    status: str = "extracted"  # extracted | normalized | needs_review | invalid
    notes: list[Note] = dc_field(default_factory=list)
    role: int = 0  # counterparty priority (lower = preferred)
    ctx_start: int | None = None  # start of label (for evidence snippet)

    @property
    def key(self) -> str | float | None:
        if isinstance(self.value, str):
            return " ".join(self.value.casefold().split())
        return self.value


def make_evidence(
    text: str,
    page: int,
    start: int,
    end: int,
    label: str | None,
    method: str,
    ctx_start: int | None = None,
) -> Evidence:
    a = text.rfind("\n", 0, ctx_start if ctx_start is not None else start) + 1
    b = text.find("\n", end)
    b = len(text) if b == -1 else b
    snippet = " ⏎ ".join(ln.strip() for ln in text[a:b].split("\n") if ln.strip())
    if len(snippet) > 220:
        snippet = snippet[:217] + "..."
    return Evidence(page=page, start=start, end=end, snippet=snippet, label=label, method=method)


def _warning(note: Note, field_name: str) -> WarningItem:
    code, message, severity = note
    return WarningItem(code=code, message=message, field=field_name, severity=severity)


def package_field(
    name: str,
    candidates: list[Candidate],
    page_text: dict[int, str],
    settings: Settings,
) -> FieldResult:
    if not candidates:
        return FieldResult(
            name=name,
            status=FieldStatus.MISSING,
            warnings=[
                WarningItem(
                    code="FIELD_NOT_FOUND",
                    message=f"No evidence for '{name}' was found in the document; value left null.",
                    field=name,
                    severity=Severity.INFO,
                )
            ],
        )

    def order(c: Candidate):
        return (c.value is None, c.role, -c.score, c.page, c.start)

    ranked = sorted(candidates, key=order)
    best = ranked[0]
    # Evidence from a label that says "this is ambiguous" (range, several dates, ...) outranks a
    # weaker inline guess at one of the values: picking one silently would be a wrong answer.
    flagged = [
        c
        for c in ranked
        if c.value is None
        and c.method.startswith("label")
        and any(n[0] in AMBIGUITY_CODES for n in c.notes)
    ]
    if best.value is not None and best.method in ("inline_pattern", "spacy_ner") and flagged:
        best = flagged[0]
    same = [c for c in ranked[1:] if c.value is not None and c.key == best.key]
    others = [
        c
        for c in ranked[1:]
        if c.value is not None
        and c.key != best.key
        and c.role == best.role
        and c.score >= best.score - 0.15
    ]
    score = min(0.99, best.score + (0.05 if same and best.value is not None else 0.0))

    evidences: list[Evidence] = []
    seen: set[tuple[int, int, int]] = set()
    for c in [best, *same]:
        span = (c.page, c.start, c.end)
        if span in seen or len(evidences) >= 3:
            continue
        seen.add(span)
        evidences.append(
            make_evidence(page_text[c.page], c.page, c.start, c.end, c.label, c.method, c.ctx_start)
        )

    warnings = [_warning(n, name) for n in best.notes]
    status = FieldStatus(best.status)
    if best.value is not None and status in (FieldStatus.EXTRACTED, FieldStatus.NORMALIZED):
        if others:
            alts = "; ".join(f"'{c.raw}'" for c in others[:3])
            warnings.append(
                WarningItem(
                    code="CONFLICTING_VALUES",
                    message=f"Other plausible values were found ({alts}); please verify.",
                    field=name,
                    severity=Severity.WARNING,
                )
            )
            status = FieldStatus.NEEDS_REVIEW
        elif score < settings.review_threshold:
            warnings.append(
                WarningItem(
                    code="LOW_HEURISTIC_SCORE",
                    message=f"Weak evidence (heuristic score {score:.2f}); please verify.",
                    field=name,
                    severity=Severity.WARNING,
                )
            )
            status = FieldStatus.NEEDS_REVIEW
    if name == "counterparty":
        roles = {c.label for c in ranked if c.role != best.role and c.value is not None}
        if roles:
            warnings.append(
                WarningItem(
                    code="OTHER_PARTIES_FOUND",
                    message="Other parties were also found ("
                    + ", ".join(sorted(x or "?" for x in roles))
                    + "); the highest-priority role (charterer > shipper > consignee > buyer) was used.",
                    field=name,
                    severity=Severity.INFO,
                )
            )
    return FieldResult(
        name=name,
        value=best.value,
        raw_value=best.raw,
        status=status,
        heuristic_score=round(score, 3),
        evidence=evidences,
        warnings=warnings,
    )


def package_fields(
    candidates: list[Candidate], pages: dict[int, str], settings: Settings
) -> dict[str, FieldResult]:
    grouped: dict[str, list[Candidate]] = {n: [] for n in FIELD_NAMES}
    for c in candidates:
        grouped[c.field].append(c)
    return {n: package_field(n, grouped[n], pages, settings) for n in FIELD_NAMES}
