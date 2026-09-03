"""LangGraph orchestration of the pipeline: the same steps as pipeline.py, as a
state graph with durable checkpoints, human-in-the-loop interrupts and per-bid
parallel fan-out.

    load_checkpoints ─► derive_rubric ─► confirm_rubric ─┐
           │ (rubric.json exists)                        ▼
           └────────────────────────────────► [extract_bid × N via Send]
                                                         ▼
                              review_extractions ─► evaluate ─► render_reports

Design rules kept from the legacy path: nodes are the existing functions (no new
LLM layer); every step still writes the human-editable JSON checkpoint files, and a
stored rubric / extraction is never re-derived or re-extracted. Human checkpoints are
`interrupt()`s when `interactive=True` (service mode) and pass-through otherwise (CLI).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from .bid_extract import extract_bid
from .config import Config
from .evaluate import evaluate
from .ingest import load_folder, load_pdf
from .llm import LLM
from .pipeline import discover_bidders
from .report import render_all
from .rubric import derive_rubric
from .schemas import BidExtraction, EvaluationResult, Rubric
from .verify import verify_extraction


def _merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def _union(a: list | None, b: list | None) -> list:
    return sorted(set(a or []) | set(b or []))


def _append(a: list | None, b: list | None) -> list:
    return (a or []) + (b or [])


class PipelineState(TypedDict, total=False):
    tender_dir: str
    bids_dir: str
    out_dir: str
    bidders: dict[str, str]                            # tenderer -> folder or PDF path
    rubric: dict | None                                # Rubric.model_dump()
    extractions: Annotated[dict[str, dict], _merge]    # tenderer -> BidExtraction dump
    corrected: Annotated[list[str], _union]            # tenderers corrected by a human
    evaluation: dict | None                            # EvaluationResult dump
    reports: list[str]
    progress: Annotated[list[str], _append]            # one line per completed step


class BidState(TypedDict):
    """Payload of one `Send` — the unit of parallel work."""
    tenderer: str
    path: str
    out_dir: str
    rubric: dict


def build_graph(cfg: Config, llm: LLM | None, checkpointer=None, interactive: bool = True,
                log=print):
    """Compile the pipeline graph. `llm` may be None when every LLM step is already
    checkpointed on disk (or stubbed in tests)."""

    def out(state) -> Path:
        return Path(state["out_dir"])

    # ---------------------------------------------------------------- nodes
    def load_checkpoints(state: PipelineState) -> dict:
        o = out(state)
        o.mkdir(parents=True, exist_ok=True)
        (o / "bids").mkdir(exist_ok=True)
        bidders = {n: str(p) for n, p in discover_bidders(Path(state["bids_dir"])).items()}
        update: dict = {"bidders": bidders, "progress": []}
        if (o / "rubric.json").is_file():
            update["rubric"] = Rubric.model_validate_json((o / "rubric.json").read_text()).model_dump(mode="json")
            update["progress"].append("using existing rubric.json (delete it to re-derive)")
        stored = {}
        for p in sorted((o / "bids").glob("*.json")):
            ext = BidExtraction.model_validate_json(p.read_text())
            stored[ext.tenderer] = ext.model_dump(mode="json")
            bidders.setdefault(ext.tenderer, "")
        if stored:
            update["extractions"] = stored
            update["progress"].append(f"using {len(stored)} stored extraction(s)")
        for line in update["progress"]:
            log(line)
        return update

    def derive_rubric_node(state: PipelineState) -> dict:
        log(f"[rubric] deriving from {state['tender_dir']} ...")
        docs = load_folder(Path(state["tender_dir"]), cfg, llm)
        rubric = derive_rubric(docs, cfg, llm)
        (out(state) / "rubric.json").write_text(rubric.model_dump_json(indent=2))
        log("[rubric] saved rubric.json")
        return {"rubric": rubric.model_dump(mode="json"), "progress": ["rubric derived"]}

    def confirm_rubric(state: PipelineState) -> dict:
        if not interactive:
            return {}
        answer = interrupt({"checkpoint": "rubric", "rubric": state["rubric"]})
        if isinstance(answer, dict) and answer:
            rubric = Rubric.model_validate(answer)
            (out(state) / "rubric.json").write_text(rubric.model_dump_json(indent=2))
            return {"rubric": rubric.model_dump(mode="json"), "progress": ["rubric confirmed (edited)"]}
        return {"progress": ["rubric confirmed"]}

    def extract_bid_node(bid: BidState) -> dict:
        name, path = bid["tenderer"], Path(bid["path"])
        rubric = Rubric.model_validate(bid["rubric"])
        docs = load_folder(path, cfg, llm) if path.is_dir() else [load_pdf(path, cfg, llm)]
        extraction = extract_bid(name, docs, rubric, cfg, llm)
        if cfg.verify_findings:
            extraction, _ = verify_extraction(extraction, docs, rubric, cfg, llm)
        (Path(bid["out_dir"]) / "bids" / f"{name}.json").write_text(
            extraction.model_dump_json(indent=2))
        log(f"[extract] {name}: extracted ({len(docs)} file(s))")
        return {"extractions": {name: extraction.model_dump(mode="json")},
                "progress": [f"extracted {name}"]}

    def review_extractions(state: PipelineState) -> dict:
        if not interactive:
            return {}
        answer = interrupt({"checkpoint": "review", "extractions": state["extractions"]})
        if isinstance(answer, dict) and answer:
            fixed = {}
            for name, raw in answer.items():
                ext = BidExtraction.model_validate({**raw, "tenderer": name})
                (out(state) / "bids" / f"{name}.json").write_text(ext.model_dump_json(indent=2))
                fixed[name] = ext.model_dump(mode="json")
            return {"extractions": fixed, "corrected": list(fixed),
                    "progress": [f"corrected {', '.join(sorted(fixed))}"]}
        return {"progress": ["extractions reviewed"]}

    def evaluate_node(state: PipelineState) -> dict:
        rubric = Rubric.model_validate(state["rubric"])
        bids = [BidExtraction.model_validate(state["extractions"][n])
                for n in sorted(state["extractions"])]
        result = evaluate(rubric, bids)
        (out(state) / "evaluation.json").write_text(result.model_dump_json(indent=2))
        log("[evaluate] deterministic evaluation complete")
        return {"evaluation": result.model_dump(mode="json"), "progress": ["evaluated"]}

    def render_reports(state: PipelineState) -> dict:
        result = EvaluationResult.model_validate(state["evaluation"])
        paths = render_all(result, out(state) / "reports")
        for p in paths:
            log(f"[reports] wrote {p}")
        return {"reports": [str(p) for p in paths], "progress": ["reports rendered"]}

    # ---------------------------------------------------------------- routing
    def fan_out(state: PipelineState):
        """One Send per bidder that has no stored extraction; straight to review if none."""
        sends = [Send("extract_bid", BidState(tenderer=n, path=p, out_dir=state["out_dir"],
                                              rubric=state["rubric"]))
                 for n, p in sorted(state["bidders"].items())
                 if n not in (state.get("extractions") or {})]
        return sends or "review_extractions"

    def after_load(state: PipelineState):
        return fan_out(state) if state.get("rubric") else "derive_rubric"

    g = StateGraph(PipelineState)
    g.add_node("load_checkpoints", load_checkpoints)
    g.add_node("derive_rubric", derive_rubric_node)
    g.add_node("confirm_rubric", confirm_rubric)
    g.add_node("extract_bid", extract_bid_node)
    g.add_node("review_extractions", review_extractions)
    g.add_node("evaluate", evaluate_node)
    g.add_node("render_reports", render_reports)

    g.add_edge(START, "load_checkpoints")
    g.add_conditional_edges("load_checkpoints", after_load,
                            ["derive_rubric", "extract_bid", "review_extractions"])
    g.add_edge("derive_rubric", "confirm_rubric")
    g.add_conditional_edges("confirm_rubric", fan_out, ["extract_bid", "review_extractions"])
    g.add_edge("extract_bid", "review_extractions")
    g.add_edge("review_extractions", "evaluate")
    g.add_edge("evaluate", "render_reports")
    g.add_edge("render_reports", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())


def graph_config(cfg: Config, thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id},
            "max_concurrency": cfg.max_parallel_bids}


def initial_state(tender_dir: Path, bids_dir: Path, out_dir: Path) -> PipelineState:
    return PipelineState(tender_dir=str(tender_dir), bids_dir=str(bids_dir), out_dir=str(out_dir))


def run_graph(tender_dir: Path, bids_dir: Path, out_dir: Path, cfg: Config, llm: LLM | None,
              log=print, thread_id: str = "cli") -> EvaluationResult:
    """CLI entry: run to completion without human interrupts (checkpoint files on disk
    remain the way to edit between runs, exactly as with the legacy pipeline)."""
    graph = build_graph(cfg, llm, interactive=False, log=log)
    state = graph.invoke(initial_state(tender_dir, bids_dir, out_dir), graph_config(cfg, thread_id))
    return EvaluationResult.model_validate(state["evaluation"])


def resume(graph, cfg: Config, thread_id: str, payload) -> dict:
    """Continue a paused (interrupted) graph with the human's answer."""
    return graph.invoke(Command(resume=payload), graph_config(cfg, thread_id))


def pending_checkpoint(state: dict) -> dict | None:
    """The interrupt payload if the graph is paused at a human checkpoint, else None."""
    ints = state.get("__interrupt__") or []
    return ints[0].value if ints else None
