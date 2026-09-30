"""The gateway's shared backends in Postgres (migrations/002_gateway.sql): a cache every
worker reads, one pace per provider across processes, and the per-project daily budget."""
from __future__ import annotations

import os
import time

import psycopg
from psycopg.types.json import Json

from app.llm.gateway import spacing


class PgCache:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]

    def get(self, key: str) -> str | None:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            row = c.execute("select value from llm_cache where key=%s", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str, meta: dict) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("insert into llm_cache (key, kind, chain, prompt_version, project, value) values (%s,%s,%s,%s,%s,%s) "
                      "on conflict (key) do nothing",
                      (key, meta.get("kind"), Json(meta.get("chain")), meta.get("prompt_version"), meta.get("project"), value))


class PgRateLimiter:
    """One row per provider key holding the next free slot. Every caller atomically
    takes the slot after the last one taken (or now) and sleeps until it, so calls
    from every worker are spaced `spacing(rpm)` apart no matter how many run."""

    def __init__(self, dsn: str | None = None, sleep=time.sleep):
        self.dsn = dsn or os.environ["DATABASE_URL"]
        self.sleep = sleep

    def acquire(self, key: str, rpm: int) -> float:
        gap = spacing(rpm)
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("insert into llm_rate_limit (key, next_slot) values (%s, now()) on conflict (key) do nothing", (key,))
            slot, now = c.execute(
                "update llm_rate_limit set next_slot = greatest(next_slot, now()) + make_interval(secs => %s) "
                "where key=%s returning extract(epoch from next_slot - make_interval(secs => %s)), extract(epoch from now())",
                (gap, key, gap)).fetchone()
        wait = max(float(slot) - float(now), 0.0)
        if wait > 0:
            self.sleep(wait)
        return wait


class PgBudget:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]

    def spent(self, project: str, day: str) -> tuple[int, float]:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            row = c.execute("select calls, usd from llm_budget where project=%s and day=%s", (project, day)).fetchone()
        return (row[0], float(row[1])) if row else (0, 0.0)

    def add(self, project: str, day: str, calls: int, usd: float) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("insert into llm_budget (project, day, calls, usd) values (%s,%s,%s,%s) on conflict (project, day) "
                      "do update set calls = llm_budget.calls + excluded.calls, usd = llm_budget.usd + excluded.usd",
                      (project, day, calls, usd))
