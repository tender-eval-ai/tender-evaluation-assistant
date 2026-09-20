"""L4 on the synthetic tender: obligations under the cited clauses that no drafted rule
quotes become gaps; a templated item contributes none; the walk stops one level below
the cited clause; a node is listed once."""
from __future__ import annotations

from app.rulesets import coverage as l4
from app.rulesets.schema import DataClass
from test.rulesets.test_novel import SIGNATURE_NODE, VALIDITY_NODE, item_of


def test_gaps_are_the_uncovered_obligations_near_the_cited_clauses(located, index):
    a = item_of(located, "a")
    gaps = l4.gaps_for([a], index, {"item_a.offer_signed": SIGNATURE_NODE})
    ids = [g.node_id for g in gaps]
    assert SIGNATURE_NODE not in ids, "quoted by a rule: covered"
    assert VALIDITY_NODE in ids and "02-Interpretation-Terms-of-Tender-and-Ge:P2:3.3" in ids
    assert "04-Terms-of-Tender-Supplement:9.4" in ids and "04-Terms-of-Tender-Supplement:9.4:(a)" not in ids, \
        "one level below the cited clause, not two"
    assert "01-Tender-Form:P4" not in ids, "the Part heading carries no obligation of its own"
    validity = next(g for g in gaps if g.node_id == VALIDITY_NODE)
    assert validity.text.startswith("Validity The Authority Representative shall comply") and validity.text.endswith(".")
    assert all(g.reason is None and g.edit is None for g in gaps)


def test_a_templated_item_contributes_no_gaps_and_nodes_are_listed_once(located, index):
    a, b = item_of(located, "a"), item_of(located, "b").model_copy(update={"template": "price_schedule"})
    assert l4.gaps_for([b], index, {}) == []
    twice = l4.gaps_for([a, a], index, {})
    assert len({g.node_id for g in twice}) == len(twice)


def test_obligation_sentences_and_depth():
    assert l4.obligation_sentence("1. Offer\nThe Contractor may reject it. The Tenderer shall sign it; then wait.") == "The Tenderer shall sign it;"
    assert l4.obligation_sentence("Notes: read carefully.") is None
    assert l4.DEPTH == 1 and DataClass.SYNTHETIC.value == "synthetic"
