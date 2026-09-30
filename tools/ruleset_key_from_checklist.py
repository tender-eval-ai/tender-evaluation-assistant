"""Convert a checklist answer key into a rule-set answer key's L0 half.

    python tools/ruleset_key_from_checklist.py --checklist <private>/tender_2.json \
        --out <private>/tender_2.ruleset_key.json

`docs/evals/ruleset_l1_l4.md`: "part and page are enough to score L0 (a checklist key
can be converted)". This does exactly that conversion and no more - it writes `part`
and `page` per schedule letter, and deliberately writes no `template`, `slots` or
`checks`, because those are judgements about the rule set that a checklist key does
not contain. The evaluator counts each of those only where the key gives it, so an
L0-only key scores items_found, part_right and page_right honestly and stays silent
on the rest rather than guessing.

Also reads a deep key (`ground_truth/deep/<tender>.json`), where the Completeness
Check Schedule's items are the level-0 nodes under `CCS`, for a tender whose
checklist key was never built separately.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_CCS_ITEM = re.compile(r"^CCS:Part([A-C]):Item\(([a-z])\)$")


def from_checklist(key: dict) -> dict:
    return {item["letter"]: {"part": item["part"], "page": item["page"]}
            for item in key.get("items", [])}


def from_deep(key: dict) -> dict:
    """The schedule's own items in a deep key: `CCS:PartA:Item(a)` at level 0."""
    out = {}
    for node in key.get("nodes", []):
        m = _CCS_ITEM.match(node["node_id"])
        if m and node.get("level") == 0:
            out[m.group(2)] = {"part": m.group(1), "page": node["page"][0]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checklist", type=Path, help="a checklist key (ground_truth/<tender>.json)")
    ap.add_argument("--deep", type=Path, help="or a deep key (ground_truth/deep/<tender>.json)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if not args.checklist and not args.deep:
        ap.error("give --checklist or --deep")

    source = args.checklist or args.deep
    key = json.loads(source.read_text())
    items = from_checklist(key) if args.checklist else from_deep(key)
    if not items:
        raise SystemExit(f"no schedule items found in {source}")
    key_out = {"case": key.get("tender", source.stem),
               "source": f"L0 half, converted from {source.name} by tools/ruleset_key_from_checklist.py",
               "items": dict(sorted(items.items()))}
    args.out.write_text(json.dumps(key_out, indent=1))
    print(f"{len(items)} items -> {args.out}: {''.join(sorted(items))}")


if __name__ == "__main__":
    main()
