"""The document viewer: the project's documents, their pages as V0 and V1 saw them,
and page images behind signed, short-lived URLs (the API key stays out of links)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pypdf import PdfReader

from app.checks.pages import render_pdf
from app.ingest import SCAN_THRESHOLD, render_page_png
from backend import deps, signing
from backend.errors import ApiError
from backend.schemas_api import Document, Page

router = APIRouter()
keyed = APIRouter(dependencies=[Depends(deps.require_key)])


@keyed.get("/projects/{pid}/documents")
def list_documents(pid: str) -> list[Document]:
    pdir = deps._project_dir(pid)
    data_class = deps.data_class_of(pdir)
    return [Document(doc_id=d["doc_id"], file=d["file"], kind=d["kind"], tenderer=d["tenderer"],
                     pages=len(PdfReader(str(d["path"])).pages), data_class=data_class) for d in deps.documents_of(pdir)]


def _labels_for(pid: str, doc: dict) -> dict[int, dict]:
    """V1's labels for a bid file from the tenderer's latest run, if any."""
    import os
    if doc["kind"] != "bid" or not os.environ.get("DATABASE_URL"):
        return {}
    store = deps.runner().store
    run = store.latest_run(pid, doc["tenderer"])
    if run is None:
        return {}
    data = store.steps(run["run_id"])["data"]
    return {lab["page"]: lab for lab in data.get("labels", []) if lab.get("doc") == doc["file"]}


@keyed.get("/projects/{pid}/documents/{doc_id}/pages")
def list_pages(pid: str, doc_id: str) -> list[Page]:
    pdir = deps._project_dir(pid)
    doc = deps.find_document(pdir, doc_id)
    labels = _labels_for(pid, doc)
    reader = PdfReader(str(doc["path"]))
    out = []
    for i, page in enumerate(reader.pages, start=1):
        lab = labels.get(i, {})
        out.append(Page(page=i, has_text=len(page.extract_text() or "") >= SCAN_THRESHOLD, label=lab.get("label"),
                        title=lab.get("title"), summary=lab.get("summary"), signed=lab.get("signed"),
                        has_table=lab.get("has_table"), image_url=signing.image_url(pid, doc_id, i)))
    return out


@router.get("/projects/{pid}/documents/{doc_id}/pages/{n}/image")
def page_image(pid: str, doc_id: str, n: int, exp: int | None = None, sig: str | None = None,
               highlight: str | None = None, x_api_key: str | None = Header(default=None)) -> Response:
    """A signed URL (from Page.image_url or a citation) or the API key opens it."""
    if not (signing.verify(pid, doc_id, n, exp, sig) or (deps.API_KEY and deps._key_ok(x_api_key))
            or (not deps.API_KEY and sig is None and exp is None)):
        raise ApiError(403, "forbidden", "the image link is invalid or has expired")
    pdir = deps._project_dir(pid)
    doc = deps.find_document(pdir, doc_id)
    if n < 1 or n > len(PdfReader(str(doc["path"])).pages):
        raise HTTPException(404, f"page {n} does not exist in {doc['file']}")
    if highlight:
        return Response(content=render_page_png(doc["path"], n - 1, scale=1.5, highlight=highlight), media_type="image/png")
    refs = render_pdf(doc["path"], pdir / "work" / "pages")          # V0's cache: rendered once, served many times
    return Response(content=open(refs[n - 1].path, "rb").read(), media_type="image/png")
