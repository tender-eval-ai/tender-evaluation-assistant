"""Inside every worker: retry jobs whose worker stopped sending heartbeats, and resume
paused runs whose wait is over. Runs its own asyncio loop in a thread with its own
Procrastinate app, because the job-manager methods for stalled jobs are async-only
and the worker's connector is busy running jobs."""
from __future__ import annotations

import asyncio
import threading

from app.jobs.queue import QUEUE, Settings, make_app
from app.jobs.runner import resume_candidates
from app.jobs.store import Store


class Sweeper(threading.Thread):
    def __init__(self, settings: Settings):
        super().__init__(daemon=True, name="sweeper")
        self.settings = settings
        self.retried: list[int] = []
        self.resumed: list[str] = []
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        app = make_app(self.settings.dsn)
        store = Store(self.settings.dsn)
        async with app.open_async():
            while not self._stop.is_set():
                try:
                    for job in await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=self.settings.stalled_after):
                        await app.job_manager.retry_job(job)
                        self.retried.append(job.id)
                except Exception:      # noqa: BLE001 - a sweep that fails is retried next tick
                    pass
                try:
                    for run in resume_candidates(store):
                        if store.transition(run["run_id"], ("paused",), state="running", step="resuming"):
                            job_id = await app.configure_task(
                                name="app.jobs.tasks.resume_check", queue=QUEUE,
                                lock=f"{run['project']}:{run['tenderer']}").defer_async(run_id=run["run_id"])
                            store.update_run(run["run_id"], job_id=job_id)
                            self.resumed.append(run["run_id"])
                except Exception:      # noqa: BLE001
                    pass
                await asyncio.sleep(self.settings.sweep_every)
