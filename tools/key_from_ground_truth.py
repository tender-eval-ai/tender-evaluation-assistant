"""An answer key for a synthetic bid, from the generator's ground truth.

    python tools/key_from_ground_truth.py --truth test/data/synthetic_tender/ground_truth.json \
        --tenderer Tenderer_A --out key/Tenderer_A    # writes bid_key.json and pages.json

Same schema (bid-key-v1) as a key hand-written in `answer_keys/tool/keyer.py`, so
`tools/score_bid_key.py` can be run end to end on the synthetic case before it is
trusted on a real bid. The ground truth knows each item's presence and page and the
values the generator printed; it knows nothing a person would add (chop, blacked-out
fields, extras), so those stay empty. Forms come from the synthetic lettering.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.checks.forms import forms_for_letter  # noqa: E402

# Ground-truth names that differ from the form menu's.
RENAMED = {"optimal_dosage_mg_per_l": "optimal_dosage"}


def key_from_truth(truth: dict, tenderer: str) -> tuple[dict, list[dict]]:
    bid = truth["bids"][tenderer]
    items = {}
    for letter, t in sorted(bid["items"].items()):
        forms = forms_for_letter(letter)
        form = forms[0] if forms else None
        values = {RENAMED.get(k, k): v for k, v in (t.get("values") or {}).items()}
        status = ("present" if t.get("present") else "not_applicable" if t.get("not_applicable") else "absent")
        fields = {}
        if form and status == "present":
            for name in form.names:
                if name in values and name != "document":
                    fields[name] = {"value": str(values[name]), "page": t.get("page"), "redacted": False, "unsure": False}
        signed = values.get("signed")
        items[letter] = {"status": status, "form": form.id if form else "other",
                         "pages": [t["page"]] if status == "present" and t.get("page") else [],
                         "signed": "" if signed is None else ("yes" if signed else "no"),
                         "dated": "", "chop": "", "redacted": "", "fields": fields, "extra": [],
                         "note": "from the generator's ground truth"}
    file = Path(bid.get("file") or "offer.pdf").name
    pages = [{"seq": p, "file": file, "page": p} for p in range(1, bid["pages"] + 1)]
    key = {"schema": "bid-key-v1", "tender": truth.get("case"), "bid_dir": tenderer, "pages_total": bid["pages"],
           "keyed_by": "ground_truth.json", "frozen": {"at": None, "by": "generator", "sha256": "synthetic"},
           "history": [], "page_tags": {}, "items": items}
    return key, pages


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--tenderer", required=True)
    ap.add_argument("--out", type=Path, required=True, help="a folder: bid_key.json and pages.json go in it")
    args = ap.parse_args()
    key, pages = key_from_truth(json.loads(args.truth.read_text()), args.tenderer)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "bid_key.json").write_text(json.dumps(key, indent=1))
    (args.out / "pages.json").write_text(json.dumps(pages, indent=1))
    print(f"{len(key['items'])} items, {len(pages)} pages -> {args.out}")


if __name__ == "__main__":
    main()
