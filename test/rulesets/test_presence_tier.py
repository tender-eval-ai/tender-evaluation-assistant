"""J12 question 1 (#114): when L1 copies a template, the form's presence rule takes its tier
from the item's Part; every other rule keeps the template's; a tier the template lacks is
never named. With the production library, a fresh build of the synthetic tender disqualifies
Tenderer C for its missing Part A certificate again."""
from __future__ import annotations

import pytest

from app.rulesets import match as l1
from app.rulesets.library import DEFAULT_DIR, load_templates
from app.rulesets.novel import outcomes_for
from app.rulesets.schema import Consequence, Part
from test.fakes import FakeLLM, Rule
from test.rulesets.test_novel import item_of

PRODUCTION = load_templates(DEFAULT_DIR)
CERT = "noncollusive_certificate"


def matched(located, index, part: Part, templates=PRODUCTION):
    item = item_of(located, "l").model_copy(update={"part": part})
    llm = FakeLLM(rules=[Rule(reply=l1.Match(template=CERT, confidence=0.9), out_model=l1.Match)])
    return l1.match_item(item, templates, index, llm)


@pytest.mark.parametrize("part, tier", [(Part.A, Consequence.CRITICAL), (Part.B, Consequence.MANDATORY_ON_REQUEST),
                                        (Part.C, Consequence.DISCRETIONARY)])
def test_the_presence_rule_takes_its_tier_from_the_items_part(located, index, part, tier):
    item = matched(located, index, part)
    rules = {r.id: r for r in item.rules}
    assert rules[f"{CERT}.submitted"].consequence == tier and rules[f"{CERT}.submitted"].outcomes is None
    template = {r.id: r for r in PRODUCTION[CERT].rules}
    for rule_id, rule in rules.items():
        if rule_id != f"{CERT}.submitted":
            assert rule == template[rule_id], f"{rule_id} keeps the template's tier"
    notes = [n.text for n in item.notes if n.kind == "consequence" and n.text.startswith(f"{CERT}.submitted")]
    assert notes == [f"{CERT}.submitted: a missing form is judged as Part {part.value} says ({tier.value.replace('_', ' ')})"]


def test_matching_again_adds_the_note_once(located, index):
    item = matched(located, index, Part.A)
    llm = FakeLLM(rules=[Rule(reply=l1.Match(template=CERT, confidence=0.9), out_model=l1.Match)])
    again = l1.match_item(item, PRODUCTION, index, llm)
    assert again.notes == item.notes


def test_a_tier_the_template_lacks_is_never_named(located, index):
    """Naming it would drop the rule (no outcomes); the Part's own outcomes stand in."""
    lacking = PRODUCTION[CERT].model_copy(update={"consequences": {
        k: v for k, v in PRODUCTION[CERT].consequences.items() if k != Consequence.CRITICAL}})
    item = matched(located, index, Part.A, {CERT: lacking})
    rule = next(r for r in item.rules if r.id == f"{CERT}.submitted")
    assert rule.consequence is None and rule.outcomes == outcomes_for(Part.A)
    assert rule.outcomes["blank"].status == "disqualified"


def test_a_conditional_or_self_decided_presence_rule_is_left_alone(located, index):
    template = PRODUCTION[CERT]
    rules = [r.model_copy(update={"condition": "the tenderer is not the manufacturer"}) if r.id == f"{CERT}.submitted" else r
             for r in template.rules]
    conditional = template.model_copy(update={"rules": rules})
    item = matched(located, index, Part.A, {CERT: conditional})
    rule = next(r for r in item.rules if r.id == f"{CERT}.submitted")
    assert rule.consequence == next(r for r in template.rules if r.id == f"{CERT}.submitted").consequence
    assert not [n for n in item.notes if n.kind == "consequence" and n.text.startswith(f"{CERT}.submitted")]


def test_a_fresh_build_with_the_production_library_disqualifies_tenderer_c(located, index, monkeypatch):
    """The synthetic tender puts the certificate in Part A; before #114 a fresh build left a
    missing one dormant (the template's mandatory_on_request)."""
    from app.checks.engine_bridge import decide
    from app.rulesets.builder import build_items
    from app.rulesets.schema import DataClass, RuleSet
    from test.checks.conftest import read_offer
    from test.rulesets.fake_factory import rules

    monkeypatch.delenv("RULESET_TEMPLATES_DIR", raising=False)
    out = build_items(located, PRODUCTION, index, FakeLLM(rules=rules()), DataClass.SYNTHETIC)
    cert = next(i for i in out.items if i.letter == "l")
    assert cert.part == Part.A and cert.template == CERT
    spec = RuleSet(project_id="SYN-2026-001", version=1, data_class=DataClass.SYNTHETIC, items=out.items, gaps=out.gaps,
                   created_by="rule_builder", created_at="2026-09-30T00:00:00Z").model_dump(mode="json")
    c = decide(read_offer("Tenderer_C"), spec)
    assert c["items"]["l"]["outcome"] == "disqualified" and c["stage1"]["outcome"] == "disqualified"
    d = decide(read_offer("Tenderer_D", verify=True), spec)
    assert d["items"]["l"]["outcome"] != "disqualified", "a tenderer with the certificate is not"
