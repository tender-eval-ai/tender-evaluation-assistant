"""The production template library (app/rulesets/templates/, checklist J12): every file
loads, speaks our forms' vocabulary, stays neutral, and gives the verdicts the rule files
meant when the engine runs it."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.checks.engine_bridge import evaluate, stage_summary
from app.checks.forms import FORMS
from app.rulesets.library import DEFAULT_DIR, load_templates
from app.rulesets.schema import Citation, ItemStatus, Part, RuleSetItem, SlotValue

TEMPLATES = load_templates(DEFAULT_DIR)


def test_the_library_holds_one_template_per_form():
    assert set(TEMPLATES) == set(FORMS), "every form has a template, and a template's id is our form id (J2 a)"


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
    """No tender number, jurisdiction, body's name, currency or clause reference (F6): a
    tender's own values live in its params file, outside git."""
    banned = re.compile(
        r"[A-Z]{1,2}\d{9,10}|Hong Kong|\bHK\b|\bAUTH\b|\bDSD\b|the plant|Authority"
        r"|HK\$|US\$|€|£|¥|\b(?:HKD|USD|EUR|GBP|RMB|CNY|dollars?|pounds? sterling|euros?)\b"
        r"|\b(?:Paragraph|Clause|Section|Note)\s+\d", re.IGNORECASE)
    for path in sorted(DEFAULT_DIR.glob("*.json")):
        found = banned.findall(path.read_text())
        assert not found, f"{path.name}: {found}"


@pytest.mark.skipif(not os.environ.get("TEMPLATE_PARAMS_FILE"), reason="a real tender's params file, outside git")
def test_no_value_from_a_real_tenders_params_is_in_a_template():
    """Opt-in: TEMPLATE_PARAMS_FILE=<private>/params/<tender>.json (tools/split_rule_files.py --params)."""
    values = []
    for slots in json.loads(Path(os.environ["TEMPLATE_PARAMS_FILE"]).read_text()).values():
        for value in slots.values():
            values += value if isinstance(value, list) else [value]
    text = " ".join(path.read_text() for path in DEFAULT_DIR.glob("*.json")).lower()
    # A figure, or a phrase of four words or more: generic form words ("Tender Closing Date")
    # are shared by every tender and are not a leak.
    specific = [v for v in values if isinstance(v, (int, float)) and abs(v) >= 10 or len(str(v).split()) >= 4]
    leaked = [v for v in specific if re.search(rf"(?<![\w.]){re.escape(str(v).lower())}(?![\w.])", text)]
    assert not leaked, leaked


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


def stage_i(result) -> str:
    """The item's Stage I outcome: what the completeness check decides (Stage II checks, some of
    them always a reviewer's, roll up separately)."""
    return stage_summary({"x": result}, "I")["outcome"]


def test_a_complete_price_schedule_passes_and_a_missing_unit_price_disqualifies():
    slots = {"estimated_quantity": 875000, "allowed_currencies": ["HK$", "US$"], "dosage_unit": "kg per tonne"}
    good = bid("price_schedule", document="Price Schedule", unit_price="HK$ 12.50", currency="HK$",
               quantity="875,000 kg", total="HK$ 10,937,500", optimal_dosage="4.3 kg per tonne")
    assert verdict("price_schedule", good, **slots)["outcome"] == "pass"
    no_dosage = {**good, "price_schedule.optimal_dosage": None}
    dosage = [f["status"] for f in verdict("price_schedule", no_dosage, **slots)["fields"]
              if f["field_id"] == "price_schedule.optimal_dosage"]
    assert dosage == ["needs_review"], "required only where the schedule asks for one: a reviewer confirms"

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
    result = verdict("compliance_schedule", blank, default_delivery_days=60)
    assert stage_i(result) == "pass" and stage_summary({"x": result}, "II")["outcome"] == "needs_review", \
        "the Authority's own satisfaction is a reviewer's call at Stage II"
    refused = bid("compliance_schedule", document="Compliance Schedule", part_b="not comply",
                  non_compliances="Part B: not comply")
    assert verdict("compliance_schedule", refused, default_delivery_days=60)["outcome"] == "disqualified"
    late = bid("compliance_schedule", document="Compliance Schedule", delivery_days="90 days")
    assert statuses(verdict("compliance_schedule", late, default_delivery_days=60))["delivery_days"] == "needs_review"


@pytest.mark.parametrize("answer, status", [
    ("Comply", "pass"), ("Complied", "pass"), ("Yes", "pass"), ("\u2713", "pass"),
    ("Cannot comply", "needs_review"), ("Unable to comply", "needs_review"), ("No", "needs_review"),
    ("Partially comply", "needs_review"), ("X", "needs_review"), ("Will comply except clause 3", "needs_review")])
def test_a_part_answer_that_is_not_plainly_complying_goes_to_a_reviewer(answer, status):
    """#117: "not comply" alone missed a refusal worded another way, and an "X" may be a tick or a cross."""
    marked = bid("compliance_schedule", document="Compliance Schedule", part_b=answer)
    assert statuses(verdict("compliance_schedule", marked, default_delivery_days=60))["part_b"] == status


def test_a_missing_compliance_schedule_leaves_no_stage_ii_review_row():
    """#117: the Authority's own satisfaction is judged on a schedule that was submitted."""
    result = verdict("compliance_schedule", bid("compliance_schedule"), default_delivery_days=60)
    assert stage_i(result) == "dormant" and stage_summary({"x": result}, "II")["outcome"] == "pass"


def test_blank_discounts_and_deposit_method_take_the_forms_defaults():
    assert verdict("price_schedule_parts_c_d", bid("price_schedule_parts_c_d"))["outcome"] == "pass"
    assert verdict("contract_deposit", bid("contract_deposit"))["outcome"] == "pass"
    precise = bid("price_schedule_parts_c_d", discount_7day="2.505%", discount_8to14day="1.5%")
    s = statuses(verdict("price_schedule_parts_c_d", precise))
    assert (s["discount_7day"], s["discount_8to14day"]) == ("needs_review", "pass"), "at most two decimals, as printed"


def test_a_post_office_box_address_goes_to_a_reviewer():
    filled = dict(document="Contact Details", contact_person="A. Lee", telephone="1234", facsimile="5678",
                  email="a@b.example", process_agent="n/a")
    assert verdict("contact_details", bid("contact_details", address="12 Harbour Road", **filled))["outcome"] == "pass"
    boxed = verdict("contact_details", bid("contact_details", address="P.O. Box 88, Central", **filled))
    assert boxed["outcome"] == "needs_review" and "should not contain 'P.O. Box'" in boxed["reasons"][0]


def test_documents_asked_for_as_evidence_are_checked_where_they_are_read():
    slots = {"certified_activity": ["manufacture of flocculants"], "tender_closing_date": "2026-06-30",
             "safety_data_sheet_sections": ["identification", "first aid"],
             "earliest_specifications_date": "2025-06-30", "evaluation_report_contents": ["method", "conclusions"]}
    complete = bid("documentary_evidence", document="Documentary evidence",
                   quality_certificate="QMS-1 by Cert Body", quality_certificate_scope="Manufacture of flocculants",
                   quality_certificate_site="1 Plant Road", quality_certificate_expiry="1 January 2028",
                   accreditation_schedule="Schedule of accreditation", safety_data_sheet="SDS for Floc-9",
                   safety_data_sheet_sections="Identification; Hazards; First aid", product_specifications="Floc-9 specs",
                   product_specifications_date="1 March 2026", evaluation_report="Evaluation report",
                   evaluation_report_contents="Method; Results; Conclusions")
    fields = {**complete, "particulars_of_goods.manufacturing_plant_address": "1 Plant Road"}
    s = statuses(verdict("documentary_evidence", fields, **slots))
    assert {k: s[k] for k in ("quality_certificate_scope", "quality_certificate_site", "quality_certificate_expiry",
                              "safety_data_sheet_sections", "product_specifications_date",
                              "evaluation_report_contents")} == dict.fromkeys(
        ("quality_certificate_scope", "quality_certificate_site", "quality_certificate_expiry",
         "safety_data_sheet_sections", "product_specifications_date", "evaluation_report_contents"), "pass")
    assert s["quality_certificate"] == "needs_review", "a reviewer judges the copy and the issuer"
    assert s["laboratory_appointed_date"] == "dormant", "a conformance test waits until the Authority asks"

    missing = statuses(verdict("documentary_evidence", bid("documentary_evidence"), **slots))
    assert missing["quality_certificate"] == "needs_review", "required only when the tender asks for it"
    assert "quality_certificate_scope" not in missing, "the checks on a missing certificate wait for it"


def test_a_tender_sample_is_dormant_until_a_reviewer_records_it():
    slots = {"sample_min_kg": 600, "sample_pack_min_kg": 500, "sample_pack_max_kg": 950,
             "sample_label_particulars": ["tender reference", "tenderer"]}
    assert statuses(verdict("tender_sample_declaration", bid("tender_sample_declaration"), **slots)) == \
        {"document": "dormant", "sample_received_date": "dormant"}
    recorded = bid("tender_sample_declaration", sample_received_date="3 July 2026", sample_net_weight_kg="400",
                   sample_pack_net_weight_kg="700", sample_label="Tender reference T-1; Tenderer: Bidder A",
                   sample_condition="original packing, sealed")
    s = verdict("tender_sample_declaration", recorded, **slots)
    assert statuses(s)["sample_net_weight_kg"] == "needs_review" and "at least 600" in " ".join(s["reasons"])
    assert statuses(s)["sample_label"] == "pass"
    assert statuses(s)["sample_charges"] == "dormant", "a reviewer field left blank waits, whatever the rule says"


def test_the_particulars_report_rows_left_empty_and_a_self_made_product():
    base = dict(document="Particulars of Goods Schedule", country_of_origin="Freedonia", manufacturer="Bidder A Ltd",
                product_name="Floc-9", manufacturing_plant_address="1 Plant Road", product_code="F9",
                active_ingredient_pct="95", bulk_density="0.7", packaging="bags", net_weight_kg="750")
    fields = {**bid("particulars_of_goods", **base), "offer_to_be_bound.tenderer_name": "Bidder A Ltd",
              "contact_details.address": "1 Plant Road"}
    slots = {"net_weight_min_kg": 500, "net_weight_max_kg": 950}
    whole = verdict("particulars_of_goods", fields, **slots)
    assert {k: v for k, v in statuses(whole).items() if k != "rows_left_blank"} == dict.fromkeys(
        [k for k in statuses(whole) if k != "rows_left_blank"], "pass")
    assert statuses(whole)["rows_left_blank"] == "needs_review", \
        "'no row empty' cannot be checked, so a reviewer confirms it (a stop-gap, #100 review)"
    gaps = {**fields, **bid("particulars_of_goods", **base, rows_left_blank="Particle size; pH")}
    assert statuses(verdict("particulars_of_goods", gaps, **slots))["rows_left_blank"] == "dormant"


def test_the_synthetic_case_still_disqualifies_tenderer_c_against_the_production_library(monkeypatch):
    """The stored all-items rule set names tier `critical` on item (l); every template defines
    the three presence tiers, so its rules are checked and a missing certificate still
    disqualifies (#99 review, point 1)."""
    from app.checks.engine_bridge import decide
    from test.checks.conftest import RULESET_ALL, read_offer

    monkeypatch.delenv("RULESET_TEMPLATES_DIR", raising=False)
    c = decide(read_offer("Tenderer_C"), RULESET_ALL)
    assert c["items"]["l"]["outcome"] == "disqualified" and c["stage1"]["outcome"] == "disqualified"
    d = decide(read_offer("Tenderer_D", verify=True), RULESET_ALL)
    assert d["items"]["l"]["outcome"] == "pass", "a complete certificate still passes"


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_every_template_defines_the_tiers_a_schedule_part_maps_to(tid):
    """J12 question 1: a form's presence rule takes its tier from the item's Part."""
    assert {"critical", "mandatory_on_request", "discretionary"} <= set(TEMPLATES[tid].consequences)
    assert any(r.id == f"{tid}.submitted" and r.check.value == "document_present" for r in TEMPLATES[tid].rules)
