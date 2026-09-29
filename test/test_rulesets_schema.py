"""The rule-set contract (app/rulesets/schema.py) enforces its own design rules."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.engine import core as engine
from app.rulesets.schema import (NEGATIVE_KEYS, NEUTRAL_KEYS, OUTCOME_KEYS, POSITIVE_KEYS, CheckType, Citation,
                                 Consequence, ConsequenceDefaults, DataClass, Edit, FollowUp, Gap, ItemNote, ItemStatus,
                                 Normalise, Outcome, Part, PartSpec, RuleSet, RuleSetItem, SlotKind, SlotSpec, SlotValue,
                                 Template, TemplateRule)

NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)


def cite(quote="Estimated Quantity (Kilograms) 875,000 kg", node="PriceSchedule:Notes:(2)") -> Citation:
    return Citation(file="tender/09 Schedules.pdf", page=1, node_id=node, quote=quote, data_class=DataClass.SYNTHETIC)


def rule(id="price_schedule.unit_price_present", **kw) -> TemplateRule:
    kw.setdefault("consequence", Consequence.CRITICAL)
    return TemplateRule(id=id, check=CheckType.FILLED, field="price_schedule.unit_price", **kw)


def item(letter="b", status=ItemStatus.VERIFIED, **kw) -> RuleSetItem:
    template = kw.pop("template", "price_schedule")
    rules = kw.pop("rules", [rule()])
    return RuleSetItem(letter=letter, title="Unit price quotation", part=Part.A, template=template,
                       citation=cite("(b) The one-time unit price quotation", "Sched:CCS:(b)"),
                       slots={"estimated_quantity": SlotValue(value=875000, citation=cite(), verified=True)},
                       rules=rules, status=status, **kw)


def ruleset(items, status="draft", **kw) -> RuleSet:
    return RuleSet(project_id="SYN-2026-001", version=1, data_class=DataClass.SYNTHETIC, items=items,
                   created_by="chenyu", created_at=NOW, status=status, **kw)


PASS_FAIL = {"blank": Outcome(status="disqualified", note="{field} is blank"), "filled": Outcome(status="pass"),
             "redacted": Outcome(status="needs_review")}


def test_the_check_menu_has_twelve_kinds():
    assert len(CheckType) == 12
    assert CheckType.HUMAN_ONLY in CheckType


def test_the_outcome_vocabulary_matches_the_engine():
    """The engine picks outcome keys from three tables; the contract must list the same ones."""
    assert POSITIVE_KEYS == frozenset(engine.POSITIVE_KEYS)
    assert NEGATIVE_KEYS == frozenset(engine.NEGATIVE_KEYS)
    assert NEUTRAL_KEYS == frozenset(engine.NEUTRAL_KEYS)
    assert {"blank", "filled", "redacted", "not_applicable"} <= OUTCOME_KEYS


def test_a_rule_is_a_gate_or_it_is_not_a_rule():
    with pytest.raises(ValidationError, match="consequence or its own outcomes"):
        rule(consequence=None)
    own = rule(consequence=None, outcomes=PASS_FAIL)
    assert own.outcomes["blank"].status == "disqualified"
    with pytest.raises(ValidationError, match="unknown outcome keys \\['blnk'\\]"):
        rule(outcomes={"blnk": Outcome(status="pass")})


def test_follow_ups_belong_to_dormant_outcomes_only():
    follow = FollowUp(trigger="Authority requests it", deadline="5 working days", if_deadline_missed="disqualified")
    assert Outcome(status="dormant", follow_up=follow).follow_up is follow
    with pytest.raises(ValidationError, match="dormant"):
        Outcome(status="pass", follow_up=follow)


def test_params_take_literals_of_four_kinds_and_normalise_is_a_closed_list():
    r = rule(params={"min": 0, "max": 2.5, "units": ["kg", "g"], "strict": True, "expected": "{estimated_quantity}"})
    assert r.slot_refs() == {"estimated_quantity"}
    with pytest.raises(ValidationError):
        rule(params={"nested": {"a": 1}})
    assert Normalise(op="round_significant_figures", params={"digits": 2}).op == "round_significant_figures"
    with pytest.raises(ValidationError):
        Normalise(op="round_to_nearest")
    assert rule(stage="II").stage == "II"
    with pytest.raises(ValidationError):
        rule(stage="III")


def test_added_items_are_numbered_x1_x2_and_schedule_items_keep_their_letter():
    assert item("l").letter == "l" and item("x1").letter == "x1" and item("x12").letter == "x12"
    for bad in ("aa", "x0", "x01", "1", "L"):
        with pytest.raises(ValidationError):
            item(bad)


def test_a_novel_item_has_no_template_so_its_rules_carry_their_own_outcomes():
    with pytest.raises(ValidationError, match="own outcomes"):
        item("l", ItemStatus.NOVEL, template=None)
    novel = item("l", ItemStatus.NOVEL, template=None, rules=[rule(consequence=None, outcomes=PASS_FAIL)],
                 condition="tenderer is not the manufacturer",
                 notes=[ItemNote(kind="trigger", text="required only if the tenderer is not the manufacturer")])
    assert novel.notes[0].kind == "trigger" and novel.condition


def test_a_template_declares_the_tiers_and_slots_its_rules_use():
    defaults = {Consequence.CRITICAL: ConsequenceDefaults(outcomes=PASS_FAIL)}
    slot = SlotSpec(name="estimated_quantity", kind=SlotKind.NUMBER, unit="kg", description="the estimated quantity")
    t = Template(id="price_schedule", form_name="Price Schedule", slots=[slot], consequences=defaults,
                 rules=[rule(params={"expected": "{estimated_quantity}"})])
    assert Template.model_validate_json(t.model_dump_json()) == t
    with pytest.raises(ValidationError, match="no defaults for it"):
        Template(id="t", form_name="f", rules=[rule(consequence=Consequence.DISCRETIONARY)])
    with pytest.raises(ValidationError, match="references slots \\['estimated_quantity'\\]"):
        Template(id="t", form_name="f", consequences=defaults, rules=[rule(params={"expected": "{estimated_quantity}"})])
    with pytest.raises(ValidationError, match="unknown outcome keys"):
        ConsequenceDefaults(outcomes={"fillled": Outcome(status="pass")})


def test_extracted_values_must_cite_their_source():
    with pytest.raises(ValidationError, match="citation"):
        SlotValue(value=875000)
    with pytest.raises(ValidationError, match="verified"):
        SlotValue(value=None, verified=True)


def test_manual_values_record_the_edit_and_keep_the_model_value():
    with pytest.raises(ValidationError, match="manual"):
        SlotValue(value=900000, origin="manual")
    corrected = SlotValue(value=900000, origin="manual", model_value=875000,
                          edit=Edit(by="nasi", at=NOW, reason="typo in the tender: see clause 5.2"))
    assert corrected.model_value == 875000 and corrected.verified is False


def test_confirmation_is_blocked_by_open_items_and_unexplained_gaps():
    with pytest.raises(ValidationError, match="need input"):
        ruleset([item("b", ItemStatus.NEEDS_INPUT)], status="confirmed", confirmed_by="nasi", confirmed_at=NOW)
    with pytest.raises(ValidationError, match="who confirmed"):
        ruleset([item("b")], status="confirmed")
    confirmed = ruleset([item("b")], status="confirmed", confirmed_by="nasi", confirmed_at=NOW)
    assert confirmed.item("b").rules[0].check == CheckType.FILLED


def test_letters_and_rule_ids_are_unique_and_versions_are_ordered():
    with pytest.raises(ValidationError, match="unique"):
        ruleset([item("b"), item("b")])
    with pytest.raises(ValidationError, match="older"):
        RuleSet(project_id="p", version=1, parent_version=1, data_class=DataClass.SYNTHETIC, items=[],
                created_by="c", created_at=NOW)


def test_round_trips_through_json():
    rs = ruleset([item("b"), item("l", ItemStatus.NOVEL, template=None,
                                  rules=[rule(consequence=None, outcomes=PASS_FAIL, stage="II")])])
    again = RuleSet.model_validate_json(rs.model_dump_json())
    assert again == rs
    assert again.item("l").template is None and again.item("l").rules[0].stage == "II"


def test_part_intros_are_located_once_each_and_a_citation_may_list_its_candidates():
    part_a = PartSpec(part=Part.A, title="Part A", citation=cite("Part A Items (a) to (c) are required", "Sched:CCS:PartA"),
                      clauses=[cite("3.3 A tender without them is not considered", "ToT:3.3")])
    assert ruleset([item()], parts=[part_a]).parts[0].clauses[0].node_id == "ToT:3.3"
    with pytest.raises(ValidationError, match="each Part appears once"):
        ruleset([item()], parts=[part_a, part_a])

    several = Citation(file="tender/01 Terms.pdf", page=4, node_id="ToT:3.3", candidates=["ToT:3.3", "Supp:3.3"],
                       quote="3.3 A tender without them", data_class=DataClass.SYNTHETIC)
    assert several.node_id in several.candidates and cite().candidates is None


def test_a_gap_reason_is_attributed_and_updated_by_is_read_back_from_the_server():
    gap = Gap(node_id="Supp:13:(d)", text="shall deliver within 14 days", reason="covered by item (e)",
              edit=Edit(by="nasi", at=NOW, reason="covered by item (e)"))
    rs = ruleset([item()], gaps=[gap], updated_by="chenyu")
    assert rs.gaps[0].edit.by == "nasi" and rs.updated_by == "chenyu"
    assert RuleSet.model_validate_json(rs.model_dump_json()) == rs
