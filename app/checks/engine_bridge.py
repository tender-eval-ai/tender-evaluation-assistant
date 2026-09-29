"""V6: a RuleSet from the shared contract evaluated by Nasi's rule engine, every item.

The engine reads a rules document in its own JSON vocabulary (rules with an id, a
field_id, a consequence tier or their own outcomes, depends_on, stage) and a vendor
item: flat keys, `<field>_redacted` and `<field>_confidence` beside each value. This
module is the only place that translates between the two, so the rule split at S1 and
the engine stay untouched by each other.

Since S4-3 it decides every item of the rule set (`decide`): the comparison kinds of the
closed CheckType menu (value, range, unit, date, math, cross-document match, contains) are
computed here in code and handed to the engine as explicit outcomes; `{slot}` references
in a rule's params are rendered from the item's slots; a rule on a field no form reads is a
reviewer's call, never a blank; V4's unverified values are `needs_review`; and the Stage I
and II summaries roll up from the rules' stages.

Since J12: `contains` takes `phrases` (all must be there) and `absent` (none may be),
`range` takes `max_decimals` (as printed), and a rule's first `normalise` step reaches the
engine as its transform, reported under `adjustments`. None changes the schema."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from app.checks.verify import agree, normalise
from app.engine.core import evaluate_item
from app.engine.field_result import FieldResult, overall_status, status_counts, worst_status
from app.rulesets.library import load_templates
from app.rulesets.schema import CheckType, RuleSet, RuleSetItem, Template, TemplateRule

_SLOT_REF = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
COMPARISONS = {CheckType.VALUE, CheckType.RANGE, CheckType.UNIT, CheckType.DATE, CheckType.MATH,
               CheckType.CROSS_DOCUMENT_MATCH, CheckType.CONTAINS}
INJECTED = {"match": "pass", "mismatch": "needs_review", "unstated": "needs_review"}   # a comparison never disqualifies
_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%B %d, %Y", "%d %B, %Y", "%d-%m-%Y")


# ---------------------------------------------------------------- values
def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value or ""))
    return float(m.group(0).replace(",", "")) if m else None


def parse_date(value: Any) -> dt.date | None:
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(value or "").strip())
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _equal(value: Any, expected: Any) -> bool:
    """Numbers within half a percent; anything else as two readings agree (V4's rule)."""
    numeric = isinstance(expected, (int, float)) and not isinstance(expected, bool) or re.fullmatch(r"[\d,.\s]+", str(expected))
    a, b = _number(value), _number(expected)
    if numeric and a is not None and b is not None:
        return abs(a - b) <= max(0.005 * abs(b), 1e-9)
    return agree(value, expected)


def _contains(text: Any, phrase: Any) -> bool:
    a, b = normalise(phrase), normalise(text)
    return bool(a) and f" {a} " in f" {b} "


def _qualify(name: str, prefix: str) -> str:
    return name if "." in name else f"{prefix}.{name}"


def render_params(rule: TemplateRule, item: RuleSetItem) -> dict:
    """The rule's params with "{slot}" references replaced by the item's slot values."""
    out: dict = {}
    for name, value in rule.params.items():
        if isinstance(value, str) and (m := _SLOT_REF.match(value)):
            slot = item.slots.get(m.group(1))
            out[name] = slot.value if slot is not None else None
        else:
            out[name] = value
    return out


def compare(rule: TemplateRule, params: dict, fields: dict) -> tuple[str, str] | None:
    """The code check behind a comparison kind: ("match" | "mismatch" | "unstated", detail).
    None for a presence kind or a blank field, where the presence outcomes apply."""
    kind = rule.check
    if kind == CheckType.HUMAN_ONLY:
        return "unstated", "a reviewer decides; no automated check"
    if kind not in COMPARISONS:
        return None
    value = fields.get(rule.field)
    if value is None:
        return None
    printed = fields.get(f"{rule.field}_printed")
    shown = printed if printed is not None else value
    prefix = rule.field.rpartition(".")[0]
    if kind == CheckType.VALUE:
        expected = params.get("expected")
        if expected is None:
            return "unstated", "no expected value to compare with"
        return ("match" if _equal(value, expected) else "mismatch", f"read {shown!r}, expected {expected!r}")
    if kind == CheckType.RANGE:
        number, lo, hi = _number(value), _number(params.get("min")), _number(params.get("max"))
        if number is None:
            return "mismatch", f"{shown!r} is not a number"
        places = _number(params.get("max_decimals"))
        if places is not None:
            # As printed: "2.50%" has two decimal places even though it is the number 2.5.
            m = re.search(r"\d[\d,]*(?:\.(\d+))?", str(shown))
            written = len(m.group(1) or "") if m else 0
            if written > places:
                return "mismatch", f"read {shown!r}, {written} decimal places, at most {places:g}"
            if lo is None and hi is None:
                return "match", f"read {shown!r}, at most {places:g} decimal places"
        if lo is None and hi is None:
            return "unstated", "no bounds to compare with"
        ok = (lo is None or number >= lo) and (hi is None or number <= hi)
        bounds = " to ".join(f"{b:g}" for b in (lo, hi) if b is not None) if lo is not None and hi is not None else \
            (f"at least {lo:g}" if lo is not None else f"at most {hi:g}")
        return ("match" if ok else "mismatch", f"read {shown!r}, allowed {bounds}")
    if kind == CheckType.UNIT:
        allowed = params.get("allowed") or ([params["expected"]] if params.get("expected") else [])
        if not allowed:
            return "unstated", "no unit to compare with"
        ok = any(_contains(shown, u) for u in allowed)
        return ("match" if ok else "mismatch", f"read {shown!r}, allowed {', '.join(str(u) for u in allowed)}")
    if kind == CheckType.CONTAINS:
        # `phrases`: every one must be there; with `absent`, none may be (an address is not a P.O. Box).
        phrase = params.get("phrase") or params.get("text") or params.get("expected")
        phrases = params.get("phrases") or ([phrase] if phrase else [])
        if isinstance(phrases, str):
            phrases = [phrases]
        if not phrases:
            return "unstated", "no phrase to look for"
        found = [p for p in phrases if _contains(shown, p)]
        if params.get("absent"):
            return ("mismatch", f"read {shown!r}, which should not contain {found[0]!r}") if found else \
                ("match", f"read {shown!r}, none of {', '.join(map(repr, phrases))}")
        missing = [p for p in phrases if p not in found]
        if missing:
            return "mismatch", f"read {shown!r}, missing {', '.join(map(repr, missing))}"
        return "match", f"read {shown!r}, looked for {', '.join(map(repr, phrases))}"
    if kind == CheckType.DATE:
        date = parse_date(shown)
        if date is None:
            return "mismatch", f"{shown!r} is not a date"
        after, before = parse_date(params.get("after")), parse_date(params.get("before"))
        if after and date < after:
            return "mismatch", f"{date.isoformat()} is before {after.isoformat()}"
        if before and date > before:
            return "mismatch", f"{date.isoformat()} is after {before.isoformat()}"
        return "match", date.isoformat()
    if kind == CheckType.MATH:
        inputs = [_qualify(str(n), prefix) for n in (params.get("inputs") or [])]
        numbers = [_number(fields.get(n)) for n in inputs]
        reported = _number(value)
        if len(numbers) < 2 or any(n is None for n in numbers) or reported is None:
            return "unstated", "an input is blank or not a number"
        op = str(params.get("op", "product"))
        expected = {"product": numbers[0] * numbers[1], "sum": numbers[0] + numbers[1]}.get(op)
        if expected is None:
            return "unstated", f"unknown operation {op!r}"
        tolerance = _number(params.get("tolerance"))
        tolerance = tolerance if tolerance is not None else max(0.01, 0.005 * abs(expected))
        return ("match" if abs(reported - expected) <= tolerance else "mismatch",
                f"read {reported:g}, the {op} of {' and '.join(inputs)} is {expected:g}")
    if kind == CheckType.CROSS_DOCUMENT_MATCH:
        other = params.get("other") or params.get("field")
        if not other:
            return "unstated", "no other field named"
        other_key = _qualify(str(other), prefix)
        other_value = fields.get(other_key)
        if other_value is None:
            return "unstated", f"{other_key} is blank"
        other_shown = fields.get(f"{other_key}_printed") or other_value
        return ("match" if agree(shown, other_shown) else "mismatch", f"read {shown!r}, {other_key} reads {other_shown!r}")
    return None


# ---------------------------------------------------------------- the engine's vocabulary
def engine_rule(rule: TemplateRule, outcomes: dict | None = None) -> dict:
    out: dict = {
        "id": rule.id,
        "field_id": rule.field,
        "field": rule.field.rsplit(".", 1)[-1].replace("_", " "),
        "check": rule.check.value,
        "consequence_tier": rule.consequence.value if rule.consequence else None,
        "stage": rule.stage,
    }
    if outcomes is not None:
        out["outcomes"] = outcomes
    elif rule.outcomes is not None:
        out["outcomes"] = {k: v.model_dump(exclude_none=True) for k, v in rule.outcomes.items()}
    if rule.normalise:
        # The engine runs one transform per rule: the first step, reported as an adjustment.
        step = rule.normalise[0]
        out["transform"] = {"operation": step.op, "params": dict(step.params), "surfaced_as": "auto_adjustment"}
    if rule.depends_on:
        out["depends_on"] = rule.depends_on[0]      # the engine reads one parent until the rule files are split
    if rule.note:
        out["note"] = rule.note
    if rule.condition:
        out["condition"] = rule.condition
    return out


def _tiers(template: Template | None) -> dict:
    tiers: dict = {}
    if template is not None:
        for tier, defaults in template.consequences.items():
            entry: dict = {"outcomes": {k: v.model_dump(exclude_none=True) for k, v in defaults.outcomes.items()}}
            if defaults.follow_up_deadline is not None:
                fd = defaults.follow_up_deadline
                entry["transform"] = {"operation": fd.op, "surfaced_as": "follow_up_deadline",
                                      "params": {"base_date": "follow_up.trigger_date", "offset_value": fd.offset}}
            tiers[tier.value] = entry
    return tiers


def rules_doc(item: RuleSetItem, template: Template | None = None, overrides: dict[str, tuple[str, str]] | None = None) -> dict:
    """The engine's rules document for one item. A rule with a computed comparison gets its
    outcomes (own or tier) plus the injected key the comparison chose."""
    tiers = _tiers(template)
    rules = []
    for rule in item.rules:
        outcomes = None
        if overrides and rule.id in overrides:
            key, detail = overrides[rule.id]
            if rule.outcomes is not None:
                base = {k: v.model_dump(exclude_none=True) for k, v in rule.outcomes.items()}
            else:
                base = dict(tiers.get(rule.consequence.value, {}).get("outcomes", {})) if rule.consequence else {}
            outcomes = {**base, key: {"status": INJECTED[key], "note": f"{{field}}: {detail}"}}
        rules.append(engine_rule(rule, outcomes))
    return {"form_name": item.title, "compliance_schedule_item": f"({item.letter})", "stage": "I",
            "consequence_tiers": tiers, "rules": rules}


def prepare(item: RuleSetItem, fields: dict) -> tuple[dict, dict[str, tuple[str, str]]]:
    """The fields with an explicit outcome for every comparison rule, and what was decided."""
    prepared, overrides = dict(fields), {}
    for rule in item.rules:
        decided = compare(rule, render_params(rule, item), fields)
        if decided is not None:
            overrides[rule.id] = decided
            prepared[f"{rule.id}__outcome"] = decided[0]
    return prepared, overrides


# ---------------------------------------------------------------- code's rules after the engine
def apply_verification(checked: list[FieldResult], fields: dict) -> None:
    """V4's rule, code not engine: a value the verifier could not confirm (`_verification.verified`
    is False) is `needs_review` whatever the engine said, never a pass and never a
    disqualification; the reason is the verifier's note. A field without a verification
    record (an older result, a person's correction) is left to the engine."""
    for f in checked:
        record = fields.get(f"{f.field_id}_verification") or {}
        if record.get("verified") is False and f.status in ("pass", "disqualified"):
            f.status = "needs_review"
            f.note = f"unverified: {record.get('note') or 'the two readings differ'}"


def apply_unextracted(checked: list[FieldResult], fields: dict) -> None:
    """A rule on a field no form reads (no key at all, not even a citation) is a reviewer's
    call: the engine saw a blank, but nothing was looked for."""
    for f in checked:
        if f.field_id not in fields and f"{f.field_id}_page" not in fields:
            f.status = "needs_review"
            f.note = f"unextracted: no form reads {f.field}; a reviewer decides"


def evaluate(item: RuleSetItem, fields: dict, template: Template | None = None) -> dict:
    """The verdict for one item: the engine's overall status (dormant fields do not count
    against a tender as submitted today; an item whose every field is dormant is dormant),
    the worst status including dormant, every checked field with its status, stage and
    note, and the reasons a reviewer reads."""
    blocked = None
    if not item.rules:
        blocked = f"item ({item.letter}) has no rules; a reviewer decides"
    elif item.template and template is None and any(r.consequence is not None and r.outcomes is None for r in item.rules):
        blocked = f"item ({item.letter}): template {item.template!r} is not in the library, so its rules have no outcomes; a reviewer decides"
    if blocked:
        return {"item": item.letter, "part": item.part.value, "outcome": "needs_review", "worst": "needs_review",
                "counts": status_counts([]), "rule_ids": [r.id for r in item.rules], "fields": [], "reasons": [blocked]}
    prepared, overrides = prepare(item, fields)
    result = evaluate_item([rules_doc(item, template, overrides)], prepared, item.letter)
    apply_verification(result.fields, fields)
    apply_unextracted(result.fields, fields)
    checked = [{"field_id": f.field_id, "field": f.field, "status": f.status, "note": f.note, "value": f.value,
                "redacted": f.redacted, "stage": f.stage,
                "follow_up": None if f.follow_up is None else vars(f.follow_up),
                "page": fields.get(f"{f.field_id}_page")} for f in result.fields]
    outcome = overall_status(result.fields)
    if result.fields and all(f.status == "dormant" for f in result.fields):
        outcome = "dormant"
    return {
        "item": item.letter,
        "part": item.part.value,
        "outcome": outcome,
        "worst": worst_status([f["status"] for f in checked]),
        "counts": status_counts(result.fields),
        "rule_ids": [r.id for r in item.rules],
        "fields": checked,
        "reasons": [f["note"] for f in checked if f["status"] != "pass" and f["note"]],
        "adjustments": result.auto_adjustments,    # a rule's `normalise` step, e.g. a dosage rounded
    }


def stage_summary(items: dict[str, dict], stage: str) -> dict:
    """{outcome, items: {letter: outcome}} over the fields checked at one stage; an item with
    nothing at that stage is left out; dormant counts only when nothing else is there."""
    per: dict[str, str] = {}
    for letter, v in items.items():
        statuses = [f["status"] for f in v.get("fields", []) if f.get("stage", "I") == stage]
        if not statuses and v.get("outcome") == "needs_review" and not v.get("fields") and stage == "I":
            statuses = ["needs_review"]                                    # an item with no rules
        if not statuses:
            continue
        live = [s for s in statuses if s != "dormant"]
        per[letter] = worst_status(live) if live else "dormant"
    live = [s for s in per.values() if s != "dormant"]
    return {"outcome": worst_status(live) if live else ("dormant" if per else "pass"), "items": per}


def decide(fields: dict, spec: dict) -> dict:
    """The pipeline's engine-only decision on every item of a confirmed RuleSet as stored:
    {ruleset_version, outcome (Stage I), items: {letter: verdict}, stage1, stage2 | null}."""
    ruleset = RuleSet.model_validate(spec)
    templates = load_templates()
    items = {}
    for item in ruleset.items:
        template = templates.get(item.template) if item.template else None
        items[item.letter] = evaluate(item, fields, template)
    stage1, stage2 = stage_summary(items, "I"), stage_summary(items, "II")
    return {"ruleset_version": ruleset.version, "outcome": stage1["outcome"], "items": items,
            "stage1": stage1, "stage2": stage2 if stage2["items"] else None}


def decide_item_l(fields: dict, spec: dict) -> dict:
    """Item (l)'s verdict alone, as the S2 tests read it."""
    verdict = decide(fields, spec)
    return {**verdict["items"]["l"], "ruleset_version": verdict["ruleset_version"]}
