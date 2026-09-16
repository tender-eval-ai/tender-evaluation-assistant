"""The run queue both variants use: Procrastinate on the harness Postgres.

Workers are separate processes (so the harness can kill one). Heartbeats and the
stalled-job timeout are short here (1 s / 3 s) so a crash is noticed within seconds;
production values would be the library defaults (10 s / 30 s). Procrastinate marks a
stalled job but does not retry it by itself: the Sweeper thread does, every second,
which in production would be a periodic task in the worker.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading

from procrastinate import App, BaseRetryStrategy, PsycopgConnector, RetryDecision

HEARTBEAT = 1.0
STALLED_AFTER = 3.0
QUEUE = "checks"


def make_app(dsn: str | None = None) -> App:
    return App(connector=PsycopgConnector(conninfo=dsn or os.environ["DATABASE_URL"]))


class TransientRetry(BaseRetryStrategy):
    """Retry only provider errors marked transient (a 429), at most five attempts, half
    a second apart. A permanent failure ends the job, visible as failed."""

    def get_retry_decision(self, *, exception: BaseException, job) -> RetryDecision | None:
        if getattr(exception, "transient", False) and job.attempts < 5:
            return RetryDecision(retry_in={"seconds": 0.5})
        return None


def reset_schema(app: App) -> None:
    """Apply Procrastinate's schema once; afterwards empty its tables between scenarios."""
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        exists = c.execute("select to_regclass('procrastinate_jobs')").fetchone()[0]
        if exists:
            c.execute("truncate procrastinate_jobs, procrastinate_events, procrastinate_periodic_defers, "
                      "procrastinate_workers restart identity")
            return
    with app.open():
        app.schema_manager.apply_schema()


def start_workers(tasks_module: str, count: int) -> list[subprocess.Popen]:
    return [subprocess.Popen([sys.executable, "-m", "spikes.common.worker_main", tasks_module, f"worker-{i}"],
                             env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for i in range(count)]


class Sweeper:
    """Retries jobs whose worker stopped sending heartbeats. Runs its own asyncio loop in
    a thread with its own App: Procrastinate's job-manager methods for stalled jobs are
    async-only. In production this would be a periodic task inside the worker."""

    def __init__(self, dsn: str | None = None, every: float = 1.0):
        self.dsn, self.every = dsn, every
        self._stop = threading.Event()
        self.retried: list[int] = []
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True)

    def start(self) -> "Sweeper":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    async def _run(self) -> None:
        app = make_app(self.dsn)
        async with app.open_async():
            while not self._stop.is_set():
                try:
                    for job in await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_AFTER):
                        await app.job_manager.retry_job(job)
                        self.retried.append(job.id)
                except Exception:      # noqa: BLE001 - a sweep that fails is retried next second
                    pass
                await asyncio.sleep(self.every)


def stalled_job_ids(dsn: str | None = None) -> list[int]:
    """Jobs being worked on by a worker whose heartbeat is older than the timeout, or
    whose worker row is gone. Plain SQL over Procrastinate's own tables."""
    import psycopg
    with psycopg.connect(dsn or os.environ["DATABASE_URL"], autocommit=True) as c:
        rows = c.execute(
            "select j.id from procrastinate_jobs j left join procrastinate_workers w on w.id = j.worker_id "
            "where j.status = 'doing' and (w.id is null or w.last_heartbeat < now() - make_interval(secs => %s))",
            (STALLED_AFTER,)).fetchall()
    return [r[0] for r in rows]
