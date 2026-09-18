def get_tier(rules_doc: dict, tier_name: str | None) -> dict | None:
    if tier_name is None:
        return None
    return rules_doc.get("consequence_tiers", {}).get(tier_name)


def resolve_outcomes(rules_doc: dict, rule: dict) -> dict:
    # Whole-object override, not a per-key merge: a rule that declares its own
    # `outcomes` (subcontractor_overseas_legal_opinion's different follow_up,
    # tender_sample_pack_size's non-standard within_range/outside_range vocabulary)
    # replaces its tier's outcomes entirely, even if it names a tier at all -
    # confirmed against every such rule found auditing the 13 rules files, none of
    # them expect the tier's other keys to still apply alongside their override.
    own_outcomes = rule.get("outcomes")
    if own_outcomes is not None:
        return own_outcomes
    tier = get_tier(rules_doc, rule.get("consequence_tier"))
    if tier is None:
        return {}
    return tier.get("outcomes", {})


def resolve_outcome(rules_doc: dict, rule: dict, outcome_key: str) -> dict | None:
    return resolve_outcomes(rules_doc, rule).get(outcome_key)
