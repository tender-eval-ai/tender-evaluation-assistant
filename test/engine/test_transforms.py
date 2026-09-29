from app.engine.transforms import TransformResult, run_transform


def _rule(**overrides) -> dict:
    rule = {"id": "test_rule", "field_id": "test_field"}
    rule.update(overrides)
    return rule


class TestRoundSignificantFigures:
    def test_rounds_down_below_five(self):
        rule = _rule()
        result = run_transform("round_significant_figures", {"test_field": 5.234}, rule, {"max_sig_figs": 2})
        assert result.value == 5.2

    def test_rounds_up_at_tie_per_technical_specifications_remark_3(self):
        # Technical Specifications Clause 3 Remark (3): round up if the next
        # significant figure is >=5.
        rule = _rule()
        result = run_transform("round_significant_figures", {"test_field": 5.25}, rule, {"max_sig_figs": 2})
        assert result.value == 5.3

    def test_value_already_within_sig_figs_is_unchanged(self):
        rule = _rule()
        result = run_transform("round_significant_figures", {"test_field": 5.2}, rule, {"max_sig_figs": 2})
        assert result.value == 5.2

    def test_never_touches_bucket_auto_adjustment_only(self):
        rule = _rule()
        result = run_transform("round_significant_figures", {"test_field": 5.234}, rule, {"max_sig_figs": 2})
        assert result.bucket is None


class TestResolveRangeToLowerBound:
    def test_range_resolves_to_lower_value(self):
        rule = _rule()
        result = run_transform("resolve_range_to_lower_bound", {"test_field": 5.2, "test_field_max": 7.2}, rule, {})
        assert result.value == 5.2

    def test_single_value_passes_through_unchanged(self):
        rule = _rule()
        result = run_transform("resolve_range_to_lower_bound", {"test_field": 5.2}, rule, {})
        assert result.value == 5.2

    def test_missing_value_returns_none(self):
        rule = _rule()
        result = run_transform("resolve_range_to_lower_bound", {}, rule, {})
        assert result.value is None


class TestArithmeticProduct:
    def test_matching_product_is_positive(self):
        rule = _rule(field_id="estimated_goods_price")
        item = {"estimated_quantity": 1102000, "one_time_unit_price": 24.6, "estimated_goods_price": 27109200}
        result = run_transform(
            "arithmetic_product", item, rule,
            {"inputs": ["estimated_quantity", "one_time_unit_price"]},
        )
        assert result.bucket == "positive"
        assert result.value == 27109200

    def test_mismatched_product_is_negative(self):
        rule = _rule(field_id="estimated_goods_price")
        item = {"estimated_quantity": 1102000, "one_time_unit_price": 24.6, "estimated_goods_price": 1.0}
        result = run_transform(
            "arithmetic_product", item, rule,
            {"inputs": ["estimated_quantity", "one_time_unit_price"]},
        )
        assert result.bucket == "negative"

    def test_within_tolerance_rounding_is_positive(self):
        rule = _rule(field_id="estimated_goods_price")
        item = {"estimated_quantity": 3, "one_time_unit_price": 0.333, "estimated_goods_price": 1.0}
        result = run_transform(
            "arithmetic_product", item, rule,
            {"inputs": ["estimated_quantity", "one_time_unit_price"]},
        )
        assert result.bucket == "positive"

    def test_missing_input_cannot_determine(self):
        rule = _rule(field_id="estimated_goods_price")
        item = {"estimated_quantity": 1102000, "estimated_goods_price": 1.0}
        result = run_transform(
            "arithmetic_product", item, rule,
            {"inputs": ["estimated_quantity", "one_time_unit_price"]},
        )
        assert result.bucket is None


class TestAddWorkingDays:
    def test_computes_forward_date_skipping_weekend(self):
        # Friday 2026-02-06 + 5 working days: Mon 9, Tue 10, Wed 11, Thu 12, Fri 13
        rule = _rule(id="tenderer_name_filled")
        item = {"tenderer_name_filled__base_date": "2026-02-06"}
        result = run_transform(
            "add_working_days", item, rule,
            {"base_date": "follow_up.trigger_date", "offset_value": 5, "offset_unit": "working_days"},
        )
        assert result.computed_date == "2026-02-13"

    def test_supports_legacy_nested_offset_param_shape(self):
        # tender_sample_plant_trial_rules.json's tender_sample_submission_deadline
        # uses {"offset": {"value": N, "unit": "..."}} instead of the flat
        # offset_value/offset_unit shape - both must resolve identically.
        rule = _rule(id="tender_sample_submission_deadline")
        item = {"tender_sample_submission_deadline__base_date": "2026-02-06"}
        result = run_transform(
            "add_working_days", item, rule,
            {"base_date": "date of the Authority's written request", "offset": {"value": 5, "unit": "working_days"}},
        )
        assert result.computed_date == "2026-02-13"

    def test_falls_back_to_common_authority_request_date_key(self):
        rule = _rule(id="some_rule")
        item = {"authority_request_date": "2026-02-06"}
        result = run_transform("add_working_days", item, rule, {"offset_value": 5, "offset_unit": "working_days"})
        assert result.computed_date == "2026-02-13"

    def test_no_base_date_available_returns_none(self):
        rule = _rule(id="some_rule")
        result = run_transform("add_working_days", {}, rule, {"offset_value": 5, "offset_unit": "working_days"})
        assert result.computed_date is None

    def test_actual_date_on_or_before_deadline_is_positive(self):
        # test_report_lab_appointment_deadline-shaped case: add_working_days used
        # with surfaced_as: comparison_input (on_time/late), not just
        # follow_up_deadline - needs an actual observed date to compare against
        # the computed deadline, not just the deadline itself.
        rule = _rule(id="test_report_lab_appointment_deadline")
        item = {
            "test_report_lab_appointment_deadline__base_date": "2026-02-06",
            "test_report_lab_appointment_deadline__actual_date": "2026-02-13",
        }
        result = run_transform("add_working_days", item, rule, {"offset_value": 5, "offset_unit": "working_days"})
        assert result.bucket == "positive"

    def test_actual_date_after_deadline_is_negative(self):
        rule = _rule(id="test_report_lab_appointment_deadline")
        item = {
            "test_report_lab_appointment_deadline__base_date": "2026-02-06",
            "test_report_lab_appointment_deadline__actual_date": "2026-02-16",
        }
        result = run_transform("add_working_days", item, rule, {"offset_value": 5, "offset_unit": "working_days"})
        assert result.bucket == "negative"

    def test_no_actual_date_leaves_bucket_none_deadline_still_computed(self):
        # follow_up_deadline usage (mandatory_on_request tier) never supplies an
        # actual_date - only wants the computed deadline, not a pass/fail.
        rule = _rule(id="tenderer_name_filled")
        item = {"tenderer_name_filled__base_date": "2026-02-06"}
        result = run_transform("add_working_days", item, rule, {"offset_value": 5, "offset_unit": "working_days"})
        assert result.bucket is None
        assert result.computed_date == "2026-02-13"


class TestAddCalendarDays:
    def test_counts_weekends(self):
        # Terms of Tender (Supplement) Paragraph 10(c)/(e): 14 calendar days, not
        # working days - a Friday-start 14-day window includes both weekends.
        rule = _rule(id="tender_sample_submission_deadline")
        item = {"tender_sample_submission_deadline__base_date": "2026-02-06"}
        result = run_transform(
            "add_calendar_days", item, rule,
            {"offset_value": 14, "offset_unit": "calendar_days"},
        )
        assert result.computed_date == "2026-02-20"


class TestDateNotEarlierThan:
    def test_within_max_age_is_positive(self):
        rule = _rule(field_id="product_specs_issue_date")
        item = {"product_specs_issue_date": "2026-01-01", "tender_closing_date": "2026-06-01"}
        result = run_transform(
            "date_not_earlier_than", item, rule,
            {"reference_date": "Tender Closing Date", "max_age_value": 12, "max_age_unit": "months", "inputs": ["product_specs_issue_date"]},
        )
        assert result.bucket == "positive"

    def test_exactly_at_boundary_is_positive(self):
        # rule text: "issue date must be >= (Tender Closing Date minus 12 months)" -
        # inclusive boundary.
        rule = _rule(field_id="product_specs_issue_date")
        item = {"product_specs_issue_date": "2025-06-01", "tender_closing_date": "2026-06-01"}
        result = run_transform(
            "date_not_earlier_than", item, rule,
            {"reference_date": "Tender Closing Date", "max_age_value": 12, "max_age_unit": "months", "inputs": ["product_specs_issue_date"]},
        )
        assert result.bucket == "positive"

    def test_too_old_is_negative(self):
        rule = _rule(field_id="product_specs_issue_date")
        item = {"product_specs_issue_date": "2024-01-01", "tender_closing_date": "2026-06-01"}
        result = run_transform(
            "date_not_earlier_than", item, rule,
            {"reference_date": "Tender Closing Date", "max_age_value": 12, "max_age_unit": "months", "inputs": ["product_specs_issue_date"]},
        )
        assert result.bucket == "negative"

    def test_missing_reference_date_cannot_determine(self):
        rule = _rule(field_id="product_specs_issue_date")
        item = {"product_specs_issue_date": "2026-01-01"}
        result = run_transform(
            "date_not_earlier_than", item, rule,
            {"reference_date": "Tender Closing Date", "max_age_value": 12, "max_age_unit": "months", "inputs": ["product_specs_issue_date"]},
        )
        assert result.bucket is None


class TestDateWithinRange:
    def test_check_date_inside_validity_period_is_positive(self):
        rule = _rule(field_id="iso_certificate")
        item = {
            "tender_closing_date": "2026-06-01",
            "iso_certificate_issue_date": "2025-01-01",
            "iso_certificate_expiry_date": "2027-01-01",
        }
        result = run_transform("date_within_range", item, rule, {})
        assert result.bucket == "positive"

    def test_check_date_on_expiry_boundary_is_positive(self):
        rule = _rule(field_id="iso_certificate")
        item = {
            "tender_closing_date": "2026-06-01",
            "iso_certificate_issue_date": "2025-01-01",
            "iso_certificate_expiry_date": "2026-06-01",
        }
        result = run_transform("date_within_range", item, rule, {})
        assert result.bucket == "positive"

    def test_check_date_after_expiry_is_negative(self):
        rule = _rule(field_id="iso_certificate")
        item = {
            "tender_closing_date": "2026-06-01",
            "iso_certificate_issue_date": "2025-01-01",
            "iso_certificate_expiry_date": "2026-01-01",
        }
        result = run_transform("date_within_range", item, rule, {})
        assert result.bucket == "negative"


class TestMinValueCheck:
    def test_above_minimum_is_positive(self):
        rule = _rule(field_id="tender_sample")
        result = run_transform("min_value_check", {"tender_sample": 650}, rule, {"min_kg": 600})
        assert result.bucket == "positive"

    def test_exactly_at_minimum_is_positive(self):
        rule = _rule(field_id="tender_sample")
        result = run_transform("min_value_check", {"tender_sample": 600}, rule, {"min_kg": 600})
        assert result.bucket == "positive"

    def test_below_minimum_is_negative(self):
        rule = _rule(field_id="tender_sample")
        result = run_transform("min_value_check", {"tender_sample": 599}, rule, {"min_kg": 600})
        assert result.bucket == "negative"


class TestValueInRangeAndRangeCheck:
    def test_value_in_range_within_bounds(self):
        rule = _rule(field_id="packing_plant_net_weight_kg")
        result = run_transform("value_in_range", {"packing_plant_net_weight_kg": 700}, rule, {"min": 500, "max": 950})
        assert result.bucket == "positive"

    def test_value_in_range_at_lower_boundary(self):
        rule = _rule(field_id="packing_plant_net_weight_kg")
        result = run_transform("value_in_range", {"packing_plant_net_weight_kg": 500}, rule, {"min": 500, "max": 950})
        assert result.bucket == "positive"

    def test_value_in_range_at_upper_boundary(self):
        rule = _rule(field_id="packing_plant_net_weight_kg")
        result = run_transform("value_in_range", {"packing_plant_net_weight_kg": 950}, rule, {"min": 500, "max": 950})
        assert result.bucket == "positive"

    def test_value_in_range_outside_bounds(self):
        rule = _rule(field_id="packing_plant_net_weight_kg")
        result = run_transform("value_in_range", {"packing_plant_net_weight_kg": 1000}, rule, {"min": 500, "max": 950})
        assert result.bucket == "negative"

    def test_range_check_is_the_same_operation_under_a_different_name(self):
        rule = _rule(field_id="tender_sample")
        result = run_transform("range_check", {"tender_sample": 500}, rule, {"min_kg": 500, "max_kg": 950})
        assert result.bucket == "positive"

    def test_missing_bounds_cannot_determine_rather_than_crashing(self):
        # test_report_compliance_with_product_specs declares range_check with no
        # numeric min/max at all (its real check is "each parameter falls within
        # the Tenderer's own declared range from Product Specs" - a multi-
        # parameter comparison this fixed-bound operation can't express). Must
        # fail soft into "can't determine", not raise on None <= value <= None.
        rule = _rule(field_id="test_report_submission")
        result = run_transform("range_check", {"test_report_submission": 42}, rule, {"rule": "descriptive text only"})
        assert result.bucket is None


class TestPercentageThreshold:
    def test_deviation_within_threshold_is_neutral_not_applicable(self):
        rule = _rule(id="product_specs_deviation_explanation")
        item = {"product_specs_deviation_explanation__deviation_pct": 15}
        result = run_transform("percentage_threshold", item, rule, {"max_deviation_pct": 20})
        assert result.bucket == "neutral"

    def test_deviation_exactly_at_threshold_is_neutral(self):
        # Source text says "deviates more than 20%" - exactly 20% doesn't trigger.
        rule = _rule(id="product_specs_deviation_explanation")
        item = {"product_specs_deviation_explanation__deviation_pct": 20}
        result = run_transform("percentage_threshold", item, rule, {"max_deviation_pct": 20})
        assert result.bucket == "neutral"

    def test_deviation_exceeding_threshold_cannot_auto_determine(self):
        # Exceeding the threshold only means an explanation is *required* - whether
        # the Authority accepted it is a judgment call this operation cannot make
        # on its own; the caller must supply an explicit outcome override.
        rule = _rule(id="product_specs_deviation_explanation")
        item = {"product_specs_deviation_explanation__deviation_pct": 25}
        result = run_transform("percentage_threshold", item, rule, {"max_deviation_pct": 20})
        assert result.bucket is None

    def test_no_deviation_supplied_cannot_determine(self):
        rule = _rule(id="product_specs_deviation_explanation")
        result = run_transform("percentage_threshold", {}, rule, {"max_deviation_pct": 20})
        assert result.bucket is None


class TestThresholdChecks:
    def test_all_checks_pass(self):
        rule = _rule(id="product_specs_substantiates_values")
        item = {"product_specs_substantiates_values__values": [8, 96]}
        params = {"checks": [
            {"operation": "max_value_check", "threshold": 10},
            {"operation": "min_value_check", "threshold": 95},
        ]}
        result = run_transform("threshold_checks", item, rule, params)
        assert result.bucket == "positive"

    def test_one_check_fails(self):
        rule = _rule(id="product_specs_substantiates_values")
        item = {"product_specs_substantiates_values__values": [12, 96]}  # moisture 12% > 10% max
        params = {"checks": [
            {"operation": "max_value_check", "threshold": 10},
            {"operation": "min_value_check", "threshold": 95},
        ]}
        result = run_transform("threshold_checks", item, rule, params)
        assert result.bucket == "negative"

    def test_boundary_values_pass(self):
        rule = _rule(id="product_specs_substantiates_values")
        item = {"product_specs_substantiates_values__values": [10, 95]}
        params = {"checks": [
            {"operation": "max_value_check", "threshold": 10},
            {"operation": "min_value_check", "threshold": 95},
        ]}
        result = run_transform("threshold_checks", item, rule, params)
        assert result.bucket == "positive"


class TestTextMatch:
    def test_exact_match_is_positive(self):
        rule = _rule(id="name_of_manufacturer_self_entry")
        item = {"name_of_manufacturer": "Acme Chemicals GmbH", "tenderer_name": "Acme Chemicals GmbH"}
        result = run_transform(
            "text_match", item, rule,
            {"inputs": ["name_of_manufacturer", "tenderer_name"]},
        )
        assert result.bucket == "positive"

    def test_case_and_whitespace_insensitive_match(self):
        rule = _rule(id="name_of_manufacturer_self_entry")
        item = {"name_of_manufacturer": "  ACME chemicals GmbH  ", "tenderer_name": "Acme Chemicals GmbH"}
        result = run_transform(
            "text_match", item, rule,
            {"inputs": ["name_of_manufacturer", "tenderer_name"]},
        )
        assert result.bucket == "positive"

    def test_mismatch_is_negative(self):
        rule = _rule(id="name_of_manufacturer_self_entry")
        item = {"name_of_manufacturer": "Acme Chemicals GmbH", "tenderer_name": "Other Corp Ltd"}
        result = run_transform(
            "text_match", item, rule,
            {"inputs": ["name_of_manufacturer", "tenderer_name"]},
        )
        assert result.bucket == "negative"

    def test_condition_false_is_neutral_not_applicable(self):
        # particulars_of_goods_schedule_rules.json's self-entry rules: only
        # applicable when tenderer_is_manufacturer is true.
        rule = _rule(id="name_of_manufacturer_self_entry")
        item = {"name_of_manufacturer": "Acme Chemicals GmbH", "tenderer_name": "Other Corp Ltd", "tenderer_is_manufacturer": False}
        result = run_transform(
            "text_match", item, rule,
            {"inputs": ["name_of_manufacturer", "tenderer_name"], "condition": "tenderer_is_manufacturer"},
        )
        assert result.bucket == "neutral"

    def test_missing_comparison_value_cannot_determine(self):
        rule = _rule(id="iso_certificate_address_match")
        item = {"address_of_manufacturing_plant": "123 Main St"}
        result = run_transform(
            "text_match", item, rule,
            {"inputs": ["iso_certificate_manufacturer_address", "address_of_manufacturing_plant"]},
        )
        assert result.bucket is None


def test_transform_result_is_the_uniform_return_type():
    result = TransformResult(bucket="positive", value=42, computed_date=None)
    assert result.bucket == "positive"
    assert result.value == 42
    assert result.computed_date is None
