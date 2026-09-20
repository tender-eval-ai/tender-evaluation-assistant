"""The synthetic tender case as a project on disk, and a FakeLLM whose replies come from
the case's ground truth: the certificate page is labelled as such, the certificate is
read as signed and dated. Everything else in the pipeline is real."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from app.checks.extract_item_l import Certificate
from app.checks.resolve import ItemPages
from app.checks.triage import PageLabel, PageLabels
from test.fakes import FakeLLM, Rule

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "test" / "data" / "synthetic_tender"
TRUTH = json.loads((CASE / "ground_truth.json").read_text())
RULESET = json.loads((CASE / "ruleset_item_l.json").read_text())
PID = "syn-2026-001"

_RANGE = re.compile(r"label pages (\d+)-(\d+)")
_PAGES = re.compile(r"from pages \[([\d, ]+)\]")


def cert_page(tenderer: str) -> int | None:
    return TRUTH["bids"].get(tenderer, {}).get("items", {}).get("l", {}).get("page")


def fake_llm(tenderer: str, *, signed: bool = True, dated: bool = True, redacted: tuple[str, ...] = (),
             label_certificate: bool = True) -> FakeLLM:
    page = cert_page(tenderer)

    def label(call):
        lo, hi = map(int, _RANGE.search(call.user).groups())
        labs = []
        for seq in range(lo, hi + 1):
            if label_certificate and seq == page:
                labs.append(PageLabel(seq=seq, label="noncollusive_certificate", title="Non-collusive Tendering Certificate",
                                      summary="certificate of independent tendering, signed", signed=True))
            else:
                labs.append(PageLabel(seq=seq, label="company_profile", title=f"Company Profile - Section {seq}"))
        return PageLabels(labels=labs)

    def resolve_reply(call):
        found = [int(m) for m in re.findall(r"p(\d+) noncollusive_certificate", call.user)]
        return ItemPages(pages=found, confidence=0.9 if found else 0.3, reason="" if found else "no certificate page in the index")

    def extract_reply(call):
        pages = [int(p) for p in _PAGES.search(call.user).group(1).split(",")]
        return Certificate(present=True, title="Non-collusive Tendering Certificate", tenderer_name=tenderer.replace("_", " "),
                           signatory="authorised signatory" if signed else None, signed=signed,
                           date="12 August 2026" if dated else None, redacted=list(redacted), page=pages[0], confidence=0.92)

    return FakeLLM([Rule(reply=label, out_model=PageLabels), Rule(reply=resolve_reply, out_model=ItemPages),
                    Rule(reply=extract_reply, out_model=Certificate)])


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """The case copied into DATA_DIR/projects/<pid>, as the API lays a project out."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pdir = tmp_path / "projects" / PID
    shutil.copytree(CASE / "bids", pdir / "bids")
    (pdir / "work").mkdir()
    (pdir / "meta.json").write_text(json.dumps({"id": PID, "name": "synthetic case", "synthetic": True,
                                                "data_class": "synthetic"}))
    return pdir
