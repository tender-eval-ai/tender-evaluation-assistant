"""The audit panel: every mutating route's event, append-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend import deps
from backend.schemas_api import Event, EventPage

router = APIRouter(dependencies=[Depends(deps.require_key)])


@router.get("/projects/{pid}/events")
def list_events(pid: str, since: float | None = None, kind: str | None = None, limit: int = 100,
                cursor: str | None = None) -> EventPage:
    deps._project_dir(pid)
    limit = max(1, min(limit, 1000))
    after_id = int(cursor) if cursor else 0
    rows = deps.runner().store.events(pid, kind=kind, after_id=after_id, since=since, limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    return EventPage(items=[Event(**r) for r in page], next_cursor=str(page[-1]["id"]) if more and page else None)
