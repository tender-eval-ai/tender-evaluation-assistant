from dataclasses import dataclass
from pathlib import Path

import fitz

# Below this many characters of extracted text, treat a page as having no
# usable native text layer (empty/whitespace-only extraction, stray artifacts).
MIN_NATIVE_TEXT_CHARS = 20

# PDFs render at 72 DPI natively via PyMuPDF. Confirmed on real documents in this
# project that this is too low for reliable OCR - it silently dropped a price
# value that 300 DPI recovered correctly. This is a correctness fix, not quality.
OCR_RENDER_DPI = 300


@dataclass
class Page:
    source_file: str
    page_number: int
    has_native_text: bool
    native_text: str | None
    image_ref: str | None = None


def load_pdf(path: Path, image_output_dir: Path | None = None) -> list[Page]:
    pages = []
    doc = fitz.open(path)
    for index in range(len(doc)):
        text = doc[index].get_text().strip()
        has_native_text = len(text) >= MIN_NATIVE_TEXT_CHARS

        image_ref = None
        if not has_native_text and image_output_dir is not None:
            image_ref = _render_page_image(doc, index, path, image_output_dir)

        pages.append(
            Page(
                source_file=str(path),
                page_number=index + 1,
                has_native_text=has_native_text,
                native_text=text if has_native_text else None,
                image_ref=image_ref,
            )
        )
    doc.close()
    return pages


def load_document_set(folder: Path, image_output_dir: Path | None = None) -> list[Page]:
    # Recursive: a real vendor submission can split its files across sibling
    # subfolders (confirmed on Tender 3 - "商务标-Fee" and "技术标-Tech" each hold
    # part of the same one submission) rather than sitting flat in one folder.
    pages = []
    for pdf_path in sorted(Path(folder).rglob("*.pdf")):
        pages.extend(load_pdf(pdf_path, image_output_dir))
    return pages


def _render_page_image(doc: fitz.Document, index: int, source_path: Path, output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{source_path.stem}_p{index + 1}.png"
    zoom = OCR_RENDER_DPI / 72
    pixmap = doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pixmap.save(image_path)
    return str(image_path)
