"""Inline (prose) patterns: sentences such as 'M/V X will lift ... at Y'."""

from __future__ import annotations

import re

from app.evidence import Candidate
from app.extractors.rules.common import S_INLINE, same_text
from app.extractors.rules.labels import ROLE_NAMES
from app.extractors.rules.values import cargo_type_candidate, date_candidate, quantity_candidates
from app.gazetteer import lookup_port
from app.normalizers import (
    clean_party,
    clean_reference,
    clean_vessel,
    find_dates,
    find_quantity,
)
from app.schemas import PageText

# ---------------------------------------------------------------------------
# Inline (prose) patterns
# ---------------------------------------------------------------------------
# Separator between words of a name: spaces, or one line wrap (but never into a "Label:" line)
_SP = r"(?:[ ]+|[ ]*\n[ ]*(?![A-Za-z ]{1,30}:)(?![^\n]*[ ]{3}))"
_LEGAL_WORD = r"(?:Ltd|Limited|Inc|LLC|GmbH|Pte|Co|Corp|PLC|B\.V|S\.A|Pvt|LLP|AG|BV|SA)"
_CAP = r"[A-Z][A-Za-z.\'\-]*"
_PORT_PHRASE = rf"{_CAP}(?:{_SP}{_CAP}){{0,2}}"
_VESSEL_INLINE = re.compile(
    r"(?<![\w/])(?i:m/v|m\.v\.|mv|m/t)[ ]+"
    r"(?P<name>[A-Z][A-Za-z0-9'\-]*(?:[ ]+(?!(?:Is|Has|Was|Will|To|At|And|For|On|In|Of|Arrived|Loading|"
    r"IS|HAS|WAS|WILL|TO|AT|AND|FOR|ON|IN|OF|ARRIVED|LOADING)\b)[A-Z0-9][A-Za-z0-9'\-]*){0,3})"
)
_VESSEL_BARE = re.compile(
    r"(?:advised|note|notify|confirm|inform)\s+that\s+(?:the\s+(?:vessel|m/v)\s+)?"
    r"(?P<name>(?!V\.\d)[A-Z][A-Za-z0-9'\-]*(?:[ ]+(?!V\.\d)[A-Z0-9][A-Za-z0-9'\-]*){0,3})"
    r"(?:[ ]+V\.\d+[A-Z]?)?\s+(?:has|have|will|is|are|arrived)\b"
)
_LOAD_AT = re.compile(
    rf"(?i:(?:load(?:ing|ed)?|lift(?:ing|ed)?|shipp(?:ed|ing))\s+(?:(?:port|place)\s+)?(?:at|in|from|ex))\s+(?P<p>{_PORT_PHRASE})"
)
_DISCH_AT = re.compile(
    rf"(?i:(?:discharg(?:e|ing|ed)|deliver(?:y|ed|ing)|unload(?:ing|ed))\s+(?:(?:port|place)\s+)?(?:at|in|to))\s+(?P<p>{_PORT_PHRASE})"
)
_LIFT_AT = re.compile(
    rf"(?i:\b(?:lift|load)(?:ing|ed)?\b)(?:[^.;:]|(?<=\d)\.(?=\d)){{0,80}}?\s(?i:at|from|ex)\s+(?P<p>{_PORT_PHRASE})"
)
_REF_INLINE = re.compile(
    r"(?i:\b(?:(?:our|fixture|charter[ ]+party|shipment)[ ]+)?ref(?:erence)?"
    r"(?:[ ]+(?:no\.?|number|is))?(?:[ ]*[:#][ ]*|[ ]*\n[ ]*|[ ]+)(?:is[ ]+)?)"
    r"(?P<r>[A-Za-z0-9][A-Za-z0-9\-/_.]{3,29})"
)
_FROM_TO = re.compile(rf"(?i:\bfrom)\s+(?P<a>{_PORT_PHRASE})\s+(?i:to)\s+(?P<b>{_PORT_PHRASE})")
_PARTY_INLINE = re.compile(
    r"(?i:chartered\s+(?:by|to)|charterers?\s+(?:are|is)|shipper\s+is|consignee\s+is)\s*:?\s*"
    r"(?P<n>(?:[A-Z](?:\.[A-Z])+\.?|[A-Z][\w&'\-]*\.?)"
    r"(?:[ ]+(?:(?:&|and|of|de|van|von)(?=[ ]+[A-Z])|[A-Z](?:\.[A-Z])+\.?|[A-Z][\w&'\-]*\.?)"
    rf"|[ ]*\n[ ]*(?={_LEGAL_WORD}\b)(?:[A-Z](?:\.[A-Z])+\.?|[A-Z][\w&'\-]*\.?))*)"
)
_WS = r"(?:[ ]+|[ ]*\n[ ]*)"  # spaces or ONE line wrap; both branches start differently => linear
_CARGO_INLINE = re.compile(
    r"(?i:cargo|shipment|consignment|carrying|carries|lift(?:ing)?|load(?:ing|ed)?|laden[ ]+with|quantity)"
    rf"(?:[ ]*:[ ]*|{_WS}(?i:of{_WS})?)?"
    rf"(?:(?i:approx\.?|about|abt\.?|circa|up[ ]+to){_WS})?"
    r"(?P<q>\d[\d.,  ]*\d|\d)[ ]*(?P<u>[A-Za-z/³0-9]+(?:[ ]+(?i:tonnes?|tons|metres|meters))?)"
    rf"{_SP}(?i:of{_SP})?(?P<c>[A-Za-z][A-Za-z\-]*(?:{_SP}[A-Za-z][A-Za-z\-]*){{0,3}}?)"
    r"(?=[ ]*(?:[,.;:]|$)|[ ]*\n(?:[ ]*\n|[A-Za-z ]{1,30}:|[^\n]*[ ]{3})"
    r"|\s+(?i:to|from|at|in|on|for|loaded|shipped|laden|ex|by|under|via|with|and)\b)"
)
_LOAD_KW = re.compile(r"(?i)\b(?:load(?:ing|ed)?|shipped\s+on\s+board|lift(?:ing|ed)?)\b")
_DISCH_KW = re.compile(r"(?i)\b(?:discharg\w*|deliver\w*|unload\w*)\b")
_DATE_BLOCK = re.compile(
    r"(?i)\b(?:invoice|issue[d]?|payment|due|expir\w*|valid\w*|signed|printed)\b"
)


def _port_phrase_hit(phrase: str) -> tuple[str, str] | None:
    toks = phrase.split()
    for n in range(len(toks), 0, -1):
        hit = lookup_port(" ".join(toks[:n]), fuzzy=False)
        if hit:
            return hit
    return None


def inline_candidates(page: PageText) -> list[Candidate]:
    text, pg = page.text, page.page
    out: list[Candidate] = []

    for m in _VESSEL_INLINE.finditer(text):
        v = clean_vessel(m["name"])
        if v:
            out.append(
                Candidate(
                    "vessel_name",
                    v,
                    m["name"],
                    pg,
                    m.start("name"),
                    m.end("name"),
                    "inline_pattern",
                    S_INLINE,
                    "M/V",
                    "extracted" if same_text(m["name"], v) else "normalized",
                )
            )

    for m in _VESSEL_BARE.finditer(text):
        name = m["name"]
        v = clean_vessel(name)
        if v and (name.isupper() or len(name.split()) >= 2):
            out.append(
                Candidate(
                    "vessel_name",
                    v,
                    name,
                    pg,
                    m.start("name"),
                    m.end("name"),
                    "inline_pattern",
                    S_INLINE - 0.05,
                    "advised that",
                    "extracted" if same_text(name, v) else "normalized",
                )
            )

    def port(field: str, grp: str, m: re.Match) -> None:
        hit = _port_phrase_hit(m[grp])
        if hit:
            raw = m[grp]
            out.append(
                Candidate(
                    field,
                    hit[0],
                    raw,
                    pg,
                    m.start(grp),
                    m.end(grp),
                    "inline_pattern",
                    S_INLINE + 0.05,
                    None,
                    "extracted" if same_text(raw, hit[0]) else "normalized",
                )
            )

    for m in _LOAD_AT.finditer(text):
        port("origin_port", "p", m)
    for m in _LIFT_AT.finditer(text):
        port("origin_port", "p", m)
    for m in _DISCH_AT.finditer(text):
        port("destination_port", "p", m)
    for m in _REF_INLINE.finditer(text):
        ref = clean_reference(m["r"])
        if ref:
            out.append(
                Candidate(
                    "document_reference",
                    ref,
                    m["r"],
                    pg,
                    m.start("r"),
                    m.end("r"),
                    "inline_pattern",
                    S_INLINE,
                    "ref",
                    "extracted",
                )
            )
    for m in _FROM_TO.finditer(text):
        a, b = _port_phrase_hit(m["a"]), _port_phrase_hit(m["b"])
        if a and b:
            port("origin_port", "a", m)
            port("destination_port", "b", m)

    for m in _PARTY_INLINE.finditer(text):
        v = clean_party(m["n"])
        if v:
            role = (
                1 if re.match(r"(?i)charter", m[0]) else 2 if re.match(r"(?i)shipper", m[0]) else 3
            )
            out.append(
                Candidate(
                    "counterparty",
                    v,
                    m["n"],
                    pg,
                    m.start("n"),
                    m.end("n"),
                    "inline_pattern",
                    S_INLINE,
                    ROLE_NAMES[role],
                    "extracted",
                    role=role,
                )
            )

    for m in _CARGO_INLINE.finditer(text):
        q = find_quantity(text[m.start("q") : m.end("u")])
        if q and q.unit:
            out += quantity_candidates(q, pg, m.start("q"), "inline_pattern", S_INLINE, None, None)
            c = cargo_type_candidate(
                m["c"], pg, m.start("c"), m.end("c"), "inline_pattern", S_INLINE, None, None
            )
            if c:
                out.append(c)

    for d in find_dates(text):
        ctx_start = max(0, d.span[0] - 70)
        ctx = text[ctx_start : d.span[0]]
        loads = [x for x in _LOAD_KW.finditer(ctx)]
        dis = [x for x in _DISCH_KW.finditer(ctx)]
        pick = None
        if loads and (not dis or loads[-1].end() > dis[-1].end()):
            pick = ("loading_date", ctx[loads[-1].end() :])
        elif dis:
            pick = ("discharge_date", ctx[dis[-1].end() :])
        if not pick:
            continue
        between = pick[1]
        if _DATE_BLOCK.search(between) or re.search(r"[.;]", between):
            continue
        if "\n" in between and (":" in between or "\n\n" in between):
            continue  # crosses into a 'Label: value' line or a new paragraph

        c = date_candidate(
            pick[0], d.raw, pg, d.span[0], d.span[1], "inline_pattern", S_INLINE, None, None
        )
        if c:
            out.append(c)
    return out
