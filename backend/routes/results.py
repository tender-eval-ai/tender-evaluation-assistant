"""Deterministic re-evaluation from the stored extractions, the evaluation result,
and model usage / cost."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.evaluate import evaluate
from app.report import render_all
from app.schemas import Rubric
from backend import deps, jobs

router = APIRouter(dependencies=[Depends(deps.require_key)])


@router.post("/projects/{pid}/legacy/evaluate")   # the contract's /evaluate is the S4 re-evaluation job (routes/review.py); this one goes at S5
def run_evaluation(pid: str) -> dict:
    pdir = deps._project_dir(pid)
    rubric_path = deps._require_rubric(pdir)
    if not deps._bidder_names(pdir):
        raise HTTPException(400, "upload at least one bid first")

    extractions = deps._stored_extractions(pdir)

    def job():
        rubric = Rubric.model_validate(deps._read_json(rubric_path))
        deps._set_status(pdir, "running", "evaluating (deterministic) and rendering reports")
        result = evaluate(rubric, extractions)
        deps._write_json(pdir / "work" / "evaluation.json", result.model_dump(mode="json"))
        render_all(result, pdir / "work" / "reports")
        deps._set_status(pdir, "done", "evaluation complete — reports ready")

    jobs._start_job(pid, pdir, job, "evaluating from stored extractions")
    return {"started": True}


@router.get("/projects/{pid}/usage")
def get_usage(pid: str) -> dict:
    """Model usage and cost for the last run: totals, $ per bid, per-bid and per-model
    breakdown, failed calls (fallbacks) — written by the graph next to evaluation.json."""
    path = deps._project_dir(pid) / "work" / "usage" / "summary.json"
    if not path.is_file():
        raise HTTPException(404, "no usage summary yet (written when the evaluation runs)")
    return deps._read_json(path)


@router.get("/projects/{pid}/evaluation")
def get_evaluation(pid: str) -> dict:
    path = deps._project_dir(pid) / "work" / "evaluation.json"
    if not path.is_file():
        raise HTTPException(404, "no evaluation yet")
    return deps._read_json(path)
