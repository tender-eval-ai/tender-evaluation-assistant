from decimal import ROUND_HALF_UP, Decimal


def resolve_dosage_value(value: float | tuple[float, float]) -> float:
    if isinstance(value, tuple):
        return min(value)
    return value


def normalize_currency(amount: float, currency: str, fx_rate: float = 1.0) -> float:
    if currency == "HKD":
        return amount
    return amount * fx_rate


def round_to_significant_figures(value: float, sig_figs: int) -> float:
    # Decimal + ROUND_HALF_UP, not Python's round() (round-half-to-even): a caller
    # of this function (the Price Schedule optimal-dosage rule) states the tie-
    # break explicitly - "the [N-th] significant figure will be increased by one
    # if the [N+1-th] significant figure equals to or exceeds five" - which is
    # round-half-up, not round-half-even. Confirmed round() gives the wrong answer
    # on an exact tie: round_to_significant_figures(8.25, 2) returned 8.2 (banker's
    # rounding to the nearest even digit) where the stated rule requires 8.3.
    if value == 0:
        return 0.0
    d = Decimal(str(value))
    quantize_exp = Decimal(1).scaleb(d.adjusted() - sig_figs + 1)
    return float(d.quantize(quantize_exp, rounding=ROUND_HALF_UP))
