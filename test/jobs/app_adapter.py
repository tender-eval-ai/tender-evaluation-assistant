"""The promoted runner (app/jobs) under the harness. Same twelve scenarios, same
FakeLLM slice (test/jobs/app_pipeline.py); the workers are `python -m app.jobs.worker`
subprocesses with second-scale heartbeat settings."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

FAST = {"JOBS_HEARTBEAT": "1", "JOBS_STALLED_AFTER": "3", "JOBS_SWEEP_EVERY": "1", "JOBS_POLL": "0.5", "JOBS_RETRY_BASE": "0.5"}
os.environ.update(FAST)                       # before Settings.from_env() and before any worker is spawned

from app import db                                          # noqa: E402
from app.jobs import queue as q                             # noqa: E402
from app.jobs import runner as runner_mod, tasks            # noqa: E402
from app.jobs.queue import Settings                         # noqa: E402
from test.jobs import app_pipeline                          # noqa: E402  registers kind "slice"
from test.jobs.adapters import Result, RunStatus            # noqa: E402

JOBS_DIR = Path(tasks.__file__).parent


class AppAdapter:
    name = "app"
    services = "Postgres (Procrastinate tables + runs, job_steps, results, rulesets)"
    glue_files = [str(p) for p in sorted(JOBS_DIR.glob("*.py")) if p.name != "__init__.py"] + [str(Path(db.__file__))]
    workers_count = 2

    def __init__(self):
        self.settings = Settings.from_env()
        self.store = tasks.store
        self.runner = runner_mod.JobRunner(self.store, self.settings)
        self._procs: list[subprocess.Popen] = []

    # ---------------------------------------------------------------- lifecycle
    def setup(self) -> None:
        self.shutdown()
        db.reset_for_tests(self.settings.dsn)
        db.migrate(self.settings.dsn)
        q.apply_schema(tasks.app)
        self.runner.open()
        self._procs = [subprocess.Popen([sys.executable, "-m", "app.jobs.worker", "--name", f"worker-{i}",
                                         "--pipelines", "test.jobs.app_pipeline", "--no-migrate"],
                                        env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                       for i in range(self.workers_count)]

    def shutdown(self) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.kill()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except Exception:   # noqa: BLE001
                pass
        self._procs = []
        self.runner.close()

    def workers(self) -> list[int]:
        return [p.pid for p in self._procs if p.poll() is None]

    def execute(self, run_id: str) -> None:
        raise RuntimeError("the app runner executes jobs in python -m app.jobs.worker processes")

    # ---------------------------------------------------------------- Orchestrator
    def start_check(self, tender: str, vendor: str) -> str:
        self.store.ensure_draft(tender, app_pipeline.DEFAULT_SPEC)
        return self.runner.start(tender, vendor, "slice")

    def status(self, run_id: str) -> RunStatus:
        s = self.runner.status(run_id)
        return RunStatus(s.run_id, s.project, s.tenderer, s.state, s.step, s.progress, s.ruleset_version,
                         s.worker_pid, s.updated_at, s.error)

    def results(self, run_id: str) -> Result | None:
        r = self.runner.results(run_id)
        return Result(r.run_id, r.tenderer, r.ruleset_version, r.fields, r.verdict, r.corrections) if r else None

    def confirm_rubric(self, tender: str) -> int:
        return self.runner.confirm_ruleset(tender)

    def edit_rubric(self, tender: str, patch: dict) -> None:
        self.store.patch_draft(tender, patch)

    def publish_rubric_version(self, tender: str, patch: dict) -> int:
        return self.runner.publish_ruleset(tender, patch)

    def correct_field(self, run_id: str, item: str, name: str, value: Any, reason: str) -> Result:
        r = self.runner.correct_field(run_id, name, value, reason)
        return Result(r.run_id, r.tenderer, r.ruleset_version, r.fields, r.verdict, r.corrections)

    def rerun(self, run_id: str) -> str:
        return self.runner.rerun(run_id)

    def list_stuck(self) -> list[dict]:
        return self.runner.list_stuck()
