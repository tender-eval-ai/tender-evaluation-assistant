"""The benchmark's definitions, pinned.

These exist so the four metrics cannot drift by accident. A change that makes one
of them more permissive fails here, and has to be argued for rather than slipped in.
"""
from tools.benchmark import BENCHMARK, own_markers, score, starts_with_own_marker


def test_the_benchmark_is_these_four_in_this_order():
    assert BENCHMARK == ("recall", "page_correct", "char_correct", "exact_location_correct")


def test_a_part_node_may_open_with_its_number_or_its_printed_name():
    """A Part carries both, and the document prints the second: "Part A", not "A"."""
    node = {"kind": "part", "label": None, "number": "A", "part": "Part A",
            "text": "Part A\nThe Tenderer shall note Paragraph 3.3"}
    assert own_markers(node) == ["A", "Part A"]
    assert starts_with_own_marker(node)


def test_part_is_a_scope_for_everything_that_is_not_a_part():
    """A "Notes:" block inside Part A must not be tested against "Part A"."""
    node = {"kind": "subitem", "label": None, "number": None, "part": "Part A", "text": "Notes:"}
    assert own_markers(node) == []
    assert starts_with_own_marker(node), "a node with no marker of its own passes"


def test_a_footnote_glyph_is_tolerated_but_a_bracketed_flag_is_not():
    """*/^/# are AI_camp's convention. A "(D)" desirability flag is the parser's job
    to attach, not this check's to ignore - widening it would loosen the metric."""
    assert starts_with_own_marker({"kind": "subitem", "label": "(a)", "text": "^(a) I/We confirm"})
    assert not starts_with_own_marker({"kind": "subclause", "number": "3.6.4.4",
                                       "text": "(D) 3.6.4.4 It is a desirable feature"})


def test_a_node_that_was_never_found_fails_every_metric():
    assert score({"page": [7, 7]}, None) == {m: False for m in BENCHMARK}


def test_exact_location_needs_a_bbox_and_the_right_page():
    key = {"page": [7, 7]}
    found = {"page": 7, "kind": "subitem", "label": "(a)", "text": "(a) something", "bbox": [0, 0, 1, 1]}
    assert score(key, found) == {m: True for m in BENCHMARK}

    assert not score(key, {**found, "bbox": None})["exact_location_correct"]
    wrong_page = score(key, {**found, "page": 8})
    assert wrong_page["recall"] and not wrong_page["page_correct"]
    assert not wrong_page["exact_location_correct"], "location is bounded by page"


def test_a_container_passes_char_correct_with_no_text_of_its_own():
    key = {"page": [3, 3]}
    assert score(key, {"page": 3, "kind": "subdocument", "text": ""})["char_correct"]
    assert not score(key, {"page": 3, "kind": "subitem", "text": ""})["char_correct"]
