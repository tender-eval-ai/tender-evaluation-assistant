import datetime
from dataclasses import dataclass
from typing import Callable

from app.engine.normalize import resolve_dosage_value, round_to_significant_figures

_NA_TOKENS = {"n/a", "na"}


@dataclass
class TransformResult:
    # "positive"/"negative": the computed comparison passed/failed - resolved
    # against a rule's specific outcome vocabulary by core.py, not hardcoded to
    # any one pair of key names (rules use match/mismatch, within_range/
    # outside_range, valid/invalid, etc. - see engine/core.py's synonym tables).
    # "neutral": the condition doesn't apply at all (e.g. a self-entry check where
    # the Tenderer isn't the Manufacturer) - distinct from None, which means "not
    # enough input to compute anything," not "computed and inapplicable."
    bucket: str | None  # "positive" | "negative" | "neutral" | None
    value: object = None  # raw computed value - used for auto_adjustment transforms
    computed_date: str | None = None  # only add_working_days/add_calendar_days set this


def _normalize_text(value) -> str:
    return " ".join(str(value).lower().split())


def _input_value(item: dict, rule: dict, transform: dict, index: int = 0):
    inputs = transform.get("inputs")
    if inputs:
        return item.get(inputs[index])
    return item.get(rule["field_id"])


def _base_date(item: dict, rule: dict) -> str | None:
    # transform.params.base_date in the rules JSON is prose ("date of the
    # Authority's written request"), not a machine-readable item key - there is
    # no live wiring to parse there. Convention instead: a rule-specific override
    # first, then the common default every base_date description in practice
    # resolves to (a Paragraph 16.1-style authority request date).
    explicit = item.get(f"{rule['id']}__base_date")
    if explicit is not None:
        return explicit
    return item.get("authority_request_date")


def _offset_days(params: dict) -> int | None:
    if "offset_value" in params:
        return params["offset_value"]
    offset = params.get("offset")
    if isinstance(offset, dict):
        return offset.get("value")
    return None


def _parse_date(value: str | None) -> datetime.date | None:
    if value is None:
        return None
    return datetime.date.fromisoformat(value)


def _add_months(date: datetime.date, months: int) -> datetime.date:
    # Manual month arithmetic (no python-dateutil - not a declared project
    # dependency) - clamps the day to the target month's actual length, e.g.
    # 2026-03-31 minus 1 month -> 2026-02-28, not an invalid 2026-02-31.
    month_index = date.month - 1 - months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(date.day, _days_in_month(year, month))
    return datetime.date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)
    return (next_month - datetime.date(year, month, 1)).days


def _add_working_days(start: datetime.date, count: int) -> datetime.date:
    current = start
    remaining = count
    while remaining > 0:
        current += datetime.timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri; public holidays not modelled
            remaining -= 1
    return current


def op_round_significant_figures(item: dict, rule: dict, params: dict) -> TransformResult:
    value = item.get(rule["field_id"])
    if value is None:
        return TransformResult(bucket=None, value=None)
    rounded = round_to_significant_figures(value, params["max_sig_figs"])
    return TransformResult(bucket=None, value=rounded)


def op_resolve_range_to_lower_bound(item: dict, rule: dict, params: dict) -> TransformResult:
    value = item.get(rule["field_id"])
    if value is None:
        return TransformResult(bucket=None, value=None)
    max_value = item.get(f"{rule['field_id']}_max")
    resolved = resolve_dosage_value((value, max_value)) if max_value is not None else value
    return TransformResult(bucket=None, value=resolved)


def op_arithmetic_product(item: dict, rule: dict, params: dict) -> TransformResult:
    inputs = params.get("inputs", [])
    if len(inputs) < 2:
        return TransformResult(bucket=None)
    a, b = item.get(inputs[0]), item.get(inputs[1])
    reported = item.get(rule["field_id"])
    if a is None or b is None or reported is None:
        return TransformResult(bucket=None)
    expected = round(a * b, 2)
    tolerance = params.get("tolerance", 0.01)
    passed = abs(reported - expected) <= tolerance
    return TransformResult(bucket="positive" if passed else "negative", value=expected)


def _make_add_days(step: Callable[[datetime.date, int], datetime.date]):
    def op(item: dict, rule: dict, params: dict) -> TransformResult:
        base = _parse_date(_base_date(item, rule))
        offset = _offset_days(params)
        if base is None or offset is None:
            return TransformResult(bucket=None, computed_date=None)
        deadline = step(base, offset)
        # Two independent uses share this operation: follow_up_deadline (tier-
        # level, just wants the computed date - no actual_date is ever supplied,
        # bucket stays None) and comparison_input (rule-level on_time/late checks,
        # e.g. test_report_lab_appointment_deadline - needs an observed date to
        # compare against the computed deadline).
        actual = _parse_date(item.get(f"{rule['id']}__actual_date"))
        bucket = None
        if actual is not None:
            bucket = "positive" if actual <= deadline else "negative"
        return TransformResult(bucket=bucket, computed_date=deadline.isoformat())

    return op


op_add_working_days = _make_add_days(_add_working_days)
op_add_calendar_days = _make_add_days(lambda base, offset: base + datetime.timedelta(days=offset))


def op_date_not_earlier_than(item: dict, rule: dict, params: dict) -> TransformResult:
    check_date = _parse_date(_input_value(item, rule, {"inputs": params.get("inputs")}))
    reference_date = _parse_date(item.get("tender_closing_date"))
    if check_date is None or reference_date is None:
        return TransformResult(bucket=None)
    unit = params.get("max_age_unit", "months")
    if unit != "months":
        raise ValueError(f"date_not_earlier_than: unsupported max_age_unit {unit!r}")
    cutoff = _add_months(reference_date, params["max_age_value"])
    passed = check_date >= cutoff
    return TransformResult(bucket="positive" if passed else "negative", value=check_date.isoformat())


def op_date_within_range(item: dict, rule: dict, params: dict) -> TransformResult:
    check_date = _parse_date(item.get("original_tender_closing_date") or item.get("tender_closing_date"))
    range_start = _parse_date(item.get(f"{rule['field_id']}_issue_date"))
    range_end = _parse_date(item.get(f"{rule['field_id']}_expiry_date"))
    if check_date is None or range_start is None or range_end is None:
        return TransformResult(bucket=None)
    passed = range_start <= check_date <= range_end
    return TransformResult(bucket="positive" if passed else "negative")


def op_min_value_check(item: dict, rule: dict, params: dict) -> TransformResult:
    value = item.get(rule["field_id"])
    minimum = params.get("min_kg", params.get("min"))
    if value is None or minimum is None:
        return TransformResult(bucket=None)
    passed = value >= minimum
    return TransformResult(bucket="positive" if passed else "negative", value=value)


def op_value_in_range(item: dict, rule: dict, params: dict) -> TransformResult:
    value = item.get(rule["field_id"])
    minimum = params.get("min", params.get("min_kg"))
    maximum = params.get("max", params.get("max_kg"))
    # Not every rule declaring this operation supplies numeric bounds -
    # test_report_compliance_with_product_specs's range_check is really a
    # multi-parameter "falls within the Tenderer's own declared range" check with
    # no fixed min/max at all - fail soft into "can't determine" rather than
    # crashing on None <= value <= None.
    if value is None or minimum is None or maximum is None:
        return TransformResult(bucket=None)
    passed = minimum <= value <= maximum
    return TransformResult(bucket="positive" if passed else "negative", value=value)


def op_percentage_threshold(item: dict, rule: dict, params: dict) -> TransformResult:
    deviation = item.get(f"{rule['id']}__deviation_pct")
    if deviation is None:
        return TransformResult(bucket=None)
    if abs(deviation) <= params["max_deviation_pct"]:
        return TransformResult(bucket="neutral", value=deviation)
    # Exceeding the threshold only establishes that an explanation is required -
    # whether the Authority accepted it is a judgment call this operation can't
    # make; the caller supplies an explicit {rule_id}__outcome for that case
    # (handled upstream in core.py, ahead of any transform).
    return TransformResult(bucket=None, value=deviation)


def op_threshold_checks(item: dict, rule: dict, params: dict) -> TransformResult:
    values = item.get(f"{rule['id']}__values")
    checks = params.get("checks", [])
    if values is None or len(values) != len(checks):
        return TransformResult(bucket=None)
    for value, check in zip(values, checks):
        threshold = check["threshold"]
        if check["operation"] == "max_value_check" and value > threshold:
            return TransformResult(bucket="negative", value=values)
        if check["operation"] == "min_value_check" and value < threshold:
            return TransformResult(bucket="negative", value=values)
    return TransformResult(bucket="positive", value=values)


def op_text_match(item: dict, rule: dict, params: dict) -> TransformResult:
    condition = params.get("condition")
    if condition is not None and not item.get(condition):
        return TransformResult(bucket="neutral")
    inputs = params.get("inputs", [])
    if len(inputs) < 2:
        return TransformResult(bucket=None)
    a, b = item.get(inputs[0]), item.get(inputs[1])
    if a is None or b is None:
        return TransformResult(bucket=None)
    passed = _normalize_text(a) == _normalize_text(b)
    return TransformResult(bucket="positive" if passed else "negative")


OPERATIONS: dict[str, Callable[[dict, dict, dict], TransformResult]] = {
    "round_significant_figures": op_round_significant_figures,
    "resolve_range_to_lower_bound": op_resolve_range_to_lower_bound,
    "arithmetic_product": op_arithmetic_product,
    "add_working_days": op_add_working_days,
    "add_calendar_days": op_add_calendar_days,
    "date_not_earlier_than": op_date_not_earlier_than,
    "date_within_range": op_date_within_range,
    "min_value_check": op_min_value_check,
    "value_in_range": op_value_in_range,
    "range_check": op_value_in_range,
    "percentage_threshold": op_percentage_threshold,
    "threshold_checks": op_threshold_checks,
    "text_match": op_text_match,
}


def run_transform(operation: str, item: dict, rule: dict, params: dict) -> TransformResult:
    return OPERATIONS[operation](item, rule, params)
