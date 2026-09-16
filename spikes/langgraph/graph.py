"""The slice as a LangGraph graph. Nodes are thin wrappers around test/jobs/slice.py.

Design decisions (see docs/spikes/slice_spec.md, section 3):
1. Progress lives in the checkpointer, one checkpoint per node. Triage is one node per
   six-page batch that loops back to itself, so a crash re-runs at most one batch.
2. The pause is `interrupt()` in confirm_rubric; the API resumes with Command(resume=spec).
   The node reads the rubric table first, so a run that reaches the pause after the
   rubric was confirmed does not stop.
3. Takeover is the Procrastinate queue's: a stalled job is retried and the new worker
   invokes the same thread, which continues from its last checkpoint.
4. Provider errors: a transient error fails the job, the queue retries it, the graph
   resumes at the failed node. A permanent error ends the job as failed.
5. No LLM cache: the granularity of point 1 is what limits repeated calls.
"""
from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from test.jobs import knobs
from test.jobs import slice as sl


class SliceState(TypedDict, total=False):
    run_id: str
    tender: str
    vendor: str
    n_pages: int
    cert_page: int
    next_batch: int
    labels: list[dict]
    item_pages: dict | None
    fields: dict | None
    rubric: dict | None
    verdict: dict | None


def build(llm, progress: Callable[[str, int, int], None], read_rubric: Callable[[str], tuple[int, bool, dict]],
          checkpointer):
    def pages(state: SliceState) -> list[bytes]:
        return sl.make_vendor(state["vendor"], state["n_pages"], state["cert_page"])["pages"]

    def triage_batch(state: SliceState) -> dict:
        start = state.get("next_batch", 0)
        batch = sl.triage(pages(state), state["vendor"], llm, progress, start_at=start, max_batches=1)
        done = min(start + sl.PAGES_PER_TRIAGE, state["n_pages"])   # one batch per node run: one checkpoint each
        return {"labels": state.get("labels", []) + batch, "next_batch": done}

    def more_batches(state: SliceState) -> str:
        return "triage_batch" if state["next_batch"] < state["n_pages"] else "resolve"

    def resolve(state: SliceState) -> dict:
        progress("resolve", 0, 1)
        return {"item_pages": sl.resolve(state["labels"], state["vendor"], llm).model_dump()}

    def extract(state: SliceState) -> dict:
        progress("extract", 0, 1)
        item_pages = sl.ItemPages.model_validate(state["item_pages"])
        return {"fields": sl.extract(pages(state), item_pages, state["vendor"], llm).model_dump()}

    def confirm_rubric(state: SliceState) -> dict:
        version, confirmed, spec = read_rubric(state["tender"])
        if not confirmed:
            progress("await_rubric", 0, 1)
            interrupt({"awaiting": "rubric", "tender": state["tender"]})
            version, confirmed, spec = read_rubric(state["tender"])   # re-read: edits made while paused
        return {"rubric": spec}

    def extra_step(state: SliceState) -> dict:
        fields = dict(state["fields"] or {})
        fields["extra_step"] = True
        progress("extra_step", 1, 1)
        return {"fields": fields}

    def decide(state: SliceState) -> dict:
        progress("decide", 0, 1)
        return {"verdict": sl.decide(state["fields"] or {}, state["rubric"] or {})}

    g = StateGraph(SliceState)
    g.add_node("triage_batch", triage_batch)
    g.add_node("resolve", resolve)
    g.add_node("extract", extract)
    g.add_node("confirm_rubric", confirm_rubric)
    g.add_node("decide", decide)
    g.add_edge(START, "triage_batch")
    g.add_conditional_edges("triage_batch", more_batches, {"triage_batch": "triage_batch", "resolve": "resolve"})
    g.add_edge("resolve", "extract")
    g.add_edge("extract", "confirm_rubric")
    if knobs.get("SLICE_EXTRA_STEP"):          # "deploying" a pipeline with one more step
        g.add_node("extra_step", extra_step)
        g.add_edge("confirm_rubric", "extra_step")
        g.add_edge("extra_step", "decide")
    else:
        g.add_edge("confirm_rubric", "decide")
    g.add_edge("decide", END)
    return g.compile(checkpointer=checkpointer)
