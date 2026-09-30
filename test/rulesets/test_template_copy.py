"""#89 PR A: an item keeps a copy of what it took from its template (the slot specs, the tiers
its rules name after the Part re-tier, the template's content hash), and evaluation, the slot
fill and confirmation read the copy. A later change to the template never alters an item
already built; an item stored before the copy existed reads the library, as before. A rule
reading a `{slot}` the item does not declare blocks confirmation."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.checks.engine_bridge import evaluate
from app.rulesets import edit as ed
from app.rulesets.library import DEFAULT_DIR, load_templates, template_of
from app.rulesets.schema import Consequence, ItemStatus, Outcome, Part, SlotKind, SlotSpec, TemplateRule
from backend.schemas_api import ItemPatch
from test.rulesets.test_presence_tier import CERT, matched
from test.rulesets.test_production_templates import bid

PRODUCTION = load_templates(DEFAULT_DIR)
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def ruleset_of(items):
    from test.test_rulesets_edit import ruleset
    return ruleset(items=[i.model_dump(mode="json") for i in items], gaps=[])


def weakened() -> dict:
    """The library after someone edits the certificate template: a missing certificate passes,
    and a new required slot appears."""
    t = PRODUCTION[CERT]
    tiers = {tier: d.model_copy(update={"outcomes": {**d.outcomes, "blank": Outcome(status="pass")}})
             for tier, d in t.consequences.items()}
    extra = SlotSpec(name="issuing_office", kind=SlotKind.TEXT, required=True, description="the office that issues it")
    return {**PRODUCTION, CERT: t.model_copy(update={"consequences": tiers, "slots": [*t.slots, extra]})}


def test_l1_writes_the_copy_with_the_tier_the_part_gave(located, index):
    item = matched(located, index, Part.B)
    copy = item.template_copy
    assert copy.version == PRODUCTION[CERT].content_hash() and len(copy.version) == 12
    assert copy.slots == PRODUCTION[CERT].slots
    named = {r.consequence for r in item.rules if r.consequence is not None and r.outcomes is None}
    assert set(copy.consequences) == named and Consequence.MANDATORY_ON_REQUEST in named, "the re-tiered tier, not the file's"


def test_a_template_changed_later_never_alters_an_item_already_built(located, index):
    item = matched(located, index, Part.A)
    missing = bid(CERT)                                        # Tenderer C: no certificate
    before = evaluate(item, missing, template_of(item, PRODUCTION))["outcome"]
    after = evaluate(item, missing, template_of(item, weakened()))["outcome"]
    assert before == after == "disqualified"
    legacy = item.model_copy(update={"template_copy": None})   # stored before the copy existed
    assert evaluate(legacy, missing, template_of(legacy, weakened()))["outcome"] == "pass", "reads the library, as before"


def test_confirmation_reads_the_copy_too(located, index):
    item = matched(located, index, Part.A)
    ruleset_item = item.model_copy(update={"status": ItemStatus.VERIFIED})
    copied = ed.confirm_blockers(ruleset_of([ruleset_item]), weakened())
    legacy = ed.confirm_blockers(ruleset_of([ruleset_item.model_copy(update={"template_copy": None})]), weakened())
    assert not [b for b in copied if b["kind"] == "empty_required_slot"]
    assert {"kind": "empty_required_slot", "letter": "l", "slot": "issuing_office"} in legacy


def test_a_rule_reading_an_undeclared_slot_blocks_confirmation(located, index):
    item = matched(located, index, Part.A).model_copy(update={"status": ItemStatus.VERIFIED})
    stray = TemplateRule(id=f"{CERT}.valid_until", check="date", field=f"{CERT}.date", params={"before": "{closing_date}"},
                         outcomes={"match": {"status": "pass"}, "mismatch": {"status": "needs_review"}})
    blockers = ed.confirm_blockers(ruleset_of([item.model_copy(update={"rules": [*item.rules, stray]})]), PRODUCTION)
    blocker = {"kind": "undeclared_slot", "letter": "l", "rule": stray.id, "slots": ["closing_date"]}
    assert blocker in blockers
    assert ed.describe_blocker(blocker) == f"item (l): rule {stray.id} reads closing_date, which the item does not declare"


def test_a_new_template_brings_its_copy_and_an_unknown_one_none(located, index):
    item = matched(located, index, Part.A)
    other = next(t for t in PRODUCTION if t != CERT)
    patched = ed.apply_patch(item, ItemPatch(template=other, reason="wrong form"), "nasi", NOW, PRODUCTION)
    assert patched.template_copy.version == PRODUCTION[other].content_hash()
    unknown = ed.apply_patch(item, ItemPatch(template="not_a_form", reason="x"), "nasi", NOW, PRODUCTION)
    assert unknown.template == "not_a_form" and unknown.template_copy is None


def test_the_content_hash_follows_the_content_only():
    t = PRODUCTION[CERT]
    assert t.content_hash() == t.model_copy(deep=True).content_hash()
    assert t.content_hash() != weakened()[CERT].content_hash()


def test_a_novel_item_keeps_no_copy(located, index):
    item = matched(located, index, Part.A)
    with pytest.raises(ValidationError, match="keeps no copy"):
        type(item).model_validate({**item.model_dump(mode="json"), "template": None,
                                   "rules": [r.model_dump(mode="json") for r in item.rules if r.outcomes is not None]})


def test_no_template_carries_a_citation_or_a_quote():
    """Templates are in our own words (J2(c)), so no tender text reaches the bank (#89 item 3)."""
    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if v is not None:
                    yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)
    for tid, template in PRODUCTION.items():
        assert not {"citation", "quote"} & set(keys(json.loads((DEFAULT_DIR / f"{tid}.json").read_text()))), tid


def test_a_fresh_build_stores_a_copy_on_every_templated_item_and_survives_a_library_edit(located, index, monkeypatch):
    """Through the whole builder, then decided against the edited library: Tenderer C is still
    disqualified for its missing certificate, because the stored rule set carries its copy."""
    from app.checks import engine_bridge
    from app.rulesets.builder import build_items
    from app.rulesets.schema import DataClass, RuleSet
    from test.checks.conftest import read_offer
    from test.fakes import FakeLLM
    from test.rulesets.fake_factory import rules

    monkeypatch.delenv("RULESET_TEMPLATES_DIR", raising=False)
    out = build_items(located, PRODUCTION, index, FakeLLM(rules=rules()), DataClass.SYNTHETIC)
    templated = [i for i in out.items if i.template]
    assert templated and all(i.template_copy and i.template_copy.version == PRODUCTION[i.template].content_hash()
                             for i in templated)
    spec = RuleSet(project_id="SYN-2026-001", version=1, data_class=DataClass.SYNTHETIC, items=out.items, gaps=out.gaps,
                   created_by="rule_builder", created_at="2026-09-30T00:00:00Z").model_dump(mode="json")
    monkeypatch.setattr(engine_bridge, "load_templates", weakened)
    assert engine_bridge.decide(read_offer("Tenderer_C"), spec)["items"]["l"]["outcome"] == "disqualified"
