"""Small curated port gazetteer used to canonicalise and sanity-check port names.

This is a hand-written sample list (name, UN/LOCODE-style code, aliases) - NOT an authoritative
UN/LOCODE extract. A port that is not listed is still extracted (with a warning), never dropped.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache

# (canonical name, locode, aliases)
_PORTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Rotterdam", "NLRTM", ()),
    ("Antwerp", "BEANR", ("Antwerpen",)),
    ("Hamburg", "DEHAM", ()),
    ("Amsterdam", "NLAMS", ()),
    ("Le Havre", "FRLEH", ()),
    ("Felixstowe", "GBFXT", ()),
    ("Southampton", "GBSOU", ()),
    ("Piraeus", "GRPIR", ()),
    ("Genoa", "ITGOA", ("Genova",)),
    ("Valencia", "ESVLC", ()),
    ("Algeciras", "ESALG", ()),
    ("Istanbul", "TRIST", ()),
    ("Odessa", "UAODS", ("Odesa",)),
    ("St Petersburg", "RULED", ("Saint Petersburg", "St. Petersburg")),
    ("Port Said", "EGPSD", ()),
    ("Alexandria", "EGALY", ()),
    ("Jeddah", "SAJED", ("Jedda",)),
    ("Dammam", "SADMM", ()),
    ("Ras Tanura", "SARTA", ()),
    ("Jebel Ali", "AEJEA", ()),
    ("Fujairah", "AEFJR", ()),
    ("Salalah", "OMSLL", ()),
    ("Bandar Abbas", "IRBND", ()),
    ("Karachi", "PKKHI", ()),
    ("Colombo", "LKCMB", ()),
    ("Chittagong", "BDCGP", ("Chattogram",)),
    ("Mundra", "INMUN", ()),
    ("Nhava Sheva", "INNSA", ("JNPT", "Jawaharlal Nehru Port")),
    ("Mumbai", "INBOM", ("Bombay",)),
    ("Kandla", "INIXY", ("Deendayal",)),
    ("Mormugao", "INMRM", ("Goa",)),
    ("New Mangalore", "INNML", ("Mangalore",)),
    ("Cochin", "INCOK", ("Kochi",)),
    ("Tuticorin", "INTUT", ("V.O. Chidambaranar", "Thoothukudi")),
    ("Chennai", "INMAA", ("Madras",)),
    ("Visakhapatnam", "INVTZ", ("Vizag", "Vishakhapatnam")),
    ("Paradip", "INPBD", ()),
    ("Haldia", "INHAL", ()),
    ("Kolkata", "INCCU", ("Calcutta",)),
    ("Singapore", "SGSIN", ()),
    ("Port Klang", "MYPKG", ("Port Kelang", "Klang")),
    ("Laem Chabang", "THLCH", ()),
    ("Ho Chi Minh City", "VNSGN", ("Saigon", "Ho Chi Minh")),
    ("Jakarta", "IDJKT", ("Tanjung Priok",)),
    ("Hong Kong", "HKHKG", ()),
    ("Shanghai", "CNSHA", ()),
    ("Ningbo", "CNNGB", ("Ningbo-Zhoushan",)),
    ("Qingdao", "CNTAO", ()),
    ("Tianjin", "CNTSN", ("Xingang",)),
    ("Dalian", "CNDLC", ()),
    ("Yantian", "CNYTN", ()),
    ("Kaohsiung", "TWKHH", ()),
    ("Busan", "KRPUS", ("Pusan",)),
    ("Yokohama", "JPYOK", ()),
    ("Port Hedland", "AUPHE", ()),
    ("Dampier", "AUDAM", ()),
    ("Hay Point", "AUHPT", ()),
    ("Newcastle", "AUNTL", ()),
    ("Los Angeles", "USLAX", ()),
    ("Long Beach", "USLGB", ()),
    ("Seattle", "USSEA", ()),
    ("Houston", "USHOU", ()),
    ("New Orleans", "USMSY", ()),
    ("Savannah", "USSAV", ()),
    ("New York", "USNYC", ()),
    ("Vancouver", "CAVAN", ()),
    ("Montreal", "CAMTR", ()),
    ("Manzanillo", "MXZLO", ()),
    ("Santos", "BRSSZ", ()),
    ("Paranagua", "BRPNG", ("Paranaguá",)),
    ("Buenos Aires", "ARBUE", ()),
    ("Valparaiso", "CLVAP", ("Valparaíso",)),
    ("Durban", "ZADUR", ()),
    ("Richards Bay", "ZARCB", ()),
    ("Lagos", "NGLOS", ()),
    ("Mombasa", "KEMBA", ()),
    ("Casablanca", "MACAS", ()),
    ("Port of Spain", "TTPOS", ()),
    ("Port Louis", "MUPLU", ()),
    ("Port Elizabeth", "ZAPLZ", ("Gqeberha",)),
    ("Port Harcourt", "NGPHC", ()),
    ("Port Sudan", "SDPZU", ()),
    ("Port Moresby", "PGPOM", ()),
    ("Port Kembla", "AUPKL", ()),
]


def _norm(text: str) -> str:
    """Lower-case, strip accents/punctuation. 'port' and 'of' are KEPT: 'Port of Spain' is a name."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return " ".join(w for w in text.split() if w != "the")


def _variants(key: str) -> list[str]:
    """The key itself first, then forms with a generic 'port of' / 'port' prefix removed."""
    out = [key]
    for prefix in ("port of ", "port "):
        if key.startswith(prefix) and len(key) > len(prefix):
            out.append(key[len(prefix) :])
    return out


_ALIAS_TO_CANON: dict[str, str] = {}
_CODE_TO_CANON: dict[str, str] = {}
for _canon, _code, _aliases in _PORTS:
    _CODE_TO_CANON[_code] = _canon
    for _name in (_canon, *_aliases):
        _ALIAS_TO_CANON[_norm(_name)] = _canon
_ALIAS_KEYS = list(_ALIAS_TO_CANON)

KNOWN_PORT_COUNT = len(_PORTS)


@lru_cache(maxsize=4096)
def lookup_port(text: str, fuzzy: bool = True) -> tuple[str, str] | None:
    """Return (canonical_name, how) where how is 'exact' | 'locode' | 'fuzzy', or None.

    The full name is tried before any generic 'Port of' prefix is dropped, so real names such as
    'Port of Spain' are never reduced to 'Spain'. Results are cached (pure function).
    """
    if not text or not text.strip() or len(text) > 80:
        return None
    code = re.fullmatch(r"\s*([A-Z]{2}\s?[A-Z]{3})\s*", text)
    if code:
        canon = _CODE_TO_CANON.get(code.group(1).replace(" ", ""))
        if canon:
            return canon, "locode"
    variants = _variants(_norm(text))
    for key in variants:
        if key in _ALIAS_TO_CANON:
            return _ALIAS_TO_CANON[key], "exact"
    if fuzzy:
        for key in variants:
            if len(key) < 5:
                continue
            # "rn" is a classic OCR/typing confusion for "m" (e.g. Rotterdarn)
            for variant in dict.fromkeys((key, key.replace("rn", "m"))):
                match = difflib.get_close_matches(variant, _ALIAS_KEYS, n=1, cutoff=0.85)
                if match:
                    return _ALIAS_TO_CANON[match[0]], "fuzzy"
    return None


def find_locode_in_text(text: str) -> str | None:
    """Find a parenthesised/standalone known LOCODE such as '(NLRTM)' in free text."""
    for m in re.finditer(r"\b([A-Z]{2}[A-Z]{3})\b", text):
        if m.group(1) in _CODE_TO_CANON:
            return m.group(1)
    return None


CARGO_TERMS = {
    "coal",
    "thermal coal",
    "coking coal",
    "iron ore",
    "crude oil",
    "palm oil",
    "wheat",
    "soybeans",
    "corn",
    "maize",
    "urea",
    "fertilizer",
    "steel coils",
    "bauxite",
    "cement clinker",
    "raw sugar",
    "sugar",
    "rice",
    "copper concentrate",
    "lng",
    "naphtha",
    "diesel",
    "containerised general cargo",
    "containers",
    "limestone",
    "scrap metal",
    "crude palm oil",
    "bitumen",
    "gasoline",
    "fuel oil",
    "barley",
    "sunflower oil",
    "cement",
    "salt",
}
