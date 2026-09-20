"""Structure of the layout parser's node tree on generated, synthetic documents (no tender data)."""
from pathlib import Path

from app.parsing.layout_document_index import parse_document
from app.parsing.loader import load_pdf
from tools.pdfgen import LINES_PER_PAGE, make_text_pdf


def _pages(*pages: list[str]) -> list[str]:
    """One list of lines per PDF page, padded so each starts on a new page."""
    lines: list[str] = []
    for page in pages:
        lines.extend(page + [""] * (LINES_PER_PAGE - len(page)))
    return lines


def _parse(tmp_path: Path, lines: list[str]) -> list[dict]:
    pdf = tmp_path / "document.pdf"
    make_text_pdf(pdf, lines)
    return parse_document(None, load_pdf(pdf))


def test_standalone_document_node_starts_on_its_first_page(tmp_path: Path):
    nodes = _parse(tmp_path, _pages(
        ["Sample Certificate", "", "1. The Tenderer certifies that it has read the documents."],
        ["2. The Tenderer certifies that the tender is genuine."],
    ))

    document = next(n for n in nodes if n["kind"] == "document")
    assert document["page"] == 1


def test_parts_belong_to_the_sub_document_they_appear_in(tmp_path: Path):
    nodes = _parse(tmp_path, _pages(
        ["Sample Price Schedule", "", "Part A - Estimated Price",
         "1. Tenderers shall quote a unit price for each item.", "", "Sample Price Schedule Page 1 of 1"],
        ["Sample Compliance Schedule", "", "Part A - Statement of Compliance",
         "1. Tenderers shall state compliance with each requirement.", "", "Sample Compliance Schedule Page 1 of 1"],
    ))

    subdocs = {n["doc_name"]: n["node_id"] for n in nodes if n["kind"] == "subdocument"}
    parts = [n for n in nodes if n["kind"] == "part"]
    assert sorted(n["parent_id"] for n in parts) == sorted(subdocs.values())
    assert all("#" not in n["node_id"] for n in parts)
    clauses = [n for n in nodes if n["kind"] == "clause"]
    assert {n["parent_id"] for n in clauses} == {n["node_id"] for n in parts}


def test_reading_lines_keep_a_slightly_lower_marker_on_its_own_line():
    from app.parsing.layout_document_index import _join_lines, _reading_lines

    # A marker and a drop capital set a fraction of a point below the rest of
    # their line, straddling a 5-point boundary, then a second line of text.
    items = [
        ("he information required in Table G of the", [153.7, 389.9, 520.9, 400.4]),
        ("(f)", [117.8, 390.1, 129.8, 401.0]),
        ("T", [146.6, 390.3, 153.7, 397.9]),
        ("Schedule.", [146.6, 403.1, 252.4, 411.3]),
    ]

    assert _join_lines(_reading_lines(items)) == "(f) T he information required in Table G of the Schedule."


def test_block_splits_where_a_line_opens_with_a_marker_in_the_marker_column():
    from app.parsing.layout_document_index import _join_lines, _reading_lines, _split_at_marker_lines

    items = [
        ("(i)", [118, 523, 129, 534]), ("Where the first condition applies, a letter", [147, 523, 521, 534]),
        ("of intent is required.", [147, 537, 300, 548]),
        ("(j)", [118, 578, 129, 589]), ("Where the second condition applies, a letter", [147, 578, 521, 589]),
        ("(ii) is not a new item because it is not in the marker column", [147, 592, 521, 603]),
    ]

    pieces = [_join_lines(p) for p in _split_at_marker_lines(_reading_lines(items))]

    assert pieces == [
        "(i) Where the first condition applies, a letter of intent is required.",
        "(j) Where the second condition applies, a letter (ii) is not a new item because it is not in the marker column",
    ]


def test_inline_enumeration_is_not_split():
    from app.parsing.layout_document_index import _reading_lines, _split_at_marker_lines

    items = [
        ("(e)", [118, 100, 129, 111]), ("the Tenderer; or", [147, 100, 400, 111]),
        ("(ii) a related person of the Tenderer", [147, 114, 400, 125]),
    ]

    assert len(_split_at_marker_lines(_reading_lines(items))) == 1


def test_text_before_the_first_marker_is_the_documents_own_text(monkeypatch):
    """A schedule's title and preamble come before its first marker; they used to
    be dropped from every node. The running masthead is kept once, where it opens
    the document, and still dropped where it repeats on later pages."""
    from test.parsing.stub_layout import parse_blocks

    masthead = "SAMPLE SCHEDULE (To be completed and returned)"
    nodes = parse_blocks(monkeypatch, {
        1: [(200, "section-header", masthead),
            (36, "text", "References to the sample terms have the meanings given there."),
            (36, "section-header", "Part A - Sample Details"),
            (48, "list-item", "(a) Name of the sample")],
        2: [(200, "section-header", masthead),
            (48, "list-item", "(b) Address of the sample")],
    })

    document = nodes["doc"]
    assert document["text"].startswith(masthead)
    assert "References to the sample terms" in document["text"]
    assert all(masthead not in n["text"] for n in nodes.values() if n is not document)


def test_a_notes_heading_is_split_from_a_first_note_numbered_by_letter_or_roman_numeral():
    from app.parsing.layout_document_index import _split_notes_heading

    assert _split_notes_heading("Notes: (1) A first note.") == ["Notes:", "(1) A first note."]
    assert _split_notes_heading("Notes: (i) A first note.") == ["Notes:", "(i) A first note."]
    assert _split_notes_heading("Notes: (a) A first note.") == ["Notes:", "(a) A first note."]
    assert _split_notes_heading("Notes: see the table above.") == ["Notes: see the table above."]


def test_a_part_numbered_with_a_roman_numeral_and_a_letter_is_a_part():
    from app.parsing.layout_document_index import _classify_marker

    assert _classify_marker("Part IA")[:2] == ("part", "IA")
    assert _classify_marker("Part IB Method of refund")[:2] == ("part", "IB")
    assert _classify_marker("Part B - Sample Details")[:2] == ("part", "B")
    assert _classify_marker("Party A agrees")[0] is None
    assert _classify_marker("Part II")[0] is None, "a roman numeral alone is not a lettered Part"


def test_a_heading_without_a_marker_is_a_node_of_its_own(monkeypatch):
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (200, "section-header", "SAMPLE CERTIFICATE"),
        (36, "text", "1. The Tenderer certifies the first matter."),
        (36, "section-header", "Second Matter"),
        (36, "text", "2. The Tenderer certifies the second matter."),
        (60, "list-item", "(a) in one respect;"),
        (90, "section-header", "An address line set in the item's own text column"),
        (60, "list-item", "(b) in another respect."),
        (36, "section-header", "Glossary:"),
    ]})

    headings = [n for n in nodes.values() if n["node_id"].split(":")[-1].startswith("heading")]
    assert [n["text"] for n in headings] == ["Second Matter"], "a title, an indented line and a label are not headings"
    assert headings[0]["parent_id"] == "doc"
    assert nodes["doc"]["text"] == "SAMPLE CERTIFICATE", "the first heading is the document's own title"
    assert nodes["doc:1"]["text"] == "1. The Tenderer certifies the first matter."
    assert nodes["doc:2:(a)"]["text"].endswith("own text column")
    assert nodes["doc:2:(b)"]["parent_id"] == "doc:2"


def test_the_first_heading_after_a_part_without_a_title_is_its_title(monkeypatch):
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (200, "section-header", "SAMPLE ANNEX"),
        (270, "section-header", "Part IA"),
        (180, "section-header", "Method of Sample Payment"),
        (270, "section-header", "Part IB - Method of Sample Refund"),
        (180, "section-header", "Refund Options"),
    ]})

    assert nodes["doc:PIA"]["text"] == "Part IA\nMethod of Sample Payment"
    assert nodes["doc:PIB:heading"]["text"] == "Refund Options"


def test_blank_form_fields_are_nodes_of_their_own(monkeypatch):
    """A signature block's and a contact list's blank fields are nodes, added the
    way run-in sub-items are: the host keeps its text. A field the layout model
    took for page furniture (class "field") was never in any node and stands
    under the document."""
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (200, "section-header", "SAMPLE CERTIFICATE"),
        (36, "list-item", "6. The Tenderer certifies the last matter."),
        (48, "text", "Name of the signatory (where applicable) : Title of the signatory (where applicable) :"),
        (48, "text", "Date :"),
        (36, "text", "The Tenderer shall provide the details below:"),
        (48, "field", "Name of Bidder:"),
    ]})

    fields = {n["node_id"]: n for n in nodes.values() if ":field" in n["node_id"]}
    assert [(n["parent_id"], n["text"]) for n in fields.values()] == [
        ("doc:6", "Name of the signatory (where applicable) :"),
        ("doc:6", "Title of the signatory (where applicable) :"),
        ("doc:6", "Date :"),
        ("doc", "Name of Bidder:"),
    ]
    assert nodes["doc:6"]["text"].endswith("Date :\nThe Tenderer shall provide the details below:")
    assert "Name of Bidder" not in nodes["doc:6"]["text"]


def test_a_field_label_is_told_from_a_sentence_ending_in_a_colon():
    from app.parsing.layout_document_index import _field_labels

    assert _field_labels("Name of Bidder: ________") == ["Name of Bidder: ________"]
    assert _field_labels("Name of witness: Title of witness:") == ["Name of witness:", "Title of witness:"]
    assert _field_labels("日期 ：") == ["日期 ："]
    assert _field_labels("Signed by the Tenderer / Signed by a signatory for and on behalf of the Tenderer :")
    for prose in ("The Tenderer shall provide the information below:", "“Tender Form” means:",
                  "in the presence of :", "Signed by a signatory for and on behalf of the Sample Company:",
                  "Address: 1 Sample Road", "上述文件亦可在下列辦事處索取："):
        assert _field_labels(prose) is None, prose


def test_a_colon_set_in_its_own_column_joins_the_label_on_its_line():
    from app.parsing.layout_document_index import _attach_stray_colons

    blocks = [(56, "text", "Name of the Tenderer", [56, 400, 150, 410], None),
              (56, "text", "Date", [56, 485, 80, 495], None),
              (273, "text", ":", [273, 403, 276, 413], None),
              (273, "text", ":", [273, 488, 276, 498], None)]

    assert [b[2] for b in _attach_stray_colons(blocks)] == ["Name of the Tenderer :", "Date :"]


def test_a_paragraph_under_a_heading_only_node_is_a_node_of_its_own(monkeypatch):
    """A preamble under a document's title and the body under a titled Part are
    paragraph nodes, added the way run-in sub-items are (the heading keeps its
    text). An untitled Part's first block is its intro, not a paragraph, and a
    paragraph stopped mid-sentence at a page break carries on."""
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {
        1: [(200, "section-header", "SAMPLE SCHEDULE"),
            (150, "text", "(To be returned with the offer)"),
            (36, "text", "Words defined in the sample terms have the same meanings here."),
            (36, "section-header", "Part A"),
            (36, "text", "Items (a) and (b) below are required."),
            (48, "list-item", "(a) A sample."),
            (36, "section-header", "Part B - Sample Timetable"),
            (36, "text", "Payment is made in two instalments, the first on delivery of the")],
        2: [(36, "text", "samples and the second on acceptance."),
            (36, "text", "No other payment is made.")],
    })

    paragraphs = {n["node_id"]: n["text"] for n in nodes.values() if ":para" in n["node_id"]}
    assert paragraphs == {
        "doc:para": "Words defined in the sample terms have the same meanings here.",
        "doc:PB:para": "Payment is made in two instalments, the first on delivery of the\n"
                       "samples and the second on acceptance.",
        "doc:PB:para#2": "No other payment is made.",
    }
    assert nodes["doc"]["text"].endswith("the same meanings here.")
    assert nodes["doc:PA"]["text"] == "Part A\nItems (a) and (b) below are required."
    assert nodes["doc:PB"]["text"].endswith("No other payment is made.")


def test_an_item_flagged_in_the_margin_is_still_its_own_item(monkeypatch):
    """A one-letter flag before an item's marker - set apart as a block of its
    own, or in the item's own block - does not stop the item being a node."""
    from app.parsing.layout_document_index import _attach_item_flags
    from test.parsing.stub_layout import parse_blocks

    blocks = [(126, "list-item", "(e) A mandatory sample feature.", [126, 190, 520, 202], None),
              (64, "section-header", "(D)", [64, 245, 76, 257], None),
              (126, "list-item", "(f) It is a desirable sample feature.", [126, 244, 520, 256], None)]
    assert [b[2] for b in _attach_item_flags(blocks)] == [
        "(e) A mandatory sample feature.", "(D) (f) It is a desirable sample feature."]

    nodes = parse_blocks(monkeypatch, {1: [
        (88, "list-item", "4.18 Other Sample Features"),
        (56, "list-item", "(D) 4.18.1 It is a desirable feature that the sample is blue."),
        (126, "list-item", "(a) in one respect;"),
        (60, "list-item", "(D) (b) it is a desirable feature that the sample is light."),
    ]})

    assert nodes["doc:4.18.1"]["text"].startswith("(D) 4.18.1 It is")
    assert nodes["doc:4.18.1:(b)"]["text"].startswith("(D) (b) it is")
    assert nodes["doc:4.18.1:(a)"]["text"] == "(a) in one respect;"


def test_an_annex_named_only_in_its_page_header_is_an_annex(monkeypatch):
    """An annex bound into a longer document opens where its header line first
    appears (joined to the heading below it); the same header on the following
    pages is furniture, and on a document's own first page it is only the
    document's title."""
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {
        1: [(36, "list-item", "35. The last clause of the sample terms.")],
        2: [(363, "annex-title", "Annex A to the Sample Terms"),
            (170, "section-header", "SAMPLE UNDERTAKING"),
            (36, "text", "THIS UNDERTAKING is made on a sample day."),
            (36, "list-item", "1. The first clause of the undertaking.")],
        3: [(363, "annex-title", "Annex A to the Sample Terms"),
            (36, "list-item", "2. The second clause of the undertaking.")],
    })

    assert nodes["doc:ANNEX-A"]["text"].startswith("Annex A to the Sample Terms\nSAMPLE UNDERTAKING")
    assert nodes["doc:ANNEX-A:para"]["text"] == "THIS UNDERTAKING is made on a sample day."
    assert nodes["doc:ANNEX-A:1"]["parent_id"] == nodes["doc:ANNEX-A:2"]["parent_id"] == "doc:ANNEX-A"
    assert nodes["doc:35"]["text"] == "35. The last clause of the sample terms."
    assert not any(n["kind"] == "annex" and n["node_id"] != "doc:ANNEX-A" for n in nodes.values())

    standalone = parse_blocks(monkeypatch, {1: [
        (353, "annex-title", "Annex A to the Sample Terms"),
        (290, "section-header", "Part IA"),
        (190, "section-header", "Method of Sample Payment")]})

    assert standalone["doc"]["text"] == "Annex A to the Sample Terms"
    assert standalone["doc:PIA"]["parent_id"] == "doc"


def test_a_paragraph_of_a_few_words_with_no_stop_runs_on(monkeypatch):
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (200, "section-header", "SAMPLE CERTIFICATE"),
        (36, "text", "To: the Sample Office"),
        (36, "text", "Dear Sir/Madam,"),
        (36, "text", "BY"),
        (240, "text", "whose office is at a sample address"),
        (36, "text", "The Tenderer certifies the sample matter."),
    ]})

    assert [n["text"] for n in nodes.values() if ":para" in n["node_id"]] == [
        "To: the Sample Office\nDear Sir/Madam,",
        "BY\nwhose office is at a sample address",
        "The Tenderer certifies the sample matter."]


def test_a_part_of_the_chinese_tender_form_is_a_part():
    from app.parsing.layout_document_index import _classify_marker

    assert _classify_marker("第 4 部分 — 樣本標題")[:2] == ("part", "4")
    assert _classify_marker("第3甲部分 — 樣本標題")[:2] == ("part", "3A")
    assert _classify_marker("第 5 部分 樣本標題")[:2] == ("part", "5")
    assert _classify_marker("第 9.9(z) 段的樣本")[0] is None
