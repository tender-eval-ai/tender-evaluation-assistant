from app.engine.core import evaluate_item, evaluate_rule, exclude_rules


def _critical_doc(**rule_overrides) -> dict:
    rule = {"id": "x_filled", "field_id": "x", "field": "X", "consequence_tier": "critical"}
    rule.update(rule_overrides)
    return {
        "consequence_tiers": {
            "critical": {"outcomes": {
                "blank": {"status": "disqualified", "note": "{field} is blank."},
                "filled": {"status": "pass"},
            }}
        },
        "rules": [rule],
    }


class TestExcludeRules:
    def test_removes_named_rule(self):
        doc = _critical_doc()
        filtered = exclude_rules(doc, {"x_filled"})
        assert filtered["rules"] == []

    def test_leaves_other_rules_untouched(self):
        doc = {"consequence_tiers": {}, "rules": [{"id": "a"}, {"id": "b"}]}
        filtered = exclude_rules(doc, {"a"})
        assert [r["id"] for r in filtered["rules"]] == ["b"]

    def test_empty_set_returns_original_doc_unchanged(self):
        doc = _critical_doc()
        assert exclude_rules(doc, set()) is doc

    def test_does_not_mutate_the_original_doc(self):
        doc = {"consequence_tiers": {}, "rules": [{"id": "a"}, {"id": "b"}]}
        exclude_rules(doc, {"a"})
        assert [r["id"] for r in doc["rules"]] == ["a", "b"]


class TestEvaluateRuleBasics:
    def test_filled_field_passes(self):
        doc = _critical_doc()
        result, adjustment = evaluate_rule(doc, doc["rules"][0], {"x": "some value"}, {}, {"x_filled"})
        assert result.status == "pass"
        assert adjustment is None

    def test_blank_field_disqualifies_with_field_name_substituted(self):
        doc = _critical_doc()
        result, _ = evaluate_rule(doc, doc["rules"][0], {}, {}, {"x_filled"})
        assert result.status == "disqualified"
        assert result.note == "X is blank."

    def test_no_field_id_or_outcomes_is_not_a_gate(self):
        doc = {"consequence_tiers": {}, "rules": [{"id": "context_rule", "check": "context"}]}
        result, adjustment = evaluate_rule(doc, doc["rules"][0], {}, {}, set())
        assert result is None
        assert adjustment is None

    def test_no_gate_tier_with_empty_outcomes_is_not_a_gate(self):
        doc = {
            "consequence_tiers": {"no_gate": {"outcomes": {}}},
            "rules": [{"id": "orphan", "field_id": "x", "consequence_tier": "no_gate"}],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {"x": "anything"}, {}, set())
        assert result is None


class TestStageResolution:
    # information_schedule_rules_stage2.json-shaped: no per-rule "stage" key on
    # any rule, the whole document is Stage II via a single top-level "stage"
    # key. A plain rule.get("stage", "I") default would mislabel every rule in
    # a document like this as Stage I - the real bug this class guards against.
    def test_rule_with_no_stage_key_falls_back_to_document_level_stage(self):
        doc = {"stage": "II", "consequence_tiers": {"critical": {"outcomes": {"filled": {"status": "pass"}}}},
               "rules": [{"id": "x", "field_id": "x", "consequence_tier": "critical"}]}
        result, _ = evaluate_rule(doc, doc["rules"][0], {"x": "v"}, {}, {"x"})
        assert result.stage == "II"

    # compliance_schedule_rules.json/price_schedule_rules.json-shaped: Stage I
    # and Stage II rules coexist inline in one document with no document-level
    # "stage" key - each rule's own tag is authoritative.
    def test_rule_with_explicit_stage_key_uses_it_regardless_of_document(self):
        doc = {"consequence_tiers": {"critical": {"outcomes": {"filled": {"status": "pass"}}}},
               "rules": [{"id": "x", "field_id": "x", "consequence_tier": "critical", "stage": "II"}]}
        result, _ = evaluate_rule(doc, doc["rules"][0], {"x": "v"}, {}, {"x"})
        assert result.stage == "II"

    def test_rule_with_neither_key_defaults_to_stage_i(self):
        doc = _critical_doc()
        result, _ = evaluate_rule(doc, doc["rules"][0], {"x": "v"}, {}, {"x_filled"})
        assert result.stage == "I"

    def test_rule_level_stage_wins_over_document_level_stage(self):
        doc = {"stage": "II", "consequence_tiers": {"critical": {"outcomes": {"filled": {"status": "pass"}}}},
               "rules": [{"id": "x", "field_id": "x", "consequence_tier": "critical", "stage": "I"}]}
        result, _ = evaluate_rule(doc, doc["rules"][0], {"x": "v"}, {}, {"x"})
        assert result.stage == "I"


class TestExplicitOverride:
    def test_explicit_outcome_key_wins_over_presence(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{"id": "sds_content_complete", "field_id": "safety_data_sheet",
                       "outcomes": {"content_ok": {"status": "pass"}, "content_wrong": {"status": "disqualified"}}}],
        }
        item = {"safety_data_sheet": "some extracted text", "sds_content_complete__outcome": "content_wrong"}
        result, _ = evaluate_rule(doc, doc["rules"][0], item, {}, {"sds_content_complete"})
        assert result.status == "disqualified"

    def test_explicit_override_ignored_if_not_a_real_outcome_key(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{"id": "sds_content_complete", "field_id": "safety_data_sheet",
                       "outcomes": {"content_ok": {"status": "pass"}, "content_wrong": {"status": "disqualified"}}}],
        }
        item = {"safety_data_sheet": "text", "sds_content_complete__outcome": "not_a_real_key"}
        result, _ = evaluate_rule(doc, doc["rules"][0], item, {}, {"sds_content_complete"})
        assert result.status == "needs_review"  # falls through to the safety net


class TestJudgmentCallSafetyNet:
    def test_no_transform_no_override_unresolvable_key_is_needs_review(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{"id": "sds_content_complete", "field": "SDS section completeness", "field_id": "safety_data_sheet",
                       "outcomes": {"content_ok": {"status": "pass"}, "content_wrong": {"status": "disqualified"}}}],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {"safety_data_sheet": "some text"}, {}, {"sds_content_complete"})
        assert result.status == "needs_review"
        assert "sds_content_complete__outcome" in result.note

    def test_blank_field_with_judgment_vocab_produces_no_finding_not_needs_review(self):
        # Regression: a rule with a non-presence outcome vocabulary (no "blank"
        # key) attached to a field that's actually blank must NOT hit the
        # needs_review safety net - there's nothing submitted to judge yet. Found
        # building price_schedule_parts_c_d_checker.py:
        # price_schedule_part_c_discount_decimal_precision (within_precision/
        # exceeds_precision) depends_on a deemed_default field that's often blank
        # by design (silence = no discount offered) - flagging every blank
        # discount field for review would be pure noise. The parent *_filled rule
        # already reports the blank field itself; this dependent rule should just
        # not fire.
        doc = {
            "consequence_tiers": {},
            "rules": [{"id": "discount_precision", "field_id": "discount_7day",
                       "outcomes": {"within_precision": {"status": "pass"}, "exceeds_precision": {"status": "needs_review"}}}],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {}, {}, {"discount_precision"})
        assert result is None


class TestTransformComparisonInput:
    def test_positive_bucket_maps_to_rule_specific_vocabulary(self):
        # min_value_check's positive/negative buckets must resolve against
        # whatever vocabulary THIS rule's outcomes actually use - here
        # within_range/outside_range, not the generic match/mismatch.
        doc = {
            "consequence_tiers": {},
            "rules": [{
                "id": "packing_range", "field_id": "packing_kg",
                "outcomes": {"within_range": {"status": "pass"}, "outside_range": {"status": "needs_review"}},
                "transform": {"operation": "value_in_range", "params": {"min": 500, "max": 950}, "surfaced_as": "comparison_input"},
            }],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {"packing_kg": 700}, {}, {"packing_range"})
        assert result.status == "pass"

    def test_negative_bucket_maps_to_rule_specific_vocabulary(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{
                "id": "packing_range", "field_id": "packing_kg",
                "outcomes": {"within_range": {"status": "pass"}, "outside_range": {"status": "needs_review"}},
                "transform": {"operation": "value_in_range", "params": {"min": 500, "max": 950}, "surfaced_as": "comparison_input"},
            }],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {"packing_kg": 1000}, {}, {"packing_range"})
        assert result.status == "needs_review"

    def test_on_request_only_tier_min_value_check_resolves_requested_and_met(self):
        # tender_sample_quantity-shaped case: min_value_check's positive bucket
        # must find requested_and_met (the tier's actual vocabulary), not fail
        # just because "match"/"within_range" aren't present.
        doc = {
            "consequence_tiers": {"on_request_only": {"outcomes": {
                "not_requested": {"status": "dormant"},
                "requested_and_met": {"status": "pass"},
                "requested_and_missed": {"status": "disqualified"},
            }}},
            "rules": [{
                "id": "tender_sample_quantity", "field_id": "tender_sample", "consequence_tier": "on_request_only",
                "transform": {"operation": "min_value_check", "params": {"min_kg": 600}, "surfaced_as": "comparison_input"},
            }],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {"tender_sample": 650}, {}, {"tender_sample_quantity"})
        assert result.status == "pass"

    def test_blank_on_request_only_tier_resolves_not_requested_without_running_transform(self):
        doc = {
            "consequence_tiers": {"on_request_only": {"outcomes": {
                "not_requested": {"status": "dormant"},
                "requested_and_met": {"status": "pass"},
                "requested_and_missed": {"status": "disqualified"},
            }}},
            "rules": [{
                "id": "tender_sample_quantity", "field_id": "tender_sample", "consequence_tier": "on_request_only",
                "transform": {"operation": "min_value_check", "params": {"min_kg": 600}, "surfaced_as": "comparison_input"},
            }],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {}, {}, {"tender_sample_quantity"})
        assert result.status == "dormant"

    def test_neutral_bucket_maps_to_not_applicable(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{
                "id": "name_of_manufacturer_self_entry", "field_id": "name_of_manufacturer",
                "outcomes": {"not_applicable": {"status": "pass"}, "match": {"status": "pass"}, "mismatch": {"status": "needs_review"}},
                "transform": {"operation": "text_match", "params": {"inputs": ["name_of_manufacturer", "tenderer_name"], "condition": "tenderer_is_manufacturer"}, "surfaced_as": "comparison_input"},
            }],
        }
        item = {"name_of_manufacturer": "Acme", "tenderer_name": "Other", "tenderer_is_manufacturer": False}
        result, _ = evaluate_rule(doc, doc["rules"][0], item, {}, {"name_of_manufacturer_self_entry"})
        assert result.status == "pass"
        assert result.note is None  # not_applicable's own entry has no note in this doc


class TestAutoAdjustment:
    def test_auto_adjustment_recorded_and_never_produces_a_field_result(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{
                "id": "dosage_significant_figures", "field_id": "optimal_dosage",
                "transform": {"operation": "round_significant_figures", "params": {"max_sig_figs": 2}, "surfaced_as": "auto_adjustment"},
            }],
        }
        result, adjustment = evaluate_rule(doc, doc["rules"][0], {"optimal_dosage": 5.234}, {}, set())
        assert result is None
        assert adjustment == {"rule_id": "dosage_significant_figures", "field_id": "optimal_dosage", "operation": "round_significant_figures", "value": 5.2}

    def test_no_adjustment_recorded_when_transform_has_no_input(self):
        doc = {
            "consequence_tiers": {},
            "rules": [{
                "id": "dosage_significant_figures", "field_id": "optimal_dosage",
                "transform": {"operation": "round_significant_figures", "params": {"max_sig_figs": 2}, "surfaced_as": "auto_adjustment"},
            }],
        }
        _, adjustment = evaluate_rule(doc, doc["rules"][0], {}, {}, set())
        assert adjustment is None


class TestFollowUpDeadline:
    def test_computed_deadline_populated_when_trigger_date_supplied(self):
        doc = {
            "consequence_tiers": {"mandatory_on_request": {
                "outcomes": {"blank": {"status": "dormant", "follow_up": {"trigger": "t", "deadline": "5 working days", "if_deadline_missed": "disqualified"}}},
                "transform": {"operation": "add_working_days", "params": {"offset_value": 5, "offset_unit": "working_days"}, "surfaced_as": "follow_up_deadline"},
            }},
            "rules": [{"id": "tenderer_name_filled", "field_id": "tenderer_name", "consequence_tier": "mandatory_on_request"}],
        }
        item = {"tenderer_name_filled__base_date": "2026-02-06"}
        result, _ = evaluate_rule(doc, doc["rules"][0], item, {}, {"tenderer_name_filled"})
        assert result.status == "dormant"
        assert result.follow_up.computed_deadline == "2026-02-13"
        assert result.follow_up.deadline == "5 working days"  # prose fallback still present

    def test_computed_deadline_none_when_no_trigger_date(self):
        doc = {
            "consequence_tiers": {"mandatory_on_request": {
                "outcomes": {"blank": {"status": "dormant", "follow_up": {"trigger": "t", "deadline": "5 working days", "if_deadline_missed": "disqualified"}}},
                "transform": {"operation": "add_working_days", "params": {"offset_value": 5, "offset_unit": "working_days"}, "surfaced_as": "follow_up_deadline"},
            }},
            "rules": [{"id": "tenderer_name_filled", "field_id": "tenderer_name", "consequence_tier": "mandatory_on_request"}],
        }
        result, _ = evaluate_rule(doc, doc["rules"][0], {}, {}, {"tenderer_name_filled"})
        assert result.follow_up.computed_deadline is None


class TestEvaluateItemEndToEnd:
    def test_fully_compliant_item_is_all_pass(self):
        doc = _critical_doc()
        item_result = evaluate_item([doc], {"x": "filled"}, item_no=1)
        assert item_result.overall_status == "pass"
        assert item_result.status_counts["pass"] == 1
        assert len(item_result.fields) == 1

    def test_blank_item_disqualifies(self):
        doc = _critical_doc()
        item_result = evaluate_item([doc], {}, item_no=1)
        assert item_result.overall_status == "disqualified"

    def test_context_rules_excluded_from_field_count(self):
        doc = {
            "consequence_tiers": {"critical": {"outcomes": {"blank": {"status": "disqualified"}, "filled": {"status": "pass"}}}},
            "rules": [
                {"id": "context_only", "check": "context"},
                {"id": "real_rule", "field_id": "x", "consequence_tier": "critical"},
            ],
        }
        item_result = evaluate_item([doc], {"x": "filled"}, item_no=1)
        assert len(item_result.fields) == 1
        assert item_result.fields[0].field_id == "x"

    def test_two_level_dependency_chain_propagates_disqualification(self):
        doc = {
            "consequence_tiers": {"on_request_only": {"outcomes": {
                "not_requested": {"status": "dormant"},
                "requested_and_met": {"status": "pass"},
                "requested_and_missed": {"status": "disqualified"},
            }}},
            "rules": [
                {"id": "tender_sample_filled", "field_id": "tender_sample", "consequence_tier": "on_request_only"},
                {"id": "plant_trial_effectiveness", "field_id": "plant_trial", "depends_on": "tender_sample_filled",
                 "outcomes": {"effective_and_not_aborted": {"status": "pass"}, "not_effective_or_aborted": {"status": "disqualified"}}},
                {"id": "additional_sample_required", "field_id": "additional_sample", "depends_on": "plant_trial_effectiveness",
                 "consequence_tier": "on_request_only"},
            ],
        }
        # tender_sample_filled__outcome forces the disqualifying branch directly -
        # simpler than reverse-engineering a raw value that resolves to it.
        item = {"tender_sample_filled__outcome": "requested_and_missed"}
        item_result = evaluate_item([doc], item, item_no=1)
        field_ids = {f.field_id for f in item_result.fields}
        assert field_ids == {"tender_sample"}  # plant_trial_effectiveness and additional_sample_required both skipped

    def test_multi_doc_cross_file_dependency(self):
        # information_schedule_rules.json + information_schedule_rules_stage2.json
        # shape: a stage2 rule depends_on a stage1 rule that lives in a different doc.
        stage1 = {
            "consequence_tiers": {"critical": {"outcomes": {"blank": {"status": "disqualified"}, "filled": {"status": "pass"}}}},
            "rules": [{"id": "iso_certificate_filled", "field_id": "iso_certificate", "consequence_tier": "critical"}],
        }
        stage2 = {
            "consequence_tiers": {},
            "rules": [{"id": "iso_certificate_scope_check", "field_id": "iso_certificate", "depends_on": "iso_certificate_filled",
                       "outcomes": {"content_ok": {"status": "pass"}, "content_wrong": {"status": "disqualified"}}}],
        }
        item = {}  # iso_certificate blank -> iso_certificate_filled disqualifies -> scope check must be skipped
        item_result = evaluate_item([stage1, stage2], item, item_no=1)
        field_ids = {f.field_id for f in item_result.fields}
        assert field_ids == {"iso_certificate"}
        assert len(item_result.fields) == 1  # only iso_certificate_filled - scope_check skipped
