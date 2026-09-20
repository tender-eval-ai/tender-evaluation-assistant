"""L0 on one case folder, saved as fixtures for the rule builder: the parser's node table
and the located schedule (items as RuleSetItems, Part intros as PartSpecs).

    python tools/locate_case.py test/data/synthetic_tender --out test/data/synthetic_tender_nodes

Synthetic cases only go into git. A real tender's output stays outside the repository,
like the answer keys (write it under a folder the .gitignore covers or outside the tree)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rulesets.locate import locate, parse_tender  # noqa: E402
from app.rulesets.schema import DataClass, PartSpec  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case", type=Path, help="case folder holding tender/*.pdf")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--data-class", default="synthetic", choices=[d.value for d in DataClass])
    args = parser.parse_args()
    pdfs = sorted((args.case / "tender").glob("*.pdf"))
    pages, nodes = parse_tender(pdfs, root=args.case)
    schedule = locate(pages, nodes, data_class=DataClass(args.data_class), root=args.case)
    parts = [PartSpec(part=p.part, title=f"Part {p.part.value}", citation=p.citation, clauses=p.clauses).model_dump(mode="json")
             for p in schedule.parts]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False, indent=0) + "\n")
    (args.out / "located.json").write_text(json.dumps({
        "case": args.case.name, "data_class": args.data_class, "files": [f"tender/{p.name}" for p in pdfs],
        "items": [i.as_rule_set_item().model_dump(mode="json") for i in schedule.items],
        "unresolved": {i.letter: i.unresolved for i in schedule.items if i.unresolved},
        "parts": parts}, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(pdfs)} files, {len(pages)} pages, {len(nodes)} nodes; {len(schedule.items)} items in "
          f"{len(schedule.parts)} Parts -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
