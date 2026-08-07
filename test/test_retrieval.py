"""Targeted page selection: relevant late pages must beat an early-pages prefix."""
from app.ingest import Document, Page
from app.retrieval import (excerpt, excerpt_all, keywords_for_text,
                           keywords_from_rubric)
from app.rubric import load_rubric
from test.conftest import FIXTURES

FILLER = "General background text about the company history and its many offices. " * 20
PRICE_PAGE = ("Price Schedule Part A: unit price HK$ 12.50 per litre, estimated goods "
              "price HK$ 625,000.00, estimated quantity 50 000 litres.")


def make_doc(n_pages: int, special: dict[int, str]) -> Document:
    doc = Document(path=__import__("pathlib").Path("offer.pdf"), kind="text")
    for i in range(1, n_pages + 1):
        doc.pages.append(Page(number=i, text=special.get(i, FILLER), source="text"))
    return doc


def test_small_document_passes_through_whole():
    doc = make_doc(2, {1: "Tender Form signed.", 2: PRICE_PAGE})
    out = excerpt(doc, ["price schedule"], char_budget=10_000)
    assert "[Page 1]" in out and "[Page 2]" in out


def test_relevant_late_page_beats_prefix_truncation():
    # Price schedule sits on page 40 of 50 — far beyond what a prefix would keep.
    doc = make_doc(50, {40: PRICE_PAGE})
    budget = 6000  # roughly 4 filler pages worth
    out = excerpt(doc, ["price schedule", "unit price"], char_budget=budget)
    assert "[Page 40]" in out
    assert "625,000.00" in out
    assert len(out) <= budget
    # naive prefix of the same budget would never reach page 40
    assert "[Page 40]" not in doc.joined(budget)


def test_first_page_always_kept():
    doc = make_doc(30, {1: "Offer of Tenderer X, duly signed.", 25: PRICE_PAGE})
    out = excerpt(doc, ["price schedule"], char_budget=5000)
    assert "[Page 1]" in out and "[Page 25]" in out


def test_keywords_derived_from_rubric():
    rubric = load_rubric(FIXTURES / "rubric.json")
    kws = keywords_from_rubric(rubric)
    assert "certificate" in kws            # base family
    assert any("collusive" in k for k in kws)   # from this rubric's checklist
    assert any("shelf" in k for k in kws)       # from its requirements


def test_keywords_for_text_targets_one_item():
    kws = keywords_for_text("Non-collusive Tendering Certificate")
    assert "certificate" in kws and "tendering" in kws


def test_excerpt_all_respects_total_budget():
    docs = [make_doc(10, {5: PRICE_PAGE}) for _ in range(3)]
    out = excerpt_all(docs, ["price schedule"], per_doc_budget=3000, total_budget=5000)
    assert len(out) <= 5200  # headers allowed on top of content budget
    assert "### FILE:" in out