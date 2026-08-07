"""Orchestrator: tender docs -> rubric -> per-bid extraction -> evaluation -> reports.

Writes checkpoint JSON at every step so runs are resumable, auditable, and the rubric
can be human-edited between steps (the product's confirmation checkpoint):

    <out>/rubric.json         derived rubric (editable; delete to re-derive)
    <out>/bids/<name>.json    per-tenderer extraction (editable; delete to re-extract)
    <out>/evaluation.json     full evaluation result
    <out>/reports/*.docx      the three Word deliverables
"""
from __future__ import annotations

from pathlib import Path

from .bid_extract import extract_bid
from .config import Config
from .evaluate import evaluate
from .ingest import load_folder, load_pdf
from .llm import LLM
from .report import render_all
from .rubric import derive_rubric, load_rubric, save_rubric
from .schemas import BidExtraction, EvaluationResult
from .verify import verify_extraction


def discover_bidders(bids_dir: Path) -> dict[str, Path]:
    """One subfolder per tenderer; loose PDFs count as single-file tenderers."""
    bidders: dict[str, Path] = {}
    for entry in sorted(bids_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            bidders[entry.name] = entry
        elif entry.suffix.lower() == ".pdf" and not entry.name.startswith("~$"):
            bidders[entry.stem] = entry
    return bidders


def run_pipeline(tender_dir: Path, bids_dir: Path, out_dir: Path,
                 cfg: Config, llm: LLM, log=print) -> EvaluationResult:
    out_dir.mkdir(parents=True, exist_ok=True)

    rubric_path = out_dir / "rubric.json"
    if rubric_path.is_file():
        log(f"Using existing rubric: {rubric_path} (delete it to re-derive)")
        rubric = load_rubric(rubric_path)
    else:
        log(f"[1/4] Ingesting tender documents from {tender_dir} ...")
        tender_docs = load_folder(tender_dir, cfg, llm)
        log(f"      {len(tender_docs)} documents "
            f"({sum(d.kind == 'scanned' for d in tender_docs)} scanned)")
        log("[2/4] Deriving evaluation rubric ...")
        rubric = derive_rubric(tender_docs, cfg, llm)
        save_rubric(rubric, rubric_path)
        log(f"      rubric saved to {rubric_path} — review/edit it, then re-run to continue")

    bids: list[BidExtraction] = []
    bids_out = out_dir / "bids"
    bids_out.mkdir(exist_ok=True)
    bidders = discover_bidders(bids_dir)
    log(f"[3/4] Extracting {len(bidders)} bids ...")
    for name, path in bidders.items():
        cached = bids_out / f"{name}.json"
        if cached.is_file():
            bids.append(BidExtraction.model_validate_json(cached.read_text()))
            log(f"      {name}: using cached extraction")
            continue
        docs = load_folder(path, cfg, llm) if path.is_dir() else [load_pdf(path, cfg, llm)]
        extraction = extract_bid(name, docs, rubric, cfg, llm)
        if cfg.verify_findings:
            extraction, amendments = verify_extraction(extraction, docs, rubric, cfg, llm)
            for note in amendments:
                log(f"      {name}: verification amended — {note}")
        cached.write_text(extraction.model_dump_json(indent=2))
        bids.append(extraction)
        log(f"      {name}: extracted ({len(docs)} file(s))")

    log("[4/4] Evaluating (deterministic) and rendering reports ...")
    result = evaluate(rubric, bids)
    (out_dir / "evaluation.json").write_text(result.model_dump_json(indent=2))
    paths = render_all(result, out_dir / "reports")
    for p in paths:
        log(f"      wrote {p}")
    return result


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
