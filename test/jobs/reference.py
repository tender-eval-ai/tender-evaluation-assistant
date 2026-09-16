"""Reference adapter: the naive baseline, one subprocess per job with a run table and
nothing else. No retry, no heartbeat, no lease, no limiter. This is roughly what
"threads inside the API" gives today, and it is expected to fail the must-pass
scenarios; the harness has to show that it does.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Json

from test.jobs.adapters import Result, RunStatus
from test.jobs import slice as sl

SCHEMA = """
create table if not exists harness_runs (
  run_id text primary key, tender text not null, vendor text not null,
  state text not null, step text, progress jsonb not null default '{}'::jsonb,
  labels jsonb, fields jsonb, rubric_version int, worker_pid int, error text,
  updated_at double precision not null);
create table if not exists harness_rubrics (
  tender text primary key, version int not null, confirmed boolean not null, spec jsonb not null);
create table if not exists harness_results (
  run_id text primary key, vendor text not null, rubric_version int not null,
  fields jsonb not null, verdict jsonb not null, corrections jsonb not null default '{}'::jsonb);
"""


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie child counts as dead
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


class ReferenceAdapter:
    name = "reference"

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]
        self._procs: list[subprocess.Popen] = []

    def _conn(self):
        return psycopg.connect(self.dsn, autocommit=True)

    # ---------------------------------------------------------------- Orchestrator
    def setup(self) -> None:
        with self._conn() as c:
            c.execute(SCHEMA)
            c.execute("truncate harness_runs, harness_rubrics, harness_results")

    def start_check(self, tender: str, vendor: str) -> str:
        run_id = uuid.uuid4().hex[:8]
        with self._conn() as c:
            c.execute("insert into harness_runs (run_id, tender, vendor, state, updated_at) values (%s,%s,%s,'queued',%s)",
                      (run_id, tender, vendor, time.time()))
            c.execute("insert into harness_rubrics (tender, version, confirmed, spec) values (%s,1,false,%s) "
                      "on conflict (tender) do nothing", (tender, Json({"version": 1, "requires_signature": True,
                                                                        "requires_date": False})))
        self._spawn(run_id)
        return run_id

    def _spawn(self, run_id: str) -> None:
        proc = subprocess.Popen([sys.executable, "-m", "test.jobs.worker", self.name, run_id],
                                env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._procs.append(proc)
        with self._conn() as c:
            c.execute("update harness_runs set worker_pid=%s, updated_at=%s where run_id=%s", (proc.pid, time.time(), run_id))

    def status(self, run_id: str) -> RunStatus:
        with self._conn() as c:
            row = c.execute("select tender, vendor, state, step, progress, rubric_version, worker_pid, updated_at, error "
                            "from harness_runs where run_id=%s", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        tender, vendor, state, step, progress, version, pid, updated, error = row
        if state in ("running", "paused") and not _pid_alive(pid):
            state = "lost"      # the naive baseline notices only when asked
        return RunStatus(run_id, tender, vendor, state, step, progress, version, pid, updated, error)

    def results(self, run_id: str) -> Result | None:
        with self._conn() as c:
            row = c.execute("select vendor, rubric_version, fields, verdict, corrections from harness_results "
                            "where run_id=%s", (run_id,)).fetchone()
        return Result(run_id, *row) if row else None

    def confirm_rubric(self, tender: str) -> int:
        with self._conn() as c:
            c.execute("update harness_rubrics set confirmed=true where tender=%s", (tender,))
            return c.execute("select version from harness_rubrics where tender=%s", (tender,)).fetchone()[0]

    def edit_rubric(self, tender: str, patch: dict) -> None:
        with self._conn() as c:
            spec = c.execute("select spec from harness_rubrics where tender=%s", (tender,)).fetchone()[0]
            spec.update(patch)
            c.execute("update harness_rubrics set spec=%s where tender=%s", (Json(spec), tender))

    def publish_rubric_version(self, tender: str, patch: dict) -> int:
        with self._conn() as c:
            version, spec = c.execute("select version, spec from harness_rubrics where tender=%s", (tender,)).fetchone()
            version += 1
            spec.update(patch)
            spec["version"] = version
            c.execute("update harness_rubrics set version=%s, spec=%s, confirmed=true where tender=%s",
                      (version, Json(spec), tender))
            rows = c.execute("select r.run_id, r.fields, r.corrections from harness_results r join harness_runs u "
                             "on u.run_id=r.run_id where u.tender=%s", (tender,)).fetchall()
            for run_id, fields, corrections in rows:     # engine only: no LLM
                verdict = sl.decide({**fields, **corrections}, spec)
                c.execute("update harness_results set verdict=%s, rubric_version=%s where run_id=%s",
                          (Json(verdict), version, run_id))
        return version

    def correct_field(self, run_id: str, item: str, name: str, value: Any, reason: str) -> Result:
        with self._conn() as c:
            row = c.execute("select r.fields, r.corrections, b.spec from harness_results r join harness_runs u "
                            "on u.run_id=r.run_id join harness_rubrics b on b.tender=u.tender where r.run_id=%s",
                            (run_id,)).fetchone()
            fields, corrections, spec = row
            corrections[name] = {"value": value, "reason": reason, "model_value": fields.get(name)}
            verdict = sl.decide({**fields, name: value}, spec)
            c.execute("update harness_results set corrections=%s, verdict=%s where run_id=%s",
                      (Json(corrections), Json(verdict), run_id))
        return self.results(run_id)

    def rerun(self, run_id: str) -> str:
        with self._conn() as c:   # naive: start over, forget everything the run had
            c.execute("update harness_runs set state='queued', step=null, progress='{}', labels=null, fields=null, "
                      "error=null, updated_at=%s where run_id=%s", (time.time(), run_id))
        self._spawn(run_id)
        return run_id

    def list_stuck(self) -> list[dict]:
        out = []
        with self._conn() as c:
            rows = c.execute("select run_id, vendor, state, step, worker_pid, updated_at from harness_runs "
                             "where state in ('running','paused')").fetchall()
        for run_id, vendor, state, step, pid, updated in rows:
            if not _pid_alive(pid):
                out.append({"run_id": run_id, "vendor": vendor, "why": f"worker {pid} is gone during {step}",
                            "since": updated})
        return out

    def workers(self) -> list[int]:
        return [p.pid for p in self._procs if p.poll() is None]

    def shutdown(self) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.kill()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    # ---------------------------------------------------------------- worker side
    def execute(self, run_id: str) -> None:
        """Runs inside the worker subprocess. Progress is saved after every triage batch,
        but nothing ever resumes from it: a killed worker is simply gone."""
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # no graceful drain: die like a naive process
        with self._conn() as c:
            tender, vendor = c.execute("select tender, vendor from harness_runs where run_id=%s", (run_id,)).fetchone()
        cert_page = int(os.environ.get("CERT_PAGE", "13"))
        bid = sl.make_vendor(vendor, int(os.environ.get("N_PAGES", "16")), cert_page)
        llm = sl.make_llm(cert_page)

        def save(**cols):
            sets = ", ".join(f"{k}=%s" for k in cols)
            with self._conn() as c:
                c.execute(f"update harness_runs set {sets}, updated_at=%s where run_id=%s",
                          (*[Json(v) if isinstance(v, (dict, list)) else v for v in cols.values()], time.time(), run_id))

        def progress(step, done, total):
            save(state="running", step=step, progress={"done": done, "total": total, "unit": "pages"})

        try:
            with llm.scope(vendor):
                save(state="running", step="triage", progress={"done": 0, "total": len(bid["pages"]), "unit": "pages"})
                labels = sl.triage(bid["pages"], vendor, llm, progress)
                save(labels=labels, step="resolve")
                item_pages = sl.resolve(labels, vendor, llm)
                save(step="extract")
                fields = sl.extract(bid["pages"], item_pages, vendor, llm).model_dump()
                save(fields=fields, step="await_rubric", state="paused")
                while True:   # pause until a person confirms the rubric
                    with self._conn() as c:
                        version, confirmed, spec = c.execute(
                            "select version, confirmed, spec from harness_rubrics where tender=%s", (tender,)).fetchone()
                    if confirmed:
                        break
                    time.sleep(0.2)
                if os.environ.get("SLICE_EXTRA_STEP"):
                    save(step="extra_step", state="running")
                    fields["extra_step"] = True
                save(step="decide", state="running")
                verdict = sl.decide(fields, spec)
                with self._conn() as c:
                    c.execute("insert into harness_results (run_id, vendor, rubric_version, fields, verdict) values "
                              "(%s,%s,%s,%s,%s) on conflict (run_id) do update set fields=excluded.fields, "
                              "verdict=excluded.verdict, rubric_version=excluded.rubric_version, corrections='{}'",
                              (run_id, vendor, version, Json(fields), Json(verdict)))
                save(state="done", step=None, rubric_version=version)
        except Exception as err:      # noqa: BLE001 - the baseline reports and stops
            save(state="failed", error=f"{type(err).__name__}: {err}")
            raise
