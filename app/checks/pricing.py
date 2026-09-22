"""The price summary and the evaluation across tenderers (S4-4), from the confirmed rule
set and the checked results. No model call, no number from a model: the arithmetic is the
legacy price engine's (`app.pricing`, kept unchanged), cost-effectiveness = the optimal
dosage rounded to two significant figures times the unit price in HK$ (lower is better),
or unit price times the estimated quantity (lowest first). What is new is where the
inputs come from: the rule set (the estimated quantity from the price schedule item's
slot; the scheme from whether any rule reads the optimal dosage) and each tenderer's
result (its fields with the reviewer's corrections applied, its Stage I and II outcomes,
who confirmed its review). An offer conforms when both stages pass; the recommended
offer is the best-ranked conforming one, as on the client's Price Summary."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from app.checks.corrections import item_verdicts
from app.checks.verify import normalise
from app.pricing import compute_price_rows
from app.rulesets.schema import RuleSet
from app.schemas import BidExtraction, BidPrice
from app.schemas import PriceScheme as LegacyScheme

PRICE_FORM = "price_schedule"
USD_HKD_DEFAULT = 7.8     # PRICING_USD_HKD: what a US$ quotation is converted at; the HK$ peg's mid-rate unless set
STAGE_ORDER = ("disqualified", "needs_review", "dormant", "pass")


def usd_hkd() -> float:
    return float(os.environ.get("PRICING_USD_HKD") or USD_HKD_DEFAULT)


@dataclass(frozen=True)
class PriceScheme:
    type: str                        # cost_effectiveness | unit_price_x_quantity
    quantity: float | None           # the estimated quantity, from the rule set
    unit: str = "kg"
    currency: str = "HK$"
    usd_hkd: float = USD_HKD_DEFAULT
    source: str = ""                 # where the quantity came from

    def as_dict(self) -> dict:
        return {"type": self.type, "quantity": self.quantity, "unit": self.unit, "currency": self.currency,
                "usd_hkd": self.usd_hkd, "source": self.source}


def scheme_of(ruleset: RuleSet) -> PriceScheme:
    """The tender's price scheme as the rule set states it: the quantity from the first
    filled `estimated_quantity` slot, cost-effectiveness when a rule reads the dosage."""
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
    return PriceScheme(type="cost_effectiveness" if reads_dosage else "unit_price_x_quantity", quantity=quantity,
                       source=source, usd_hkd=usd_hkd())


def currency_code(text: Any) -> str:
    """HKD, USD or the text itself, from however the offer wrote it (HK$, US$, USD, ...)."""
    words = normalise(text).split()
    if not words:
        return "HKD"
    if "us" in words or "usd" in words:
        return "USD"
    if "hk" in words or "hkd" in words:
        return "HKD"
    return str(text).strip().upper()


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

    def price(self, scheme: PriceScheme) -> BidPrice:
        currency = currency_code(self.fields.get(f"{PRICE_FORM}.currency") or self.fields.get(f"{PRICE_FORM}.unit_price_printed"))
        return BidPrice(currency=currency, unit_price=_number(self.fields.get(f"{PRICE_FORM}.unit_price")),
                        optimal_dosage=_number(self.fields.get(f"{PRICE_FORM}.optimal_dosage")),
                        quoted_total=_number(self.fields.get(f"{PRICE_FORM}.total")),
                        fx_to_hkd=scheme.usd_hkd if currency == "USD" else None)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_rows(scheme: PriceScheme, offers: list[Offer]) -> tuple[list[dict], str | None]:
    """One row per offer, ranked; the recommended tenderer. Without an estimated quantity
    nothing can be computed and every row says so."""
    if scheme.quantity is None:
        rows = []
        for o in offers:
            p = o.price(scheme)
            rows.append({"tenderer": o.tenderer, "conforming": o.conforming, "currency": p.currency, "unit_price": p.unit_price,
                         "unit_price_hkd": None, "dosage": p.optimal_dosage, "dosage_rounded": None, "estimated_goods_price": None,
                         "quoted_total": p.quoted_total, "arithmetic_ok": None, "cost_effectiveness": None, "ranking": None,
                         "remark": "cannot be calculated: the rule set states no estimated quantity"})
        return _decorate(rows, offers, scheme), None
    legacy = LegacyScheme(type=scheme.type, quantity=scheme.quantity, unit=scheme.unit, currency="HKD")
    bids = [BidExtraction(tenderer=o.tenderer, documents=[], compliance=[], price=o.price(scheme)) for o in offers]
    rows, recommended = compute_price_rows(legacy, bids, {o.tenderer for o in offers if o.conforming})
    return _decorate([r.model_dump() for r in rows], offers, scheme), recommended


def _decorate(rows: list[dict], offers: list[Offer], scheme: PriceScheme) -> list[dict]:
    by = {o.tenderer: o for o in offers}
    for row in rows:
        o = by[row["tenderer"]]
        row.update(stage1=o.stage("stage1"), stage2=o.stage("stage2"), reviewed_by=o.reviewed_by, corrected=o.corrected,
                   run_id=o.run_id)
        notes = []
        if row["currency"] == "USD" and row.get("unit_price") is not None:
            notes.append(f"quoted in US$, converted at {scheme.usd_hkd:g} HK$/US$")
        if not o.conforming:
            notes.append({"disqualified": "not a conforming offer", "needs_review": "pending review", "dormant": "items outstanding"}
                         .get(o.stage("stage1") if o.stage("stage1") != "pass" else o.stage("stage2"), "not a conforming offer"))
        if o.reviewed_by is None:
            notes.append("review not confirmed")
        row["remark"] = "; ".join([row["remark"]] * bool(row["remark"]) + notes)
    return rows


def price_summary(ruleset: RuleSet, offers: list[Offer], missing: list[str] | None = None) -> dict:
    scheme = scheme_of(ruleset)
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
