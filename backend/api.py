"""FastAPI backend: the evaluation pipeline as a project-based service.

Project lifecycle (mirrors the CLI checkpoints, which stay human-editable):

    POST /projects                          create a project
    POST /projects/{id}/tender              upload tender document PDFs
    POST /projects/{id}/bids/{tenderer}     upload one tenderer's offer PDFs
    POST /projects/{id}/rubric/derive       background job -> work/rubric.json
    GET/PUT /projects/{id}/rubric           review / edit the rubric  (human checkpoint)
    POST /projects/{id}/evaluate            background job: extract missing bids,
                                            evaluate deterministically, render reports
    GET  /projects/{id}/status              poll background job state
    GET  /projects/{id}/evaluation          full EvaluationResult JSON
    GET  /projects/{id}/reports[/{name}]    list / download the Word deliverables
    PUT  /projects/{id}/bids/{tenderer}/extraction   inject or correct an extraction

Data layout under $DATA_DIR/projects/<id>/:
    meta.json  tender/*.pdf  bids/<tenderer>/*.pdf
    work/{rubric.json, bids/<tenderer>.json, evaluation.json, reports/*.docx, cache/}

Auth: if the API_KEY env var is set, every request (except /health) must send it in the
X-API-Key header. Always set it on any machine that is not localhost-only.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.bid_extract import extract_bid
from app.config import Config, load_dotenv
from app.evaluate import evaluate
from app.ingest import load_folder, render_page_png
from app.report import render_all
from app.rubric import derive_rubric
from app.schemas import BidExtraction, Rubric
from app.verify import verify_extraction

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
PROJECTS = DATA_DIR / "projects"
API_KEY = os.environ.get("API_KEY", "")
# Server-side folder imports: case folders placed here (host ./inbox, mounted
# read-only in Docker) can be imported into a project with one click.
INBOX_DIR = Path(os.environ.get("INBOX_DIR", "inbox"))
# Fresh bid extractions run concurrently (cloud endpoints benefit; a local Ollama
# just queues them). 1 disables parallelism.
MAX_PARALLEL_BIDS = max(1, int(os.environ.get("MAX_PARALLEL_BIDS", "4")))

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key header")


app = FastAPI(title="Tender Evaluation Assistant API", version="0.1.0")

# The UI's folder picker uploads from the browser straight to this API (the Streamlit
# server never proxies the files), which is a cross-origin request from the UI's port.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(dependencies=[Depends(require_key)])


# ---------------------------------------------------------------- helpers

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def _project_dir(pid: str) -> Path:
    pdir = PROJECTS / pid
    if not pdir.is_dir():
        raise HTTPException(404, f"project '{pid}' not found")
    return pdir


def _set_status(pdir: Path, state: str, detail: str = "") -> None:
    _write_json(pdir / "status.json", {"state": state, "detail": detail, "updated": time.time()})


def _get_status(pdir: Path) -> dict:
    path = pdir / "status.json"
    return _read_json(path) if path.is_file() else {"state": "idle", "detail": ""}


def _make_cfg(pdir: Path) -> Config:
    cfg = Config()
    cfg.cache_dir = pdir / "work" / "cache"
    cfg.max_ocr_pages = int(os.environ.get("MAX_OCR_PAGES", cfg.max_ocr_pages))
    return cfg


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name).strip()
    if not cleaned:
        raise HTTPException(400, f"unusable filename: {name!r}")
    return cleaned


async def _save_pdfs(files: list[UploadFile], dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = _safe_name(f.filename or "")
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, f"only PDF uploads are accepted, got: {name}")
        (dest / name).write_bytes(await f.read())
        saved.append(name)
    return saved


# One background job per project at a time.
_jobs_lock = threading.Lock()
_running: set[str] = set()


def _start_job(pid: str, pdir: Path, target, detail: str = "queued") -> None:
    with _jobs_lock:
        if pid in _running:
            raise HTTPException(409, "a job is already running for this project")
        _running.add(pid)
    # Status must flip to "running" before the endpoint returns, or a client polling
    # right after the POST could see the previous job's terminal state and stop early.
    _set_status(pdir, "running", detail)

    def wrapper():
        try:
            target()
        except Exception as err:  # surface anything to the status file
            _set_status(pdir, "error", f"{type(err).__name__}: {err}")
        finally:
            with _jobs_lock:
                _running.discard(pid)

    threading.Thread(target=wrapper, daemon=True).start()


# ---------------------------------------------------------------- health & projects

@app.get("/health")
def health() -> dict:
    cfg = Config()
    return {"ok": True, "text_model": cfg.text_model, "vision_model": cfg.vision_model,
            "auth_required": bool(API_KEY)}


class NewProject(BaseModel):
    name: str


@api.post("/projects")
def create_project(req: NewProject) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", req.name.lower()).strip("-")[:40] or "project"
    pid = f"{slug}-{secrets.token_hex(3)}"
    pdir = PROJECTS / pid
    (pdir / "tender").mkdir(parents=True)
    (pdir / "bids").mkdir()
    (pdir / "work" / "bids").mkdir(parents=True)
    _write_json(pdir / "meta.json", {"id": pid, "name": req.name, "created": time.time()})
    _set_status(pdir, "idle")
    return {"id": pid, "name": req.name}


@api.get("/projects")
def list_projects() -> list[dict]:
    out = []
    if PROJECTS.is_dir():
        for meta_path in sorted(PROJECTS.glob("*/meta.json")):
            meta = _read_json(meta_path)
            meta["status"] = _get_status(meta_path.parent)
            out.append(meta)
    return out


@api.get("/projects/{pid}")
def get_project(pid: str) -> dict:
    pdir = _project_dir(pid)
    work = pdir / "work"
    return {
        **_read_json(pdir / "meta.json"),
        "status": _get_status(pdir),
        "tender_files": sorted(p.name for p in (pdir / "tender").glob("*.pdf")),
        "bidders": sorted(p.name for p in (pdir / "bids").iterdir() if p.is_dir()),
        "extracted": sorted(p.stem for p in (work / "bids").glob("*.json")),
        "has_rubric": (work / "rubric.json").is_file(),
        "has_evaluation": (work / "evaluation.json").is_file(),
        "reports": sorted(p.name for p in (work / "reports").glob("*.docx"))
        if (work / "reports").is_dir() else [],
    }


@api.delete("/projects/{pid}")
def delete_project(pid: str) -> dict:
    pdir = _project_dir(pid)
    with _jobs_lock:
        if pid in _running:
            raise HTTPException(409, "a job is running for this project; wait for it to finish")
    shutil.rmtree(pdir)
    return {"deleted": pid}


# ---------------------------------------------------------------- uploads

@api.post("/projects/{pid}/tender")
async def upload_tender(pid: str, files: list[UploadFile] = File(...)) -> dict:
    saved = await _save_pdfs(files, _project_dir(pid) / "tender")
    return {"saved": saved}


@api.post("/projects/{pid}/bids/{tenderer}")
async def upload_bid(pid: str, tenderer: str, files: list[UploadFile] = File(...)) -> dict:
    saved = await _save_pdfs(files, _project_dir(pid) / "bids" / _safe_name(tenderer))
    return {"saved": saved}


# ---------------------------------------------------------------- server-folder import

def _pdfs_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.pdf") if not p.name.startswith("~$"))


@api.get("/inbox")
def list_inbox() -> list[dict]:
    """Case folders available for one-click import (host ./inbox; demo_case is
    mounted there too). Convention: <case>/tender/*.pdf + <case>/bids/<tenderer>/."""
    if not INBOX_DIR.is_dir():
        return []
    out = []
    for d in sorted(INBOX_DIR.iterdir()):
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


@api.post("/projects/{pid}/import")
def import_from_inbox(pid: str, req: ImportRequest) -> dict:
    """Import a whole folder from the inbox: kind 'case' expects tender/ + bids/
    subfolders; 'tender' copies a folder of PDFs as tender documents; 'bids' treats
    each subfolder (or loose PDF) as one tenderer."""
    pdir = _project_dir(pid)
    src = (INBOX_DIR / req.path).resolve()
    if not src.is_dir() or not src.is_relative_to(INBOX_DIR.resolve()):
        raise HTTPException(404, f"inbox folder '{req.path}' not found")

    tender_count, bidders = 0, {}

    def import_bids(bids_src: Path) -> None:
        for entry in sorted(bids_src.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                n = _copy_pdfs(entry, pdir / "bids" / _safe_name(entry.name))
                if n:
                    bidders[entry.name] = n
            elif entry.suffix.lower() == ".pdf" and not entry.name.startswith("~$"):
                dest = pdir / "bids" / _safe_name(entry.stem)
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


# ---------------------------------------------------------------- rubric

@api.post("/projects/{pid}/rubric/derive")
def derive(pid: str) -> dict:
    pdir = _project_dir(pid)
    if not list((pdir / "tender").glob("*.pdf")):
        raise HTTPException(400, "upload tender documents first")

    def job():
        from app.llm import LLM
        _set_status(pdir, "running", "deriving evaluation rubric from tender documents")
        cfg = _make_cfg(pdir)
        llm = LLM(cfg)
        docs = load_folder(pdir / "tender", cfg, llm)
        rubric = derive_rubric(docs, cfg, llm)
        _write_json(pdir / "work" / "rubric.json", rubric.model_dump(mode="json"))
        _set_status(pdir, "done", "rubric derived — review and edit it before evaluating")

    _start_job(pid, pdir, job, "deriving evaluation rubric from tender documents")
    return {"started": True}


@api.get("/projects/{pid}/rubric")
def get_rubric(pid: str) -> dict:
    path = _project_dir(pid) / "work" / "rubric.json"
    if not path.is_file():
        raise HTTPException(404, "no rubric yet — derive it or PUT one")
    return _read_json(path)


@api.put("/projects/{pid}/rubric")
def put_rubric(pid: str, rubric: Rubric) -> dict:
    _write_json(_project_dir(pid) / "work" / "rubric.json", rubric.model_dump(mode="json"))
    return {"saved": True}


# ---------------------------------------------------------------- extraction & evaluation

@api.put("/projects/{pid}/bids/{tenderer}/extraction")
def put_extraction(pid: str, tenderer: str, extraction: BidExtraction) -> dict:
    """Inject or human-correct one tenderer's extraction; skipped by the LLM step."""
    pdir = _project_dir(pid)
    extraction.tenderer = tenderer
    _write_json(pdir / "work" / "bids" / f"{_safe_name(tenderer)}.json",
                extraction.model_dump(mode="json"))
    return {"saved": True}


@api.get("/projects/{pid}/bids/{tenderer}/extraction")
def get_extraction(pid: str, tenderer: str) -> dict:
    path = _project_dir(pid) / "work" / "bids" / f"{_safe_name(tenderer)}.json"
    if not path.is_file():
        raise HTTPException(404, f"no extraction for '{tenderer}' yet")
    return _read_json(path)


def _page_png(pdir: Path, pdf_dir: Path, cache_tag: str, page: int,
              file: str | None) -> Response:
    """Rendered PNG of one page of a PDF in pdf_dir — the evidence behind a citation."""
    pdfs = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.is_dir() else []
    if file:
        target = pdf_dir / _safe_name(file)
        if not target.is_file():
            raise HTTPException(404, f"file '{file}' not found")
    elif pdfs:
        target = pdfs[0]
    else:
        raise HTTPException(404, "no PDFs uploaded")
    cache = pdir / "work" / "cache" / "pages"
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / f"{cache_tag}__{target.stem}__{page}.png"
    if not cached.is_file():
        try:
            cached.write_bytes(render_page_png(target, page - 1, scale=1.5))
        except Exception as err:
            raise HTTPException(400, f"cannot render page {page} of {target.name}: {err}")
    return Response(content=cached.read_bytes(), media_type="image/png")


@api.get("/projects/{pid}/bids/{tenderer}/page")
def bid_page_image(pid: str, tenderer: str, page: int = 1, file: str | None = None) -> Response:
    pdir = _project_dir(pid)
    safe = _safe_name(tenderer)
    return _page_png(pdir, pdir / "bids" / safe, safe, page, file)


@api.get("/projects/{pid}/tender/page")
def tender_page_image(pid: str, page: int = 1, file: str | None = None) -> Response:
    """Evidence page for rubric source citations."""
    pdir = _project_dir(pid)
    return _page_png(pdir, pdir / "tender", "tender", page, file)


def _bidder_names(pdir: Path) -> set[str]:
    uploaded = {p.name for p in (pdir / "bids").iterdir() if p.is_dir()}
    extracted = {p.stem for p in (pdir / "work" / "bids").glob("*.json")}
    return uploaded | extracted


def _require_rubric(pdir: Path) -> Path:
    rubric_path = pdir / "work" / "rubric.json"
    if not rubric_path.is_file():
        raise HTTPException(400, "derive (and review) the rubric first")
    return rubric_path


def _extract_missing(pdir: Path, rubric: Rubric, cfg: Config) -> list[BidExtraction]:
    """Extract (and adversarially verify) bids that have no stored extraction; stored
    ones — including human corrections — are used as-is and never re-verified. Fresh
    extractions run in parallel, MAX_PARALLEL_BIDS at a time."""
    names = sorted(_bidder_names(pdir))
    results: dict[str, BidExtraction] = {}
    todo: list[str] = []
    for name in names:
        ext_path = pdir / "work" / "bids" / f"{name}.json"
        if ext_path.is_file():
            results[name] = BidExtraction.model_validate(_read_json(ext_path))
        else:
            todo.append(name)
    if not todo:
        return [results[n] for n in names]

    from app.llm import LLM
    llm = LLM(cfg)
    progress_lock = threading.Lock()
    done = 0

    def extract_one(name: str) -> None:
        nonlocal done
        docs = load_folder(pdir / "bids" / name, cfg, llm)
        extraction = extract_bid(name, docs, rubric, cfg, llm)
        if cfg.verify_findings:
            extraction, _ = verify_extraction(extraction, docs, rubric, cfg, llm)
        _write_json(pdir / "work" / "bids" / f"{name}.json",
                    extraction.model_dump(mode="json"))
        results[name] = extraction
        with progress_lock:
            done += 1
            _set_status(pdir, "running",
                        f"extracting bids: {done}/{len(todo)} finished (last: {name})")

    _set_status(pdir, "running",
                f"extracting {len(todo)} bid(s), up to {MAX_PARALLEL_BIDS} in parallel")
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_BIDS, len(todo))) as pool:
        futures = {pool.submit(extract_one, n): n for n in todo}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as err:
                pool.shutdown(wait=False, cancel_futures=True)
                raise RuntimeError(f"extracting {futures[fut]}: {err}") from err
    return [results[n] for n in names]


@api.post("/projects/{pid}/extract")
def run_extract(pid: str) -> dict:
    """Extract missing bids only (no evaluation) — feeds the human review step."""
    pdir = _project_dir(pid)
    rubric_path = _require_rubric(pdir)
    if not _bidder_names(pdir):
        raise HTTPException(400, "upload at least one bid first")

    def job():
        rubric = Rubric.model_validate(_read_json(rubric_path))
        _extract_missing(pdir, rubric, _make_cfg(pdir))
        _set_status(pdir, "done", "extractions ready for review")

    _start_job(pid, pdir, job, "starting bid extraction")
    return {"started": True}


@api.post("/projects/{pid}/evaluate")
def run_evaluation(pid: str) -> dict:
    pdir = _project_dir(pid)
    rubric_path = _require_rubric(pdir)
    if not _bidder_names(pdir):
        raise HTTPException(400, "upload at least one bid first")

    def job():
        rubric = Rubric.model_validate(_read_json(rubric_path))
        extractions = _extract_missing(pdir, rubric, _make_cfg(pdir))
        _set_status(pdir, "running", "evaluating (deterministic) and rendering reports")
        result = evaluate(rubric, extractions)
        _write_json(pdir / "work" / "evaluation.json", result.model_dump(mode="json"))
        render_all(result, pdir / "work" / "reports")
        _set_status(pdir, "done", "evaluation complete — reports ready")

    _start_job(pid, pdir, job, "starting bid extraction")
    return {"started": True}


@api.get("/projects/{pid}/status")
def status(pid: str) -> dict:
    return _get_status(_project_dir(pid))


@api.get("/projects/{pid}/evaluation")
def get_evaluation(pid: str) -> dict:
    path = _project_dir(pid) / "work" / "evaluation.json"
    if not path.is_file():
        raise HTTPException(404, "no evaluation yet")
    return _read_json(path)


# ---------------------------------------------------------------- reports

@api.get("/projects/{pid}/reports")
def list_reports(pid: str) -> list[str]:
    reports = _project_dir(pid) / "work" / "reports"
    return sorted(p.name for p in reports.glob("*.docx")) if reports.is_dir() else []


@api.get("/projects/{pid}/reports/{name}")
def download_report(pid: str, name: str) -> FileResponse:
    path = _project_dir(pid) / "work" / "reports" / _safe_name(name)
    if not path.is_file():
        raise HTTPException(404, f"report '{name}' not found")
    return FileResponse(path, media_type=DOCX_MIME, filename=path.name)


app.include_router(api)
