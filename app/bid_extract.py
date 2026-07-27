"""Per-bid extraction: which required documents are present, compliance evidence, and
price fields — every finding cites the page it came from."""
from __future__ import annotations

from .config import Config
from .ingest import Document
from .llm import LLM
from .schemas import BidExtraction, Rubric

SYSTEM = (
    "You support a public Tender Assessment Panel (TAP). You are given the "
    "evaluation rubric for a tender and the content of ONE tenderer's offer (page "
    "numbers marked as [Page N]). Extract:\n"
    "1. documents — for EVERY stage1_checklist item: is it present in the offer? "
    "present=true is allowed ONLY if the offer text explicitly mentions that document — "
    "copy the mentioning sentence into `note` and cite the page. If the offer nowhere "
    "mentions the document, you MUST set present=false; never assume a document exists "
    "because other tenderers included it or because it is normally required.\n"
    "2. compliance — for EVERY stage2_requirement: does the offer comply? 'yes' / 'no' "
    "only with clear evidence (quote it, cite the page); otherwise 'unclear'. Compare "
    "numbers against the limit direction: 'within/at most N days' is satisfied by any "
    "stated period <= N; 'at least N months' is satisfied by any stated figure >= N. "
    "E.g. delivery in 30 days complies with 'within 45 days'.\n"
    "3. price — unit price, currency, optimal dosage (if the scheme uses one), and the "
    "quoted total/estimated goods price if stated. Numbers exactly as printed.\n"
    "Content marked [REDACTED] is masked, not missing: a form that is visibly present "
    "but with values redacted still counts as present. Never guess numbers."
)


def extract_bid(tenderer: str, bid_docs: list[Document], rubric: Rubric,
                cfg: Config, llm: LLM) -> BidExtraction:
    parts = []
    total = 0
    for doc in bid_docs:
        piece = f"### FILE: {doc.name}\n{doc.joined(cfg.max_doc_chars)}"
        if total + len(piece) > cfg.max_total_chars:
            piece = piece[: max(0, cfg.max_total_chars - total)]
        parts.append(piece)
        total += len(piece)
        if total >= cfg.max_total_chars:
            break
    user = (
        f"Evaluation rubric:\n{rubric.model_dump_json(indent=2)}\n\n"
        f"Offer of tenderer '{tenderer}':\n\n" + "\n\n".join(parts)
    )
    extraction = llm.chat_json(SYSTEM, user, BidExtraction)
    extraction.tenderer = tenderer  # folder name wins over anything the model inferred
    extraction.source_file = ", ".join(d.name for d in bid_docs)
    return extraction
