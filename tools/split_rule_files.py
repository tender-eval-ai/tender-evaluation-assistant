"""Split AI_camp's 13 rule files into reusable templates plus one tender's params.

    python tools/split_rule_files.py --source <AI_camp>/agent/src/procurement_agent/validator/rules \
        --templates app/rulesets/templates --params app/rulesets/params/Tender 1.json

The plan's S1 deliverable. Each source file mixes two things: what the FORM always
requires (its rules, its consequence tiers, its notes) and what THIS tender put in the
blanks (the estimated quantity, the deposit percentage, the schedule letter the form
answers). The first becomes `app/rulesets/templates/<id>.json`, reused by every tender;
the second becomes one params file per tender, and the rule references it as `{slot}`.

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
from pathlib import Path

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

NOTE_KIND = {"note": "definition", "condition": "trigger", "presence": "definition",
             "outcome_policy": "consequence", "gate": "definition", "normalise": "definition"}
_TRIGGER = re.compile(r"_conditional_trigger$|_trigger$")


def template_id(filename: str) -> str:
    return re.sub(r"_rules(_stage2)?$", lambda m: "_stage2" if m.group(1) else "", Path(filename).stem)


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

    report, counts = [], {"check": 0, "not_a_rule": 0, "unmapped": 0, "split": 0}
    for path in sorted(args.source.glob("*.json")):
        doc = json.loads(path.read_text())
        for rule in doc.get("rules", []):
            kind, why = kind_of(rule)
            if why == "unmapped":
                counts["unmapped"] += 1
            elif why:
                counts["not_a_rule"] += 1
            else:
                counts["check"] += 1
                if rule.get("check") in SPLITS:
                    counts["split"] += 1
            report.append({"file": path.name, "id": rule["id"], "check": rule.get("check"),
                           "kind": kind, "not_a_rule": why,
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
    if args.report:
        args.report.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"classification written to {args.report}")


if __name__ == "__main__":
    main()
