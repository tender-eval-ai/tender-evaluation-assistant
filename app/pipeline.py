"""Pipeline helpers shared by the graph orchestrator (app/graph.py) and the CLI:
bidder discovery, the offline (fixture-driven) run, and the console summary.

Checkpoint layout written by the graph — human-editable between runs:

    <out>/rubric.json         derived rubric (editable; delete to re-derive)
    <out>/bids/<name>.json    per-tenderer extraction (editable; delete to re-extract)
    <out>/agent/<name>.json   evidence-search agent trace, when it ran
    <out>/evaluation.json     full evaluation result
    <out>/reports/*.docx      the three Word deliverables
"""
from __future__ import annotations

from pathlib import Path

from .evaluate import evaluate
from .report import render_all
from .rubric import load_rubric
from .schemas import BidExtraction, EvaluationResult


def discover_bidders(bids_dir: Path) -> dict[str, Path]:
    """One subfolder per tenderer; loose PDFs count as single-file tenderers."""
    bidders: dict[str, Path] = {}
    for entry in sorted(bids_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            bidders[entry.name] = entry
        elif entry.suffix.lower() == ".pdf" and not entry.name.startswith("~$"):
            bidders[entry.stem] = entry
    return bidders


def run_offline(fixture_dir: Path, out_dir: Path, log=print) -> EvaluationResult:
    """Offline mode: rubric + bid extractions come from JSON fixtures; the deterministic
    half of the pipeline (evaluation, pricing, Word reports) runs for real."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rubric = load_rubric(fixture_dir / "rubric.json")
    bids = [BidExtraction.model_validate_json(p.read_text())
            for p in sorted((fixture_dir / "bids").glob("*.json"))]
    log(f"Loaded fixture rubric '{rubric.tender_ref}' and {len(bids)} bids (no network calls)")
    result = evaluate(rubric, bids)
    (out_dir / "evaluation.json").write_text(result.model_dump_json(indent=2))
    paths = render_all(result, out_dir / "reports")
    for p in paths:
        log(f"wrote {p}")
    return result


def summarize(result: EvaluationResult) -> str:
    lines = [f"Tender: {result.rubric.tender_ref} — {result.rubric.subject}",
             f"Stage I: {sum(r.passed for r in result.stage1)}/{len(result.stage1)} passed",
             f"Stage II: {sum(r.passed for r in result.stage2)}/{len(result.stage2)} passed",
             "Price ranking:"]
    scheme = result.rubric.price_scheme.type
    for row in sorted(result.price_rows, key=lambda r: (r.ranking is None, r.ranking or 0)):
        metric = row.cost_effectiveness if scheme == "cost_effectiveness" else row.estimated_goods_price
        metric_s = f"{metric:,.2f}" if metric is not None else "cannot be calculated"
        rank = f"#{row.ranking}" if row.ranking else "n/a"
        flag = " *RECOMMENDED*" if row.tenderer == result.recommended else ""
        note = f"  [{row.remark}]" if row.remark and not flag else ""
        lines.append(f"  {rank:>4}  {row.tenderer:<24} {metric_s}{flag}{note}")
    return "\n".join(lines)
