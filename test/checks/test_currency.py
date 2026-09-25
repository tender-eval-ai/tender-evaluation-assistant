"""Which currency an offer printed, and what the price summary does with it: a known
currency with a rate is converted and says so; anything it cannot convert is not ranked
and says why. Before this, "€" read as HK$, and C$ and A$ went through at 1:1."""
from __future__ import annotations

import pytest

from app.checks.currency import code_of, convert, read
from app.checks.pricing import Offer, PriceScheme, price_rows, settle_currency

PASSED = {"stage1": {"outcome": "pass"}, "stage2": {"outcome": "pass"}}


@pytest.mark.parametrize("printed, code", [
    ("HK$", "HKD"), ("HK $ 12.50 per kg", "HKD"), ("US$ 7.22 per kg", "USD"), ("U.S.$", "USD"), ("USD", "USD"),
    ("C$", "CAD"), ("CA$ 11.00", "CAD"), ("A$", "AUD"), ("AU$", "AUD"), ("NZ$", "NZD"), ("S$", "SGD"), ("NT$", "TWD"),
    ("RMB 80", "CNY"), ("€ 1.40", "EUR"), ("EUR", "EUR"), ("£", "GBP"), ("Hong Kong dollars", "HKD"), ("12.50 HKD per kg", "HKD"),
])
def test_a_printed_currency_reads_as_its_code(printed, code):
    assert read(printed).code == code


@pytest.mark.parametrize("printed, problem", [
    ("", "not stated"), (None, "not stated"), ("$", "ambiguous"), ("dollars", "ambiguous"), ("¥", "ambiguous"),
    ("HK$ 12.50 (US$ 1.60)", "mixed"), ("INR", "unknown"), ("per kg", "unknown"),
])
def test_what_is_not_clear_is_not_guessed(printed, problem):
    reading = read(printed)
    assert reading.code is None and reading.problem == problem


def test_a_currency_the_tender_gives_a_rate_for_is_known():
    assert read("INR 100", known=("INR",)).code == "INR"
    assert code_of("HK$") == "HKD" and code_of("hkd") == "HKD" and code_of("INR") == "INR" and code_of("dollars") is None


def test_conversion_needs_the_tenders_currency_and_a_rate():
    assert convert(read("US$"), "HKD", {"USD": 7.8}).rate == 7.8
    assert convert(read("HK$"), "HKD", {}).rate == 1.0
    assert convert(read("C$"), "HKD", {"USD": 7.8}).rate is None, "no rate: never 1:1"
    assert convert(read("US$"), None, {"USD": 7.8}).rate is None, "no tender currency to convert into"
    taken = convert(read("$"), "HKD", {})
    assert taken.code == "HKD" and taken.rate == 1.0 and "'$'; taken as HK$" in taken.note
    assert convert(read("$"), "EUR", {}).rate is None, "a dollar sign is not a euro"
    assert convert(read("HK$ 12.50 (US$ 1.60)"), "HKD", {"USD": 7.8}).rate is None
    blank = convert(read(""), "HKD", {})
    assert blank.rate == 1.0 and "no currency printed" in blank.note


def offer(tenderer: str, printed: str | None, unit_price: float, total: float | None = None) -> Offer:
    fields = {"price_schedule.currency": printed, "price_schedule.unit_price": unit_price, "price_schedule.total": total}
    return Offer(tenderer=tenderer, run_id="r", fields=fields, verdict=PASSED, reviewed_by="nasi")


def test_offers_in_other_currencies_are_converted_or_left_unranked():
    scheme = PriceScheme(type="unit_price_x_quantity", quantity=1000, base_currency="HKD",
                         exchange_rates={"USD": 7.8, "CAD": 5.7, "AUD": 5.1})
    offers = [offer("T_hk", "HK$", 12.0), offer("T_us", "US$", 1.6), offer("T_ca", "C$", 2.0), offer("T_au", "A$", 2.2),
              offer("T_eu", "€", 1.4), offer("T_nt", "NT$", 50.0)]
    rows, recommended = price_rows(scheme, offers)
    by = {r["tenderer"]: r for r in rows}
    assert by["T_ca"]["unit_price_base"] == 11.4 and "converted at 5.7 HK$/C$" in by["T_ca"]["remark"]
    assert by["T_au"]["unit_price_base"] == 11.22 and by["T_us"]["unit_price_base"] == 12.48
    assert [by[t]["ranking"] for t in ("T_au", "T_ca", "T_hk", "T_us")] == [1, 2, 3, 4] and recommended == "T_au"
    for t, why in (("T_eu", "no exchange rate from € to HK$"), ("T_nt", "no exchange rate from NT$ to HK$")):
        assert by[t]["ranking"] is None and by[t]["unit_price_base"] is None and why in by[t]["remark"]
    assert by["T_eu"]["currency"] == "€" and by["T_eu"]["unit_price"] == 1.4, "shown as quoted"


def test_the_arithmetic_is_checked_in_the_currency_the_offer_quoted():
    scheme = PriceScheme(type="unit_price_x_quantity", quantity=1000, base_currency="HKD", exchange_rates={"USD": 7.8})
    rows, _ = price_rows(scheme, [offer("right", "US$", 1.6, total=1600.0), offer("wrong", "US$", 1.6, total=1650.0)])
    by = {r["tenderer"]: r for r in rows}
    assert by["right"]["arithmetic_ok"] is True and "arithmetical error" not in by["right"]["remark"]
    assert by["right"]["estimated_goods_price"] == 12480.0, "the ranked figure is in the tender's currency"
    assert by["wrong"]["arithmetic_ok"] is False
    assert "quoted total 1,650.00 does not tally with calculated 1,600.00 (US$)" in by["wrong"]["remark"]


def test_offers_in_one_currency_need_no_setting():
    scheme = PriceScheme(type="unit_price_x_quantity", quantity=10)
    offers = [offer("a", "€ 3.00", 3.0), offer("b", "EUR", 2.5)]
    settled = settle_currency(scheme, offers)
    assert settled.base_currency == "EUR" and settled.currency_source == "every offer is quoted in €"
    rows, recommended = price_rows(settled, offers)
    assert recommended == "b" and all(r["ranking"] for r in rows)
    mixed = settle_currency(scheme, [offer("a", "€", 3.0), offer("b", "US$", 3.0)])
    assert mixed.base_currency is None


def test_an_ambiguous_or_unknown_currency_waits_for_a_reviewer():
    scheme = PriceScheme(type="unit_price_x_quantity", quantity=10, base_currency="EUR")
    rows, recommended = price_rows(scheme, [offer("dollar", "$", 3.0), offer("odd", "XYZ", 3.0), offer("euro", "€", 4.0)])
    by = {r["tenderer"]: r for r in rows}
    assert by["dollar"]["ranking"] is None and "not ranked until a reviewer corrects the currency" in by["dollar"]["remark"]
    assert by["odd"]["ranking"] is None and "currency 'XYZ' not recognised" in by["odd"]["remark"]
    assert recommended == "euro"


def test_a_bad_rate_setting_is_refused(monkeypatch):
    from app.checks.pricing import currency_settings
    from app.rulesets.schema import RuleSet

    empty = RuleSet(project_id="p", version=1, status="draft", data_class="synthetic", items=[],
                    created_by="t", created_at="2026-09-25T00:00:00Z")
    monkeypatch.setenv("PRICING_FX_RATES", '{"USD": -1}')
    with pytest.raises(ValueError, match="positive rate"):
        currency_settings(empty)
    monkeypatch.setenv("PRICING_FX_RATES", "7.8")
    with pytest.raises(ValueError, match="must map a currency"):
        currency_settings(empty)
