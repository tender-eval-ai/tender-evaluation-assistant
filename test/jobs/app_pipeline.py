"""The harness slice (test/jobs/slice.py) as an app pipeline of kind "slice": the same
FakeLLM steps behind app.jobs' Step and Pipeline shapes, so the twelve scenarios
certify the promoted runner exactly as they certified the spike."""
from __future__ import annotations

import os

from app.llm.gateway import Gateway, GatewaySettings
from app.llm.gateway_pg import PgRateLimiter
from app.jobs import registry
from app.jobs.models import Context, Pause, Pipeline, Step
from test.jobs import knobs
from test.jobs import slice as sl

DEFAULT_SPEC = {"requires_signature": True, "requires_date": False}


def _bid(ctx: Context):
    """The vendor's pages and the LLM: the FakeLLM behind the gateway, with the shared
    rate limiter when the scenario names a provider limit (LLM_RPM), and no cache, so
    "repeated LLM calls" still measures the runner's resumption and nothing else."""
    cert_page = int(knobs.get("CERT_PAGE", "13"))
    n_pages = int(knobs.get("N_PAGES", "16"))
    rpm = int(knobs.get("LLM_RPM", "0") or 0)
    llm = Gateway(sl.make_llm(cert_page), project=ctx.run["project"], data_class="synthetic",
                  settings=GatewaySettings(rpm=rpm or None),
                  limiter=PgRateLimiter(os.environ["DATABASE_URL"]) if rpm else None, limiter_key="fake-provider")
    return sl.make_vendor(ctx.run["tenderer"], n_pages, cert_page), llm


def triage(ctx: Context):
    bid, llm = _bid(ctx)
    tenderer, n = ctx.run["tenderer"], len(bid["pages"])
    labels, nxt = list(ctx.data.get("labels", [])), int(ctx.data.get("next_batch", 0))
    with llm.scope(tenderer):
        while nxt < n:                                                    # one batch, then checkpoint
            labels += sl.triage(bid["pages"], tenderer, llm, ctx.progress, start_at=nxt, max_batches=1)
            nxt = min(nxt + sl.PAGES_PER_TRIAGE, n)
            ctx.checkpoint(labels=labels, next_batch=nxt)
    return None


def resolve(ctx: Context):
    _, llm = _bid(ctx)
    ctx.progress("resolve", 0, 1, "calls")
    with llm.scope(ctx.run["tenderer"]):
        return {"item_pages": sl.resolve(ctx.data["labels"], ctx.run["tenderer"], llm).model_dump()}


def extract(ctx: Context):
    bid, llm = _bid(ctx)
    ctx.progress("extract", 0, 1, "calls")
    with llm.scope(ctx.run["tenderer"]):
        pages = sl.ItemPages.model_validate(ctx.data["item_pages"])
        return {"fields": sl.extract(bid["pages"], pages, ctx.run["tenderer"], llm).model_dump()}


def await_ruleset(ctx: Context):
    return None if ctx.ruleset() else Pause("ruleset_confirmed")


def extra_step(ctx: Context):
    """Stands for a step deployed while runs were paused (scenario 9)."""
    if not knobs.get("SLICE_EXTRA_STEP"):
        return None
    ctx.progress("extra_step", 1, 1, "steps")
    return {"fields": {**ctx.data["fields"], "extra_step": True}}


PIPELINE = registry.register(Pipeline(
    kind="slice",
    steps=[Step("triage", triage), Step("resolve", resolve, "calls"), Step("extract", extract, "calls"),
           Step("await_ruleset", await_ruleset, "steps"), Step("extra_step", extra_step, "steps")],
    fields_key="fields",
    decide=sl.decide,
    resume_when={"ruleset_confirmed": lambda store, run: store.latest_confirmed(run["project"]) is not None},
))
