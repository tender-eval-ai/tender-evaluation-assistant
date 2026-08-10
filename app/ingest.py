"""Ingestion: PDF classification (digital text vs scan), extraction, OCR with cache.

Finding from the sample data: tender (招标) documents carry text layers, but bid (投标)
documents are pure scans — so OCR via a vision model is the backbone for bids.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from .config import Config
from .llm import LLM

# Average extractable chars/page below which a PDF is treated as scanned.
SCAN_THRESHOLD = 100


@dataclass
class Page:
    number: int          # 1-based
    text: str
    source: str          # "text" | "ocr" | "skipped"


@dataclass
class Document:
    path: Path
    kind: str            # "text" | "scanned"
    pages: list[Page] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    def joined(self, max_chars: int | None = None) -> str:
        out = "\n".join(f"[Page {p.number}]\n{p.text}" for p in self.pages if p.text.strip())
        return out[:max_chars] if max_chars else out


def classify_pdf(path: Path, sample_pages: int = 5) -> str:
    reader = PdfReader(str(path))
    n = min(len(reader.pages), sample_pages)
    if n == 0:
        return "scanned"
    chars = sum(len(reader.pages[i].extract_text() or "") for i in range(n))
    return "text" if chars / n >= SCAN_THRESHOLD else "scanned"


def render_page_png(path: Path, page_index: int, scale: float = 2.0) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[page_index]
        pil = page.render(scale=scale).to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()


def _file_sha(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _page_has_image(page) -> bool:
    """True if the page carries an image XObject (i.e. looks like a scan)."""
    try:
        return bool(page.images)
    except Exception:
        return True  # malformed resources — assume it is worth OCR'ing


def load_pdf(path: Path, cfg: Config, llm: LLM | None = None) -> Document:
    """Load a PDF as per-page text. The text-vs-scan decision is made PER PAGE: pages
    with a usable text layer are read directly, sparse pages that carry an image are
    OCR'd through the vision model (on-disk cache). So a digital document with a
    scanned annex, or a scan with an embedded OCR layer on some pages, both get the
    cheap path wherever possible. Imageless sparse pages in a text document (blank
    separators, short cover pages) keep their text — there is nothing more to read.
    At most cfg.max_ocr_pages pages per document are OCR'd; the rest are skipped."""
    kind = classify_pdf(path)
    doc = Document(path=path, kind=kind)
    reader = PdfReader(str(path))

    if kind == "scanned" and llm is None:
        raise RuntimeError(f"{path.name} is a scanned PDF; OCR requires an LLM client.")

    cache = cfg.cache_dir / _file_sha(path)
    ocr_used = 0
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if len(text) >= SCAN_THRESHOLD:
            doc.pages.append(Page(number=i + 1, text=text, source="text"))
            continue
        if kind == "text" and (llm is None or not _page_has_image(page)):
            doc.pages.append(Page(number=i + 1, text=text, source="text"))
            continue
        if ocr_used >= cfg.max_ocr_pages:
            doc.pages.append(Page(number=i + 1, text="", source="skipped"))
            continue
        cached = cache / f"page_{i + 1:04d}.md"
        if cached.is_file():
            text = cached.read_text()
        else:
            cache.mkdir(parents=True, exist_ok=True)
            text = llm.ocr_page(render_page_png(path, i))
            cached.write_text(text)
        ocr_used += 1
        doc.pages.append(Page(number=i + 1, text=text, source="ocr"))
    return doc


def load_folder(folder: Path, cfg: Config, llm: LLM | None = None) -> list[Document]:
    pdfs = sorted(p for p in folder.rglob("*.pdf") if not p.name.startswith("~$"))
    return [load_pdf(p, cfg, llm) for p in pdfs]
