"""The pipeline of kind "vendor_check": one tenderer's offer checked for item (l).

    render -> triage -> resolve -> extract -> verify -> await_ruleset -> (decide, by the job)

Progress is checkpointed after rendering, after every triage batch, and after each
later step, so a retried or resumed job continues from the first missing piece. The
model is reached only through the gateway; `LLM_FACTORY` is what tests replace."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from app.checks import engine_bridge, pages as pg, triage as v1
from app.checks.extract_item_l import VERIFY, extract
from app.checks.resolve import ItemPages, resolve
from app.checks.verify import text_reader, verify_fields
from app.config import Config
from app.gateway import Gateway, GatewaySettings, MemoryCache
from app.jobs import registry
from app.jobs.models import Context, Pause, Pipeline, Step

ITEM = "l"


def project_dir(project: str) -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "projects" / project


def data_class_of(pdir: Path) -> str:
    meta_path = pdir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    if meta.get("data_class"):
        return meta["data_class"]
    return "synthetic" if meta.get("synthetic") else "confidential"


def make_llm(pdir: Path, project: str, tenderer: str) -> Gateway:
    """The real thing: app.llm.LLM behind the gateway, with the shared Postgres
    backends when DATABASE_URL is set and in-memory ones otherwise."""
    from app.llm import LLM
    cfg = Config()
    cfg.cache_dir = pdir / "work" / "cache"
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        from app.gateway_pg import PgBudget, PgCache, PgRateLimiter
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
    ctx.progress("resolve", 0, 1, "calls")
    llm = _llm(ctx)
    before = dict(getattr(llm, "stats", {}))
    with llm.scope(ctx.run["tenderer"]):
        pages = resolve(ctx.data["labels"], ITEM, ctx.run["tenderer"], llm).model_dump()
    return {"item_pages": pages, "cost": _cost(ctx, llm, before)}


def extract_step(ctx: Context):
    ctx.progress("extract", 0, 1, "calls")
    llm = _llm(ctx)
    before = dict(getattr(llm, "stats", {}))
    with llm.scope(ctx.run["tenderer"]):
        item_pages = ItemPages.model_validate(ctx.data["item_pages"])
        fields = extract(ctx.data["pages"], item_pages, ctx.run["tenderer"], llm)
    return {"fields": fields, "cost": _cost(ctx, llm, before)}


def verify_step(ctx: Context):
    """V4: the extracted values checked against the text layer (no call) or by a second read of
    the scanned pages (one call); `fields` is replaced by the verified copy."""
    ctx.progress("verify", 0, 1, "calls")
    llm = _llm(ctx)
    before = dict(getattr(llm, "stats", {}))
    bid_dir = project_dir(ctx.run["project"]) / "bids" / ctx.run["tenderer"]
    with llm.scope(ctx.run["tenderer"]):
        fields = verify_fields(ctx.data["fields"], ctx.data["pages"], ctx.data["item_pages"]["pages"], VERIFY,
                               ctx.run["tenderer"], llm, text_reader(bid_dir))
    return {"fields": fields, "cost": _cost(ctx, llm, before)}


def await_ruleset(ctx: Context):
    return None if ctx.ruleset() else Pause("ruleset_confirmed")


PIPELINE = registry.register(Pipeline(
    kind="vendor_check",
    steps=[Step("render", render), Step("triage", triage), Step("resolve", resolve_step, "calls"),
           Step("extract", extract_step, "calls"), Step("verify", verify_step, "calls"),
           Step("await_ruleset", await_ruleset, "steps")],
    fields_key="fields",
    decide=engine_bridge.decide_item_l,
    resume_when={"ruleset_confirmed": lambda store, run: store.latest_confirmed(run["project"]) is not None},
))
