"""The price summary and the evaluation across tenderers (S4-4), from the confirmed rule
set and the checked results. No model call, no number from a model: the arithmetic is the
legacy price engine's (`app.checks.price_engine`, kept unchanged), cost-effectiveness = the optimal
dosage rounded to two significant figures times the unit price in the tender's currency
(lower is better), or unit price times the estimated quantity (lowest first). What is new
is where the inputs come from: the rule set (the estimated quantity, the tender's currency
and the exchange rates from the price schedule item's slots; the scheme from whether any
rule reads the optimal dosage), the currency each offer printed (`app.checks.currency`:
converted before the legacy engine sees it, never at 1:1) and each tenderer's
result (its fields with the reviewer's corrections applied, its Stage I and II outcomes,
who confirmed its review). An offer conforms when both stages pass; the recommended
offer is the best-ranked conforming one, as on the client's Price Summary."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from typing import Any

from app.checks import currency
from app.checks.corrections import item_verdicts
from app.rulesets.schema import RuleSet
from app.checks.price_engine import ARITHMETIC_TOLERANCE, BidExtraction, BidPrice, compute_price_rows
from app.checks.price_engine import PriceScheme as LegacyScheme

PRICE_FORM = "price_schedule"
STAGE_ORDER = ("disqualified", "needs_review", "dormant", "pass")


@dataclass(frozen=True)
class PriceScheme:
    type: str                        # cost_effectiveness | unit_price_x_quantity
    quantity: float | None           # the estimated quantity, from the rule set
    unit: str = "kg"
    base_currency: str | None = None  # the tender's currency (ISO 4217): what every price is compared in
    exchange_rates: dict = field(default_factory=dict)   # ISO code -> rate into base_currency
    currency_source: str = ""        # where the tender's currency came from
    source: str = ""                 # where the quantity came from

    def as_dict(self) -> dict:
        return {"type": self.type, "quantity": self.quantity, "unit": self.unit,
                "currency": currency.label(self.base_currency) or None, "base_currency": self.base_currency,
                "exchange_rates": dict(self.exchange_rates), "currency_source": self.currency_source, "source": self.source}


def _slot(ruleset: RuleSet, name: str) -> tuple[Any, str]:
    """The first filled slot of that name, and where it is."""
    for item in ruleset.items:
        slot = item.slots.get(name)
        if slot is not None and slot.value not in (None, "", {}):
            return slot.value, f"item ({item.letter}), slot {name}"
    return None, ""


def _rates(value: Any, where: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must map a currency to its rate, e.g. {{\"USD\": 7.8}}")
    rates = {}
    for name, rate in value.items():
        code = currency.code_of(name)
        if code is None or not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
            raise ValueError(f"{where}: {name!r}: {rate!r} is not a currency and a positive rate")
        rates[code] = float(rate)
    return rates


def currency_settings(ruleset: RuleSet) -> tuple[str | None, dict[str, float], str]:
    """The tender's currency, the exchange rates into it, and where the currency came from.
    The rule set's slots (`currency`, `exchange_rates` on the price schedule item) come
    first; PRICING_BASE_CURRENCY and PRICING_FX_RATES are the deployment's fallback."""
    value, where = _slot(ruleset, "currency")
    base = currency.code_of(value) if value is not None else None
    if base is None and os.environ.get("PRICING_BASE_CURRENCY"):
        base, where = currency.code_of(os.environ["PRICING_BASE_CURRENCY"]), "PRICING_BASE_CURRENCY"
    rates: dict[str, float] = {}
    if os.environ.get("PRICING_FX_RATES"):
        try:
            env = json.loads(os.environ["PRICING_FX_RATES"])
        except json.JSONDecodeError as err:
            raise ValueError(f"PRICING_FX_RATES is not JSON: {err}") from None
        rates.update(_rates(env, "PRICING_FX_RATES"))
    value, slot_where = _slot(ruleset, "exchange_rates")
    if value is not None:
        rates.update(_rates(value, slot_where))
    rates.pop(base, None)
    return base, rates, where if base else ""


def scheme_of(ruleset: RuleSet) -> PriceScheme:
    """The tender's price scheme as the rule set states it: the quantity from the first
    filled `estimated_quantity` slot, cost-effectiveness when a rule reads the dosage,
    and the currency settings (`currency_settings`)."""
    quantity, source = None, ""
    for item in ruleset.items:
        slot = item.slots.get("estimated_quantity")
        if slot is not None and slot.value is not None:
            try:
                quantity = float(slot.value)
            except (TypeError, ValueError):
                continue
            source = f"item ({item.letter}), slot estimated_quantity"
            break
    reads_dosage = any(r.field == f"{PRICE_FORM}.optimal_dosage" for item in ruleset.items for r in item.rules)
    base, rates, where = currency_settings(ruleset)
    return PriceScheme(type="cost_effectiveness" if reads_dosage else "unit_price_x_quantity", quantity=quantity,
                       source=source, base_currency=base, exchange_rates=rates, currency_source=where)


@dataclass(frozen=True)
class Quote:
    """One offer's price fields, as printed and corrected, with the currency they are in."""

    reading: currency.Reading
    unit_price: float | None
    optimal_dosage: float | None
    quoted_total: float | None


@dataclass
class Offer:
    """What one tenderer's checked result contributes to the summary."""

    tenderer: str
    run_id: str
    fields: dict                     # with the reviewer's corrections applied
    verdict: dict
    reviewed_by: str | None = None
    corrections: dict = field(default_factory=dict)

    def stage(self, which: str) -> str | None:
        summary = self.verdict.get(which)
        return summary.get("outcome") if summary else None

    @property
    def conforming(self) -> bool:
        return self.stage("stage1") == "pass" and self.stage("stage2") in (None, "pass")

    @property
    def items(self) -> dict[str, str]:
        return {letter: v.get("outcome") for letter, v in item_verdicts(self.verdict).items()}

    @property
    def corrected(self) -> list[str]:
        """The corrected price fields, by short name."""
        return sorted(k.rsplit(".", 1)[-1] for k in self.corrections if k.startswith(f"{PRICE_FORM}.") and not k.endswith("_page"))

    def quote(self, scheme: PriceScheme) -> Quote:
        printed = self.fields.get(f"{PRICE_FORM}.currency") or self.fields.get(f"{PRICE_FORM}.unit_price_printed")
        return Quote(reading=currency.read(printed, tuple(scheme.exchange_rates)),
                     unit_price=_number(self.fields.get(f"{PRICE_FORM}.unit_price")),
                     optimal_dosage=_number(self.fields.get(f"{PRICE_FORM}.optimal_dosage")),
                     quoted_total=_number(self.fields.get(f"{PRICE_FORM}.total")))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def settle_currency(scheme: PriceScheme, offers: list[Offer]) -> PriceScheme:
    """Without a stated currency, offers that all quote the same one are compared in it."""
    if scheme.base_currency or not offers:
        return scheme
    codes = {o.quote(scheme).reading.code for o in offers}
    if len(codes) == 1 and None not in codes:
        code = codes.pop()
        return replace(scheme, base_currency=code, currency_source=f"every offer is quoted in {currency.label(code)}")
    return scheme


def price_rows(scheme: PriceScheme, offers: list[Offer]) -> tuple[list[dict], str | None]:
    """One row per offer, ranked; the recommended tenderer. Without an estimated quantity
    nothing can be computed and every row says so. An offer the currency rules cannot
    convert gets no price in the tender's currency, so it is not ranked."""
    quotes = {o.tenderer: o.quote(scheme) for o in offers}
    rates = {o.tenderer: currency.convert(quotes[o.tenderer].reading, scheme.base_currency, scheme.exchange_rates)
             for o in offers}
    if scheme.quantity is None:
        rows = []
        for o in offers:
            q = quotes[o.tenderer]
            rows.append({"tenderer": o.tenderer, "conforming": o.conforming, "unit_price": q.unit_price,
                         "unit_price_base": None, "dosage": q.optimal_dosage, "dosage_rounded": None, "estimated_goods_price": None,
                         "quoted_total": q.quoted_total, "arithmetic_ok": None, "cost_effectiveness": None, "ranking": None,
                         "remark": "cannot be calculated: the rule set states no estimated quantity"})
        return _decorate(rows, offers, quotes, rates), None

    def in_base(o: Offer) -> float | None:
        q, c = quotes[o.tenderer], rates[o.tenderer]
        return round(q.unit_price * c.rate, 4) if q.unit_price is not None and c.rate is not None else None

    # The legacy engine is given prices already in the tender's currency, so its own
    # conversion never runs; the arithmetic check is done here, in the quoted currency.
    legacy = LegacyScheme(type=scheme.type, quantity=scheme.quantity, unit=scheme.unit, currency=scheme.base_currency or "")
    bids = [BidExtraction(tenderer=o.tenderer, documents=[], compliance=[],
                          price=BidPrice(currency=scheme.base_currency or "", unit_price=in_base(o),
                                         optimal_dosage=quotes[o.tenderer].optimal_dosage))
            for o in offers]
    rows, recommended = compute_price_rows(legacy, bids, {o.tenderer for o in offers if o.conforming})
    out = []
    for row, o in zip(rows, offers):
        q, c = quotes[o.tenderer], rates[o.tenderer]
        d = row.model_dump()
        d["unit_price"] = q.unit_price
        tally = None
        if scheme.type == "unit_price_x_quantity" and q.quoted_total is not None and q.unit_price is not None:
            calculated = round(q.unit_price * scheme.quantity, 2)
            d["quoted_total"], d["arithmetic_ok"] = q.quoted_total, abs(q.quoted_total - calculated) <= ARITHMETIC_TOLERANCE
            if not d["arithmetic_ok"]:
                other = f" ({currency.label(c.code)})" if c.code and c.code != scheme.base_currency else ""
                tally = f"arithmetical error: quoted total {q.quoted_total:,.2f} does not tally with calculated {calculated:,.2f}{other}"
        d["remark"] = "; ".join(x for x in (tally, d["remark"]) if x)
        out.append(d)
    return _decorate(out, offers, quotes, rates), recommended


def _decorate(rows: list[dict], offers: list[Offer], quotes: dict[str, Quote], rates: dict[str, currency.Converted]) -> list[dict]:
    by = {o.tenderer: o for o in offers}
    for row in rows:
        o, q, c = by[row["tenderer"]], quotes[row["tenderer"]], rates[row["tenderer"]]
        row.update(currency=currency.label(c.code) if c.code else q.reading.printed, stage1=o.stage("stage1"),
                   stage2=o.stage("stage2"), reviewed_by=o.reviewed_by, corrected=o.corrected, run_id=o.run_id)
        notes = [c.note] if c.note and q.unit_price is not None else []
        if not o.conforming:
            notes.append({"disqualified": "not a conforming offer", "needs_review": "pending review", "dormant": "items outstanding"}
                         .get(o.stage("stage1") if o.stage("stage1") != "pass" else o.stage("stage2"), "not a conforming offer"))
        if o.reviewed_by is None:
            notes.append("review not confirmed")
        row["remark"] = "; ".join([row["remark"]] * bool(row["remark"]) + notes)
    return rows


def price_summary(ruleset: RuleSet, offers: list[Offer], missing: list[str] | None = None) -> dict:
    scheme = settle_currency(scheme_of(ruleset), offers)
    rows, recommended = price_rows(scheme, offers)
    return {"ruleset_version": ruleset.version, "scheme": scheme.as_dict(), "rows": rows, "recommended": recommended,
            "missing": sorted(missing or [])}


# ---------------------------------------------------------------- the evaluation across tenderers
def _names(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else (items[0] if items else "none")


def stage_conclusion(offers: list[Offer], which: str, ruleset: RuleSet) -> str:
    """One paragraph in the Summary List's voice: who passed, who waits on a reviewer, who
    is not considered further and why."""
    titles = {i.letter: i.title for i in ruleset.items}
    label = "Stage I" if which == "stage1" else "Stage II"
    if not offers:
        return f"{label}: no tenderer has been checked yet."
    if all(o.stage(which) is None for o in offers):
        return f"{label}: the rule set has no {label} rules."
    groups: dict[str, list[str]] = {}
    for o in offers:
        groups.setdefault(o.stage(which) or "pass", []).append(o.tenderer)
    parts = []
    if groups.get("pass"):
        parts.append(f"{_names(groups['pass'])} passed {label}")
    for status, verb in (("needs_review", "await a reviewer's decision on"), ("dormant", "have items the Authority may request:"),
                         ("disqualified", "are not considered further:")):
        for tenderer in groups.get(status, []):
            o = next(x for x in offers if x.tenderer == tenderer)
            letters = [k for k, v in (o.verdict.get(which) or {}).get("items", {}).items() if v == status]
            named = ", ".join(f"item ({k}) {titles.get(k, '')}".rstrip() for k in letters) or "see the record"
            parts.append(f"{tenderer} {verb.replace('await', 'awaits').replace('have', 'has').replace('are', 'is')} {named}")
    return f"{label}: " + "; ".join(parts) + "."


def evaluation(ruleset: RuleSet, offers: list[Offer], missing: list[str] | None = None) -> dict:
    summary = price_summary(ruleset, offers, missing)
    recommended = summary["recommended"]
    rec = (f"The offer of {recommended} is the best-ranked conforming offer." if recommended
           else "No conforming offer can be recommended yet.")
    return {"ruleset_version": ruleset.version,
            "tenderers": [{"tenderer": o.tenderer, "run_id": o.run_id, "stage1": o.stage("stage1"), "stage2": o.stage("stage2"),
                           "items": o.items, "reviewed_by": o.reviewed_by, "corrections": len(o.corrections), "conforming": o.conforming}
                          for o in offers],
            "stage1_conclusion": stage_conclusion(offers, "stage1", ruleset),
            "stage2_conclusion": stage_conclusion(offers, "stage2", ruleset),
            "recommendation": rec, "recommended": recommended, "price": summary}
