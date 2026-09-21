"""What a build saves: the Part intros merged one per Part, and the rule set the builder's
items become, with a person's work kept when there was a rule set before.

A rebuild never overwrites a human edit: an item a person edited keeps its rules, template
and notes, and a slot a person corrected keeps their value while the new suggestion goes
beside it as `model_value`; items a person added (x1, x2, ...) stay; a gap's reason stays
with its node. Everything the builder produced afresh replaces what it produced before."""
from __future__ import annotations

from datetime import datetime, timezone

from app.rulesets.schema import DataClass, Gap, ItemStatus, PartSpec, RuleSet, RuleSetItem

BUILDER = "rule_builder"


def merge_parts(parts: list[PartSpec]) -> list[PartSpec]:
    """`locate` lists a Part once per run of items on the page; a RuleSet wants each Part
    once, with the first intro's citation and every clause any run cited."""
    merged: dict[str, PartSpec] = {}
    for part in parts:
        key = part.part.value
        if key not in merged:
            merged[key] = part.model_copy(update={"clauses": list(part.clauses)})
            continue
        known = {(c.node_id, c.quote) for c in merged[key].clauses}
        extra = [c for c in part.clauses if (c.node_id, c.quote) not in known]
        merged[key] = merged[key].model_copy(update={"clauses": [*merged[key].clauses, *extra]})
    return sorted(merged.values(), key=lambda p: p.part.value)


def touched(item: RuleSetItem) -> bool:
    """Did a person work on this item?"""
    return item.status == ItemStatus.EDITED or item.edit is not None or any(s.origin == "manual" for s in item.slots.values())


def with_new_suggestions(prior: RuleSetItem, built: RuleSetItem) -> RuleSetItem:
    """The person's item, with the builder's new value beside each slot they corrected."""
    slots = dict(prior.slots)
    for name, slot in prior.slots.items():
        if slot.origin == "manual" and name in built.slots:
            slots[name] = slot.model_copy(update={"model_value": built.slots[name].value})
    return prior.model_copy(update={"slots": slots})


def merge_build(existing: dict | None, items: list[RuleSetItem], parts: list[PartSpec], gaps: list[Gap], *,
                project_id: str, data_class: DataClass, model: str | None, prompt_version: str) -> dict:
    """The spec to save as the draft. The store sets version and parent."""
    now = datetime.now(timezone.utc)
    if existing is None:
        fresh = RuleSet(project_id=project_id, version=1, data_class=data_class, items=items, parts=parts, gaps=gaps,
                        created_by=BUILDER, created_at=now, model=model, prompt_version=prompt_version)
        return fresh.model_dump(mode="json")
    old = RuleSet.model_validate(existing)
    prior_by_letter = {i.letter: i for i in old.items}
    merged: list[RuleSetItem] = []
    for item in items:
        prior = prior_by_letter.get(item.letter)
        merged.append(with_new_suggestions(prior, item) if prior is not None and touched(prior) else item)
    built_letters = {i.letter for i in items}
    merged.extend(p for p in old.items if p.letter not in built_letters and (p.letter.startswith("x") or touched(p)))
    reasons = {g.node_id: g for g in old.gaps if g.reason}
    kept_gaps = [reasons.get(g.node_id, g) for g in gaps]
    rebuilt = RuleSet(project_id=project_id, version=old.version, parent_version=old.parent_version, status="draft",
                      data_class=data_class, items=merged, parts=parts, gaps=kept_gaps, created_by=old.created_by,
                      created_at=old.created_at, model=model, prompt_version=prompt_version)
    return rebuilt.model_dump(mode="json")
