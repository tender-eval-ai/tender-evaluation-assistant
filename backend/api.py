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
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.bid_extract import extract_bid
from app.config import Config, load_dotenv
from app.evaluate import evaluate
from app.ingest import load_folder
from app.report import render_all
from app.rubric import derive_rubric
from app.schemas import BidExtraction, Rubric

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
PROJECTS = DATA_DIR / "projects"
API_KEY = os.environ.get("API_KEY", "")

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key header")


app = FastAPI(title="Tender Evaluation Assistant API", version="0.1.0")
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


def _start_job(pid: str, pdir: Path, target) -> None:
    with _jobs_lock:
        if pid in _running:
            raise HTTPException(409, "a job is already running for this project")
        _running.add(pid)

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


# ---------------------------------------------------------------- uploads

@api.post("/projects/{pid}/tender")
async def upload_tender(pid: str, files: list[UploadFile] = File(...)) -> dict:
    saved = await _save_pdfs(files, _project_dir(pid) / "tender")
    return {"saved": saved}


@api.post("/projects/{pid}/bids/{tenderer}")
async def upload_bid(pid: str, tenderer: str, files: list[UploadFile] = File(...)) -> dict:
    saved = await _save_pdfs(files, _project_dir(pid) / "bids" / _safe_name(tenderer))
    return {"saved": saved}


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

    _start_job(pid, pdir, job)
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


@api.post("/projects/{pid}/evaluate")
def run_evaluation(pid: str) -> dict:
    pdir = _project_dir(pid)
    rubric_path = pdir / "work" / "rubric.json"
    if not rubric_path.is_file():
        raise HTTPException(400, "derive (and review) the rubric first")
    uploaded = {p.name for p in (pdir / "bids").iterdir() if p.is_dir()}
    extracted = {p.stem for p in (pdir / "work" / "bids").glob("*.json")}
    if not uploaded | extracted:
        raise HTTPException(400, "upload at least one bid first")

    def job():
        rubric = Rubric.model_validate(_read_json(rubric_path))
        cfg = _make_cfg(pdir)
        llm = None
        extractions = []
        for name in sorted(uploaded | extracted):
            ext_path = pdir / "work" / "bids" / f"{name}.json"
            if ext_path.is_file():
                extractions.append(BidExtraction.model_validate(_read_json(ext_path)))
                continue
            if llm is None:
                from app.llm import LLM
                llm = LLM(cfg)
            _set_status(pdir, "running", f"extracting bid: {name}")
            docs = load_folder(pdir / "bids" / name, cfg, llm)
            extraction = extract_bid(name, docs, rubric, cfg, llm)
            _write_json(ext_path, extraction.model_dump(mode="json"))
            extractions.append(extraction)
        _set_status(pdir, "running", "evaluating (deterministic) and rendering reports")
        result = evaluate(rubric, extractions)
        _write_json(pdir / "work" / "evaluation.json", result.model_dump(mode="json"))
        render_all(result, pdir / "work" / "reports")
        _set_status(pdir, "done", "evaluation complete — reports ready")

    _start_job(pid, pdir, job)
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
