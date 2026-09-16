"""The rubric (human checkpoint) and per-tenderer extractions (inject or correct)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import BidExtraction, Rubric
from backend import deps

router = APIRouter(dependencies=[Depends(deps.require_key)])


@router.get("/projects/{pid}/rubric")
def get_rubric(pid: str) -> dict:
    path = deps._project_dir(pid) / "work" / "rubric.json"
    if not path.is_file():
        raise HTTPException(404, "no rubric yet — derive it or PUT one")
    return deps._read_json(path)


@router.put("/projects/{pid}/rubric")
def put_rubric(pid: str, rubric: Rubric) -> dict:
    deps._write_json(deps._project_dir(pid) / "work" / "rubric.json", rubric.model_dump(mode="json"))
    return {"saved": True}


@router.put("/projects/{pid}/bids/{tenderer}/extraction")
def put_extraction(pid: str, tenderer: str, extraction: BidExtraction) -> dict:
    """Inject or human-correct one tenderer's extraction; skipped by the LLM step."""
    pdir = deps._project_dir(pid)
    extraction.tenderer = tenderer
    deps._write_json(pdir / "work" / "bids" / f"{deps._safe_name(tenderer)}.json",
                     extraction.model_dump(mode="json"))
    return {"saved": True}


@router.get("/projects/{pid}/bids/{tenderer}/extraction")
def get_extraction(pid: str, tenderer: str) -> dict:
    path = deps._project_dir(pid) / "work" / "bids" / f"{deps._safe_name(tenderer)}.json"
    if not path.is_file():
        raise HTTPException(404, f"no extraction for '{tenderer}' yet")
    return deps._read_json(path)
