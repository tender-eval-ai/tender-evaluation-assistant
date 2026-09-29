"""Split AI_camp's 13 rule files into reusable templates plus one tender's params.

    python tools/split_rule_files.py --source <AI_camp>/agent/src/procurement_agent/validator/rules \
        --report <private>/classification.json --templates app/rulesets/templates \
        --params <private>/params/Tender 1.json

It classifies every rule and places its field; the report carries rule values, so it
goes outside git. The field map (checklist J2) names each file's template by our form
id and each rule's `field_id` by a key of that form (`app/checks/forms.py`). A field the
form does not have is reported as having no home, never guessed.

The templates themselves (`app/rulesets/templates/`, checklist J12) are written by hand,
in our own words, never the rule files'. `--templates` checks them against the rule
files: every check whose field has a home either has a template rule of the same kind on
the same field, or is listed as left out, so nothing is dropped silently. `--params`
writes the rule files' tender's own values under the templates' slot names, the other
half of the split; like the report, it stays outside git.

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
    "estimated_quantity_value": "value",                         # public-printed constant
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

# J2 (b): a rule's `field_id` to the field of its form that holds the same thing: a name
# in the rule file's own form, or a whole `<form>.<field>` key when the thing lives in
# another form (J12: a document has one home, #76 point 2). A field_id missing here has
# no home and is reported. The close rather than word-for-word ones say why.
FIELD_OF = {
    # The tenderer's contact block is five fields of the form (#76 review, point 4); the
    # rule's own `field_id` names the block, and the address stands for it here.
    "contact_details": {"tenderer_contact_details": "address", "process_agent_contact_details": "process_agent"},
    "compliance_schedule": {"compliance_part_b_earlier_delivery_days": "delivery_days",
                            "compliance_part_a": "part_a", "compliance_part_b": "part_b",
                            "compliance_part_c": "part_c", "compliance_part_d": "part_d",
                            "compliance_part_d_longer_shelf_life_months": "shelf_life_months"},
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
        "address_of_manufacturing_plant": "manufacturing_plant_address",
        "product_code_number": "product_code",
        # The rows that describe one tender's product: one field says which are empty (J12).
        **{row: "rows_left_blank" for row in (
            "physical_form", "particle_size", "cationicity_by_colloid_titration", "molecular_weight_distribution",
            "effective_ph_range", "ph_of_half_percent_solution")},
    },
    # Tables B to D (e2b3189); the documents the rows point to are read where the tender asks for them.
    "information_schedule": {
        **{name: name for name in (
            "tenderer_name", "principal_place_of_business", "business_entity_type", "shareholders_ownership",
            "business_experience_length", "directors_partners_names", "incorporation_place_date",
            "business_profile_info", "business_registration_certificate", "memorandum_articles_of_association",
            "latest_annual_return", "employees_compensation_insurance", "subcontractor_name",
            "subcontractor_place_of_business", "subcontractor_obligations", "subcontractor_undertaking",
            "subcontractor_overseas_legal_opinion", "subcontractor_service_centre_location", "event_disclosure_box")},
        "tenderer_contact_details": "telephone",             # with fax and e-mail, each its own rule
        "iso_certificate": "documentary_evidence.quality_certificate",
        "safety_data_sheet": "documentary_evidence.safety_data_sheet",
        "product_specifications": "documentary_evidence.product_specifications",
        "evaluation_report": "documentary_evidence.evaluation_report",
        "test_report_lab_appointment": "documentary_evidence.laboratory_appointed_date",
        "test_report_submission": "documentary_evidence.test_report_received_date",
        "test_report_document_form": "documentary_evidence.test_report",
        "tenderers_declaration_independence": "documentary_evidence.laboratory_independence_declaration",
        "tenderers_declaration_bundling": "documentary_evidence.laboratory_independence_declaration",
        "board_resolution_extract": "board_resolution.document",
    },
    "price_schedule_parts_c_d": {"banking_details": "part_d", "discount_7day": "discount_7day",
                                 "discount_8to14day": "discount_8to14day"},
    "price_schedule": {"estimated_quantity": "quantity", "one_time_unit_price": "unit_price",
                       "estimated_goods_price": "total", "optimal_dosage": "optimal_dosage"},
    # A sample is delivered on request, after closing: a reviewer records it (FieldDef.by).
    "tender_sample_declaration": {"tender_sample": "sample_received_date",
                                  "additional_tender_sample": "additional_sample_received_date",
                                  "plant_trial": "plant_trial_result"},
}

# One field_id that different rules read different parts of: the rule decides. Also the
# field a reviewer's (`human_only`) check is about, so it is placed like any other.
FIELD_OF_RULE = {
    "appendix_tenderer_address_not_postal_box": "contact_details.address",
    "noncollusive_certificate_filled": "noncollusive_certificate.document",
    "noncollusive_certificate_tenderer_identified": "noncollusive_certificate.tenderer_name",
    "noncollusive_certificate_signed": "noncollusive_certificate.signature",
    "packing_plant_net_weight_range": "particulars_of_goods.net_weight_kg",   # the number, not the printed row
    "event_disclosure_tick_formatting": "information_schedule.event_disclosure_box",
    "unit_price_unit": "price_schedule.currency",          # the form reads the currency as its own field
    "iso_certificate_accompanied_by_schedules": "documentary_evidence.accreditation_schedule",
    "iso_certificate_scope_check": "documentary_evidence.quality_certificate_scope",
    "iso_certificate_address_match": "documentary_evidence.quality_certificate_site",
    "iso_certificate_validity_and_logo": "documentary_evidence.quality_certificate_expiry",
    "sds_content_complete": "documentary_evidence.safety_data_sheet_sections",
    "product_specs_issue_date": "documentary_evidence.product_specifications_date",
    "evaluation_report_content_complete": "documentary_evidence.evaluation_report_contents",
    "test_report_compliance_with_product_specs": "documentary_evidence.test_report",
    "tender_sample_quantity": "tender_sample_declaration.sample_net_weight_kg",
    "tender_sample_pack_size": "tender_sample_declaration.sample_pack_net_weight_kg",
    "tender_sample_label_complete": "tender_sample_declaration.sample_label",
    # human_only: what a reviewer looks at
    "iso_certificate_original_or_certified_copy": "documentary_evidence.quality_certificate",
    "iso_certificate_issuer_accreditation": "documentary_evidence.quality_certificate",
    "test_report_original_or_certified_copy": "documentary_evidence.test_report",
    "sds_bilingual_latest_version": "documentary_evidence.safety_data_sheet",
    "event_disclosure_details_complete": "information_schedule.event_disclosure_box",
    "compliance_government_dissatisfaction_gate": "compliance_schedule.document",
    "tender_sample_original_packing": "tender_sample_declaration.sample_condition",
    "tender_sample_sealed": "tender_sample_declaration.sample_condition",
    "tender_sample_extra_charges": "tender_sample_declaration.sample_charges",
    "plant_trial_effectiveness": "tender_sample_declaration.plant_trial_result",
}

# Kinds a person decides from the document as a whole: placed only through FIELD_OF_RULE.
NO_FIELD_KINDS = {"human_only"}

# The rule files' tender-specific values, by the template slots that now hold them: the
# rule's id to [(template, slot, how to read the value from the rule's `value`)].
SLOT_OF_RULE = {
    "estimated_quantity_value": [("price_schedule", "estimated_quantity", lambda v: v)],
    "unit_price_unit": [("price_schedule", "allowed_currencies", lambda v: v)],
    "dosage_unit": [("price_schedule", "dosage_unit", lambda v: v)],
    "compliance_part_b_earlier_delivery_proposal": [("compliance_schedule", "default_delivery_days",
                                                     lambda v: v["default_days"])],
    "compliance_part_d_longer_shelf_life_proposal": [("compliance_schedule", "default_shelf_life_months",
                                                      lambda v: v["default_months"])],
    "packing_plant_net_weight_range": [("particulars_of_goods", "net_weight_min_kg", lambda v: v["min"]),
                                       ("particulars_of_goods", "net_weight_max_kg", lambda v: v["max"])],
    "sds_content_complete": [("documentary_evidence", "safety_data_sheet_sections", lambda v: v)],
    "evaluation_report_content_complete": [("documentary_evidence", "evaluation_report_contents", lambda v: v)],
    "tender_sample_quantity": [("tender_sample_declaration", "sample_min_kg", lambda v: v["min_kg"])],
    "tender_sample_pack_size": [("tender_sample_declaration", "sample_pack_min_kg", lambda v: v["min_kg"]),
                                ("tender_sample_declaration", "sample_pack_max_kg", lambda v: v["max_kg"])],
    "tender_sample_label_complete": [("tender_sample_declaration", "sample_label_particulars", lambda v: v)],
}


def resolve(template: str, name: str) -> str:
    """A map entry as a `<form>.<field>` key: a bare name belongs to the rule file's own form."""
    return name if "." in name else f"{template}.{name}"


def template_id(filename: str) -> str:
    """Our form id for a rule file; the file's own stem when the map has none (reported)."""
    stem = re.sub(r"_rules(_stage2)?$", "", Path(filename).stem)
    return TEMPLATE_OF_FILE.get(stem, stem)


def field_of(template: str, rule: dict, kind: str | None) -> tuple[str | None, str]:
    """(`<form>.<field>` key, status): status is `mapped`, `not_needed` or `no_home`."""
    if kind is None or (kind in NO_FIELD_KINDS and rule["id"] not in FIELD_OF_RULE):
        return None, "not_needed"
    name = FIELD_OF_RULE.get(rule["id"]) or FIELD_OF.get(template, {}).get(rule.get("field_id"))
    if name is None:
        return None, "no_home"
    return resolve(template, name), "mapped"


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


# The kinds the engine decides by presence alone (blank, filled, redacted): one stands
# for another, as a rule file's "filled" on a whole document is a template's
# "document_present" on its heading.
PRESENCE_KINDS = {"filled", "document_present", "signature", "tick_box"}


def left_out(report: list[dict], templates: dict) -> dict[str, list[str]]:
    """{template: [rule-file rule ids]}: the checks with a home that no template rule of the
    same kind on the same field carries. A template the library lacks leaves all of its."""
    group = lambda kind: "presence" if kind in PRESENCE_KINDS else kind  # noqa: E731
    rules = [r for t in templates.values() for r in t.rules]
    have = {(r.field, group(r.check.value)) for r in rules}
    judged = {r.field for r in rules if r.check.value == "human_only"}   # a reviewer judges what the kinds can't
    checked = {r.field for r in rules}
    out: dict[str, list[str]] = defaultdict(list)
    for r in report:
        if r["field_status"] != "mapped" or (r["field"], group(r["kind"])) in have or r["field"] in judged:
            continue
        if r["kind"] == "human_only" and r["field"] in checked:
            continue
        out[r["template"]].append(r["id"])
    return dict(out)


def params_of(source: Path) -> dict[str, dict]:
    """{template: {slot: value}} from the rule files' own tender."""
    out: dict[str, dict] = defaultdict(dict)
    for path in sorted(source.glob("*.json")):
        for rule in json.loads(path.read_text()).get("rules", []):
            for template, slot, read in SLOT_OF_RULE.get(rule["id"], []):
                out[template][slot] = read(rule["value"])
    return dict(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--report", type=Path, help="write the per-rule classification as JSON")
    ap.add_argument("--templates", type=Path, help="list the rule-file checks these templates leave out")
    ap.add_argument("--params", type=Path, help="write the rule files' tender values by template slot, as JSON")
    args = ap.parse_args()

    keys = [resolve(t, n) for t, fields in FIELD_OF.items() for n in fields.values()] + list(FIELD_OF_RULE.values())
    wrong = [k for k in keys if k.partition(".")[0] not in FORMS or k.partition(".")[2] not in FORMS[k.partition(".")[0]].names]
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
    if args.templates:
        from app.rulesets.library import load_templates
        templates = load_templates(args.templates)
        missing = left_out(report, templates)
        checks = sum(r["field_status"] == "mapped" for r in report)
        print(f"templates: {len(templates)}; of {checks} checks with a home, "
              f"{checks - sum(map(len, missing.values()))} have a template rule, left out:")
        for template in sorted(missing):
            print(f"  {template}: {', '.join(missing[template])}")
    if args.params:
        args.params.parent.mkdir(parents=True, exist_ok=True)
        args.params.write_text(json.dumps(params_of(args.source), indent=1, ensure_ascii=False))
        print(f"params written to {args.params}")


if __name__ == "__main__":
    main()
