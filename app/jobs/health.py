"""The worker's health check, for its container: `python -m app.jobs.health` exits 0 when
this container's sweeper finished a sweep recently, which means the process is alive and
reached the database, and 1 otherwise. The sweeper marks each sweep by touching ALIVE (one
worker per container, so one file). A worker started with --no-sweep gives no signal."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from app.jobs.queue import Settings

ALIVE = Path(tempfile.gettempdir()) / "tea-worker-alive"


def mark_alive() -> None:
    ALIVE.touch()


def max_age() -> float:
    """Three missed sweeps, or the stalled-job timeout when that is longer."""
    sweep = float(os.environ.get("JOBS_SWEEP_EVERY", Settings.sweep_every))
    stalled = float(os.environ.get("JOBS_STALLED_AFTER", Settings.stalled_after))
    return max(3 * sweep, stalled)


def check(now: float | None = None) -> tuple[bool, str]:
    try:
        age = (now or time.time()) - ALIVE.stat().st_mtime
    except FileNotFoundError:
        return False, "no sweep has finished yet"
    if age > max_age():
        return False, f"the last sweep finished {age:.0f} s ago (limit {max_age():.0f} s)"
    return True, f"the last sweep finished {age:.0f} s ago"


def main() -> int:
    ok, why = check()
    print(why, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
