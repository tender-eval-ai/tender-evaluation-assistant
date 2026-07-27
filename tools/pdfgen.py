"""Dependency-free generator of simple text-layer PDFs, for tests and demo fixtures."""
from __future__ import annotations

from pathlib import Path

LINES_PER_PAGE = 48


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_text_pdf(path: Path, text: str | list[str]) -> None:
    """Write a minimal multi-page PDF whose text layer extracts cleanly with pypdf."""
    lines = text.splitlines() if isinstance(text, str) else list(text)
    page_chunks = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[""]]
    n = len(page_chunks)
    page_ids = [3 + 2 * i for i in range(n)]
    font_id = 3 + 2 * n

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % pid for pid in page_ids), n),
    ]
    for i, chunk in enumerate(page_chunks):
        content = "BT /F1 11 Tf 14 TL 72 760 Td " + " T* ".join(
            f"({_escape(line)}) Tj" for line in chunk) + " ET"
        raw = content.encode("latin-1", errors="replace")
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (page_ids[i] + 1, font_id))
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(raw), raw))
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
