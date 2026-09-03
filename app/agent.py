"""Bounded evidence-search agent: a tool-using loop that runs ONLY for findings the
pipeline could not settle after adversarial verification — required documents still
marked missing, compliance still "unclear", and a price the first pass never saw.

Agency is deliberately narrow:
- action selection is a schema-validated JSON `AgentAction` per step (works on any
  OpenAI-compatible endpoint, reuses chat_json's validation retry);
- tools are read-only (`app.tools.BidTools`); on-demand OCR has a per-bid budget;
- a `finish(found=true)` is accepted only if the quote actually appears on the cited
  page (checked in code) — the agent cannot cite what it inferred;
- it may restore a missing document with verified evidence (same trust level as the
  verification pass) but never changes a compliance verdict: "unclear" stays unclear
  with the evidence attached and a suggestion for the human;
- every step is recorded in a trace that is persisted next to the extraction.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .bid_extract import extract_price
from .config import Config
from .grounding import quote_on_page
from .ingest import Document
from .schemas import BidExtraction, Rubric
from .tools import TOOL_DESCRIPTIONS, BidTools

SYSTEM = (
    "You are an evidence-search agent for a public Tender Assessment Panel. A "
    "first-pass review could not find something in a tenderer's offer. Search the "
    "offer with the tools and either find VERBATIM evidence or conclude it is absent.\n"
    "Tools:\n" + TOOL_DESCRIPTIONS + "\n"
    "Rules: one action per step. Pages marked [skipped] have not been read — if a "
    "table of contents or cover page points to one, ocr_page it. A quote must be copied "
    "exactly from page text you have read; it is checked, and an unverifiable quote is "
    "rejected. found=false is a correct answer when the evidence is not in the offer. "
    "Never infer from what tenderers usually submit. You have a limited number of "
    "steps; finish as soon as you know the answer."
)

TRANSCRIPT_RESULT_CHARS = 4000
TRACE_RESULT_CHARS = 300


class AgentAction(BaseModel):
    """One step: a tool call, or `finish`."""
    thought: str = Field(default="", description="One sentence: why this step")
    tool: Literal["list_pages", "search_pages", "read_page", "ocr_page", "finish"]
    query: str = Field(default="", description="search_pages only")
    page: Optional[int] = Field(default=None, description="read_page / ocr_page / finish")
    file: Optional[str] = Field(default=None, description="file name for multi-file bids")
    found: bool = Field(default=False, description="finish only")
    quote: str = Field(default="", description="finish only: verbatim text from the cited page")
    note: str = Field(default="", description="finish only: one-line explanation")
    suggested: Optional[Literal["yes", "no", "unclear"]] = Field(
        default=None, description="finish only, compliance tasks: what the passage implies")


def _run_task(task: str, tools: BidTools, cfg: Config, llm) -> tuple[AgentAction | None, list[dict]]:
    """The loop. Returns the accepted finish action (or None) and the step trace."""
    first = tools.page_text(1) or ""
    transcript = [f"Task: {task}",
                  "Initial observation — pages of this offer:\n" + tools.list_pages(),
                  "Page 1 (cover / contents) reads:\n" + (first[:1500] or "(unread)")]
    trace: list[dict] = []
    for step in range(1, cfg.agent_max_steps + 1):
        action = llm.chat_json(SYSTEM, "\n\n".join(transcript) + f"\n\nStep {step}: choose your next action.",
                               AgentAction)
        args = {k: v for k, v in (("query", action.query), ("page", action.page), ("file", action.file))
                if v not in (None, "")}
        if action.tool == "finish":
            if action.found:
                ok = action.page is not None and quote_on_page(action.quote, tools.page_text(action.page, action.file))
                if not ok:
                    result = (f"REJECTED: the quote does not appear verbatim on page {action.page}. "
                              "Read the page and copy the text exactly, or finish with found=false.")
                    trace.append({"step": step, "thought": action.thought, "tool": "finish",
                                  "args": {"page": action.page, "quote": action.quote[:200]},
                                  "result": result})
                    transcript.append(f"Step {step}: finish(found=true, page={action.page}) -> {result}")
                    continue
            trace.append({"step": step, "thought": action.thought, "tool": "finish",
                          "args": {"found": action.found, "page": action.page,
                                   "quote": action.quote[:200], "suggested": action.suggested},
                          "result": "accepted"})
            return action, trace
        try:
            if action.tool == "list_pages":
                result = tools.list_pages()
            elif action.tool == "search_pages":
                result = tools.search_pages(action.query)
            elif action.tool == "read_page":
                result = tools.read_page(action.page, action.file)
            else:
                result = tools.ocr_page(action.page, action.file)
        except ValueError as err:
            result = f"ERROR: {err}"
        trace.append({"step": step, "thought": action.thought, "tool": action.tool,
                      "args": args, "result": result[:TRACE_RESULT_CHARS]})
        transcript.append(f"Step {step}: {action.tool}({args}) ->\n{result[:TRANSCRIPT_RESULT_CHARS]}")
    trace.append({"step": cfg.agent_max_steps, "tool": "budget", "args": {},
                  "result": "step budget exhausted — finding left unchanged"})
    return None, trace


def evidence_search(extraction: BidExtraction, bid_docs: list[Document], rubric: Rubric,
                    cfg: Config, llm) -> tuple[BidExtraction, dict]:
    """Run the agent for every unresolved finding of one bid. Returns the (possibly
    amended) extraction and a report: {"findings": {id: trace}, "ocr_pages": [...],
    "amendments": [...]} — empty findings means the agent never ran."""
    report: dict = {"findings": {}, "ocr_pages": [], "amendments": []}
    items = {i.id: i for i in rubric.stage1_checklist}
    reqs = {r.id: r for r in rubric.stage2_requirements}
    tools = BidTools(bid_docs, cfg, llm, cfg.agent_ocr_pages)
    name = extraction.tenderer

    for d in extraction.documents:
        item = items.get(d.checklist_id)
        if d.present or item is None or not item.required:
            continue
        task = (f"Find evidence that the offer of '{name}' includes the required document: "
                f"'{item.item}'. finish(found=true) only after reading a page that shows or "
                "explicitly mentions this document; quote that sentence verbatim.")
        action, trace = _run_task(task, tools, cfg, llm)
        report["findings"][d.checklist_id] = trace
        if action and action.found:
            d.present, d.page = True, action.page
            d.note = f"found by evidence search (p.{action.page}): {action.quote[:200]}"
            report["amendments"].append(f"{d.checklist_id} restored — found on p.{action.page}")

    for c in extraction.compliance:
        req = reqs.get(c.requirement_id)
        if c.complies != "unclear" or req is None:
            continue
        task = (f"Find the passage of the offer of '{name}' that addresses the essential "
                f"requirement: '{req.requirement}'. finish(found=true) with the verbatim passage "
                "and set `suggested` to what it implies (yes / no / unclear); a human decides.")
        action, trace = _run_task(task, tools, cfg, llm)
        report["findings"][c.requirement_id] = trace
        if action and action.found:
            c.page = action.page
            c.evidence = (f"evidence found by search (p.{action.page}), verdict left to reviewer"
                          f"{f', agent suggests: {action.suggested}' if action.suggested else ''}: "
                          f"{action.quote[:200]}")
            report["amendments"].append(
                f"{c.requirement_id} evidence attached (still unclear, suggests {action.suggested})")

    if extraction.price.unit_price is None:
        task = (f"Find the Price Schedule of the offer of '{name}' with the quoted unit price "
                "(and the estimated goods price / total if stated). finish(found=true) and "
                "quote the price line verbatim.")
        ocr_before = tools.ocr_used
        action, trace = _run_task(task, tools, cfg, llm)
        report["findings"]["price"] = trace
        # Re-extract when the agent found the schedule — or merely read new pages: the
        # price may be on one of them even if the loop ran out of steps.
        if (action and action.found) or tools.ocr_used > ocr_before:
            extraction.price = extract_price(name, bid_docs, rubric, cfg, llm)
            where = f"p.{action.page}" if action and action.found else "newly read pages"
            report["amendments"].append(
                f"price re-extracted from {where}: unit_price={extraction.price.unit_price}")

    report["ocr_pages"] = [list(t) for t in tools.ocr_pages]
    return extraction, report
