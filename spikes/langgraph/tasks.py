"""Procrastinate tasks that run the LangGraph slice: one job per run, resumed through
the same thread after a crash (checkpoint) or a confirmation (interrupt)."""
from __future__ import annotations

import os

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from spikes.common.queue import QUEUE, TransientRetry, make_app
from spikes.common.store import Store
from spikes.langgraph import graph as lg
from test.jobs import knobs
from test.jobs import slice as sl

app = make_app()
store = Store("lg")


def _thread(run: dict) -> dict:
    return {"configurable": {"thread_id": f"{run['run_id']}:{run['attempt']}"}}


def _run_graph(run_id: str, resume: bool) -> None:
    run = store.run(run_id)
    cert_page = int(knobs.get("CERT_PAGE", "13"))
    n_pages = int(knobs.get("N_PAGES", "16"))
    llm = sl.make_llm(cert_page)

    def progress(step: str, done: int, total: int) -> None:
        store.update_run(run_id, state="running", step=step, progress={"done": done, "total": total, "unit": "pages"})

    store.update_run(run_id, worker_pid=os.getpid())    # which process holds the job (the harness kills it)
    try:
        with llm.scope(run["vendor"]):
            with PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as saver:   # tables exist: adapter.setup()
                graph = lg.build(llm, progress, store.rubric, saver)
                config = _thread(run)
                if resume:
                    _, _, spec = store.rubric(run["tender"])
                    result = graph.invoke(Command(resume=spec), config)
                elif graph.get_state(config).values:        # a checkpoint exists: continue after a crash
                    result = graph.invoke(None, config)
                else:
                    result = graph.invoke({"run_id": run_id, "tender": run["tender"], "vendor": run["vendor"],
                                           "n_pages": n_pages, "cert_page": cert_page, "next_batch": 0, "labels": []},
                                          config)
            if "__interrupt__" in result:
                version, confirmed, spec = store.rubric(run["tender"])
                if not confirmed:
                    store.update_run(run_id, state="paused", step="await_rubric")
                    return
                # confirmed between the node's check and now: continue in this job
                with PostgresSaver.from_conn_string(os.environ["DATABASE_URL"]) as saver:
                    graph = lg.build(llm, progress, store.rubric, saver)
                    result = graph.invoke(Command(resume=spec), config)
            version, _, spec = store.rubric(run["tender"])
            store.store_result(run_id, run["vendor"], version, result["fields"], spec)
            store.update_run(run_id, state="done", step=None, rubric_version=version)
    except Exception as err:
        transient = getattr(err, "transient", False)
        store.update_run(run_id, state="running" if transient else "failed", error=f"{type(err).__name__}: {err}")
        raise


@app.task(queue=QUEUE, retry=TransientRetry(), pass_context=True)
def run_slice(context, run_id: str) -> None:
    _run_graph(run_id, resume=False)


@app.task(queue=QUEUE, retry=TransientRetry(), pass_context=True)
def resume_run(context, run_id: str) -> None:
    _run_graph(run_id, resume=True)
