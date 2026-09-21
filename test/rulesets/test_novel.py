"""L3 on the synthetic tender: one call per item without a template; a requirement becomes a
rule only when its quote is found on a cited clause, with a reference note citing the node;
an unverified requirement is kept as a note; outcomes follow the item's Part."""
from __future__ import annotations

from app.rulesets import novel as l3
from app.rulesets.schema import CheckType, DataClass, ItemStatus, Part
from test.fakes import FakeLLM, Rule

SIGNATURE_NODE = "01-Tender-Form:P4:3"
SIGNATURE_QUOTE = "The Tenderer shall notify the other party in writing within fourteen days of the Purchase Order."
VALIDITY_NODE = "01-Tender-Form:P4:2"


def item_of(located, letter):
    return next(i for i in located if i.letter == letter)


def reply_for_a(call):
    assert "Item (a)" in call.user and "Check kinds: filled, value" in call.user
    return l3.Requirements(requirements=[
        l3.Requirement(name="offer_signed", check=CheckType.SIGNATURE, field="offer_signature", quote=SIGNATURE_QUOTE,
                       node_id=SIGNATURE_NODE, note="the offer to be bound must be signed"),
        l3.Requirement(name="validity_stated", check=CheckType.FILLED, field="validity_period",
                       quote="Validity\nThe Authority Representative shall comply with the Technical Specifications", node_id=None),
        l3.Requirement(name="blue_ink", check=CheckType.CONTAINS, field="offer_signature", params={"phrase": "blue ink"},
                       quote="The offer shall be signed in blue ink", node_id=SIGNATURE_NODE),
    ])


def test_a_drafted_rule_needs_a_verified_quote_and_carries_a_reference_note(located, index):
    llm = FakeLLM(rules=[Rule(reply=reply_for_a, out_model=l3.Requirements)])
    drafted, sources = l3.draft_item(item_of(located, "a"), index, llm, DataClass.SYNTHETIC)

    assert llm.count(out_model=l3.Requirements) == 1
    assert [r.id for r in drafted.rules] == ["item_a.offer_signed", "item_a.validity_stated"]
    signed = drafted.rules[0]
    assert signed.check == CheckType.SIGNATURE and signed.field == "item_a.offer_signature" and signed.stage == "I"
    assert signed.outcomes["blank"].status == "disqualified" and signed.outcomes["filled"].status == "pass"
    assert sources == {"item_a.offer_signed": SIGNATURE_NODE, "item_a.validity_stated": VALIDITY_NODE}, \
        "a wrong or missing node id is repaired from the quote"
    assert drafted.status == ItemStatus.NOVEL
    notes = {n.text.split(":")[0]: n for n in drafted.notes}
    assert notes["item_a.offer_signed"].citation.node_id == SIGNATURE_NODE and notes["item_a.offer_signed"].citation.page == 3
    assert notes["item_a.offer_signed"].citation.file == "tender/01 Tender Form.pdf"
    unverified = next(n for n in drafted.notes if n.text.startswith("unverified draft blue_ink"))
    assert unverified.citation is None and "blue ink" in unverified.text


def test_outcomes_follow_the_part(located, index):
    def one_rule(call):
        return l3.Requirements(requirements=[l3.Requirement(name="r", check=CheckType.FILLED, field="f", quote=QUOTE[call.user[6]])])
    QUOTE = {"e": "The Tenderer shall", "m": "The Tenderer shall"}
    llm = FakeLLM(rules=[Rule(reply=one_rule, out_model=l3.Requirements)])
    e, _ = l3.draft_item(item_of(located, "e"), index, llm, DataClass.SYNTHETIC)      # Part B
    m, _ = l3.draft_item(item_of(located, "m"), index, llm, DataClass.SYNTHETIC)      # Part C
    assert e.part == Part.B and e.rules[0].outcomes["blank"].status == "dormant"
    assert e.rules[0].outcomes["blank"].follow_up.if_deadline_missed == "disqualified"
    assert m.part == Part.C and m.rules[0].outcomes["blank"].status == "pass"
    assert l3.outcomes_for(Part.A)["redacted"].status == "needs_review"


def test_no_verified_requirement_makes_the_item_a_gap_and_no_clauses_means_no_call(located, index):
    llm = FakeLLM(rules=[Rule(reply=l3.Requirements(), out_model=l3.Requirements)])
    drafted, sources = l3.draft_item(item_of(located, "a"), index, llm, DataClass.SYNTHETIC)
    assert drafted.status == ItemStatus.GAP and drafted.rules == [] and sources == {}

    bare = item_of(located, "a").model_copy(update={"clauses": []})
    quiet = FakeLLM()
    drafted, _ = l3.draft_item(bare, index, quiet, DataClass.SYNTHETIC)
    assert drafted.status == ItemStatus.GAP and quiet.count() == 0


def test_duplicate_names_get_distinct_ids(located, index):
    twice = l3.Requirements(requirements=[
        l3.Requirement(name="signed", check=CheckType.SIGNATURE, field="s", quote=SIGNATURE_QUOTE),
        l3.Requirement(name="signed", check=CheckType.FILLED, field="s", quote=SIGNATURE_QUOTE)])
    llm = FakeLLM(rules=[Rule(reply=twice, out_model=l3.Requirements)])
    drafted, _ = l3.draft_item(item_of(located, "a"), index, llm, DataClass.SYNTHETIC)
    assert [r.id for r in drafted.rules] == ["item_a.signed", "item_a.signed_2"]


def test_matched_items_pass_through_l3_untouched(located, templates, index):
    from app.rulesets import match as l1
    from test.rulesets.test_match import by_item
    matched = l1.match_items(located, templates, index, FakeLLM(rules=[Rule(reply=by_item, out_model=l1.Match)]))
    llm = FakeLLM(rules=[Rule(reply=l3.Requirements(), out_model=l3.Requirements)])
    out, _ = l3.draft_items(matched, index, llm, DataClass.SYNTHETIC)
    assert llm.count() == 13 and next(i for i in out if i.letter == "l").template == "noncollusive_certificate"
