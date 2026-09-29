"""L3 for templated items on the synthetic tender: the model is shown the template's rules
as they will check this tender, and what it says the tender adds becomes a rule only when
its quote is found; what it says the template covers counts only when the rule exists and
the quote is found; an item without a template or clauses costs no call."""
from __future__ import annotations

from app.rulesets import additions as l3b, novel as l3, slots as l2
from app.rulesets.evaluate import UNVERIFIED
from app.rulesets.schema import CheckType, DataClass, ItemStatus
from test.fakes import FakeLLM, Rule
from test.rulesets.fake_factory import ANALYSIS_NODE, ANALYSIS_QUOTE, QUOTE_ITEM_1_NODE, additions_reply
from test.rulesets.test_novel import item_of
from test.rulesets.test_slots import answer, matched_price_item


def filled_price_item(located, templates, index):
    item = matched_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=answer(), out_model=l2.SlotFill)])
    return l2.fill_item(item, templates["price_schedule"], index, llm, DataClass.SYNTHETIC)


def test_an_addition_the_template_lacks_becomes_a_marked_rule_beside_the_templates(located, templates, index):
    item = filled_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=additions_reply, out_model=l3b.Additions)])
    added, sources, covered = l3b.add_to_item(item, index, llm, DataClass.SYNTHETIC)

    prompt = llm.prompts[0]
    assert "- price_schedule.quantity_matches: value on price_schedule.quantity expected=875000" in prompt, \
        "the template's rules with this tender's slot values"
    assert "Fields of this form (Price Schedule, Part A)" in prompt and f"[{ANALYSIS_NODE}]" in prompt

    ids = [r.id for r in added.rules]
    assert ids == ["price_schedule.unit_price_present", "price_schedule.quantity_matches", "price_schedule.certificate_of_analysis"]
    rule = added.rules[-1]
    assert rule.check == CheckType.DOCUMENT_PRESENT and rule.field == "price_schedule.certificate_of_analysis"
    assert rule.note == "added for this tender: not in the template"
    assert rule.outcomes["blank"].status == "disqualified", "the outcomes follow the item's Part, as for a novel rule"
    note = added.notes[-1]
    assert note.text == f"price_schedule.certificate_of_analysis{l3.ADDITION}: \"{ANALYSIS_QUOTE}\""
    assert note.citation.node_id == ANALYSIS_NODE
    assert sources == {"price_schedule.certificate_of_analysis": ANALYSIS_NODE} and covered == [QUOTE_ITEM_1_NODE]
    assert added.status == ItemStatus.VERIFIED and added.template == "price_schedule", "the item stays what L2 made it"


def test_an_addition_never_takes_a_template_rules_id_and_an_unverified_one_stays_a_note(located, templates, index):
    item = filled_price_item(located, templates, index)
    reply = l3b.Additions(additions=[
        l3.Requirement(name="unit_price_present", check=CheckType.FILLED, field="unit_price", quote=ANALYSIS_QUOTE),
        l3.Requirement(name="blue_ink", check=CheckType.CONTAINS, field="unit_price", quote="The price shall be in blue ink")])
    added, sources, _ = l3b.add_to_item(item, index, FakeLLM(rules=[Rule(reply=reply, out_model=l3b.Additions)]), DataClass.SYNTHETIC)
    assert [r.id for r in added.rules][-1] == "price_schedule.unit_price_present_2"
    assert list(sources) == ["price_schedule.unit_price_present_2"]
    unverified = [n.text for n in added.notes if n.text.startswith(UNVERIFIED)]
    assert unverified == [f"unverified draft blue_ink (contains){l3.ADDITION}: \"The price shall be in blue ink\""], \
        "counted by the S3 eval like any unverified draft"


def test_covered_counts_only_for_the_items_own_rules_and_a_quote_found(located, templates, index):
    item = filled_price_item(located, templates, index)
    reply = l3b.Additions(covered=[
        l3b.Covered(rule_id="price_schedule.unit_price_present", quote="The Tenderer shall quote for Item 1 only."),
        l3b.Covered(rule_id="price_schedule.invented", quote="The Supplier shall provide a certificate of analysis"),
        l3b.Covered(rule_id="price_schedule.quantity_matches", quote="The quantity shall be doubled")])
    _, _, covered = l3b.add_to_item(item, index, FakeLLM(rules=[Rule(reply=reply, out_model=l3b.Additions)]), DataClass.SYNTHETIC)
    assert covered == [QUOTE_ITEM_1_NODE]


def test_no_template_or_no_clauses_no_call(located, templates, index):
    silent = FakeLLM(rules=[])                     # any call would raise UnexpectedCall
    novel = item_of(located, "a")
    assert l3b.add_to_item(novel, index, silent, DataClass.SYNTHETIC) == (novel, {}, [])
    bare = filled_price_item(located, templates, index).model_copy(update={"clauses": []})
    assert l3b.add_to_item(bare, index, silent, DataClass.SYNTHETIC) == (bare, {}, [])
    assert silent.count() == 0
