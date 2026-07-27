"""PDF classification: digital-text PDFs are read directly; scans are routed to OCR."""
import pytest

from app.config import Config
from app.ingest import classify_pdf, load_pdf
from test.conftest import make_text_pdf

TEXT = ("Terms of Tender Supplement. The Tenderer shall submit the Price Schedule and "
        "the Particulars of Goods Schedule. Delivery within 60 days is an essential "
        "requirement. Shelf life of at least 12 months is required.")


def test_text_pdf_classified_and_extracted(tmp_path):
    pdf = tmp_path / "terms.pdf"
    make_text_pdf(pdf, TEXT)
    assert classify_pdf(pdf) == "text"
    doc = load_pdf(pdf, Config(token="unused"))
    assert doc.kind == "text"
    assert "essential requirement" in doc.pages[0].text
    assert "[Page 1]" in doc.joined()


def test_scanned_pdf_requires_llm(tmp_path):
    # A page with no extractable text is treated as scanned; without a vision client
    # ingestion must fail loudly rather than silently produce an empty document.
    from pypdf import PdfWriter
    pdf = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf, "wb") as f:
        writer.write(f)
    assert classify_pdf(pdf) == "scanned"
    with pytest.raises(RuntimeError, match="OCR requires"):
        load_pdf(pdf, Config(token="unused"))
