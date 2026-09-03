"""Read-only tools the evidence-search agent may call over ONE tenderer's documents.

Every tool returns a string for the agent's transcript. Pages are addressed by their
1-based number (plus an optional file name for multi-file bids). `ocr_page` is the
tool that makes the agent worth having: pages beyond the initial OCR cap are
`skipped` at ingestion; the agent can read them on demand, within a per-bid budget.
Tools mutate the in-memory Document so later steps (and the final quote check) see
the newly read text; nothing is ever written except the OCR cache.
"""
from __future__ import annotations

import re

from .config import Config
from .ingest import Document, Page, ocr_single_page
from .retrieval import _score

MAX_RESULT_CHARS = 4000
TOOL_DESCRIPTIONS = (
    "list_pages() -> every page with its file, number, source (text | ocr | skipped = "
    "not read yet) and a one-line preview\n"
    "search_pages(query) -> pages already read that mention the query, best first, "
    "with snippets (skipped pages cannot match — read them first)\n"
    "read_page(page[, file]) -> the full text of a page already read\n"
    "ocr_page(page[, file]) -> read a skipped page through OCR (limited budget)\n"
    "finish(found, page, quote, note[, suggested]) -> end the search; quote must be "
    "copied verbatim from a page you read"
)


class BidTools:
    def __init__(self, docs: list[Document], cfg: Config, llm, ocr_budget: int):
        self.docs = docs
        self.cfg = cfg
        self.llm = llm
        self.ocr_budget = ocr_budget
        self.ocr_used = 0
        self.ocr_pages: list[tuple[str, int]] = []

    # ---------------------------------------------------------------- addressing
    def _doc(self, file: str | None) -> Document:
        if not self.docs:
            raise ValueError("this bid has no documents")
        if not file:
            return self.docs[0]
        for d in self.docs:
            if d.name == file or d.name.endswith(file):
                return d
        raise ValueError(f"unknown file '{file}' — files: {', '.join(d.name for d in self.docs)}")

    def _page(self, doc: Document, page: int | None) -> Page:
        if page is None or page < 1 or page > len(doc.pages):
            raise ValueError(f"{doc.name} has pages 1..{len(doc.pages)}")
        return doc.pages[page - 1]

    def page_text(self, page: int | None, file: str | None = None) -> str | None:
        try:
            return self._page(self._doc(file), page).text
        except ValueError:
            return None

    # ---------------------------------------------------------------- tools
    def list_pages(self) -> str:
        lines = []
        for doc in self.docs:
            for p in doc.pages:
                first = next((ln.strip() for ln in p.text.splitlines() if ln.strip()), "")
                preview = first[:80] if first else ("(not read yet)" if p.source == "skipped" else "(blank)")
                lines.append(f"{doc.name} p.{p.number} [{p.source}] {preview}")
        return "\n".join(lines) or "no pages"

    def search_pages(self, query: str, top_k: int = 5) -> str:
        words = re.findall(r"[a-z0-9]{3,}", (query or "").lower())
        hits = []
        for doc in self.docs:
            for p in doc.pages:
                if not p.text.strip():
                    continue
                score = _score(p.text, words) + (5 if query.lower() in p.text.lower() else 0)
                if score:
                    hits.append((score, doc, p))
        hits.sort(key=lambda t: (-t[0], t[1].name, t[2].number))
        if not hits:
            return ("no page read so far mentions that — pages marked [skipped] in "
                    "list_pages have not been read; use ocr_page on the likely one")
        out = []
        for score, doc, p in hits[:top_k]:
            low = p.text.lower()
            pos = next((low.find(w) for w in words if low.find(w) >= 0), 0)
            snippet = re.sub(r"\s+", " ", p.text[max(0, pos - 80): pos + 160]).strip()
            out.append(f"{doc.name} p.{p.number} (score {score}): …{snippet}…")
        return "\n".join(out)

    def read_page(self, page: int | None, file: str | None = None) -> str:
        doc = self._doc(file)
        p = self._page(doc, page)
        if p.source == "skipped":
            return (f"{doc.name} p.{page} has not been read (scanned page beyond the "
                    f"initial OCR cap) — call ocr_page({page}) to read it")
        return p.text[:MAX_RESULT_CHARS] or "(blank page)"

    def ocr_page(self, page: int | None, file: str | None = None) -> str:
        doc = self._doc(file)
        p = self._page(doc, page)
        if p.source != "skipped" and p.text.strip():
            return "already read:\n" + p.text[:MAX_RESULT_CHARS]
        if self.ocr_used >= self.ocr_budget:
            return (f"OCR budget exhausted ({self.ocr_budget} page(s) for this bid) — "
                    "decide with what you have read")
        p.text = ocr_single_page(doc.path, page - 1, self.cfg, self.llm)
        p.source = "ocr"
        self.ocr_used += 1
        self.ocr_pages.append((doc.name, page))
        return p.text[:MAX_RESULT_CHARS] or "(blank page)"
