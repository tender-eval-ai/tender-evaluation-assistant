"""Dependency-free generator of simple text-layer PDFs, for tests and demo fixtures."""
from __future__ import annotations

from pathlib import Path

LINES_PER_PAGE = 48


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Width/height from a baseline JPEG's SOF marker (fallback 1x1)."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return 1, 1


def make_text_pdf(path: Path, text: str | list[str],
                  images: dict[int, bytes] | None = None) -> None:
    """Write a minimal multi-page PDF whose text layer extracts cleanly with pypdf.
    `images` optionally embeds a JPEG on 0-based page indices — those pages look like
    scans (image XObject, little/no text), for testing the per-page OCR routing."""
    lines = text.splitlines() if isinstance(text, str) else list(text)
    page_chunks = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[""]]
    images = images or {}
    n = len(page_chunks)
    page_ids, next_id = [], 3
    for i in range(n):  # page + content (+ image) objects, ids assigned sequentially
        page_ids.append(next_id)
        next_id += 3 if i in images else 2
    font_id = next_id

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % pid for pid in page_ids), n),
    ]
    for i, chunk in enumerate(page_chunks):
        content = "BT /F1 11 Tf 14 TL 72 760 Td " + " T* ".join(
            f"({_escape(line)}) Tj" for line in chunk) + " ET"
        xobject = b""
        if i in images:
            content += " q 400 0 0 500 100 150 cm /Im1 Do Q"
            xobject = b" /XObject << /Im1 %d 0 R >>" % (page_ids[i] + 2)
        raw = content.encode("latin-1", errors="replace")
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >>%s >> >>"
            % (page_ids[i] + 1, font_id, xobject))
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(raw), raw))
        if i in images:
            jpeg = images[i]
            w, h = _jpeg_size(jpeg)
            objects.append(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                b"/Length %d >>\nstream\n%s\nendstream" % (w, h, len(jpeg), jpeg))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref_at)
    Path(path).write_bytes(bytes(out))
