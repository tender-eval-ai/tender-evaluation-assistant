"""Deterministic grounding of citations — the code-side guardrail behind every LLM
claim: a citation is evidence only if it points at a page the pipeline actually
read, and (where a verbatim quote is required) the quote appears on that page.

Applied after first-pass extraction (`ground_extraction`), to every refutation of the
verification pass, and to every `finish` of the evidence-search agent. A finding that
fails grounding is not deleted — it is demoted to the state that triggers a real
look: "present" becomes missing (so verification and the agent search for it),
"yes"/"no" becomes "unclear" (so a human decides).
"""
from __future__ import annotations

import re

from .ingest import Document
from .schemas import BidExtraction


def readable_pages(docs: list[Document]) -> dict[int, str]:
    """page number -> text, for pages with content (multi-file bids merge by number)."""
    pages: dict[int, str] = {}
    for doc in docs:
        for p in doc.pages:
            if p.text.strip():
                pages[p.number] = (pages.get(p.number, "") + "\n" + p.text).strip()
    return pages


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("-\n", "")).strip().lower()


def quote_on_page(quote: str, page_text: str | None) -> bool:
    """Verbatim check with tolerance for OCR edge noise: the whole normalised quote, or
    any 6-word window of it, must occur in the page text."""
    if not quote or not page_text:
        return False
    q, t = _norm(quote), _norm(page_text)
    if q in t:
        return True
    words = q.split(" ")
    if len(words) < 6:
        return False
    return any(" ".join(words[i:i + 6]) in t for i in range(len(words) - 5))


def cited_ok(page: int | None, quote: str | None, docs: list[Document],
             require_quote: bool) -> bool:
    """Is (page, quote) an acceptable citation against what was actually read?"""
    if page is None:
        return False
    text = readable_pages(docs).get(page)
    if text is None:
        return False
    return quote_on_page(quote or "", text) if require_quote else True


CONTENTS_RE = re.compile(r"\b(table of contents|contents (entry|page|list)|index entry)\b", re.I)


def cites_contents_entry(note: str | None) -> bool:
    """The model itself says its evidence is a contents/index entry. The prompts state
    that a contents entry is not evidence; an 8B local model was seen ignoring that,
    so the rule is enforced here — a listing proves the document was planned, not
    that it is in the offer."""
    return bool(note) and bool(CONTENTS_RE.search(note))


def ground_extraction(extraction: BidExtraction, docs: list[Document]) -> list[str]:
    """Demote first-pass findings that cite pages nobody read, or whose stated
    evidence is a contents entry. Returns amendment notes."""
    read = readable_pages(docs)
    if not docs:
        return []
    notes: list[str] = []
    for d in extraction.documents:
        if d.present and d.page is not None and d.page not in read:
            d.present = False
            d.note = (f"first pass cited unread page {d.page} — not accepted as evidence"
                      + (f"; it said: {d.note[:150]}" if d.note else ""))
            notes.append(f"{d.checklist_id}: 'present' cited unread p.{d.page} — demoted to missing")
        elif d.present and cites_contents_entry(d.note):
            d.present = False
            d.note = f"first pass cited a contents entry — not evidence; it said: {d.note[:150]}"
            notes.append(f"{d.checklist_id}: 'present' cited a contents entry — demoted to missing")
    for c in extraction.compliance:
        if c.complies in ("yes", "no") and c.page is not None and c.page not in read:
            was = c.complies
            c.complies = "unclear"
            c.evidence = (f"first pass judged '{was}' citing unread page {c.page} — needs "
                          f"evidence" + (f"; it said: {c.evidence[:150]}" if c.evidence else ""))
            notes.append(f"{c.requirement_id}: '{was}' cited unread p.{c.page} — demoted to unclear")
    return notes
