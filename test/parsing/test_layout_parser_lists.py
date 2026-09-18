"""Sub-item list nesting in the layout parser, driven by stub layout blocks so the
block geometry (marker column, text column) is exact: indentation is the only
signal that tells a paragraph closing a list from the list's own continuation.
"""
import pytest

from test.parsing.stub_layout import parse_blocks as _parse


def test_a_paragraph_in_a_nested_lists_marker_column_closes_only_that_list(monkeypatch):
    nodes = _parse(monkeypatch, {1: [
        (72, "text", "5. The Tenderer shall submit the following:"),
        (100, "list-item", "(a) Sample documents"),
        (130, "list-item", "(1) A first requirement with two conditions:"),
        (160, "list-item", "(a) the first condition;"),
        (160, "list-item", "(b) the second condition."),
        (160, "text", "A closing paragraph written at the nested list's own marker column."),
        (130, "list-item", "(2) A second requirement of the same list."),
        (100, "list-item", "(b) Further sample documents"),
    ]})

    tail = next(n for n in nodes.values() if n["node_id"].endswith(":tail"))
    assert tail["parent_id"] == "doc:5:(a):(1)", "the paragraph resumes (1), which holds the closed list"
    assert "doc:5:(a):(2)" in nodes, "the outer (1)/(2) list stays open"
    assert nodes["doc:5:(a):(2)"]["parent_id"] == "doc:5:(a)"
    assert nodes["doc:5:(b)"]["parent_id"] == "doc:5"


def test_a_paragraph_in_the_outermost_marker_column_closes_the_whole_list(monkeypatch):
    nodes = _parse(monkeypatch, {1: [
        (72, "text", "7. A Tender will not be considered further if:"),
        (100, "list-item", "(a) the first ground applies;"),
        (130, "list-item", "(i) in one way; or"),
        (130, "list-item", "(ii) in another way;"),
        (100, "list-item", "(b) the second ground applies."),
        (100, "text", "The grounds above are separate and independent from each other."),
    ]})

    assert nodes["doc:7:tail"]["parent_id"] == "doc:7"


@pytest.mark.parametrize("x0", [115, 130])
def test_a_paragraph_indented_past_the_marker_column_continues_the_last_item(monkeypatch, x0):
    nodes = _parse(monkeypatch, {1: [
        (72, "text", "7. A Tender will not be considered further if:"),
        (100, "list-item", "(a) the first ground applies;"),
        (100, "list-item", "(b) the second ground applies,"),
        (x0, "text", "continued on a further line of the same item."),
    ]})

    assert not any(n.endswith(":tail") for n in nodes)
    assert nodes["doc:7:(b)"]["text"].endswith("same item.")

