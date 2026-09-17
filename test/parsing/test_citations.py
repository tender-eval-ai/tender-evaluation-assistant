"""CitationIndex on a hand-built, synthetic node table (no tender data)."""
from app.parsing.citations import CitationIndex, parse_citations


def _node(node_id, kind, page, number=None, label=None, title=None, doc_name=None, text="", aliases=None):
    return {"node_id": node_id, "parent_id": node_id.rpartition(":")[0] or None, "kind": kind, "page": page,
            "number": number, "label": label, "title": title, "doc_name": doc_name, "part": None,
            "text": text, "aliases": aliases}


NODES = [
    # A combined schedules file with two footer-named sub-documents.
    _node("S", "document", 1),
    _node("S:00-Price", "subdocument", 1, doc_name="Sample Price Schedule"),
    _node("S:00-Price:PA", "part", 1, number="A", title="Estimated Price"),
    _node("S:00-Price:PA:1", "clause", 1, number="1"),
    _node("S:00-Price:PA:2", "clause", 2, number="2"),
    _node("S:00-Price:PB", "part", 3, number="B", title="Payment"),
    _node("S:01-Goods", "subdocument", 4, doc_name="Sample Goods Schedule"),
    _node("S:01-Goods:PA", "part", 4, number="A"),
    _node("S:01-Goods:PA:2", "clause", 4, number="2"),
    _node("S:01-Goods:PB", "part", 5, number="B"),
    _node("S:01-Goods:PB:2", "clause", 5, number="2"),
    # A standalone booklet whose Parts carry the document names.
    _node("T", "document", 1),
    _node("T:P1", "part", 2, number="1", title="SAMPLE TERMS"),
    _node("T:P1:7", "clause", 3, number="7"),
    _node("T:P1:7.2", "subclause", 3, number="7.2"),
    _node("T:P1:7.2:(b)", "subitem", 3, label="(b)"),
    _node("T:ANNEX-A", "annex", 9, number="A", text="Annex A to the Sample Terms\nUNDERTAKING"),
    # Standalone files named only by their footer.
    _node("C", "document", 1),
    _node("C:(4)", "subitem", 2, label="(4)", doc_name="Appendix to the Sample Terms - Contacts"),
    _node("D", "document", 1),
    _node("D:PIA", "part", 1, number="IA", doc_name="Annex B to the Sample Terms"),
    _node("D:PIB", "part", 1, number="IB", doc_name="Annex B to the Sample Terms"),
    # A form known only by its title line.
    _node("F", "document", 1, aliases=["SAMPLE FORM"]),
    _node("F:P4", "part", 2, number="4", title="OFFER"),
]


def _resolve(text):
    index = CitationIndex(NODES)
    return [[n["node_id"] for n in nodes] for _, nodes in index.resolve_text(text)]


def test_paragraph_of_a_named_part_still_resolves():
    assert _resolve("Paragraph 7.2(b) of the Sample Terms") == [["T:P1:7.2:(b)"]]


def test_part_and_numbered_row_of_a_sub_document():
    assert _resolve("Part B of the Sample Price Schedule") == [["S:00-Price:PB"]]
    assert _resolve("Item 1 in Part A of the Sample Price Schedule") == [["S:00-Price:PA:1"]]


def test_lists_and_ranges_expand_to_one_citation_per_target():
    assert _resolve("Paragraphs 2 of Tables A and B of the Sample Goods Schedule") == [
        ["S:01-Goods:PA:2"], ["S:01-Goods:PB:2"]]
    assert _resolve("Items 1 to 2 in Part A of the Sample Price Schedule") == [
        ["S:00-Price:PA:1"], ["S:00-Price:PA:2"]]


def test_numbered_part_of_an_appendix_and_dash_named_part_of_an_annex():
    assert _resolve("part (4) in the Appendix to the Sample Terms (Contacts)") == [["C:(4)"]]
    assert _resolve("Annex B to the Sample Terms - Part IB - Method of refund") == [["D:PIB"]]


def test_annex_named_after_its_document():
    assert _resolve("the terms set out at Annex A to the Sample Terms.") == [["T:ANNEX-A"]]


def test_whole_document_mentions_and_title_aliases():
    assert _resolve("The Sample Goods Schedule, duly completed.") == [["S:01-Goods"]]
    assert _resolve("Part 4 of the Sample Form (signed version)") == [["F:P4"]]


def test_part_titles_in_mixed_case_are_not_document_mentions():
    assert _resolve("an Estimated Price is required") == []


def test_parse_citations_keeps_the_legacy_fields():
    (citation,) = parse_citations("Paragraph 10.1(j) of the Terms of Tender")
    assert (citation.number, citation.name, citation.items) == ("10.1", "Terms of Tender", ("j",))
