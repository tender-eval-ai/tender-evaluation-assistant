"""Procrastinate on Postgres: the app, the settings, the retry policy and the
stalled-job query. Timing comes from the environment so the harness can run with
second-scale values while production keeps the library defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass

from procrastinate import App, BaseRetryStrategy, PsycopgConnector, RetryDecision

QUEUE = "checks"
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Settings:
    dsn: str
    heartbeat: float = 10.0        # seconds between a worker's heartbeats
    stalled_after: float = 30.0    # a job whose worker missed this many seconds is retried
    sweep_every: float = 5.0       # how often a worker looks for stalled jobs and paused runs
    poll: float = 2.0              # how often an idle worker asks for a job
    concurrency: int = 2           # jobs one worker runs at once

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(dsn=env["DATABASE_URL"],
                   heartbeat=float(env.get("JOBS_HEARTBEAT", cls.heartbeat)),
                   stalled_after=float(env.get("JOBS_STALLED_AFTER", cls.stalled_after)),
                   sweep_every=float(env.get("JOBS_SWEEP_EVERY", cls.sweep_every)),
                   poll=float(env.get("JOBS_POLL", cls.poll)),
                   concurrency=int(env.get("JOBS_CONCURRENCY", cls.concurrency)))


def make_app(dsn: str | None = None) -> App:
    return App(connector=PsycopgConnector(conninfo=dsn or os.environ["DATABASE_URL"]))


class TransientRetry(BaseRetryStrategy):
    """Retry only errors marked transient (a provider 429 or a timeout), up to MAX_ATTEMPTS,
    with a growing wait: JOBS_RETRY_BASE seconds (default 10), doubled each time, at most two
    minutes, so the retries outlast a provider's one-minute token window. Half a second apart,
    four checks against a 10K-token-a-minute deployment all died inside the same minute
    (2026-09-30). Anything else ends the job, visible as failed."""

    def __init__(self, base: float | None = None):
        self.base = float(os.environ.get("JOBS_RETRY_BASE", 10.0)) if base is None else base

    def wait(self, attempts: int) -> float:
        """Seconds before the next try, after `attempts` tries so far."""
        return min(120.0, self.base * 2 ** attempts)

    def get_retry_decision(self, *, exception: BaseException, job) -> RetryDecision | None:
        if getattr(exception, "transient", False) and job.attempts < MAX_ATTEMPTS:
            return RetryDecision(retry_in={"seconds": self.wait(job.attempts)})
        return None


def apply_schema(app: App) -> bool:
    """Create Procrastinate's tables once. Returns True when they were created now."""
    import psycopg
    with psycopg.connect(app.connector.conninfo if hasattr(app.connector, "conninfo") else os.environ["DATABASE_URL"],
                         autocommit=True) as c:
        if c.execute("select to_regclass('procrastinate_jobs')").fetchone()[0]:
            return False
    with app.open():
        app.schema_manager.apply_schema()
    return True


def stalled_job_ids(dsn: str, stalled_after: float) -> list[int]:
    """Jobs being worked on by a worker whose heartbeat is older than the timeout, or
    whose worker row is gone. Plain SQL over Procrastinate's own tables."""
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute(
            "select j.id from procrastinate_jobs j left join procrastinate_workers w on w.id = j.worker_id "
            "where j.status = 'doing' and (w.id is null or w.last_heartbeat < now() - make_interval(secs => %s))",
            (stalled_after,)).fetchall()
    return [r[0] for r in rows]


def job_states(dsn: str, job_ids: list[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute("select id, status from procrastinate_jobs where id = any(%s)", (job_ids,)).fetchall()
    return {r[0]: r[1] for r in rows}
