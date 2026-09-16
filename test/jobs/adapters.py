"""The interface every orchestrator variant implements for the harness.

An adapter owns its own storage (a job table, LangGraph checkpoints, Procrastinate's
tables); the harness never reads that storage directly. It only calls these methods
and reads the FakeLLM log, so the same scenarios measure every variant the same way.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Protocol

ADAPTERS = {
    "reference": "test.jobs.reference:ReferenceAdapter",
    "langgraph": "spikes.langgraph.adapter:LangGraphAdapter",
    "queue": "spikes.queue.adapter:ProcrastinateAdapter",
}


@dataclass
class RunStatus:
    run_id: str
    tender: str
    vendor: str
    state: str                      # queued | running | paused | done | failed | dead | lost
    step: str | None                # triage | resolve | extract | await_rubric | decide
    progress: dict                  # {"done": n, "total": m, "unit": "pages"} for the current step
    rubric_version: int | None
    worker_pid: int | None
    updated_at: float
    error: str | None = None


@dataclass
class Result:
    run_id: str
    vendor: str
    rubric_version: int
    fields: dict
    verdict: dict
    corrections: dict = field(default_factory=dict)


class Orchestrator(Protocol):
    name: str

    def setup(self) -> None:
        """Create or reset the adapter's own storage; called before every scenario."""

    def start_check(self, tender: str, vendor: str) -> str:
        """Enqueue one vendor check and return its run id at once."""

    def status(self, run_id: str) -> RunStatus: ...

    def results(self, run_id: str) -> Result | None: ...

    def confirm_rubric(self, tender: str) -> int:
        """Confirm the tender's rubric; paused runs may proceed. Returns the version."""

    def edit_rubric(self, tender: str, patch: dict) -> None:
        """Change the draft rubric (before confirmation); a paused run must see the change."""

    def publish_rubric_version(self, tender: str, patch: dict) -> int:
        """Confirm a new version and re-check every finished vendor against it, engine only."""

    def correct_field(self, run_id: str, item: str, name: str, value: Any, reason: str) -> Result:
        """Human correction: the verdict updates at once with no LLM call."""

    def rerun(self, run_id: str) -> str:
        """Re-extract the same vendor; a correction must survive it."""

    def list_stuck(self) -> list[dict]:
        """Which runs are stuck, why, since when. One call, no digging."""

    def workers(self) -> list[int]:
        """PIDs of live worker processes, so the harness can kill one."""

    def shutdown(self) -> None: ...


def load(name: str) -> Orchestrator:
    module, _, cls = ADAPTERS[name].partition(":")
    return getattr(importlib.import_module(module), cls)()
