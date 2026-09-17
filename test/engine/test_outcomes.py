from app.engine.outcomes import resolve_outcomes, resolve_outcome, get_tier


def _rules_doc(**overrides) -> dict:
    doc = {
        "consequence_tiers": {
            "critical": {
                "outcomes": {
                    "blank": {"status": "disqualified", "note": "{field} is blank."},
                    "filled": {"status": "pass"},
                }
            },
            "mandatory_on_request": {
                "outcomes": {
                    "blank": {"status": "dormant", "follow_up": {"trigger": "t", "deadline": "d", "if_deadline_missed": "disqualified"}},
                    "filled": {"status": "pass"},
                },
                "transform": {"operation": "add_working_days", "surfaced_as": "follow_up_deadline"},
            },
        },
    }
    doc.update(overrides)
    return doc


def test_rule_with_tier_uses_tier_outcomes():
    doc = _rules_doc()
    rule = {"id": "x", "consequence_tier": "critical"}
    assert resolve_outcomes(doc, rule) == doc["consequence_tiers"]["critical"]["outcomes"]


def test_rule_level_outcomes_fully_override_tier_not_merge():
    # subcontractor_overseas_legal_opinion-shaped case: the rule's own outcomes
    # dict replaces the tier's entirely, even though it shares a tier name and
    # would otherwise inherit a different follow_up.
    doc = _rules_doc()
    rule = {
        "id": "x",
        "consequence_tier": "mandatory_on_request",
        "outcomes": {"blank": {"status": "dormant", "follow_up": {"trigger": "custom", "deadline": "custom", "if_deadline_missed": "disqualified"}}},
    }
    resolved = resolve_outcomes(doc, rule)
    assert resolved == rule["outcomes"]
    assert resolved["blank"]["follow_up"]["trigger"] == "custom"
    assert "filled" not in resolved  # confirms whole-object override, not a per-key merge


def test_rule_with_no_tier_and_no_own_outcomes_resolves_empty():
    # Informational/context/no_gate-shaped rules - not a gate, nothing to resolve.
    doc = _rules_doc()
    rule = {"id": "x"}
    assert resolve_outcomes(doc, rule) == {}


def test_rule_referencing_unknown_tier_resolves_empty_not_a_crash():
    doc = _rules_doc()
    rule = {"id": "x", "consequence_tier": "does_not_exist"}
    assert resolve_outcomes(doc, rule) == {}


def test_rule_with_own_outcomes_and_no_consequence_tier_key():
    # appendix_tenderer_address_not_postal_box-shaped case: no consequence_tier at
    # all, just a standalone outcomes dict.
    doc = _rules_doc()
    rule = {"id": "x", "outcomes": {"postal_box": {"status": "needs_review"}, "not_a_postal_box": {"status": "pass"}}}
    assert resolve_outcomes(doc, rule) == rule["outcomes"]


def test_resolve_outcome_returns_matching_entry():
    doc = _rules_doc()
    rule = {"id": "x", "consequence_tier": "critical"}
    assert resolve_outcome(doc, rule, "blank") == {"status": "disqualified", "note": "{field} is blank."}


def test_resolve_outcome_returns_none_for_unresolvable_key():
    doc = _rules_doc()
    rule = {"id": "x", "consequence_tier": "critical"}
    assert resolve_outcome(doc, rule, "sealed") is None


def test_get_tier_returns_tier_dict():
    doc = _rules_doc()
    assert get_tier(doc, "mandatory_on_request")["transform"]["operation"] == "add_working_days"


def test_get_tier_returns_none_for_missing_tier():
    doc = _rules_doc()
    assert get_tier(doc, "nonexistent") is None


def test_get_tier_returns_none_for_rule_with_no_tier():
    doc = _rules_doc()
    assert get_tier(doc, None) is None
