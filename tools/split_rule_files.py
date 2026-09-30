"""Split AI_camp's 13 rule files into reusable templates plus one tender's params.

    python tools/split_rule_files.py --source <AI_camp>/agent/src/procurement_agent/validator/rules \
        --report <private>/classification.json

Today it classifies every rule and places its field; the report carries rule values,
so it goes outside git. The field map (checklist J2) names each file's template by our
form id and each rule's `field_id` by a key of that form (`app/checks/forms.py`). A
field the form does not have is reported as having no home, never guessed: that list
is what the forms need before the templates can be written. Writing the templates and
the params comes next, in our own words, never the rule files'.

The plan's S1 deliverable. Each source file mixes two things: what the FORM always
requires (its rules, its consequence tiers, its notes) and what THIS tender put in the
blanks (the estimated quantity, the deposit percentage, the schedule letter the form
answers). The first becomes `app/rulesets/templates/<form id>.json`, reused by every
tender; the second becomes one params file per tender, kept outside git beside the
answer keys, and the rule references it as `{slot}`.

The check-name mapping is `docs/check_kind_mapping.md`, which is authoritative: 44
AI_camp check names over 126 rules, 99 mapping to one of the twelve CheckTypes, one
splitting in two, and 27 that are not checks at all. This script does not re-derive
that mapping; it applies it, and refuses to guess. A rule it cannot place is reported,
never silently dropped or downgraded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.checks.forms import FORMS  # noqa: E402

# docs/check_kind_mapping.md, "By check name". A name mapping to a single kind is here;
# the four that split per rule are resolved by `PER_RULE` below.
KIND = {
    "filled": "filled", "conditional_filled": "filled", "conditional_explanation": "filled",
    "tick_box_declaration": "tick_box", "exactly_one_ticked": "tick_box",
    "strike_out_choice": "tick_box", "formatting": "tick_box",
    "range": "range", "conditional_value": "range", "compliance_match": "range",
    "substantiation_check": "range",
    "deadline_check": "date", "date_max_age": "date", "deadline": "date",
    "unit": "unit", "math": "math",
    "cross_document_match": "cross_document_match",
    "self_entry_if_tenderer_is_manufacturer": "cross_document_match",
    "checklist": "contains", "contains_all_elements": "contains",
    "contains_all_sections_with_content": "contains", "content_check": "contains",
    "text_match": "contains",
    "bundling_check": "document_present", "conditional_requirement": "document_present",
    "evidence_of_delivery": "document_present",
    "presence_of_accompanying_document": "document_present",
    "third_party_result": "human_only", "accredited_body_lookup": "human_only",
}

# Not checks. The value says where the entry goes instead, so nothing is lost.
NOT_A_RULE = {
    "context": "note",                 # an item note; a *_conditional_trigger becomes `condition`
    "umbrella_gate": "gate",           # expressed as depends_on on the rules it gates
    "on_request_trigger": "condition",
    "definitional_carveout": "note",   # a definition, and a condition on the rules it carves out
    "clarification_exception": "outcome_policy",
    "authority_discretion": "note",
    "na_allowed": "presence",          # the engine already reads "N/A" as not_applicable
    "overflow_allowed": "note",
    "reference_note": "note",
    "significant_figures": "normalise",
    "single_number": "normalise",
}

# "Names that split per rule": the same AI_camp check name means different kinds in
# different rules, so the mapping resolves these by rule id. Plus the one exception
# inside `filled`. Copied from docs/check_kind_mapping.md, not re-derived.
PER_RULE = {
    "noncollusive_certificate_signed": "signature",
    # content_criterion (8)
    "appendix_tenderer_address_not_postal_box": "contains",      # negated: must NOT contain a P.O. Box
    "board_resolution_applicability_by_entity_type": None,       # not a rule: the item's condition by entity type
    "event_disclosure_details_complete": "human_only",
    "price_schedule_part_c_discount_decimal_precision": "range",  # decimals in [0, 2]; there is no precision kind
    "sds_bilingual_latest_version": "human_only",
    "tender_sample_extra_charges": "human_only",
    "tender_sample_original_packing": "human_only",
    "tender_sample_sealed": "human_only",
    # document_form (3)
    "certified_true_copy_general_mechanism": None,               # not a rule: general mechanism, an item note
    "iso_certificate_original_or_certified_copy": "human_only",
    "test_report_original_or_certified_copy": "human_only",
    # value (2)
    "estimated_quantity_value": "value",                         # authority-printed constant
    "tender_sample_quantity": "range",                           # a minimum, so range with only min
}
SPLITS = {"date_validity_and_presence": ("date", "human_only")}

_TRIGGER = re.compile(r"_conditional_trigger$|_trigger$")

# J2 (a): a template's id is our form id. The rule file's name, without `_rules` and
# the stage suffix, to the form it describes. The Information Schedule's Stage II rules
# join its Stage I rules in one template; each rule keeps its stage.
TEMPLATE_OF_FILE = {
    "appendix_contact_details": "contact_details",
    "board_resolution_authorisation": "board_resolution",
    "certification_track_record": "documentary_evidence",
    "compliance_schedule": "compliance_schedule",
    "contract_deposit_method": "contract_deposit",
    "information_schedule": "information_schedule",
    "manufacturer_letter_of_intent": "manufacturer_letter",
    "noncollusive_tendering_certificate": "noncollusive_certificate",
    "particulars_of_goods_schedule": "particulars_of_goods",
    "price_schedule_parts_c_d": "price_schedule_parts_c_d",
    "price_schedule": "price_schedule",
    "tender_sample_plant_trial": "tender_sample_declaration",
}

# J2 (b): a rule's `field_id` to the field of its form that holds the same thing.
# Only where the form has that field; a field_id missing here has no home yet and is
# reported. Two are close rather than word for word, and say why.
FIELD_OF = {
    "contact_details": {},
    "compliance_schedule": {"compliance_part_b_earlier_delivery_days": "delivery_days"},
    "contract_deposit": {"contract_deposit_method": "method"},
    "manufacturer_letter": {"manufacturer_letter_of_intent": "document"},  # the letter itself is present
    "noncollusive_certificate": {},
    "particulars_of_goods": {
        "place_of_origin": "country_of_origin",
        "name_of_manufacturer": "manufacturer",
        "brand_product_name": "product_name",
        "packing_plant_net_weight_kg": "packaging",           # the Packing row, net weight in kg
        "percentage_activity": "active_ingredient_pct",       # a polyelectrolyte's activity is its active content
        "bulk_density": "bulk_density",
    },
    "price_schedule_parts_c_d": {"banking_details": "part_d"},
    "price_schedule": {"estimated_quantity": "quantity", "one_time_unit_price": "unit_price",
                       "estimated_goods_price": "total", "optimal_dosage": "optimal_dosage"},
}

# One field_id that different rules read different parts of: the rule decides.
FIELD_OF_RULE = {
    "appendix_tenderer_address_not_postal_box": "address",
    "noncollusive_certificate_filled": "document",
    "noncollusive_certificate_tenderer_identified": "tenderer_name",
    "noncollusive_certificate_signed": "signature",
}

# Kinds a person decides from the document as a whole: they read no field.
NO_FIELD_KINDS = {"human_only"}


def template_id(filename: str) -> str:
    """Our form id for a rule file; the file's own stem when the map has none (reported)."""
    stem = re.sub(r"_rules(_stage2)?$", "", Path(filename).stem)
    return TEMPLATE_OF_FILE.get(stem, stem)


def field_of(template: str, rule: dict, kind: str | None) -> tuple[str | None, str]:
    """(`<form>.<field>` key, status): status is `mapped`, `not_needed` or `no_home`."""
    if kind is None or kind in NO_FIELD_KINDS:
        return None, "not_needed"
    name = FIELD_OF_RULE.get(rule["id"]) or FIELD_OF.get(template, {}).get(rule.get("field_id"))
    if name is None:
        return None, "no_home"
    return f"{template}.{name}", "mapped"


def kind_of(rule: dict) -> tuple[str | None, str | None]:
    """(CheckType, reason-it-is-not-a-rule). Exactly one is set."""
    name = rule.get("check")
    if rule["id"] in PER_RULE:
        kind = PER_RULE[rule["id"]]
        return (kind, None) if kind else (None, "note")
    if name in SPLITS:
        return SPLITS[name][0], None          # the second half is reported, not invented
    if name in NOT_A_RULE:
        return None, NOT_A_RULE[name]
    if name in KIND:
        return KIND[name], None
    return None, "unmapped"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--report", type=Path, help="write the per-rule classification as JSON")
    args = ap.parse_args()

    wrong = [f"{t}.{n}" for t, fields in FIELD_OF.items() for n in fields.values() if n not in FORMS[t].names]
    if wrong:
        sys.exit(f"the field map names fields its forms do not have: {', '.join(wrong)}")

    report, counts = [], {"check": 0, "not_a_rule": 0, "unmapped": 0, "split": 0}
    homeless: dict[str, set[str]] = defaultdict(set)
    for path in sorted(args.source.glob("*.json")):
        doc = json.loads(path.read_text())
        template = template_id(path.name)
        for rule in doc.get("rules", []):
            kind, why = kind_of(rule)
            field, placed = field_of(template, rule, kind)
            if placed == "no_home":
                homeless[template].add(rule.get("field_id") or f"(no field_id: {rule['id']})")
            if why == "unmapped":
                counts["unmapped"] += 1
            elif why:
                counts["not_a_rule"] += 1
            else:
                counts["check"] += 1
                if rule.get("check") in SPLITS:
                    counts["split"] += 1
            report.append({"file": path.name, "template": template, "id": rule["id"], "check": rule.get("check"),
                           "kind": kind, "not_a_rule": why, "field": field, "field_status": placed,
                           "tier": rule.get("consequence_tier"),
                           "has_own_outcomes": bool(rule.get("outcomes")),
                           "transform": rule.get("transform", {}).get("operation") if rule.get("transform") else None,
                           "depends_on": rule.get("depends_on"),
                           "stage": rule.get("stage") or doc.get("stage") or "I",
                           "field_id": rule.get("field_id"),
                           "value": rule.get("value"),
                           "must_be": rule.get("must_be"),
                           "is_trigger": bool(_TRIGGER.search(rule["id"]))})
    print(f"{len(report)} rules: {counts['check']} checks "
          f"({counts['split']} of them the split name), {counts['not_a_rule']} not a rule, "
          f"{counts['unmapped']} UNMAPPED")
    placed = [r["field_status"] for r in report]
    print(f"fields: {placed.count('mapped')} mapped, {placed.count('not_needed')} not needed, "
          f"{placed.count('no_home')} with no home in their form yet")
    for template in sorted(homeless):
        print(f"  {template}: {', '.join(sorted(homeless[template]))}")
    if args.report:
        args.report.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"classification written to {args.report}")


if __name__ == "__main__":
    main()
