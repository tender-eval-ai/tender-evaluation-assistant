"""The two evaluations in tools/eval_parser.py, on a hand-built key and node table."""
from app.parsing.loader import Page
from tools.eval_parser import citation_resolution, key_marker_path, match_deep_key, parser_recall


def _node(node_id, kind, page, text="", number=None, label=None, title=None):
    return {"node_id": node_id, "parent_id": node_id.rpartition(":")[0] or None, "kind": kind, "page": page,
            "text": text, "number": number, "label": label, "title": title, "source_file": "02 Terms.pdf"}


NODES = [
    _node("T", "document", 1),
    _node("T:P1", "part", 2, "PART 1 SAMPLE TERMS", number="1", title="SAMPLE TERMS"),
    _node("T:P1:2", "clause", 3, "2. Mandatory Features The Goods shall", number="2"),
    _node("T:P1:2:(a)", "subitem", 3, "(a) Ferric chloride content", label="(a)"),
    _node("T:P1:2:(i)", "subitem", 3, "(i) Cadmium content", label="(i)"),
    # The parser hangs (k) under (i): the right words on the right page, the wrong place.
    _node("T:P1:2:(i):(k)", "subitem", 3, "(k) Copper content", label="(k)"),
    _node("T:P1:2:tail", "subitem", 4, "Glossary: GB/T - GuoBiao"),
    _node("T:P1:2:note", "subitem", 4, "Notes:"),
    _node("T:P1:2:(i)#2", "subitem", 4, "(i) The latest version shall also apply.", label="(i)"),
]


def _key(node_id, page, first_words, parent=None):
    return {"node_id": node_id, "parent_id": parent, "file": "02 Terms.pdf", "page": [page, page],
            "first_words": first_words}


KEY = [
    _key("ToT", 1, "SAMPLE TERMS"),
    _key("ToT:2", 3, "2. Mandatory Features The Goods shall"),
    _key("ToT:2(a)", 3, "(a) Ferric chloride content", "ToT:2"),
    _key("ToT:2(k)", 3, "(k) Copper content", "ToT:2"),
    _key("ToT:2:Glossary", 4, "Glossary: GB/T - GuoBiao", "ToT:2"),
    _key("ToT:2:Notes", 4, "Notes:", "ToT:2"),
    _key("ToT:2:Note(i)", 4, "(i) The latest version shall also apply.", "ToT:2:Notes"),
    _key("ToT:9", 8, "9. Not parsed at all"),
    _key("ToT:9:heading", 8, "A heading under 9", "ToT:9"),
]


def _found(key=KEY, nodes=NODES):
    return {k: (m["node"] or {}).get("node_id") for k, m in match_deep_key(key, nodes, single_file=False).items()}


def test_a_key_path_becomes_the_parser_id_segments_it_must_end_with():
    assert key_marker_path("ToT:3.3(a)(i)") == [{"3.3", "(3.3)"}, {"(a)"}, {"(i)"}]
    assert key_marker_path("InfoSchedule:TableB:Row(c)") == [{"PB", "TB"}, {"c", "(c)"}]
    assert key_marker_path("NCTC") == []
    for unmarked in ("TechSpec:2:Glossary", "POGS:Notes", "TechSpec:2:Note(ii)", "Form:field:Date"):
        assert key_marker_path(unmarked) is None


def test_a_marked_node_is_found_by_its_path_on_its_page():
    found = _found()
    assert found["ToT:2"] == "T:P1:2" and found["ToT:2(a)"] == "T:P1:2:(a)"
    assert found["ToT"] == "T", "a whole document is its document node on its first page"


def test_a_node_in_the_wrong_place_is_not_found_though_its_words_are_on_the_page():
    assert _found()["ToT:2(k)"] is None


def test_an_unmarked_node_is_found_by_its_marked_ancestor_and_first_words():
    found = _found()
    assert found["ToT:2:Glossary"] == "T:P1:2:tail"
    assert found["ToT:2:Notes"] == "T:P1:2:note"
    # The key's "Notes" level is skipped: the note's marked ancestor is clause 2, and
    # its words pick the note, not item (i) of the same marker.
    assert found["ToT:2:Note(i)"] == "T:P1:2:(i)#2"


def test_an_unmarked_node_under_a_missing_ancestor_is_not_found():
    matches = match_deep_key(KEY, NODES, single_file=False)
    assert matches["ToT:9"]["node"] is None and matches["ToT:9:heading"]["node"] is None
    assert matches["ToT:9:heading"]["why"] == "marked ancestor not found"


def test_recall_is_reported_for_all_marked_and_unmarked_nodes():
    report = parser_recall({"nodes": KEY}, NODES, single_file=False)
    assert report["marked"] == (3, 5)      # ToT, 2 and 2(a) found; 2(k) and 9 not
    assert report["unmarked"] == (3, 4)    # Glossary, Notes and Note(i) found; 9's heading not
    assert report["all"] == (6, 9)


def test_each_citation_is_unique_ambiguous_or_unresolved():
    nodes = NODES + [_node("F", "document", 1), _node("F:P1", "part", 2, number="1", title="SAMPLE TERMS"),
                     _node("F:P1:2", "clause", 2, number="2")]
    text = ("See Paragraph 2(a) of the Sample Terms, Paragraph 9 of the Sample Terms "
            "and Paragraph 2 of the Sample Terms.")
    report = citation_resolution({"02 Terms.pdf": [Page(source_file="02 Terms.pdf", page_number=1,
                                                        has_native_text=True, native_text=text)]}, nodes)
    assert [r["outcome"] for r in report["rows"]] == ["unique", "unresolved", "ambiguous"]
    assert report["unique"] == (1, 3) and report["ambiguous"] == 1 and report["unresolved"] == 1
