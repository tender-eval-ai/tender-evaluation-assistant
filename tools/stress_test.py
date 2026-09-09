"""Drive a generated case through a running backend API and measure timings.

Usage (backend must be up, e.g. `docker compose up -d`):
    python tools/make_demo_case.py --bidders 30 --out demo_case_stress
    python tools/stress_test.py --case demo_case_stress --name "stress 30"

Prints per-phase wall-clock times and the evaluation outcome summary — the numbers
that answer "does this hold up at a realistic 20-60 bidder scale?".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.score_case import score  # noqa: E402


def wait_for_job(base: str, headers: dict, pid: str, poll: float = 2.0,
                 after_ts: float = 0.0) -> tuple[dict, float]:
    """Poll until a terminal state newer than `after_ts` (guards against reading the
    previous job's leftover 'done' before the new job has written its status)."""
    start = time.time()
    last = ""
    while True:
        status = requests.get(f"{base}/projects/{pid}/status", headers=headers, timeout=30).json()
        if status.get("detail") != last:
            last = status.get("detail", "")
            print(f"  [{time.time() - start:6.1f}s] {status['state']}: {last}", flush=True)
        if status["state"] in ("done", "error", "waiting") and status.get("updated", 0) > after_ts:
            return status, time.time() - start
        time.sleep(poll)


def upload(base: str, headers: dict, path: str, pdfs: list[Path]) -> None:
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in pdfs]
    resp = requests.post(f"{base}{path}", headers=headers, files=files, timeout=120)
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--case", default="demo_case_stress",
                        help="case folder (relative to repo root) from make_demo_case.py")
    parser.add_argument("--name", default="stress test")
    parser.add_argument("--out", help="write the summary (timings, agreement, usage) to this JSON file")
    args = parser.parse_args()

    base = args.backend.rstrip("/")
    headers = {"X-API-Key": os.environ["API_KEY"]} if os.environ.get("API_KEY") else {}
    case = ROOT / args.case
    bidders = sorted(d for d in (case / "bids").iterdir() if d.is_dir())
    print(f"Case: {case.name} — {len(bidders)} bidders, backend {base}")

    health = requests.get(f"{base}/health", timeout=10).json()
    print(f"Backend models: text={health['text_model']} vision={health['vision_model']}")

    t_start = time.time()
    pid = requests.post(f"{base}/projects", json={"name": args.name, "synthetic": True},
                        headers=headers, timeout=30).json()["id"]
    upload(base, headers, f"/projects/{pid}/tender", sorted((case / "tender").glob("*.pdf")))
    for bidder in bidders:
        upload(base, headers, f"/projects/{pid}/bids/{bidder.name}", sorted(bidder.glob("*.pdf")))
    t_upload = time.time() - t_start
    print(f"\nUploads done in {t_upload:.1f}s. Deriving rubric ...")

    # Orchestrated run: pauses at the rubric checkpoint, is resumed unedited, pauses
    # again at the extraction review, is resumed again -> evaluation + reports.
    mark = time.time()
    requests.post(f"{base}/projects/{pid}/run", headers=headers, timeout=30).raise_for_status()
    status, t_rubric = wait_for_job(base, headers, pid, after_ts=mark)
    if status["state"] != "waiting":
        print(f"RUBRIC FAILED: {status['detail']}")
        return 1

    print(f"Rubric derived in {t_rubric:.1f}s (paused for confirmation — auto-confirming). "
          f"Extracting {len(bidders)} bids in parallel ...")
    mark = time.time()
    requests.post(f"{base}/projects/{pid}/resume", json={}, headers=headers, timeout=30).raise_for_status()
    status, t_extract = wait_for_job(base, headers, pid, after_ts=mark)
    if status["state"] != "waiting":
        print(f"EXTRACTION FAILED: {status['detail']}")
        return 1

    print(f"Extraction done in {t_extract:.1f}s (paused for review — auto-confirming) ...")
    mark = time.time()
    requests.post(f"{base}/projects/{pid}/resume", json={}, headers=headers, timeout=30).raise_for_status()
    status, t_final = wait_for_job(base, headers, pid, after_ts=mark)
    if status["state"] == "error":
        print(f"EVALUATION FAILED: {status['detail']}")
        return 1
    t_eval = t_extract + t_final

    ev = requests.get(f"{base}/projects/{pid}/evaluation", headers=headers, timeout=30).json()
    s1_pass = sum(r["passed"] for r in ev["stage1"])
    s2_pass = sum(r["passed"] for r in ev["stage2"])
    arith = [r["tenderer"] for r in ev["price_rows"] if r.get("arithmetic_ok") is False]

    print("\n===== STRESS TEST SUMMARY =====")
    print(f"Project:            {pid}")
    print(f"Bidders:            {len(bidders)}")
    print(f"Upload time:        {t_upload:8.1f}s")
    print(f"Rubric derivation:  {t_rubric:8.1f}s")
    print(f"Bid extraction+eval:{t_eval:8.1f}s  "
          f"(~{t_eval / max(1, len(bidders)):.1f}s per bidder incl. rate-limit waits)")
    print(f"Total wall clock:   {time.time() - t_start:8.1f}s")
    print(f"Stage I:            {s1_pass}/{len(ev['stage1'])} passed")
    print(f"Stage II:           {s2_pass}/{len(ev['stage2'])} passed")
    print(f"Arithmetic errors:  {', '.join(arith) or 'none'}")
    print(f"Recommended:        {ev.get('recommended')}")
    print(f"Reports:            {requests.get(f'{base}/projects/{pid}/reports', headers=headers, timeout=30).json()}")

    agreement = None
    if (case / "ground_truth.json").is_file():
        agreement = score(ev, json.loads((case / "ground_truth.json").read_text()))
        o = agreement["overall"]
        print(f"Agreement:          {o['agree']}/{o['of']} checks ({o['pct']}%)")
        for k, v in agreement.items():
            if k != "overall" and v["disagreements"]:
                print(f"  {k}: {v['disagreements']}")
    usage = requests.get(f"{base}/projects/{pid}/usage", headers=headers, timeout=30)
    usage = usage.json() if usage.status_code == 200 else None
    if usage:
        print(f"Model cost:         ${usage['usd_total']} total, ${usage['usd_per_bid_mean']} mean / "
              f"${usage['usd_per_bid_median']} median per bid; {usage['tokens_per_bid']} tokens and "
              f"{usage['calls_per_bid']} calls per bid; median model time per bid "
              f"{usage['model_seconds_per_bid_median']} s; failed calls {usage['failed_calls']}")
        print(f"Models served:      {usage['models']}")
    if args.out:
        Path(args.out).write_text(json.dumps({
            "project": pid, "case": case.name, "bidders": len(bidders),
            "models": {"text": health["text_model"], "vision": health["vision_model"]},
            "seconds": {"upload": round(t_upload, 1), "rubric": round(t_rubric, 1),
                        "extract": round(t_extract, 1), "evaluate": round(t_final, 1),
                        "total": round(time.time() - t_start, 1)},
            "stage1_passed": s1_pass, "stage2_passed": s2_pass, "arithmetic_errors": arith,
            "recommended": ev.get("recommended"), "agreement": agreement, "usage": usage,
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
