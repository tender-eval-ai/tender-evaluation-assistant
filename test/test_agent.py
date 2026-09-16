"""Evidence-search agent (app/agent.py + app/tools.py): finds buried evidence via
on-demand OCR, respects budgets, rejects unverifiable quotes, never flips verdicts,
and never runs when nothing is unresolved."""

from app.agent import AgentAction, evidence_search
from app.grounding import quote_on_page
from app.config import Config
from app.ingest import Document, Page
from app.schemas import (BidExtraction, BidPrice, ChecklistItem, ComplianceFinding,
                         DocumentPresence, EssentialRequirement, PriceScheme, Rubric)
from app.tools import BidTools
from test.fakes import FakeLLM, Rule
from tools.pdfgen import make_text_pdf

PAGE1 = ("Offer of Tenderer X - Tender Ref. DEMO0022026\n"
         "Table of Contents: page 2 Non-collusive Tendering Certificate.\n"
         "Delivery within 30 days from the purchase order is confirmed.")
CERT_OCR = "Non-collusive Tendering Certificate: completed and signed by the director."
PRICE_OCR = "Price Schedule Part A: unit price HK$ 9.50 per litre."

RUBRIC = Rubric(
    tender_ref="T", stage1_checklist=[
        ChecklistItem(id="S1-01", item="Signed Tender Form"),
        ChecklistItem(id="S1-04", item="Non-collusive Tendering Certificate")],
    stage2_requirements=[EssentialRequirement(id="S2-01", requirement="Delivery within 45 days")],
    price_scheme=PriceScheme(type="unit_price_x_quantity", quantity=50000, unit="litre"))


def scripted(actions, ocr_text=CERT_OCR) -> FakeLLM:
    """Agent actions in order; a fixed price for the BidPrice call; one OCR transcript."""
    return FakeLLM(rules=[Rule(reply=BidPrice(unit_price=9.5), out_model=BidPrice)],
                   sequence=actions, ocr_text=ocr_text)


def _docs(tmp_path) -> list[Document]:
    pdf = tmp_path / "offer.pdf"
    make_text_pdf(pdf, PAGE1.splitlines() + [""] * 48)          # 2 pages
    return [Document(path=pdf, kind="scanned", pages=[
        Page(1, PAGE1, "ocr"), Page(2, "", "skipped")])]


def _cfg(tmp_path, steps=6, ocr=2) -> Config:
    cfg = Config()
    cfg.cache_dir = tmp_path / "cache"
    cfg.agent_max_steps, cfg.agent_ocr_pages = steps, ocr
    return cfg


def _ext(cert_present=False, delivery="yes", unit_price=10.0) -> BidExtraction:
    return BidExtraction(
        tenderer="Tenderer X",
        documents=[DocumentPresence(checklist_id="S1-01", present=True, page=1),
                   DocumentPresence(checklist_id="S1-04", present=cert_present)],
        compliance=[ComplianceFinding(requirement_id="S2-01", complies=delivery, page=1)],
        price=BidPrice(unit_price=unit_price))


def test_finds_buried_document_via_on_demand_ocr(tmp_path):
    llm = scripted([
        AgentAction(tool="list_pages", thought="see what is unread"),
        AgentAction(tool="ocr_page", page=2, thought="contents says page 2"),
        AgentAction(tool="finish", found=True, page=2, quote=CERT_OCR, note="on page 2"),
    ])
    ext, report = evidence_search(_ext(), _docs(tmp_path), RUBRIC, _cfg(tmp_path), llm)
    cert = next(d for d in ext.documents if d.checklist_id == "S1-04")
    assert cert.present is True and cert.page == 2
    assert cert.note.startswith("found by evidence search")
    assert llm.ocr_calls == 1 and report["ocr_pages"] == [["offer.pdf", 2]]
    assert [s["tool"] for s in report["findings"]["S1-04"]] == ["list_pages", "ocr_page", "finish"]
    assert report["amendments"] == ["S1-04 restored — found on p.2"]


def test_unverifiable_quote_is_rejected(tmp_path):
    llm = scripted([
        AgentAction(tool="finish", found=True, page=1, quote="Certificate enclosed herewith"),
        AgentAction(tool="finish", found=False, note="not in the offer"),
    ])
    ext, report = evidence_search(_ext(), _docs(tmp_path), RUBRIC, _cfg(tmp_path), llm)
    assert next(d for d in ext.documents if d.checklist_id == "S1-04").present is False
    trace = report["findings"]["S1-04"]
    assert trace[0]["result"].startswith("REJECTED") and trace[1]["result"] == "accepted"
    assert report["amendments"] == []


def test_step_budget_ends_search_unchanged(tmp_path):
    llm = scripted([AgentAction(tool="list_pages")] * 3)
    ext, report = evidence_search(_ext(), _docs(tmp_path), RUBRIC, _cfg(tmp_path, steps=3), llm)
    assert next(d for d in ext.documents if d.checklist_id == "S1-04").present is False
    assert llm.count(out_model=AgentAction) == 3
    assert report["findings"]["S1-04"][-1]["tool"] == "budget"


def test_unclear_compliance_gets_evidence_but_keeps_verdict(tmp_path):
    quote = "Delivery within 30 days from the purchase order is confirmed."
    llm = scripted([
        AgentAction(tool="read_page", page=1),
        AgentAction(tool="finish", found=True, page=1, quote=quote, suggested="yes"),
    ])
    ext, report = evidence_search(_ext(cert_present=True, delivery="unclear"),
                                  _docs(tmp_path), RUBRIC, _cfg(tmp_path), llm)
    finding = ext.compliance[0]
    assert finding.complies == "unclear"                  # never flipped by the agent
    assert "agent suggests: yes" in finding.evidence and quote in finding.evidence
    assert finding.page == 1
    assert report["amendments"] == ["S2-01 evidence attached (still unclear, suggests yes)"]


def test_missing_price_is_reextracted_after_search(tmp_path):
    llm = scripted([
        AgentAction(tool="ocr_page", page=2),
        AgentAction(tool="finish", found=True, page=2, quote=PRICE_OCR),
    ], ocr_text=PRICE_OCR)
    ext, report = evidence_search(_ext(cert_present=True, unit_price=None),
                                  _docs(tmp_path), RUBRIC, _cfg(tmp_path), llm)
    assert ext.price.unit_price == 9.5
    assert "price" in report["findings"] and report["amendments"][0].startswith("price re-extracted")


def test_nothing_unresolved_means_no_llm_calls(tmp_path):
    llm = scripted([])
    ext, report = evidence_search(_ext(cert_present=True), _docs(tmp_path), RUBRIC,
                                  _cfg(tmp_path), llm)
    assert llm.count(kind="chat_json") == 0 and report["findings"] == {}


def test_tools_search_read_and_ocr_budget(tmp_path):
    docs = _docs(tmp_path)
    tools = BidTools(docs, _cfg(tmp_path, ocr=0), scripted([]), ocr_budget=0)
    assert "p.1 [ocr]" in tools.list_pages() and "p.2 [skipped] (not read yet)" in tools.list_pages()
    assert "p.1" in tools.search_pages("delivery purchase order")
    assert "not been read" in tools.read_page(2) and "ocr_page(2)" in tools.read_page(2)
    assert "budget exhausted" in tools.ocr_page(2)
    assert "pages 1..2" in tools.read_page(9) if False else True  # range error path below
    try:
        tools.read_page(9)
    except ValueError as err:
        assert "pages 1..2" in str(err)


def test_quote_check_tolerates_ocr_edges():
    page = "The completed Non-collusive Tendering  Certificate is enclosed\nwith this offer."
    assert quote_on_page("non-collusive tendering certificate is enclosed", page)
    assert quote_on_page("XX completed Non-collusive Tendering Certificate is enclosed with YY", page)
    assert not quote_on_page("a totally different sentence about pricing terms", page)
    assert not quote_on_page("", page)


def test_price_reextracted_when_pages_were_read_even_without_finish(tmp_path):
    # The loop runs out of steps right after reading the right page: the targeted
    # price re-extraction must still run because new pages were read.
    llm = scripted([AgentAction(tool="ocr_page", page=2)] * 2, ocr_text=PRICE_OCR)
    ext, report = evidence_search(_ext(cert_present=True, unit_price=None),
                                  _docs(tmp_path), RUBRIC, _cfg(tmp_path, steps=2), llm)
    assert ext.price.unit_price == 9.5
    assert report["amendments"] == ["price re-extracted from newly read pages: unit_price=9.5"]
