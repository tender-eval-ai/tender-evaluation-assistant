#!/usr/bin/env python3
"""Buried-evidence benchmark: the pipeline with the evidence-search agent OFF vs ON,
scored against the case's ground_truth.json.

  python tools/make_demo_case.py --buried --bidders 3 --out buried_case
  python tools/benchmark_buried.py --case buried_case --out output/bench --max-ocr-pages 4

Both runs share one OCR cache, so the second run only pays for the pages the agent
chooses to read. Prints a before/after table (the number quoted in the docs).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config, load_dotenv  # noqa: E402
from app.graph import run_graph  # noqa: E402


def score(out_dir: Path, truth: dict, rubric: dict) -> dict:
    cert_id = next((i["id"] for i in rubric["stage1_checklist"]
                    if "collusive" in i["item"].lower()), None)
    should, found, false_restores, first_pass_fp, price_ok, ocr_pages = 0, 0, 0, 0, 0, 0
    unclear, unclear_evidenced = 0, 0
    for name, t in truth.items():
        ext = json.loads((out_dir / "bids" / f"{name}.json").read_text())
        for c in ext["compliance"]:
            if c["complies"] == "unclear":
                unclear += 1
                unclear_evidenced += int(c["evidence"].startswith("evidence found by search"))
        cert = next((d for d in ext["documents"] if d["checklist_id"] == cert_id), {})
        present = cert.get("present", False)
        by_agent = (cert.get("note") or "").startswith("found by evidence search")
        if t["certificate"]:
            should += 1
            found += int(present)
        elif present:
            false_restores += int(by_agent)
            first_pass_fp += int(not by_agent)
        up = ext["price"].get("unit_price")
        price_ok += int(up is not None and abs(float(up) - t["unit_price"]) < 0.005)
        agent = out_dir / "agent" / f"{name}.json"
        if agent.is_file():
            ocr_pages += len(json.loads(agent.read_text())["ocr_pages"])
    return {"cert_recall": f"{found}/{should}", "false_restores": false_restores,
            "first_pass_false_positives": first_pass_fp,
            "price_extracted": f"{price_ok}/{len(truth)}",
            "unclear_with_evidence": f"{unclear_evidenced}/{unclear}",
            "agent_ocr_pages": ocr_pages}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="buried_case")
    ap.add_argument("--out", default="output/bench")
    ap.add_argument("--max-ocr-pages", type=int, default=4,
                    help="initial OCR cap per document (the agent may read more)")
    ap.add_argument("--modes", default="baseline,agent",
                    help="which runs to (re)do, e.g. 'agent' to redo only the agent run and "
                         "keep an existing baseline (its rubric and OCR cache are reused)")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    case = ROOT / args.case
    truth = json.loads((case / "ground_truth.json").read_text())
    out = ROOT / args.out
    from app.llm import LLM
    results = {}
    if (out / "results.json").is_file():
        results = json.loads((out / "results.json").read_text())       # keep modes not redone
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        cfg = Config()
        cfg.max_ocr_pages = args.max_ocr_pages
        cfg.cache_dir = out / "cache"          # shared: agent run re-uses first-pass OCR
        cfg.agent_enabled = mode == "agent"
        run_dir = out / mode
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True)
        if mode == "agent" and (out / "baseline" / "rubric.json").is_file():
            shutil.copy(out / "baseline" / "rubric.json", run_dir / "rubric.json")  # same rubric
        llm = LLM(cfg)
        t0 = time.time()
        run_graph(case / "tender", case / "bids", run_dir, cfg, llm, log=lambda *a: None)
        secs = time.time() - t0
        rubric = json.loads((run_dir / "rubric.json").read_text())
        results[mode] = {**score(run_dir, truth, rubric), "seconds": round(secs)}
        print(f"{mode:9s} {results[mode]}", flush=True)

    print("\n| run | certificate recall | agent false restores | first-pass false positives "
          "| price extracted | unclear findings w/ evidence | agent OCR pages | time |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for mode, r in results.items():
        print(f"| {mode} | {r['cert_recall']} | {r['false_restores']} | {r['first_pass_false_positives']} "
              f"| {r['price_extracted']} | {r['unclear_with_evidence']} | {r['agent_ocr_pages']} "
              f"| {r['seconds']} s |")
    (out / "results.json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
