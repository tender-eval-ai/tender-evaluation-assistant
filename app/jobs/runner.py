"""The port the API calls. Everything here is a store read or a defer; the work
happens in worker processes."""
from __future__ import annotations

from typing import Any

from procrastinate import exceptions

from app.jobs import queue as q
from app.jobs import registry, tasks
from app.jobs.models import Result, RunStatus
from app.jobs.queue import Settings
from app.jobs.store import Store


def _lock(run: dict) -> str:
    return f"{run['project']}:{run['tenderer']}"


class JobRunner:
    def __init__(self, store: Store | None = None, settings: Settings | None = None):
        self.store = store or tasks.store
        self.settings = settings or Settings.from_env()
        self.app = tasks.app
        self._open = False

    def open(self) -> "JobRunner":
        if not self._open:
            self.app.open()
            self._open = True
        return self

    def close(self) -> None:
        if self._open:
            self.app.close()
            self._open = False

    # ---------------------------------------------------------------- runs
    def start(self, project: str, tenderer: str, kind: str) -> str:
        """Enqueue one check and return its run id at once. A second start for the same
        project and tenderer while one is active returns the active run."""
        existing = self.store.active_run(project, tenderer)
        if existing:
            return existing
        run_id = self.store.create_run(project, tenderer, kind)
        lock = f"{project}:{tenderer}"
        try:
            job_id = tasks.run_check.configure(lock=lock, queueing_lock=lock).defer(run_id=run_id)
        except exceptions.AlreadyEnqueued:
            self.store.update_run(run_id, state="failed", error="duplicate submission")
            return self.store.active_run(project, tenderer) or run_id
        self.store.update_run(run_id, job_id=job_id)
        return run_id

    def status(self, run_id: str) -> RunStatus:
        return self.store.status(run_id)

    def results(self, run_id: str) -> Result | None:
        return self.store.results(run_id)

    def runs(self, project: str | None = None) -> list[RunStatus]:
        rows = self.store.runs_where("project=%s", (project,)) if project else self.store.runs_where("true")
        return [RunStatus(**r) for r in rows]

    def rerun(self, run_id: str) -> str:
        """Re-extract from scratch; corrections on the result survive (the store applies
        them again when the new fields are stored)."""
        run = self.store.run(run_id)
        self.store.clear_steps(run_id)
        self.store.update_run(run_id, state="queued", step=None, progress={}, error=None, attempt=run["attempt"] + 1)
        job_id = tasks.run_check.configure(lock=_lock(run)).defer(run_id=run_id)
        self.store.update_run(run_id, job_id=job_id)
        return run_id

    def retry(self, run_id: str) -> str:
        """A failed or dead run continues from its saved steps."""
        run = self.store.run(run_id)
        if run["state"] not in ("failed", "dead"):
            raise ValueError(f"run {run_id} is {run['state']}; only failed or dead runs are retried")
        self.store.update_run(run_id, state="queued", error=None, attempt=run["attempt"] + 1)
        job_id = tasks.run_check.configure(lock=_lock(run)).defer(run_id=run_id)
        self.store.update_run(run_id, job_id=job_id)
        return run_id

    # ---------------------------------------------------------------- pause and resume
    def resume_paused(self, project: str | None = None) -> int:
        """Resume every paused run whose pipeline says the wait is over. Called on the
        event that unblocks runs (a confirmation) and by every worker's sweeper, so a run
        that pauses just after the event is still picked up."""
        n = 0
        for run in resume_candidates(self.store, project):
            if self.store.transition(run["run_id"], ("paused",), state="running", step="resuming"):
                job_id = tasks.resume_check.configure(lock=_lock(run)).defer(run_id=run["run_id"])
                self.store.update_run(run["run_id"], job_id=job_id)
                n += 1
        return n

    # ---------------------------------------------------------------- rule sets
    def confirm_ruleset(self, project: str) -> int:
        version = self.store.confirm(project)
        self.resume_paused(project)
        return version

    def publish_ruleset(self, project: str, patch: dict) -> int:
        return self.store.publish(project, patch, lambda kind: registry.get(kind).decide)

    def correct_field(self, run_id: str, name: str, value: Any, reason: str, by: str = "reviewer") -> Result:
        run = self.store.run(run_id)
        return self.store.correct_field(run_id, name, value, reason, by, registry.get(run["kind"]).decide)

    # ---------------------------------------------------------------- what is stuck
    def list_stuck(self) -> list[dict]:
        """Runs that are not progressing: why, since when. One call, no digging."""
        stalled = set(q.stalled_job_ids(self.store.dsn, self.settings.stalled_after))
        runs = self.store.runs_where("state in ('queued','running','failed','dead')")
        jobs = q.job_states(self.store.dsn, [r["job_id"] for r in runs if r["job_id"]])
        out = []
        for run in runs:
            why = None
            if run["state"] == "failed":
                why = f"job failed: {run['error']}"
            elif run["state"] == "dead":
                why = f"gave up after {q.MAX_ATTEMPTS} attempts: {run['error']}"
            elif run["job_id"] in stalled:
                why = f"job {run['job_id']} stalled during {run['step']} (worker heartbeat lost)"
            elif run["job_id"] and jobs.get(run["job_id"]) == "failed":
                why = f"job {run['job_id']} failed without updating the run"
            if why:
                out.append({"run_id": run["run_id"], "project": run["project"], "tenderer": run["tenderer"],
                            "vendor": run["tenderer"], "state": run["state"], "why": why, "since": run["updated_at"]})
        return out


def resume_candidates(store: Store, project: str | None = None) -> list[dict]:
    """Paused runs whose pipeline's `resume_when` predicate for their pause reason holds."""
    where, params = ("state='paused' and project=%s", (project,)) if project else ("state='paused'", ())
    out = []
    for run in store.runs_where(where, params):
        try:
            pipeline = registry.get(run["kind"])
        except KeyError:
            continue                                        # this process does not know the pipeline
        reason = (run["progress"] or {}).get("reason")
        pred = pipeline.resume_when.get(reason)
        if pred and pred(store, run):
            out.append(run)
    return out
