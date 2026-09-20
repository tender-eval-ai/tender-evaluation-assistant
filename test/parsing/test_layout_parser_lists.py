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

    assert nodes["doc:9.1:run-in-tail"]["text"] == "shall comply with the sample requirements."
    assert nodes["doc:9.1:run-in-tail"]["parent_id"] == "doc:9.1"
    assert nodes["doc:9.1:(b)"]["text"].endswith("shall comply with the sample requirements.")
    assert nodes["doc:9.2:run-in-tail"]["text"] == "Its size is set out below."
    assert not any(n["node_id"].startswith("doc:9.3:run-in-tail") for n in nodes.values())


def test_a_clause_with_both_tails_keeps_both_ids_distinct(monkeypatch):
    """The sentence resuming inside a run-in list and the paragraph closing a list on
    its own block are different nodes of the same clause. Sharing one ":tail" suffix
    gave the second of them ":tail#2", so which clause carried the "#2" - and the id
    anything citing it has to use - moved with any change to either."""
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (72, "list-item", "7. A Tender will not be considered further if (a) a first ground applies; "
                          "or (b) the Tenderer, has been convicted of an offence."),
        (100, "list-item", "(c) a third ground applies."),
        (100, "text", "The grounds above are separate and independent of each other."),
    ]})

    assert nodes["doc:7:run-in-tail"]["text"] == "has been convicted of an offence."
    assert nodes["doc:7:tail"]["text"] == "The grounds above are separate and independent of each other."
    assert not any("#" in node_id for node_id in nodes)


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


def test_a_full_stop_before_a_capital_is_a_tail_only_inside_a_run_in_list(monkeypatch):
    """`_RUN_IN_TAIL` on its own splits at any "." or ";" before a capital, which a
    company name or an abbreviation gives it ("Sample Co. Ltd. The Tenderer", "No.
    Five"). It is safe because it is only ever applied to the last item of a run-in
    list the parser has already found in that block: a block with no such list never
    reaches it and keeps its sentence whole.
    """
    from app.parsing.layout_document_index import _RUN_IN_TAIL
    from test.parsing.stub_layout import parse_blocks

    assert _RUN_IN_TAIL.search("The tender is submitted by Sample Co. Ltd. The Tenderer shall sign it.")

    nodes = parse_blocks(monkeypatch, {1: [
        (72, "list-item", "3.1 The tender is submitted by Sample Co. Ltd. The Tenderer shall sign it "
                          "as No. Five requires."),
    ]})

    assert sorted(nodes) == ["doc", "doc:3.1"]
    assert nodes["doc:3.1"]["text"].endswith("as No. Five requires.")


def test_an_uppercase_marker_opens_an_item_only_at_the_start_of_a_block(monkeypatch):
    """`_UPPERCASE_SUBITEM` on its own accepts "(I) " or "(A) " in front of any text,
    and a tender writes both mid-sentence. It is safe because it is only ever asked
    about a block's own first characters (`_classify_marker`), and the layout model
    has already decided where a block begins: a marker inside a sentence is not one.
    """
    from app.parsing.layout_document_index import _UPPERCASE_SUBITEM
    from test.parsing.stub_layout import parse_blocks

    assert _UPPERCASE_SUBITEM.match("(I) the undersigned, confirm the above.")

    nodes = parse_blocks(monkeypatch, {1: [
        (72, "list-item", "4. The Tenderer confirms that the offer (I) remains open and (A) is signed."),
        (72, "text", "A note about paragraph (B) of the deed."),
    ]})

    assert sorted(nodes) == ["doc", "doc:4"]
