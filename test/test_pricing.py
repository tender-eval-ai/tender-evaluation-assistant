"""The price engine is the part that must never be wrong — pure deterministic math."""
import pytest

from app.pricing import compute_price_rows, round_2sf
from app.schemas import BidExtraction, BidPrice, PriceScheme


def bid(name, unit_price=None, dosage=None, quoted_total=None, currency="HKD", fx=None):
    return BidExtraction(
        tenderer=name, documents=[], compliance=[],
        price=BidPrice(currency=currency, unit_price=unit_price, optimal_dosage=dosage,
                       quoted_total=quoted_total, fx_to_hkd=fx))


class TestRound2sf:
    """Terms of Tender rule: 2 significant figures, 3rd digit >= 5 rounds up."""

    @pytest.mark.parametrize("raw,expected", [
        (2.849, 2.8),     # 3rd sig fig 4 -> dropped
        (2.85, 2.9),      # 3rd sig fig 5 -> rounds up
        (5.678, 5.7),
        (0.02349, 0.023),  # leading zeros are not significant
        (0.0255, 0.026),
        (3.0, 3.0),
        (57.5, 58.0),
        (0.0, 0.0),
    ])
    def test_cases(self, raw, expected):
        assert round_2sf(raw) == pytest.approx(expected)


class TestCostEffectiveness:
    scheme = PriceScheme(type="cost_effectiveness", quantity=100000, unit="kg")

    def test_ranking_and_recommendation(self):
        bids = [
            bid("A", unit_price=20.0, dosage=2.849),   # CE = 2.8 * 20.00 = 56.00
            bid("B", unit_price=19.8, dosage=2.0),     # CE = 39.60
            bid("C", unit_price=25.0, dosage=1.0),     # CE = 25.00 but non-conforming
            bid("D", unit_price=18.5, dosage=None),    # cannot be calculated
        ]
        rows, recommended = compute_price_rows(self.scheme, bids, conforming={"A", "B"})
        by_name = {r.tenderer: r for r in rows}

        # Non-conforming offers still get ranked (as in the client sample) ...
        assert by_name["C"].ranking == 1
        assert by_name["B"].ranking == 2
        assert by_name["A"].ranking == 3
        # ... but the recommendation goes to the best CONFORMING offer.
        assert recommended == "B"
        assert by_name["B"].cost_effectiveness == pytest.approx(39.60)
        assert by_name["A"].cost_effectiveness == pytest.approx(56.00)  # dosage rounded first

        # No dosage -> no CE, no ranking, explicit remark.
        assert by_name["D"].cost_effectiveness is None
        assert by_name["D"].ranking is None
        assert by_name["D"].remark == "cannot be calculated"

    def test_foreign_currency_converted(self):
        bids = [bid("US", unit_price=2.97, dosage=3.0, currency="USD", fx=7.8515)]
        rows, _ = compute_price_rows(self.scheme, bids, conforming=set())
        assert rows[0].unit_price_hkd == pytest.approx(23.32, abs=0.01)
        assert rows[0].cost_effectiveness == pytest.approx(69.96, abs=0.01)

    def test_estimated_goods_price_uses_quantity(self):
        rows, _ = compute_price_rows(self.scheme, [bid("A", unit_price=20.0, dosage=2.0)],
                                     conforming={"A"})
        assert rows[0].estimated_goods_price == pytest.approx(2_000_000.00)


class TestUnitPriceTimesQuantity:
    scheme = PriceScheme(type="unit_price_x_quantity", quantity=22521575, unit="kg")

    def test_ranking_by_estimated_price(self):
        bids = [
            bid("A", unit_price=1.19, quoted_total=26800674.25),
            bid("B", unit_price=1.30, quoted_total=29278047.50),
        ]
        rows, recommended = compute_price_rows(self.scheme, bids, conforming={"A", "B"})
        by_name = {r.tenderer: r for r in rows}
        assert by_name["A"].ranking == 1
        assert by_name["B"].ranking == 2
        assert recommended == "A"

    def test_arithmetic_error_detected(self):
        # Modeled on the client sample: quoted 28,601,670.00 but 1.27 x 22,521,575
        # computes to 28,602,400.25 — the TAP flags the discrepancy.
        bids = [bid("X", unit_price=1.27, quoted_total=28601670.00)]
        rows, _ = compute_price_rows(self.scheme, bids, conforming={"X"})
        assert rows[0].estimated_goods_price == pytest.approx(28602400.25)
        assert rows[0].arithmetic_ok is False
        assert "arithmetical error" in rows[0].remark

    def test_tally_ok_within_tolerance(self):
        bids = [bid("Y", unit_price=1.19, quoted_total=26800674.25)]
        rows, _ = compute_price_rows(self.scheme, bids, conforming={"Y"})
        assert rows[0].arithmetic_ok is True
        assert "error" not in rows[0].remark
