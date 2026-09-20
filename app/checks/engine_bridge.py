"""V6: a RuleSetItem from the shared contract evaluated by Nasi's rule engine.

The engine reads a rules document in its own JSON vocabulary (rules with an id, a
field_id, a consequence tier or their own outcomes, depends_on, stage) and a vendor
item: flat keys, `<field>_redacted` and `<field>_confidence` beside each value. This
module is the only place that translates between the two, so the rule split at S1 and
the engine stay untouched by each other."""
from __future__ import annotations

from app.engine.core import evaluate_item
from app.engine.field_result import worst_status
from app.rulesets.schema import RuleSet, RuleSetItem, Template, TemplateRule


def engine_rule(rule: TemplateRule) -> dict:
    out: dict = {
        "id": rule.id,
        "field_id": rule.field,
        "field": rule.field.rsplit(".", 1)[-1].replace("_", " "),
        "check": rule.check.value,
        "consequence_tier": rule.consequence.value if rule.consequence else None,
        "stage": rule.stage,
    }
    if rule.outcomes is not None:
        out["outcomes"] = {k: v.model_dump(exclude_none=True) for k, v in rule.outcomes.items()}
    if rule.depends_on:
        out["depends_on"] = rule.depends_on[0]      # the engine reads one parent until the rule files are split
    if rule.note:
        out["note"] = rule.note
    if rule.condition:
        out["condition"] = rule.condition
    return out


def rules_doc(item: RuleSetItem, template: Template | None = None) -> dict:
    tiers = {}
    if template is not None:
        for tier, defaults in template.consequences.items():
            entry: dict = {"outcomes": {k: v.model_dump(exclude_none=True) for k, v in defaults.outcomes.items()}}
            if defaults.follow_up_deadline is not None:
                fd = defaults.follow_up_deadline
                entry["transform"] = {"operation": fd.op, "surfaced_as": "follow_up_deadline",
                                      "params": {"base_date": "follow_up.trigger_date", "offset_value": fd.offset}}
            tiers[tier.value] = entry
    return {"form_name": item.title, "compliance_schedule_item": f"({item.letter})", "stage": "I",
            "consequence_tiers": tiers, "rules": [engine_rule(r) for r in item.rules]}


def evaluate(item: RuleSetItem, fields: dict, template: Template | None = None) -> dict:
    """The verdict for one item: the engine's overall status (dormant fields do not
    count against a tender as submitted today), the worst status including dormant,
    every checked field with its status and note, and the reasons a reviewer reads."""
    result = evaluate_item([rules_doc(item, template)], fields, item.letter)
    checked = [{"field_id": f.field_id, "field": f.field, "status": f.status, "note": f.note, "value": f.value,
                "redacted": f.redacted, "stage": f.stage,
                "follow_up": None if f.follow_up is None else vars(f.follow_up),
                "page": fields.get(f"{f.field_id}_page")} for f in result.fields]
    return {
        "item": item.letter,
        "part": item.part.value,
        "outcome": result.overall_status,
        "worst": worst_status([f["status"] for f in checked]),
        "counts": result.status_counts,
        "rule_ids": [r.id for r in item.rules],
        "fields": checked,
        "reasons": [f["note"] for f in checked if f["status"] != "pass" and f["note"]],
    }


def decide_item_l(fields: dict, spec: dict) -> dict:
    """The pipeline's engine-only decision: `spec` is a confirmed RuleSet as stored."""
    ruleset = RuleSet.model_validate(spec)
    verdict = evaluate(ruleset.item("l"), fields)
    verdict["ruleset_version"] = ruleset.version
    return verdict
