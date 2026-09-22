"""The four synthetic bids against `ground_truth.json`: every form found on its page, every
number read and coerced, every value verified (text layer or second read), and the
conclusions the all-items rule set reaches: Tenderer_C loses its Part A certificate,
Tenderer_D (the one that is not the manufacturer) passes Stage I with two dormant Part B
items, A and B wait on a reviewer for the conditional letter of intent."""
from __future__ import annotations

import pytest

from app.checks.engine_bridge import decide
from app.checks.fields import is_meta
from app.checks.forms import FORMS, forms_for_letter
from test.checks.conftest import RULESET_ALL, TEMPLATES, TRUTH, read_offer

TENDERERS = ("Tenderer_A", "Tenderer_B", "Tenderer_C", "Tenderer_D")
STAGE1 = {"Tenderer_A": "needs_review", "Tenderer_B": "needs_review", "Tenderer_C": "disqualified", "Tenderer_D": "pass"}


@pytest.fixture(autouse=True)
def templates(monkeypatch):
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))


@pytest.mark.parametrize("tenderer", TENDERERS)
def test_every_form_is_found_on_its_page_and_the_numbers_match(tenderer):
    truth = TRUTH["bids"][tenderer]
    fields = read_offer(tenderer, verify=True)
    for letter, item in truth["items"].items():
        form = forms_for_letter(letter)[0]
        key = form.key("document")
        if item["present"]:
            assert fields[key] is not None and fields[f"{key}_page"]["page"] == item["page"], (tenderer, letter)
        else:
            assert fields[key] is None and fields[f"{key}_page"] is None, (tenderer, letter)
    price = truth["items"]["b"]["values"]
    assert fields["price_schedule.unit_price"] == price["unit_price"] and fields["price_schedule.currency"] == price["currency"]
    assert fields["price_schedule.optimal_dosage"] == price["optimal_dosage_mg_per_l"] and fields["price_schedule.total"] == price["total"]
    assert fields["price_schedule.quantity"] == TRUTH["estimated_quantity_kg"]
    goods = truth["items"]["d"]["values"]
    assert fields["particulars_of_goods.shelf_life_months"] == goods["shelf_life_months"]
    assert fields["particulars_of_goods.manufacturer"] == goods["manufacturer"]
    assert fields["compliance_schedule.delivery_days"] == truth["items"]["n"]["values"]["delivery_days"]
    if not truth["manufacturer_itself"]:
        assert fields["manufacturer_letter.manufacturer"] == truth["items"]["i"]["values"]["manufacturer"]


@pytest.mark.parametrize("tenderer", TENDERERS)
def test_every_value_read_is_verified_on_the_text_layer_or_by_a_second_read(tenderer):
    scanned = TRUTH["bids"][tenderer]["scanned"]
    fields = read_offer(tenderer, verify=True)
    unverified, unchecked_values = [], []
    for key, value in fields.items():
        if is_meta(key):
            continue
        record = fields.get(f"{key}_verification") or {}
        if record.get("verified") is False:
            unverified.append((key, value, record.get("note")))
        if value is not None and record.get("verified") is None and not FORMS[key.rpartition(".")[0]].key("signature") == key:
            unchecked_values.append((key, value))
    assert unverified == [], unverified
    assert unchecked_values == [], unchecked_values
    methods = {r["method"] for k, r in fields.items() if k.endswith("_verification") and r and r.get("verified")}
    assert methods == ({"second_read"} if scanned else {"text_layer"})


@pytest.mark.parametrize("tenderer", TENDERERS)
def test_the_rule_set_reaches_the_expected_conclusions(tenderer):
    truth = TRUTH["bids"][tenderer]
    v = decide(read_offer(tenderer, verify=True), RULESET_ALL)
    assert v["stage1"]["outcome"] == STAGE1[tenderer], v["stage1"]
    assert v["stage2"]["outcome"] == "pass" and set(v["stage2"]["items"]) == {"c", "d", "n"}
    items = v["stage1"]["items"]
    assert items["g"] == "dormant", "samples were never requested: a Part B item may be asked for later"
    assert items["e"] == ("dormant" if truth["scanned"] else "pass"), "the country of origin is read off the text layer only"
    if truth["manufacturer_itself"]:
        assert items["i"] == "needs_review", "the letter of intent is conditional; a reviewer decides"
        assert "required only where the tenderer is not the manufacturer" in v["items"]["i"]["reasons"][0]
    else:
        assert items["i"] == "pass" and items["j"] == "dormant"
    if not truth["items"]["l"]["present"]:
        assert items["l"] == "disqualified" and "missing" in v["items"]["l"]["reasons"][0]
    else:
        assert items["l"] == "pass"
    non_pass = {k: o for k, o in items.items() if o != "pass"}
    expected = {"g": "dormant"}
    if truth["scanned"]:
        expected["e"] = "dormant"
    if truth["manufacturer_itself"]:
        expected["i"] = "needs_review"
    else:
        expected["j"] = "dormant"
    if not truth["items"]["l"]["present"]:
        expected["l"] = "disqualified"
    assert non_pass == expected
