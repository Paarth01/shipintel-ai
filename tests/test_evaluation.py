from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ev = _load("evaluate")
gen = _load("generate_synthetic_data")
HAVE_DATA = (ROOT / "data" / "annotations" / "dev.jsonl").exists()


def test_norm_rules():
    assert ev.norm("  Port   HEDLAND ") == "port hedland"
    assert ev.norm(45000) == ev.norm(45000.0) and ev.norm(None) is None


def test_prf_handles_zero_division_and_basic_values():
    assert ev.prf(0, 0, 0) == {"precision": None, "recall": None, "f1": None}
    r = ev.prf(8, 2, 8)
    assert r["precision"] == pytest.approx(0.8) and r["recall"] == pytest.approx(0.5)
    assert r["f1"] == pytest.approx(2 * 0.8 * 0.5 / 1.3)


@pytest.mark.skipif(not HAVE_DATA, reason="no sample data")
def test_cell_counts_are_consistent_and_perfect_prediction_scores_one(monkeypatch):
    recs = ev.load_split("dev")[:6]

    # Oracle: pretend the pipeline returns exactly the ground truth -> every metric must be perfect.
    class FakeField:
        def __init__(self, v):
            self.value, self.status = v, type("S", (), {"value": "extracted"})()

    class FakeResult:
        def __init__(self, truth):
            self.fields = {k: FakeField(v) for k, v in truth.items()}
            self.metadata = type("M", (), {"processing_ms": 1.0})()

        def all_warnings(self):
            return []

    truth_by_file = {r["file"]: r["expected"] for r in recs}
    monkeypatch.setattr(
        ev, "process_document", lambda fname, *a, **k: FakeResult(truth_by_file[fname])
    )
    m = ev.run_split(recs, use_nlp=False)
    cells = m["micro"]["tp"] + m["micro"]["fp"] + m["micro"]["fn"] + m["micro"]["tn"]
    assert cells == 10 * len(recs)
    assert m["micro"]["fp"] == 0 and m["micro"]["fn"] == 0 and m["document_exact_match"] == 1.0


@pytest.mark.skipif(not HAVE_DATA, reason="no sample data")
def test_wrong_value_counts_as_fp_and_fn(monkeypatch):
    recs = [r for r in ev.load_split("dev") if r["expected"]["vessel_name"]][:1]

    class F:
        def __init__(self, v):
            self.value, self.status = v, type("S", (), {"value": "extracted"})()

    class R:
        fields = {n: F(None) for n in ev.FIELD_NAMES} | {"vessel_name": F("WRONG NAME")}
        metadata = type("M", (), {"processing_ms": 1.0})()

        def all_warnings(self):
            return []

    monkeypatch.setattr(ev, "process_document", lambda *a, **k: R())
    m = ev.run_split(recs, use_nlp=False)
    pf = m["per_field"]["vessel_name"]
    assert (pf["tp"], pf["fp"], pf["fn"]) == (0, 1, 1)


@pytest.mark.skipif(not HAVE_DATA, reason="no sample data")
def test_dev_split_regression_guard():
    """Guards against pipeline breakage. NOT a performance claim: dev is the tuning split."""
    m = ev.run_split(ev.load_split("dev"), use_nlp=False)
    assert m["n_failures"] == 0 and m["micro"]["f1"] > 0.9


def test_generator_is_deterministic_and_labels_everything_synthetic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ra, rb = gen.generate(a, seed=7), gen.generate(b, seed=7)
    assert ra == rb and len(ra) == 150
    assert all(r["synthetic"] for r in ra)
    assert {r["split"] for r in ra} == {"dev", "test"}
    # split is by template: no template appears in both splits
    dev_t = {r["template"] for r in ra if r["split"] == "dev"}
    test_t = {r["template"] for r in ra if r["split"] == "test"}
    assert not dev_t & test_t
    for r in ra[:10]:
        if r["file"].endswith(".txt"):
            assert "SYNTHETIC" in (a / "samples" / r["file"]).read_text()
        assert set(r["expected"]) == set(ev.FIELD_NAMES)
    lines = (a / "annotations" / "dev.jsonl").read_text().splitlines()
    assert all(json.loads(line)["split"] == "dev" for line in lines)


def test_fabrication_guard_every_expected_value_is_in_the_document_text():
    """Ground truth must be derivable from the document (except normalised forms) - spot check."""
    if not HAVE_DATA:
        pytest.skip("no sample data")
    for r in ev.load_split("all"):
        if not r["file"].endswith(".txt") or r["kind"] == "non_shipping":
            continue
        text = (ROOT / "data" / "samples" / r["file"]).read_text().casefold()
        for name in ("vessel_name", "document_reference"):
            if r["expected"][name]:
                assert r["expected"][name].casefold().split()[0] in text, (r["document_id"], name)
