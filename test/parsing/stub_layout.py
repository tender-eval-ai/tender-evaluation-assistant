"""Drive the layout parser's main loop from stub layout blocks instead of a PDF.

`tools.pdfgen` writes every line at one left margin and cannot draw ruled
tables, so block geometry and classes (marker column, text column, `table`)
cannot be produced through a synthetic PDF. Blocks here are exact.
"""
import app.parsing.layout_document_index as layout
from app.parsing.loader import Page


def parse_blocks(monkeypatch, blocks_by_page: dict[int, list[tuple[float, str, str]]]) -> dict[str, dict]:
    """Parse stub blocks, given per page as (x0, class_name, text); returns nodes by id."""
    def blocks(_source, page_number):
        out = []
        for index, (x0, class_name, text) in enumerate(blocks_by_page.get(page_number, [])):
            top = 100 + 20 * index
            out.append((x0, class_name, text, [x0, top, 520, top + 12], None))
        return out

    monkeypatch.setattr(layout, "_layout_blocks", blocks)
    pages = [Page("sample.pdf", number, True, "Sample text on this page for the parser.")
             for number in sorted(blocks_by_page)]
    return {n["node_id"]: n for n in layout.parse_document("doc", pages)}
