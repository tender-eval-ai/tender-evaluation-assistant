"""Runs, per-step progress, results with corrections, and rule-set versions, in
Postgres (migrations/001_jobs.sql). The store is the app-owned state the API reads;
the queue's own tables belong to Procrastinate."""
from __future__ import annotations

import os
import uuid
from typing import Any, Callable

import psycopg
from psycopg.types.json import Json

from app.checks.fields import is_meta
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

    def latest_run(self, project: str, tenderer: str, done_only: bool = False) -> dict | None:
        where = "project=%s and tenderer=%s" + (" and state='done'" if done_only else "")
        rows = self.runs_where(where, (project, tenderer))
        return rows[-1] if rows else None

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
            row = c.execute("select run_id, project, tenderer, ruleset_version, fields, verdict, corrections, "
                            "review_confirmed_by, extract(epoch from review_confirmed_at) from results where run_id=%s",
                            (run_id,)).fetchone()
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
        return self.correct_fields(run_id, {name: value}, reason, by, decide)

    def correct_fields(self, run_id: str, values: dict[str, Any], reason: str, by: str,
                       decide: Callable[[dict, dict], dict]) -> Result:
        """A human correction of one or more keys (a value and its page, say): each kept beside
        the model's value, the verdict re-decided at once, a review confirmation withdrawn
        because the verdict may have changed."""
        with self.conn() as c:
            row = c.execute("select r.fields, r.corrections, r.ruleset_version, s.spec from results r "
                            "join rulesets s on s.project=r.project and s.version=r.ruleset_version "
                            "where r.run_id=%s", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            fields, corrections, version, spec = row
            for name, value in values.items():
                corrections[name] = {"value": value, "reason": reason, "by": by, "model_value": fields.get(name)}
            c.execute("update results set corrections=%s, verdict=%s, review_confirmed_by=null, review_confirmed_at=null, "
                      "updated_at=now() where run_id=%s",
                      (Json(corrections), Json(decide(_apply(fields, corrections), spec)), run_id))
        return self.results(run_id)

    def confirm_review(self, run_id: str, by: str) -> Result:
        with self.conn() as c:
            c.execute("update results set review_confirmed_by=%s, review_confirmed_at=now(), updated_at=now() where run_id=%s",
                      (by, run_id))
        return self.results(run_id)

    def project_results(self, project: str) -> list[Result]:
        with self.conn() as c:
            rows = c.execute("select run_id, project, tenderer, ruleset_version, fields, verdict, corrections, "
                             "review_confirmed_by, extract(epoch from review_confirmed_at) from results where project=%s "
                             "order by tenderer", (project,)).fetchall()
        return [Result(*r) for r in rows]

    def redecide(self, project: str, version: int, spec: dict, decide_for: Callable[[str], Callable[[dict, dict], dict]]) -> list[dict]:
        """Every stored result of the project re-decided against `spec` (rule-set `version`)
        and pinned to it. Engine only. A result whose verdict changed loses its review
        confirmation. Returns one row per result: run_id, tenderer, before, after, changed."""
        out = []
        with self.conn() as c:
            rows = c.execute("select r.run_id, r.tenderer, r.fields, r.corrections, r.verdict, u.kind from results r "
                             "join runs u on u.run_id=r.run_id where r.project=%s order by r.tenderer", (project,)).fetchall()
            for run_id, tenderer, fields, corrections, before, kind in rows:
                after = decide_for(kind)(_apply(fields, corrections), spec)
                changed = not _same_verdict(before, after)          # the version stamp alone is not a change
                if changed:
                    c.execute("update results set verdict=%s, ruleset_version=%s, review_confirmed_by=null, "
                              "review_confirmed_at=null, updated_at=now() where run_id=%s", (Json(after), version, run_id))
                else:
                    c.execute("update results set verdict=%s, ruleset_version=%s, updated_at=now() where run_id=%s",
                              (Json(after), version, run_id))
                out.append({"run_id": run_id, "tenderer": tenderer, "before": before, "after": after, "changed": changed})
        return out

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

    def versions(self, project: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("select version, status, parent_version, created_by, extract(epoch from created_at), "
                             "confirmed_by, extract(epoch from confirmed_at), updated_by from rulesets where project=%s "
                             "order by version", (project,)).fetchall()
        keys = ["version", "status", "parent_version", "created_by", "created_at", "confirmed_by", "confirmed_at", "updated_by"]
        return [dict(zip(keys, r)) for r in rows]

    def editor_of(self, project: str, version: int | None) -> str | None:
        """Who last saved that version's draft (the server-owned `updated_by`)."""
        if version is None:
            return None
        with self.conn() as c:
            row = c.execute("select updated_by from rulesets where project=%s and version=%s", (project, version)).fetchone()
        return row[0] if row else None

    def get_version(self, project: str, version: int) -> dict | None:
        with self.conn() as c:
            row = c.execute("select spec from rulesets where project=%s and version=%s", (project, version)).fetchone()
        return row[0] if row else None

    def save_draft(self, project: str, spec: dict, user: str) -> tuple[int, bool]:
        """Replace the open draft, or open a new one after the latest confirmed version.
        Returns (version, created)."""
        with self.conn() as c:
            row = c.execute("select version from rulesets where project=%s and status='draft' order by version desc limit 1",
                            (project,)).fetchone()
            if row:
                version = row[0]
                c.execute("update rulesets set spec=%s, updated_by=%s where project=%s and version=%s",
                          (Json({**spec, "version": version}), user, project, version))
                return version, False
            latest = c.execute("select max(version) from rulesets where project=%s", (project,)).fetchone()[0]
            confirmed = c.execute("select max(version) from rulesets where project=%s and status='confirmed'",
                                  (project,)).fetchone()[0]
            version = (latest or 0) + 1
            c.execute("insert into rulesets (project, version, status, spec, created_by, updated_by, parent_version) "
                      "values (%s,%s,'draft',%s,%s,%s,%s)",
                      (project, version, Json({**spec, "version": version, "parent_version": confirmed}), user, user, confirmed))
            return version, True

    def confirm(self, project: str, user: str = "system") -> int:
        """Confirm the latest draft as `user` (a person from the API, else "system", since
        a confirmed rule set records who confirmed it). Returns the confirmed version (the
        latest one when there is no draft)."""
        with self.conn() as c:
            row = c.execute("update rulesets set status='confirmed', confirmed_at=now(), confirmed_by=%s, "
                            "spec = spec || jsonb_build_object('status', 'confirmed', 'confirmed_by', %s::text, "
                            "'confirmed_at', to_char(now() at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')) "
                            "where project=%s and version = (select max(version) from rulesets where project=%s "
                            "and status='draft') returning version", (user, user, project, project)).fetchone()
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

    # ---------------------------------------------------------------- audit
    def event(self, kind: str, project: str, subject: str | None, before: Any, after: Any, actor: str,
              reason: str | None = None) -> int:
        with self.conn() as c:
            return c.execute("insert into events (kind, project, subject, before, after, actor, reason) "
                             "values (%s,%s,%s,%s,%s,%s,%s) returning id",
                             (kind, project, subject, Json(before), Json(after), actor, reason)).fetchone()[0]

    def events(self, project: str, kind: str | None = None, after_id: int = 0, since: float | None = None,
               limit: int = 100) -> list[dict]:
        where, params = ["project=%s", "id > %s"], [project, after_id]
        if kind:
            where.append("kind=%s")
            params.append(kind)
        if since is not None:
            where.append("at >= to_timestamp(%s)")
            params.append(since)
        with self.conn() as c:
            rows = c.execute(f"select id, kind, project, subject, before, after, actor, reason, extract(epoch from at) "
                             f"from events where {' and '.join(where)} order by id limit %s", (*params, limit)).fetchall()
        keys = ["id", "kind", "project", "subject", "before", "after", "user", "reason", "at"]
        return [dict(zip(keys, r)) for r in rows]


def _same_verdict(a: dict, b: dict) -> bool:
    """Equal apart from the rule-set version each was decided against."""
    strip = lambda v: {k: x for k, x in (v or {}).items() if k != "ruleset_version"}  # noqa: E731
    return strip(a) == strip(b)


def _apply(fields: dict, corrections: dict) -> dict:
    """The fields as the engine should see them: each corrected key holds the person's value,
    and its V4 record and its printed text are dropped (a person's value is not the model's
    reading to verify, and a check counting decimals as printed must count the person's)."""
    out = {**fields, **{k: v["value"] for k, v in corrections.items()}}
    for k in corrections:
        if not is_meta(k):
            out[f"{k}_verification"] = None
            out.pop(f"{k}_printed", None)
    return out
