"""Score a built rule set against an answer key (docs/evals/ruleset_l1_l4.md).

    python tools/eval_ruleset.py --ruleset draft.json --key test/data/synthetic_tender_nodes/ruleset_key.json
    python tools/eval_ruleset.py --api http://localhost:8010 --project <pid> --key <key> [--out report.json]

The rule set is a RuleSet JSON file, or the project's current one from the API. The keys
for the real tenders live outside git; only the synthetic key is in the repository."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rulesets.evaluate import score, table  # noqa: E402
from app.rulesets.schema import RuleSet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ruleset", type=Path, help="a RuleSet JSON file")
    parser.add_argument("--api", help="or the API base, with --project")
    parser.add_argument("--project")
    parser.add_argument("--key-header", dest="api_key", default=None, help="X-API-Key, when the API requires one")
    parser.add_argument("--key", type=Path, required=True, help="the answer key JSON")
    parser.add_argument("--version", type=int, help="a rule-set version instead of the current one")
    parser.add_argument("--out", type=Path, help="write the full result as JSON")
    args = parser.parse_args()
    if args.ruleset:
        spec = json.loads(args.ruleset.read_text())
    elif args.api and args.project:
        import requests

        headers = {"X-API-Key": args.api_key} if args.api_key else {}
        params = {"version": args.version} if args.version else {}
        r = requests.get(f"{args.api.rstrip('/')}/projects/{args.project}/ruleset", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        spec = r.json()
    else:
        parser.error("give --ruleset, or --api with --project")
    result = score(RuleSet.model_validate(spec), json.loads(args.key.read_text()))
    print(f"rule set v{result['version']} ({result['model'] or 'model unknown'}, {result['prompt_version'] or '-'})\n")
    print(table(result))
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
        print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
