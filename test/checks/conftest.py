"""The synthetic tender case as a project on disk, and a FakeLLM whose replies come from
the case's ground truth: every form's pages are labelled as such, every form is read with
the values the generator printed (from the page text where the offer is digital, so V4
finds them verbatim), and a second read agrees with the first unless told otherwise.
Everything else in the pipeline is real."""
from __future__ import annotations

import json
import re
import shutil
from functools import lru_cache
from pathlib import Path

import pytest

from app.checks.forms import FORMS
from app.checks.labels import labels_for
from app.checks.resolve import ItemPages
from app.checks.triage import PageLabel, PageLabels
from app.checks.verify import Reading, SecondRead
from test.fakes import FakeLLM, Rule

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "test" / "data" / "synthetic_tender"
TRUTH = json.loads((CASE / "ground_truth.json").read_text())
RULESET = json.loads((CASE / "ruleset_item_l.json").read_text())          # item (l) alone (S2)
RULESET_ALL = json.loads((CASE / "ruleset_all_items.json").read_text())   # every item (S4-3)
TEMPLATES = ROOT / "test" / "data" / "templates"
PID = "syn-2026-001"

_RANGE = re.compile(r"label pages (\d+)-(\d+)")
_ASKED = re.compile(r"^- (\w+):", re.M)
_FORM_FIND = re.compile(r"find the pages of form (\w+)")
_FORM_EXTRACT = re.compile(r"extract form (\w+) .*? from pages \[([\d, ]*)\]")
_FORM_SECOND = re.compile(r"read these fields of form (\w+)")
# The date as printed on Tenderer_A's certificate; the scans' dates are only on their images.
DATES = {"Tenderer_A": "14 August 2026"}
DEFAULT_DATE = "12 August 2026"
# The section headings the generator prints, as the model would read them.
TITLES = {
    "offer_to_be_bound": "Tender Form - PART 4 - OFFER TO BE BOUND", "price_schedule": "Price Schedule - Part A - Item 1",
    "price_schedule_parts_c_d": "Price Schedule - Parts C and D", "particulars_of_goods": "Particulars of Goods Schedule",
    "information_schedule": "Information Schedule - Tables A, B and C", "tender_sample_declaration": "Tender Sample Declaration",
    "documentary_evidence": "Documentary Evidence of Compliance", "manufacturer_letter": "Manufacturer's Letter of Intent",
    "board_resolution": "Certified Extract of Board Resolution", "contact_details": "Appendix to the Terms of Tender - Contact Details",
    "noncollusive_certificate": "Non-collusive Tendering Certificate", "compliance_schedule": "Compliance Schedule",
    "method_of_production": "Annex A Part I - Method of Production Statement",
}
SIGNED_LETTERS = ("a", "i", "l")


def truth_items(tenderer: str) -> dict:
    return TRUTH["bids"].get(tenderer, {}).get("items", {})


def cert_page(tenderer: str) -> int | None:
    return truth_items(tenderer).get("l", {}).get("page")


def page_labels(tenderer: str) -> dict[int, str]:
    """{page: label} for every form page of the offer, by the ground truth."""
    out: dict[int, str] = {}
    for letter, item in truth_items(tenderer).items():
        if item.get("page") and labels_for(letter):
            out[item["page"]] = labels_for(letter)[0]
    return out


def form_page(tenderer: str, form_id: str) -> int | None:
    label = FORMS[form_id].label
    return next((page for page, lab in page_labels(tenderer).items() if lab == label), None)


@lru_cache(maxsize=None)
def page_text(tenderer: str, page: int) -> str:
    """The text layer of one page of the offer ("" for a scan)."""
    from pypdf import PdfReader
    pdf = CASE / "bids" / tenderer / "offer.pdf"
    if not pdf.is_file():
        return ""
    reader = PdfReader(str(pdf))
    return (reader.pages[page - 1].extract_text() or "") if 0 < page <= len(reader.pages) else ""


def _line(tenderer: str, form_id: str, pattern: str, default: str | None = None) -> str | None:
    """A value read off the page's text layer by regex (digital offers), else `default`."""
    page = form_page(tenderer, form_id)
    m = re.search(pattern, page_text(tenderer, page)) if page else None
    return m.group(1).strip() if m else default


def form_values(tenderer: str, form_id: str, *, signed: bool = True, dated: bool = True) -> dict[str, str | None]:
    """The first reading of one form, as printed by the generator (tools/make_synthetic_tender.py)."""
    items, name = truth_items(tenderer), tenderer.replace("_", " ")
    values: dict[str, str | None] = {"document": TITLES[form_id]}
    if form_id == "offer_to_be_bound":
        values.update(tenderer_name=name, signature=f"authorised signatory of {name}",
                      date=_line(tenderer, form_id, r"on (\d+ August 2026)", DEFAULT_DATE), chop="Company chop affixed.")
    elif form_id == "price_schedule":
        v = items["b"]["values"]
        values.update(unit_price=f"{v['currency']} {v['unit_price']:.2f} per kg", currency=v["currency"],
                      optimal_dosage=f"{v['optimal_dosage_mg_per_l']} mg/L", quantity=f"{TRUTH['estimated_quantity_kg']:,} kg",
                      total=f"{v['currency']} {v['total']:,.2f}", signature="signature present")
    elif form_id == "price_schedule_parts_c_d":
        values.update(part_c="nil", part_d="not applicable")
    elif form_id == "particulars_of_goods":
        v = items["d"]["values"]
        values.update(product_name="Synthetic Coagulant Granules Type S", manufacturer=v["manufacturer"],
                      country_of_origin=_line(tenderer, form_id, r"Country of origin: (.+)"),
                      shelf_life_months=f"{v['shelf_life_months']} months", packaging=None, active_ingredient_pct=None, bulk_density=None)
    elif form_id == "information_schedule":
        values.update(track_record="Riverside Works", quality_certification="ISO 9001 certificate attached",
                      production_capacity=_line(tenderer, form_id, r"Production Capacity: (.+)", "t per year"))
    elif form_id == "documentary_evidence":
        values.update(evidence=_line(tenderer, form_id, r"(Test report TR-\d+)", "Test report"))
    elif form_id == "manufacturer_letter":
        values.update(manufacturer=items.get("i", {}).get("values", {}).get("manufacturer"), tenderer_name=name, signature="signature present")
    elif form_id == "board_resolution":
        values.update(resolution="the Managing Director is authorised to sign and submit the Tender", certified_by="Company Secretary")
    elif form_id == "contact_details":
        values.update(tenderer_name=name, contact_person="Ms Lee", telephone=_line(tenderer, form_id, r"(\+852 \d+ \d+)", "+852"),
                      email=f"tenders@{tenderer.lower()}.example", address="12 Harbour Road, Kwai Chung")
    elif form_id == "noncollusive_certificate":
        values.update(tenderer_name=name, signature="authorised signatory" if signed else None,
                      date=DATES.get(tenderer, DEFAULT_DATE) if dated else None)
    elif form_id == "compliance_schedule":
        values.update(delivery_days=f"{items['n']['values']['delivery_days']} days", non_compliances=None)
    elif form_id == "method_of_production":
        values.update(statement=_line(tenderer, form_id, r"Statement\n(.+)"))
    elif form_id == "tender_sample_declaration":
        values.update(declaration=None)
    return values


def fake_llm(tenderer: str, *, signed: bool = True, dated: bool = True, redacted: tuple[str, ...] = (),
             label_certificate: bool = True, second: dict | None = None, second_confidence: float = 0.88,
             values: dict[str, dict] | None = None) -> FakeLLM:
    """`signed`, `dated` and `redacted` shape the certificate's reading; `values` overrides
    any form's first reading field by field ({form id: {field: value}}); `second` overrides
    what V4's second read reports, by field name across forms. By default the second read
    agrees with the first."""
    labels = page_labels(tenderer)
    if not label_certificate:
        labels = {p: lab for p, lab in labels.items() if lab != "noncollusive_certificate"}
    signed_pages = {truth_items(tenderer)[x]["page"] for x in SIGNED_LETTERS if truth_items(tenderer).get(x, {}).get("page")}
    title_of = {FORMS[f].label: TITLES[f] for f in FORMS}

    def reading(form_id: str) -> dict[str, str | None]:
        base = form_values(tenderer, form_id, signed=signed, dated=dated)
        return {**base, **((values or {}).get(form_id) or {})}

    def label(call):
        lo, hi = map(int, _RANGE.search(call.user).groups())
        labs = []
        for seq in range(lo, hi + 1):
            lab = labels.get(seq, "company_profile")
            labs.append(PageLabel(seq=seq, label=lab, title=title_of.get(lab, f"Company Profile - Section {seq}"),
                                  summary="" if lab == "company_profile" else f"{title_of.get(lab, lab)}, filled in",
                                  signed=seq in signed_pages))
        return PageLabels(labels=labs)

    def resolve_reply(call):
        m = _FORM_FIND.search(call.user)
        wanted = FORMS[m.group(1)].label if m else "noncollusive_certificate"
        found = [int(x) for x in re.findall(rf"p(\d+) {wanted} ", call.user)]
        return ItemPages(pages=found, confidence=0.9 if found else 0.3, reason="" if found else f"no {wanted} page in the index")

    def extract_reply(call):
        m = _FORM_EXTRACT.search(call.user)
        form_id, pages = m.group(1), [int(p) for p in m.group(2).split(",") if p.strip()]
        out = reading(form_id)
        redacted_names = [n for n in redacted if form_id == "noncollusive_certificate" or n in out]
        return {"present": True, **out, "redacted": redacted_names, "page": pages[0] if pages else None, "confidence": 0.92}

    def second_reply(call):
        m = _FORM_SECOND.search(call.user)
        first = reading(m.group(1)) if m else {}
        merged = {**first, **(second or {})}
        return SecondRead(readings=[Reading(field=n, value=merged.get(n), confidence=second_confidence) for n in _ASKED.findall(call.user)])

    return FakeLLM([Rule(reply=label, out_model=PageLabels), Rule(reply=resolve_reply, out_model=ItemPages),
                    Rule(reply=extract_reply, match=r"extract form "), Rule(reply=second_reply, out_model=SecondRead)])


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """The case copied into DATA_DIR/projects/<pid>, as the API lays a project out; the test
    templates in the library."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pdir = tmp_path / "projects" / PID
    shutil.copytree(CASE / "bids", pdir / "bids")
    (pdir / "work").mkdir()
    (pdir / "meta.json").write_text(json.dumps({"id": PID, "name": "synthetic case", "synthetic": True,
                                                "data_class": "synthetic"}))
    return pdir


# ---------------------------------------------------------------- an offer read without a worker
def pages_of(tenderer: str) -> list[dict]:
    """The offer's pages as `render_offer` describes them, without rendering: the PDF stands in
    for every page image (the fake never looks at the bytes)."""
    bid = TRUTH["bids"][tenderer]
    pdf = str(CASE / "bids" / tenderer / "offer.pdf")
    return [{"seq": i, "doc": "offer.pdf", "page": i, "path": pdf, "has_text": not bid["scanned"]} for i in range(1, bid["pages"] + 1)]


def read_offer(tenderer: str, llm: FakeLLM | None = None, *, verify: bool = False, **fake_kw) -> dict:
    """Every form of the offer extracted (and, with `verify`, verified) with the fake, the
    forms' pages taken from the ground truth. What the pipeline's fields look like."""
    from app.checks.extract import extract_form
    from app.checks.verify import text_reader, verify_fields
    llm = llm or fake_llm(tenderer, **fake_kw)
    pages = pages_of(tenderer)
    fields: dict = {}
    text_of = text_reader(CASE / "bids" / tenderer)
    for form in FORMS.values():
        page = form_page(tenderer, form.id)
        form_pages = [page] if page else []
        fields.update(extract_form(form, pages, form_pages, tenderer, llm))
        if verify:
            fields = verify_fields(fields, pages, form_pages, form.specs(), tenderer, llm, text_of)
    return fields
