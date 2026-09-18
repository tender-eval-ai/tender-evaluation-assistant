"""The Procrastinate tasks. One job per run: `run_check` starts it, `resume_check`
continues a paused one; both execute the run's pipeline from its saved steps.

Progress lives in job_steps (done steps and their data, plus checkpoints a step writes
inside itself), so a job that is retried after a crash, or resumed after a pause,
continues from the first missing piece. A transient provider error fails the job and
the retry policy re-runs it; a permanent one leaves the run `failed`; exhausting the
retries leaves it `dead`. Either is visible in `list_stuck`."""
from __future__ import annotations

import os
from typing import Any

from app.jobs import registry
from app.jobs.execute import run_pipeline
from app.jobs.queue import MAX_ATTEMPTS, QUEUE, TransientRetry, make_app
from app.jobs.store import Store

app = make_app()
store = Store()


class PgContext:
    """The context a step sees inside a job: progress and checkpoints go to Postgres."""

    def __init__(self, run: dict, st: Store, done: list[str], data: dict):
        self.run, self.store, self.done, self.data = run, st, done, data

    def progress(self, step: str, done: int, total: int, unit: str = "pages") -> None:
        self.store.update_run(self.run["run_id"], state="running", step=step,
                              progress={"done": done, "total": total, "unit": unit})

    def checkpoint(self, **data: Any) -> None:
        self.data.update(data)
        self.store.save_steps(self.run["run_id"], self.done, self.data)

    def complete(self, step: str, data: dict | None) -> None:
        if data:
            self.data.update(data)
        self.done.append(step)
        self.store.save_steps(self.run["run_id"], self.done, self.data)

    def paused(self, step: str, reason: str) -> None:
        self.store.update_run(self.run["run_id"], state="paused", step=step, progress={"reason": reason})

    def resumed(self, step: str) -> None:
        self.store.update_run(self.run["run_id"], state="running", step=step, progress={})

    def ruleset(self) -> tuple[int, dict] | None:
        return self.store.latest_confirmed(self.run["project"])


def execute(run_id: str, attempts: int = 0) -> None:
    run = store.run(run_id)
    if run["state"] == "done":
        return                                   # a second resume for a run that already finished
    pipeline = registry.get(run["kind"])
    st = store.steps(run_id)
    ctx = PgContext(run, store, st["done"], st["data"])
    store.update_run(run_id, state="running", worker_pid=os.getpid(), error=None)
    try:
        outcome = run_pipeline(pipeline, ctx)
        if outcome.state == "paused":
            return
        confirmed = ctx.ruleset()
        if confirmed is None:
            raise RuntimeError("no confirmed rule set to decide against")
        version, spec = confirmed
        fields = ctx.data.get(pipeline.fields_key) or {}
        store.store_result(run_id, run["project"], run["tenderer"], version, fields, spec, pipeline.decide)
        store.update_run(run_id, state="done", step=None, progress={}, ruleset_version=version)
    except Exception as err:
        transient = getattr(err, "transient", False)
        if transient and attempts + 1 < MAX_ATTEMPTS:
            state = "running"                    # the queue retries; the next attempt continues from job_steps
        elif transient:
            state = "dead"
        else:
            state = "failed"
        store.update_run(run_id, state=state, error=f"{type(err).__name__}: {err}")
        raise


@app.task(queue=QUEUE, retry=TransientRetry(), pass_context=True)
def run_check(context, run_id: str) -> None:
    execute(run_id, context.job.attempts)


@app.task(queue=QUEUE, retry=TransientRetry(), pass_context=True)
def resume_check(context, run_id: str) -> None:
    execute(run_id, context.job.attempts)
