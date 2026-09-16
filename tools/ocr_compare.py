"""Compare two vision chains' OCR of the same scanned pages — quality, time, cost.

    python tools/ocr_compare.py --case buried_case \\
        --a "qwen3-vl:8b@http://localhost:11434/v1" \\
        --b "google/gemini-2.5-flash@https://us-central1-aiplatform.googleapis.com/v1/projects/<p>/locations/us-central1/endpoints/openapi"

For every page of every offer in the case, both chains transcribe the rendered page
(separate caches under --out, so nothing is shared), and the report gives: text
similarity between the two transcripts (difflib ratio on normalised text), whether
each transcript contains the page's ground-truth facts where the case defines them
(unit price, quoted total, certificate line, delivery days, shelf life), and per-chain
seconds and $ per page. Synthetic cases only: page images go to whichever endpoint the
chain names.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config, load_dotenv  # noqa: E402
from app.ingest import ocr_single_page  # noqa: E402
from pypdf import PdfReader  # noqa: E402


def _norm(t: str) -> str:
    t = re.sub(r"(?<=\d),(?=\d)", "", t)          # 518,500.00 == 518500.00
    return re.sub(r"[^a-z0-9.]+", " ", t.lower()).strip()


def facts_for(truth: dict | None) -> list[tuple[str, str]]:
    """(label, needle) pairs that must appear somewhere in the offer's transcript."""
    if not truth:
        return []
    out = []
    if "unit_price" in truth:
        out.append(("unit price", f"{truth['unit_price']:.2f}"))
    if "quoted_total" in truth:
        out.append(("quoted total", f"{truth['quoted_total']:,.2f}".replace(",", "")))
    if truth.get("certificate"):
        out.append(("certificate", "non-collusive tendering certificate"))
    if "delivery_days" in truth:
        out.append(("delivery days", f"{truth['delivery_days']} days"))
    if "shelf_life_months" in truth:
        out.append(("shelf life", f"{truth['shelf_life_months']} months"))
    return out


def run_chain(label: str, entry: str, pdfs: list[Path], out: Path) -> dict:
    from app.llm import LLM
    cfg = Config()
    cfg.vision_model, cfg.vision_fallbacks = entry, []
    cfg.cache_dir = out / "cache" / label
    llm = LLM(cfg)
    pages: dict[str, dict[int, str]] = {}
    t0 = time.time()
    for pdf in pdfs:
        n = len(PdfReader(str(pdf)).pages)
        pages[pdf.parent.name] = {}
        for i in range(n):
            t1 = time.time()
            text = ocr_single_page(pdf, i, cfg, llm)
            pages[pdf.parent.name][i + 1] = text
            print(f"  [{label}] {pdf.parent.name} p.{i + 1}: {len(text)} chars, {time.time() - t1:.1f}s",
                  file=sys.stderr, flush=True)
    snap = llm.usage.snapshot()
    return {"entry": entry, "pages": pages, "seconds": round(time.time() - t0, 1),
            "usage": snap["totals"], "served": {k: v["served"] for k, v in snap["models"].items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="buried_case")
    ap.add_argument("--a", help="vision chain entry A (model[@base_url])")
    ap.add_argument("--b", help="vision chain entry B")
    ap.add_argument("--out", default="output/ocr_compare")
    ap.add_argument("--bidders", type=int, default=0, help="limit to the first N bidders (0 = all)")
    ap.add_argument("--rescore", action="store_true",
                    help="re-score from <out>/transcripts.json + report.json without calling any model")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")

    case = ROOT / args.case
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    truth = json.loads((case / "ground_truth.json").read_text()) if (case / "ground_truth.json").is_file() else {}

    if args.rescore:
        prev = json.loads((out / "report.json").read_text())
        pages = json.loads((out / "transcripts.json").read_text())
        res = {k: {"entry": prev["chains"][k]["entry"], "pages": pages[k], "seconds": prev["chains"][k]["seconds"],
                   "usage": {"usd": prev["chains"][k]["usd"], "prompt_tokens": prev["chains"][k]["tokens"],
                             "output_tokens": 0, "failed": prev["chains"][k]["failed_calls"]},
                   "served": prev["chains"][k]["served"]} for k in ("a", "b")}
        n_pages = prev["pages"]
    else:
        bidders = sorted(d for d in (case / "bids").iterdir() if d.is_dir())
        if args.bidders:
            bidders = bidders[:args.bidders]
        pdfs = [p for b in bidders for p in sorted(b.glob("*.pdf"))]
        n_pages = sum(len(PdfReader(str(p)).pages) for p in pdfs)
        print(f"{len(pdfs)} offer(s), {n_pages} pages; A={args.a}  B={args.b}", file=sys.stderr)
        res = {"a": run_chain("a", args.a, pdfs, out), "b": run_chain("b", args.b, pdfs, out)}

    sims, fact_rows = [], []
    empty = {k: [f"{n} p.{p}" for n, pg in res[k]["pages"].items() for p, t in pg.items() if not _norm(t)]
             for k in ("a", "b")}
    for name in res["a"]["pages"]:
        for pno, ta in res["a"]["pages"][name].items():
            tb = res["b"]["pages"][name].get(pno, "")
            sims.append(difflib.SequenceMatcher(None, _norm(ta), _norm(tb)).ratio())
        joined = {k: _norm("\n".join(res[k]["pages"][name].values())) for k in ("a", "b")}
        for label, needle in facts_for(truth.get(name)):
            fact_rows.append((name, label, _norm(needle) in joined["a"], _norm(needle) in joined["b"]))
    sims.sort()
    report = {
        "case": case.name, "pages": n_pages,
        "similarity": {"mean": round(sum(sims) / len(sims), 3), "median": round(sims[len(sims) // 2], 3),
                       "min": round(sims[0], 3)},
        "facts": {"checked": len(fact_rows),
                  "a_found": sum(1 for r in fact_rows if r[2]), "b_found": sum(1 for r in fact_rows if r[3]),
                  "missed_by_a": [f"{n}: {label}" for n, label, a, b in fact_rows if not a],
                  "missed_by_b": [f"{n}: {label}" for n, label, a, b in fact_rows if not b]},
        "empty_transcripts": empty,
        "chains": {k: {"entry": v["entry"], "served": v["served"], "seconds": v["seconds"],
                       "seconds_per_page": round(v["seconds"] / n_pages, 1),
                       "usd": v["usage"]["usd"], "usd_per_page": round(v["usage"]["usd"] / n_pages, 5),
                       "tokens": v["usage"]["prompt_tokens"] + v["usage"]["output_tokens"],
                       "failed_calls": v["usage"]["failed"]} for k, v in res.items()},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    (out / "transcripts.json").write_text(json.dumps({k: v["pages"] for k, v in res.items()}, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
