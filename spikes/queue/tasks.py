"""The slice as one Procrastinate job that saves its own progress in a job_steps table and
pauses by status.

Design decisions (see docs/spikes/slice_spec.md, section 3):
1. Progress lives in q_steps: labels so far and the next batch index after every triage
   batch, then the resolved pages, then the extracted fields. A job that starts (or is
   retried, or is resumed) reads the row and continues from the first missing piece.
2. The pause is a status: the job writes `paused` when the rubric is not confirmed and
   returns; confirmation defers the same job again, which finds the fields saved and
   goes straight to the decision. The job re-reads the flag after marking itself paused,
   which closes the race with a confirmation written in between.
3. Takeover is the queue's: a stalled job is retried and any worker continues from
   q_steps.
4. Provider errors: a transient error fails the job, the retry strategy re-runs it, and
   it continues from q_steps; a permanent error ends the job as failed.
5. No LLM cache: the batch granularity of point 1 is what limits repeated calls.
"""
from __future__ import annotations

import os

import psycopg
from psycopg.types.json import Json

from spikes.common.queue import QUEUE, TransientRetry, make_app
from spikes.common.store import Store
from test.jobs import knobs
from test.jobs import slice as sl

app = make_app()
store = Store("q")

STEPS_SQL = """
create table if not exists q_steps (
  run_id text primary key, next_batch int not null default 0, labels jsonb not null default '[]'::jsonb,
  item_pages jsonb, fields jsonb);
"""


def _steps(run_id: str) -> dict:
    with psycopg.connect(store.dsn, autocommit=True) as c:
        row = c.execute("select next_batch, labels, item_pages, fields from q_steps where run_id=%s", (run_id,)).fetchone()
    if row is None:
        return {"next_batch": 0, "labels": [], "item_pages": None, "fields": None}
    return dict(zip(["next_batch", "labels", "item_pages", "fields"], row))


def _save(run_id: str, **cols) -> None:
    sets = ", ".join(f"{k}=excluded.{k}" for k in cols)
    with psycopg.connect(store.dsn, autocommit=True) as c:
        c.execute(f"insert into q_steps (run_id, {', '.join(cols)}) values (%s, {', '.join('%s' for _ in cols)}) "
                  f"on conflict (run_id) do update set {sets}",
                  (run_id, *[Json(v) if isinstance(v, (dict, list)) else v for v in cols.values()]))


def _run(run_id: str) -> None:
    run = store.run(run_id)
    cert_page = int(knobs.get("CERT_PAGE", "13"))
    n_pages = int(knobs.get("N_PAGES", "16"))
    bid = sl.make_vendor(run["vendor"], n_pages, cert_page)
    llm = sl.make_llm(cert_page)
    st = _steps(run_id)

    def progress(step: str, done: int, total: int) -> None:
        store.update_run(run_id, state="running", step=step, progress={"done": done, "total": total, "unit": "pages"})

    store.update_run(run_id, worker_pid=os.getpid())    # which process holds the job (the harness kills it)
    try:
        with llm.scope(run["vendor"]):
            labels, next_batch = st["labels"], st["next_batch"]
            while next_batch < n_pages:                                  # one batch, then save
                labels += sl.triage(bid["pages"], run["vendor"], llm, progress, start_at=next_batch, max_batches=1)
                next_batch = min(next_batch + sl.PAGES_PER_TRIAGE, n_pages)
                _save(run_id, labels=labels, next_batch=next_batch)
            if st["item_pages"] is None:
                progress("resolve", 0, 1)
                st["item_pages"] = sl.resolve(labels, run["vendor"], llm).model_dump()
                _save(run_id, item_pages=st["item_pages"])
            if st["fields"] is None:
                progress("extract", 0, 1)
                item_pages = sl.ItemPages.model_validate(st["item_pages"])
                st["fields"] = sl.extract(bid["pages"], item_pages, run["vendor"], llm).model_dump()
                _save(run_id, fields=st["fields"])
            version, confirmed, spec = store.rubric(run["tender"])
            if not confirmed:
                store.update_run(run_id, state="paused", step="await_rubric")
                version, confirmed, spec = store.rubric(run["tender"])   # re-read: closes the race
                if not confirmed:
                    return
                store.update_run(run_id, state="running", step="resuming")
            fields = dict(st["fields"])
            if knobs.get("SLICE_EXTRA_STEP"):                              # a step deployed later applies to paused runs
                progress("extra_step", 1, 1)
                fields["extra_step"] = True
            progress("decide", 0, 1)
            store.store_result(run_id, run["vendor"], version, fields, spec)
            store.update_run(run_id, state="done", step=None, rubric_version=version)
    except Exception as err:
        transient = getattr(err, "transient", False)
        store.update_run(run_id, state="running" if transient else "failed", error=f"{type(err).__name__}: {err}")
        raise


@app.task(queue=QUEUE, retry=TransientRetry(), pass_context=True)
def run_slice(context, run_id: str) -> None:
    _run(run_id)


@app.task(queue=QUEUE, retry=TransientRetry(), pass_context=True)
def resume_run(context, run_id: str) -> None:
    _run(run_id)
