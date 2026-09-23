"""Build a rule set's L0 layer for one tender and write it as a RuleSet.

    python tools/build_l0_ruleset.py --pdfs <tender folder> --data-class redacted_sample --out draft.json

L0 is `locate`: the Completeness Check Schedule's Parts and items, each with its
citation and the clauses its row points at. It is deterministic - the parser and a
regex scan, no model call - so it runs offline and costs nothing, which is what lets
the L0 half of the S3 joint check be measured before the template library exists.

The result is a real RuleSet with every item at `needs_input` (located, no rules yet),
so `tools/eval_ruleset.py` scores items_found, part_right and page_right against the
answer key. template_right, slots_right and checks_recall stay silent: the key does
not claim them for an L0 key, and L1 to L4 have not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rulesets.build import merge_parts  # noqa: E402
from app.rulesets.locate import locate, parse_tender  # noqa: E402
from app.rulesets.schema import DataClass, PartSpec, RuleSet  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdfs", type=Path, required=True, help="a folder of tender PDFs, or one combined PDF")
    ap.add_argument("--out", type=Path, required=True)
    # Required, with no default: the LLM gateway trusts this label to decide which
    # endpoints may see the text, so a real tender must never come out `synthetic`.
    ap.add_argument("--data-class", required=True, choices=[d.value for d in DataClass],
                    help="redacted_sample for the camp's tenders; synthetic only for generated fixtures")
    args = ap.parse_args()

    pdfs = sorted(args.pdfs.glob("*.pdf")) if args.pdfs.is_dir() else [args.pdfs]
    if not pdfs:
        raise SystemExit(f"no PDFs under {args.pdfs}")
    pages, nodes = parse_tender(pdfs, root=args.pdfs if args.pdfs.is_dir() else args.pdfs.parent)
    schedule = locate(pages, nodes, data_class=DataClass(args.data_class),
                      root=args.pdfs if args.pdfs.is_dir() else args.pdfs.parent)
    if not schedule.items:
        raise SystemExit("no Completeness Check Schedule found")

    ruleset = RuleSet(
        project_id=args.pdfs.name,
        version=1,
        status="draft",
        data_class=DataClass(args.data_class),
        created_by="tools/build_l0_ruleset.py",
        created_at=dt.datetime.now(dt.UTC),
        # A Part the schedule states in more than one place is one Part, merged the way
        # the ruleset_build job merges it; a RuleSet refuses a Part listed twice.
        parts=merge_parts([PartSpec(part=p.part, title=f"Part {p.part.value}", citation=p.citation, clauses=p.clauses)
                           for p in schedule.parts]),
        items=[i.as_rule_set_item() for i in schedule.items],
    )
    args.out.write_text(ruleset.model_dump_json(indent=1))
    letters = "".join(i.letter for i in ruleset.items)
    print(f"{len(ruleset.items)} items ({letters}) in {len(ruleset.parts)} parts -> {args.out}")


if __name__ == "__main__":
    main()
