"""The pure editing operations (app/rulesets/edit.py) on the fixture rule set: a person's
change is an attributed Edit, the model's value survives every correction, letters for
added items are x1, x2, ..., diffs name what changed, and confirmation blockers say why."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.rulesets import edit as ed
from app.rulesets.library import load_templates
from app.rulesets.schema import (Citation, Consequence, DataClass, Gap, ItemNote, ItemStatus, Outcome, Part, RuleSet, RuleSetItem,
                                 SlotValue, TemplateRule)
from backend.schemas_api import ItemPatch, NewItem, SlotPatch
from test.checks.conftest import RULESET

NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
TEMPLATES = load_templates(Path(__file__).resolve().parent / "data" / "templates")
OWN = {"blank": Outcome(status="disqualified"), "filled": Outcome(status="pass"), "redacted": Outcome(status="needs_review")}


def ruleset(**update) -> RuleSet:
    return RuleSet.model_validate({**copy.deepcopy(RULESET), "status": "draft", "confirmed_by": None, "confirmed_at": None, **update})


def cite(quote="4. Estimated quantity: 875,000 kg", node="09-Schedules:00-Price-Schedule:Notes:(4)") -> Citation:
    return Citation(file="tender/09 Schedules.pdf", page=2, node_id=node, quote=quote, data_class=DataClass.SYNTHETIC)


def price_item(**update) -> RuleSetItem:
    fields = dict(letter="b", title="Unit price quotation", part=Part.A, template="price_schedule",
                  citation=cite("(b) The one-time unit price quotation", "Sched:CCS:(b)"),
                  slots={"estimated_quantity": SlotValue(value=875000, citation=cite(), verified=True)},
                  status=ItemStatus.VERIFIED)
    return RuleSetItem(**{**fields, **update})


# ---------------------------------------------------------------- patches

def test_a_corrected_slot_keeps_the_models_value_through_a_second_correction():
    once = ed.apply_patch(price_item(), ItemPatch(slot=SlotPatch(name="estimated_quantity", value=900000), reason="typo in the key"),
                          "nasi", NOW)
    slot = once.slots["estimated_quantity"]
    assert slot.value == 900000 and slot.model_value == 875000 and slot.origin == "manual" and not slot.verified
    assert once.status == ItemStatus.EDITED and once.edit.by == "nasi" and once.edit.reason == "typo in the key"

    twice = ed.apply_patch(once, ItemPatch(slot=SlotPatch(name="estimated_quantity", value=875500), reason="re-read the note"), "chenyu", NOW)
    assert twice.slots["estimated_quantity"].model_value == 875000, "the model's value, not the first correction"
    assert twice.edit.by == "chenyu"


def test_a_rule_is_replaced_by_id_or_appended_and_a_note_is_appended():
    item = ruleset().items[0]
    changed = TemplateRule(id="noncollusive_certificate.dated", check="filled", field="noncollusive_certificate.date", outcomes=OWN,
                           note="date now needs_review when blank")
    patched = ed.apply_patch(item, ItemPatch(rule=changed, reason="tender allows undated"), "nasi", NOW)
    assert [r.id for r in patched.rules] == [r.id for r in item.rules] and patched.rules[-1].note == changed.note

    extra = TemplateRule(id="noncollusive_certificate.stamped", check="filled", field="noncollusive_certificate.chop", outcomes=OWN)
    assert [r.id for r in ed.apply_patch(item, ItemPatch(rule=extra, reason="company chop"), "nasi", NOW).rules][-1] == extra.id

    noted = ed.apply_patch(item, ItemPatch(note=ItemNote(kind="reference", text="see Paragraph 9.4"), reason="cross-ref"), "nasi", NOW)
    assert noted.notes[-1].text == "see Paragraph 9.4" and len(noted.notes) == len(item.notes) + 1
    assert ed.apply_patch(item, ItemPatch(template="noncollusive_certificate", reason="template written"), "nasi", NOW).template == "noncollusive_certificate"


def test_a_patch_that_changes_nothing_is_refused():
    with pytest.raises(ed.EditError) as err:
        ed.apply_patch(ruleset().items[0], ItemPatch(reason="nothing"), "nasi", NOW)
    assert err.value.code == "bad_request"


# ---------------------------------------------------------------- items

def test_added_items_are_lettered_x1_x2_and_carry_their_own_outcomes():
    rs = ruleset()
    new = NewItem(title="Company chop on every page", part=Part.B, citation=cite("Every page shall bear the chop", "Supp:22"),
                  rules=[TemplateRule(id="chop.every_page", check="filled", field="chop.pages", outcomes=OWN)], reason="clause 22")
    x1 = ed.add_item(rs, new, "nasi", NOW)
    assert x1.letter == "x1" and x1.status == ItemStatus.EDITED and x1.edit.by == "nasi" and x1.template is None
    rs = rs.model_copy(update={"items": [*rs.items, x1]})
    assert ed.add_item(rs, new, "nasi", NOW).letter == "x2"
    with pytest.raises(ValidationError):   # no template, so a rule without its own outcomes is not a gate
        ed.add_item(rs, NewItem(title="t", part=Part.B, citation=cite(), reason="r",
                                rules=[TemplateRule(id="x.y", check="filled", field="f", consequence="critical")]), "nasi", NOW)


def test_items_are_found_replaced_and_removed_by_letter():
    rs = ruleset()
    assert ed.find_item(rs, "l").letter == "l"
    with pytest.raises(ed.EditError) as err:
        ed.find_item(rs, "q")
    assert err.value.code == "not_found"
    assert ed.remove_item(rs, "l").items == []
    with pytest.raises(ed.EditError):
        ed.remove_item(rs, "q")


def test_notes_are_edited_and_removed_by_index_within_bounds():
    item = ruleset().items[0].model_copy(update={"notes": [ItemNote(kind="definition", text="first"), ItemNote(kind="trigger", text="second")]})
    edited = ed.edit_note(item, 1, ItemNote(kind="trigger", text="second, reworded"), "nasi", NOW, "clearer")
    assert [n.text for n in edited.notes] == ["first", "second, reworded"] and edited.edit.reason == "clearer"
    assert [n.text for n in ed.remove_note(item, 0, "nasi", NOW, "duplicate").notes] == ["second"]
    with pytest.raises(ed.EditError):
        ed.remove_note(item, 2, "nasi", NOW, "no such note")


# ---------------------------------------------------------------- gaps and diffs

def test_a_gap_reason_is_attributed():
    rs = ruleset(gaps=[Gap(node_id="Supp:13:(d)", text="shall deliver within 14 days")])
    rs2, gap = ed.set_gap_reason(rs, "Supp:13:(d)", "covered by item (e)", "nasi", NOW)
    assert gap.reason == "covered by item (e)" and gap.edit.by == "nasi" and rs2.gaps[0] == gap
    with pytest.raises(ed.EditError):
        ed.set_gap_reason(rs, "Supp:99", "x", "nasi", NOW)


def test_a_diff_names_added_removed_and_changed_items_with_the_edit_when_a_person_made_it():
    v1 = ruleset()
    noted = ed.apply_patch(v1.items[0], ItemPatch(note=ItemNote(kind="reference", text="see 9.4"), reason="cross-ref"), "nasi", NOW)
    x1 = ed.add_item(v1, NewItem(title="Chop", part=Part.B, citation=cite(), reason="clause 22",
                                 rules=[TemplateRule(id="chop.p", check="filled", field="chop.pages", outcomes=OWN)]), "nasi", NOW)
    v2 = v1.model_copy(update={"version": 2, "parent_version": 1, "items": [noted, x1]})
    d = ed.diff(v1, v2)
    assert d["from"] == 1 and d["to"] == 2 and d["added"] == ["x1"] and d["removed"] == []
    assert d["changed"][0]["letter"] == "l" and set(d["changed"][0]["fields"]) == {"notes", "status"} and d["changed"][0]["edit"].by == "nasi"

    # The rule builder's change carries no edit record: the diff says null.
    rebuilt = v1.items[0].model_copy(update={"rules": v1.items[0].rules[:-1]})
    v3 = v1.model_copy(update={"version": 3, "items": [rebuilt]})
    assert ed.diff(v1, v3)["changed"] == [{"letter": "l", "fields": ["rules"], "edit": None}]
    assert ed.diff(v2, v1)["removed"] == ["x1"]


# ---------------------------------------------------------------- confirmation

def test_confirmation_blockers_name_open_items_unexplained_gaps_and_empty_required_slots():
    assert ed.confirm_blockers(ruleset(), TEMPLATES) == []

    open_item = ruleset().items[0].model_copy(update={"status": ItemStatus.NEEDS_INPUT})
    empty = price_item(slots={})                                              # I1.15: status verified, slot empty
    stale = price_item(letter="c", template="ghost_template")
    rs = ruleset(items=[open_item, empty, stale], gaps=[Gap(node_id="Supp:13:(d)", text="shall")])
    kinds = [(b["kind"], b.get("letter") or b.get("node_id")) for b in ed.confirm_blockers(rs, TEMPLATES)]
    assert kinds == [("item_status", "l"), ("empty_required_slot", "b"), ("unknown_template", "c"), ("gap_without_reason", "Supp:13:(d)")]
    assert ed.describe_blocker(ed.confirm_blockers(rs, TEMPLATES)[1]) == "item (b): required slot estimated_quantity is empty"

    filled = price_item()                                                     # optional slot may stay empty
    assert ed.confirm_blockers(ruleset(items=[filled]), TEMPLATES) == []


def test_the_template_library_reads_one_template_per_file_named_by_id(tmp_path):
    assert set(TEMPLATES) == {"noncollusive_certificate", "price_schedule"}
    assert [s.name for s in TEMPLATES["price_schedule"].slots] == ["estimated_quantity", "currency"]
    assert load_templates(tmp_path / "missing") == {}
    (tmp_path / "wrong.json").write_text((Path(__file__).resolve().parent / "data" / "templates" / "price_schedule.json").read_text())
    with pytest.raises(ValueError, match="names must match"):
        load_templates(tmp_path)
    assert ed.rules_of(ruleset().items[0], TEMPLATES) == ruleset().items[0].rules
    assert [r.id for r in ed.rules_of(price_item(rules=[]), TEMPLATES)] == ["price_schedule.unit_price_present", "price_schedule.quantity_matches"]


def test_a_rule_naming_a_tier_its_template_lacks_blocks_confirmation():
    """Such a rule would never be checked: the engine finds no outcomes for it (#99 review)."""
    rules = [r.model_copy(deep=True) for r in TEMPLATES["price_schedule"].rules]
    lost = rules[0].model_copy(update={"consequence": Consequence.DISCRETIONARY, "outcomes": None})
    rs = ruleset(items=[price_item(rules=[lost, *rules[1:]])])
    [blocker] = ed.confirm_blockers(rs, TEMPLATES)
    assert blocker == {"kind": "unknown_tier", "letter": "b", "rule": lost.id, "tier": "discretionary"}
    assert ed.describe_blocker(blocker) == f"item (b): rule {lost.id} names tier discretionary, which its template does not define"
