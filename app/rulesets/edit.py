"""Rule-set editing (S3): the pure operations behind the editing routes.

Each operation takes a model and returns a new one; the routes load the draft, apply,
validate, save and write the event. A person's change is an `Edit` on the item or gap
(who, when, why). A corrected slot keeps the model's value in `model_value` and becomes
`origin: manual`; the item's status becomes `edited`, an item a person adds too."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.rulesets.schema import Edit, Gap, ItemNote, ItemStatus, RuleSet, RuleSetItem, SlotValue, Template, TemplateRule

X_LETTER = "x"


class EditError(ValueError):
    """A change that cannot be applied as asked: unknown letter, slot, note or gap, or
    a patch that changes nothing. `code` is the API error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _edit(user: str, now: datetime, reason: str) -> Edit:
    return Edit(by=user, at=now, reason=reason)


# ---------------------------------------------------------------- items

def apply_patch(item: RuleSetItem, patch: BaseModel, user: str, now: datetime) -> RuleSetItem:
    """`ItemPatch`: a slot value, a rule (replaced by id or appended), the template, or
    a note appended. At least one must be given."""
    slot, rule, template, note = (getattr(patch, name, None) for name in ("slot", "rule", "template", "note"))
    if slot is None and rule is None and template is None and note is None:
        raise EditError("bad_request", "the patch changes nothing: give a slot, a rule, a template or a note")
    update: dict = {}
    if slot is not None:
        update["slots"] = {**item.slots, slot.name: correct_slot(item.slots.get(slot.name), slot.value, user, now, patch.reason)}
    if rule is not None:
        rules = [rule if r.id == rule.id else r for r in item.rules]
        if all(r.id != rule.id for r in item.rules):
            rules.append(rule)
        update["rules"] = rules
    if template is not None:
        update["template"] = template
    if note is not None:
        update["notes"] = [*item.notes, note]
    return item.model_copy(update={**update, "status": ItemStatus.EDITED, "edit": _edit(user, now, patch.reason)})


def correct_slot(old: SlotValue | None, value, user: str, now: datetime, reason: str) -> SlotValue:
    """A person's value. The model's value survives every correction: the first keeps it
    in `model_value`, a second correction keeps the same original, not the first correction.
    `verified` is set only by code (V4), so a person's value is not verified; the model's
    citation stays with it as the place the value was read from."""
    if old is None:
        return SlotValue(value=value, verified=False, origin="manual", model_value=None, edit=_edit(user, now, reason))
    model_value = old.model_value if old.origin == "manual" else old.value
    return old.model_copy(update={"value": value, "verified": False, "origin": "manual", "model_value": model_value,
                                  "edit": _edit(user, now, reason)})


def next_letter(ruleset: RuleSet) -> str:
    """Items a person adds are x1, x2, ... after the highest one present."""
    taken = [int(i.letter[1:]) for i in ruleset.items if i.letter.startswith(X_LETTER)]
    return f"{X_LETTER}{max(taken, default=0) + 1}"


def add_item(ruleset: RuleSet, new: BaseModel, user: str, now: datetime) -> RuleSetItem:
    """`NewItem`: from a clause a person picked; `edited` with their edit record (I1.16).
    No template, so the rules must carry their own outcomes (the schema checks)."""
    return RuleSetItem(letter=next_letter(ruleset), title=new.title, part=new.part, template=None, citation=new.citation,
                       clauses=[], rules=list(new.rules), status=ItemStatus.EDITED, edit=_edit(user, now, new.reason))


def find_item(ruleset: RuleSet, letter: str) -> RuleSetItem:
    for item in ruleset.items:
        if item.letter == letter:
            return item
    raise EditError("not_found", f"the rule set has no item ({letter})")


def replace_item(ruleset: RuleSet, item: RuleSetItem) -> RuleSet:
    return ruleset.model_copy(update={"items": [item if i.letter == item.letter else i for i in ruleset.items]})


def remove_item(ruleset: RuleSet, letter: str) -> RuleSet:
    find_item(ruleset, letter)
    return ruleset.model_copy(update={"items": [i for i in ruleset.items if i.letter != letter]})


# ---------------------------------------------------------------- notes

def edit_note(item: RuleSetItem, index: int, note: ItemNote, user: str, now: datetime, reason: str) -> RuleSetItem:
    if not 0 <= index < len(item.notes):
        raise EditError("not_found", f"item ({item.letter}) has no note {index}")
    notes = [note if i == index else n for i, n in enumerate(item.notes)]
    return item.model_copy(update={"notes": notes, "status": ItemStatus.EDITED, "edit": _edit(user, now, reason)})


def remove_note(item: RuleSetItem, index: int, user: str, now: datetime, reason: str) -> RuleSetItem:
    if not 0 <= index < len(item.notes):
        raise EditError("not_found", f"item ({item.letter}) has no note {index}")
    notes = [n for i, n in enumerate(item.notes) if i != index]
    return item.model_copy(update={"notes": notes, "status": ItemStatus.EDITED, "edit": _edit(user, now, reason)})


# ---------------------------------------------------------------- gaps

def set_gap_reason(ruleset: RuleSet, node_id: str, reason: str, user: str, now: datetime) -> tuple[RuleSet, Gap]:
    """The reason a gap is acceptable, attributed (I1.12)."""
    for i, gap in enumerate(ruleset.gaps):
        if gap.node_id == node_id:
            given = gap.model_copy(update={"reason": reason, "edit": _edit(user, now, reason)})
            gaps = [given if j == i else g for j, g in enumerate(ruleset.gaps)]
            return ruleset.model_copy(update={"gaps": gaps}), given
    raise EditError("not_found", f"the rule set has no gap for node {node_id}")


# ---------------------------------------------------------------- diff

_IGNORED_IN_DIFF = ("edit",)


def diff(old: RuleSet, new: RuleSet) -> dict:
    """Items added, removed and changed between two versions. A changed item lists the
    fields that differ and its edit record when a person made the change; a change the
    rule builder made carries no edit (`null`, I1.14)."""
    before = {i.letter: i for i in old.items}
    after = {i.letter: i for i in new.items}
    changed = []
    for letter in sorted(set(before) & set(after), key=_letter_order):
        a, b = before[letter].model_dump(mode="json"), after[letter].model_dump(mode="json")
        fields = [k for k in b if k not in _IGNORED_IN_DIFF and a.get(k) != b.get(k)]
        if fields:
            edit = after[letter].edit if after[letter].edit != before[letter].edit else None
            changed.append({"letter": letter, "fields": fields, "edit": edit})
    return {"from": old.version, "to": new.version,
            "added": sorted(set(after) - set(before), key=_letter_order),
            "removed": sorted(set(before) - set(after), key=_letter_order), "changed": changed}


def _letter_order(letter: str) -> tuple[int, int | str]:
    return (1, int(letter[1:])) if letter.startswith(X_LETTER) else (0, letter)


# ---------------------------------------------------------------- confirmation

def confirm_blockers(ruleset: RuleSet, templates: dict[str, Template]) -> list[dict]:
    """Why the draft cannot be confirmed yet: an item that needs input or is a gap, a gap
    without a reason, and (I1.15) an empty required slot of the item's template, whatever
    the item's status. Each blocker names what to fix."""
    out: list[dict] = []
    for item in ruleset.items:
        if item.status in (ItemStatus.NEEDS_INPUT, ItemStatus.GAP):
            out.append({"kind": "item_status", "letter": item.letter, "status": item.status.value})
        if item.template is not None:
            template = templates.get(item.template)
            if template is None:
                out.append({"kind": "unknown_template", "letter": item.letter, "template": item.template})
                continue
            for spec in template.slots:
                value = item.slots.get(spec.name)
                if spec.required and (value is None or value.value is None):
                    out.append({"kind": "empty_required_slot", "letter": item.letter, "slot": spec.name})
            # A rule naming a tier its template does not define would never be checked (#99 review).
            for rule in item.rules:
                if rule.consequence is not None and rule.outcomes is None and rule.consequence not in template.consequences:
                    out.append({"kind": "unknown_tier", "letter": item.letter, "rule": rule.id,
                                "tier": rule.consequence.value})
    for gap in ruleset.gaps:
        if not gap.reason:
            out.append({"kind": "gap_without_reason", "node_id": gap.node_id})
    return out


def rules_of(item: RuleSetItem, templates: dict[str, Template]) -> list[TemplateRule]:
    """The item's own rules, else its template's."""
    if item.rules or item.template is None:
        return list(item.rules)
    template = templates.get(item.template)
    return list(template.rules) if template else []


def describe_blocker(blocker: dict) -> str:
    kind = blocker["kind"]
    if kind == "item_status":
        return f"item ({blocker['letter']}) still needs input" if blocker["status"] == "needs_input" else f"item ({blocker['letter']}) is a gap"
    if kind == "empty_required_slot":
        return f"item ({blocker['letter']}): required slot {blocker['slot']} is empty"
    if kind == "unknown_template":
        return f"item ({blocker['letter']}): template {blocker['template']} is not in the library"
    if kind == "unknown_tier":
        return f"item ({blocker['letter']}): rule {blocker['rule']} names tier {blocker['tier']}, which its template does not define"
    return f"gap {blocker['node_id']} has no reason"
