"""S4-4: the price summary and the evaluation across the four synthetic tenderers, from
the all-items rule set and the results the fake produces. Cost-effectiveness per the
Terms of Tender formula (dosage to two significant figures times the unit price in the
tender's currency), a US$ quotation converted at the rule set's rate, ranking over every computable offer, the
recommendation to the best-ranked conforming one, and the Summary List's conclusions."""
from __future__ import annotations

import pytest

from app.checks.engine_bridge import decide
from app.checks.pricing import Offer, evaluation, price_summary, scheme_of, stage_conclusion
from app.jobs.store import _apply
from app.rulesets.schema import RuleSet
from test.checks.conftest import RULESET, RULESET_ALL, TEMPLATES, read_offer

TENDERERS = ("Tenderer_A", "Tenderer_B", "Tenderer_C", "Tenderer_D")
ALL = RuleSet.model_validate(RULESET_ALL)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    monkeypatch.delenv("PRICING_BASE_CURRENCY", raising=False)
    monkeypatch.delenv("PRICING_FX_RATES", raising=False)


def offers(*, reviewed: bool = True, resolve_letter_of_intent: bool = True) -> list[Offer]:
    """The four results as the store would hold them after a reviewer marked the conditional
    letter of intent not applicable for the three manufacturers and confirmed the reviews."""
    out = []
    for t in TENDERERS:
        fields = read_offer(t, verify=True)
        corrections = {}
        if resolve_letter_of_intent and fields.get("manufacturer_letter.document") is None:
            corrections["manufacturer_letter.document"] = {"value": "N/A", "by": "nasi", "reason": "the tenderer is the manufacturer",
                                                          "model_value": None}
        applied = _apply(fields, corrections)
        verdict = decide(applied, RULESET_ALL)
        out.append(Offer(tenderer=t, run_id=f"run-{t[-1]}", fields=applied, verdict=verdict, corrections=corrections,
                         reviewed_by="nasi" if reviewed and verdict["outcome"] != "disqualified" or (reviewed and t == "Tenderer_C") else None))
    return out


def test_the_scheme_comes_from_the_rule_set():
    scheme = scheme_of(ALL)
    assert scheme.type == "cost_effectiveness" and scheme.quantity == 875000
    assert scheme.base_currency == "HKD" and scheme.exchange_rates == {"USD": 7.8}
    assert scheme.source == "item (b), slot estimated_quantity" and scheme.currency_source == "item (b), slot currency"
    assert scheme.as_dict()["currency"] == "HK$"
    only_l = scheme_of(RuleSet.model_validate(RULESET))
    assert only_l.type == "unit_price_x_quantity" and only_l.quantity is None


def test_a_not_applicable_correction_resolves_the_conditional_letter_of_intent():
    by = {o.tenderer: o for o in offers()}
    assert by["Tenderer_A"].verdict["items"]["i"]["outcome"] == "pass" and by["Tenderer_A"].stage("stage1") == "pass"
    assert "not required" in by["Tenderer_A"].verdict["items"]["i"]["fields"][0]["note"]
    assert by["Tenderer_C"].stage("stage1") == "disqualified" and by["Tenderer_D"].stage("stage1") == "pass"
    assert by["Tenderer_D"].corrections == {} and by["Tenderer_A"].corrected == []


def test_cost_effectiveness_ranks_every_offer_and_recommends_the_best_conforming_one():
    summary = price_summary(ALL, offers())
    rows = {r["tenderer"]: r for r in summary["rows"]}
    assert summary["scheme"]["type"] == "cost_effectiveness" and summary["missing"] == []
    assert rows["Tenderer_A"]["cost_effectiveness"] == 18.92 and rows["Tenderer_A"]["dosage_rounded"] == 4.3
    assert rows["Tenderer_B"]["cost_effectiveness"] == 20.9 and rows["Tenderer_C"]["cost_effectiveness"] == 19.44
    assert rows["Tenderer_D"]["unit_price_base"] == 56.316 and rows["Tenderer_D"]["cost_effectiveness"] == 168.95
    assert rows["Tenderer_D"]["currency"] == "US$" and "converted at 7.8 HK$/US$" in rows["Tenderer_D"]["remark"]
    assert rows["Tenderer_A"]["currency"] == "HK$" and rows["Tenderer_A"]["unit_price_base"] == rows["Tenderer_A"]["unit_price"]
    assert [rows[t]["ranking"] for t in TENDERERS] == [1, 3, 2, 4]
    assert rows["Tenderer_A"]["estimated_goods_price"] == 3850000.0
    assert summary["recommended"] == "Tenderer_A" and rows["Tenderer_A"]["remark"] == "recommended (conforming offer)"
    assert rows["Tenderer_C"]["conforming"] is False and "not a conforming offer" in rows["Tenderer_C"]["remark"]
    assert all(r["reviewed_by"] == "nasi" for r in summary["rows"])


def test_an_unreviewed_or_pending_offer_cannot_be_recommended():
    summary = price_summary(ALL, offers(reviewed=False, resolve_letter_of_intent=False))
    rows = {r["tenderer"]: r for r in summary["rows"]}
    assert summary["recommended"] == "Tenderer_D", "the only offer with both stages passed"
    assert "pending review" in rows["Tenderer_A"]["remark"] and "review not confirmed" in rows["Tenderer_A"]["remark"]
    assert rows["Tenderer_A"]["ranking"] == 1, "ranked all the same, as the client's Price Summary ranks every offer"


def test_without_an_estimated_quantity_nothing_is_calculated():
    summary = price_summary(RuleSet.model_validate(RULESET), offers()[:2])
    assert summary["recommended"] is None
    assert all(r["ranking"] is None and r["estimated_goods_price"] is None and "no estimated quantity" in r["remark"] for r in summary["rows"])
    assert summary["rows"][0]["unit_price"] == 4.4


def without_currency_slots() -> RuleSet:
    ruleset = ALL.model_copy(deep=True)
    for item in ruleset.items:
        item.slots.pop("currency", None)
        item.slots.pop("exchange_rates", None)
    return ruleset


def test_the_rule_sets_rate_comes_before_the_environments(monkeypatch):
    monkeypatch.setenv("PRICING_FX_RATES", '{"US$": 7.75}')
    rows = {r["tenderer"]: r for r in price_summary(ALL, offers())["rows"]}
    assert rows["Tenderer_D"]["unit_price_base"] == 56.316, "the rule set states 7.8"
    rows = {r["tenderer"]: r for r in price_summary(without_currency_slots(), offers())["rows"]}
    assert rows["Tenderer_D"]["unit_price_base"] is None, "no tender currency: HK$ and US$ offers cannot be compared"
    monkeypatch.setenv("PRICING_BASE_CURRENCY", "HKD")
    summary = price_summary(without_currency_slots(), offers())
    rows = {r["tenderer"]: r for r in summary["rows"]}
    assert rows["Tenderer_D"]["unit_price_base"] == 55.955 and "7.75" in rows["Tenderer_D"]["remark"]
    assert summary["scheme"]["currency_source"] == "PRICING_BASE_CURRENCY"


def test_an_offer_without_a_rate_is_not_ranked_and_says_why():
    summary = price_summary(without_currency_slots(), offers())
    rows = {r["tenderer"]: r for r in summary["rows"]}
    assert summary["scheme"]["currency"] is None, "HK$ and US$ offers: no single currency to compare in"
    assert all(r["ranking"] is None for r in rows.values()) and summary["recommended"] is None
    assert "the tender's currency is not set" in rows["Tenderer_D"]["remark"]


def test_the_conclusions_read_like_the_summary_list():
    ev = evaluation(ALL, offers(), missing=["Tenderer_E"])
    assert ev["stage1_conclusion"] == ("Stage I: Tenderer_A, Tenderer_B and Tenderer_D passed Stage I; Tenderer_C is not considered "
                                       "further: item (l) The signed Non-collusive Tendering Certificate.")
    assert ev["stage2_conclusion"] == "Stage II: Tenderer_A, Tenderer_B, Tenderer_C and Tenderer_D passed Stage II."
    assert ev["recommended"] == "Tenderer_A" and ev["recommendation"] == "The offer of Tenderer_A is the best-ranked conforming offer."
    assert ev["price"]["missing"] == ["Tenderer_E"] and [t["tenderer"] for t in ev["tenderers"]] == list(TENDERERS)
    assert ev["tenderers"][0]["items"]["i"] == "pass" and ev["tenderers"][0]["corrections"] == 1 and ev["tenderers"][3]["corrections"] == 0
    pending = evaluation(ALL, offers(reviewed=False, resolve_letter_of_intent=False))
    assert "Tenderer_A awaits a reviewer's decision on item (i)" in pending["stage1_conclusion"]
    assert stage_conclusion([], "stage1", ALL) == "Stage I: no tenderer has been checked yet."
    assert stage_conclusion(offers()[:1], "stage2", RuleSet.model_validate(RULESET)).startswith("Stage II: Tenderer_A passed")
