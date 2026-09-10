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
    doc = load_pdf(pdf, Config())
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
        load_pdf(pdf, Config())


def _tiny_jpeg() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(buf, format="JPEG")
    return buf.getvalue()


class _OCRStub:
    def __init__(self):
        self.calls = 0

    def ocr_page(self, png_bytes):
        self.calls += 1
        return "OCR CONTENT of the scanned page"


class _NoOCR:
    def ocr_page(self, png_bytes):
        raise AssertionError("OCR must not be called for imageless text pages")


def test_mixed_pdf_ocrs_only_the_scanned_page(tmp_path):
    # Page 1 has a rich text layer; page 2 is image-only (a scanned annex): the
    # text-vs-scan decision is per page, so only page 2 goes through OCR.
    pdf = tmp_path / "mixed.pdf"
    make_text_pdf(pdf, ["Tender terms and conditions apply. " * 10] + [""] * 48,
                  images={1: _tiny_jpeg()})
    assert classify_pdf(pdf) == "text"
    cfg = Config()
    cfg.cache_dir = tmp_path / "cache"
    llm = _OCRStub()
    doc = load_pdf(pdf, cfg, llm)
    assert [p.source for p in doc.pages] == ["text", "ocr"]
    assert doc.pages[1].text == "OCR CONTENT of the scanned page"
    assert llm.calls == 1
    # Second load hits the per-page cache — no new OCR call.
    doc2 = load_pdf(pdf, cfg, llm)
    assert llm.calls == 1 and doc2.pages[1].source == "ocr"


def test_text_pdf_blank_page_not_ocred(tmp_path):
    # An imageless sparse page (blank separator) in a text document must not waste
    # an OCR call — there is nothing on it to read.
    pdf = tmp_path / "report.pdf"
    make_text_pdf(pdf, ["Substantive tender content here. " * 10] + [""] * 48)
    doc = load_pdf(pdf, Config(), _NoOCR())
    assert [p.source for p in doc.pages] == ["text", "text"]
