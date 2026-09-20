"""CitationIndex on a hand-built, synthetic node table (no tender data)."""
import time

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


def test_a_name_that_runs_on_past_in_falls_back_to_the_known_name():
    assert _resolve("Part A of the Sample Price Schedule in Local Currency") == [["S:00-Price:PA"]]


def test_lists_and_ranges_expand_to_one_citation_per_target():
    assert _resolve("Paragraphs 2 of Tables A and B of the Sample Goods Schedule") == [
        ["S:01-Goods:PA:2"], ["S:01-Goods:PB:2"]]
    assert _resolve("Items 1 to 2 in Part A of the Sample Price Schedule") == [
        ["S:00-Price:PA:1"], ["S:00-Price:PA:2"]]


def test_numbered_part_of_an_appendix_and_dash_named_part_of_an_annex():
    assert _resolve("part (4) in the Appendix to the Sample Terms (Contacts)") == [["C:(4)"]]
    assert _resolve("Annex B to the Sample Terms - Part IB - Method of refund") == [["D:PIB"]]


def test_several_dash_named_parts_in_brackets_each_resolve():
    assert _resolve("Annex B to the Sample Terms - (Part IA - Method of payment and "
                    "Part IB - Method of refund (if applicable)).") == [["D:PIA"], ["D:PIB"]]


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


def test_a_numbered_file_names_its_document():
    nodes = [dict(_node("G", "document", 1), source_file="/tender/01 Sample Form (G.F.999).pdf"),
             _node("G:P4", "part", 2, number="4", title="OFFER"),
             dict(_node("H", "document", 1), source_file="10 Appendix to the Sample Terms - Contacts.pdf"),
             _node("H:(4)", "subitem", 1, label="(4)"),
             _node("H:(5)", "subitem", 1, label="(5)"),
             dict(_node("K", "document", 1), source_file="04 Sample Terms (Supplement).pdf")]
    index = CitationIndex(nodes)

    def resolve(text):
        return [[n["node_id"] for n in found] for _, found in index.resolve_text(text)]

    assert resolve("Part 4 of the Sample Form (English version)") == [["G:P4"]]
    assert resolve("parts (4) and (5) respectively in the Appendix to the Sample Terms - Contacts") == [
        ["H:(4)"], ["H:(5)"]]
    assert resolve("part (4) in the Appendix to the Sample Terms") == [["H:(4)"]]
    # A parenthesis without a digit is part of the name, not a form number.
    assert index.scopes.get("sample term") is None


def test_chains_sharing_one_document_name_each_resolve():
    assert _resolve("Paragraph 2 of Table A, paragraph 2 of Table B and Part B of the Sample Goods Schedule") == [
        ["S:01-Goods:PA:2"], ["S:01-Goods:PB:2"], ["S:01-Goods:PB"]]
    # Two chains with their own names stay separate.
    assert _resolve("Paragraph 7.2(b) of the Sample Terms and Part B of the Sample Price Schedule") == [
        ["T:P1:7.2:(b)"], ["S:00-Price:PB"]]


def test_a_wrapped_footer_label_is_found_by_its_long_tail():
    nodes = [_node("W", "document", 1),
             _node("W:00-Contacts", "subdocument", 1, doc_name="Sample Terms of Tender - Contact Details"),
             _node("W:00-Contacts:(5)", "subitem", 1, label="(5)"),
             _node("W:01-Terms", "subdocument", 2, doc_name="Sample Terms of Tender"),
             _node("W:01-Terms:3", "clause", 2, number="3")]
    index = CitationIndex(nodes)

    def resolve(text):
        return [[n["node_id"] for n in found] for _, found in index.resolve_text(text)]

    assert (resolve("part (5) in the Appendix to the Sample Terms of Tender (Contact Details)")
            == [["W:00-Contacts:(5)"]])
    # A short known tail is a document of its own, not a wrapped label.
    assert resolve("Paragraph 3 of the Annex Z to the Sample Terms of Tender") == [[]]


def test_a_long_list_with_no_document_name_parses_quickly():
    """A list that is not a citation must fail fast, not backtrack.

    Every id in a list used to be matchable as a number, a Part id and an annex id
    over the same text, so a chain that failed for want of a document name was
    re-read 3**n ways: measured before the fix, 14 items took 17.7 s and 20 items
    over 10 minutes; a chain that did end in a name stayed instant either way.
    """
    long_list = "Paragraphs " + ", ".join(str(n) for n in range(1, 20)) + " and 20 above are separate."
    respectively = ("Paragraphs " + ", ".join(str(n) for n in range(1, 10))
                    + " and 10 and Tables " + ", ".join(chr(65 + n) for n in range(9)) + " and J respectively.")
    of_chain = " ".join("paragraph %d of Table A" % n for n in range(1, 11)) + " below."

    start = time.perf_counter()
    for text in (long_list, respectively, of_chain):
        assert parse_citations(text) == []
    assert time.perf_counter() - start < 0.05

    # The same list resolves as before once a document name follows it.
    named = "Paragraphs " + ", ".join(str(n) for n in range(1, 20)) + " and 20 of the Sample Terms"
    assert [c.number for c in parse_citations(named)] == [str(n) for n in range(1, 21)]


def test_a_paragraph_of_an_annex_with_no_node_stays_unresolved():
    """"Annex 1 to the <X>" is a container of its own, not a wrapped label of <X>.

    The long-tail fallback below read the name as <X> and returned <X>'s own clause
    of that number - a confidently wrong location. Unresolved beats wrong: locate
    reports it as `unresolved`, where a wrong node is invisible.
    """
    nodes = [_node("W", "document", 1),
             _node("W:00-Terms", "subdocument", 1, doc_name="Sample Terms of Tender - Contact Details"),
             _node("W:00-Terms:(5)", "subitem", 1, label="(5)"),
             _node("W:00-Terms:3", "clause", 1, number="3")]
    index = CitationIndex(nodes)

    def resolve(text):
        return [[n["node_id"] for n in found] for _, found in index.resolve_text(text)]

    assert resolve("Paragraph 3 of the Annex 1 to the Sample Terms of Tender - Contact Details") == [[]]
    assert resolve("Paragraph 3 of the Supplement to the Sample Terms of Tender - Contact Details") == [[]]
    # A head with no identifier of its own is how a wrapped footer label reads, and
    # still finds the document by its tail (both real cases on Tender 3).
    assert resolve("part (5) in the Appendix to the Sample Terms of Tender (Contact Details)") == [["W:00-Terms:(5)"]]
