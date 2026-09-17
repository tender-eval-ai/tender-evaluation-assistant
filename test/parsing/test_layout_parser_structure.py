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
