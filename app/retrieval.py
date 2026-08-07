"""Keyword-targeted page selection: prompt with the pages that matter, not a prefix.

Blind character truncation silently drops whatever happens to sit late in a document
— for a 300-page bid that can be the Price Schedule itself. Here pages are scored by
keyword families and the prompt budget is filled with the highest-scoring pages
(first page always included), keeping [Page N] markers so citations stay valid.
Documents that already fit the budget pass through whole.
"""
from __future__ import annotations

import re

from .ingest import Document
from .schemas import Rubric

# What defines the evaluation rules inside a tender document set.
RUBRIC_KEYWORDS = [
    "terms of tender", "tender evaluation", "evaluation", "marking scheme",
    "essential requirement", "price schedule", "compliance schedule",
    "particulars of goods", "tender form", "offer to be bound", "certificate",
    "non-collusive", "delivery", "warranty", "shelf life", "packing", "labelling",
    "quantity", "unit price", "submission", "special conditions",
]

# What matters inside any offer, regardless of the tender's specifics.
BID_BASE_KEYWORDS = [
    "offer to be bound", "tender form", "price schedule", "particulars of goods",
    "compliance schedule", "certificate", "non-collusive", "unit price",
    "estimated goods price", "total", "delivery", "signed", "signature",
]

_WORD = re.compile(r"[a-z]{5,}")


def keywords_for_text(text: str) -> list[str]:
    """Base bid keywords plus the significant words of a specific item/requirement."""
    return sorted(set(BID_BASE_KEYWORDS) | set(_WORD.findall(text.lower())))


def keywords_from_rubric(rubric: Rubric) -> list[str]:
    """Bid-extraction keywords derived from what THIS tender's rubric asks about."""
    kws = set(BID_BASE_KEYWORDS)
    for item in rubric.stage1_checklist:
        kws.update(_WORD.findall(item.item.lower()))
    for req in rubric.stage2_requirements:
        kws.update(_WORD.findall(req.requirement.lower()))
    return sorted(kws)


def _score(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(1 for kw in keywords if kw in lower)


def excerpt(doc: Document, keywords: list[str], char_budget: int) -> str:
    """The document's most relevant pages, in reading order, within char_budget."""
    full = doc.joined()
    if len(full) <= char_budget:
        return full

    pages = [p for p in doc.pages if p.text.strip()]
    if not pages:
        return ""
    first = pages[0]
    ranked = sorted(pages[1:], key=lambda p: (-_score(p.text, keywords), p.number))

    picked, used = [first], len(first.text) + 12
    for page in ranked:
        cost = len(page.text) + 12
        if used + cost > char_budget:
            continue
        picked.append(page)
        used += cost

    picked.sort(key=lambda p: p.number)
    out = "\n".join(f"[Page {p.number}]\n{p.text}" for p in picked)
    return out[:char_budget]


def excerpt_all(docs: list[Document], keywords: list[str], per_doc_budget: int,
                total_budget: int) -> str:
    """Multi-document excerpt under a shared total budget, with FILE headers."""
    parts: list[str] = []
    used = 0
    for doc in docs:
        chunk = excerpt(doc, keywords, per_doc_budget)
        if not chunk.strip():
            continue
        piece = f"### FILE: {doc.name}\n{chunk}"
        if used + len(piece) > total_budget:
            piece = piece[: max(0, total_budget - used)]
        parts.append(piece)
        used += len(piece)
        if used >= total_budget:
            break
    return "\n\n".join(parts)
