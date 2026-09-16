"""The Word deliverables: list and download."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend import deps

router = APIRouter(dependencies=[Depends(deps.require_key)])


@router.get("/projects/{pid}/reports")
def list_reports(pid: str) -> list[str]:
    reports = deps._project_dir(pid) / "work" / "reports"
    return sorted(p.name for p in reports.glob("*.docx")) if reports.is_dir() else []


@router.get("/projects/{pid}/reports/{name}")
def download_report(pid: str, name: str) -> FileResponse:
    path = deps._project_dir(pid) / "work" / "reports" / deps._safe_name(name)
    if not path.is_file():
        raise HTTPException(404, f"report '{name}' not found")
    return FileResponse(path, media_type=deps.DOCX_MIME, filename=path.name)
