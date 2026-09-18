import pytest

from app.engine.depends import RuleGraphError, is_dependency_satisfied, resolution_order
from app.engine.field_result import FieldResult


def _result(status: str) -> FieldResult:
    return FieldResult(field_id="x", field="X", value=None, status=status, confidence=None, source=None, note=None)


def test_no_dependency_is_always_satisfied():
    assert is_dependency_satisfied({"id": "a"}, {}, set()) is True


def test_evaluable_parent_disqualified_blocks_child():
    rule = {"id": "child", "depends_on": "parent"}
    assert is_dependency_satisfied(rule, {"parent": _result("disqualified")}, {"parent"}) is False


def test_evaluable_parent_dormant_blocks_child():
    rule = {"id": "child", "depends_on": "parent"}
    assert is_dependency_satisfied(rule, {"parent": _result("dormant")}, {"parent"}) is False


def test_evaluable_parent_pass_allows_child():
    rule = {"id": "child", "depends_on": "parent"}
    assert is_dependency_satisfied(rule, {"parent": _result("pass")}, {"parent"}) is True


def test_evaluable_parent_needs_review_allows_child():
    # needs_review isn't a hard stop the way disqualified/dormant are - a field
    # flagged for human review might still turn out fine, so downstream checks
    # that depend on it should still run rather than being silently suppressed.
    rule = {"id": "child", "depends_on": "parent"}
    assert is_dependency_satisfied(rule, {"parent": _result("needs_review")}, {"parent"}) is True


def test_non_evaluable_parent_always_allows_child():
    # manufacturer_letter_of_intent_filled depends_on a pure "context" rule with no
    # field_id/outcomes - nothing was ever resolved for it, so there's no status to
    # gate on. Policy: evaluate anyway rather than silently drop the check.
    # "context_only_parent" is absent from evaluable_ids because it has no
    # outcomes at all - never would have produced a FieldResult even in principle.
    rule = {"id": "child", "depends_on": "context_only_parent"}
    assert is_dependency_satisfied(rule, {}, set()) is True


def test_evaluable_parent_blocked_by_its_own_dependency_propagates_the_block():
    # additional_sample_required depends_on plant_trial_effectiveness depends_on
    # tender_sample_filled (real 2-level chain, tender_sample_plant_trial_rules.json).
    # If tender_sample_filled disqualifies, plant_trial_effectiveness is itself
    # skipped (never added to `resolved`) - but it WOULD have been evaluable (it
    # has real outcomes), so its absence must propagate as a block, not be read as
    # "nothing to gate on."
    rule = {"id": "additional_sample_required", "depends_on": "plant_trial_effectiveness"}
    resolved = {"tender_sample_filled": _result("disqualified")}  # plant_trial_effectiveness absent - it was skipped
    evaluable_ids = {"tender_sample_filled", "plant_trial_effectiveness", "additional_sample_required"}
    assert is_dependency_satisfied(rule, resolved, evaluable_ids) is False


class TestResolutionOrder:
    def test_independent_rules_keep_relative_order(self):
        rules = [{"id": "a"}, {"id": "b"}]
        assert [r["id"] for r in resolution_order(rules)] == ["a", "b"]

    def test_child_is_moved_after_its_parent_even_if_declared_first(self):
        rules = [{"id": "child", "depends_on": "parent"}, {"id": "parent"}]
        order = [r["id"] for r in resolution_order(rules)]
        assert order.index("parent") < order.index("child")

    def test_two_level_chain_resolves_correctly(self):
        # additional_sample_required -> plant_trial_effectiveness -> tender_sample_filled
        rules = [
            {"id": "additional_sample_required", "depends_on": "plant_trial_effectiveness"},
            {"id": "plant_trial_effectiveness", "depends_on": "tender_sample_filled"},
            {"id": "tender_sample_filled"},
        ]
        order = [r["id"] for r in resolution_order(rules)]
        assert order.index("tender_sample_filled") < order.index("plant_trial_effectiveness")
        assert order.index("plant_trial_effectiveness") < order.index("additional_sample_required")

    def test_dependency_on_a_rule_outside_this_file_is_not_an_error(self):
        # information_schedule_rules_stage2.json's rules depend_on ids that live in
        # the sibling stage1 file - resolution_order only needs to order what's
        # actually present, an external dependency isn't a graph node here.
        rules = [{"id": "a", "depends_on": "some_other_files_rule"}]
        assert [r["id"] for r in resolution_order(rules)] == ["a"]

    def test_cycle_raises(self):
        rules = [{"id": "a", "depends_on": "b"}, {"id": "b", "depends_on": "a"}]
        with pytest.raises(RuleGraphError):
            resolution_order(rules)
