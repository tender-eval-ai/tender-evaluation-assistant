"""Table handling in the layout parser: grid row/cell reading and row labelling.

These exercise the pure helpers directly with stub grids rather than through a
PDF, because `tools.pdfgen` writes a text layer only - it cannot draw the ruled
lines PyMuPDF's table finder detects, so the grid path is unreachable from a
synthetic document.
"""
from pathlib import Path
from types import SimpleNamespace


from app.parsing.layout_document_index import (
    _layout_blocks,
    _page_grids,
    _row_label,
    _table_row_pieces,
)
from tools.pdfgen import make_text_pdf

def _grid(rows):
    """A stub of PyMuPDF's Table: `rows` is [(top, bottom, [cell bboxes])]."""
    return SimpleNamespace(
        row_count=len(rows),
        rows=[SimpleNamespace(bbox=(0, top, 600, bottom), cells=cells) for top, bottom, cells in rows],
    )

def test_row_label_prefers_a_short_unique_first_cell():
    seen: set[str] = set()
    assert _row_label("β", 0, seen) == "β"
    assert _row_label("μSv/h", 1, seen) == "μSv/h"

def test_row_label_falls_back_to_position_when_the_cell_repeats_or_is_long():
    seen: set[str] = set()
    assert _row_label("Item", 0, seen) == "Item"
    assert _row_label("Item", 1, seen) == "r2", "a repeated first cell is not a key"
    assert _row_label("x" * 80, 2, seen) == "r3", "a sentence is not a key"
    assert _row_label("   ", 3, seen) == "r4", "an empty first cell is not a key"

def test_a_rows_marker_column_is_read_before_the_cell_beside_it():
    """The defect this exists for: `_reading_lines` orders a block by vertical
    centre, so a marker set lower than the text beside it reads after that text
    ("Business profile information ... (h) the number and location ...")."""
    marker_cell = (40, 100, 80, 140)
    body_cell = (80, 100, 560, 140)
    grid = _grid([(100, 140, [marker_cell, body_cell])])
    items = [
        ("Business profile information of the Tenderer", (90, 102, 400, 112)),
        ("(h)", (45, 118, 70, 128)),          # lower than the body's first line
        ("including the number of employees", (90, 118, 400, 128)),
    ]

    pieces = _table_row_pieces(items, grid)

    assert len(pieces) == 1
    lines, label = pieces[0]
    text = " ".join(t for line in lines for t, _ in line)
    assert text.startswith("(h)"), text
    assert label == "(h)"

def test_each_grid_row_becomes_its_own_piece():
    grid = _grid([
        (100, 140, [(40, 100, 80, 140), (80, 100, 560, 140)]),
        (140, 180, [(40, 140, 80, 180), (80, 140, 560, 180)]),
    ])
    items = [
        ("β", (45, 110, 60, 120)), ("Beta", (90, 110, 130, 120)),
        ("γ", (45, 150, 60, 160)), ("Gama", (90, 150, 130, 160)),
    ]

    pieces = _table_row_pieces(items, grid)

    assert [label for _, label in pieces] == ["β", "γ"]

def test_a_grid_that_does_not_cover_every_item_is_rejected():
    """A caption or trailing note inside the same layout block means the grid
    does not describe this block; the caller falls back to the text-only split
    rather than silently dropping the uncovered text."""
    grid = _grid([(100, 140, [(40, 100, 560, 140)])])
    items = [("β", (45, 110, 60, 120)), ("a note far below the table", (45, 400, 300, 412))]

    assert _table_row_pieces(items, grid) == []

def test_a_table_with_no_cells_is_dropped_rather_than_raising():
    """PyMuPDF raises `ValueError: min() iterable argument is empty` from
    `Table.bbox` when a detected table carries no cells - seen on the borderless
    glossary, and it crashed a whole 12-document run before this guard."""
    class _Cellless:
        row_count = 3
        rows = []

        @property
        def bbox(self):
            raise ValueError("min() iterable argument is empty")

    page = SimpleNamespace(find_tables=lambda: SimpleNamespace(tables=[_Cellless()]))

    assert _page_grids("no-such-file.pdf", 1, page) == []

def test_every_layout_block_carries_its_row_label_field(tmp_path: Path):
    """Blocks are 5-tuples. Widening them from 4 broke two unpack sites that no
    existing test covered, one of which only runs on a table-shaped page."""
    pdf = tmp_path / "plain.pdf"
    make_text_pdf(pdf, ["Part A", "", "(a) The first item.", "", "(b) The second item."])

    blocks = _layout_blocks(str(pdf), 1)

    assert blocks, "expected at least one block"
    assert all(len(block) == 5 for block in blocks)
    assert all(block[4] is None for block in blocks), "a non-table block has no row label"


def test_a_picture_carrying_a_text_layer_is_read_as_a_table(monkeypatch, tmp_path: Path):
    """The layout model sometimes classifies a whole ruled table as a picture;
    dropped as one, every row of it was lost. A picture with at most a few
    labels is still dropped."""
    import app.parsing.layout_document_index as layout
    import pymupdf.layout.pymupdf_util as util

    pdf = tmp_path / "page.pdf"
    make_text_pdf(pdf, ["placeholder"])
    rows = [("1", "First sample item"), ("2", "Second sample item"), ("3", "Third sample item"),
            ("4", "Fourth sample item")]
    texts, bboxes = [], []
    for index, (number, description) in enumerate(rows):
        top = 200 + 20 * index
        texts += [number, description]
        bboxes += [[60, top, 70, top + 10], [120, top, 300, top + 10]]
    texts.append("Figure label")
    bboxes.append([60, 500, 120, 510])
    groups = [
        {"class_name": "picture", "indicies": list(range(8)), "group_bbox": [50, 190, 320, 290]},
        {"class_name": "picture", "indicies": [8], "group_bbox": [50, 490, 320, 520]},
    ]
    model = SimpleNamespace(predict=lambda page, return_raw=True: groups,
                            input_type=None, feature_set_name=None, feature_extractor=None)
    monkeypatch.setattr(layout, "_get_model", lambda: model)
    monkeypatch.setattr(util, "create_input_data_from_page", lambda page, options=None: {"text": texts, "bboxes": bboxes})

    blocks = layout._layout_blocks(str(pdf), 1)

    assert [b[2] for b in blocks] == [f"{n} {d}" for n, d in rows]
    assert all(b[1] == "table" for b in blocks)


def test_a_table_row_keyed_by_a_bare_number_carries_that_number(monkeypatch):
    from test.parsing.stub_layout import parse_blocks

    nodes = parse_blocks(monkeypatch, {1: [
        (36, "section-header", "Part A - Sample Prices"),
        (40, "table", "Item Description Quantity", "Item"),
        (40, "table", "2 A second sample item 4 sets", "2"),
        (40, "table", "3 A third sample item 2 sets", "3"),
    ]})

    rows = {n["label"]: n for n in nodes.values() if n.get("label")}
    assert rows["2"]["number"] == "2"
    assert rows["3"]["number"] == "3"
    assert rows["Item"]["number"] is None, "a header cell is not a number"
