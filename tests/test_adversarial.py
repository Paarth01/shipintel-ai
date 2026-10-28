"""Adversarial / performance tests: no input may cause super-linear time (audit finding S1/S2)."""

from __future__ import annotations

import importlib
import itertools
import re
import time

import pytest

from app.config import Settings
from app.pipeline import process_document

MODULES = [
    "app.extractors.rules.inline",
    "app.extractors.rules.labels",
    "app.extractors.rules.values",
    "app.normalizers",
    "app.gazetteer",
    "app.textnorm",
]
N = 6000
INPUTS = {
    "spaces": " " * N + "!",
    "kw+spaces": "ref" + " " * N + "!",
    "newlines": "ref" + "\n" * N + "!",
    "digits": "9" * N + "x",
    "digit,space": "1 " * (N // 2) + "x",
    "num,sep": "1,234" + ",234" * (N // 4) + "x",
    "dots": "A." * (N // 2) + "x",
    "capwords": "Acme " * (N // 5) + "x",
    "cap.words": "A.B. " * (N // 5) + "x",
    "colon-label": "ab: " * (N // 4),
    "lower words": "of " * (N // 3),
    "kv-spaces": "Cargo:" + " " * N + "x",
    "to/at words": "load at " * (N // 8),
    "dashes": "-" * N + "x",
    "tabs/nbsp": "load\t\u00a0" * (N // 4),
    "ranges": "1-" * (N // 2) + "x",
    "quantity words": "cargo 1 " * (N // 8),
}


def _patterns():
    out = []
    for mod_name in MODULES:
        mod = importlib.import_module(mod_name)
        out += [(f"{mod_name}.{k}", v) for k, v in vars(mod).items() if isinstance(v, re.Pattern)]
    return out


PATTERNS = _patterns()


def test_pattern_inventory_is_not_empty():
    assert len(PATTERNS) >= 25


@pytest.mark.parametrize("name,pattern", PATTERNS, ids=[n for n, _ in PATTERNS])
def test_no_regex_is_super_linear(name, pattern):
    """Each pattern must handle 6,000-char pathological inputs in well under a second.

    (Before the fix, `_REF_INLINE` took 1.3 s at N=8000 and grew 4x per doubling.)"""
    worst = 0.0
    for label, text in INPUTS.items():
        start = time.perf_counter()
        pattern.search(text)
        list(itertools.islice(pattern.finditer(text), 50))
        elapsed = time.perf_counter() - start
        worst = max(worst, elapsed)
        assert elapsed < 0.5, f"{name} took {elapsed:.2f}s on {label!r} (n={N})"


def test_regex_cost_grows_roughly_linearly():
    """Doubling the input must not quadruple the time for the two formerly quadratic patterns."""
    from app.extractors.rules.inline import _CARGO_INLINE, _REF_INLINE

    for pat, prefix in ((_REF_INLINE, "reference"), (_CARGO_INLINE, "Cargo:")):
        t = {}
        for n in (8000, 16000):
            text = prefix + " " * n + "!"
            s = time.perf_counter()
            list(pat.finditer(text))
            t[n] = max(time.perf_counter() - s, 1e-4)
        assert t[16000] < 0.25, (pat.pattern[:30], t)


PIPELINE_CASES = {
    "space flood": lambda: "reference" + " " * 20000 + "!\n",
    "cargo space flood": lambda: "Cargo:" + " " * 20000 + "x\n",
    "identical unknown labels": lambda: "Something: x\n" * 60000,
    "unique unknown labels": lambda: "".join(f"Something{i:06d}: x\n" for i in range(40000)),
    "valid label flood": lambda: "Vessel: MV ALPHA ONE\n" * 40000,
    "single huge line": lambda: "word " * 150000,
    "digit run": lambda: "Quantity: " + "9" * 500000 + " MT\n",
    "huge port value": lambda: "Port of Loading: " + "A" * 200000 + "\n",
    "huge party value": lambda: "Shipper: " + "Acme, " * 100000 + "\n",
    "date flood": lambda: "Loading Date: 12 March 2025\n" * 30000,
}


@pytest.mark.parametrize("case", sorted(PIPELINE_CASES))
def test_pathological_documents_finish_quickly(case):
    data = PIPELINE_CASES[case]().encode()
    assert len(data) < 1_000_000
    start = time.perf_counter()
    process_document("a.txt", data, settings=Settings(), include_text=False)
    assert time.perf_counter() - start < 6.0, f"{case}: {time.perf_counter() - start:.1f}s"


def test_fuzzy_label_budget_bounds_the_work():
    """With a budget of 0 no difflib lookups run at all, so label-flood cost is pure scanning."""
    data = "".join(f"Something{i:06d}: x\n" for i in range(20000)).encode()
    start = time.perf_counter()
    process_document("a.txt", data, settings=Settings(fuzzy_label_budget=0), include_text=False)
    assert time.perf_counter() - start < 3.0


def test_whitespace_runs_are_capped_in_cleaned_text():
    r = process_document("a.txt", ("Vessel:" + " " * 5000 + "MV ALPHA ONE\n").encode())
    assert " " * 4 not in r.pages[0].text and r.fields["vessel_name"].value == "ALPHA ONE"
