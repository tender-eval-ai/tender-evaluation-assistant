"""Runs, per-step progress, results with corrections, and rule-set versions, in
Postgres (migrations/001_jobs.sql). The store is the app-owned state the API reads;
the queue's own tables belong to Procrastinate."""
from __future__ import annotations

import os
import uuid
from typing import Any, Callable

import psycopg
from psycopg.types.json import Json

from app.jobs.models import Result, RunStatus

_RUN_COLS = ("run_id", "project", "tenderer", "kind", "state", "step", "progress", "attempt", "job_id",
             "worker_pid", "ruleset_version", "error", "updated_at")
_RUN_SELECT = ("select run_id, project, tenderer, kind, state, step, progress, attempt, job_id, worker_pid, "
               "ruleset_version, error, extract(epoch from updated_at) from runs")


def _j(v: Any) -> Any:
    return Json(v) if isinstance(v, (dict, list)) else v


class Store:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]

    def conn(self):
        return psycopg.connect(self.dsn, autocommit=True)

    # ---------------------------------------------------------------- runs
    def active_run(self, project: str, tenderer: str) -> str | None:
        with self.conn() as c:
            row = c.execute("select run_id from runs where project=%s and tenderer=%s and "
                            "state in ('queued','running','paused') order by created_at desc limit 1",
                            (project, tenderer)).fetchone()
        return row[0] if row else None

    def create_run(self, project: str, tenderer: str, kind: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self.conn() as c:
            c.execute("insert into runs (run_id, project, tenderer, kind, state) values (%s,%s,%s,%s,'queued')",
                      (run_id, project, tenderer, kind))
        return run_id

    def update_run(self, run_id: str, **cols: Any) -> None:
        sets = ", ".join(f"{k}=%s" for k in cols)
        with self.conn() as c:
            c.execute(f"update runs set {sets}, updated_at=now() where run_id=%s", (*[_j(v) for v in cols.values()], run_id))

    def transition(self, run_id: str, from_states: tuple[str, ...], **cols: Any) -> bool:
        """Conditional update: only one caller wins when several see the same state."""
        sets = ", ".join(f"{k}=%s" for k in cols)
        with self.conn() as c:
            cur = c.execute(f"update runs set {sets}, updated_at=now() where run_id=%s and state = any(%s)",
                            (*[_j(v) for v in cols.values()], run_id, list(from_states)))
            return cur.rowcount == 1

    def run(self, run_id: str) -> dict:
        with self.conn() as c:
            row = c.execute(f"{_RUN_SELECT} where run_id=%s", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(zip(_RUN_COLS, row))

    def runs_where(self, where: str, params: tuple = ()) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(f"{_RUN_SELECT} where {where} order by created_at", params).fetchall()
        return [dict(zip(_RUN_COLS, r)) for r in rows]

    def status(self, run_id: str) -> RunStatus:
        return RunStatus(**self.run(run_id))

    # ---------------------------------------------------------------- steps
    def steps(self, run_id: str) -> dict:
        with self.conn() as c:
            row = c.execute("select done, data from job_steps where run_id=%s", (run_id,)).fetchone()
        return {"done": list(row[0]), "data": dict(row[1])} if row else {"done": [], "data": {}}

    def save_steps(self, run_id: str, done: list[str], data: dict) -> None:
        with self.conn() as c:
            c.execute("insert into job_steps (run_id, done, data) values (%s,%s,%s) on conflict (run_id) do update "
                      "set done=excluded.done, data=excluded.data, updated_at=now()", (run_id, Json(done), Json(data)))

    def clear_steps(self, run_id: str) -> None:
        with self.conn() as c:
            c.execute("delete from job_steps where run_id=%s", (run_id,))

    # ---------------------------------------------------------------- results
    def results(self, run_id: str) -> Result | None:
        with self.conn() as c:
            row = c.execute("select run_id, project, tenderer, ruleset_version, fields, verdict, corrections "
                            "from results where run_id=%s", (run_id,)).fetchone()
        return Result(*row) if row else None

    def store_result(self, run_id: str, project: str, tenderer: str, version: int, fields: dict, spec: dict,
                     decide: Callable[[dict, dict], dict]) -> dict:
        """Store the fields and the verdict. Corrections already recorded for this run are
        kept and applied, so a re-run never silently undoes a reviewer's decision."""
        with self.conn() as c:
            row = c.execute("select corrections from results where run_id=%s", (run_id,)).fetchone()
            corrections = row[0] if row else {}
            verdict = decide(_apply(fields, corrections), spec)
            c.execute("insert into results (run_id, project, tenderer, ruleset_version, fields, verdict, corrections) "
                      "values (%s,%s,%s,%s,%s,%s,%s) on conflict (run_id) do update set fields=excluded.fields, "
                      "verdict=excluded.verdict, ruleset_version=excluded.ruleset_version, updated_at=now()",
                      (run_id, project, tenderer, version, Json(fields), Json(verdict), Json(corrections)))
        return verdict

    def correct_field(self, run_id: str, name: str, value: Any, reason: str, by: str,
                      decide: Callable[[dict, dict], dict]) -> Result:
        """A human correction: kept beside the model's value, verdict re-decided at once."""
        with self.conn() as c:
            row = c.execute("select r.fields, r.corrections, r.ruleset_version, s.spec from results r "
                            "join rulesets s on s.project=r.project and s.version=r.ruleset_version "
                            "where r.run_id=%s", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            fields, corrections, version, spec = row
            corrections[name] = {"value": value, "reason": reason, "by": by, "model_value": fields.get(name)}
            c.execute("update results set corrections=%s, verdict=%s, updated_at=now() where run_id=%s",
                      (Json(corrections), Json(decide(_apply(fields, corrections), spec)), run_id))
        return self.results(run_id)

    # ---------------------------------------------------------------- rule sets
    def ensure_draft(self, project: str, spec: dict) -> int:
        """Create version 1 as a draft when the project has no rule set at all."""
        with self.conn() as c:
            c.execute("insert into rulesets (project, version, status, spec) values (%s,1,'draft',%s) "
                      "on conflict (project, version) do nothing", (project, Json({**spec, "version": 1})))
            return c.execute("select max(version) from rulesets where project=%s", (project,)).fetchone()[0]

    def draft(self, project: str) -> tuple[int, dict] | None:
        with self.conn() as c:
            row = c.execute("select version, spec from rulesets where project=%s and status='draft' "
                            "order by version desc limit 1", (project,)).fetchone()
        return (row[0], row[1]) if row else None

    def patch_draft(self, project: str, patch: dict) -> int:
        with self.conn() as c:
            version, spec = c.execute("select version, spec from rulesets where project=%s and status='draft' "
                                      "order by version desc limit 1", (project,)).fetchone()
            spec.update(patch)
            c.execute("update rulesets set spec=%s where project=%s and version=%s", (Json(spec), project, version))
        return version

    def confirm(self, project: str) -> int:
        """Confirm the latest draft. Returns the confirmed version (the latest one when
        there is no draft)."""
        with self.conn() as c:
            row = c.execute("update rulesets set status='confirmed', confirmed_at=now() where project=%s and "
                            "version = (select max(version) from rulesets where project=%s and status='draft') "
                            "returning version", (project, project)).fetchone()
            if row:
                return row[0]
            return c.execute("select max(version) from rulesets where project=%s and status='confirmed'",
                             (project,)).fetchone()[0]

    def latest_confirmed(self, project: str) -> tuple[int, dict] | None:
        with self.conn() as c:
            row = c.execute("select version, spec from rulesets where project=%s and status='confirmed' "
                            "order by version desc limit 1", (project,)).fetchone()
        return (row[0], row[1]) if row else None

    def publish(self, project: str, patch: dict, decide_for: Callable[[str], Callable[[dict, dict], dict]]) -> int:
        """A new confirmed version from the latest spec plus `patch`, and every stored
        result of the project re-decided against it. Engine only: no LLM call."""
        with self.conn() as c:
            version, spec = c.execute("select version, spec from rulesets where project=%s order by version desc limit 1",
                                      (project,)).fetchone()
            version += 1
            spec = {**spec, **patch, "version": version}
            c.execute("insert into rulesets (project, version, status, spec, confirmed_at) values (%s,%s,'confirmed',%s,now())",
                      (project, version, Json(spec)))
            rows = c.execute("select r.run_id, r.fields, r.corrections, u.kind from results r join runs u on u.run_id=r.run_id "
                             "where r.project=%s", (project,)).fetchall()
            for run_id, fields, corrections, kind in rows:
                verdict = decide_for(kind)(_apply(fields, corrections), spec)
                c.execute("update results set verdict=%s, ruleset_version=%s, updated_at=now() where run_id=%s",
                          (Json(verdict), version, run_id))
        return version


def _apply(fields: dict, corrections: dict) -> dict:
    return {**fields, **{k: v["value"] for k, v in corrections.items()}}
