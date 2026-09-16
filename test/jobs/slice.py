"""The vertical slice both orchestrator variants run: one vendor, item (l), the
Non-collusive Tendering Certificate.

    triage      V1   label pages, six page images per LLM call
    resolve     V2   which pages hold item (l), one call with the page index
    extract     V3   read the certificate's fields from its page image, one call
    await       L5   pause until the tender's rubric is confirmed
    decide      V6   engine only, no LLM: pass or disqualified under the confirmed rubric

Everything an orchestrator needs to checkpoint is a plain function argument or return
value, so a step can be tested alone and progress can be saved per page. The LLM is
always a FakeLLM whose rules compute their replies from the prompt, so any vendor of
any size can be run without scripting every call.
"""
from __future__ import annotations

import os
import re
from typing import Callable

from pydantic import BaseModel

from test.fakes import FakeLLM, Rule
from test.jobs import knobs

PAGES_PER_TRIAGE = 6
ITEM = "l"
Progress = Callable[[str, int, int], None]      # step, done, total


class PageLabel(BaseModel):
    page: int
    label: str


class PageLabels(BaseModel):
    labels: list[PageLabel]


class ItemPages(BaseModel):
    pages: list[int]
    confidence: float


class CertificateFields(BaseModel):
    present: bool
    signed: bool
    dated: bool
    page: int | None


def make_vendor(vendor: str, n_pages: int = 16, cert_page: int = 13) -> dict:
    """A vendor's bid as page images (bytes); the certificate sits on `cert_page`."""
    return {"vendor": vendor, "pages": [f"{vendor}:page:{i}".encode() for i in range(1, n_pages + 1)],
            "cert_page": cert_page}


def triage(pages: list[bytes], vendor: str, llm: FakeLLM, progress: Progress, start_at: int = 0,
           max_batches: int | None = None) -> list[dict]:
    """Label every page, six per call. `start_at` lets a resumed worker skip labelled batches;
    `max_batches` lets an orchestrator checkpoint after each batch by calling one at a time."""
    labels: list[dict] = []
    total = len(pages)
    for k, i in enumerate(range(start_at, total, PAGES_PER_TRIAGE)):
        if max_batches is not None and k >= max_batches:
            break
        batch = pages[i:i + PAGES_PER_TRIAGE]
        out = llm.chat_json("Label each page.", f"vendor {vendor}: label pages {i + 1}-{i + len(batch)} of {total}",
                            PageLabels, images=batch)
        labels.extend(lab.model_dump() for lab in out.labels)
        progress("triage", i + len(batch), total)
    return labels


def resolve(labels: list[dict], vendor: str, llm: FakeLLM) -> ItemPages:
    index = "\n".join(f"p{lab['page']} {lab['label']}" for lab in labels)
    return llm.chat_json("Find the pages for item (l).", f"vendor {vendor}: resolve item (l)\n{index}", ItemPages)


def extract(pages: list[bytes], item_pages: ItemPages, vendor: str, llm: FakeLLM) -> CertificateFields:
    if not item_pages.pages:
        return CertificateFields(present=False, signed=False, dated=False, page=None)
    images = [pages[p - 1] for p in item_pages.pages]
    return llm.chat_json("Read the certificate.", f"vendor {vendor}: extract item (l) from pages {item_pages.pages}",
                         CertificateFields, images=images)


def decide(fields: dict, rubric: dict) -> dict:
    """Engine, no LLM. A missing Part A item disqualifies; the rubric says what 'complete' means."""
    reasons = []
    if not fields.get("present"):
        reasons.append("certificate not found")
    if rubric.get("requires_signature", True) and not fields.get("signed"):
        reasons.append("not signed")
    if rubric.get("requires_date", False) and not fields.get("dated"):
        reasons.append("not dated")
    return {"item": ITEM, "tier": "A", "outcome": "pass" if not reasons else "disqualified",
            "reasons": reasons, "rubric_version": rubric.get("version")}


# ---------------------------------------------------------------- the fake's rules
_RANGE = re.compile(r"label pages (\d+)-(\d+)")
_PAGES = re.compile(r"from pages \[([\d, ]+)\]")


def fake_rules(cert_page: int) -> list[Rule]:
    def label(call):
        lo, hi = map(int, _RANGE.search(call.user).groups())
        return PageLabels(labels=[PageLabel(page=p, label="noncollusive_certificate" if p == cert_page else "other")
                                  for p in range(lo, hi + 1)])

    def resolve_reply(call):
        found = [int(m) for m in re.findall(r"p(\d+) noncollusive_certificate", call.user)]
        return ItemPages(pages=found, confidence=0.9 if found else 0.2)

    def extract_reply(call):
        pages = [int(p) for p in _PAGES.search(call.user).group(1).split(",")]
        return CertificateFields(present=True, signed=True, dated=False, page=pages[0])

    return [Rule(reply=label, out_model=PageLabels), Rule(reply=resolve_reply, out_model=ItemPages),
            Rule(reply=extract_reply, out_model=CertificateFields)]


def make_llm(cert_page: int, log_path: str | None = None, delay: tuple[float, float] | None = None,
             faults: dict | None = None) -> FakeLLM:
    """The worker's LLM. Delay and faults come from the harness knobs when a worker is a
    subprocess: FAKE_DELAY="0.3,0.6", FAKE_FAULTS="2:429,3:429,5:permanent". Fault indexes
    count calls across every process and attempt of the scenario (the shared log), so a
    worker that retries a job sees the next fault, not the same one again."""
    if delay is None and knobs.get("FAKE_DELAY"):
        lo, hi = (float(x) for x in knobs.get("FAKE_DELAY").split(","))
        delay = (lo, hi)
    log_path = log_path or os.environ.get("FAKE_LLM_LOG")
    offset = 0
    if faults is None and knobs.get("FAKE_FAULTS"):
        faults = {}
        for part in knobs.get("FAKE_FAULTS").split(","):
            n, kind = part.split(":")
            faults[int(n)] = ProviderError(kind)
        if log_path and os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as fh:
                offset = sum(1 for line in fh if line.strip())
    return FakeLLM(rules=fake_rules(cert_page), log_path=log_path, delay=delay, faults=faults, index_offset=offset)


class ProviderError(RuntimeError):
    """A simulated provider failure: '429' is transient (retry), 'permanent' is not."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind
        self.transient = kind == "429"
