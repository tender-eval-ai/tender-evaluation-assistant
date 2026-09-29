"""What L2 and L3 show the model of an item's clauses: every cited clause gets a fair share
of the budget, so a long one no longer crowds out the ones after it; a clause cut at its
share is marked in the prompt and noted on the item for the person who confirms it; and a
quote from the schedule row itself verifies, since the model is shown the row too."""
from __future__ import annotations

from app.rulesets import novel as l3, slots as l2
from app.rulesets.schema import CheckType, DataClass
from test.fakes import FakeLLM, Rule
from test.rulesets.test_slots import answer, matched_price_item

ROW_A = "09-Schedules:03-Completeness-Check-Schedule:PA:(a)"


def item_of(located, letter):
    return next(i for i in located if i.letter == letter)


def test_shares_are_equal_and_a_short_clause_gives_what_it_does_not_need_to_the_others():
    assert l2.shares([100, 5000, 20000], 9000) == [100, 4450, 4450]
    assert l2.shares([300, 400], 9000) == [300, 400], "clauses that fit are shown whole"
    assert l2.shares([], 9000) == []


def test_every_clause_is_shown_and_one_cut_at_its_share_is_marked(located, index):
    item = item_of(located, "l")    # six clauses; the certificate itself, the longest, comes last
    whole = l2.clause_context(item, index)
    assert whole.cut == [], "about 6,700 characters: the whole of every clause fits the budget"
    assert "[10-Non-collusive-Tendering-Certificate" in whole.text, "under the old 6,000 cap the last clause was cut"

    small = l2.clause_context(item, index, budget=3000)
    for clause in item.clauses:
        assert f"[{clause.node_id}" in small.text, f"{clause.node_id} crowded out"
    assert small.cut and all(shown < total for _, shown, total in small.cut)
    for label, shown, total in small.cut:
        assert f"[... {label}: {total - shown} more lines not shown in full]" in small.text
    assert len(small.text) < 3000 + 100 * len(small.cut), "the budget, plus one marker line per cut clause"


def test_a_clause_the_model_saw_only_in_part_is_noted_on_the_item_once(located, templates, index, monkeypatch):
    monkeypatch.setattr(l2, "CONTEXT_CHARS", 700)
    item = matched_price_item(located, templates, index)
    llm = FakeLLM(rules=[Rule(reply=answer(), out_model=l2.SlotFill)])
    filled = l2.fill_item(item, templates["price_schedule"], index, llm, DataClass.SYNTHETIC)
    assert filled.slots["estimated_quantity"].verified, "verification reads the node table, not the prompt"
    notes = [n.text for n in filled.notes if n.text.startswith("the model was shown")]
    assert notes == ["the model was shown 4 of the 6 lines of 09-Schedules:00-Price-Schedule:PA; "
                     "check the rest for requirements it could not see",
                     "the model was shown 0 of the 6 lines of 04-Terms-of-Tender-Supplement:5; "
                     "check the rest for requirements it could not see"]
    again = l2.fill_item(filled, templates["price_schedule"], index, llm, DataClass.SYNTHETIC)
    assert again.notes == filled.notes, "a rebuild does not add the same note twice"


def test_a_quote_from_the_schedule_row_itself_verifies(located, index):
    item = item_of(located, "a")
    assert l2.roots_of(item) == [*(c.node_id for c in item.clauses), ROW_A], "the row last: the clauses are looked at first"
    reply = l3.Requirements(requirements=[l3.Requirement(name="offer_signed", check=CheckType.SIGNATURE, field="offer_signature",
                                                         quote="duly signed by the Tenderer", node_id=None)])
    drafted, sources = l3.draft_item(item, index, FakeLLM(rules=[Rule(reply=reply, out_model=l3.Requirements)]),
                                     DataClass.SYNTHETIC)
    assert [r.id for r in drafted.rules] == ["offer_to_be_bound.offer_signed"]
    assert sources == {"offer_to_be_bound.offer_signed": ROW_A}, "the words are in the row, not in a cited clause"
