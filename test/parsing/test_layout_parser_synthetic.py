"""Smoke test for the ported layout parser on a generated, synthetic schedule (no tender data)."""
from pathlib import Path

from app.parsing.layout_document_index import parse_document
from app.parsing.loader import load_pdf
from tools.pdfgen import make_text_pdf

SCHEDULE = [
    "Completeness Check Schedule",
    "",
    "Part A",
    "The Tenderer shall note Paragraph 3.3 of the Terms of Tender.",
    "",
    "(a) The signed Offer to be Bound in Part 4 of the Tender Form.",
    "",
    "(b) The unit price quotation for Item 1 in Part A of the Price Schedule.",
    "",
    "Part B",
    "In addition to the documents in Part A, the Tenderer shall submit the following.",
    "",
    "(c) The information required in Table A of the Information Schedule.",
]


def test_parts_and_items_become_nodes(tmp_path: Path):
    pdf = tmp_path / "schedule.pdf"
    make_text_pdf(pdf, SCHEDULE)

    nodes = parse_document(None, load_pdf(pdf))

    items = {(n["part"], n["label"]): n for n in nodes if n["kind"] == "subitem"}
    assert set(items) == {("Part A", "(a)"), ("Part A", "(b)"), ("Part B", "(c)")}
    assert all(n["page"] == 1 for n in items.values())
    assert items[("Part A", "(b)")]["text"].startswith("(b)")
    assert items[("Part A", "(b)")]["char_end"] == len(items[("Part A", "(b)")]["text"])
