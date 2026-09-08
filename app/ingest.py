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


def _highlight_rects(page, query: str) -> list[tuple[float, float, float, float]]:
    """Line rectangles (PDF points, bottom-left origin) of the first occurrence of
    `query` on the page. LLM quotes rarely match the PDF verbatim and pdfium search
    does not cross line breaks, so progressively shorter leading word-runs are tried.
    Scanned pages have no text layer — they simply return no rects."""
    import re
    words = re.sub(r"\s+", " ", query or "").strip().split(" ")
    if not words:
        return []
    textpage = page.get_textpage()
    for n in dict.fromkeys([len(words), 10, 6, 4, 3]):
        if n > len(words):
            continue
        needle = " ".join(words[:n])
        if len(needle) < 4:
            break
        match = textpage.search(needle, match_case=False).get_next()
        if match:
            index, count = match
            return [textpage.get_rect(i)
                    for i in range(textpage.count_rects(index, count))]
    return []


def render_page_png(path: Path, page_index: int, scale: float = 2.0,
                    highlight: str | None = None) -> bytes:
    """Rendered page PNG. If `highlight` text is found on the page (needs a text
    layer), its lines get a translucent yellow marker."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[page_index]
        pil = page.render(scale=scale).to_pil().convert("RGBA")
        rects = _highlight_rects(page, highlight) if highlight else []
        if rects:
            from PIL import Image, ImageDraw
            _, page_h = page.get_size()
            overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            for left, bottom, right, top in rects:
                box = ((left - 2) * scale, (page_h - top - 2) * scale,
                       (right + 2) * scale, (page_h - bottom + 2) * scale)
                draw.rectangle(box, fill=(255, 225, 0, 88),
                               outline=(255, 160, 0, 220), width=2)
            pil = Image.alpha_composite(pil, overlay)
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="PNG")
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


def _ocr_cache_file(path: Path, page_index: int, cfg: Config, sha: str | None = None) -> Path:
    return cfg.cache_dir / (sha or _file_sha(path)) / f"page_{page_index + 1:04d}.md"


def cached_ocr(path: Path, page_index: int, cfg: Config, sha: str | None = None) -> str | None:
    """A page's cached transcription, or None if it was never OCR'd."""
    cached = _ocr_cache_file(path, page_index, cfg, sha)
    return cached.read_text() if cached.is_file() else None


def ocr_single_page(path: Path, page_index: int, cfg: Config, llm: LLM) -> str:
    """OCR one page through the vision chain, with the per-page on-disk cache. Also
    used by the evidence-search agent to read pages beyond the initial OCR cap."""
    cached = _ocr_cache_file(path, page_index, cfg)
    if cached.is_file():
        return cached.read_text()
    text = llm.ocr_page(render_page_png(path, page_index))
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text)
    return text


def load_pdf(path: Path, cfg: Config, llm: LLM | None = None,
             cached_only: bool = False) -> Document:
    """Load a PDF as per-page text. The text-vs-scan decision is made PER PAGE: pages
    with a usable text layer are read directly, sparse pages that carry an image are
    OCR'd through the vision model (on-disk cache). So a digital document with a
    scanned annex, or a scan with an embedded OCR layer on some pages, both get the
    cheap path wherever possible. Imageless sparse pages in a text document (blank
    separators, short cover pages) keep their text — there is nothing more to read.
    At most cfg.max_ocr_pages pages per document are OCR'd; the rest are skipped.

    `cached_only` (the MCP server's mode) never calls the vision model: a page that
    would need OCR takes its cached transcription if the pipeline already produced
    one, otherwise it is marked `skipped` for on-demand `ocr_page`."""
    kind = classify_pdf(path)
    doc = Document(path=path, kind=kind)
    reader = PdfReader(str(path))

    if kind == "scanned" and llm is None and not cached_only:
        raise RuntimeError(f"{path.name} is a scanned PDF; OCR requires an LLM client.")

    ocr_used, sha = 0, None
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if len(text) >= SCAN_THRESHOLD:
            doc.pages.append(Page(number=i + 1, text=text, source="text"))
            continue
        if kind == "text" and ((llm is None and not cached_only) or not _page_has_image(page)):
            doc.pages.append(Page(number=i + 1, text=text, source="text"))
            continue
        if cached_only:
            sha = sha or _file_sha(path)
            cached = cached_ocr(path, i, cfg, sha)
            doc.pages.append(Page(number=i + 1, text=cached, source="ocr") if cached is not None
                             else Page(number=i + 1, text="", source="skipped"))
            continue
        if ocr_used >= cfg.max_ocr_pages:
            doc.pages.append(Page(number=i + 1, text="", source="skipped"))
            continue
        text = ocr_single_page(path, i, cfg, llm)
        ocr_used += 1
        doc.pages.append(Page(number=i + 1, text=text, source="ocr"))
    return doc


def load_folder(folder: Path, cfg: Config, llm: LLM | None = None,
                cached_only: bool = False) -> list[Document]:
    pdfs = sorted(p for p in folder.rglob("*.pdf") if not p.name.startswith("~$"))
    return [load_pdf(p, cfg, llm, cached_only=cached_only) for p in pdfs]
