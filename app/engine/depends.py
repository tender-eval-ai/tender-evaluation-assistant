from app.engine.field_result import FieldResult

_BLOCKING_STATUSES = {"disqualified", "dormant"}


class RuleGraphError(Exception):
    pass


def is_dependency_satisfied(rule: dict, resolved: dict[str, FieldResult], evaluable_ids: set[str]) -> bool:
    parent_id = rule.get("depends_on")
    if parent_id is None:
        return True
    parent_result = resolved.get(parent_id)
    if parent_result is not None:
        return parent_result.status not in _BLOCKING_STATUSES
    if parent_id not in evaluable_ids:
        # Parent was never going to produce a FieldResult at all (a pure "context"
        # rule with no field_id/outcomes, e.g.
        # manufacturer_letter_of_intent_conditional_trigger) - nothing to gate on.
        # Policy: evaluate the child anyway rather than silently drop a check
        # because its stated dependency turned out to be undeterminable.
        return True
    # Parent WAS evaluable (has real outcomes) but produced no FieldResult this
    # run - it was itself skipped because *its* dependency blocked it
    # (additional_sample_required -> plant_trial_effectiveness ->
    # tender_sample_filled: a disqualified tender_sample_filled skips
    # plant_trial_effectiveness, which must propagate to skip this rule too,
    # not be read as "nothing to gate on").
    return False


def resolution_order(rules: list[dict]) -> list[dict]:
    # Topological sort so a rule is always resolved after whatever it depends_on
    # (when that parent is itself one of these rules) - needed because JSON rule
    # order isn't guaranteed dependency-safe (nothing enforces it when a file is
    # hand-edited), and multi-level chains (additional_sample_required ->
    # plant_trial_effectiveness -> tender_sample_filled) need every ancestor
    # resolved first, not just the immediate parent.
    by_id = {rule["id"]: rule for rule in rules}
    ordered: list[dict] = []
    visited: set[str] = set()
    in_progress: set[str] = set()

    def visit(rule: dict) -> None:
        rule_id = rule["id"]
        if rule_id in visited:
            return
        if rule_id in in_progress:
            raise RuleGraphError(f"depends_on cycle detected at rule {rule_id!r}")
        in_progress.add(rule_id)
        parent_id = rule.get("depends_on")
        parent = by_id.get(parent_id) if parent_id is not None else None
        if parent is not None:
            visit(parent)
        in_progress.discard(rule_id)
        visited.add(rule_id)
        ordered.append(rule)

    for rule in rules:
        visit(rule)
    return ordered
