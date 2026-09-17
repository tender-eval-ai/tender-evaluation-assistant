"""V0: every page rendered once, numbered across the offer, no cap."""
from pathlib import Path

from app.checks.pages import read_png, render_offer
from test.checks.conftest import CASE, TRUTH


def test_every_page_of_a_scanned_offer_is_rendered_and_cached(tmp_path):
    bid = CASE / "bids" / "Tenderer_B"
    refs = render_offer(bid, tmp_path)
    assert len(refs) == TRUTH["bids"]["Tenderer_B"]["pages"] == 16
    assert [r.seq for r in refs] == list(range(1, 17)) and all(r.doc == "offer.pdf" for r in refs)
    assert not any(r.has_text for r in refs), "a scanned offer has no text layer"
    assert read_png(refs[12])[:8] == b"\x89PNG\r\n\x1a\n"
    pngs = sorted(Path(refs[0].path).parent.glob("page_*.png"))
    assert len(pngs) == 16
    stamps = [p.stat().st_mtime_ns for p in pngs]
    again = render_offer(bid, tmp_path)
    assert [r.path for r in again] == [r.path for r in refs]
    assert [p.stat().st_mtime_ns for p in pngs] == stamps, "a second render reuses the files"


def test_a_digital_offer_reports_its_text_layer(tmp_path):
    refs = render_offer(CASE / "bids" / "Tenderer_A", tmp_path)
    assert len(refs) == 12 and all(r.has_text for r in refs)


def test_progress_counts_pages_across_the_offer(tmp_path):
    seen = []
    render_offer(CASE / "bids" / "Tenderer_A", tmp_path, progress=lambda d, n: seen.append((d, n)))
    assert seen[0] == (1, 12) and seen[-1] == (12, 12)
