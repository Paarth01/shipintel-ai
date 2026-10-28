#!/usr/bin/env python
"""Evaluate the OCR path on SYNTHETIC scans. Every number is computed from real Tesseract runs.

Held-out documents are rendered to images (DejaVu Sans Mono), degraded at three levels, wrapped in
image-only PDFs, and processed by the real pipeline with OCR enabled. Reported per level:
  * word error rate (WER) and character similarity of the OCR text vs the original text
  * field-level precision/recall/F1 (same definitions as scripts/evaluate.py)
  * the same documents read from text (no OCR) as an upper bound, to isolate OCR loss
  * seconds per page

LIMITS (read before quoting): these are rendered, not photographed, scans: one clean monospace font,
simulated degradation (rotation, blur, noise, JPEG, resolution loss), English, single page. They say
little about real scanner/phone-camera output, handwriting, stamps, tables or multi-column layouts.

Usage:  python scripts/evaluate_ocr.py [--docs-per-template 10] [--levels clean,mild,heavy]
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from app.config import Settings  # noqa: E402
from app.errors import ShipIntelError  # noqa: E402
from app.extractors.ocr import ocr_available  # noqa: E402
from app.pipeline import process_document  # noqa: E402
from app.schemas import FIELD_NAMES  # noqa: E402

_spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
_ev = importlib.util.module_from_spec(_spec)
sys.modules["evaluate"] = _ev
_spec.loader.exec_module(_ev)

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
]
DPI = 200
LEVELS = {
    #        rotate  blur  noise  contrast  jpeg_q  scale
    "clean": dict(rotate=0.0, blur=0.0, noise=0.0, contrast=1.0, jpeg=None, scale=1.0),
    "mild": dict(rotate=0.8, blur=0.8, noise=8.0, contrast=0.95, jpeg=70, scale=1.0),
    "heavy": dict(rotate=1.5, blur=1.4, noise=25.0, contrast=0.8, jpeg=35, scale=0.7),
}


def load_font(size: int = 24) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit("No monospace TrueType font found; install fonts-dejavu-core.")


def render(text: str, level: dict, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    font = load_font(24)
    lines = text.splitlines() or [""]
    line_h, margin = 34, 80
    width = 1654  # A4 at 200 dpi
    height = max(700, margin * 2 + line_h * len(lines))
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill=0, font=font)
        y += line_h
    if level["rotate"]:
        img = img.rotate(
            rnd.choice([-1, 1]) * level["rotate"],
            expand=True,
            fillcolor=255,
            resample=Image.BICUBIC,
        )
    if level["blur"]:
        img = img.filter(ImageFilter.GaussianBlur(level["blur"]))
    if level["contrast"] < 1.0:
        img = img.point(lambda v: int(255 - (255 - v) * level["contrast"]))
    if level["noise"]:
        px = img.load()
        sigma = level["noise"]
        w, h = img.size
        for _ in range(w * h // 6):  # sparse gaussian noise keeps this fast in pure Python
            x, y2 = rnd.randrange(w), rnd.randrange(h)
            px[x, y2] = max(0, min(255, int(px[x, y2] + rnd.gauss(0, sigma))))
    if level["scale"] < 1.0:
        w, h = img.size
        img = img.resize((int(w * level["scale"]), int(h * level["scale"])), Image.BILINEAR)
        img = img.resize((w, h), Image.BILINEAR)
    if level["jpeg"]:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=level["jpeg"])
        img = Image.open(io.BytesIO(buf.getvalue())).convert("L")
    return img


def to_scanned_pdf(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    w_pt, h_pt = img.width * 72 / DPI, img.height * 72 / DPI
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    return edit_distance(r, h) / max(1, len(r))


def char_similarity(ref: str, hyp: str) -> float:
    import difflib

    return difflib.SequenceMatcher(
        None, " ".join(ref.split()), " ".join(hyp.split()), autojunk=False
    ).ratio()


def score(records_preds: list[tuple[dict, dict]]) -> dict:
    tp = fp = fn = tn = 0
    exact = 0
    for rec, pred in records_preds:
        ok = True
        for n in FIELD_NAMES:
            exp, got = _ev.norm(rec["expected"][n]), _ev.norm(pred.get(n))
            if exp is None and got is None:
                tn += 1
            elif exp is not None and exp == got:
                tp += 1
            else:
                ok = False
                if got is not None:
                    fp += 1
                if exp is not None:
                    fn += 1
        exact += ok
    return {
        **_ev.prf(tp, fp, fn),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "doc_exact_match": _ev.safe_div(exact, len(records_preds)),
    }


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--docs-per-template", type=int, default=10)
    ap.add_argument("--levels", default="clean,mild,heavy")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = ap.parse_args()

    settings = Settings(ocr_enabled=True, ocr_dpi=DPI)
    if not ocr_available(settings):
        raise SystemExit("Tesseract (or pytesseract) is not available; see README 'Optional OCR'.")

    records = [
        r
        for r in _ev.load_split(args.split)
        if r["file"].endswith(".txt") and r["kind"] != "non_shipping"
    ]
    by_t: dict[str, list[dict]] = {}
    for r in records:
        by_t.setdefault(r["template"], []).append(r)
    chosen = [r for t in sorted(by_t) for r in by_t[t][: args.docs_per_template]]
    print(
        f"{len(chosen)} documents from {len(by_t)} templates ({args.split} split), levels: {args.levels}"
    )

    texts = {
        r["document_id"]: (ROOT / "data" / "samples" / r["file"]).read_text(encoding="utf-8")
        for r in chosen
    }
    baseline = []
    for r in chosen:
        res = process_document(
            r["file"], texts[r["document_id"]].encode(), settings=Settings(), include_text=False
        )
        baseline.append((r, res.values()))
    results = {"baseline_text_no_ocr": score(baseline), "levels": {}}

    for name in args.levels.split(","):
        level = LEVELS[name]
        preds, wers, sims, secs, failures = [], [], [], [], []
        for r in chosen:
            doc_id = r["document_id"]
            img = render(texts[doc_id], level, seed=int(doc_id.split("-")[1]))
            pdf = to_scanned_pdf(img)
            t0 = time.perf_counter()
            try:
                res = process_document(
                    f"{doc_id}.pdf", pdf, settings=settings, ocr=True, include_text=True
                )
                secs.append(time.perf_counter() - t0)
                ocr_text = "\n".join(p.text for p in res.pages)
                wers.append(wer(texts[doc_id], ocr_text))
                sims.append(char_similarity(texts[doc_id], ocr_text))
                preds.append((r, res.values()))
            except ShipIntelError as exc:
                failures.append({"document_id": doc_id, "error": exc.code})
                preds.append((r, {}))
        results["levels"][name] = {
            "documents": len(chosen),
            "failures": failures,
            "wer_mean": statistics.mean(wers) if wers else None,
            "wer_median": statistics.median(wers) if wers else None,
            "char_similarity_mean": statistics.mean(sims) if sims else None,
            "seconds_per_page_median": statistics.median(secs) if secs else None,
            **score(preds),
        }
        lv = results["levels"][name]
        print(
            f"  {name:6} WER {pct(lv['wer_mean'])}  char-sim {pct(lv['char_similarity_mean'])}  "
            f"F1 {pct(lv['f1'])} (P {pct(lv['precision'])} R {pct(lv['recall'])})  "
            f"{lv['seconds_per_page_median']:.1f}s/page  failures {len(failures)}",
            flush=True,
        )

    env = {
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "tesseract": os.popen("tesseract --version 2>&1 | head -1").read().strip(),
    }
    b = results["baseline_text_no_ocr"]
    lines = [
        f"## OCR evaluation (synthetic rendered scans, `{args.split}` split, {len(chosen)} documents)",
        "",
        f"Baseline: the same documents read from text (no OCR): **P {pct(b['precision'])} / R {pct(b['recall'])} / "
        f"F1 {pct(b['f1'])}**, all-10-fields-correct {pct(b['doc_exact_match'])}.",
        "",
        "| Level | WER (mean) | Char similarity | Precision | Recall | F1 | Docs all correct | s/page (median) | Failures |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, lv in results["levels"].items():
        lines.append(
            f"| {name} | {pct(lv['wer_mean'])} | {pct(lv['char_similarity_mean'])} | {pct(lv['precision'])} | "
            f"{pct(lv['recall'])} | {pct(lv['f1'])} | {pct(lv['doc_exact_match'])} | "
            f"{lv['seconds_per_page_median']:.1f} | {len(lv['failures'])} |"
        )
    lines += [
        "",
        f"Environment: {env['platform']}, {env['cpu_count']} CPU, Python {env['python']}, {env['tesseract']}.",
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ocr_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out_dir / "ocr_eval.json").write_text(
        json.dumps({"environment": env, "results": results}, indent=2), encoding="utf-8"
    )
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
