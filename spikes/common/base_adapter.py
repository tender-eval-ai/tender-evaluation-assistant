"""What both variants share on the adapter side: worker processes on the Procrastinate
queue, the stalled-job sweeper, a resumer loop that closes the race between "a run
pauses" and "the rubric is confirmed", idempotent starts, and the store-backed rubric,
result and correction calls. A variant subclasses this and decides only how progress is
kept and how a paused run continues."""
from __future__ import annotations

import threading
import time
from typing import Any

from procrastinate import exceptions

from spikes.common import queue as q
from spikes.common.store import Store
from test.jobs.adapters import Result, RunStatus


class QueueBackedAdapter:
    name = "base"
    tasks_module = ""          # e.g. "spikes.queue.tasks"; must expose app, store, run_slice, resume_run
    workers_count = 2

    def __init__(self, tasks):
        self.tasks = tasks
        self.app = tasks.app
        self.store: Store = tasks.store
        self._procs = []
        self._sweeper: q.Sweeper | None = None
        self._open = False
        self._stop = threading.Event()
        self._resumer: threading.Thread | None = None

    # ---------------------------------------------------------------- hooks
    def _extra_setup(self) -> None:
        """Create or reset the variant's own progress store (checkpoints, job_steps)."""

    def _on_rerun(self, run: dict) -> None:
        """Forget the variant's progress for a run that is re-extracted from scratch."""

    # ---------------------------------------------------------------- Orchestrator
    def setup(self) -> None:
        self.shutdown()
        self.store.reset()
        q.reset_schema(self.app)
        self._extra_setup()
        self.app.open()
        self._open = True
        self._procs = q.start_workers(self.tasks_module, count=self.workers_count)
        self._sweeper = q.Sweeper(self.store.dsn).start()
        self._stop.clear()
        self._resumer = threading.Thread(target=self._resume_loop, daemon=True)
        self._resumer.start()

    def start_check(self, tender: str, vendor: str) -> str:
        existing = self.store.active_run(tender, vendor)
        if existing:
            return existing
        run_id = self.store.create_run(tender, vendor)
        try:
            job_id = self.tasks.run_slice.configure(lock=f"{tender}:{vendor}", queueing_lock=f"{tender}:{vendor}") \
                .defer(run_id=run_id)
        except exceptions.AlreadyEnqueued:
            self.store.update_run(run_id, state="failed", error="duplicate submission")
            return self.store.active_run(tender, vendor) or run_id
        self.store.update_run(run_id, job_id=job_id)
        return run_id

    def status(self, run_id: str) -> RunStatus:
        return self.store.status(run_id)

    def results(self, run_id: str) -> Result | None:
        return self.store.results(run_id)

    def confirm_rubric(self, tender: str) -> int:
        version = self.store.confirm_rubric(tender)
        self._resume_paused()
        return version

    def edit_rubric(self, tender: str, patch: dict) -> None:
        self.store.edit_rubric(tender, patch)

    def publish_rubric_version(self, tender: str, patch: dict) -> int:
        return self.store.publish_rubric_version(tender, patch)

    def correct_field(self, run_id: str, item: str, name: str, value: Any, reason: str) -> Result:
        return self.store.correct_field(run_id, name, value, reason)

    def rerun(self, run_id: str) -> str:
        run = self.store.run(run_id)
        self._on_rerun(run)
        self.store.update_run(run_id, state="queued", step=None, progress={}, error=None, attempt=run["attempt"] + 1)
        job_id = self.tasks.run_slice.configure(lock=f"{run['tender']}:{run['vendor']}").defer(run_id=run_id)
        self.store.update_run(run_id, job_id=job_id)
        return run_id

    def list_stuck(self) -> list[dict]:
        stalled = set(q.stalled_job_ids(self.store.dsn))
        out = []
        for run in self.store.runs_where("state in ('queued','running','failed')"):
            if run["state"] == "failed":
                out.append({"run_id": run["run_id"], "vendor": run["vendor"], "why": "job failed", "since": run["updated_at"]})
            elif run["job_id"] in stalled:
                out.append({"run_id": run["run_id"], "vendor": run["vendor"],
                            "why": f"job {run['job_id']} stalled during {run['step']} (worker heartbeat lost)",
                            "since": run["updated_at"]})
        return out

    def workers(self) -> list[int]:
        return [p.pid for p in self._procs if p.poll() is None]

    def shutdown(self) -> None:
        self._stop.set()
        if self._sweeper:
            self._sweeper.stop()
            self._sweeper = None
        for p in self._procs:
            if p.poll() is None:
                p.kill()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except Exception:   # noqa: BLE001
                pass
        self._procs = []
        if self._open:
            try:
                self.app.close()
            except Exception:   # noqa: BLE001
                pass
            self._open = False

    def execute(self, run_id: str) -> None:
        raise RuntimeError(f"the {self.name} variant runs jobs through Procrastinate workers")

    # ---------------------------------------------------------------- resumer
    def _resume_paused(self) -> int:
        """Resume every paused run whose rubric is confirmed. Called on confirmation and
        every half second, so a run that pauses just after the confirmation is written
        is still picked up."""
        n = 0
        for run in self.store.runs_where("state='paused'"):
            _, confirmed, _ = self.store.rubric(run["tender"])
            if not confirmed:
                continue
            self.store.update_run(run["run_id"], state="running", step="resuming")
            job_id = self.tasks.resume_run.configure(lock=f"{run['tender']}:{run['vendor']}").defer(run_id=run["run_id"])
            self.store.update_run(run["run_id"], job_id=job_id)
            n += 1
        return n

    def _resume_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._resume_paused()
            except Exception:   # noqa: BLE001 - retried next tick
                pass
            time.sleep(0.5)
