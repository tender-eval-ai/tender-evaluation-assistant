"""Plain-SQL migrations: migrations/NNN_name.sql, applied in order, recorded in
schema_migrations. Each file has a `-- migrate:up` and a `-- migrate:down` section so
a migration can be reversed (the pull request checklist asks for it)."""
from __future__ import annotations

import os
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
UP, DOWN = "-- migrate:up", "-- migrate:down"


def split(sql: str) -> tuple[str, str]:
    """The up and down parts of a migration file."""
    if UP not in sql or DOWN not in sql:
        raise ValueError(f"a migration needs both {UP!r} and {DOWN!r} sections")
    _, rest = sql.split(UP, 1)
    up, down = rest.split(DOWN, 1)
    return up.strip(), down.strip()


def files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(p for p in directory.glob("*.sql") if p.name[:3].isdigit())


def _connect(dsn: str | None):
    import psycopg
    return psycopg.connect(dsn or os.environ["DATABASE_URL"], autocommit=True)


def applied(dsn: str | None = None) -> list[str]:
    with _connect(dsn) as c:
        c.execute("create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())")
        return [r[0] for r in c.execute("select name from schema_migrations order by name").fetchall()]


def migrate(dsn: str | None = None, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration not yet recorded. Returns the names applied now."""
    done = set(applied(dsn))
    ran = []
    for path in files(directory):
        if path.stem in done:
            continue
        up, _ = split(path.read_text())
        with _connect(dsn) as c, c.transaction():
            c.execute(up)
            c.execute("insert into schema_migrations (name) values (%s)", (path.stem,))
        ran.append(path.stem)
    return ran


def rollback(name: str, dsn: str | None = None, directory: Path = MIGRATIONS_DIR) -> None:
    """Reverse one applied migration by name."""
    path = directory / f"{name}.sql"
    _, down = split(path.read_text())
    with _connect(dsn) as c, c.transaction():
        c.execute(down)
        c.execute("delete from schema_migrations where name=%s", (name,))


def reset_for_tests(dsn: str | None = None) -> None:
    """Drop the app's tables and empty Procrastinate's, so a test starts from nothing."""
    with _connect(dsn) as c:
        c.execute("drop table if exists results, job_steps, rulesets, runs, llm_cache, llm_rate_limit, llm_budget, "
                  "events, schema_migrations cascade")
        if c.execute("select to_regclass('procrastinate_jobs')").fetchone()[0]:
            c.execute("truncate procrastinate_jobs, procrastinate_events, procrastinate_periodic_defers, "
                      "procrastinate_workers restart identity")
