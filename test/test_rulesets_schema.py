"""The rule-set contract (app/rulesets/schema.py) enforces its own design rules."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.rulesets.schema import (CheckType, Citation, DataClass, Edit, ItemStatus, RuleSet, RuleSetItem,
                                 SlotValue, TemplateRule, Tier)

NOW = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)


def cite(quote="Estimated Quantity (Kilograms) 875,000 kg", node="PriceSchedule:Notes:(2)") -> Citation:
    return Citation(file="tender/09 Schedules.pdf", page=1, node_id=node, quote=quote, data_class=DataClass.SYNTHETIC)


def item(letter="b", status=ItemStatus.VERIFIED, **kw) -> RuleSetItem:
    template = kw.pop("template", "price_schedule")
    return RuleSetItem(letter=letter, title="Unit price quotation", part=Tier.A, template=template,
                       citation=cite("(b) The one-time unit price quotation", "Sched:CCS:(b)"),
                       slots={"estimated_quantity": SlotValue(value=875000, citation=cite(), verified=True)},
                       rules=[TemplateRule(id="price_schedule.unit_price_present", check=CheckType.FILLED,
                                           field="price_schedule.unit_price", tier=Tier.A)],
                       status=status, **kw)


def ruleset(items, status="draft", **kw) -> RuleSet:
    return RuleSet(project_id="SYN-2026-001", version=1, data_class=DataClass.SYNTHETIC, items=items,
                   created_by="chenyu", created_at=NOW, status=status, **kw)


def test_the_check_menu_has_twelve_kinds():
    assert len(CheckType) == 12
    assert CheckType.HUMAN_ONLY in CheckType


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
    rs = ruleset([item("b"), item("l", ItemStatus.NOVEL, template=None)])
    again = RuleSet.model_validate_json(rs.model_dump_json())
    assert again == rs
    assert again.item("l").template is None
