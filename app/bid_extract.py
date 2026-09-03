"""Per-bid extraction: which required documents are present, compliance evidence, and
price fields — every finding cites the page it came from."""
from __future__ import annotations

from .config import Config
from .grounding import ground_extraction
from .ingest import Document
from .llm import LLM
from .retrieval import excerpt_all, keywords_from_rubric
from .schemas import BidExtraction, BidPrice, Rubric

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
    "but with values redacted still counts as present. A table of contents entry, index "
    "line or generic section heading is NOT evidence that a specific document is present "
    "or a requirement met — only the document itself, or an explicit statement, counts. "
    "Cite only pages whose content you were given. Never guess numbers."
)


def extract_bid(tenderer: str, bid_docs: list[Document], rubric: Rubric,
                cfg: Config, llm: LLM) -> BidExtraction:
    content = excerpt_all(bid_docs, keywords_from_rubric(rubric),
                          cfg.max_doc_chars, cfg.max_total_chars)
    user = (
        f"Evaluation rubric:\n{rubric.model_dump_json(indent=2)}\n\n"
        f"Offer of tenderer '{tenderer}':\n\n" + content
    )
    extraction = llm.chat_json(SYSTEM, user, BidExtraction)
    extraction.tenderer = tenderer  # folder name wins over anything the model inferred
    extraction.source_file = ", ".join(d.name for d in bid_docs)
    ground_extraction(extraction, bid_docs)  # citations of unread pages are not evidence
    return extraction


PRICE_SYSTEM = (
    "You support a public Tender Assessment Panel (TAP). From ONE tenderer's offer "
    "(page numbers marked as [Page N]) extract ONLY the price fields: unit price, "
    "currency, optimal dosage (only if the price scheme uses one), and the quoted "
    "total / estimated goods price if stated. Numbers exactly as printed; null for "
    "anything not stated. Never guess."
)

PRICE_KEYWORDS = ["price schedule", "unit price", "estimated goods price", "total",
                  "dosage", "currency", "hk$", "per litre", "per kg"]


def extract_price(tenderer: str, bid_docs: list[Document], rubric: Rubric,
                  cfg: Config, llm: LLM) -> BidPrice:
    """Targeted re-extraction of the price fields alone — used after the evidence-search
    agent has read pages (e.g. a Price Schedule) that the first pass could not see."""
    content = excerpt_all(bid_docs, PRICE_KEYWORDS, cfg.max_doc_chars, cfg.max_total_chars)
    user = (f"Price scheme: {rubric.price_scheme.model_dump_json()}\n\n"
            f"Offer of tenderer '{tenderer}':\n\n" + content)
    return llm.chat_json(PRICE_SYSTEM, user, BidPrice)
