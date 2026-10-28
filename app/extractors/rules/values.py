"""Turn a matched label + value into typed, normalised candidates."""

from __future__ import annotations

import re

from app.evidence import Candidate, Note
from app.extractors.rules.common import FUZZY_PENALTY, S_NEXT, same_text
from app.extractors.rules.labels import KV, ROLE_NAMES
from app.gazetteer import CARGO_TERMS, find_locode_in_text, lookup_port
from app.normalizers import (
    DateParse,
    clean_cargo_type,
    clean_party,
    clean_reference,
    clean_vessel,
    collapse_ws,
    find_bare_quantity,
    find_dates,
    find_quantity,
    is_placeholder,
    normalize_unit,
    smart_title,
)
from app.schemas import PageText, Severity

# ---------------------------------------------------------------------------
# Value -> candidates
# ---------------------------------------------------------------------------
_PORT_PREFIX = re.compile(r"^(?:the\s+)?(?:port|place)\s+of\s+|^port\s*[:\-]\s*", re.I)
_PORT_SUFFIX = re.compile(  # input is whitespace-collapsed, so single spaces keep this linear
    r"[ ](?:outer[ ])?(?:anchorage|roads|port|terminal|berth[ ]?\d*|harbou?r)$", re.I
)


def resolve_port(value: str) -> tuple[str | None, str, str]:
    """Return (canonical_or_cleaned, how, cleaned_raw). how: exact|locode|fuzzy|none."""
    raw = collapse_ws(value)
    locode = find_locode_in_text(raw)
    stripped = re.sub(r"\([^)]*\)", " ", raw)
    first = re.split(r"\s*[,/;]\s*|\s+-\s+", stripped, maxsplit=1)[0]
    first = first.strip()
    with_prefix = collapse_ws(_PORT_SUFFIX.sub("", first)).strip(" .:;-")
    cleaned = collapse_ws(_PORT_SUFFIX.sub("", _PORT_PREFIX.sub("", first))).strip(" .:;-")
    if len(with_prefix) > 60:  # never run fuzzy matching on long text
        return None, "none", with_prefix[:60]
    attempts = dict.fromkeys(
        (with_prefix, cleaned, " ".join(cleaned.split()[:2]), " ".join(cleaned.split()[:1]))
    )
    for attempt in attempts:
        if attempt:
            hit = lookup_port(attempt)
            if hit:
                return hit[0], hit[1], cleaned
    if locode:
        hit = lookup_port(locode)
        if hit:
            return hit[0], "locode", cleaned
    if len(cleaned) < 3 or len(cleaned) > 40 or not re.search(r"[A-Za-z]{3}", cleaned):
        return None, "none", cleaned
    return smart_title(cleaned), "none", cleaned


def _placeholder_candidate(
    field: str,
    raw: str,
    page: int,
    s: int,
    e: int,
    kv_method: str,
    score: float,
    label: str,
    ctx: int,
) -> Candidate:
    return Candidate(
        field,
        None,
        raw,
        page,
        s,
        e,
        kv_method,
        score * 0.6,
        label,
        "needs_review",
        [
            (
                "PLACEHOLDER_VALUE",
                f"'{raw.strip()}' is a placeholder, not a value.",
                Severity.WARNING,
            )
        ],
        ctx_start=ctx,
    )


def _unparseable(
    field: str, raw: str, page: int, s: int, e: int, method: str, score: float, label: str, ctx: int
) -> Candidate:
    return Candidate(
        field,
        None,
        raw,
        page,
        s,
        e,
        method,
        score * 0.5,
        label,
        "needs_review",
        [
            (
                "UNPARSEABLE_VALUE",
                f"Could not interpret '{raw.strip()[:60]}' for '{field}'.",
                Severity.WARNING,
            )
        ],
        ctx_start=ctx,
    )


def date_candidate(
    field: str,
    text: str,
    page: int,
    s: int,
    e: int,
    method: str,
    score: float,
    label: str | None,
    ctx: int | None,
) -> Candidate | None:
    dates = find_dates(text)
    if len({d.value for d in dates if d.status == "ok"}) == 1 and all(
        d.status == "ok" for d in dates
    ):
        dates = dates[:1]  # the same date written twice is still one date
    if len(dates) > 1 or (dates and dates[0].status == "range"):
        first, last = dates[0], dates[-1]
        a, b = first.span[0], last.span[1]
        raw = text[a:b]
        is_range = any(d.status == "range" for d in dates)
        code = "DATE_RANGE" if is_range else "MULTIPLE_DATES"
        msg = (
            f"'{raw.strip()[:60]}' is a date range; no single date was chosen."
            if is_range
            else f"Several different dates were found ('{raw.strip()[:60]}'); no single date was chosen."
        )
        return Candidate(
            field,
            None,
            raw,
            page,
            s + a,
            s + b,
            method,
            score * 0.6,
            label,
            "needs_review",
            [(code, msg, Severity.WARNING)],
            ctx_start=ctx,
        )
    d = dates[0] if dates else DateParse("none")
    if d.status == "none":
        if is_placeholder(text):
            return _placeholder_candidate(
                field, text, page, s, e, method, score, label or "", ctx or s
            )
        return _unparseable(field, text, page, s, e, method, score, label or "", ctx or s)
    ds, de = s + d.span[0], s + d.span[1]
    if d.status == "ok" and d.value is not None:
        return Candidate(
            field,
            d.value.isoformat(),
            d.raw,
            page,
            ds,
            de,
            method,
            score,
            label,
            "normalized",
            ctx_start=ctx,
        )
    code, sev, status = (
        ("AMBIGUOUS_DATE", Severity.WARNING, "needs_review")
        if d.status == "ambiguous"
        else ("INVALID_DATE", Severity.ERROR, "invalid")
    )
    return Candidate(
        field,
        None,
        d.raw,
        page,
        ds,
        de,
        method,
        score * 0.6,
        label,
        status,
        [(code, d.message, sev)],
        ctx_start=ctx,
    )


def _port_candidate(
    field: str,
    text: str,
    page: int,
    s: int,
    e: int,
    method: str,
    score: float,
    label: str | None,
    ctx: int | None,
    require_gz: bool,
) -> Candidate | None:
    if is_placeholder(text):
        return _placeholder_candidate(field, text, page, s, e, method, score, label or "", ctx or s)
    value, how, cleaned = resolve_port(text)
    if value is None:
        return (
            None
            if require_gz
            else _unparseable(field, text, page, s, e, method, score, label or "", ctx or s)
        )
    notes: list[Note] = []
    if how in ("exact", "locode"):
        score += 0.05
    elif how == "fuzzy":
        notes.append(
            (
                "PORT_FUZZY_MATCH",
                f"'{cleaned}' was matched to known port '{value}' despite a spelling difference.",
                Severity.INFO,
            )
        )
    else:
        if require_gz or method == "inline_pattern":
            return None
        score -= 0.25
        notes.append(
            (
                "UNRECOGNIZED_PORT",
                f"'{value}' is not in the built-in port list; verify the port name.",
                Severity.WARNING,
            )
        )
    status = "extracted" if same_text(text, value) else "normalized"
    return Candidate(
        field, value, text.strip(), page, s, e, method, score, label, status, notes, ctx_start=ctx
    )


def quantity_candidates(
    q,
    page: int,
    base: int,
    method: str,
    score: float,
    label: str | None,
    ctx: int | None,
    unit_hint: str | None = None,
) -> list[Candidate]:
    out: list[Candidate] = []
    s, e = base + q.span[0], base + q.span[1]
    notes = [(c, m, Severity.WARNING) for c, m in q.notes if c.startswith("QUANTITY")]
    unit_notes = [(c, m, Severity.WARNING) for c, m in q.notes if not c.startswith("QUANTITY")]
    if q.ambiguous or q.value is None:
        out.append(
            Candidate(
                "cargo_quantity",
                None,
                q.raw,
                page,
                s,
                e,
                method,
                score * 0.6,
                label,
                "needs_review",
                notes,
                ctx_start=ctx,
            )
        )
    else:
        out.append(
            Candidate(
                "cargo_quantity",
                q.value,
                q.raw,
                page,
                s,
                e,
                method,
                score,
                label,
                "normalized",
                notes,
                ctx_start=ctx,
            )
        )
    unit = q.unit or unit_hint
    if unit:
        raw_unit = q.unit_raw or unit
        out.append(
            Candidate(
                "cargo_unit",
                unit,
                raw_unit,
                page,
                s,
                e,
                method,
                score,
                label,
                "extracted" if raw_unit == unit else "normalized",
                [] if not q.unit_raw else unit_notes,
                ctx_start=ctx,
            )
        )
    elif q.unit_raw:
        out.append(
            Candidate(
                "cargo_unit",
                None,
                q.unit_raw,
                page,
                s,
                e,
                method,
                score * 0.5,
                label,
                "needs_review",
                unit_notes,
                ctx_start=ctx,
            )
        )
    return out


def cargo_type_candidate(
    text: str,
    page: int,
    s: int,
    e: int,
    method: str,
    score: float,
    label: str | None,
    ctx: int | None,
    raw: str | None = None,
) -> Candidate | None:
    value = clean_cargo_type(text)
    if value is None:
        return None
    if value.casefold() in CARGO_TERMS:
        score = min(0.99, score + 0.03)
    return Candidate(
        "cargo_type",
        value,
        (raw if raw is not None else text).strip(),
        page,
        s,
        e,
        method,
        score,
        label,
        "extracted" if same_text(text, value) else "normalized",
        ctx_start=ctx,
    )


def candidates_from_kv(page: PageText, kv: KV) -> list[Candidate]:
    text = page.text
    raw = text[kv.start : kv.end]
    if not raw.strip():
        return []
    a, kind = kv.alias, kv.alias.kind
    base = S_NEXT if kv.method == "next" else a.base
    method = "label_next_line" if kv.method == "next" else "label_match"
    if kv.how == "fuzzy":
        base -= FUZZY_PENALTY
        method = "label_fuzzy"
    fuzzy_note: list[Note] = (
        [
            (
                "LABEL_FUZZY_MATCH",
                f"Label '{kv.label.strip()}' was matched approximately.",
                Severity.INFO,
            )
        ]
        if kv.how == "fuzzy"
        else []
    )
    pg, s, e, lab, ctx = page.page, kv.start, kv.end, kv.label.strip(), kv.ctx_start
    out: list[Candidate] = []

    if kind == "vessel":
        if is_placeholder(raw):
            return [_placeholder_candidate("vessel_name", raw, pg, s, e, method, base, lab, ctx)]
        v = clean_vessel(raw)
        c = (
            Candidate(
                "vessel_name",
                v,
                raw.strip(),
                pg,
                s,
                e,
                method,
                base,
                lab,
                "extracted" if v and same_text(raw, v) else "normalized",
                ctx_start=ctx,
            )
            if v
            else _unparseable("vessel_name", raw, pg, s, e, method, base, lab, ctx)
        )
        out.append(c)
    elif kind in ("origin", "destination"):
        field = "origin_port" if kind == "origin" else "destination_port"
        port_c = _port_candidate(field, raw, pg, s, e, method, base, lab, ctx, a.require_gazetteer)
        if port_c:
            out.append(port_c)
    elif kind in ("load_date", "discharge_date"):
        field = "loading_date" if kind == "load_date" else "discharge_date"
        date_c = date_candidate(field, raw, pg, s, e, method, base, lab, ctx)
        if date_c:
            out.append(date_c)
    elif kind == "cargo":
        if is_placeholder(raw):
            return [_placeholder_candidate("cargo_type", raw, pg, s, e, method, base, lab, ctx)]
        q = find_quantity(raw)
        rest = raw
        if q:
            out += quantity_candidates(q, pg, s, method, base, lab, ctx)
            rest = raw[: q.span[0]] + " " + raw[q.span[1] :]
        cargo_c = cargo_type_candidate(rest, pg, s, e, method, base, lab, ctx, raw=raw)
        if cargo_c:
            out.append(cargo_c)
        elif not q:
            out.append(_unparseable("cargo_type", raw, pg, s, e, method, base, lab, ctx))
    elif kind == "quantity":
        q = find_quantity(raw) or find_bare_quantity(raw)
        if q:
            out += quantity_candidates(q, pg, s, method, base, lab, ctx, kv.unit_hint)
        elif is_placeholder(raw):
            out.append(
                _placeholder_candidate("cargo_quantity", raw, pg, s, e, method, base, lab, ctx)
            )
    elif kind == "unit":
        unit, notes = normalize_unit(raw.strip())
        if unit:
            out.append(
                Candidate(
                    "cargo_unit",
                    unit,
                    raw.strip(),
                    pg,
                    s,
                    e,
                    method,
                    base,
                    lab,
                    "extracted" if raw.strip() == unit else "normalized",
                    [(c, m, Severity.WARNING) for c, m in notes],
                    ctx_start=ctx,
                )
            )
    elif kind == "reference":
        if is_placeholder(raw):
            return [
                _placeholder_candidate("document_reference", raw, pg, s, e, method, base, lab, ctx)
            ]
        v = clean_reference(raw)
        out.append(
            Candidate(
                "document_reference",
                v,
                raw.strip(),
                pg,
                s,
                e,
                method,
                base,
                lab,
                "extracted" if v and same_text(raw, v) else "normalized",
                ctx_start=ctx,
            )
            if v
            else _unparseable("document_reference", raw, pg, s, e, method, base, lab, ctx)
        )
    elif kind == "party":
        if is_placeholder(raw):
            return [_placeholder_candidate("counterparty", raw, pg, s, e, method, base, lab, ctx)]
        v = clean_party(raw)
        if v:
            c = Candidate(
                "counterparty",
                v,
                raw.strip(),
                pg,
                s,
                e,
                method,
                base,
                ROLE_NAMES[a.role],
                "extracted" if same_text(raw, v) else "normalized",
                role=a.role,
                ctx_start=ctx,
            )
            out.append(c)
        else:
            c = _unparseable("counterparty", raw, pg, s, e, method, base, lab, ctx)
            c.role = a.role
            out.append(c)
    for c in out:
        c.notes = fuzzy_note + c.notes
    return out
