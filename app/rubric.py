"""Tender understanding: derive the per-tender evaluation rubric from tender documents.

Every tender defines its own completeness checklist, essential requirements and price
formula, so the rubric is extracted per project and saved as editable JSON for human
confirmation — the key checkpoint in the product design.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .ingest import Document
from .llm import LLM
from .retrieval import RUBRIC_KEYWORDS, excerpt_all
from .schemas import Rubric

SYSTEM = (
    "You support a public Tender Assessment Panel (TAP). From the tender documents "
    "provided, derive the evaluation rubric:\n"
    "1. stage1_checklist — every form, schedule or certificate a tenderer MUST submit "
    "(completeness check): tender form / offer to be bound, price schedule, particulars "
    "of goods schedule, compliance schedule, certificates, etc. Ids S1-01, S1-02, ...\n"
    "2. stage2_requirements — essential requirements whose breach disqualifies an offer "
    "(delivery period, warranty, shelf life, packing/labelling, mandatory technical "
    "specs marked 'essential'). Ids S2-01, S2-02, ...\n"
    "3. price_scheme — how the tender says price is assessed: 'cost_effectiveness' when "
    "the formula multiplies a dosage/consumption figure by unit price (e.g. D x M), "
    "otherwise 'unit_price_x_quantity'. Include the estimated quantity and unit from "
    "the Price Schedule.\n"
    "Cite where the tender states each item: set source_file to the '### FILE:' header "
    "and source_page to the [Page N] marker of the passage you relied on, and copy the "
    "requiring clause into source_clause. Only include what the documents actually "
    "require."
)

# Files most likely to define the rubric, in priority order for the prompt budget.
PRIORITY_KEYWORDS = [
    "terms of tender", "supplement", "special conditions", "technical specification",
    "schedule", "tender form", "interpretation",
]


def _priority(doc: Document) -> int:
    name = doc.name.lower()
    for rank, kw in enumerate(PRIORITY_KEYWORDS):
        if kw in name:
            return rank
    return len(PRIORITY_KEYWORDS)


def derive_rubric(tender_docs: list[Document], cfg: Config, llm: LLM) -> Rubric:
    docs = sorted(tender_docs, key=_priority)
    content = excerpt_all(docs, RUBRIC_KEYWORDS, cfg.max_doc_chars, cfg.max_total_chars)
    return llm.chat_json(SYSTEM, "Tender documents:\n\n" + content, Rubric)


def save_rubric(rubric: Rubric, path: Path) -> None:
    path.write_text(rubric.model_dump_json(indent=2))


def load_rubric(path: Path) -> Rubric:
    return Rubric.model_validate_json(path.read_text())
