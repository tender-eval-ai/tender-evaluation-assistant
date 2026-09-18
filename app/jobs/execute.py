"""Run a pipeline over a context. Pure: the context decides where progress is saved,
so this is tested without Postgres and reused by every job."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.jobs.models import Context, Pause, Pipeline


class ExecContext(Context, Protocol):
    done: list[str]

    def complete(self, step: str, data: dict | None) -> None:
        """Merge the step's output into `data`, mark the step done, save both."""

    def paused(self, step: str, reason: str) -> None:
        """Record that the run is parked in this step."""

    def resumed(self, step: str) -> None:
        """Record that the run is moving again in this step."""


@dataclass
class Outcome:
    state: str                  # done | paused
    step: str | None = None
    reason: str | None = None


def run_pipeline(pipeline: Pipeline, ctx: ExecContext) -> Outcome:
    for step in pipeline.steps:
        if step.name in ctx.done:
            continue
        out = step.run(ctx)
        if isinstance(out, Pause):
            ctx.paused(step.name, out.reason)
            out = step.run(ctx)          # re-check: an unblock written in between is not missed
            if isinstance(out, Pause):
                return Outcome("paused", step.name, out.reason)
            ctx.resumed(step.name)
        ctx.complete(step.name, out)
    return Outcome("done")
