"""Score an evaluation.json against a case's ground_truth.json — agreement, not eyeballing.

    python tools/score_case.py --truth demo_case_stress/ground_truth.json \
        --evaluation data/projects/<id>/work/evaluation.json

Checks per bidder: Stage I verdict (certificate present?), Stage II verdict (shelf
life >= 12 months), arithmetic-error flag, unit price (to the cent). Works for the
N-bidder case and the --buried case (which has no arithmetic errors and no shelf-life
breaches; those checks are skipped when the truth lacks the field).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def score(evaluation: dict, truth: dict) -> dict:
    s1 = {r["tenderer"]: r for r in evaluation["stage1"]}
    s2 = {r["tenderer"]: r for r in evaluation["stage2"]}
    price = {r["tenderer"]: r for r in evaluation["price_rows"]}
    checks: dict[str, list] = {"stage1": [], "stage2": [], "arithmetic": [], "unit_price": []}
    for name, t in sorted(truth.items()):
        if name not in s1:
            for k in checks:
                checks[k].append((name, False, "missing from evaluation"))
            continue
        checks["stage1"].append((name, s1[name]["passed"] == t["certificate"],
                                 f"passed={s1[name]['passed']} truth cert={t['certificate']}"))
        if "shelf_life_months" in t and "arithmetic_error" in t:
            want = t["shelf_life_months"] >= 12
            if name in s2:      # Stage II is only assessed for bids that passed Stage I
                checks["stage2"].append((name, s2[name]["passed"] == want,
                                         f"passed={s2[name]['passed']} truth shelf={t['shelf_life_months']}"))
            got = price[name].get("arithmetic_ok") is False
            checks["arithmetic"].append((name, got == t["arithmetic_error"],
                                         f"flagged={got} truth={t['arithmetic_error']}"))
        got_price = price[name].get("unit_price")
        ok = got_price is not None and abs(got_price - t["unit_price"]) < 0.005
        checks["unit_price"].append((name, ok, f"got={got_price} truth={t['unit_price']}"))
    out = {}
    for k, rows in checks.items():
        if rows:
            out[k] = {"agree": sum(1 for _, ok, _ in rows if ok), "of": len(rows),
                      "disagreements": [f"{n}: {why}" for n, ok, why in rows if not ok]}
    total = sum(v["of"] for v in out.values())
    agree = sum(v["agree"] for v in out.values())
    out["overall"] = {"agree": agree, "of": total,
                      "pct": round(100 * agree / total, 1) if total else None}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--evaluation", required=True)
    args = ap.parse_args()
    result = score(json.loads(Path(args.evaluation).read_text()),
                   json.loads(Path(args.truth).read_text()))
    print(json.dumps(result, indent=2))
    return 0 if not any(v.get("disagreements") for k, v in result.items() if k != "overall") else 1


if __name__ == "__main__":
    sys.exit(main())
