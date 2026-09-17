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

