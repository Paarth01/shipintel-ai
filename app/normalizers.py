"""Value normalisation: dates, quantities, units, and light string cleaning.

Documented assumptions
- Text-month dates (12 March 2025, Mar 12 2025, 12-Mar-2025) and ISO dates are unambiguous.
- Dotted numeric dates (12.03.2025) are read day-first (DMY), the usual convention for them.
- Slash/dash numeric dates (03/04/2025) where both parts are <= 12 are AMBIGUOUS -> value None.
- Two-digit years are not interpreted.
- 'tons' (short/long) is ambiguous -> mapped to MT but flagged for review.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import date

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
MONTH_ALT = _MON

_RE_ISO = re.compile(r"(?<!\d)(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?!\d)")
_RE_DMY_TEXT = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s\-/.,]*({_MON})[a-z]*\.?[\s\-/.,]*(\d{{4}})(?!\d)",
    re.I,
)
_RE_MDY_TEXT = re.compile(
    rf"(?<![a-z])({_MON})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I
)
_RE_NUM = re.compile(r"(?<!\d)(\d{1,2})([/\-.])(\d{1,2})\2(\d{4})(?!\d)")

YEAR_MIN, YEAR_MAX = 1990, 2100

# '12-15 March 2025' / '10 March to 15 March 2025': the partial first date sits just before a full one
_RANGE_PREFIX = re.compile(
    rf"(?i)(?:\d{{1,2}}(?:st|nd|rd|th)?(?:[ ]+(?:{_MON})[a-z]*\.?)?[ ]*(?:-|\u2013|\u2014|\bto\b|\buntil\b)[ ]*)$"
)
# connector between two complete dates: '2025-03-10 to 2025-03-15'
_RANGE_CONN = re.compile(r"(?i)^\s*(?:-|\u2013|\u2014|\bto\b|\buntil\b|\bthrough\b|\bthru\b)\s*$")


@dataclass
class DateParse:
    status: str  # ok | ambiguous | invalid | range | none
    value: date | None = None
    span: tuple[int, int] = (0, 0)
    raw: str = ""
    message: str = ""
    normalized: bool = True  # a date text is always transformed to ISO


def _build(y: int, m: int, d: int, span: tuple[int, int], raw: str) -> DateParse:
    try:
        value = date(y, m, d)
    except ValueError:
        return DateParse("invalid", None, span, raw, f"'{raw}' is not a real calendar date.")
    if not YEAR_MIN <= y <= YEAR_MAX:
        return DateParse("invalid", None, span, raw, f"Year {y} is outside {YEAR_MIN}-{YEAR_MAX}.")
    return DateParse("ok", value, span, raw)


def find_dates(text: str) -> list[DateParse]:
    """All date expressions in `text`, in order of position (non-overlapping)."""
    found: list[DateParse] = []
    for m in _RE_ISO.finditer(text):
        found.append(_build(int(m[1]), int(m[3]), int(m[4]), m.span(), m[0]))
    for m in _RE_DMY_TEXT.finditer(text):
        found.append(_build(int(m[3]), MONTHS[m[2].lower()], int(m[1]), m.span(), m[0]))
    for m in _RE_MDY_TEXT.finditer(text):
        found.append(_build(int(m[3]), MONTHS[m[1].lower()], int(m[2]), m.span(), m[0]))
    for m in _RE_NUM.finditer(text):
        a, sep, b, y = int(m[1]), m[2], int(m[3]), int(m[4])
        raw, span = m[0], m.span()
        if sep == ".":
            found.append(_build(y, b, a, span, raw))  # day-first
        elif a > 12 and b <= 12:
            found.append(_build(y, b, a, span, raw))
        elif b > 12 and a <= 12:
            found.append(_build(y, a, b, span, raw))
        elif a == b:
            found.append(_build(y, a, b, span, raw))
        elif a <= 12 and b <= 12:
            msg = f"'{raw}' is ambiguous (day-first or month-first); not interpreted."
            found.append(DateParse("ambiguous", None, span, raw, msg))
        else:
            found.append(DateParse("invalid", None, span, raw, f"'{raw}' is not a valid date."))
    found.sort(key=lambda d: d.span[0])
    deduped: list[DateParse] = []
    for d in found:  # drop overlaps
        if not deduped or d.span[0] >= deduped[-1].span[1]:
            deduped.append(d)

    def range_of(start: int, end: int) -> DateParse:
        raw = text[start:end]
        return DateParse(
            "range",
            None,
            (start, end),
            raw,
            f"'{raw}' is a date range; it was not collapsed to a single date.",
        )

    # 1) two complete dates joined by a range connector -> one range
    merged: list[DateParse] = []
    for d in deduped:
        if merged and _RANGE_CONN.match(text[merged[-1].span[1] : d.span[0]]):
            merged.append(range_of(merged.pop().span[0], d.span[1]))
        else:
            merged.append(d)
    # 2) a partial date just before a full one ('12-15 March 2025') -> range. The look-back never
    #    reaches into the previous item, so '2025-03-10 to ...' is not mistaken for a partial date.
    final: list[DateParse] = []
    prev_end = 0
    for d in merged:
        if d.status in ("ok", "ambiguous"):
            lo = max(prev_end, d.span[0] - 30)
            pm = _RANGE_PREFIX.search(text[lo : d.span[0]])
            if pm:
                d = range_of(lo + pm.start(), d.span[1])
        final.append(d)
        prev_end = d.span[1]
    return final


def parse_date(text: str) -> DateParse:
    dates = find_dates(text)
    return dates[0] if dates else DateParse("none")


# ---------------------------------------------------------------------------
# Quantities and units
# ---------------------------------------------------------------------------

_UNIT_MAP = {
    "mt": "MT",
    "mts": "MT",
    "m/t": "MT",
    "metric ton": "MT",
    "metric tons": "MT",
    "metric tonne": "MT",
    "metric tonnes": "MT",
    "tonne": "MT",
    "tonnes": "MT",
    "ton": "MT?",
    "tons": "MT?",
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "bbl": "bbl",
    "bbls": "bbl",
    "barrel": "bbl",
    "barrels": "bbl",
    "teu": "TEU",
    "teus": "TEU",
    "cbm": "m3",
    "m3": "m3",
    "m³": "m3",
    "cubic meter": "m3",
    "cubic meters": "m3",
    "cubic metre": "m3",
    "cubic metres": "m3",
}
_UNIT_ALT = "|".join(
    re.escape(u).replace(r"\ ", r"\s+") for u in sorted(_UNIT_MAP, key=len, reverse=True)
)
_NUM = r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_RANGE_SEP = r"\s*(?:-|\u2013|\u2014|\bto\b|/)\s*"
_SIGN = r"[-\u2212]"
QTY_RE = re.compile(
    rf"(?<![\w.,])(?P<sign>{_SIGN})?(?P<num>{_NUM})\s*(?P<unit>{_UNIT_ALT})(?![\w/])", re.I
)
QTY_RANGE_RE = re.compile(
    rf"(?<![\w.,])(?P<a>{_NUM}){_RANGE_SEP}(?P<b>{_NUM})\s*(?P<unit>{_UNIT_ALT})(?![\w/])", re.I
)
QTY_ONLY_RE = re.compile(rf"(?<![\w.,])(?P<sign>{_SIGN})?(?P<num>{_NUM})(?![\w.,/])")
BARE_RANGE_RE = re.compile(rf"(?<![\w.,])(?P<a>{_NUM}){_RANGE_SEP}(?P<b>{_NUM})(?![\w.,/])")


@dataclass
class QuantityParse:
    value: float | None
    unit: str | None
    unit_raw: str | None
    span: tuple[int, int]
    raw: str
    ambiguous: bool = False
    notes: list[tuple[str, str]] = field(default_factory=list)  # (code, message)


def parse_number(token: str) -> tuple[float | None, bool]:
    """Parse '45,000', '45.000,5', '45 000', '45,5'. Returns (value, ambiguous)."""
    t = token.strip()
    if re.fullmatch(r"\d{1,3}( \d{3})+([.,]\d+)?", t):
        t = t.replace(" ", "")
    has_c, has_d = "," in t, "." in t
    try:
        if has_c and has_d:
            if t.rfind(",") > t.rfind("."):  # 45.000,50
                return float(t.replace(".", "").replace(",", ".")), False
            return float(t.replace(",", "")), False  # 45,000.50
        if has_c:
            if re.fullmatch(r"\d{1,3}(,\d{3})+", t):
                return float(t.replace(",", "")), False
            if re.fullmatch(r"\d+,\d{1,2}", t):
                return float(t.replace(",", ".")), False
            return None, True
        if has_d:
            if re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", t):
                return float(t.replace(".", "")), False
            if re.fullmatch(r"\d{1,3}\.\d{3}", t):
                return None, True  # 45.000 -> 45000 or 45.0 ?
            return float(t), False
        return float(t), False
    except ValueError:
        return None, True


def normalize_unit(raw: str) -> tuple[str | None, list[tuple[str, str]]]:
    key = " ".join(raw.lower().replace(".", "").split())
    canon = _UNIT_MAP.get(key)
    if canon is None:
        return None, [("UNIT_UNRECOGNIZED", f"Unit '{raw}' is not recognised.")]
    if canon == "MT?":
        return "MT", [
            ("UNIT_AMBIGUOUS", f"'{raw}' may mean short or long tons; assumed metric tonnes (MT).")
        ]
    return canon, []


def _signed(m: re.Match) -> tuple[float | None, bool]:
    value, ambiguous = parse_number(m["num"])
    if m["sign"] and value is not None:
        value = -value  # a stated minus sign is kept so validation can reject it
    return value, ambiguous


def _range_parse(m: re.Match, unit_raw: str | None) -> QuantityParse:
    unit, notes = normalize_unit(unit_raw) if unit_raw else (None, [])
    q = QuantityParse(None, unit, unit_raw, m.span(), m[0], True, notes)
    q.notes.append(("QUANTITY_RANGE", f"'{m[0]}' is a range; no single quantity was chosen."))
    return q


def find_quantity(text: str) -> QuantityParse | None:
    """'number + unit' expression in text, or None.

    Ranges ('45,000 - 50,000 MT') and several different quantities in one value are reported as
    ambiguous (value None) instead of silently picking one. A leading minus sign is preserved.
    """
    rm = QTY_RANGE_RE.search(text)
    m = QTY_RE.search(text)
    if rm and (m is None or rm.start() <= m.start()):
        return _range_parse(rm, rm["unit"])
    if not m:
        return None
    value, ambiguous = _signed(m)
    unit, notes = normalize_unit(m["unit"])
    q = QuantityParse(value, unit, m["unit"], m.span(), m[0], ambiguous, notes)
    if ambiguous:
        q.notes.append(("QUANTITY_AMBIGUOUS", f"'{m['num']}' is ambiguous (thousands or decimal)."))
        return q
    distinct = {_signed(mm)[0] for mm in itertools.islice(QTY_RE.finditer(text), 20)}
    if len(distinct) > 1:
        q.value, q.ambiguous = None, True
        q.notes.append(
            ("QUANTITY_MULTIPLE", "Several different quantities were found in one value.")
        )
    return q


def find_bare_quantity(text: str) -> QuantityParse | None:
    rm = BARE_RANGE_RE.search(text)
    m = QTY_ONLY_RE.search(text)
    if rm and (m is None or rm.start() <= m.start()):
        return _range_parse(rm, None)
    if not m:
        return None
    value, ambiguous = _signed(m)
    q = QuantityParse(value, None, None, m.span(), m[0], ambiguous)
    if ambiguous:
        q.notes.append(("QUANTITY_AMBIGUOUS", f"'{m['num']}' is ambiguous (thousands or decimal)."))
    return q


# ---------------------------------------------------------------------------
# String cleaning
# ---------------------------------------------------------------------------

PLACEHOLDERS = {
    "n/a",
    "na",
    "tba",
    "tbn",
    "tbc",
    "nil",
    "none",
    "unknown",
    "-",
    "--",
    "to be advised",
    "to be nominated",
    "to be confirmed",
    "not applicable",
    "not stated",
    "null",
}
_ACRONYMS = {"LNG", "LPG", "DAP", "NPK", "UAN", "CPO", "RBD", "HSFO", "VLSFO", "TSP", "SSP"}


def is_placeholder(value: str) -> bool:
    return " ".join(value.lower().strip(" .:;").split()) in PLACEHOLDERS


def collapse_ws(s: str) -> str:
    return " ".join(s.split())


def _title_part(part: str) -> str:
    return part.upper() if part.upper() in _ACRONYMS else part[:1].upper() + part[1:].lower()


def smart_title(s: str) -> str:
    """Title-case each word and each '-' / '/' separated part ('Ust-Luga', not 'Ust-luga')."""
    out = []
    for tok in collapse_ws(s).split(" "):
        parts = re.split(r"([-/])", tok)
        out.append("".join(p if p in ("-", "/") else _title_part(p) for p in parts))
    return " ".join(out)


_VESSEL_PREFIX = re.compile(
    r"^(?:m\s*/\s*v|m\.\s*v\.|mv|m\s*/\s*t|motor\s+vessel|mt\b(?=\s+[A-Za-z]))\s+", re.I
)
_VESSEL_CUT = re.compile(
    r"[ ](?:v\.|voy\b|voyage\b|imo\b|flag\b|\(|-[ ]|/[ ])", re.I
)  # input is whitespace-collapsed


def clean_vessel(value: str) -> str | None:
    v = collapse_ws(value).strip(" \"'.:;,")
    v = _VESSEL_PREFIX.sub("", v)
    v = _VESSEL_CUT.split(v, maxsplit=1)[0].strip(" \"'.:;,")
    if len(v) < 2 or len(v) > 40 or not re.search(r"[A-Za-z]", v):
        return None
    return v.upper()


CARGO_SYNONYMS = {"liquefied natural gas": "LNG", "liquified natural gas": "LNG"}


def clean_cargo_type(value: str) -> str | None:
    v = collapse_ws(value)
    v = re.sub(
        r"[+\-]{1,2}\s*/?\s*[+\-]?\s*\d+\s*%(\s*(?:moloo|mol|at\s+\w+'?s?\s+option))?",
        " ",
        v,
        flags=re.I,
    )
    v = re.sub(r"\b(?:approx\.?|about|abt\.?|circa|up\s+to)\b", " ", v, flags=re.I)
    v = re.sub(r"\b(?:in\s+bulk|bulk\s+cargo|in\s+packages?)\b", " ", v, flags=re.I)
    v = re.sub(r"^\s*(?:of|:|-|,)\s+", "", v, flags=re.I)
    v = re.sub(r"\s+(?:of)\s*$", "", v, flags=re.I)
    v = collapse_ws(v).strip(" -:;,.()\"'")
    v = re.sub(r"^(?:of)\s+", "", v, flags=re.I).strip()
    if len(v) < 3 or len(v) > 60 or not re.search(r"[A-Za-z]{3}", v):
        return None
    return CARGO_SYNONYMS.get(v.casefold(), smart_title(v))


_STREET = re.compile(
    r"^(?:\d|p\.?\s?o\.?\s|plot\b|floor\b|level\b|suite\b|unit\b|building\b|bldg\b|tower\b|"
    r"[\w .'-]*\b(?:road|rd|street|st|avenue|ave|lane|drive|boulevard|blvd|square|plaza|quay|"
    r"harbou?r|house|centre|center|park)\b)",
    re.I,
)
_LEGAL = re.compile(
    r"\b(?:ltd|limited|inc|llc|gmbh|s\.?a|pte|co|corp|corporation|plc|bv|b\.v|ag|pvt|llp|"
    r"sdn bhd|ab|as|a/s|oy|nv|kg|spa|srl)\.?$",
    re.I,
)


def clean_party(value: str) -> str | None:
    v = collapse_ws(value)
    v = re.split(
        r"\s+(?:c/o|care of|att(?:n|ention)?[:.]|tel[:.]|email[:.]|vat\b)",
        v,
        maxsplit=1,
        flags=re.I,
    )[0]
    v = re.sub(r"\(.*?\)", " ", v)
    parts = [p.strip() for p in v.split(",")]
    kept: list[str] = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if i > 0 and (_STREET.match(part) or kept and _LEGAL.search(kept[-1])):
            break
        kept.append(part)
        if i == 0 and _LEGAL.search(part):
            break
    name = ", ".join(kept) if kept else ""
    name = collapse_ws(name).strip(" -:;,\"'")
    if len(name) < 3 or len(name) > 80 or not re.search(r"[A-Za-z]{3}", name):
        return None
    return name


_REF_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/_.]{3,29}")
_REF_LEAD = {"no", "nr", "#", "number", "ref", "reference", "is"}


def clean_reference(value: str) -> str | None:
    """A reference must be the FIRST token of the value (after labels like 'No.' / 'is').

    Prose such as 'see clause 12345 below' is rejected rather than yielding '12345'.
    """
    toks = value.split()
    i = 0
    while i < len(toks) and toks[i].lower().strip(":.") in _REF_LEAD:
        i += 1
    if i >= len(toks):
        return None
    cand = toks[i].strip(",;()[]\"'").rstrip(".-/_")
    if _REF_TOKEN.fullmatch(cand) and re.search(r"\d", cand) and len(cand) >= 4:
        return cand
    return None
