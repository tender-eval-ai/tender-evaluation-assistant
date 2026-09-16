"""Runs, rubrics and results for a variant, in Postgres tables with a prefix. Results and
corrections are the shared, app-owned state both variants publish into; how a variant
tracks progress (checkpoints or a job_steps table) is its own business."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Json

from test.jobs import slice as sl
from test.jobs.adapters import Result, RunStatus

DEFAULT_RUBRIC = {"version": 1, "requires_signature": True, "requires_date": False}


class Store:
    def __init__(self, prefix: str, dsn: str | None = None):
        self.p = prefix
        self.dsn = dsn or os.environ["DATABASE_URL"]

    def conn(self):
        return psycopg.connect(self.dsn, autocommit=True)

    def reset(self) -> None:
        p = self.p
        with self.conn() as c:
            c.execute(f"drop table if exists {p}_runs, {p}_rubrics, {p}_results")   # schema may have changed
            c.execute(f"""
            create table if not exists {p}_runs (
              run_id text primary key, tender text not null, vendor text not null, state text not null,
              step text, progress jsonb not null default '{{}}'::jsonb, attempt int not null default 1,
              job_id bigint, worker_pid int, rubric_version int, error text, updated_at double precision not null);
            create table if not exists {p}_rubrics (
              tender text primary key, version int not null, confirmed boolean not null, spec jsonb not null);
            create table if not exists {p}_results (
              run_id text primary key, vendor text not null, rubric_version int not null,
              fields jsonb not null, verdict jsonb not null, corrections jsonb not null default '{{}}'::jsonb);
            """)

    # ---------------------------------------------------------------- runs
    def active_run(self, tender: str, vendor: str) -> str | None:
        with self.conn() as c:
            row = c.execute(f"select run_id from {self.p}_runs where tender=%s and vendor=%s and "
                            "state in ('queued','running','paused')", (tender, vendor)).fetchone()
        return row[0] if row else None

    def create_run(self, tender: str, vendor: str) -> str:
        run_id = uuid.uuid4().hex[:8]
        with self.conn() as c:
            c.execute(f"insert into {self.p}_runs (run_id, tender, vendor, state, updated_at) values (%s,%s,%s,'queued',%s)",
                      (run_id, tender, vendor, time.time()))
            c.execute(f"insert into {self.p}_rubrics (tender, version, confirmed, spec) values (%s,1,false,%s) "
                      "on conflict (tender) do nothing", (tender, Json(dict(DEFAULT_RUBRIC))))
        return run_id

    def update_run(self, run_id: str, **cols) -> None:
        sets = ", ".join(f"{k}=%s" for k in cols)
        with self.conn() as c:
            c.execute(f"update {self.p}_runs set {sets}, updated_at=%s where run_id=%s",
                      (*[Json(v) if isinstance(v, (dict, list)) else v for v in cols.values()], time.time(), run_id))

    def run(self, run_id: str) -> dict:
        with self.conn() as c:
            row = c.execute(f"select run_id, tender, vendor, state, step, progress, attempt, job_id, rubric_version, "
                            f"error, updated_at, worker_pid from {self.p}_runs where run_id=%s", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        keys = ["run_id", "tender", "vendor", "state", "step", "progress", "attempt", "job_id", "rubric_version",
                "error", "updated_at", "worker_pid"]
        return dict(zip(keys, row))

    def runs_where(self, where: str, params: tuple = ()) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(f"select run_id, tender, vendor, state, step, job_id, updated_at from {self.p}_runs "
                             f"where {where}", params).fetchall()
        return [dict(zip(["run_id", "tender", "vendor", "state", "step", "job_id", "updated_at"], r)) for r in rows]

    def status(self, run_id: str, worker_pid: int | None = None) -> RunStatus:
        r = self.run(run_id)
        return RunStatus(r["run_id"], r["tender"], r["vendor"], r["state"], r["step"], r["progress"],
                         r["rubric_version"], worker_pid or r["worker_pid"], r["updated_at"], r["error"])

    # ---------------------------------------------------------------- rubric
    def rubric(self, tender: str) -> tuple[int, bool, dict]:
        with self.conn() as c:
            return c.execute(f"select version, confirmed, spec from {self.p}_rubrics where tender=%s", (tender,)).fetchone()

    def confirm_rubric(self, tender: str) -> int:
        with self.conn() as c:
            c.execute(f"update {self.p}_rubrics set confirmed=true where tender=%s", (tender,))
            return c.execute(f"select version from {self.p}_rubrics where tender=%s", (tender,)).fetchone()[0]

    def edit_rubric(self, tender: str, patch: dict) -> None:
        with self.conn() as c:
            spec = c.execute(f"select spec from {self.p}_rubrics where tender=%s", (tender,)).fetchone()[0]
            spec.update(patch)
            c.execute(f"update {self.p}_rubrics set spec=%s where tender=%s", (Json(spec), tender))

    def publish_rubric_version(self, tender: str, patch: dict) -> int:
        with self.conn() as c:
            version, spec = c.execute(f"select version, spec from {self.p}_rubrics where tender=%s", (tender,)).fetchone()
            version += 1
            spec.update(patch)
            spec["version"] = version
            c.execute(f"update {self.p}_rubrics set version=%s, spec=%s, confirmed=true where tender=%s",
                      (version, Json(spec), tender))
            rows = c.execute(f"select r.run_id, r.fields, r.corrections from {self.p}_results r join {self.p}_runs u "
                             "on u.run_id=r.run_id where u.tender=%s", (tender,)).fetchall()
            for run_id, fields, corrections in rows:      # engine only, no LLM
                merged = {**fields, **{k: v["value"] for k, v in corrections.items()}}
                c.execute(f"update {self.p}_results set verdict=%s, rubric_version=%s where run_id=%s",
                          (Json(sl.decide(merged, spec)), version, run_id))
        return version

    # ---------------------------------------------------------------- results
    def results(self, run_id: str) -> Result | None:
        with self.conn() as c:
            row = c.execute(f"select vendor, rubric_version, fields, verdict, corrections from {self.p}_results "
                            "where run_id=%s", (run_id,)).fetchone()
        return Result(run_id, *row) if row else None

    def store_result(self, run_id: str, vendor: str, version: int, fields: dict, spec: dict) -> dict:
        """Store fields and the verdict. Corrections already recorded for this run are kept
        and applied, so a re-run never silently undoes a reviewer's decision."""
        with self.conn() as c:
            row = c.execute(f"select corrections from {self.p}_results where run_id=%s", (run_id,)).fetchone()
            corrections = row[0] if row else {}
            merged = {**fields, **{k: v["value"] for k, v in corrections.items()}}
            verdict = sl.decide(merged, spec)
            c.execute(f"insert into {self.p}_results (run_id, vendor, rubric_version, fields, verdict, corrections) "
                      "values (%s,%s,%s,%s,%s,%s) on conflict (run_id) do update set fields=excluded.fields, "
                      "verdict=excluded.verdict, rubric_version=excluded.rubric_version",
                      (run_id, vendor, version, Json(fields), Json(verdict), Json(corrections)))
        return verdict

    def correct_field(self, run_id: str, name: str, value: Any, reason: str) -> Result:
        with self.conn() as c:
            fields, corrections, spec = c.execute(
                f"select r.fields, r.corrections, b.spec from {self.p}_results r join {self.p}_runs u on u.run_id=r.run_id "
                f"join {self.p}_rubrics b on b.tender=u.tender where r.run_id=%s", (run_id,)).fetchone()
            corrections[name] = {"value": value, "reason": reason, "model_value": fields.get(name)}
            merged = {**fields, **{k: v["value"] for k, v in corrections.items()}}
            c.execute(f"update {self.p}_results set corrections=%s, verdict=%s where run_id=%s",
                      (Json(corrections), Json(sl.decide(merged, spec)), run_id))
        return self.results(run_id)


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True)
