"""Background jobs: one daemon thread per project at a time, state in status.json.

This is the part the stop point S1 comparison replaces with a worker (LangGraph +
Postgres checkpointer or a Procrastinate queue). Until then it is kept exactly as it
was, in one place.
"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import HTTPException

from backend import deps

_jobs_lock = threading.Lock()
_running: set[str] = set()


def is_running(pid: str) -> bool:
    with _jobs_lock:
        return pid in _running


def _start_job(pid: str, pdir: Path, target, detail: str = "queued") -> None:
    with _jobs_lock:
        if pid in _running:
            raise HTTPException(409, "a job is already running for this project")
        _running.add(pid)
    # Status must flip to "running" before the endpoint returns, or a client polling
    # right after the POST could see the previous job's terminal state and stop early.
    deps._set_status(pdir, "running", detail)

    def wrapper():
        try:
            target()
        except Exception as err:  # surface anything to the status file
            deps._set_status(pdir, "error", f"{type(err).__name__}: {err}")
        finally:
            with _jobs_lock:
                _running.discard(pid)

    threading.Thread(target=wrapper, daemon=True).start()


def _reset_interrupted_jobs() -> int:
    """Jobs run in daemon threads: if the process died mid-job (deploy, crash, Cloud Run
    scaling the instance away), status.json still says "running" and a client would
    poll forever. Flip those to a clear error once, at startup; finished steps are
    checkpointed on disk, so the human just runs or continues again."""
    flipped = 0
    if not deps.PROJECTS.is_dir():
        return 0
    for pdir in deps.PROJECTS.iterdir():
        try:
            if pdir.is_dir() and deps._get_status(pdir).get("state") == "running":
                deps._set_status(pdir, "error", "the backend restarted while this job was running "
                                                "— run or continue again (finished steps are kept)")
                flipped += 1
        except (OSError, ValueError):
            continue
    return flipped
