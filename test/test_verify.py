"""Adversarial verification: refuted negatives are amended, upheld ones untouched,
and positive findings are never re-checked."""
from pathlib import Path

from app.config import Config
from app.ingest import Document, Page
from app.rubric import load_rubric
from app.schemas import (BidExtraction, BidPrice, ComplianceFinding,
                         DocumentPresence)
from app.verify import Verdict, verify_extraction
from test.conftest import FIXTURES


class ScriptedLLM:
    """Returns pre-scripted verdicts in order; records the claims it was asked about."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.claims = []

    def chat_json(self, system, user, out_model, chain=None):
        assert out_model is Verdict
        self.claims.append(user.split("\n")[1])
        return self.verdicts.pop(0)


def make_extraction() -> BidExtraction:
    return BidExtraction(
        tenderer="Bidder X",
        documents=[
            DocumentPresence(checklist_id="S1-01", present=True, page=1),
            DocumentPresence(checklist_id="S1-04", present=False),
        ],
        compliance=[
            ComplianceFinding(requirement_id="S2-01", complies="yes", page=2),
            ComplianceFinding(requirement_id="S2-02", complies="no",
                              evidence="shelf life 6 months stated", page=3),
        ],
        price=BidPrice(unit_price=10.0),
    )


def make_docs() -> list[Document]:
    """12 pages; the refutation quotes used below really are on pages 7 and 12."""
    doc = Document(path=Path("offer.pdf"), kind="text")
    doc.pages.append(Page(number=1, text="Offer content with certificate mention.", source="text"))
    for n in range(2, 13):
        text = {7: "Particulars: shelf life 18 months on page 7 as stated.",
                12: "Non-collusive Tendering Certificate: completed and signed."}.get(n, "filler")
        doc.pages.append(Page(number=n, text=text, source="text"))
    return [doc]


def run(verdicts):
    rubric = load_rubric(FIXTURES / "rubric.json")
    llm = ScriptedLLM(verdicts)
    ext, amendments = verify_extraction(make_extraction(), make_docs(), rubric,
                                        Config(), llm)
    return ext, amendments, llm


def test_only_negative_findings_are_challenged():
    _, _, llm = run([Verdict(refuted=False), Verdict(refuted=False)])
    assert len(llm.claims) == 2  # one missing doc + one non-compliance, nothing else


def test_upheld_findings_stay_unchanged():
    ext, amendments, _ = run([Verdict(refuted=False), Verdict(refuted=False)])
    assert ext.documents[1].present is False
    assert ext.compliance[1].complies == "no"
    assert amendments == []


def test_refuted_missing_document_is_restored():
    ext, amendments, _ = run([
        Verdict(refuted=True, evidence="Certificate: completed and signed", page=12),
        Verdict(refuted=False),
    ])
    assert ext.documents[1].present is True
    assert ext.documents[1].page == 12
    assert "restored by verification" in ext.documents[1].note
    assert len(amendments) == 1


def test_refuted_noncompliance_demoted_to_unclear_not_yes():
    ext, amendments, _ = run([
        Verdict(refuted=False),
        Verdict(refuted=True, evidence="shelf life 18 months on page 7", page=7),
    ])
    assert ext.compliance[1].complies == "unclear"  # human decides, never auto-pass
    assert "counter-evidence" in ext.compliance[1].evidence
    assert len(amendments) == 1


def test_refutation_without_evidence_is_ignored():
    ext, _, _ = run([Verdict(refuted=True, evidence=""), Verdict(refuted=False)])
    assert ext.documents[1].present is False  # evidence-free refutation doesn't count

def test_refutation_citing_unread_page_or_missing_quote_is_ignored():
    # Page 99 was never read; page 3 is read but does not contain the quote.
    ext, amendments, _ = run([
        Verdict(refuted=True, evidence="Certificate: completed and signed", page=99),
        Verdict(refuted=True, evidence="shelf life 18 months", page=3),
    ])
    assert ext.documents[1].present is False
    assert ext.compliance[1].complies == "no"
    assert len(amendments) == 2 and all("refutation ignored" in a for a in amendments)
