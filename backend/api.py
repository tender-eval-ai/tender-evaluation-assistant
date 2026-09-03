"""FastAPI backend: the evaluation pipeline as a project-based service.

Project lifecycle (mirrors the CLI checkpoints, which stay human-editable):

    POST /projects                          create a project
    POST /projects/{id}/tender              upload tender document PDFs
    POST /projects/{id}/bids/{tenderer}     upload one tenderer's offer PDFs
    GET/PUT /projects/{id}/rubric           review / edit the rubric  (human checkpoint)
    POST /projects/{id}/run                 orchestrated run (LangGraph): derive rubric
                                            -> PAUSE -> extract bids (parallel, verified,
                                            evidence-searched) -> PAUSE -> evaluate, report
    POST /projects/{id}/resume              continue past a pause (edits made via the PUT
                                            endpoints while paused are picked up)
    GET  /projects/{id}/graph               pending checkpoint, progress, corrections
    POST /projects/{id}/evaluate            re-evaluate from the stored extractions
                                            (deterministic; no LLM)
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

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import Config, load_dotenv
from app.evaluate import evaluate
from app.graph import (build_graph, graph_config, initial_state, pending_checkpoint,
                       pending_from_snapshot, resume as graph_resume)
from app.ingest import render_page_png
from app.report import render_all
from app.schemas import BidExtraction, Rubric

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
PROJECTS = DATA_DIR / "projects"
API_KEY = os.environ.get("API_KEY", "")
# Server-side folder imports: case folders placed here (host ./inbox, mounted
# read-only in Docker) can be imported into a project with one click.
INBOX_DIR = Path(os.environ.get("INBOX_DIR", "inbox"))

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


def require_key_or_query(x_api_key: str | None = Header(default=None),
                         key: str | None = None) -> None:
    """Evidence page images are also opened as plain browser links (new tab), which
    cannot send headers — those endpoints accept the key as ?key=… too."""
    if API_KEY and x_api_key != API_KEY and key != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key header")


media = APIRouter(dependencies=[Depends(require_key_or_query)])


# ---------------------------------------------------------------- helpers

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, obj) -> None:
    """Atomic write (temp file + rename): status.json is rewritten on every progress
    line by background jobs while the UI/tests poll it — a reader must never see a
    half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


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
              file: str | None, highlight: str | None = None) -> Response:
    """Rendered PNG of one page of a PDF in pdf_dir — the evidence behind a citation.
    With `highlight`, the quoted text is marked on the page (text-layer pages only)."""
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
    hl_tag = f"__{hashlib.sha1(highlight.encode()).hexdigest()[:10]}" if highlight else ""
    cached = cache / f"{cache_tag}__{target.stem}__{page}{hl_tag}.png"
    if not cached.is_file():
        try:
            cached.write_bytes(render_page_png(target, page - 1, scale=1.5,
                                               highlight=highlight))
        except Exception as err:
            raise HTTPException(400, f"cannot render page {page} of {target.name}: {err}")
    return Response(content=cached.read_bytes(), media_type="image/png")


@media.get("/projects/{pid}/bids/{tenderer}/page")
def bid_page_image(pid: str, tenderer: str, page: int = 1, file: str | None = None,
                   highlight: str | None = None) -> Response:
    pdir = _project_dir(pid)
    safe = _safe_name(tenderer)
    return _page_png(pdir, pdir / "bids" / safe, safe, page, file, highlight)


@media.get("/projects/{pid}/tender/page")
def tender_page_image(pid: str, page: int = 1, file: str | None = None,
                      highlight: str | None = None) -> Response:
    """Evidence page for rubric source citations."""
    pdir = _project_dir(pid)
    return _page_png(pdir, pdir / "tender", "tender", page, file, highlight)


def _bidder_names(pdir: Path) -> set[str]:
    uploaded = {p.name for p in (pdir / "bids").iterdir() if p.is_dir()}
    extracted = {p.stem for p in (pdir / "work" / "bids").glob("*.json")}
    return uploaded | extracted


def _require_rubric(pdir: Path) -> Path:
    rubric_path = pdir / "work" / "rubric.json"
    if not rubric_path.is_file():
        raise HTTPException(400, "derive (and review) the rubric first")
    return rubric_path


def _stored_extractions(pdir: Path) -> list[BidExtraction]:
    """Every bidder's stored extraction (the graph's output, possibly human-corrected)."""
    names = sorted(_bidder_names(pdir))
    missing = [n for n in names if not (pdir / "work" / "bids" / f"{n}.json").is_file()]
    if missing:
        raise HTTPException(400, f"no extraction yet for: {', '.join(missing)} — start the "
                                 "orchestrated run (POST /run) first")
    return [BidExtraction.model_validate(_read_json(pdir / "work" / "bids" / f"{n}.json"))
            for n in names]


# ---------------------------------------------------------------- orchestrated run (graph)

WAITING_DETAIL = {
    "rubric": "waiting: confirm the rubric — review/edit it, then Continue",
    "review": "waiting: review the extractions — correct any, then Continue",
}


def _graph_db(pdir: Path) -> str:
    (pdir / "work").mkdir(parents=True, exist_ok=True)
    return str(pdir / "work" / "graph.sqlite")


def _graph_snapshot(pdir: Path, pid: str):
    """State of the project's graph thread (None if it never ran)."""
    if not (pdir / "work" / "graph.sqlite").is_file():
        return None
    cfg = _make_cfg(pdir)
    with SqliteSaver.from_conn_string(_graph_db(pdir)) as saver:
        graph = build_graph(cfg, None, checkpointer=saver, interactive=True, log=lambda m: None)
        return graph.get_state(graph_config(cfg, pid))


def _graph_job(pid: str, pdir: Path, start: bool, payload: dict | None = None) -> None:
    """Run the graph in the background until the next human checkpoint or the end."""
    def job():
        from app.llm import LLM
        cfg = _make_cfg(pdir)
        llm = LLM(cfg)
        with SqliteSaver.from_conn_string(_graph_db(pdir)) as saver:
            graph = build_graph(cfg, llm, checkpointer=saver, interactive=True,
                                log=lambda m: _set_status(pdir, "running", m))
            if start:
                state = graph.invoke(initial_state(pdir / "tender", pdir / "bids", pdir / "work"),
                                     graph_config(cfg, pid))
            else:
                state = graph_resume(graph, cfg, pid, payload)
        pending = pending_checkpoint(state)
        if pending:
            _set_status(pdir, "waiting", WAITING_DETAIL[pending["checkpoint"]])
        else:
            _set_status(pdir, "done", "evaluation complete — reports ready")

    _start_job(pid, pdir, job, "starting the orchestrated run" if start else "continuing the run")


@api.post("/projects/{pid}/run")
def run_project(pid: str) -> dict:
    pdir = _project_dir(pid)
    if not list((pdir / "tender").glob("*.pdf")) and not (pdir / "work" / "rubric.json").is_file():
        raise HTTPException(400, "upload tender documents first")
    if pending_from_snapshot(_graph_snapshot(pdir, pid)):
        raise HTTPException(409, "the run is paused at a human checkpoint — use /resume")
    _graph_job(pid, pdir, start=True)
    return {"started": True}


class ResumeRequest(BaseModel):
    rubric: dict | None = None
    extractions: dict[str, dict] | None = None


@api.post("/projects/{pid}/resume")
def resume_project(pid: str, req: ResumeRequest | None = None) -> dict:
    pdir = _project_dir(pid)
    pending = pending_from_snapshot(_graph_snapshot(pdir, pid))
    if not pending:
        raise HTTPException(409, "nothing to resume — the run is not paused")
    payload = {k: v for k, v in (req.model_dump() if req else {}).items() if v is not None}
    _graph_job(pid, pdir, start=False, payload=payload)
    return {"resumed": pending["checkpoint"]}


@api.get("/projects/{pid}/graph")
def graph_state(pid: str) -> dict:
    pdir = _project_dir(pid)
    snap = _graph_snapshot(pdir, pid)
    pending = pending_from_snapshot(snap)
    values = (snap.values if snap else None) or {}
    return {"ran": snap is not None, "pending": pending["checkpoint"] if pending else None,
            "progress": values.get("progress", []), "corrected": values.get("corrected", []),
            "next": list(snap.next) if snap else []}


@api.get("/projects/{pid}/bids/{tenderer}/agent")
def agent_trace(pid: str, tenderer: str) -> dict:
    """The evidence-search agent's step trace for one bid (404 if it never ran)."""
    path = _project_dir(pid) / "work" / "agent" / f"{_safe_name(tenderer)}.json"
    if not path.is_file():
        raise HTTPException(404, f"no evidence-search trace for '{tenderer}'")
    return _read_json(path)


@api.post("/projects/{pid}/evaluate")
def run_evaluation(pid: str) -> dict:
    pdir = _project_dir(pid)
    rubric_path = _require_rubric(pdir)
    if not _bidder_names(pdir):
        raise HTTPException(400, "upload at least one bid first")

    extractions = _stored_extractions(pdir)

    def job():
        rubric = Rubric.model_validate(_read_json(rubric_path))
        _set_status(pdir, "running", "evaluating (deterministic) and rendering reports")
        result = evaluate(rubric, extractions)
        _write_json(pdir / "work" / "evaluation.json", result.model_dump(mode="json"))
        render_all(result, pdir / "work" / "reports")
        _set_status(pdir, "done", "evaluation complete — reports ready")

    _start_job(pid, pdir, job, "evaluating from stored extractions")
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
app.include_router(media)
