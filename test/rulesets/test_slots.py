"""L2 on the synthetic tender: one call per item with slots, the quote verified in code
against the cited clauses' subtrees, values coerced by kind, unverified answers kept for a
person, and the item verified only when every required slot is."""
from __future__ import annotations

from app.rulesets import match as l1, slots as l2
from app.rulesets.builder import build_items
from app.rulesets.schema import DataClass, ItemStatus, SlotKind
from test.fakes import FakeLLM, Rule
from test.rulesets.test_match import by_item

QUANTITY_NODE = "09-Schedules:00-Price-Schedule:PA:(2)"


def matched_price_item(located, templates, index):
    llm = FakeLLM(rules=[Rule(reply=by_item, out_model=l1.Match)])
    return next(i for i in l1.match_items(located, templates, index, llm) if i.letter == "b")


def answer(value="875,000 kg", quote="The Estimated Quantity (Kilograms) (\"kg\") (A) of Item 1 for the Contract Period is 875,000 kg.",
           node_id=QUANTITY_NODE, extra=()):
    return l2.SlotFill(slots=[l2.SlotAnswer(name="estimated_quantity", value=value, quote=quote, node_id=node_id), *extra])


def test_a_quoted_value_is_verified_on_its_node_and_coerced_by_kind(located, templates, index):
    item = matched_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=answer(), out_model=l2.SlotFill)])
    filled = l2.fill_item(item, templates["price_schedule"], index, llm, DataClass.SYNTHETIC)

    assert llm.count(out_model=l2.SlotFill) == 1
    slot = filled.slots["estimated_quantity"]
    assert slot.value == 875000 and slot.verified and slot.origin == "extracted"
    assert slot.citation.node_id == QUANTITY_NODE and slot.citation.file == "tender/09 Schedules.pdf" and slot.citation.page == 1
    assert filled.slots["currency"].value is None, "optional and unstated: empty"
    assert filled.status == ItemStatus.VERIFIED, "every required slot verified"
    prompt = llm.prompts[0]
    assert "- estimated_quantity (number, kg)" in prompt and "currency (text, optional)" in prompt
    assert f"[{QUANTITY_NODE}]" in prompt, "the cited clause's descendants are in the context"


def test_a_quote_not_on_any_cited_clause_stays_unverified_and_the_item_needs_input(located, templates, index):
    item = matched_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=answer(quote="the quantity is about 900,000 kg", node_id=None), out_model=l2.SlotFill)])
    filled = l2.fill_item(item, templates["price_schedule"], index, llm, DataClass.SYNTHETIC)
    slot = filled.slots["estimated_quantity"]
    assert slot.value == 875000 and not slot.verified and slot.citation.node_id is None
    assert slot.citation.quote == "the quantity is about 900,000 kg" and slot.citation.page == 1
    assert filled.status == ItemStatus.NEEDS_INPUT


def test_a_wrong_node_id_is_repaired_when_the_quote_is_found_elsewhere_under_the_clauses(located, templates, index):
    item = matched_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=answer(node_id="09-Schedules:00-Price-Schedule:PA:(1)"), out_model=l2.SlotFill)])
    slot = l2.fill_item(item, templates["price_schedule"], index, llm, DataClass.SYNTHETIC).slots["estimated_quantity"]
    assert slot.verified and slot.citation.node_id == QUANTITY_NODE


def test_a_missing_or_unreadable_answer_leaves_the_slot_empty(located, templates, index):
    item = matched_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=l2.SlotFill(slots=[l2.SlotAnswer(name="estimated_quantity", value="as stated", quote="x")]),
                              out_model=l2.SlotFill)])
    filled = l2.fill_item(item, templates["price_schedule"], index, llm, DataClass.SYNTHETIC)
    assert filled.slots["estimated_quantity"].value is None and filled.status == ItemStatus.NEEDS_INPUT
    empty = l2.fill_item(item, templates["price_schedule"], index, FakeLLM(rules=[Rule(reply=l2.SlotFill(), out_model=l2.SlotFill)]),
                         DataClass.SYNTHETIC)
    assert all(s.value is None for s in empty.slots.values())


def test_values_are_coerced_by_slot_kind():
    assert l2.coerce("875,000 kg", SlotKind.NUMBER) == 875000 and l2.coerce("HK$ 12.50", SlotKind.MONEY) == 12.5
    # Thousands printed with a space (or a no-break space) read as one number, not the first group.
    assert l2.coerce("875 000 kg", SlotKind.NUMBER) == 875000 and l2.coerce("1 000 000.50", SlotKind.NUMBER) == 1000000.5
    assert l2.coerce("1\u00a0250", SlotKind.NUMBER) == 1250 and l2.coerce("HK$ 4 252 500", SlotKind.MONEY) == 4252500
    assert l2.coerce("4.3 mg/L", SlotKind.NUMBER) == 4.3 and l2.coerce("12 24", SlotKind.NUMBER) == 12
    assert l2.coerce(42, SlotKind.NUMBER) == 42 and l2.coerce("none stated", SlotKind.NUMBER) is None
    assert l2.coerce(True, SlotKind.NUMBER) is None
    assert l2.coerce("HK$; US$", SlotKind.LIST) == ["HK$", "US$"] and l2.coerce(["a", 1], SlotKind.LIST) == ["a", "1"]
    assert l2.coerce("  HK$ ", SlotKind.TEXT) == "HK$" and l2.coerce("", SlotKind.TEXT) is None and l2.coerce(None, SlotKind.DATE) is None


def test_the_builder_runs_every_layer_with_one_call_per_item_one_per_item_with_slots_or_a_template_one_per_novel_item(located, templates, index):
    from app.rulesets import additions as l3b, novel as l3
    llm = FakeLLM(rules=[Rule(reply=by_item, out_model=l1.Match), Rule(reply=answer(), out_model=l2.SlotFill),
                         Rule(reply=l3.Requirements(), out_model=l3.Requirements), Rule(reply=l3b.Additions(), out_model=l3b.Additions)])
    out = build_items(located, templates, index, llm, DataClass.SYNTHETIC)
    assert llm.count(out_model=l1.Match) == 15 and llm.count(out_model=l2.SlotFill) == 1
    assert llm.count(out_model=l3.Requirements) == 13 and llm.count(out_model=l3b.Additions) == 2, "one per templated item"
    assert llm.count() == 31
    by_letter = {i.letter: i for i in out.items}
    assert by_letter["b"].status == ItemStatus.VERIFIED and by_letter["b"].slots["estimated_quantity"].value == 875000
    assert by_letter["l"].status == ItemStatus.VERIFIED and by_letter["l"].template == "noncollusive_certificate"
    assert sum(i.status == ItemStatus.GAP for i in out.items) == 13, "nothing drafted: the thirteen items are gaps"
    assert out.gaps and all(g.reason is None for g in out.gaps) and out.sources == {}
