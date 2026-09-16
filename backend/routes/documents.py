"""Evidence page images: the rendered page behind a citation, optionally highlighted.
Opened as plain browser links too, so this router also accepts the key as ?key=…"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.ingest import render_page_png
from backend import deps

router = APIRouter(dependencies=[Depends(deps.require_key_or_query)])


def _page_png(pdir: Path, pdf_dir: Path, cache_tag: str, page: int,
              file: str | None, highlight: str | None = None) -> Response:
    """Rendered PNG of one page of a PDF in pdf_dir — the evidence behind a citation.
    With `highlight`, the quoted text is marked on the page (text-layer pages only)."""
    pdfs = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.is_dir() else []
    if file:
        target = pdf_dir / deps._safe_name(file)
        if not target.is_file():
            raise HTTPException(404, f"file '{file}' not found")
    elif pdfs:
        target = pdfs[0]
    else:
        raise HTTPException(404, "no PDFs uploaded")
    cache = pdir / "work" / "cache" / "pages"
    cache.mkdir(parents=True, exist_ok=True)
    hl_tag = f"__{hashlib.sha1(highlight.encode()).hexdigest()[:10]}" if highlight else ""
    cached = cache / f"{cache_tag}__{target.stem}__{page}{hl_tag}.png"
    if not cached.is_file():
        try:
            cached.write_bytes(render_page_png(target, page - 1, scale=1.5,
                                               highlight=highlight))
        except Exception as err:
            raise HTTPException(400, f"cannot render page {page} of {target.name}: {err}")
    return Response(content=cached.read_bytes(), media_type="image/png")


@router.get("/projects/{pid}/bids/{tenderer}/page")
def bid_page_image(pid: str, tenderer: str, page: int = 1, file: str | None = None,
                   highlight: str | None = None) -> Response:
    pdir = deps._project_dir(pid)
    safe = deps._safe_name(tenderer)
    return _page_png(pdir, pdir / "bids" / safe, safe, page, file, highlight)


@router.get("/projects/{pid}/tender/page")
def tender_page_image(pid: str, page: int = 1, file: str | None = None,
                      highlight: str | None = None) -> Response:
    """Evidence page for rubric source citations."""
    pdir = deps._project_dir(pid)
    return _page_png(pdir, pdir / "tender", "tender", page, file, highlight)
