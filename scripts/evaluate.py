#!/usr/bin/env python
"""Evaluate the extraction pipeline on a labelled split. Every number is computed from real runs.

Usage:
  python scripts/evaluate.py --split dev                # development set (rules were tuned on it)
  python scripts/evaluate.py --split test               # held-out templates; run it sparingly
  python scripts/evaluate.py --split test --nlp         # also compare rules vs rules+spaCy NER
  python scripts/evaluate.py --split dev --errors 30    # print more error examples

Comparison rules (documented normalisation):
  strings   case-insensitive, whitespace-collapsed exact match
  numbers   equal within 1e-6
  dates     ISO-8601 string equality
  null      expected null counts as correct only if the system also returns null
A wrong non-null prediction counts as BOTH a false positive and a false negative.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.errors import ShipIntelError  # noqa: E402
from app.pipeline import process_document  # noqa: E402
from app.schemas import FIELD_NAMES, ExtractionResult  # noqa: E402

VALIDATION_CODES = {
    "AMBIGUOUS_DATE",
    "INVALID_DATE",
    "DISCHARGE_BEFORE_LOADING",
    "SAME_PORT",
    "NONPOSITIVE_QUANTITY",
}


def norm(v):
    if v is None:
        return None
    if isinstance(v, float | int):
        return round(float(v), 6)
    return " ".join(str(v).casefold().split())


def load_split(split: str) -> list[dict]:
    splits = ["dev", "test"] if split == "all" else [split]
    recs = []
    for s in splits:
        path = ROOT / "data" / "annotations" / f"{s}.jsonl"
        recs += [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return recs


def safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def prf(tp: int, fp: int, fn: int) -> dict:
    p, r = safe_div(tp, tp + fp), safe_div(tp, tp + fn)
    f1 = safe_div(2 * p * r, p + r) if p is not None and r is not None and (p + r) else None
    return {"precision": p, "recall": r, "f1": f1}


def run_split(records: list[dict], use_nlp: bool) -> dict:
    settings = get_settings()
    cells = defaultdict(lambda: Counter())  # field -> tp/fp/fn/tn
    by_template = defaultdict(lambda: Counter())
    by_type = defaultdict(lambda: Counter())
    errors, times, failures = [], [], []
    doc_exact = 0
    flagged_wrong = Counter()
    absent_false = Counter()
    warn_hits = defaultdict(lambda: [0, 0])  # code -> [detected, expected]
    clean_docs = clean_false_alarm = 0
    nonship = [0, 0]  # all-null docs, total
    for rec in records:
        data = (ROOT / "data" / "samples" / rec["file"]).read_bytes()
        try:
            res: ExtractionResult = process_document(
                rec["file"], data, settings=settings, nlp=use_nlp, include_text=False
            )
            pred = {n: res.fields[n].value for n in FIELD_NAMES}
            status = {n: res.fields[n].status.value for n in FIELD_NAMES}
            codes = {w.code for w in res.all_warnings()}
            times.append(res.metadata.processing_ms)
        except ShipIntelError as exc:
            failures.append({"document_id": rec["document_id"], "error": exc.code})
            pred, status, codes = (
                dict.fromkeys(FIELD_NAMES),
                dict.fromkeys(FIELD_NAMES, "missing"),
                set(),
            )
        ftype = rec["file"].rsplit(".", 1)[-1]
        all_ok = True
        for n in FIELD_NAMES:
            exp, got = norm(rec["expected"][n]), norm(pred[n])
            c = cells[n]
            key = (
                "tn"
                if exp is None and got is None
                else "tp"
                if exp is not None and exp == got
                else "fp_fn"
                if exp is not None and got is not None
                else "fp"
                if got is not None
                else "fn"
            )
            for tgt in (c, by_template[rec["template"]], by_type[ftype]):
                if key == "fp_fn":
                    tgt["fp"] += 1
                    tgt["fn"] += 1
                else:
                    tgt[key] += 1
            if exp is None:
                c["absent_total"] += 1
                if got is not None:
                    absent_false[n] += 1
            if key not in ("tp", "tn"):
                all_ok = False
                if got is not None:
                    flagged_wrong["wrong_nonnull"] += 1
                    if status[n] in ("needs_review", "invalid"):
                        flagged_wrong["wrong_flagged"] += 1
                errors.append(
                    {
                        "document_id": rec["document_id"],
                        "template": rec["template"],
                        "file": rec["file"],
                        "field": n,
                        "expected": rec["expected"][n],
                        "predicted": pred[n],
                        "status": status[n],
                        "kind": rec["kind"],
                    }
                )
            elif key == "tp":
                flagged_wrong["right_total"] += 1
                if status[n] in ("needs_review", "invalid"):
                    flagged_wrong["right_flagged"] += 1
        doc_exact += all_ok
        for code in rec["expected_warnings"]:
            warn_hits[code][1] += 1
            warn_hits[code][0] += code in codes
        if not rec["expected_warnings"]:
            clean_docs += 1
            clean_false_alarm += bool(codes & VALIDATION_CODES)
        if rec["kind"] == "non_shipping":
            nonship[1] += 1
            nonship[0] += all(v is None for v in pred.values())

    per_field = {}
    tp = fp = fn = tn = 0
    for n in FIELD_NAMES:
        c = cells[n]
        per_field[n] = {
            **prf(c["tp"], c["fp"], c["fn"]),
            "tp": c["tp"],
            "fp": c["fp"],
            "fn": c["fn"],
            "tn": c["tn"],
            "exact_match_accuracy": safe_div(c["tp"] + c["tn"], len(records)),
        }
        tp, fp, fn, tn = tp + c["tp"], fp + c["fp"], fn + c["fn"], tn + c["tn"]
    f1s = [v["f1"] for v in per_field.values() if v["f1"] is not None]
    absent_total = sum(cells[n]["absent_total"] for n in FIELD_NAMES)

    def group(d):
        return {
            k: {**prf(v["tp"], v["fp"], v["fn"]), "n_cells": v["tp"] + v["fp"] + v["fn"] + v["tn"]}
            for k, v in sorted(d.items())
        }

    return {
        "n_documents": len(records),
        "n_failures": len(failures),
        "failures": failures,
        "micro": {**prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "macro_f1": statistics.mean(f1s) if f1s else None,
        "field_cell_accuracy": safe_div(tp + tn, tp + tn + fp + fn),
        "document_exact_match": safe_div(doc_exact, len(records)),
        "per_field": per_field,
        "missing_field_handling_rate": safe_div(
            absent_total - sum(absent_false.values()), absent_total
        ),
        "absent_cells": absent_total,
        "false_values_on_absent_cells": sum(absent_false.values()),
        "validation_detection": {
            k: {"detected": v[0], "expected": v[1], "rate": safe_div(v[0], v[1])}
            for k, v in sorted(warn_hits.items())
        },
        "validation_detection_overall": safe_div(
            sum(v[0] for v in warn_hits.values()), sum(v[1] for v in warn_hits.values())
        ),
        "validation_false_alarm_rate_on_clean_docs": safe_div(clean_false_alarm, clean_docs),
        "non_shipping_all_null_rate": safe_div(nonship[0], nonship[1]),
        "review_flagging": {
            "wrong_nonnull_predictions": flagged_wrong["wrong_nonnull"],
            "wrong_and_flagged": flagged_wrong["wrong_flagged"],
            "share_of_wrong_flagged": safe_div(
                flagged_wrong["wrong_flagged"], flagged_wrong["wrong_nonnull"]
            ),
            "correct_predictions": flagged_wrong["right_total"],
            "correct_but_flagged": flagged_wrong["right_flagged"],
            "share_of_correct_flagged": safe_div(
                flagged_wrong["right_flagged"], flagged_wrong["right_total"]
            ),
        },
        "by_template": group(by_template),
        "by_file_type": group(by_type),
        "timing_ms": {
            "median": statistics.median(times) if times else None,
            "mean": statistics.mean(times) if times else None,
            "max": max(times) if times else None,
            "n": len(times),
        },
        "errors": errors,
    }


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def markdown(name: str, m: dict, env: dict) -> str:
    out = [
        f"### {name}",
        "",
        f"- Documents: **{m['n_documents']}** (pipeline failures: {m['n_failures']})",
        f"- Micro P / R / F1: **{pct(m['micro']['precision'])} / {pct(m['micro']['recall'])} / {pct(m['micro']['f1'])}**; "
        f"macro-F1 {pct(m['macro_f1'])}",
        f"- Field-cell accuracy (null-aware exact match): {pct(m['field_cell_accuracy'])}; "
        f"documents with all 10 fields correct: {pct(m['document_exact_match'])}",
        f"- Missing-field handling (absent field -> null): {pct(m['missing_field_handling_rate'])} "
        f"({m['false_values_on_absent_cells']} wrong values on {m['absent_cells']} absent cells)",
        f"- Validation-error detection: {pct(m['validation_detection_overall'])}; "
        f"false alarms on documents without injected problems: {pct(m['validation_false_alarm_rate_on_clean_docs'])}",
        f"- Non-shipping documents returned all-null: {pct(m['non_shipping_all_null_rate'])}",
        f"- Of wrong non-null values, flagged needs_review/invalid: {pct(m['review_flagging']['share_of_wrong_flagged'])} "
        f"({m['review_flagging']['wrong_and_flagged']}/{m['review_flagging']['wrong_nonnull_predictions']}); "
        f"correct values that were flagged anyway: {pct(m['review_flagging']['share_of_correct_flagged'])}",
        f"- Time per document: median {m['timing_ms']['median']:.1f} ms, mean {m['timing_ms']['mean']:.1f} ms "
        f"({env['cpu_count']} CPU, {env['platform']}, Python {env['python']}, OCR off)",
        "",
        "| Field | Precision | Recall | F1 | TP | FP | FN | TN | Exact-match acc. |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for n, v in m["per_field"].items():
        out.append(
            f"| {n} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} | {v['tp']} | {v['fp']} | "
            f"{v['fn']} | {v['tn']} | {pct(v['exact_match_accuracy'])} |"
        )
    out += ["", "| Template | Precision | Recall | F1 |", "|---|---|---|---|"]
    for k, v in m["by_template"].items():
        out.append(f"| {k} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} |")
    out += ["", "| File type | Precision | Recall | F1 |", "|---|---|---|---|"]
    for k, v in m["by_file_type"].items():
        out.append(f"| {k} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} |")
    out += ["", "| Injected problem | Detected | Expected | Rate |", "|---|---|---|---|"]
    for k, v in m["validation_detection"].items():
        out.append(f"| {k} | {v['detected']} | {v['expected']} | {pct(v['rate'])} |")
    return "\n".join(out) + "\n"


def print_errors(m: dict, limit: int) -> None:
    errs = m["errors"]
    print(
        f"\n{len(errs)} field errors. By field: {dict(Counter(e['field'] for e in errs).most_common())}"
    )
    print(f"By template: {dict(Counter(e['template'] for e in errs).most_common())}")
    for e in errs[:limit]:
        print(
            f"  {e['document_id']} [{e['template']}, {e['kind']}] {e['field']}: "
            f"expected={e['expected']!r} got={e['predicted']!r} ({e['status']})"
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--nlp", action="store_true", help="also evaluate rules+spaCy and compare")
    ap.add_argument("--errors", type=int, default=15, help="number of error examples to print")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = ap.parse_args()

    records = load_split(args.split)
    env = {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }
    results = {"rules": run_split(records, use_nlp=False)}
    if args.nlp:
        from app.extractors.nlp import nlp_available

        if nlp_available(get_settings()):
            results["rules+spacy"] = run_split(records, use_nlp=True)
        else:
            print(
                "spaCy / model not available - skipping NLP comparison (see README 'Optional NLP')."
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    md = [f"## Evaluation - split `{args.split}`", ""]
    for name, m in results.items():
        md.append(markdown(f"{name} ({args.split})", m, env))
    if len(results) == 2:
        a, b = results["rules"]["micro"], results["rules+spacy"]["micro"]
        md.append(
            "### Same-split comparison\n\n| Method | Precision | Recall | F1 |\n|---|---|---|---|"
        )
        for name, mm in (("rules", a), ("rules+spacy", b)):
            md.append(
                f"| {name} | {pct(mm['precision'])} | {pct(mm['recall'])} | {pct(mm['f1'])} |"
            )
    text = "\n".join(md)
    print(text)
    print_errors(results["rules"], args.errors)
    (args.out_dir / f"eval_{args.split}.md").write_text(text, encoding="utf-8")
    (args.out_dir / f"eval_{args.split}.json").write_text(
        json.dumps(
            {"split": args.split, "environment": env, "results": results}, indent=2, default=str
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out_dir}/eval_{args.split}.md and .json")


if __name__ == "__main__":
    main()
