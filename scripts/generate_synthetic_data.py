#!/usr/bin/env python
"""Generate SYNTHETIC shipping documents (TXT + PDF) and ground-truth annotations.

Everything produced here is fictional and labelled as synthetic in every document footer and in
the annotations (`"synthetic": true`). Vessel and company names are random word combinations and
may coincide with real ones by accident; no real-world records are used or imitated.

Split policy: documents are split by TEMPLATE, not by document. Templates D1-D6 form the `dev`
split (used while building the rules); templates T1-T3 form the held-out `test` split. The test
templates use different layouts and some different label wording.

Usage:  python scripts/generate_synthetic_data.py [--seed 42] [--out data]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.gazetteer import lookup_port  # noqa: E402  (only to sanity-check the port pools)
from app.schemas import FIELD_NAMES  # noqa: E402

FOOTER = "[SYNTHETIC SAMPLE - fictional data generated for software testing; not a real document]"

# (name, country, locode) - all present in the app gazetteer
KNOWN_PORTS = [
    ("Rotterdam", "Netherlands", "NLRTM"),
    ("Antwerp", "Belgium", "BEANR"),
    ("Hamburg", "Germany", "DEHAM"),
    ("Singapore", "Singapore", "SGSIN"),
    ("Shanghai", "China", "CNSHA"),
    ("Qingdao", "China", "CNTAO"),
    ("Busan", "South Korea", "KRPUS"),
    ("Houston", "USA", "USHOU"),
    ("Santos", "Brazil", "BRSSZ"),
    ("Durban", "South Africa", "ZADUR"),
    ("Port Hedland", "Australia", "AUPHE"),
    ("Newcastle", "Australia", "AUNTL"),
    ("Mundra", "India", "INMUN"),
    ("Kandla", "India", "INIXY"),
    ("Paradip", "India", "INPBD"),
    ("Visakhapatnam", "India", "INVTZ"),
    ("Chennai", "India", "INMAA"),
    ("Jebel Ali", "UAE", "AEJEA"),
    ("Fujairah", "UAE", "AEFJR"),
    ("Jeddah", "Saudi Arabia", "SAJED"),
    ("Piraeus", "Greece", "GRPIR"),
    ("Genoa", "Italy", "ITGOA"),
    ("Valencia", "Spain", "ESVLC"),
    ("Le Havre", "France", "FRLEH"),
    ("Yokohama", "Japan", "JPYOK"),
    ("Kaohsiung", "Taiwan", "TWKHH"),
    ("Port Klang", "Malaysia", "MYPKG"),
    ("Colombo", "Sri Lanka", "LKCMB"),
    ("Richards Bay", "South Africa", "ZARCB"),
    ("Dampier", "Australia", "AUDAM"),
    ("Hay Point", "Australia", "AUHPT"),
    ("Los Angeles", "USA", "USLAX"),
    ("New Orleans", "USA", "USMSY"),
    ("Vancouver", "Canada", "CAVAN"),
    ("Mombasa", "Kenya", "KEMBA"),
    ("Lagos", "Nigeria", "NGLOS"),
    ("Dalian", "China", "CNDLC"),
    ("Tianjin", "China", "CNTSN"),
    ("Mormugao", "India", "INMRM"),
    ("Alexandria", "Egypt", "EGALY"),
]
# Ports deliberately absent from the app gazetteer (tests the 'unrecognised port' path)
UNKNOWN_PORTS = [
    ("Vizhinjam", "India"),
    ("Ust-Luga", "Russia"),
    ("Gladstone", "Australia"),
    ("Tubarao", "Brazil"),
    ("Gdansk", "Poland"),
    ("Klaipeda", "Lithuania"),
    ("Kribi", "Cameroon"),
    ("Dunkirk", "France"),
]

V_A = [
    "NORDIC",
    "PACIFIC",
    "ATLANTIC",
    "OCEAN",
    "STAR",
    "GOLDEN",
    "BLUE",
    "CAPE",
    "EASTERN",
    "ARCTIC",
    "SILVER",
    "CRIMSON",
    "NORTHERN",
    "AMBER",
    "IVORY",
    "CORAL",
    "HARBOUR",
    "TIDAL",
]
V_B = [
    "AURORA",
    "TRADER",
    "PIONEER",
    "VOYAGER",
    "HORIZON",
    "SPIRIT",
    "FORTUNE",
    "HARMONY",
    "EXPLORER",
    "LEGEND",
    "PROVIDENCE",
    "ENDEAVOUR",
    "MERIDIAN",
    "GUARDIAN",
    "NAVIGATOR",
]
C_A = [
    "Meridian",
    "Orion",
    "Baltic",
    "Sunrise",
    "Halcyon",
    "Vanguard",
    "Kestrel",
    "Lumen",
    "Cobalt",
    "Zenith",
    "Aldgate",
    "Northwind",
    "Tidewater",
    "Granite",
    "Saffron",
    "Juniper",
]
C_B = [
    "Bulk Trading",
    "Commodities",
    "Shipping",
    "Maritime",
    "Chartering",
    "Energy",
    "Agri Exports",
    "Logistics",
    "Resources",
    "Marine Services",
]
C_S = ["Ltd", "Ltd.", "Pte Ltd", "GmbH", "Inc.", "LLC", "S.A.", "B.V.", "Co. Ltd", "Pvt Ltd"]
STREETS = [
    "12 Harbour Road",
    "88 Quay Street",
    "5 Marina Boulevard",
    "301 Dock Lane",
    "17 Port Avenue",
    "Plot 44, Industrial Estate",
]
CITIES = ["London", "Singapore", "Dubai", "Mumbai", "Athens", "Geneva", "Hamburg"]

# cargo_type -> (units, (min_qty, max_qty), surface variants)
CARGO = {
    "Thermal Coal": (["MT"], (20_000, 80_000), ["Thermal Coal", "thermal coal", "THERMAL COAL"]),
    "Iron Ore": (["MT"], (50_000, 180_000), ["Iron Ore", "IRON ORE", "iron ore"]),
    "Crude Palm Oil": (["MT"], (5_000, 40_000), ["Crude Palm Oil", "CRUDE PALM OIL"]),
    "Wheat": (["MT"], (10_000, 60_000), ["Wheat", "WHEAT", "wheat"]),
    "Soybeans": (["MT"], (20_000, 70_000), ["Soybeans", "SOYBEANS"]),
    "Corn": (["MT"], (20_000, 65_000), ["Corn", "CORN"]),
    "Urea": (["MT"], (8_000, 45_000), ["Urea", "UREA"]),
    "Steel Coils": (["MT"], (5_000, 30_000), ["Steel Coils", "steel coils"]),
    "Bauxite": (["MT"], (40_000, 120_000), ["Bauxite", "BAUXITE"]),
    "Cement Clinker": (["MT"], (15_000, 50_000), ["Cement Clinker", "CEMENT CLINKER"]),
    "Raw Sugar": (["MT"], (10_000, 55_000), ["Raw Sugar", "RAW SUGAR"]),
    "Copper Concentrate": (["MT"], (5_000, 25_000), ["Copper Concentrate", "COPPER CONCENTRATE"]),
    "Limestone": (["MT"], (20_000, 70_000), ["Limestone", "LIMESTONE"]),
    "Crude Oil": (["bbl"], (300_000, 2_000_000), ["Crude Oil", "CRUDE OIL"]),
    "Diesel": (["bbl", "MT"], (20_000, 400_000), ["Diesel", "DIESEL"]),
    "Naphtha": (["MT"], (15_000, 40_000), ["Naphtha", "NAPHTHA"]),
    "Containerised General Cargo": (
        ["TEU"],
        (500, 9_000),
        ["Containerised General Cargo", "containerised general cargo"],
    ),
    "LNG": (["m3"], (80_000, 170_000), ["LNG", "Liquefied Natural Gas"]),
}
UNIT_SURFACE = {
    "MT": ["MT", "MT", "MT", "metric tons", "Metric Tonnes", "MTS", "tonnes"],
    "bbl": ["bbl", "barrels", "BBLS"],
    "TEU": ["TEU", "TEUs"],
    "m3": ["m3", "cbm", "CBM", "cubic metres"],
}
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
ROLE_ORDER = ["charterer", "shipper", "consignee", "buyer"]

DEV_TEMPLATES = [
    "D1_bill_of_lading",
    "D2_fixture_recap",
    "D3_cargo_manifest",
    "D4_notice_of_readiness",
    "D5_shipping_instruction",
    "D6_voyage_summary",
]
TEST_TEMPLATES = ["T1_charter_party_summary", "T2_consignment_advice", "T3_voyage_email"]
DOCS_PER_TEMPLATE = {"dev": 16, "test": 18}
# Special-case documents per template position (index within template)
KIND_SCHEDULE = {
    1: "ambiguous_date",
    3: "date_order",
    5: "zero_qty",
    7: "same_port",
    9: "invalid_date",
    11: "ambiguous_date",
    13: "date_order",
    15: "non_shipping",
}
P_OMIT = {
    "vessel": 0.03,
    "origin": 0.10,
    "dest": 0.10,
    "cargo": 0.06,
    "qty": 0.08,
    "load": 0.15,
    "disch": 0.25,
    "ref": 0.06,
    "charterer": 0.45,
    "shipper": 0.35,
    "consignee": 0.35,
    "buyer": 0.70,
}


# ---------------------------------------------------------------------------
# Scenario -> surfaces
# ---------------------------------------------------------------------------
def company(rng: random.Random) -> str:
    return f"{rng.choice(C_A)} {rng.choice(C_B)} {rng.choice(C_S)}"


def fmt_date(d: dt.date, rng: random.Random, style: str | None = None) -> str:
    style = style or rng.choice(["dmy", "mdy", "abbr", "iso", "ordinal", "dotted", "slash"])
    m = MONTHS[d.month - 1]
    if style == "slash" and d.day <= 12:
        style = "dmy"  # never emit a numeric date that is ambiguous by accident
    return {
        "dmy": f"{d.day} {m} {d.year}",
        "mdy": f"{m} {d.day}, {d.year}",
        "abbr": f"{d.day:02d}-{m[:3]}-{d.year}",
        "iso": d.isoformat(),
        "ordinal": f"{d.day}{'th' if 10 <= d.day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d.day % 10, 'th')} {m} {d.year}",
        "dotted": f"{d.day:02d}.{d.month:02d}.{d.year}",
        "slash": f"{d.day:02d}/{d.month:02d}/{d.year}",
    }[style]


def fmt_qty(q: float, rng: random.Random) -> str:
    if q != int(q):
        return rng.choice(
            [f"{q:,.1f}", f"{q:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")]
        )
    return rng.choice([f"{int(q):,}", f"{int(q):,}", str(int(q)), f"{int(q):,}".replace(",", " ")])


def port_surface(p: tuple, rng: random.Random, noisy: bool = True) -> str:
    name = p[0]
    country = p[1]
    code = p[2] if len(p) > 2 else None
    form = rng.choice(["plain", "plain", "upper", "country", "locode"])
    if code is None and form == "locode":
        form = "plain"
    if form == "upper":
        name = name.upper()
    if (
        noisy and code and rng.random() < 0.05 and len(name) > 5
    ):  # spelling noise (known ports only)
        i = rng.randrange(1, len(name) - 1)
        name = (
            name[:i] + name[i + 1 :]
            if rng.random() < 0.5
            else name[:i] + name[i + 1] + name[i] + name[i + 2 :]
        )
    if form == "country":
        return f"{name}, {country}"
    if form == "locode":
        return f"{name} ({code})"
    return name


def typo(label: str, rng: random.Random) -> str:
    if len(label) < 5:
        return label
    i = rng.randrange(1, len(label) - 1)
    if not label[i].isalpha():
        return label
    return rng.choice(
        [
            label[:i] + label[i + 1 :],
            label[:i] + label[i + 1] + label[i] + label[i + 2 :],
            label[:i] + rng.choice("aeiounrst") + label[i + 1 :],
        ]
    )


def make_scenario(rng: random.Random, kind: str) -> dict:
    cargo = rng.choice(list(CARGO))
    units, (lo, hi), variants = CARGO[cargo]
    unit = rng.choice(units)
    qty = float(round(rng.uniform(lo, hi), -2 if hi > 1000 else 0))
    if rng.random() < 0.10 and hi > 1000:
        qty += 0.5  # occasional decimal quantity
    load = dt.date(2024, 6, 1) + dt.timedelta(days=rng.randrange(0, 760))
    disch = load + dt.timedelta(days=rng.randrange(8, 41))
    pool = KNOWN_PORTS
    ports = rng.sample(pool, 2)
    o, d = ports
    if rng.random() < 0.10:
        o = rng.choice(UNKNOWN_PORTS)
    if rng.random() < 0.10:
        d = rng.choice(UNKNOWN_PORTS)
    prefix = rng.choice(["BL", "MSK", "FX", "CP", "MAN", "SI", "REF"])
    ref = rng.choice(
        [
            f"{prefix}-{load.year}-{rng.randrange(1000, 999999):06d}",
            f"{prefix}{load.year}/{rng.randrange(100, 9999)}",
            f"{prefix}{rng.randrange(100000, 999999)}",
            f"{prefix}-{rng.randrange(1000, 99999)}-{rng.choice('ABCDEFGH')}",
        ]
    )
    vessel = f"{rng.choice(V_A)} {rng.choice(V_B)}" + (
        f" {rng.randrange(2, 9)}" if rng.random() < 0.08 else ""
    )
    return {
        "kind": kind,
        "cargo": cargo,
        "variants": variants,
        "unit": unit,
        "qty": qty,
        "load": load,
        "disch": disch,
        "origin": o,
        "dest": d,
        "ref": ref,
        "vessel": vessel,
        "parties": {r: company(rng) for r in ROLE_ORDER},
        "issue": load - dt.timedelta(days=rng.randrange(1, 6)),
        "voyage": f"{rng.randrange(1, 60)}{rng.choice('EW')}",
        "city": rng.choice(CITIES),
        "street": rng.choice(STREETS),
        "imo": f"{rng.randrange(9000000, 9999999)}",
    }


def surfaces(
    rng: random.Random, sc: dict, roles: list[str], typo_p: float
) -> tuple[dict, dict, list[str]]:
    """Return (surfaces S, truth, expected_warnings). Truth is None for omitted/uninterpretable."""
    kind = sc["kind"]
    expected_warnings: list[str] = []
    force = {
        "ambiguous_date": {"load"},
        "invalid_date": {"load"},
        "date_order": {"load", "disch"},
        "same_port": {"origin", "dest"},
        "zero_qty": {"cargo", "qty"},
    }.get(kind, set())
    omit = {k: (k not in force and rng.random() < p) for k, p in P_OMIT.items()}
    omit["unit_only"] = False
    present_roles = [r for r in roles if not omit[r]]
    S: dict = {}
    truth = dict.fromkeys(FIELD_NAMES)

    S["vessel"] = (
        None
        if omit["vessel"]
        else rng.choice(
            [
                f"M/V {sc['vessel']}",
                f"MV {sc['vessel'].title()}",
                sc["vessel"],
                f"M.V. {sc['vessel'].title()}",
                f"{sc['vessel']} V.{sc['voyage']}",
            ]
        )
    )
    truth["vessel_name"] = None if omit["vessel"] else sc["vessel"].upper()

    dest = sc["origin"] if kind == "same_port" else sc["dest"]
    S["origin"] = None if omit["origin"] else port_surface(sc["origin"], rng)
    S["dest"] = None if omit["dest"] else port_surface(dest, rng)
    truth["origin_port"] = None if omit["origin"] else sc["origin"][0]
    truth["destination_port"] = None if omit["dest"] else dest[0]
    if kind == "same_port":
        expected_warnings.append("SAME_PORT")

    S["cargo_name"] = None if omit["cargo"] else rng.choice(sc["variants"])
    truth["cargo_type"] = None if omit["cargo"] else sc["cargo"]
    qty = 0.0 if kind == "zero_qty" else sc["qty"]
    unit_s = rng.choice(UNIT_SURFACE[sc["unit"]])
    if omit["qty"]:
        S["qty_num"] = S["unit"] = S["qty"] = None
    else:
        S["qty_num"], S["unit"] = fmt_qty(qty, rng), unit_s
        S["qty"] = f"{S['qty_num']} {unit_s}"
        truth["cargo_unit"] = sc["unit"]
        truth["cargo_quantity"] = None if kind == "zero_qty" else qty
        if kind == "zero_qty":
            expected_warnings.append("NONPOSITIVE_QUANTITY")

    load, disch = sc["load"], sc["disch"]
    if kind == "date_order":
        disch = load - dt.timedelta(days=rng.randrange(3, 20))
        expected_warnings.append("DISCHARGE_BEFORE_LOADING")
    if omit["load"]:
        S["load"] = None
    elif kind == "ambiguous_date":
        a, b = rng.sample(range(1, 13), 2)
        S["load"] = f"{a:02d}/{b:02d}/{load.year}"
        expected_warnings.append("AMBIGUOUS_DATE")
    elif kind == "invalid_date":
        S["load"] = rng.choice(["31 April 2025", "30 February 2025", "31/06/2025"])
        expected_warnings.append("INVALID_DATE")
    else:
        S["load"] = fmt_date(load, rng)
        truth["loading_date"] = load.isoformat()
    S["disch"] = None if omit["disch"] else fmt_date(disch, rng)
    truth["discharge_date"] = None if omit["disch"] else disch.isoformat()

    S["ref"] = None if omit["ref"] else sc["ref"]
    truth["document_reference"] = None if omit["ref"] else sc["ref"]

    S["parties"] = {}
    for r in roles:
        if omit[r]:
            continue
        name = sc["parties"][r]
        S["parties"][r] = (
            f"{name}, {sc['street']}, {sc['city']}"
            if r == "shipper" and rng.random() < 0.4
            else name
        )
    for r in ROLE_ORDER:
        if r in present_roles:
            truth["counterparty"] = sc["parties"][r]
            break
    S["typo_p"] = typo_p
    return S, truth, expected_warnings


def combined_cargo(S: dict, rng: random.Random) -> str | None:
    name, qty = S["cargo_name"], S["qty"]
    if name and qty:
        return rng.choice(
            [
                f"{qty} {name}",
                f"{name} - {qty}",
                f"approx. {qty} {name} +/- 10%",
                f"{name} in bulk, {qty}",
                f"{qty} of {name}",
            ]
        )
    return name or None


# ---------------------------------------------------------------------------
# Templates -> items  ("title", t) | ("kv", label, value) | ("para", text) | ("blank",)
# ---------------------------------------------------------------------------
def kvs(rng: random.Random, S: dict, pairs: list) -> list:
    out = []
    for label, value in pairs:
        if value:
            if rng.random() < S["typo_p"]:
                label = typo(label, rng)
            out.append(("kv", label, value))
    return out


def party_value(S: dict, role: str):
    return S["parties"].get(role)


def tpl_d1(rng, sc, S):
    lab = rng.choice
    items = [("title", "BILL OF LADING")]
    items += kvs(
        rng,
        S,
        [
            (lab(["B/L No.", "BL No", "Bill of Lading No."]), S["ref"]),
            ("Shipper", party_value(S, "shipper")),
            ("Consignee", party_value(S, "consignee")),
            ("Notify Party", company(rng)),
            (lab(["Vessel", "Ocean Vessel", "Vessel Name"]), S["vessel"]),
            (lab(["Port of Loading", "Loading Port"]), S["origin"]),
            ("Port of Discharge", S["dest"]),
        ],
    )
    mode = combined_cargo(S, rng)
    items += kvs(
        rng,
        S,
        [
            ("Description of Goods", mode),
            ("Shipped on Board", S["load"]),
            (lab(["Date of Discharge", "Delivery Date"]), S["disch"]),
            ("Date of Issue", fmt_date(sc["issue"], rng)),
            ("Place of Issue", sc["city"]),
            ("Freight", "PREPAID"),
            ("Container No.", f"MSKU{rng.randrange(1000000, 9999999)}"),
        ],
    )
    items.append(
        (
            "para",
            "Weight, measure and quantity declared by shipper. Carrier not responsible for loss or damage as per terms overleaf.",
        )
    )
    return items


def tpl_d2(rng, sc, S):
    items = [
        ("title", "FIXTURE RECAP"),
        ("para", "We are pleased to confirm the following fixture. Main terms as per below."),
    ]
    items += kvs(
        rng,
        S,
        [
            ("Fixture Ref", S["ref"]),
            ("Vessel", S["vessel"]),
            ("Charterers", party_value(S, "charterer")),
            ("Cargo", combined_cargo(S, rng)),
            ("Load Port", S["origin"]),
            ("Discharge Port", S["dest"]),
            ("Freight", f"USD {rng.randrange(12, 40)}.{rng.randrange(10, 99)} PMT"),
            ("Invoice No", f"INV-{rng.randrange(10000, 99999)}"),
        ],
    )
    sent = []
    if S["load"]:
        sent.append(f"Loading is expected on {S['load']}.")
    if S["disch"]:
        sent.append(f"Discharge is expected on {S['disch']}.")
    if sent:
        items.append(("para", " ".join(sent) + " Laytime and demurrage as per charter party."))
    items.append(("para", "Kindly confirm receipt of this recap at your earliest convenience."))
    return items


def tpl_d3(rng, sc, S):
    items = [("title", "CARGO MANIFEST")]
    items += kvs(
        rng,
        S,
        [
            ("Manifest No", S["ref"]),
            ("Vessel Name", S["vessel"]),
            ("Origin", S["origin"]),
            ("Destination", S["dest"]),
            ("Commodity", S["cargo_name"]),
            ("Quantity", S["qty"]),
            ("Date Loaded", S["load"]),
            ("Date Discharged", S["disch"]),
            ("Shipper", party_value(S, "shipper")),
            ("Voyage No", sc["voyage"]),
            ("IMO No", sc["imo"]),
            ("Date of Issue", fmt_date(sc["issue"], rng)),
        ],
    )
    return items


def tpl_d4(rng, sc, S):
    items = [("title", "NOTICE OF READINESS")]
    if S["ref"]:
        items.append(("para", f"Ref: {S['ref']}"))
    ch = party_value(S, "charterer")
    items.append(("para", f"Date: {fmt_date(sc['issue'], rng)}"))
    items.append(("para", "Dear Sirs,"))
    s1 = (
        f"Please be advised that {S['vessel']} has arrived"
        if S["vessel"]
        else "Please be advised that the vessel has arrived"
    )
    s1 += (
        f" and is ready in all respects to load at {S['origin']}."
        if S["origin"]
        else " and is ready in all respects."
    )
    para = [s1]
    if ch and S["qty"] and S["cargo_name"]:
        para.append(f"She is chartered by {ch} and is carrying {S['qty']} of {S['cargo_name']}.")
    elif ch:
        para.append(f"She is chartered by {ch}.")
    elif S["qty"] and S["cargo_name"]:
        para.append(f"She is carrying {S['qty']} of {S['cargo_name']}.")
    elif S["cargo_name"]:
        para.append(f"The cargo is {S['cargo_name']}.")
    if S["load"]:
        para.append(f"Loading commenced on {S['load']}.")
    if S["dest"]:
        para.append(
            f"The cargo will be discharged at {S['dest']}"
            + (f", with discharge on {S['disch']}." if S["disch"] else ".")
        )
    elif S["disch"]:
        para.append(f"Discharge is planned on {S['disch']}.")
    items.append(("para", " ".join(para)))
    items.append(("para", "Yours faithfully, The Master"))
    return items


def tpl_d5(rng, sc, S):
    items = [("title", "SHIPPING INSTRUCTION")]
    items += kvs(
        rng,
        S,
        [
            ("Shipper", party_value(S, "shipper")),
            ("Vessel", S["vessel"]),
            ("Loading Port", S["origin"]),
            ("Discharge Port", S["dest"]),
            ("Commodity", S["cargo_name"]),
            ("Quantity", S["qty"]),
            ("Loading Date", S["load"]),
            ("Discharge Date", S["disch"]),
            ("Document No", S["ref"]),
            ("Special Instructions", "Handle with care; keep dry"),
        ],
    )
    return items


def tpl_d6(rng, sc, S):
    items = [("title", "VOYAGE SUMMARY")]
    items += kvs(
        rng,
        S,
        [
            ("Vessel", S["vessel"]),
            ("Ref", S["ref"]),
            ("From", S["origin"]),
            ("To", S["dest"]),
            ("Cargo", S["cargo_name"]),
            ("Qty", S["qty"]),
            ("Loaded", S["load"]),
            ("Discharged", S["disch"]),
            ("Charterer", party_value(S, "charterer")),
            ("Voyage", sc["voyage"]),
        ],
    )
    return items


def tpl_t1(rng, sc, S):
    items = [("title", "CHARTER PARTY SUMMARY")]
    pairs = [
        ("CP Ref", S["ref"]),
        ("Vessel", S["vessel"]),
        ("Charterers", party_value(S, "charterer")),
        ("Cargo", S["cargo_name"]),
        ("Quantity", S["qty"]),
        ("Load Port", S["origin"]),
        ("Discharge Port", S["dest"]),
        ("Loading Date", S["load"]),
        ("Discharge Date", S["disch"]),
        ("Owners", company(rng)),
        ("Freight", f"USD {rng.randrange(12, 40)} PMT"),
    ]
    n = 0
    for label, value in pairs:
        if value:
            n += 1
            lab = typo(label, rng) if rng.random() < S["typo_p"] else label
            items.append(("kv", f"{n}. {lab}", value))
    return items


def tpl_t2(rng, sc, S):
    items = [("title", "CONSIGNMENT ADVICE")]
    items += kvs(
        rng,
        S,
        [
            ("Carrier Vessel", S["vessel"]),
            ("Shipment Ref", S["ref"]),
            ("Origin Port", S["origin"]),
            ("Destination Port", S["dest"]),
            ("Goods", S["cargo_name"]),
            ("Total Quantity", S["qty"]),
            ("Loaded On", S["load"]),
            ("Delivered On", S["disch"]),
            ("Consignee", party_value(S, "consignee")),
            ("Buyer", party_value(S, "buyer")),
            ("Advice Date", fmt_date(sc["issue"], rng)),
        ],
    )
    return items


def tpl_t3(rng, sc, S):
    items = [("title", "VOYAGE UPDATE")]
    para = []
    v = S["vessel"] or "the vessel"
    first = f"Please note that {'MV ' + sc['vessel'].title() if S['vessel'] else v} will lift"
    if S["qty"] and S["cargo_name"]:
        first += f" {S['qty']} of {S['cargo_name']}"
    elif S["cargo_name"]:
        first += f" a cargo of {S['cargo_name']}"
    else:
        first += " the cargo"
    if S["origin"]:
        first += f" at {S['origin']}"
    if S["dest"]:
        first += f" for delivery to {S['dest']}"
    para.append(first + ".")
    if S["load"]:
        para.append(f"Loading is scheduled for {S['load']}.")
    if S["disch"]:
        para.append(f"Delivery is expected on {S['disch']}.")
    if S["ref"]:
        para.append(f"Our reference is {S['ref']}.")
    items.append(("para", " ".join(para)))
    b = party_value(S, "buyer")
    if b:
        items.append(("para", f"Buyer: {b}"))
    items.append(("para", "Regards, Operations Desk"))
    return items


TEMPLATES = {
    "D1_bill_of_lading": dict(
        fn=tpl_d1, roles=["shipper", "consignee"], txt=["colon", "aligned"], pdf=["lines", "table"]
    ),
    "D2_fixture_recap": dict(fn=tpl_d2, roles=["charterer"], txt=["colon"], pdf=["lines"]),
    "D3_cargo_manifest": dict(
        fn=tpl_d3, roles=["shipper"], txt=["aligned", "colon"], pdf=["table"]
    ),
    "D4_notice_of_readiness": dict(fn=tpl_d4, roles=["charterer"], txt=["colon"], pdf=["lines"]),
    "D5_shipping_instruction": dict(
        fn=tpl_d5, roles=["shipper"], txt=["aligned"], pdf=["table", "lines"]
    ),
    "D6_voyage_summary": dict(fn=tpl_d6, roles=["charterer"], txt=["pipe"], pdf=["lines"]),
    "T1_charter_party_summary": dict(fn=tpl_t1, roles=["charterer"], txt=["colon"], pdf=["lines"]),
    "T2_consignment_advice": dict(
        fn=tpl_t2, roles=["consignee", "buyer"], txt=["aligned"], pdf=["table"]
    ),
    "T3_voyage_email": dict(fn=tpl_t3, roles=["buyer"], txt=["colon"], pdf=["lines"]),
}

NON_SHIPPING = [
    (
        "OFFICE SUPPLIES INVOICE",
        [
            "Invoice No: INV-20931",
            "Item: A4 paper, 40 reams",
            "Item: stapler (box of 10)",
            "Total due: USD 212.40",
            "Payment due within 30 days.",
            "Thank you for your business.",
        ],
    ),
    (
        "TEAM MEETING NOTES",
        [
            "Attendees: five people from operations and finance.",
            "Agenda: budget review, holiday rota, printer replacement.",
            "Action: book the meeting room for next Tuesday.",
            "Next meeting: first Monday of the month.",
        ],
    ),
    (
        "WEATHER BULLETIN",
        [
            "Forecast: light winds and scattered showers across the northern coast.",
            "Visibility: moderate to good. Sea state: slight.",
            "Outlook: improving conditions by the weekend.",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_txt(items: list, style: str, rng: random.Random) -> str:
    lines: list[str] = []
    i = 0
    while i < len(items):
        it = items[i]
        if it[0] == "title":
            lines += [it[1], ""]
        elif it[0] == "para":
            lines += textwrap.wrap(it[1], width=78) + [""]
        elif it[0] == "kv":
            if style == "pipe":
                group = [it]
                size = rng.choice([2, 3])
                while len(group) < size and i + 1 < len(items) and items[i + 1][0] == "kv":
                    i += 1
                    group.append(items[i])
                lines.append(" | ".join(f"{g[1]}: {g[2]}" for g in group))
            elif style == "aligned":
                lab = it[1].upper()
                lines.append(f"{lab:<24}{it[2]}" if len(lab) < 22 else f"{lab}   {it[2]}")
            else:
                lines.append(f"{it[1]}: {it[2]}")
        i += 1
    return "\n".join(lines).rstrip() + "\n\n" + FOOTER + "\n"


def render_pdf(items: list, style: str, path: Path) -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors, pagesizes
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    flow = []
    kv_rows: list[list] = []

    def flush() -> None:
        nonlocal kv_rows
        if kv_rows:
            tbl = Table(kv_rows, colWidths=[55 * mm, 110 * mm])
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            flow.extend([tbl, Spacer(1, 6)])
            kv_rows = []

    for it in items:
        if it[0] == "title":
            flow += [Paragraph(f"<b>{escape(it[1])}</b>", ss["Title"]), Spacer(1, 6)]
        elif it[0] == "para":
            flush()
            flow += [Paragraph(escape(it[1]), ss["BodyText"]), Spacer(1, 4)]
        elif it[0] == "kv":
            if style == "table":
                kv_rows.append(
                    [
                        Paragraph(escape(it[1]), ss["BodyText"]),
                        Paragraph(escape(it[2]), ss["BodyText"]),
                    ]
                )
            else:
                flow.append(Paragraph(f"{escape(it[1])}: {escape(it[2])}", ss["BodyText"]))
    flush()
    flow += [Spacer(1, 10), Paragraph(f"<font size=7>{escape(FOOTER)}</font>", ss["BodyText"])]
    SimpleDocTemplate(
        str(path),
        pagesize=pagesizes.A4,
        invariant=1,
        title="Synthetic sample",
        author="ShipIntel AI synthetic generator",
    ).build(flow)


def render_non_shipping(rng: random.Random) -> list:
    title, lines = rng.choice(NON_SHIPPING)
    return [("title", title)] + [("para", ln) for ln in lines]


# ---------------------------------------------------------------------------
def generate(out: Path, seed: int) -> list[dict]:
    rng = random.Random(seed)
    samples, ann_dir = out / "samples", out / "annotations"
    for d in (samples, ann_dir):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*"):
            if old.suffix in {".txt", ".pdf", ".jsonl"}:
                old.unlink()
    for name, *_ in UNKNOWN_PORTS:
        assert lookup_port(name) is None, f"{name} unexpectedly in gazetteer"
    for name, _c, _code in KNOWN_PORTS:
        assert lookup_port(name), f"{name} missing from gazetteer"

    records: list[dict] = []
    counter = 0
    for split, templates in (("dev", DEV_TEMPLATES), ("test", TEST_TEMPLATES)):
        for tname in templates:
            cfg = TEMPLATES[tname]
            for idx in range(DOCS_PER_TEMPLATE[split]):
                counter += 1
                doc_id = f"SI-{counter:04d}"
                kind = KIND_SCHEDULE.get(idx, "normal")
                if kind == "non_shipping" and rng.random() < 0.5 and split == "dev":
                    kind = "normal"
                use_pdf = rng.random() < 0.35
                if kind == "non_shipping":
                    items, truth, warns = render_non_shipping(rng), dict.fromkeys(FIELD_NAMES), []
                    style_txt, style_pdf = "colon", "lines"
                else:
                    sc = make_scenario(rng, kind)
                    S, truth, warns = surfaces(rng, sc, cfg["roles"], typo_p=0.04)
                    items = cfg["fn"](rng, sc, S)
                    style_txt, style_pdf = rng.choice(cfg["txt"]), rng.choice(cfg["pdf"])
                if use_pdf:
                    fname = f"{doc_id}.pdf"
                    render_pdf(items, style_pdf, samples / fname)
                else:
                    fname = f"{doc_id}.txt"
                    (samples / fname).write_text(
                        render_txt(items, style_txt, rng), encoding="utf-8"
                    )
                records.append(
                    {
                        "document_id": doc_id,
                        "file": fname,
                        "split": split,
                        "template": tname,
                        "synthetic": True,
                        "kind": kind,
                        "expected": truth,
                        "expected_warnings": warns,
                    }
                )
    for split in ("dev", "test"):
        with (ann_dir / f"{split}.jsonl").open("w", encoding="utf-8") as fh:
            for rec in records:
                if rec["split"] == split:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return records


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=ROOT / "data")
    args = ap.parse_args()
    recs = generate(args.out, args.seed)
    by = {}
    for r in recs:
        by.setdefault((r["split"], r["kind"]), 0)
        by[(r["split"], r["kind"])] += 1
    print(f"Generated {len(recs)} synthetic documents in {args.out}/samples (seed={args.seed})")
    for (split, kind), n in sorted(by.items()):
        print(f"  {split:5} {kind:15} {n}")


if __name__ == "__main__":
    main()
