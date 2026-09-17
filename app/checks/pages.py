"""V0: every page of an offer rendered to PNG once, under the project's work folder,
with no page cap. Pages are numbered in one sequence across the offer's files so the
later layers can refer to "page 13" whatever the file split."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from pypdf import PdfReader

from app.ingest import SCAN_THRESHOLD, _file_sha, render_page_png

SCALE = 1.5     # about 110 dpi: readable for a vision model, small enough to send six at a time
Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class PageRef:
    seq: int          # 1-based across the whole offer
    doc: str          # file name
    page: int         # 1-based within the file
    path: str         # the PNG
    has_text: bool    # a usable text layer (a digital page) or a scan


def render_pdf(pdf: Path, out_dir: Path, first_seq: int = 1, scale: float = SCALE,
               progress: Progress | None = None) -> list[PageRef]:
    reader = PdfReader(str(pdf))
    folder = out_dir / _file_sha(pdf)
    refs: list[PageRef] = []
    n = len(reader.pages)
    for i in range(n):
        png = folder / f"page_{i + 1:04d}.png"
        if not png.is_file():
            folder.mkdir(parents=True, exist_ok=True)
            tmp = png.with_name(f".{png.name}.{os.getpid()}.tmp")
            tmp.write_bytes(render_page_png(pdf, i, scale=scale))
            os.replace(tmp, png)
        has_text = len(reader.pages[i].extract_text() or "") >= SCAN_THRESHOLD
        refs.append(PageRef(first_seq + i, pdf.name, i + 1, str(png), has_text))
        if progress:
            progress(i + 1, n)
    return refs


def render_offer(bid_dir: Path, out_dir: Path, progress: Progress | None = None) -> list[PageRef]:
    """Every PDF of one tenderer's folder, in file-name order, numbered in one sequence."""
    pdfs = sorted(p for p in bid_dir.rglob("*.pdf") if not p.name.startswith("~$"))
    total = sum(len(PdfReader(str(p)).pages) for p in pdfs)
    refs: list[PageRef] = []
    for pdf in pdfs:
        done_before = len(refs)
        refs += render_pdf(pdf, out_dir, first_seq=len(refs) + 1,
                           progress=(lambda d, n: progress(done_before + d, total)) if progress else None)
    return refs


def read_png(ref: PageRef | dict) -> bytes:
    path = ref["path"] if isinstance(ref, dict) else ref.path
    return Path(path).read_bytes()


def as_dicts(refs: list[PageRef]) -> list[dict]:
    return [asdict(r) for r in refs]
