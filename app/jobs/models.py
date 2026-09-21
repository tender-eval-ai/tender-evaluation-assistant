"""Shapes shared by the runner, the worker and every pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

STATES = ("queued", "running", "paused", "done", "failed", "dead")
TENDER = "_tender"     # the tenderer of a run that belongs to the tender itself (a rule-set build)
EVALUATE = "_evaluate"  # the tenderer of a run that re-decides every result (an evaluation)


def is_project_run(tenderer: str | None) -> bool:
    """Runs of the project itself use a sentinel tenderer; the API shows them as null."""
    return bool(tenderer) and tenderer.startswith("_")


@dataclass
class RunStatus:
    run_id: str
    project: str
    tenderer: str
    kind: str
    state: str                      # one of STATES
    step: str | None                # the step being run, or the one the run is paused in
    progress: dict                  # {"done": n, "total": m, "unit": "pages"} for the current step
    attempt: int
    ruleset_version: int | None
    worker_pid: int | None
    updated_at: float               # epoch seconds
    error: str | None = None
    job_id: int | None = None       # the queue's job id, for list_stuck and the logs


@dataclass
class Result:
    run_id: str
    project: str
    tenderer: str
    ruleset_version: int
    fields: dict
    verdict: dict
    corrections: dict = field(default_factory=dict)
    review_confirmed_by: str | None = None
    review_confirmed_at: float | None = None


class Pause:
    """A step's answer when it cannot continue yet. The run is parked as `paused`; the
    sweeper (or the API, on the event that unblocks it) resumes it when the pipeline's
    `resume_when[reason]` holds, and the same step runs again."""

    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self) -> str:
        return f"Pause({self.reason!r})"


class Context(Protocol):
    """What a step sees. `data` is the run's saved state; a step reads what earlier
    steps (or its own earlier attempt) left there and returns what it adds."""

    run: dict
    data: dict

    def progress(self, step: str, done: int, total: int, unit: str = "pages") -> None: ...

    def checkpoint(self, **data: Any) -> None:
        """Save partial results inside a step (after each batch), so a retry after a
        crash continues from here instead of the step's start."""

    def ruleset(self) -> tuple[int, dict] | None:
        """The project's latest confirmed rule set as (version, spec), or None."""


StepFn = Callable[[Context], "dict | Pause | None"]


@dataclass
class Step:
    name: str
    run: StepFn
    unit: str = "pages"


@dataclass
class Pipeline:
    """One kind of job: the ordered steps, where the extracted fields end up, and the
    engine-only decision the store re-runs on corrections and new rule-set versions."""

    kind: str
    steps: list[Step]
    fields_key: str | None                                 # None: the run stores no result (a build saves its own draft)
    decide: Callable[[dict, dict], dict] | None = None     # (fields, ruleset spec) -> verdict; no LLM
    resume_when: dict[str, Callable[[Any, dict], bool]] = field(default_factory=dict)   # reason -> (store, run) -> bool
