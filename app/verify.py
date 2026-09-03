"""Adversarial verification of negative findings before they reach a report.

A false "document missing" or "non-compliant" determination is the costliest
extraction failure — it can wrongly eliminate a tenderer. Every negative finding
gets an independent re-check that tries to REFUTE it against a targeted excerpt of
the offer:

- refuted `present=false`  -> flipped to present, with the found page (objective fact)
- refuted `complies="no"`  -> demoted to "unclear" (goes to the human clarification
  list; a machine never auto-passes a compliance judgment)

Upheld findings pass through unchanged. Human-corrected extractions are never
re-verified (the caller skips them).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .config import Config
from .grounding import cited_ok
from .ingest import Document
from .llm import LLM
from .retrieval import excerpt_all, keywords_for_text
from .schemas import BidExtraction, Rubric

SYSTEM = (
    "You are an adversarial second reviewer for a public Tender Assessment Panel. "
    "A first-pass reviewer made a NEGATIVE finding about a tenderer's offer. Your only "
    "job is to try to REFUTE it: search the offer content for evidence that the "
    "document IS present or the requirement IS met. Set refuted=true ONLY if you can "
    "quote concrete evidence VERBATIM and cite its [Page N]. A table of contents entry "
    "or generic section heading is not evidence that a specific document is present. If "
    "you find no such evidence, uphold the finding with refuted=false. Never invent "
    "evidence."
)


class Verdict(BaseModel):
    refuted: bool
    evidence: str = Field(default="", description="Quoted counter-evidence, if any")
    page: Optional[int] = None


def _challenge(llm: LLM, claim: str, offer_content: str) -> Verdict:
    user = f"Negative finding to challenge:\n{claim}\n\nOffer content:\n{offer_content}"
    return llm.chat_json(SYSTEM, user, Verdict)


def verify_extraction(extraction: BidExtraction, bid_docs: list[Document],
                      rubric: Rubric, cfg: Config, llm: LLM) -> tuple[BidExtraction, list[str]]:
    """Re-check every negative finding; returns the (possibly amended) extraction and
    a human-readable list of amendments."""
    amendments: list[str] = []
    items = {i.id: i.item for i in rubric.stage1_checklist}
    reqs = {r.id: r.requirement for r in rubric.stage2_requirements}

    for doc_finding in extraction.documents:
        if doc_finding.present:
            continue
        item = items.get(doc_finding.checklist_id, doc_finding.checklist_id)
        content = excerpt_all(bid_docs, keywords_for_text(item),
                              cfg.max_doc_chars, cfg.max_total_chars)
        verdict = _challenge(
            llm, f"The offer does NOT include: {item}", content)
        if verdict.refuted and verdict.evidence and not cited_ok(
                verdict.page, verdict.evidence, bid_docs, require_quote=True):
            amendments.append(f"{extraction.tenderer}/{doc_finding.checklist_id}: refutation "
                              f"ignored — quote not found on p.{verdict.page}")
        elif verdict.refuted and verdict.evidence:
            doc_finding.present = True
            doc_finding.page = verdict.page
            doc_finding.note = f"restored by verification pass: {verdict.evidence[:200]}"
            amendments.append(f"{extraction.tenderer}/{doc_finding.checklist_id}: "
                              f"'missing' refuted (p.{verdict.page})")

    for comp_finding in extraction.compliance:
        if comp_finding.complies != "no":
            continue
        req = reqs.get(comp_finding.requirement_id, comp_finding.requirement_id)
        content = excerpt_all(bid_docs, keywords_for_text(req),
                              cfg.max_doc_chars, cfg.max_total_chars)
        verdict = _challenge(
            llm, f"The offer does NOT comply with the essential requirement: {req}", content)
        if verdict.refuted and verdict.evidence and not cited_ok(
                verdict.page, verdict.evidence, bid_docs, require_quote=True):
            amendments.append(f"{extraction.tenderer}/{comp_finding.requirement_id}: refutation "
                              f"ignored — quote not found on p.{verdict.page}")
        elif verdict.refuted and verdict.evidence:
            comp_finding.complies = "unclear"
            comp_finding.evidence = (f"verification found counter-evidence, needs human "
                                     f"review: {verdict.evidence[:200]}")
            comp_finding.page = verdict.page or comp_finding.page
            amendments.append(f"{extraction.tenderer}/{comp_finding.requirement_id}: "
                              f"'non-compliant' demoted to unclear (p.{verdict.page})")

    return extraction, amendments
