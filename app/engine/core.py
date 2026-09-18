from app.engine.depends import is_dependency_satisfied, resolution_order
from app.engine.outcomes import get_tier, resolve_outcomes
from app.engine.state import classify_presence
from app.engine.transforms import run_transform
from app.engine.result import ItemCheckResult, assemble
from app.engine.field_result import FieldResult, FollowUp

# Every comparison-shaped transform reports one of positive/negative/neutral -
# these tables map that generic 3-way result onto whatever specific vocabulary a
# rule's own `outcomes` actually declares (match/mismatch, within_range/
# outside_range, valid/invalid, requested_and_met/requested_and_missed, ...).
# First candidate present in the rule's resolved outcomes wins - new vocabulary
# pairs are a one-line addition here, never a JSON rewrite.
POSITIVE_KEYS = (
    "match", "within_range", "within_precision", "valid", "compliant", "confirmed_compliant",
    "accredited", "on_time", "requested_and_met", "content_ok", "complete", "sealed",
    "bundled", "not_a_postal_box", "no_extra_charges", "receipt_confirmed",
    "effective_and_not_aborted",
)
NEGATIVE_KEYS = (
    "mismatch", "outside_range", "exceeds_precision", "invalid", "non_compliant", "noncompliant",
    "expressly_non_compliant", "not_accredited", "late", "requested_and_missed", "content_wrong",
    "incomplete", "not_sealed", "not_bundled", "postal_box", "extra_charges_proposed",
    "no_receipt_evidence", "not_effective_or_aborted",
)
NEUTRAL_KEYS = ("not_applicable", "not_requested", "unstated", "na")


def _first_present(outcomes: dict, candidates: tuple[str, ...]) -> str | None:
    return next((key for key in candidates if key in outcomes), None)


def _effective_params(transform: dict) -> dict:
    # "inputs"/"condition" live as siblings of "params" inside a transform block
    # in every real rules file (goods_price_math, the self-entry rules,
    # iso_certificate_address_match, product_specs_issue_date/_deviation_
    # explanation), not nested inside it - operations read them via params.get(),
    # so merge everything into one dict here rather than at every call site.
    params = dict(transform.get("params", {}))
    for key in ("inputs", "condition"):
        if key in transform:
            params[key] = transform[key]
    return params


def _resolve_outcome_key(rule: dict, resolved_outcomes: dict, item: dict, presence_state: str | None) -> str | None:
    explicit = item.get(f"{rule['id']}__outcome")
    if explicit is not None and explicit in resolved_outcomes:
        return explicit

    if presence_state == "redacted" and "redacted" in resolved_outcomes:
        return "redacted"
    if presence_state == "not_applicable" and "not_applicable" in resolved_outcomes:
        return "not_applicable"
    if presence_state == "blank":
        if "blank" in resolved_outcomes:
            return "blank"
        neutral = _first_present(resolved_outcomes, NEUTRAL_KEYS)
        if neutral:
            return neutral
        # No blank/neutral key defined for this rule - fall through rather than
        # give up, in case a transform or the plain "filled" key still resolves it.

    transform = rule.get("transform")
    if transform and transform.get("surfaced_as") == "comparison_input":
        result = run_transform(transform["operation"], item, rule, _effective_params(transform))
        bucket_keys = {"positive": POSITIVE_KEYS, "negative": NEGATIVE_KEYS, "neutral": NEUTRAL_KEYS}.get(result.bucket)
        if bucket_keys:
            key = _first_present(resolved_outcomes, bucket_keys)
            if key:
                return key

    if presence_state == "filled" and "filled" in resolved_outcomes:
        return "filled"

    return None


def _run_auto_adjustment(rule: dict, item: dict) -> dict | None:
    transform = rule.get("transform")
    if not transform or transform.get("surfaced_as") != "auto_adjustment":
        return None
    result = run_transform(transform["operation"], item, rule, _effective_params(transform))
    if result.value is None:
        return None
    return {
        "rule_id": rule["id"],
        "field_id": rule.get("field_id"),
        "operation": transform["operation"],
        "value": result.value,
    }


def _build_follow_up(rules_doc: dict, rule: dict, item: dict, outcome_entry: dict) -> FollowUp | None:
    raw_follow_up = outcome_entry.get("follow_up")
    if raw_follow_up is None:
        return None
    follow_up = FollowUp(**raw_follow_up)
    tier = get_tier(rules_doc, rule.get("consequence_tier"))
    tier_transform = tier.get("transform") if tier else None
    if tier_transform and tier_transform.get("surfaced_as") == "follow_up_deadline":
        deadline_result = run_transform(tier_transform["operation"], item, rule, _effective_params(tier_transform))
        follow_up.computed_deadline = deadline_result.computed_date
    return follow_up


def evaluate_rule(
    rules_doc: dict, rule: dict, item: dict, resolved: dict[str, FieldResult], evaluable_ids: set[str]
) -> tuple[FieldResult | None, dict | None]:
    auto_adjustment = _run_auto_adjustment(rule, item)

    resolved_outcomes = resolve_outcomes(rules_doc, rule)
    if not resolved_outcomes:
        return None, auto_adjustment  # not a gate - context/definitional/no_gate rule
    if not is_dependency_satisfied(rule, resolved, evaluable_ids):
        return None, auto_adjustment  # dependency chain blocked - skip, don't flag

    field_id = rule.get("field_id")
    presence_state = classify_presence(item, field_id) if field_id else None
    outcome_key = _resolve_outcome_key(rule, resolved_outcomes, item, presence_state)
    if outcome_key is None:
        if presence_state == "blank":
            # Nothing to evaluate: the underlying field is blank, this rule has no
            # blank/neutral outcome of its own (a judgment-call rule like content_
            # ok/content_wrong that presupposes something was actually submitted),
            # and no explicit override was given. Distinct from "filled but can't
            # judge" below - there's no content here to judge at all, so a
            # dependent judgment-call rule simply doesn't fire (its parent *_filled
            # rule already reports the blank field itself).
            return None, auto_adjustment
        outcome_entry = {
            "status": "needs_review",
            "note": f"Could not be automatically determined - needs an explicit {rule['id']}__outcome.",
        }
    else:
        outcome_entry = resolved_outcomes[outcome_key]

    field_label = rule.get("field", field_id or rule["id"])
    note = outcome_entry.get("note")
    if note:
        note = note.replace("{field}", field_label)
    status = outcome_entry["status"]
    follow_up = _build_follow_up(rules_doc, rule, item, outcome_entry) if status == "dormant" else None

    field_result = FieldResult(
        field_id=field_id or rule["id"],
        field=field_label,
        value=item.get(field_id) if field_id else None,
        status=status,
        confidence=item.get(f"{field_id}_confidence") if field_id else None,
        source=rule.get("source"),
        note=note,
        follow_up=follow_up,
        redacted=outcome_key == "redacted",
        # Per-rule "stage" wins if present (compliance_schedule_rules.json,
        # tender_sample_plant_trial_rules.json, and the two single-rule cases in
        # price_schedule_rules.json/particulars_of_goods_schedule_rules.json all
        # tag Stage II rules this way, inline alongside Stage I rules in the same
        # file). Otherwise fall back to the owning document's own top-level
        # "stage" - information_schedule_rules_stage2.json's 12 rules carry no
        # per-rule "stage" key at all, since the whole file is Stage II by
        # construction (loaded as the second doc in
        # information_schedule_checker.py's evaluate_item call, top-level
        # "stage": "II"); a plain rule.get("stage", "I") default would mislabel
        # every one of them as Stage I. Ordinary Stage I files have neither key
        # at either level and fall through to "I".
        stage=rule.get("stage") or rules_doc.get("stage", "I"),
    )
    return field_result, auto_adjustment


def exclude_rules(rules_doc: dict, rule_ids: set[str]) -> dict:
    # Escape hatch for a recurring schema gap: some rules' applicability is only
    # described in prose on a "context" rule with no field_id/outcomes/condition
    # (e.g. manufacturer_letter_of_intent_conditional_trigger, "required only if
    # the Tenderer is not itself the Manufacturer") - nothing machine-readable for
    # depends_on to gate on generically. A checker that knows the real-world
    # condition (from its own item contract) filters the inapplicable rule out
    # entirely before handing the doc to evaluate_item, rather than letting it
    # mis-evaluate as if unconditionally required.
    if not rule_ids:
        return rules_doc
    return {**rules_doc, "rules": [r for r in rules_doc["rules"] if r["id"] not in rule_ids]}


def evaluate_item(rules_docs: list[dict], item: dict, item_no) -> ItemCheckResult:
    rule_owner: dict[str, dict] = {}
    all_rules: list[dict] = []
    for doc in rules_docs:
        for rule in doc.get("rules", []):
            rule_owner[rule["id"]] = doc
            all_rules.append(rule)

    evaluable_ids = {r["id"] for r in all_rules if resolve_outcomes(rule_owner[r["id"]], r)}

    resolved: dict[str, FieldResult] = {}
    fields: list[FieldResult] = []
    auto_adjustments: list[dict] = []

    for rule in resolution_order(all_rules):
        owner_doc = rule_owner[rule["id"]]
        result, adjustment = evaluate_rule(owner_doc, rule, item, resolved, evaluable_ids)
        if adjustment is not None:
            auto_adjustments.append(adjustment)
        if result is not None:
            resolved[rule["id"]] = result
            fields.append(result)

    return assemble(item_no, fields, auto_adjustments)
