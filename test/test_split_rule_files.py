"""The field map in tools/split_rule_files.py (checklist J2): templates are named by our
form ids, and a rule's field is a key of that form or is reported, never guessed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import split_rule_files as split  # noqa: E402
from app.checks.forms import FORMS  # noqa: E402


def test_every_template_is_one_of_our_forms():
    assert set(split.TEMPLATE_OF_FILE.values()) <= set(FORMS)


def test_every_mapped_field_is_a_field_of_its_form():
    for template, fields in split.FIELD_OF.items():
        for name in fields.values():
            assert name in FORMS[template].names, f"{template}.{name}"
    by_rule = {"appendix_tenderer_address_not_postal_box": "contact_details",
               "noncollusive_certificate_filled": "noncollusive_certificate",
               "noncollusive_certificate_tenderer_identified": "noncollusive_certificate",
               "noncollusive_certificate_signed": "noncollusive_certificate"}
    assert set(by_rule) == set(split.FIELD_OF_RULE)
    for rule_id, template in by_rule.items():
        assert split.FIELD_OF_RULE[rule_id] in FORMS[template].names


def test_template_id_drops_the_suffix_and_joins_stage_two():
    assert split.template_id("price_schedule_rules.json") == "price_schedule"
    assert split.template_id("noncollusive_tendering_certificate_rules.json") == "noncollusive_certificate"
    assert split.template_id("information_schedule_rules_stage2.json") == "information_schedule"
    assert split.template_id("a_new_form_rules.json") == "a_new_form", "unknown files keep their name, and are reported"


def test_a_field_the_form_lacks_is_reported_not_guessed():
    rule = {"id": "particle_size_filled", "check": "filled", "field_id": "particle_size"}
    assert split.field_of("particulars_of_goods", rule, "filled") == (None, "no_home")


def test_a_rule_that_needs_no_field():
    assert split.field_of("information_schedule", {"id": "x", "field_id": "iso_certificate"}, "human_only") == \
        (None, "not_needed")
    assert split.field_of("price_schedule", {"id": "x", "field_id": "optimal_dosage"}, None) == (None, "not_needed")


def test_the_rule_decides_when_one_field_id_holds_several_fields():
    signed = {"id": "noncollusive_certificate_signed", "check": "filled", "field_id": "noncollusive_certificate"}
    kind, _ = split.kind_of(signed)
    assert split.field_of("noncollusive_certificate", signed, kind) == ("noncollusive_certificate.signature", "mapped")
    price = {"id": "unit_price_filled", "check": "filled", "field_id": "one_time_unit_price"}
    assert split.field_of("price_schedule", price, "filled") == ("price_schedule.unit_price", "mapped")
