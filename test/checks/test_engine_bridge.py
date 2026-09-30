"""V6: the fixture rule set for item (l) evaluated by app/engine through the bridge."""
import pytest

from app.checks.engine_bridge import decide_item_l, evaluate, rules_doc
from test.checks.item_l import PREFIX
from app.rulesets.schema import RuleSet
from test.checks.conftest import RULESET

RS = RuleSet.model_validate(RULESET)
ITEM = RS.item("l")


def fields(document="Non-collusive Tendering Certificate", signature="authorised signatory", name="Tenderer B",
           date="12 August 2026", redacted=()):
    out = {}
    for key, value in (("document", document), ("signature", signature), ("tenderer_name", name), ("date", date)):
        out[f"{PREFIX}.{key}"] = None if key in redacted else value
        out[f"{PREFIX}.{key}_redacted"] = key in redacted
        out[f"{PREFIX}.{key}_confidence"] = 0.9
        out[f"{PREFIX}.{key}_page"] = {"doc": "offer.pdf", "page": 13, "seq": 13}
    return out


def test_the_fixture_is_a_valid_confirmed_rule_set_with_four_rules_on_item_l():
    assert RS.status == "confirmed" and RS.version == 1 and RS.data_class == "synthetic"
    assert ITEM.part == "A" and [r.id for r in ITEM.rules] == [
        f"{PREFIX}.submitted", f"{PREFIX}.signed", f"{PREFIX}.tenderer_identified", f"{PREFIX}.dated"]


def test_the_bridge_speaks_the_engine_vocabulary():
    doc = rules_doc(ITEM)
    signed = next(r for r in doc["rules"] if r["id"] == f"{PREFIX}.signed")
    assert signed["field_id"] == f"{PREFIX}.signature" and signed["depends_on"] == f"{PREFIX}.submitted"
    assert signed["outcomes"]["blank"]["status"] == "disqualified" and signed["consequence_tier"] is None
    assert doc["compliance_schedule_item"] == "(l)" and doc["consequence_tiers"] == {}


def test_a_complete_signed_dated_certificate_passes():
    v = evaluate(ITEM, fields())
    assert v["outcome"] == "pass" and v["worst"] == "pass" and v["reasons"] == []
    assert [f["status"] for f in v["fields"]] == ["pass"] * 4 and v["part"] == "A"
    assert v["fields"][0]["page"] == {"doc": "offer.pdf", "page": 13, "seq": 13}


def test_a_missing_certificate_disqualifies_and_skips_the_dependent_checks():
    v = evaluate(ITEM, fields(document=None, signature=None, name=None, date=None))
    assert v["outcome"] == "disqualified"
    assert [f["field_id"] for f in v["fields"]] == [f"{PREFIX}.document"], "dependents of a disqualified check are not run"
    assert "missing" in v["reasons"][0]


def test_an_unsigned_certificate_disqualifies_but_the_name_is_still_checked():
    v = evaluate(ITEM, fields(signature=None, date=None))
    assert v["outcome"] == "disqualified"
    statuses = {f["field_id"]: f["status"] for f in v["fields"]}
    assert statuses[f"{PREFIX}.signature"] == "disqualified" and statuses[f"{PREFIX}.tenderer_name"] == "pass"
    assert f"{PREFIX}.date" not in statuses, "dated depends on signed"


def test_a_redacted_signature_needs_review_rather_than_disqualifying():
    v = evaluate(ITEM, fields(redacted=("signature",)))
    statuses = {f["field_id"]: f["status"] for f in v["fields"]}
    assert v["outcome"] == "needs_review" and statuses[f"{PREFIX}.signature"] == "needs_review"
    assert next(f for f in v["fields"] if f["field_id"] == f"{PREFIX}.signature")["redacted"] is True
    assert "black bar" in v["reasons"][0]


def test_a_missing_date_is_a_reviewers_call():
    v = evaluate(ITEM, fields(date=None))
    assert v["outcome"] == "needs_review" and v["worst"] == "needs_review"


def test_an_unverified_value_is_the_reviewers_call_never_a_pass_or_a_disqualification():
    unverified = {"verified": False, "method": "second_read", "second_value": "18 August 2026",
                  "note": "the model read '12 August 2026'; a second, independent read found '18 August 2026'"}
    v = evaluate(ITEM, {**fields(), f"{PREFIX}.date_verification": unverified})
    date = next(f for f in v["fields"] if f["field_id"] == f"{PREFIX}.date")
    assert v["outcome"] == "needs_review" and date["status"] == "needs_review" and date["note"].startswith("unverified: the model read")
    assert v["counts"] == {"pass": 3, "dormant": 0, "needs_review": 1, "disqualified": 0}
    blank = {"verified": False, "method": "second_read", "second_value": "9 August 2026", "note": "the model read nothing; a second, independent read found '9 August 2026'"}
    v = evaluate(ITEM, {**fields(date=None), f"{PREFIX}.date_verification": blank})
    assert v["outcome"] == "needs_review", "the engine's disqualification is withheld while the two readings differ"


def test_a_verified_or_unchecked_or_corrected_value_is_left_to_the_engine():
    for record in ({"verified": True, "method": "text_layer", "note": "found"}, {"verified": None, "method": None, "note": "-"}, None):
        v = evaluate(ITEM, {**fields(), f"{PREFIX}.date_verification": record})
        assert v["outcome"] == "pass", record


def test_decide_reads_the_stored_rule_set_and_pins_its_version():
    v = decide_item_l(fields(), RULESET)
    assert v["ruleset_version"] == 1 and v["outcome"] == "pass" and v["rule_ids"][0] == f"{PREFIX}.submitted"
    with pytest.raises(KeyError):
        decide_item_l(fields(), {**RULESET, "items": []})


# ---------------------------------------------------------------- S4-3: every item, the comparison kinds
from types import SimpleNamespace  # noqa: E402

from app.checks.engine_bridge import compare, decide, parse_date, render_params, stage_summary  # noqa: E402
from app.rulesets.schema import Outcome, RuleSetItem, TemplateRule  # noqa: E402
from test.checks.conftest import RULESET_ALL, TEMPLATES, read_offer  # noqa: E402

OWN = {"blank": Outcome(status="disqualified", note="{field} is missing"), "filled": Outcome(status="pass"),
       "redacted": Outcome(status="needs_review")}
PRICE = {"price_schedule.unit_price": 4.4, "price_schedule.unit_price_printed": "HK$ 4.40 per kg", "price_schedule.quantity": 875000,
         "price_schedule.quantity_printed": "875,000 kg", "price_schedule.total": 3850000.0, "price_schedule.optimal_dosage": 4.3,
         "price_schedule.optimal_dosage_printed": "4.3 mg/L", "offer_to_be_bound.date": "14 August 2026",
         "offer_to_be_bound.tenderer_name": "Tenderer_A", "contact_details.tenderer_name": "Tenderer A", "x.blank": None}


def rule(check: str, field: str, **params) -> TemplateRule:
    return TemplateRule(id=f"t.{check}", check=check, field=field, params=params, outcomes=OWN)


def check(kind: str, field: str, **params):
    r = rule(kind, field, **params)
    return compare(r, r.params, PRICE)


def test_the_comparison_kinds_are_decided_in_code():
    assert check("value", "price_schedule.quantity", expected=875000) == ("match", "read '875,000 kg', expected 875000")
    assert check("value", "price_schedule.quantity", expected=900000)[0] == "mismatch"
    assert check("value", "contact_details.tenderer_name", expected="tenderer a")[0] == "match"
    assert check("value", "price_schedule.quantity")[0] == "unstated"
    assert check("range", "price_schedule.optimal_dosage", min=0.5, max=20) == ("match", "read '4.3 mg/L', allowed 0.5 to 20")
    assert check("range", "price_schedule.optimal_dosage", max=4)[0] == "mismatch"
    assert check("unit", "price_schedule.unit_price", allowed=["HK$", "US$"])[0] == "match"
    assert check("unit", "price_schedule.unit_price", allowed=["EUR"])[0] == "mismatch"
    assert check("contains", "price_schedule.unit_price", phrase="per kg")[0] == "match"
    assert check("date", "offer_to_be_bound.date") == ("match", "2026-08-14")
    assert check("date", "offer_to_be_bound.date", before="2026-08-01")[0] == "mismatch"
    assert check("date", "offer_to_be_bound.tenderer_name")[0] == "mismatch", "not a date"
    assert check("math", "price_schedule.total", inputs=["unit_price", "quantity"]) == \
        ("match", "read 3.85e+06, the product of price_schedule.unit_price and price_schedule.quantity is 3.85e+06")
    assert check("math", "price_schedule.total", inputs=["unit_price", "optimal_dosage"])[0] == "mismatch"
    assert check("cross_document_match", "offer_to_be_bound.tenderer_name", other="contact_details.tenderer_name")[0] == "match"
    assert check("human_only", "price_schedule.total") == ("unstated", "a reviewer decides; no automated check")
    assert check("value", "x.blank", expected=1) is None, "a blank field keeps the presence outcomes"
    assert check("filled", "price_schedule.total") is None and check("signature", "price_schedule.total") is None


def test_contains_can_ask_for_every_phrase_or_for_none_and_range_can_count_decimals():
    fields = {**PRICE, "contact_details.address": "P.O. Box 123, Central", "price_schedule_parts_c_d.discount_7day": "2.505%",
              "documentary_evidence.safety_data_sheet_sections": "Identification; Hazards; First aid"}
    def on(kind, field, **params):
        r = rule(kind, field, **params)
        return compare(r, r.params, fields)
    sections = "documentary_evidence.safety_data_sheet_sections"
    assert on("contains", sections, phrases=["identification", "first aid"])[0] == "match"
    assert on("contains", sections, phrases=["identification", "disposal"]) == \
        ("mismatch", "read 'Identification; Hazards; First aid', missing 'disposal'")
    assert on("contains", "contact_details.address", phrases=["P.O. Box", "PO Box"], absent=True)[0] == "mismatch"
    assert on("contains", "price_schedule.unit_price", phrases=["P.O. Box"], absent=True)[0] == "match"
    assert on("range", "price_schedule_parts_c_d.discount_7day", max_decimals=2) == \
        ("mismatch", "read '2.505%', 3 decimal places, at most 2")
    assert on("range", "price_schedule.unit_price", max_decimals=2)[0] == "match", "'HK$ 4.40' has two, as printed"
    assert on("range", "price_schedule.unit_price", max_decimals=2, max=4)[0] == "mismatch", "the bounds still apply"


def test_a_rules_normalise_steps_run_in_order_on_a_number_and_are_reported():
    from app.rulesets.schema import Normalise

    steps = [Normalise(op="resolve_range_to_lower_bound"),
             Normalise(op="round_significant_figures", params={"max_sig_figs": 2})]
    r = TemplateRule(id="price_schedule.dosage_given", check="filled", field="price_schedule.optimal_dosage",
                     outcomes=OWN, normalise=steps)
    item = RuleSetItem(letter="c", title="dosage", part="A", citation=ITEM.citation, rules=[r], status="novel")
    v = evaluate(item, {"price_schedule.optimal_dosage": "4.36 - 5.1 kg/t"})
    assert v["outcome"] == "pass" and v["adjustments"] == [
        {"rule_id": "price_schedule.dosage_given", "field_id": "price_schedule.optimal_dosage",
         "operations": ["resolve_range_to_lower_bound", "round_significant_figures"], "from": "4.36 - 5.1 kg/t",
         "value": 4.4}], "the range's lower end, then rounded"
    corrected = evaluate(item, {"price_schedule.optimal_dosage": "4.4 kg/t"})
    assert corrected["outcome"] == "pass", "a person's correction arrives as text and is read as its number"
    unit = TemplateRule(id="price_schedule.dosage_unit", check="unit", field="price_schedule.optimal_dosage",
                        params={"expected": "kg/t"}, outcomes={"match": {"status": "pass"}, "mismatch": {"status": "needs_review"}})
    both = item.model_copy(update={"rules": [r, unit]})
    assert evaluate(both, {"price_schedule.optimal_dosage": "4.36 kg/t"})["outcome"] == "pass", \
        "rounded to a number, the value keeps its printed unit for the unit check"
    unreadable = evaluate(item, {"price_schedule.optimal_dosage": "see attached"})
    assert unreadable["outcome"] == "needs_review" and "could not normalise" in unreadable["reasons"][0]
    assert "adjustments" not in evaluate(item, {"price_schedule.optimal_dosage": 4.4}), \
        "no key when nothing changed, so a stored verdict still compares equal"
    assert "transform" not in rules_doc(item)["rules"][0], "the steps run in the bridge, not the engine"


def test_a_blank_field_a_reviewer_enters_is_dormant_whatever_the_rule_says():
    blank = {"status": "disqualified", "note": "{field} is missing"}
    rules = [TemplateRule(id="s.delivered", check="filled", field="tender_sample_declaration.sample_received_date",
                          outcomes={"blank": blank, "filled": {"status": "pass"}}),
             TemplateRule(id="s.weight", check="range", field="tender_sample_declaration.sample_net_weight_kg",
                          params={"min": 600}, outcomes={"match": {"status": "pass"}, "mismatch": {"status": "needs_review"}})]
    item = RuleSetItem(letter="g", title="samples", part="A", citation=ITEM.citation, rules=rules, status="novel")
    v = evaluate(item, {"tender_sample_declaration.sample_received_date": None})
    by = {f["field_id"]: f for f in v["fields"]}
    assert v["outcome"] == "dormant" and by["tender_sample_declaration.sample_received_date"]["status"] == "dormant"
    assert "entered by a reviewer" in by["tender_sample_declaration.sample_received_date"]["note"]
    assert by["tender_sample_declaration.sample_net_weight_kg"]["status"] == "dormant", \
        "a rule with no blank outcome still gets a row to enter the value on"
    entered = evaluate(item, {"tender_sample_declaration.sample_received_date": "3 July 2026",
                              "tender_sample_declaration.sample_net_weight_kg": 400})
    assert {f["field_id"]: f["status"] for f in entered["fields"]}["tender_sample_declaration.sample_net_weight_kg"] \
        == "needs_review", "once entered, it is checked like any other"


def test_a_reviewers_check_on_a_missing_document_waits_and_an_unreadable_date_bound_is_never_skipped():
    judged = rule("human_only", "documentary_evidence.quality_certificate")
    assert compare(judged, {}, {"documentary_evidence.quality_certificate": None}) is None
    assert compare(judged, {}, {"documentary_evidence.quality_certificate": "QMS-1"})[0] == "unstated"
    assert check("date", "offer_to_be_bound.date", after="noon on 30 June 2026") == \
        ("unstated", "the bound after 'noon on 30 June 2026' is not a date a person has confirmed")


def test_decimals_count_every_figure_as_written_and_nil_has_none():
    def on(text, **params):
        r = rule("range", "d.x", **params)
        return compare(r, r.params, {"d.x": text})
    assert on("Nil", max_decimals=2) == ("match", "read 'Nil', no figure")
    assert on("7-day: 2.505%", max_decimals=2)[0] == "mismatch", "every figure, not only the first"
    assert on("2,505%", max_decimals=2)[0] == "mismatch", "a decimal comma in a percentage"
    assert on("HK$ 12,500.00", max_decimals=2)[0] == "match", "a thousands comma elsewhere"
    assert on("Nil", max_decimals=2, max=5)[0] == "mismatch", "with bounds, a figure is still needed"


def test_a_bare_number_correction_keeps_the_unit_and_counts_the_persons_figure():
    """#100 re-review: a reviewer's 7.5 corrects the figure. The unit check still finds the
    currency printed beside it, and the decimal count and the message show the person's value."""
    from app.jobs.store import _apply
    corrected = _apply(PRICE, {"price_schedule.unit_price": {"value": 7.5, "by": "chenyu", "reason": "misread"}})
    unit = rule("unit", "price_schedule.unit_price", allowed=["HK$", "US$"])
    assert compare(unit, unit.params, corrected) == ("match", "read 'HK$ 4.40 per kg', allowed HK$, US$")
    places = rule("range", "price_schedule.unit_price", max_decimals=2, max=10)
    assert compare(places, places.params, corrected) == ("match", "read 7.5, allowed at most 10")
    three = _apply(PRICE, {"price_schedule.unit_price": {"value": "7.505", "by": "chenyu", "reason": "misread"}})
    assert compare(places, places.params, three)[0] == "mismatch", "the person's three places, not the printed two"
    typed = _apply(PRICE, {"price_schedule.unit_price": {"value": "7.5 per kg", "by": "chenyu", "reason": "misread"}})
    assert compare(unit, unit.params, typed)[0] == "mismatch", "a person's own text replaces the printed text"


def test_absent_is_a_yes_or_no_and_an_empty_phrase_is_ignored():
    fields = {"c.address": "P.O. Box 12"}
    def on(**params):
        r = rule("contains", "c.address", **params)
        return compare(r, r.params, fields)
    assert on(phrases=["P.O. Box"], absent="false")[0] == "match", "the string 'false' is no"
    assert on(phrases=["P.O. Box"], absent=True)[0] == "mismatch"
    assert on(phrases=["", "P.O. Box"]) == ("match", "read 'P.O. Box 12', looked for 'P.O. Box'")
    assert on(phrases=[""]) == ("unstated", "no phrase to look for")


def test_dates_parse_in_the_forms_offers_print_them():
    assert [parse_date(d).isoformat() for d in ("14 August 2026", "14 Aug 2026", "2026-08-14", "14/08/2026", "August 14, 2026", "14th August 2026")] \
        == ["2026-08-14"] * 6
    assert parse_date("not a date") is None and parse_date(None) is None


def test_slot_references_in_params_are_rendered_from_the_items_slots():
    item = SimpleNamespace(slots={"estimated_quantity": SimpleNamespace(value=875000)})
    r = rule("value", "price_schedule.quantity", expected="{estimated_quantity}", tolerance="{missing}", other=3)
    assert render_params(r, item) == {"expected": 875000, "tolerance": None, "other": 3}


def test_a_comparison_never_disqualifies_and_its_reason_is_readable():
    item = RuleSetItem.model_validate({**RULESET_ALL["items"][2]})       # (c): dosage present, unit mg/L, range 0.5 to 20
    fields = {**PRICE, "price_schedule.optimal_dosage": 40.0, "price_schedule.optimal_dosage_printed": "40 mg/L"}
    v = evaluate(item, fields)
    by = {f["field_id"]: f for f in v["fields"]}
    assert v["outcome"] == "needs_review" and by["price_schedule.optimal_dosage"]["status"] == "needs_review"
    assert "allowed 0.5 to 20" in v["reasons"][0] and by["price_schedule.optimal_dosage"]["stage"] == "II"


def test_a_rule_on_a_field_no_form_reads_is_a_reviewers_call_not_a_blank():
    item = RuleSetItem(letter="x1", title="colour", part="A", status="novel",
                       citation={"file": "f", "page": 1, "quote": "q", "data_class": "synthetic"},
                       rules=[rule("filled", "particulars_of_goods.colour")])
    v = evaluate(item, PRICE)
    assert v["outcome"] == "needs_review" and v["fields"][0]["note"] == "unextracted: no form reads colour; a reviewer decides"
    v = evaluate(item, {**PRICE, "particulars_of_goods.colour": None, "particulars_of_goods.colour_page": None})
    assert v["outcome"] == "disqualified", "a blank the form did look for is a blank"


def test_an_item_with_no_rules_or_without_its_template_is_a_reviewers_call():
    bare = RuleSetItem(letter="x2", title="nothing", part="A", status="novel",
                       citation={"file": "f", "page": 1, "quote": "q", "data_class": "synthetic"})
    assert evaluate(bare, PRICE)["outcome"] == "needs_review"
    l_item = next(i for i in RuleSet.model_validate(RULESET_ALL).items if i.letter == "l")
    assert l_item.template == "noncollusive_certificate" and all(r.outcomes is None for r in l_item.rules)
    v = evaluate(l_item, fields(), template=None)
    assert v["outcome"] == "needs_review" and "not in the library" in v["reasons"][0] and v["fields"] == []


def test_stage_summaries_roll_up_by_the_rules_stage():
    items = {"a": {"outcome": "pass", "fields": [{"status": "pass", "stage": "I"}]},
             "c": {"outcome": "pass", "fields": [{"status": "pass", "stage": "I"}, {"status": "needs_review", "stage": "II"}]},
             "g": {"outcome": "dormant", "fields": [{"status": "dormant", "stage": "I"}]},
             "z": {"outcome": "needs_review", "fields": []}}
    assert stage_summary(items, "I") == {"outcome": "needs_review", "items": {"a": "pass", "c": "pass", "g": "dormant", "z": "needs_review"}}
    assert stage_summary(items, "II") == {"outcome": "needs_review", "items": {"c": "needs_review"}}
    assert stage_summary({"g": items["g"]}, "I")["outcome"] == "dormant" and stage_summary({}, "I") == {"outcome": "pass", "items": {}}


def test_decide_judges_every_item_of_the_rule_set_with_the_templates_tiers(monkeypatch):
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    v = decide(read_offer("Tenderer_D", verify=True), RULESET_ALL)
    assert set(v["items"]) == set("abcdefghijklmno") and v["ruleset_version"] == 1
    assert v["items"]["l"]["outcome"] == "pass" and [f["status"] for f in v["items"]["l"]["fields"]] == ["pass"] * 4
    assert v["items"]["b"]["outcome"] == "pass" and v["items"]["b"]["rule_ids"][-1] == "price_schedule.total_is_unit_price_times_quantity"
    assert v["stage1"]["items"]["j"] == "dormant" and v["stage1"]["items"]["g"] == "dormant", "Part B items the offer lacks"
    assert v["stage1"]["outcome"] == "pass" and v["outcome"] == "pass"
    assert v["stage2"] == {"outcome": "pass", "items": {"c": "pass", "d": "pass", "n": "pass"}}
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES / "nowhere"))
    v = decide(read_offer("Tenderer_D"), RULESET_ALL)
    assert v["items"]["l"]["outcome"] == "needs_review" and v["items"]["b"]["outcome"] == "needs_review", "no templates, no silent pass"
    assert v["items"]["a"]["outcome"] == "pass", "novel rules carry their own outcomes"
