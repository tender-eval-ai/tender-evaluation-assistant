"""Projects: create, list, inspect, delete; PDF uploads; one-click imports from the inbox."""
from __future__ import annotations

import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend import deps
from backend.schemas_api import Project
from backend.times import when

router = APIRouter(dependencies=[Depends(deps.require_key)])


class NewProject(BaseModel):
    name: str
    # Kept for older clients: `data_class` below is what the gateway keys on.
    synthetic: bool = False
    # The class the LLM gateway keys its endpoint allowlist on (docs/api_contract.md).
    # Derived from `synthetic` when absent, so today's clients keep working.
    data_class: Literal["synthetic", "redacted_sample", "confidential"] | None = None


def _project(meta: dict, **detail) -> Project:
    """meta.json as the contract's Project; projects created before data classes existed
    derive theirs from the synthetic flag."""
    data_class = meta.get("data_class") or ("synthetic" if meta.get("synthetic") else "confidential")
    status = dict(detail.pop("status", None) or {})
    status["updated"] = when(status.get("updated"))
    return Project.model_validate({**meta, "data_class": data_class, "created": when(meta.get("created")), "status": status, **detail})


@router.post("/projects")
def create_project(req: NewProject) -> Project:
    slug = re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")[:40] or "project"
    pid = f"{slug}-{secrets.token_hex(3)}"
    pdir = deps.PROJECTS / pid
    (pdir / "tender").mkdir(parents=True)
    (pdir / "bids").mkdir()
    (pdir / "work").mkdir()
    data_class = req.data_class or ("synthetic" if req.synthetic else "confidential")
    synthetic = data_class == "synthetic"
    deps._write_json(pdir / "meta.json", {"id": pid, "name": req.name, "created": time.time(),
                                          "synthetic": synthetic, "data_class": data_class})
    deps._set_status(pdir, "idle")
    return _project(deps._read_json(pdir / "meta.json"), status=deps._get_status(pdir))


@router.get("/projects")
def list_projects() -> list[Project]:
    out = []
    if deps.PROJECTS.is_dir():
        for meta_path in sorted(deps.PROJECTS.glob("*/meta.json")):
            out.append(_project(deps._read_json(meta_path), status=deps._get_status(meta_path.parent)))
    return out


@router.get("/projects/{pid}")
def get_project(pid: str) -> Project:
    pdir = deps._project_dir(pid)
    return _project(
        deps._read_json(pdir / "meta.json"),
        status=deps._get_status(pdir),
        tender_files=sorted(p.name for p in (pdir / "tender").glob("*.pdf")),
        bidders=sorted(p.name for p in (pdir / "bids").iterdir() if p.is_dir()),
    )


@router.delete("/projects/{pid}")
def delete_project(pid: str) -> dict:
    shutil.rmtree(deps._project_dir(pid))
    return {"deleted": pid}


# ---------------------------------------------------------------- uploads

@router.post("/projects/{pid}/tender")
async def upload_tender(pid: str, files: list[UploadFile] = File(...)) -> dict:
    saved = await deps._save_pdfs(files, deps._project_dir(pid) / "tender")
    return {"saved": saved}


@router.post("/projects/{pid}/bids/{tenderer}")
async def upload_bid(pid: str, tenderer: str, files: list[UploadFile] = File(...)) -> dict:
    saved = await deps._save_pdfs(files, deps._project_dir(pid) / "bids" / deps._safe_name(tenderer))
    return {"saved": saved}


# ---------------------------------------------------------------- server-folder import

def _pdfs_in(folder: Path) -> list[Path]:
    """Same rule as app.ingest.load_folder (recursive, Office lock files skipped), so
    what the UI lists is what the pipeline reads."""
    return sorted(p for p in folder.rglob("*.pdf") if not p.name.startswith("~$"))


@router.get("/inbox")
def list_inbox() -> list[dict]:
    """Case folders available for one-click import (host ./inbox; compose mounts the
    synthetic tender there too). Convention: <case>/tender/*.pdf + <case>/bids/<tenderer>/."""
    if not deps.INBOX_DIR.is_dir():
        return []
    out = []
    for d in sorted(deps.INBOX_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        bids_dir = d / "bids"
        bidders = sorted(b.name for b in bids_dir.iterdir() if b.is_dir()) \
            if bids_dir.is_dir() else []
        entry = {
            "name": d.name,
            "tender_pdfs": len(_pdfs_in(d / "tender")) if (d / "tender").is_dir() else 0,
            "bidders": bidders,
            "loose_pdfs": len(_pdfs_in(d)),
        }
        if entry["tender_pdfs"] or entry["bidders"] or entry["loose_pdfs"]:
            out.append(entry)
    return out


class ImportRequest(BaseModel):
    path: str
    kind: Literal["case", "tender", "bids"] = "case"


def _copy_pdfs(src: Path, dest: Path) -> int:
    pdfs = _pdfs_in(src)
    if pdfs:
        dest.mkdir(parents=True, exist_ok=True)
        for pdf in pdfs:
            shutil.copy2(pdf, dest / pdf.name)
    return len(pdfs)


@router.post("/projects/{pid}/import")
def import_from_inbox(pid: str, req: ImportRequest) -> dict:
    """Import a whole folder from the inbox: kind 'case' expects tender/ + bids/
    subfolders; 'tender' copies a folder of PDFs as tender documents; 'bids' treats
    each subfolder (or loose PDF) as one tenderer."""
    pdir = deps._project_dir(pid)
    src = (deps.INBOX_DIR / req.path).resolve()
    if not src.is_dir() or not src.is_relative_to(deps.INBOX_DIR.resolve()):
        raise HTTPException(404, f"inbox folder '{req.path}' not found")

    tender_count, bidders = 0, {}

    def import_bids(bids_src: Path) -> None:
        for entry in sorted(bids_src.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                n = _copy_pdfs(entry, pdir / "bids" / deps._safe_name(entry.name))
                if n:
                    bidders[entry.name] = n
            elif entry.suffix.lower() == ".pdf" and not entry.name.startswith("~$"):
                dest = pdir / "bids" / deps._safe_name(entry.stem)
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, dest / entry.name)
                bidders[entry.stem] = 1

    if req.kind == "tender":
        tender_count = _copy_pdfs(src, pdir / "tender")
    elif req.kind == "bids":
        import_bids(src)
    else:  # case
        if (src / "tender").is_dir():
            tender_count = _copy_pdfs(src / "tender", pdir / "tender")
        if (src / "bids").is_dir():
            import_bids(src / "bids")
        if not tender_count and not bidders:
            raise HTTPException(
                400, f"'{req.path}' has no tender/ or bids/ subfolder with PDFs — "
                     "use kind='tender' or kind='bids' to import a flat folder")

    return {"tender_pdfs": tender_count, "bidders": bidders}
