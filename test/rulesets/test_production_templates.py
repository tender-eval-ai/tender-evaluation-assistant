"""The production template library (app/rulesets/templates/, checklist J12): every file
loads, speaks our forms' vocabulary, stays neutral, and gives the verdicts the rule files
meant when the engine runs it."""
from __future__ import annotations

import re

import pytest

from app.checks.engine_bridge import evaluate
from app.checks.forms import FORMS
from app.rulesets.library import DEFAULT_DIR, load_templates
from app.rulesets.schema import Citation, ItemStatus, Part, RuleSetItem, SlotValue

TEMPLATES = load_templates(DEFAULT_DIR)


def test_the_library_holds_one_template_per_form_the_rule_files_cover():
    assert set(TEMPLATES) == {
        "board_resolution", "compliance_schedule", "contact_details", "contract_deposit", "information_schedule",
        "manufacturer_letter", "noncollusive_certificate", "particulars_of_goods", "price_schedule",
        "price_schedule_parts_c_d"}
    assert set(TEMPLATES) <= set(FORMS), "a template's id is our form id (J2 a)"


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_every_rule_reads_a_field_its_form_has(tid):
    form = FORMS[tid]
    for rule in TEMPLATES[tid].rules:
        prefix, _, name = rule.field.rpartition(".")
        assert prefix == tid and name in form.names, f"{rule.id}: {rule.field}"
        for other in rule.params.get("inputs", []):
            assert other in form.names, f"{rule.id}: input {other}"


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_a_rule_depends_only_on_rules_of_its_own_template(tid):
    ids = {r.id for r in TEMPLATES[tid].rules}
    for rule in TEMPLATES[tid].rules:
        assert rule.id.startswith(f"{tid}.") and set(rule.depends_on) <= ids, rule.id


def test_the_wording_is_our_own_and_neutral():
    """No tender number, no jurisdiction, no body's name, no currency (F6): a tender's own
    values live in its params file, outside git."""
    banned = re.compile(r"[A-Z]{1,2}\d{9,10}|Hong Kong|\bHK\b|HK\$|US\$|\bAUTH\b|\bDSD\b|the plant|Authority", re.IGNORECASE)
    for path in sorted(DEFAULT_DIR.glob("*.json")):
        found = banned.findall(path.read_text())
        assert not found, f"{path.name}: {found}"


# ---------------------------------------------------------------- through the engine
CITE = Citation(file="tender/schedules.pdf", page=1, quote="the schedule row", data_class="synthetic")


def item_for(tid: str, part: Part = Part.A, **slots) -> RuleSetItem:
    template = TEMPLATES[tid]
    return RuleSetItem(letter="a", title=template.form_name, part=part, template=tid, citation=CITE,
                       rules=[r.model_copy(deep=True) for r in template.rules],
                       slots={k: SlotValue(value=v, citation=CITE, verified=True) for k, v in slots.items()},
                       status=ItemStatus.VERIFIED)


def bid(tid: str, **values) -> dict:
    """What V3 and V4 leave for one form: every field of the menu, verified, blank unless given."""
    fields: dict = {}
    for f in FORMS[tid].all_fields:
        key = FORMS[tid].key(f.name)
        value = values.get(f.name)
        fields.update({key: value, f"{key}_redacted": False, f"{key}_confidence": 0.95,
                       f"{key}_page": {"doc": "offer.pdf", "page": 3, "seq": 3} if value is not None else None,
                       f"{key}_verification": {"verified": True}})
    return fields


def verdict(tid, fields, **slots):
    return evaluate(item_for(tid, **slots), fields, TEMPLATES[tid])


def statuses(result) -> dict[str, str]:
    return {f["field_id"].rpartition(".")[2]: f["status"] for f in result["fields"]}


def test_a_complete_price_schedule_passes_and_a_missing_unit_price_disqualifies():
    slots = {"estimated_quantity": 875000, "allowed_currencies": ["HK$", "US$"]}
    good = bid("price_schedule", document="Price Schedule", unit_price="HK$ 12.50", currency="HK$",
               quantity="875,000 kg", total="HK$ 10,937,500")
    assert verdict("price_schedule", good, **slots)["outcome"] == "pass"

    wrong = bid("price_schedule", document="Price Schedule", unit_price="HK$ 12.50", currency="HK$",
                quantity="1,000,000 kg", total="HK$ 1")
    s = statuses(verdict("price_schedule", wrong, **slots))
    assert s["quantity"] == "needs_review" and s["total"] == "needs_review", "a comparison never disqualifies"

    blank = bid("price_schedule", document="Price Schedule", currency="HK$", quantity="875,000 kg", total="HK$ 1")
    assert verdict("price_schedule", blank, **slots)["outcome"] == "disqualified"


def test_a_missing_certificate_is_dormant_until_requested():
    result = verdict("noncollusive_certificate", bid("noncollusive_certificate"))
    assert statuses(result) == {"document": "dormant"}, "its dependants wait for the certificate"
    signed = bid("noncollusive_certificate", document="Non-collusive Tendering Certificate",
                 tenderer_name="Bidder A Ltd", signature="J. Chan", date="12 March 2026")
    assert verdict("noncollusive_certificate", signed)["outcome"] == "pass"


def test_a_blank_that_only_a_condition_makes_required_goes_to_a_reviewer():
    """The engine does not act on `condition` yet (J12 question 2): a missing letter of intent
    may be a tenderer that makes the goods itself, so it is never a disqualification."""
    result = verdict("manufacturer_letter", bid("manufacturer_letter"))
    assert statuses(result) == {"document": "needs_review"}


def test_the_compliance_schedule_passes_blank_parts_and_excludes_an_express_non_compliance():
    blank = bid("compliance_schedule", document="Compliance Schedule")
    assert verdict("compliance_schedule", blank, default_delivery_days=60)["outcome"] == "pass"
    refused = bid("compliance_schedule", document="Compliance Schedule", part_b="not comply",
                  non_compliances="Part B: not comply")
    assert verdict("compliance_schedule", refused, default_delivery_days=60)["outcome"] == "disqualified"
    late = bid("compliance_schedule", document="Compliance Schedule", delivery_days="90 days")
    assert statuses(verdict("compliance_schedule", late, default_delivery_days=60))["delivery_days"] == "needs_review"


def test_blank_discounts_and_deposit_method_take_the_forms_defaults():
    assert verdict("price_schedule_parts_c_d", bid("price_schedule_parts_c_d"))["outcome"] == "pass"
    assert verdict("contract_deposit", bid("contract_deposit"))["outcome"] == "pass"
