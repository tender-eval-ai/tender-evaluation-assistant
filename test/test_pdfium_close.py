"""pdfium's children are closed before their document (app.ingest, app.checks.verify). Left to
the garbage collector, a page or text page freed while the document closed changed the set
close() walks, and a correction answered 500 (RuntimeError: Set changed size during
iteration, seeding the Showcase, 2026-09-30). Many opens with collections in between must not
raise, and must find the same quote every time."""
import gc
from pathlib import Path

from app.checks.verify import page_text
from app.ingest import locate_quote, render_page_png

PDF = Path(__file__).resolve().parent / "data" / "synthetic_tender" / "tender" / "09 Schedules.pdf"


def test_many_opens_with_collections_between_them_never_raise():
    first = locate_quote(PDF, 0, "PRICE SCHEDULE")
    assert first is not None and first.quote.upper() == "PRICE SCHEDULE"
    for n in range(150):
        assert locate_quote(PDF, 0, "PRICE SCHEDULE") == first
        if n % 10 == 0:
            assert render_page_png(PDF, 0, scale=0.5, highlight="PRICE SCHEDULE")[:4] == b"\x89PNG"
            assert "PRICE SCHEDULE" in page_text(PDF, 0).upper()
            gc.collect()
