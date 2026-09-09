"""Citation grounding: claims that cite pages nobody read are demoted, never kept."""
from pathlib import Path

from app.grounding import cited_ok, ground_extraction, readable_pages
from app.ingest import Document, Page
from app.schemas import BidExtraction, BidPrice, ComplianceFinding, DocumentPresence


def _docs() -> list[Document]:
    doc = Document(path=Path("offer.pdf"), kind="scanned")
    doc.pages += [Page(1, "Contents: 11 Certificates and Declarations", "ocr"),
                  Page(2, "Tender Form signed.", "ocr"),
                  Page(3, "", "skipped"), Page(11, "", "skipped")]
    return [doc]


def test_readable_pages_excludes_unread():
    assert sorted(readable_pages(_docs())) == [1, 2]


def test_first_pass_claims_on_unread_pages_are_demoted():
    ext = BidExtraction(
        tenderer="X",
        documents=[DocumentPresence(checklist_id="S1-01", present=True, page=2, note="signed"),
                   DocumentPresence(checklist_id="S1-04", present=True, page=11,
                                    note="listed in contents"),
                   DocumentPresence(checklist_id="S1-02", present=True)],   # no citation: kept
        compliance=[ComplianceFinding(requirement_id="S2-01", complies="yes", page=11),
                    ComplianceFinding(requirement_id="S2-02", complies="no", page=2)],
        price=BidPrice())
    notes = ground_extraction(ext, _docs())
    by_id = {d.checklist_id: d for d in ext.documents}
    assert by_id["S1-01"].present is True                       # cited a read page
    assert by_id["S1-04"].present is False and "unread page 11" in by_id["S1-04"].note
    assert by_id["S1-02"].present is True                       # nothing to check
    assert ext.compliance[0].complies == "unclear" and "unread page 11" in ext.compliance[0].evidence
    assert ext.compliance[1].complies == "no"
    assert len(notes) == 2


def test_cited_ok_requires_read_page_and_optionally_quote():
    docs = _docs()
    assert cited_ok(2, None, docs, require_quote=False)
    assert not cited_ok(11, None, docs, require_quote=False)
    assert cited_ok(2, "Tender Form signed.", docs, require_quote=True)
    assert not cited_ok(2, "Certificate enclosed", docs, require_quote=True)
    assert not cited_ok(None, "x", docs, require_quote=False)


def test_contents_entry_is_not_evidence():
    # Seen on a local 8B model: "present, page 1 — Table of Contents entry for
    # '11 Certificates and Declarations'". Page 1 was read, so the unread-page rule
    # cannot fire; the contents rule must.
    from app.grounding import cites_contents_entry, ground_extraction
    from app.ingest import Document, Page
    from app.schemas import BidExtraction, BidPrice, DocumentPresence
    docs = [Document(path=Path("offer.pdf"), kind="scanned", pages=[
        Page(1, "Offer. Table of Contents: 11 Certificates and Declarations", "ocr"),
        Page(11, "", "skipped")])]
    ext = BidExtraction(tenderer="T", compliance=[], price=BidPrice(), documents=[
        DocumentPresence(checklist_id="S1-04", present=True, page=1,
                         note="Table of Contents entry for '11 Certificates and Declarations'"),
        DocumentPresence(checklist_id="S1-01", present=True, page=1, note="signed tender form on page 1")])
    notes = ground_extraction(ext, docs)
    assert ext.documents[0].present is False and "contents entry" in ext.documents[0].note
    assert ext.documents[1].present is True                      # ordinary citation untouched
    assert notes == ["S1-04: 'present' cited a contents entry — demoted to missing"]
    assert cites_contents_entry("listed in the contents page") and not cites_contents_entry("signed on p.3")
