"""Score the bid checker against a frozen answer key: the S4 measure on real bids.

    python tools/score_bid_key.py --key <case>/bid_key.json --result result.json \
        [--pages <case>/pages.json] [--out score.json] [--details]

`result.json` is the checker's BidResult for one tenderer (GET /projects/{pid}/bids/
{tenderer}/results). The key is the one `answer_keys/tool/keyer.py` writes (schema
bid-key-v1): facts per schedule item, not verdicts. So this scores what the checker
READ, item by item:

- presence  the item is in the bid or not, as the key says (items the key calls not
            applicable or unsure are not scored);
- pages     the pages the checker cited for the item overlap the key's (hit) and all
            lie inside them (within);
- values    each field the key gives a value for, compared as a number when both sides
            read as one (0.5% tolerance, "1. 3" reads as 1.3), as a date when both parse,
            by presence for a signature, and otherwise by V4's `agree`;
- invented  a value the checker reports where the key says the field is blank or
            blacked out: the error the verification layer exists to stop;
- verification  where each scored value went: accepted (V4 verified it), flagged (V4
            could not, so a reviewer sees it) or not checkable, and how many of each were
            wrong. A wrong value V4 accepted is the error that reaches a verdict unseen.

An item the key found but no form of the checker's menu reads (form "other", or no
fields for the letter) is counted as not covered, not as a miss: it measures the menu.

Only numbers are printed. --details also prints the disagreeing values, which come from
the bid: run it on this machine only, and never paste its output into the repository.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.checks.engine_bridge import parse_date  # noqa: E402
from app.checks.forms import FORMS  # noqa: E402
from app.checks.verify import agree  # noqa: E402

SCORED = ("present", "absent")
VERIFICATION = ("accepted", "accepted_wrong", "flagged", "flagged_wrong", "unchecked", "unchecked_wrong")
TOLERANCE = 0.005


def _number(value) -> float | None:
    """A value as a number, if it reads as one: "24.60", "1. 3", "27,109,200.00", 4.4."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"(?<=\d)[\s,](?=\d)|(?<=\d\.)\s+(?=\d)", "", str(value).strip())
    m = re.fullmatch(r"[^\d-]{0,4}(-?\d+(?:\.\d+)?)\s*%?", text)
    return float(m.group(1)) if m else None


def same_value(expected, got, kind: str = "text") -> bool:
    if kind == "signature":
        return bool(expected) == bool(got)
    a, b = _number(expected), _number(got)
    if a is not None and b is not None:
        return abs(a - b) <= TOLERANCE * max(abs(a), abs(b), 1e-9)
    if kind == "date":
        da, db = parse_date(str(expected)), parse_date(str(got))
        if da and db:
            return da == db
    return agree(expected, got)


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def load_pages(path: Path | None) -> dict[int, tuple[str, int]] | None:
    """seq -> (file name, page in that file), from prepare.py's pages.json."""
    if path is None or not path.is_file():
        return None
    return {p["seq"]: (PurePosixPath(p["file"]).name, p["page"]) for p in json.loads(path.read_text())}


def checker_item(fields: dict | None) -> dict:
    """What the checker reported for one letter: present (None when no form read it),
    the pages it cited, and each field's value."""
    if not fields:
        return {"covered": False, "present": None, "pages": set(), "values": {}, "verified": {}}
    document = fields.get("document") or {}
    present = not _blank(document.get("value")) or bool(document.get("redacted"))
    pages = {(PurePosixPath(v["page"]["file"]).name, v["page"]["page"]) for v in fields.values() if v.get("page")}
    return {"covered": True, "present": present, "pages": pages,
            "values": {n: (v.get("value"), bool(v.get("redacted"))) for n, v in fields.items() if n != "document"},
            "verified": {n: (v.get("verification") or {}).get("verified") for n, v in fields.items() if n != "document"}}


def _kinds(form_id: str) -> dict[str, str]:
    form = FORMS.get(form_id)
    return {f.name: f.kind for f in form.all_fields} if form else {}


def score_item(letter: str, item: dict, got: dict, pages: dict | None) -> dict:
    row = {"letter": letter, "key": item.get("status") or "", "form": item.get("form") or "",
           "checker": None if not got["covered"] else ("present" if got["present"] else "absent"),
           "scored": item.get("status") in SCORED, "covered": got["covered"] and item.get("form") != "other",
           "presence_ok": None, "page_hit": None, "page_within": None,
           "values": {"compared": 0, "match": 0, "missed": 0, "mismatch": 0, "invented": 0},
           "extras": len([x for x in item.get("extra", []) if not _blank(x.get("value"))]), "disagreements": [],
           "verification": dict.fromkeys(VERIFICATION, 0)}
    if not row["scored"] or not row["covered"]:
        return row
    row["presence_ok"] = (item["status"] == "present") == bool(got["present"])
    if item["status"] != "present" or not got["present"]:
        return row

    key_pages = {pages[s] if pages and s in pages else (None, s) for s in item.get("pages", [])}
    cited = got["pages"] if pages else {(None, p) for _, p in got["pages"]}
    if cited:
        row["page_hit"] = bool(cited & key_pages)
        row["page_within"] = cited <= key_pages

    kinds = _kinds(item.get("form", ""))
    v = row["values"]

    def went(name: str, right: bool) -> None:
        verified = got["verified"].get(name)
        where = "accepted" if verified is True else "flagged" if verified is False else "unchecked"
        row["verification"][where] += 1
        row["verification"][f"{where}_wrong"] += not right

    # A signature is scored from the key's item-level `signed` flag (yes / no; unclear and
    # n/a are not scored), whatever the key wrote in the field, which describes the mark.
    signed = {"yes": True, "no": False}.get(item.get("signed", ""))
    for name, kind in kinds.items():
        if kind != "signature" or signed is None or name not in got["values"]:
            continue
        got_value, got_redacted = got["values"][name]
        v["compared"] += 1
        right = same_value(signed, not _blank(got_value) or got_redacted, "signature")
        went(name, right)
        if right:
            v["match"] += 1
        else:
            v["mismatch"] += 1
            row["disagreements"].append((name, "signed" if signed else "unsigned", got_value))
    for name, field in (item.get("fields") or {}).items():
        kind = kinds.get(name, "text")
        if kind == "signature" or field.get("unsure") or name not in got["values"]:
            continue
        got_value, got_redacted = got["values"][name]
        if field.get("redacted") or _blank(field.get("value")):
            if not field.get("redacted") and field.get("page") is None:
                continue                                     # nothing recorded: not an answer
            if not _blank(got_value) and not got_redacted:
                v["invented"] += 1
                went(name, False)
                row["disagreements"].append((name, "[blacked out]" if field.get("redacted") else "[blank]", got_value))
            continue
        v["compared"] += 1
        right = not _blank(got_value) and same_value(field["value"], got_value, kind)
        went(name, right)
        if _blank(got_value):
            v["missed"] += 1
            row["disagreements"].append((name, field["value"], None))
        elif right:
            v["match"] += 1
        else:
            v["mismatch"] += 1
            row["disagreements"].append((name, field["value"], got_value))
    return row


def score(key: dict, result: dict, pages: dict | None = None) -> dict:
    rows = [score_item(letter, item, checker_item(result.get("fields", {}).get(letter)), pages)
            for letter, item in sorted(key["items"].items())]
    scored = [r for r in rows if r["scored"]]
    covered = [r for r in scored if r["covered"]]
    both = [r for r in covered if r["page_hit"] is not None]
    total = {k: sum(r["values"][k] for r in rows) for k in ("compared", "match", "missed", "mismatch", "invented")}
    verification = {k: sum(r["verification"][k] for r in rows) for k in VERIFICATION}
    rate = lambda n, d: round(n / d, 3) if d else None      # noqa: E731
    return {
        "tender": key.get("tender"), "tenderer": result.get("tenderer"), "key_frozen": (key.get("frozen") or {}).get("sha256"),
        "items": len(rows), "items_scored": len(scored), "not_covered": len(scored) - len(covered),
        "presence_correct": sum(bool(r["presence_ok"]) for r in covered), "presence_scored": len(covered),
        "presence_accuracy": rate(sum(bool(r["presence_ok"]) for r in covered), len(covered)),
        "page_hit": sum(r["page_hit"] for r in both), "page_within": sum(r["page_within"] for r in both), "page_scored": len(both),
        "values": total, "value_accuracy": rate(total["match"], total["compared"]),
        "verification": verification,
        "accepted_precision": rate(verification["accepted"] - verification["accepted_wrong"], verification["accepted"]),
        "extras_outside_menu": sum(r["extras"] for r in rows),
        "rows": rows,
    }


def format_score(s: dict, details: bool = False) -> str:
    v, c = s["values"], s["verification"]
    lines = [f"{s['tender']} / {s['tenderer']}  (key {str(s['key_frozen'])[:10] if s['key_frozen'] else 'NOT FROZEN'})",
             f"  items            {s['items_scored']} scored of {s['items']}; {s['not_covered']} not covered by the form menu",
             f"  presence         {s['presence_correct']}/{s['presence_scored']}",
             f"  pages            hit {s['page_hit']}/{s['page_scored']}, within {s['page_within']}/{s['page_scored']}",
             f"  values           {v['match']}/{v['compared']} match; {v['missed']} missed, {v['mismatch']} wrong",
             f"  invented         {v['invented']}",
             f"  verification     {c['accepted']} accepted by V4, {c['accepted_wrong']} of them wrong; "
             f"{c['flagged']} flagged for a reviewer, {c['flagged_wrong']} wrong; "
             f"{c['unchecked']} not checkable, {c['unchecked_wrong']} wrong",
             f"  outside the menu {s['extras_outside_menu']} key values no form reads",
             "", "  item  key            checker   presence  pages       values"]
    for r in s["rows"]:
        pres = "-" if r["presence_ok"] is None else ("ok" if r["presence_ok"] else "WRONG")
        pages = "-" if r["page_hit"] is None else f"{'hit' if r['page_hit'] else 'MISS'}/{'in' if r['page_within'] else 'OUT'}"
        vals = f"{r['values']['match']}/{r['values']['compared']}" + (f" +{r['values']['invented']} invented" if r["values"]["invented"] else "")
        cover = "" if r["covered"] or not r["scored"] else "  (not covered)"
        lines.append(f"  ({r['letter']})  {r['key']:<14} {str(r['checker']):<9} {pres:<9} {pages:<11} {vals}{cover}")
        if details:
            lines += [f"        {name}: key {exp!r}  checker {got!r}" for name, exp, got in r["disagreements"]]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", type=Path, required=True)
    ap.add_argument("--result", type=Path, required=True, help="the checker's BidResult as JSON")
    ap.add_argument("--pages", type=Path, help="prepare.py's pages.json; default: beside the key")
    ap.add_argument("--out", type=Path, help="write the score as JSON (numbers only)")
    ap.add_argument("--details", action="store_true", help="also print disagreeing values (local use only)")
    args = ap.parse_args()
    key = json.loads(args.key.read_text())
    if not key.get("frozen"):
        print("warning: the key is not frozen; a score against it can change", file=sys.stderr)
    s = score(key, json.loads(args.result.read_text()), load_pages(args.pages or args.key.parent / "pages.json"))
    print(format_score(s, args.details))
    if args.out:
        numbers = {k: v for k, v in s.items() if k != "rows"}
        numbers["rows"] = [{k: v for k, v in r.items() if k != "disagreements"} for r in s["rows"]]
        args.out.write_text(json.dumps(numbers, indent=1))


if __name__ == "__main__":
    main()
