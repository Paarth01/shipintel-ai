"""Label dictionaries and the label scanner ('Label: value', aligned, pipe, next-line)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.deadline import Deadline, FuzzyBudget
from app.extractors.rules.common import S_LABEL
from app.normalizers import (
    normalize_unit,
)


# ---------------------------------------------------------------------------
# Label dictionaries
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Alias:
    kind: str  # vessel | origin | destination | cargo | quantity | unit | load_date |
    #            discharge_date | reference | party
    base: float = S_LABEL
    role: int = 0
    require_gazetteer: bool = False


def _norm_label(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", s.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s.replace(".", ""))
    return " ".join(s.split())


_ALIAS_SOURCE: list[tuple[Alias, list[str]]] = [
    (
        Alias("vessel"),
        [
            "vessel",
            "vessel name",
            "name of vessel",
            "ship",
            "ship name",
            "name of ship",
            "m/v",
            "mv",
            "motor vessel",
            "carrying vessel",
            "ocean vessel",
            "vsl",
        ],
    ),
    (
        Alias("origin"),
        [
            "port of loading",
            "loading port",
            "load port",
            "loadport",
            "pol",
            "port of origin",
            "origin port",
            "port of lading",
            "place of loading",
            "port of shipment",
            "port of departure",
            "departure port",
        ],
    ),
    (Alias("origin", 0.80), ["origin"]),
    (Alias("origin", 0.80, 0, True), ["from"]),
    (
        Alias("destination"),
        [
            "port of discharge",
            "discharge port",
            "discharging port",
            "discharge port",
            "pod",
            "port of destination",
            "destination port",
            "port of delivery",
            "port of unloading",
            "unloading port",
        ],
    ),
    (Alias("destination", 0.80), ["destination"]),
    (Alias("destination", 0.80, 0, True), ["to"]),
    (
        Alias("cargo"),
        [
            "cargo",
            "commodity",
            "description of goods",
            "goods",
            "cargo description",
            "nature of cargo",
            "description of cargo",
            "product",
            "type of cargo",
            "goods description",
        ],
    ),
    (
        Alias("quantity"),
        ["quantity", "qty", "cargo quantity", "total quantity", "cargo qty", "quantity of cargo"],
    ),
    (Alias("quantity", 0.65), ["weight", "gross weight", "net weight", "volume"]),
    (Alias("unit"), ["unit", "uom", "unit of measure"]),
    (
        Alias("load_date"),
        [
            "loading date",
            "date of loading",
            "load date",
            "loaded on",
            "shipped on board",
            "shipped on board date",
            "on board date",
            "date of shipment",
            "shipment date",
            "commenced loading",
            "loading commenced",
            "date loaded",
        ],
    ),
    (
        Alias("discharge_date"),
        [
            "discharge date",
            "date of discharge",
            "discharging date",
            "date discharged",
            "commenced discharge",
            "discharge commenced",
            "discharged on",
            "delivery date",
            "date of delivery",
            "delivered on",
            "date delivered",
        ],
    ),
    (
        Alias("reference"),
        [
            "b/l no",
            "bl no",
            "bl number",
            "b/l number",
            "b/l",
            "bill of lading no",
            "bill of lading number",
            "reference",
            "ref",
            "ref no",
            "reference no",
            "reference number",
            "our ref",
            "fixture ref",
            "fixture reference",
            "charter party ref",
            "cp ref",
            "charter party reference",
            "manifest no",
            "manifest number",
            "document no",
            "document number",
            "doc no",
            "document ref",
            "shipment ref",
            "shipment no",
        ],
    ),
    (Alias("party", 0.90, 1), ["charterer", "charterers", "chartered by"]),
    (Alias("party", 0.88, 2), ["shipper", "shipper name", "exporter"]),
    (Alias("party", 0.85, 3), ["consignee", "consignee name", "importer"]),
    (Alias("party", 0.80, 4), ["buyer", "receiver"]),
]
ALIASES: dict[str, Alias] = {}
for _alias, _names in _ALIAS_SOURCE:
    for _n in _names:
        ALIASES[_norm_label(_n)] = _alias
_FUZZY_KEYS = [k for k in ALIASES if len(k) >= 7]

ROLE_NAMES = {1: "charterer", 2: "shipper", 3: "consignee", 4: "buyer"}


_FUZZY_CACHE: dict[str, str | None] = {}


def resolve_label(
    raw: str, allow_fuzzy: bool, budget: FuzzyBudget | None = None
) -> tuple[Alias | None, str, str | None]:
    """Return (alias, how, unit_hint). how in {'exact','fuzzy',''}."""
    unit_hint = None
    m = re.search(r"\(([^)]*)\)", raw)
    if m:
        unit_hint, _ = normalize_unit(m.group(1))
    key = _norm_label(raw)
    if key in ALIASES:
        return ALIASES[key], "exact", unit_hint
    if allow_fuzzy and len(key) >= 7:
        if key in _FUZZY_CACHE:  # repeated spellings cost nothing
            hit = _FUZZY_CACHE[key]
        elif budget is not None and not budget.take():
            hit = None  # per-document work budget exhausted: skip fuzzy matching
        else:
            found = difflib.get_close_matches(key, _FUZZY_KEYS, n=1, cutoff=0.85)
            hit = found[0] if found else None
            if len(_FUZZY_CACHE) > 8192:
                _FUZZY_CACHE.clear()
            _FUZZY_CACHE[key] = hit
        if hit:
            return ALIASES[hit], "fuzzy", unit_hint
    return None, "", unit_hint


# ---------------------------------------------------------------------------
# Label scan
# ---------------------------------------------------------------------------
_COLON = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 /&.\-()#]{1,44}?)\s*[:=]\s*(?P<value>.*)$")
_SPLIT = re.compile(r"\s*\|\s*|\s{3,}")


@dataclass
class KV:
    label: str
    alias: Alias
    how: str
    unit_hint: str | None
    start: int
    end: int
    method: str
    ctx_start: int


def _lines(text: str) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for ln in text.split("\n"):
        out.append((pos, pos + len(ln), ln))
        pos += len(ln) + 1
    return out


def _segments(line: str, base: int) -> list[tuple[int, int, str]]:
    segs, last = [], 0
    for m in _SPLIT.finditer(line):
        if m.start() > last:
            segs.append((base + last, base + m.start(), line[last : m.start()]))
        last = m.end()
    if last < len(line):
        segs.append((base + last, base + len(line), line[last:]))
    return segs


def _segment_is_label(seg: str) -> bool:
    m = _COLON.match(seg)
    if m and resolve_label(m["label"], False)[0]:
        return True
    return resolve_label(seg, False)[0] is not None


def _next_line_value(lines, idx) -> tuple[int, int] | None:
    for j in range(idx + 1, min(idx + 3, len(lines))):
        s, e, ln = lines[j]
        if not ln.strip():
            continue
        if len(ln.strip()) > 70 or any(_segment_is_label(x[2]) for x in _segments(ln, s)):
            return None
        lead = len(ln) - len(ln.lstrip())
        return s + lead, e
    return None


_LIST_MARKER = re.compile(
    r"^[ ]*(?:\(?\d{1,2}[.)]|\(?[A-Za-z][.)]|[-\u2022*\u2013])[ ]+(?=[A-Za-z])"
)


def scan_labels(
    text: str, budget: FuzzyBudget | None = None, deadline: Deadline | None = None
) -> list[KV]:
    lines = [(s, e, _LIST_MARKER.sub(lambda m: " " * len(m[0]), ln)) for s, e, ln in _lines(text)]
    out: list[KV] = []
    for i, (ls, _le, line) in enumerate(lines):
        if deadline is not None and i % 256 == 0:
            deadline.check()
        lead = len(line) - len(line.lstrip())
        segs = _segments(line.lstrip(), ls + lead)
        j = 0
        while j < len(segs):
            s, e, seg = segs[j]
            m = _COLON.match(seg)
            if m:
                alias, how, hint = resolve_label(m["label"], True, budget)
                if alias:
                    vs, ve = s + m.start("value"), s + m.end("value")
                    if m["value"].strip():
                        out.append(KV(m["label"], alias, how, hint, vs, ve, "label", s))
                    else:
                        nl = _next_line_value(lines, i)
                        if nl:
                            out.append(KV(m["label"], alias, how, hint, nl[0], nl[1], "next", s))
                    j += 1
                    continue
            alias, how, hint = resolve_label(
                seg, len(segs) == 2 and j == 0 and len(seg.split()) <= 4
            )
            if alias:
                if j + 1 < len(segs) and not _segment_is_label(segs[j + 1][2]):
                    out.append(
                        KV(seg, alias, how, hint, segs[j + 1][0], segs[j + 1][1], "label", s)
                    )
                    j += 2
                    continue
                nl = _next_line_value(lines, i) if j == len(segs) - 1 else None
                if nl:
                    out.append(KV(seg, alias, how, hint, nl[0], nl[1], "next", s))
            j += 1
    return out
