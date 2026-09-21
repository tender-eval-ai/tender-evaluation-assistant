"""Score a built rule set against an answer key (S3 eval, layers L0 to L4).

The key names, per schedule letter, the Part and page the item sits on, the template it
should match (null: none), the slot values the template should take, and the check kinds a
drafted rule should carry. A key may give only Part and page (the checklist keys do), in
which case the template, slot and check metrics count nothing. The numbers are recorded in
docs/evals/ruleset_l1_l4.md; the keys for the real tenders stay outside git."""
from __future__ import annotations

from app.rulesets.schema import RuleSet, RuleSetItem

UNVERIFIED = "unverified draft"


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def score_item(item: RuleSetItem | None, expected: dict) -> dict:
    row: dict = {"found": item is not None}
    if item is None:
        return row
    row["status"] = item.status.value
    row["part_ok"] = item.part.value == expected["part"]
    row["page_ok"] = (item.citation.page == expected["page"]) if expected.get("page") else None
    if "template" in expected:
        row["template_ok"] = item.template == expected["template"]
    if expected.get("slots"):
        row["slots"] = {}
        for name, value in expected["slots"].items():
            slot = item.slots.get(name)
            row["slots"][name] = {"value_ok": slot is not None and slot.value == value,
                                  "verified": bool(slot and slot.verified),
                                  "node": slot.citation.node_id if slot and slot.citation else None}
    if expected.get("checks"):
        kinds = {r.check.value for r in item.rules}
        row["checks_found"] = [c for c in expected["checks"] if c in kinds]
        row["checks_missing"] = [c for c in expected["checks"] if c not in kinds]
    row["rules"] = len(item.rules)
    row["unverified_notes"] = sum(1 for n in item.notes if n.text.startswith(UNVERIFIED))
    return row


def score(ruleset: RuleSet, key: dict) -> dict:
    """Per-item rows and the totals the eval doc records."""
    expected_items: dict[str, dict] = key["items"]
    found = {i.letter: i for i in ruleset.items}
    rows = {letter: score_item(found.get(letter), exp) for letter, exp in expected_items.items()}
    present = [r for r in rows.values() if r["found"]]
    keyed_templates = [r for r in present if "template_ok" in r]
    slots = [s for r in present for s in r.get("slots", {}).values()]
    checks_total = sum(len(exp.get("checks", [])) for exp in expected_items.values())
    checks_found = sum(len(r.get("checks_found", [])) for r in present)
    statuses: dict[str, int] = {}
    for item in ruleset.items:
        statuses[item.status.value] = statuses.get(item.status.value, 0) + 1
    n = len(expected_items)
    totals = {
        "items_found": [len(present), n],
        "part_right": [sum(1 for r in present if r["part_ok"]), n],
        "page_right": [sum(1 for r in present if r.get("page_ok")), sum(1 for e in expected_items.values() if e.get("page"))],
        "template_right": [sum(1 for r in keyed_templates if r["template_ok"]), len(keyed_templates)],
        "slots_right": [sum(1 for s in slots if s["value_ok"] and s["verified"]), sum(len(e.get("slots", {})) for e in expected_items.values())],
        "checks_recall": [checks_found, checks_total],
        "extra_items": sorted(set(found) - set(expected_items)),
        "statuses": statuses,
        "rules_total": sum(len(i.rules) for i in ruleset.items),
        "unverified_notes": sum(r.get("unverified_notes", 0) for r in present),
        "gaps": len(ruleset.gaps),
        "gaps_reasoned": sum(1 for g in ruleset.gaps if g.reason),
    }
    percent = {k: _pct(*v) for k, v in totals.items() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int)}
    return {"version": ruleset.version, "model": ruleset.model, "prompt_version": ruleset.prompt_version,
            "rows": rows, "totals": totals, "percent": percent}


def tick(value) -> str:
    return "-" if value is None else ("yes" if value else "NO")


def table(result: dict) -> str:
    """The per-item rows and the totals as Markdown."""
    lines = ["| item | status | Part | page | template | slots | checks | rules | unverified |", "|---|---|---|---|---|---|---|---|---|"]
    for letter, r in result["rows"].items():
        if not r["found"]:
            lines.append(f"| ({letter}) | MISSING | | | | | | | |")
            continue
        slots = ", ".join(f"{k}: {'ok' if v['value_ok'] and v['verified'] else 'value' if v['value_ok'] else 'no'}" for k, v in r.get("slots", {}).items()) or "-"
        checks = f"{len(r['checks_found'])}/{len(r['checks_found']) + len(r['checks_missing'])}" if "checks_found" in r else "-"
        lines.append(f"| ({letter}) | {r['status']} | {tick(r['part_ok'])} | {tick(r.get('page_ok'))} | {tick(r.get('template_ok'))} | {slots} | {checks} | {r['rules']} | {r['unverified_notes']} |")
    t, p = result["totals"], result["percent"]
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    for name in ("items_found", "part_right", "page_right", "template_right", "slots_right", "checks_recall"):
        a, b = t[name]
        lines.append(f"| {name} | {a}/{b} ({p[name] if p[name] is not None else '-'}%) |")
    lines.append(f"| statuses | {', '.join(f'{k} {v}' for k, v in sorted(t['statuses'].items()))} |")
    lines.append(f"| rules_total / unverified_notes | {t['rules_total']} / {t['unverified_notes']} |")
    lines.append(f"| gaps (reasoned) | {t['gaps']} ({t['gaps_reasoned']}) |")
    if t["extra_items"]:
        lines.append(f"| extra_items | {', '.join(t['extra_items'])} |")
    return "\n".join(lines)
