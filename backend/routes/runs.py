"""The orchestrated run (LangGraph with a SQLite checkpoint per project): start,
resume past a human checkpoint, inspect the graph, the agent trace, and job status."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel

from app.graph import (build_graph, graph_config, initial_state, pending_checkpoint,
                       pending_from_snapshot, resume as graph_resume)
from backend import deps, jobs

router = APIRouter(dependencies=[Depends(deps.require_key)])

WAITING_DETAIL = {
    "rubric": "waiting: confirm the rubric — review/edit it, then Continue",
    "review": "waiting: review the extractions — correct any, then Continue",
}


def _graph_db_canonical(pdir: Path) -> Path:
    return pdir / "work" / "graph.sqlite"


def _graph_db_scratch(pdir: Path) -> Path | None:
    return Path(deps.GRAPH_DB_SCRATCH) / pdir.name / "graph.sqlite" if deps.GRAPH_DB_SCRATCH else None


def _graph_db(pdir: Path) -> str:
    """Path to open the project's graph checkpoint DB at. With GRAPH_DB_SCRATCH_DIR
    set, that is a local working copy, refreshed from the canonical file under work/
    whenever the canonical one is newer (first use on a fresh instance, or after the
    scratch disk was lost); _graph_db_publish() copies it back after every job. So an
    instance restart between two human checkpoints loses nothing: the pause state is
    on the bucket, not only on the disk that went away."""
    canonical = _graph_db_canonical(pdir)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    scratch = _graph_db_scratch(pdir)
    if scratch is None:
        return str(canonical)
    scratch.parent.mkdir(parents=True, exist_ok=True)
    if canonical.is_file() and (not scratch.is_file()
                                or canonical.stat().st_mtime > scratch.stat().st_mtime):
        shutil.copyfile(canonical, scratch)
        os.utime(scratch, (canonical.stat().st_atime, canonical.stat().st_mtime))
    return str(scratch)


def _graph_db_publish(pdir: Path) -> None:
    """Copy the scratch DB back to the canonical location (temp file + rename, so a
    reader never sees a half-copied DB); no-op without a scratch dir."""
    scratch = _graph_db_scratch(pdir)
    if scratch is None or not scratch.is_file():
        return
    canonical = _graph_db_canonical(pdir)
    tmp = canonical.with_name(f".{canonical.name}.{os.getpid()}.tmp")
    shutil.copyfile(scratch, tmp)
    os.replace(tmp, canonical)
    # Same mtime on both copies: the next _graph_db() must not copy it back again.
    st = canonical.stat()
    os.utime(scratch, (st.st_atime, st.st_mtime))


def _graph_db_exists(pdir: Path) -> bool:
    scratch = _graph_db_scratch(pdir)
    return _graph_db_canonical(pdir).is_file() or bool(scratch and scratch.is_file())


def _graph_snapshot(pdir: Path, pid: str):
    """State of the project's graph thread (None if it never ran)."""
    if not _graph_db_exists(pdir):
        return None
    cfg = deps._make_cfg(pdir)
    with SqliteSaver.from_conn_string(_graph_db(pdir)) as saver:
        graph = build_graph(cfg, None, checkpointer=saver, interactive=True, log=lambda m: None)
        return graph.get_state(graph_config(cfg, pid))


def _graph_job(pid: str, pdir: Path, start: bool, payload: dict | None = None) -> None:
    """Run the graph in the background until the next human checkpoint or the end."""
    def job():
        from app.llm import LLM
        cfg = deps._make_cfg(pdir)
        llm = LLM(cfg)
        try:
            with SqliteSaver.from_conn_string(_graph_db(pdir)) as saver:
                graph = build_graph(cfg, llm, checkpointer=saver, interactive=True,
                                    log=lambda m: deps._set_status(pdir, "running", m))
                if start:
                    state = graph.invoke(initial_state(pdir / "tender", pdir / "bids", pdir / "work"),
                                         graph_config(cfg, pid))
                else:
                    state = graph_resume(graph, cfg, pid, payload)
        finally:
            _graph_db_publish(pdir)   # pause/finish state onto durable storage
        pending = pending_checkpoint(state)
        if pending:
            deps._set_status(pdir, "waiting", WAITING_DETAIL[pending["checkpoint"]])
        else:
            deps._set_status(pdir, "done", "evaluation complete — reports ready")

    jobs._start_job(pid, pdir, job, "starting the orchestrated run" if start else "continuing the run")


@router.post("/projects/{pid}/run")
def run_project(pid: str) -> dict:
    pdir = deps._project_dir(pid)
    if not list((pdir / "tender").glob("*.pdf")) and not (pdir / "work" / "rubric.json").is_file():
        raise HTTPException(400, "upload tender documents first")
    if pending_from_snapshot(_graph_snapshot(pdir, pid)):
        raise HTTPException(409, "the run is paused at a human checkpoint — use /resume")
    _graph_job(pid, pdir, start=True)
    return {"started": True}


class ResumeRequest(BaseModel):
    rubric: dict | None = None
    extractions: dict[str, dict] | None = None


@router.post("/projects/{pid}/resume")
def resume_project(pid: str, req: ResumeRequest | None = None) -> dict:
    pdir = deps._project_dir(pid)
    pending = pending_from_snapshot(_graph_snapshot(pdir, pid))
    if not pending:
        raise HTTPException(409, "nothing to resume — the run is not paused")
    payload = {k: v for k, v in (req.model_dump() if req else {}).items() if v is not None}
    _graph_job(pid, pdir, start=False, payload=payload)
    return {"resumed": pending["checkpoint"]}


@router.get("/projects/{pid}/graph")
def graph_state(pid: str) -> dict:
    pdir = deps._project_dir(pid)
    snap = _graph_snapshot(pdir, pid)
    pending = pending_from_snapshot(snap)
    values = (snap.values if snap else None) or {}
    return {"ran": snap is not None, "pending": pending["checkpoint"] if pending else None,
            "progress": values.get("progress", []), "corrected": values.get("corrected", []),
            "next": list(snap.next) if snap else []}


@router.get("/projects/{pid}/bids/{tenderer}/agent")
def agent_trace(pid: str, tenderer: str) -> dict:
    """The evidence-search agent's step trace for one bid (404 if it never ran)."""
    path = deps._project_dir(pid) / "work" / "agent" / f"{deps._safe_name(tenderer)}.json"
    if not path.is_file():
        raise HTTPException(404, f"no evidence-search trace for '{tenderer}'")
    return deps._read_json(path)


@router.get("/projects/{pid}/status")
def status(pid: str) -> dict:
    return deps._get_status(deps._project_dir(pid))
