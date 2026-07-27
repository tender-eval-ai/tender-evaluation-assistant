"""Deterministic price engine — no LLM involvement in any number.

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

from .schemas import BidExtraction, PriceRow, PriceScheme

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
            fx = p.fx_to_hkd if (p.fx_to_hkd and row.currency.upper() not in ("HKD", "HK$")) else 1.0
            row.unit_price_hkd = round(p.unit_price * fx, 4)
            row.estimated_goods_price = round(row.unit_price_hkd * scheme.quantity, 2)

        if scheme.type == "cost_effectiveness":
            if p.optimal_dosage is not None and row.unit_price_hkd is not None:
                row.dosage = p.optimal_dosage
                row.dosage_rounded = round_2sf(p.optimal_dosage)
                row.cost_effectiveness = round(row.dosage_rounded * row.unit_price_hkd, 2)
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
