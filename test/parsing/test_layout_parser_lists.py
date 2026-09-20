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


def test_a_run_in_list_inside_one_sentence_is_split_at_each_item():
    from app.parsing.layout_document_index import _split_run_in_items

    pieces = _split_run_in_items(
        "(c) in the event of (i) a first event occurs; (ii) a second event occurs; or (iii) a third one, "
        "the offer lapses."
    )

    assert [text.split()[0] for text, _ in pieces] == ["(c)", "(i)", "(ii)", "(iii)"]
    assert [opens for _, opens in pieces] == [False, True, False, False]


def test_a_nested_run_in_list_is_split_at_both_levels():
    from app.parsing.layout_document_index import _split_run_in_items

    pieces = _split_run_in_items(
        "4.1 A sample clause covering (a) a first class of item; (b) every item of the kind listed, being "
        "(i) the first kind; (ii) the second kind; (c) any further item."
    )

    assert [text.split()[0] for text, _ in pieces] == ["4.1", "(a)", "(b)", "(i)", "(ii)", "(c)"]
    assert [opens for _, opens in pieces] == [False, True, False, True, False, False]


@pytest.mark.parametrize("text", [
    "(d) as required by Paragraphs (a) and (b) above and the items (a) to (c) below.",
    "(d) within two (2) weeks and three (3) days of the date of notice.",
    "(d) as set out in sub-paragraph 7(a)(i) and 7(a)(ii) of the sample terms.",
    "(d) a list with a single (a) member only.",
])
def test_citations_quantities_and_lone_markers_are_not_run_in_lists(text):
    from app.parsing.layout_document_index import _split_run_in_items

    assert _split_run_in_items(text) == [(text, False)]


def test_run_in_items_are_added_under_their_item_without_changing_what_follows(monkeypatch):
    """"(i)" continues "(h)" alphabetically; split out of "(h)", it opens (h)'s own
    list. (h) keeps its whole text, and the next block still continues (h)'s list."""
    nodes = _parse(monkeypatch, {1: [
        (72, "text", "3. The Tenderer shall provide:"),
        (100, "list-item", "(g) a first document;"),
        (100, "list-item", "(h) contact details (i) telephone number; (ii) email address;"),
        (100, "list-item", "(i) a further document."),
    ]})

    assert nodes["doc:3:(h):(i)"]["parent_id"] == "doc:3:(h)"
    assert nodes["doc:3:(h):(ii)"]["parent_id"] == "doc:3:(h)"
    assert nodes["doc:3:(h)"]["text"] == "(h) contact details (i) telephone number; (ii) email address;"
    assert nodes["doc:3:(h):(ii)"]["text"] == "(ii) email address;"
    assert nodes["doc:3:(i)"]["parent_id"] == "doc:3"


def test_nested_run_in_items_nest_and_the_following_text_still_joins_the_host(monkeypatch):
    nodes = _parse(monkeypatch, {1: [
        (72, "text", "4.1 A sample clause covering (a) a first class of item; (b) every item of the kind "
                     "listed, being (i) the first kind; (ii) the second kind; (c) any further item."),
        (72, "text", "A closing sentence of the same clause."),
    ]})

    assert nodes["doc:4.1:(a)"]["parent_id"] == "doc:4.1"
    assert nodes["doc:4.1:(b):(ii)"]["parent_id"] == "doc:4.1:(b)"
    assert nodes["doc:4.1:(c)"]["parent_id"] == "doc:4.1"
    assert nodes["doc:4.1"]["text"].endswith("A closing sentence of the same clause.")


def test_the_sentence_resuming_after_a_run_in_list_is_a_tail_node(monkeypatch):
    """After a list of alternatives inside one sentence, the sentence carries on
    ("..., shall comply"): that text is a tail node of the host. The last item
    keeps it too, as run-in items keep the text they were cut from."""
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (36, "list-item", "9.1 The sample terms may specify that (a) the sample goods; and/or (b) the "
                          "sample maker, shall comply with the sample requirements."),
        (36, "list-item", "9.2 A sample may be (a) blue; or (b) red. Its size is set out below."),
        (36, "list-item", "9.3 A sample is (a) blue; or (b) red, as the buyer prefers."),
    ]})

    assert nodes["doc:9.1:tail"]["text"] == "shall comply with the sample requirements."
    assert nodes["doc:9.1:tail"]["parent_id"] == "doc:9.1"
    assert nodes["doc:9.1:(b)"]["text"].endswith("shall comply with the sample requirements.")
    assert nodes["doc:9.2:tail"]["text"] == "Its size is set out below."
    assert not any(n["node_id"].startswith("doc:9.3:tail") for n in nodes.values())


def test_a_list_lettered_or_numbered_in_capitals_is_a_list(monkeypatch):
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (84, "section-header", "WHEREAS"),
        (84, "list-item", "(A) The first sample recital."),
        (84, "list-item", "(B) The second sample recital."),
        (84, "list-item", "(2) Sample maintenance"),
        (120, "list-item", "(I) Regular sample maintenance:"),
        (150, "list-item", "(a) a first sample task;"),
        (120, "list-item", "(II) Further sample maintenance."),
    ]})

    labels = {n["label"]: n["parent_id"] for n in nodes.values() if n.get("label")}
    assert nodes["doc:(A)"]["text"] == "(A) The first sample recital."
    assert labels["(B)"] == labels["(A)"], "(B) continues (A)"
    assert labels["(II)"] == labels["(I)"], "(II) continues (I)"
    assert labels["(a)"].endswith(":(I)")
