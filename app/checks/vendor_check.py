"""The pipeline of kind "vendor_check": one tenderer's offer checked, every form.

    render -> triage -> resolve -> extract -> verify -> await_ruleset -> agent -> (decide, by the job)

Progress is checkpointed after rendering, after every triage batch, and after each
later step, so a retried or resumed job continues from the first missing piece. The
model is reached only through the gateway; `LLM_FACTORY` is what tests replace."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from app.checks import engine_bridge, pages as pg, triage as v1
from app.checks.agent import search_form
from app.checks.extract import extract_form
from app.checks.forms import FORMS, form_for
from app.checks.resolve import resolve_form
from app.checks.verify import text_reader, verify_fields
from app.config import Config
from app.llm.gateway import Gateway, GatewaySettings, MemoryCache
from app.jobs import registry
from app.jobs.models import Context, Pause, Pipeline, Step
from app.rulesets.schema import Part, RuleSet


def project_dir(project: str) -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "projects" / project


def data_class_of(pdir: Path) -> str:
    meta_path = pdir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    if meta.get("data_class"):
        return meta["data_class"]
    return "synthetic" if meta.get("synthetic") else "confidential"


def make_llm(pdir: Path, project: str, tenderer: str) -> Gateway:
    """The real thing: app.llm.client.LLM behind the gateway, with the shared Postgres
    backends when DATABASE_URL is set and in-memory ones otherwise."""
    from app.llm.client import LLM
    cfg = Config()
    cfg.cache_dir = pdir / "work" / "cache"
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        from app.llm.gateway_pg import PgBudget, PgCache, PgRateLimiter
        cache, limiter, budget = PgCache(dsn), PgRateLimiter(dsn), PgBudget(dsn)
    else:
        cache, limiter, budget = MemoryCache(), None, None
    return Gateway(LLM(cfg), project=project, data_class=data_class_of(pdir), settings=GatewaySettings.from_env(),
                   cache=cache, limiter=limiter, budget=budget)


def _factory_from_env():
    """VENDOR_CHECK_LLM_FACTORY="module:function" swaps the model for a test double in a
    worker process; unset, the real gateway-wrapped client is used."""
    spec = os.environ.get("VENDOR_CHECK_LLM_FACTORY")
    if not spec:
        return make_llm
    module, _, name = spec.partition(":")
    return getattr(importlib.import_module(module), name)


LLM_FACTORY = _factory_from_env()


def _llm(ctx: Context):
    return LLM_FACTORY(project_dir(ctx.run["project"]), ctx.run["project"], ctx.run["tenderer"])


COST_KEYS = ("calls", "cache_hits", "usd", "waited_seconds")


def _cost(ctx: Context, llm, before: dict) -> dict:
    """The run's model cost so far: what was saved plus this step's calls since `before`."""
    saved = ctx.data.get("cost") or {}
    stats = getattr(llm, "stats", {})
    return {k: round(saved.get(k, 0) + stats.get(k, 0) - before.get(k, 0), 6) for k in COST_KEYS}


def render(ctx: Context):
    pdir = project_dir(ctx.run["project"])
    bid_dir = pdir / "bids" / ctx.run["tenderer"]
    refs = pg.render_offer(bid_dir, pdir / "work" / "pages", progress=lambda d, n: ctx.progress("render", d, n))
    if not refs:
        raise FileNotFoundError(f"no PDF pages under {bid_dir}")
    return {"pages": pg.as_dicts(refs)}


def triage(ctx: Context):
    pages = ctx.data["pages"]
    labels, nxt = list(ctx.data.get("labels", [])), int(ctx.data.get("next_batch", 0))
    llm = _llm(ctx)
    with llm.scope(ctx.run["tenderer"]):
        while nxt < len(pages):                                         # one batch, then checkpoint
            before = dict(getattr(llm, "stats", {}))
            labels += v1.triage(pages, ctx.run["tenderer"], llm, ctx.progress, start_at=nxt, max_batches=1)
            nxt = min(nxt + v1.PAGES_PER_CALL, len(pages))
            ctx.checkpoint(labels=labels, next_batch=nxt, cost=_cost(ctx, llm, before))
    return None


def resolve_step(ctx: Context):
    """V2 for every form of the menu: the labels answer; the model is asked only for a form no
    page is labelled as (an absent form costs one call)."""
    forms = list(FORMS.values())
    llm = _llm(ctx)
    before = dict(getattr(llm, "stats", {}))
    form_pages: dict[str, dict] = {}
    with llm.scope(ctx.run["tenderer"]):
        for i, form in enumerate(forms):
            ctx.progress("resolve", i, len(forms), "forms")
            form_pages[form.id] = resolve_form(ctx.data["labels"], form, ctx.run["tenderer"], llm).model_dump()
    return {"form_pages": form_pages, "cost": _cost(ctx, llm, before)}


def extract_step(ctx: Context):
    """V3 per form present, one call each, checkpointed after every form so a retry continues
    with the next one. `fields` grows across the forms."""
    llm = _llm(ctx)
    fields = dict(ctx.data.get("fields") or {})
    done = set(ctx.data.get("extracted") or [])
    with llm.scope(ctx.run["tenderer"]):
        for form in FORMS.values():
            if form.id in done:
                continue
            ctx.progress("extract", len(done), len(FORMS), "forms")
            before = dict(getattr(llm, "stats", {}))
            fields.update(extract_form(form, ctx.data["pages"], ctx.data["form_pages"][form.id]["pages"], ctx.run["tenderer"], llm))
            done.add(form.id)
            ctx.checkpoint(fields=fields, extracted=sorted(done), cost=_cost(ctx, llm, before))
    return None


def verify_step(ctx: Context):
    """V4 per form: the values checked against the text layer (no call) or by a second read of
    the scanned pages (one call per form); `fields` is replaced by the verified copy."""
    llm = _llm(ctx)
    fields = dict(ctx.data["fields"])
    done = set(ctx.data.get("verified") or [])
    text_of = text_reader(project_dir(ctx.run["project"]) / "bids" / ctx.run["tenderer"])
    with llm.scope(ctx.run["tenderer"]):
        for form in FORMS.values():
            if form.id in done:
                continue
            ctx.progress("verify", len(done), len(FORMS), "forms")
            before = dict(getattr(llm, "stats", {}))
            fields = verify_fields(fields, ctx.data["pages"], ctx.data["form_pages"][form.id]["pages"], form.specs(),
                                   ctx.run["tenderer"], llm, text_of)
            done.add(form.id)
            ctx.checkpoint(fields=fields, verified=sorted(done), cost=_cost(ctx, llm, before))
    return None


def await_ruleset(ctx: Context):
    return None if ctx.ruleset() else Pause("ruleset_confirmed")


def agent_step(ctx: Context):
    """V5, once the rule set is known: for every Part A item whose form no page was labelled
    as, the bounded agent looks for the form; a verified pointer sends that form through V3
    and V4. Checkpointed per form; the trace of every action is kept."""
    confirmed = ctx.ruleset()
    if confirmed is None:
        return None
    ruleset = RuleSet.model_validate(confirmed[1])
    form_pages = dict(ctx.data["form_pages"])
    wanted = sorted({form_for(item).id for item in ruleset.items
                     if item.part == Part.A and form_for(item) is not None and not form_pages[form_for(item).id]["pages"]})
    done = set(ctx.data.get("agent_done") or [])
    todo = [f for f in wanted if f not in done]
    if not todo:
        return None
    llm = _llm(ctx)
    fields = dict(ctx.data["fields"])
    trace = dict(ctx.data.get("agent_trace") or {})
    text_of = text_reader(project_dir(ctx.run["project"]) / "bids" / ctx.run["tenderer"])
    with llm.scope(ctx.run["tenderer"]):
        for i, form_id in enumerate(todo):
            form = FORMS[form_id]
            ctx.progress("agent", i, len(todo), "forms")
            before = dict(getattr(llm, "stats", {}))
            found, steps = search_form(form, ctx.data["pages"], ctx.data["labels"], text_of, llm)
            if found:
                form_pages[form_id] = {"pages": found, "confidence": 0.8, "reason": "found by the agent with a verified quote"}
                fields.update(extract_form(form, ctx.data["pages"], found, ctx.run["tenderer"], llm, located=False))
                fields = verify_fields(fields, ctx.data["pages"], found, form.specs(), ctx.run["tenderer"], llm, text_of)
            trace[form_id] = steps
            done.add(form_id)
            ctx.checkpoint(fields=fields, form_pages=form_pages, agent_trace=trace, agent_done=sorted(done), cost=_cost(ctx, llm, before))
    return None


PIPELINE = registry.register(Pipeline(
    kind="vendor_check",
    steps=[Step("render", render), Step("triage", triage), Step("resolve", resolve_step, "forms"),
           Step("extract", extract_step, "forms"), Step("verify", verify_step, "forms"),
           Step("await_ruleset", await_ruleset, "steps"), Step("agent", agent_step, "forms")],
    fields_key="fields",
    decide=engine_bridge.decide,
    resume_when={"ruleset_confirmed": lambda store, run: store.latest_confirmed(run["project"]) is not None},
))
