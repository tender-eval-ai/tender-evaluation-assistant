"""The pipeline of kind "ruleset_build": one tender's rule set drafted from its documents.

    parse -> locate -> match -> slots -> novel -> coverage -> save

parse runs Nasi's layout parser once and caches the node table under the project's work
folder (slow); locate finds the schedule's items and Parts (L0); match, slots and novel are
the model layers (L1 to L3), novel checkpointed after every item; coverage is code (L4);
save merges the result into the project's draft without overwriting a person's edits.
The model is reached only through the gateway; `LLM_FACTORY` is what tests replace."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from app.checks.vendor_check import _cost, data_class_of, make_llm, project_dir
from app.jobs import registry
from app.jobs.models import TENDER, Context, Pipeline, Step
from app.rulesets import build as merge, coverage as l4, match as l1, novel as l3, slots as l2
from app.rulesets.library import EMPTY, load_templates
from app.rulesets.locate import locate, parse_tender
from app.rulesets.nodes import NodeIndex
from app.rulesets.schema import DataClass, Gap, PartSpec, RuleSetItem

PROMPT_VERSION = f"{l1.PROMPT_VERSION}+{l2.PROMPT_VERSION}+{l3.PROMPT_VERSION}"


def _factory_from_env():
    """RULESET_BUILD_LLM_FACTORY="module:function" swaps the model for a test double."""
    spec = os.environ.get("RULESET_BUILD_LLM_FACTORY")
    if not spec:
        return make_llm
    module, _, name = spec.partition(":")
    return getattr(importlib.import_module(module), name)


LLM_FACTORY = _factory_from_env()


def _llm(ctx: Context):
    return LLM_FACTORY(project_dir(ctx.run["project"]), ctx.run["project"], TENDER)


def tender_pdfs(pdir: Path) -> list[Path]:
    return sorted((pdir / "tender").glob("*.pdf"))


def nodes_path(pdir: Path) -> Path:
    return pdir / "work" / "nodes.json"


def _pdir(ctx: Context) -> Path:
    return project_dir(ctx.run["project"])


def _nodes(ctx: Context) -> list[dict]:
    return json.loads(Path(ctx.data["nodes_file"]).read_text())


def _items(ctx: Context) -> list[RuleSetItem]:
    return [RuleSetItem.model_validate(i) for i in ctx.data["items"]]


def _dump(items) -> list[dict]:
    return [i.model_dump(mode="json") for i in items]


def _data_class(ctx: Context) -> DataClass:
    return DataClass(data_class_of(_pdir(ctx)))


def parse(ctx: Context):
    pdir = _pdir(ctx)
    pdfs = tender_pdfs(pdir)
    if not pdfs:
        raise FileNotFoundError(f"no tender PDFs under {pdir / 'tender'}")
    ctx.progress("parse", 0, len(pdfs), "files")
    path = nodes_path(pdir)
    if not path.is_file() or os.environ.get("RULESET_BUILD_REPARSE"):
        _, nodes = parse_tender(pdfs, root=pdir.resolve())          # a resolved root: project-relative file names
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(nodes, ensure_ascii=False))
    ctx.progress("parse", len(pdfs), len(pdfs), "files")
    return {"nodes_file": str(path), "files": [f"tender/{p.name}" for p in pdfs]}


def locate_step(ctx: Context):
    from app.parsing.loader import load_pdf

    pdir = _pdir(ctx)
    pdfs = tender_pdfs(pdir)
    pages = [p for pdf in pdfs for p in load_pdf(pdf)]
    schedule = locate(pages, _nodes(ctx), data_class=_data_class(ctx), root=pdir)
    if not schedule.items:
        raise RuntimeError("no Completeness Check Schedule found in the tender")
    parts = merge.merge_parts([PartSpec(part=p.part, title=f"Part {p.part.value}", citation=p.citation, clauses=p.clauses)
                               for p in schedule.parts])
    return {"items": [i.as_rule_set_item().model_dump(mode="json") for i in schedule.items],
            "parts": [p.model_dump(mode="json") for p in parts],
            "unresolved": {i.letter: i.unresolved for i in schedule.items if i.unresolved}}


def match_step(ctx: Context):
    items = _items(ctx)
    ctx.progress("match", 0, len(items), "calls")
    templates = load_templates()
    llm = _llm(ctx)
    before = dict(getattr(llm, "stats", {}))
    with llm.scope(TENDER):
        matched = l1.match_items(items, templates, NodeIndex(_nodes(ctx)), llm)
    return {"items": _dump(matched), "cost": _cost(ctx, llm, before), "templates": len(templates)}


def slots_step(ctx: Context):
    items = _items(ctx)
    with_slots = [i for i in items if i.template is not None and i.slots]
    ctx.progress("slots", 0, len(with_slots), "calls")
    llm = _llm(ctx)
    before = dict(getattr(llm, "stats", {}))
    with llm.scope(TENDER):
        filled = l2.fill_items(items, load_templates(), NodeIndex(_nodes(ctx)), llm, _data_class(ctx))
    return {"items": _dump(filled), "cost": _cost(ctx, llm, before)}


def novel_step(ctx: Context):
    """One call per item without a template, checkpointed after each, so a retry continues
    with the next item rather than the first."""
    items = _items(ctx)
    done = set(ctx.data.get("novel_done", []))
    todo = [i for i in items if i.template is None and i.letter not in done]
    total = len(done) + len(todo)
    ctx.progress("novel", len(done), total, "calls")
    index = NodeIndex(_nodes(ctx))
    llm = _llm(ctx)
    sources = dict(ctx.data.get("sources", {}))
    with llm.scope(TENDER):
        for item in todo:
            before = dict(getattr(llm, "stats", {}))
            drafted, found = l3.draft_item(item, index, llm, _data_class(ctx))
            items = [drafted if i.letter == item.letter else i for i in items]
            sources.update(found)
            done.add(item.letter)
            ctx.checkpoint(items=_dump(items), sources=sources, novel_done=sorted(done), cost=_cost(ctx, llm, before))
            ctx.progress("novel", len(done), total, "calls")
    return None


def coverage_step(ctx: Context):
    gaps = l4.gaps_for(_items(ctx), NodeIndex(_nodes(ctx)), ctx.data.get("sources", {}))
    return {"gaps": [g.model_dump(mode="json") for g in gaps]}


def save(ctx: Context):
    store = ctx.store
    pid = ctx.run["project"]
    existing = store.draft(pid) or store.latest_confirmed(pid)
    spec = merge.merge_build(existing[1] if existing else None, _items(ctx),
                             [PartSpec.model_validate(p) for p in ctx.data["parts"]],
                             [Gap.model_validate(g) for g in ctx.data.get("gaps", [])],
                             project_id=pid, data_class=_data_class(ctx), model=os.environ.get("TEXT_MODEL"),
                             prompt_version=PROMPT_VERSION)
    version, created = store.save_draft(pid, spec, merge.BUILDER)
    after = store.get_version(pid, version)
    reason = "new draft" if created else "draft rebuilt"
    if ctx.data.get("templates") == 0:
        reason += f"; {EMPTY}"                      # the audit log shows why every item is novel
    store.event("ruleset.built", pid, f"v{version}", existing[1] if existing else None, after, merge.BUILDER, reason)
    return {"ruleset_version": version}


PIPELINE = registry.register(Pipeline(
    kind="ruleset_build",
    steps=[Step("parse", parse, "files"), Step("locate", locate_step, "items"), Step("match", match_step, "calls"),
           Step("slots", slots_step, "calls"), Step("novel", novel_step, "calls"), Step("coverage", coverage_step, "steps"),
           Step("save", save, "steps")],
    fields_key=None,
))
