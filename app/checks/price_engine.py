"""The deterministic price engine, from the prototype: no LLM involvement in any number.

`app.checks.pricing` feeds it the checked results. The models it takes and returns live here
too; until the layout clean-up they were `app/schemas.py`, and this file was `app/pricing.py`.

Implements both Price Summary formats observed in the client samples:
- cost_effectiveness: CE = D x M (dosage rounded to 2 significant figures per the
  Terms of Tender formula), lower is better; offers without a usable dosage get
  "cannot be calculated" / ranking "not applicable".
- unit_price_x_quantity: estimated goods price = unit price x estimated quantity,
  lowest first; the tenderer's quoted total is tallied against the computed figure and
  discrepancies are flagged (the TAP's "arithmetical error" note in sample 2).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


# ---------------------------------------------------------------- the tender's price scheme

class PriceScheme(BaseModel):
    """How the tender says price must be assessed. Drives which Price Summary format is used."""
    type: Literal["cost_effectiveness", "unit_price_x_quantity"]
    quantity: float = Field(description="Estimated quantity from the Price Schedule")
    unit: str = "kg"
    currency: str = "HKD"
    notes: str = ""
    source_file: str = Field(default="", description="Tender file (### FILE header) defining the scheme")
    source_page: Optional[int] = Field(default=None, description="[Page N] marker where defined")


# ---------------------------------------------------------------- per-bid extraction

class DocumentPresence(BaseModel):
    checklist_id: str
    present: bool
    page: Optional[int] = Field(default=None, description="Page in the bid where found")
    note: str = ""


class ComplianceFinding(BaseModel):
    requirement_id: str
    complies: Literal["yes", "no", "unclear"]
    evidence: str = Field(default="", description="Short quote or observation supporting the finding")
    page: Optional[int] = None


class BidPrice(BaseModel):
    currency: str = "HKD"
    unit_price: Optional[float] = Field(default=None, description="One-time unit price as quoted")
    optimal_dosage: Optional[float] = Field(
        default=None, description="Optimal dosage, only for cost-effectiveness schemes")
    quoted_total: Optional[float] = Field(
        default=None, description="Estimated goods price as quoted by the tenderer, if stated")
    # Stored before F6 as `fx_to_hkd`; read under either name, so an old extraction
    # or checkpoint keeps its rate instead of pricing a foreign bid at 1.0.
    fx_to_base: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("fx_to_base", "fx_to_hkd"),
        description="Conversion rate to the base currency if quoted in a foreign currency")


class BidExtraction(BaseModel):
    """Everything extracted from one tenderer's offer."""
    tenderer: str
    documents: list[DocumentPresence]
    compliance: list[ComplianceFinding]
    price: BidPrice
    source_file: str = ""


# ---------------------------------------------------------------- the Price Summary

class PriceRow(BaseModel):
    tenderer: str
    conforming: bool                        # passed Stage I and Stage II
    currency: str = "HKD"
    unit_price: Optional[float] = None      # as quoted, original currency
    unit_price_base: Optional[float] = Field(default=None, validation_alias=AliasChoices("unit_price_base", "unit_price_hkd"))
    dosage: Optional[float] = None
    dosage_rounded: Optional[float] = None  # 2 significant figures per the tender formula
    estimated_goods_price: Optional[float] = None  # HKD
    quoted_total: Optional[float] = None
    arithmetic_ok: Optional[bool] = None    # quoted total tallies with unit price x quantity
    cost_effectiveness: Optional[float] = None
    ranking: Optional[int] = None
    remark: str = ""


# ---------------------------------------------------------------- the engine

# Tolerance (HKD) when tallying a quoted total against unit price x quantity.
ARITHMETIC_TOLERANCE = 0.5


def round_2sf(x: float) -> float:
    """Round to 2 significant figures, half-up on the 3rd — the Terms of Tender rule:
    'the 2nd significant figure will be increased by one if the 3rd equals or exceeds 5'."""
    if x == 0:
        return 0.0
    d = Decimal(str(x))
    quantum = Decimal(1).scaleb(d.adjusted() - 1)
    return float(d.quantize(quantum, rounding=ROUND_HALF_UP))


def _metric(row: PriceRow, scheme_type: str) -> float | None:
    return row.cost_effectiveness if scheme_type == "cost_effectiveness" else row.estimated_goods_price


def compute_price_rows(scheme: PriceScheme, bids: list[BidExtraction],
                       conforming: set[str]) -> tuple[list[PriceRow], str | None]:
    """Build the price table for all bidders (conforming or not, as in the samples) and
    pick the recommended offer: best metric among fully conforming tenderers."""
    rows: list[PriceRow] = []
    for bid in bids:
        p = bid.price
        row = PriceRow(
            tenderer=bid.tenderer,
            conforming=bid.tenderer in conforming,
            currency=p.currency or "HKD",
            unit_price=p.unit_price,
        )
        if p.unit_price is not None:
            fx = p.fx_to_base if (p.fx_to_base and row.currency.upper() not in ("HKD", "HK$")) else 1.0
            row.unit_price_base = round(p.unit_price * fx, 4)
            row.estimated_goods_price = round(row.unit_price_base * scheme.quantity, 2)

        if scheme.type == "cost_effectiveness":
            if p.optimal_dosage is not None and row.unit_price_base is not None:
                row.dosage = p.optimal_dosage
                row.dosage_rounded = round_2sf(p.optimal_dosage)
                row.cost_effectiveness = round(row.dosage_rounded * row.unit_price_base, 2)
            else:
                row.remark = "cannot be calculated"
        else:
            if p.quoted_total is not None and row.estimated_goods_price is not None:
                row.quoted_total = p.quoted_total
                row.arithmetic_ok = abs(p.quoted_total - row.estimated_goods_price) <= ARITHMETIC_TOLERANCE
                if not row.arithmetic_ok:
                    row.remark = (
                        f"arithmetical error: quoted total {p.quoted_total:,.2f} does not tally "
                        f"with calculated {row.estimated_goods_price:,.2f}"
                    )
        rows.append(row)

    # Rank every offer with a computable metric (samples rank non-conforming offers too).
    rankable = sorted(
        (r for r in rows if _metric(r, scheme.type) is not None),
        key=lambda r: _metric(r, scheme.type),
    )
    for i, row in enumerate(rankable, start=1):
        row.ranking = i

    conforming_ranked = [r for r in rankable if r.conforming]
    recommended = conforming_ranked[0].tenderer if conforming_ranked else None
    for row in rows:
        if row.tenderer == recommended:
            row.remark = (row.remark + "; " if row.remark else "") + "recommended (conforming offer)"
    return rows, recommended
