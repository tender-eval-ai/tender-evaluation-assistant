"""V6: the fixture rule set for item (l) evaluated by app/engine through the bridge."""
import pytest

from app.checks.engine_bridge import decide_item_l, evaluate, rules_doc
from app.checks.extract_item_l import PREFIX
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
