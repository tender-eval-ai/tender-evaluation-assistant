"""The synthetic tender-style case (tools/make_synthetic_tender.py) must keep the document
structure the parser and the schedule locator key on: 17 sub-documents, a running
header of "Tender Ref." / "<Document name>" / "Page N of M" at the top of every page,
PART headings with per-part clause numbering, clause numbers on their own line above
the title, and a Completeness Check Schedule with "Part A/B/C" heading lines, items
(a) to (o) and paragraph cross-references that resolve to real clauses. The small
profile is generated here (a few seconds, offline)."""
import json
import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from tools.make_synthetic_tender import PROFILES, generate

FIXTURE = Path(__file__).resolve().parents[1] / "test" / "data" / "synthetic_tender"


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample") / "case"
    truth = generate(out, "small")
    return out, truth


def _text(path: Path, page: int) -> str:
    return PdfReader(str(path)).pages[page - 1].extract_text() or ""


def test_seventeen_documents_bound_into_one_combined_file(case):
    out, truth = case
    docs = truth["tender"]["documents"]
    assert len(docs) == 17
    combined = truth["tender"]["combined"]
    assert sum(d["pages"] for d in docs) == combined["pages"]
    assert len(PdfReader(str(out / combined["file"])).pages) == combined["pages"]
    for d in docs:
        assert len(PdfReader(str(out / d["file"])).pages) == d["pages"]


def test_supplement_pages_carry_the_running_header(case):
    out, _ = case
    reader = PdfReader(str(out / "tender" / "04 Terms of Tender (Supplement).pdf"))
    n = len(reader.pages)
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        assert text.startswith(f"Tender Ref.: SYN-2026-001\nTerms of Tender (Supplement)\nPage {i} of {n}\n")
        assert "Page" not in text.splitlines()[-1], "no bottom footer: the page line is a top running header"
    everything = "\n".join(p.extract_text() for p in reader.pages)
    assert re.search(r"(?m)^13\.\nNon-collusive Tendering Certificate$", everything), "number above its title"


def test_standard_terms_have_ref_no_header_and_per_part_numbering(case):
    out, _ = case
    reader = PdfReader(str(out / "tender" / "02 Interpretation, Terms of Tender and General Conditions of Contract.pdf"))
    assert reader.pages[0].extract_text().startswith("Ref. No. SYN-TERMS-1 (January 2026)\nPage 1 of")
    everything = "\n".join(p.extract_text() for p in reader.pages)
    assert re.search(r"(?m)^PART 2\nTERMS OF TENDER", everything)
    assert re.search(r"(?m)^PART 3\nGENERAL CONDITIONS OF CONTRACT", everything)
    assert len(re.findall(r"(?m)^1\.$", everything)) >= 3, "clause numbering restarts in every PART"
    assert re.search(r"(?m)^3\.3 ", everything)


def test_completeness_check_schedule_rows_parts_and_references(case):
    out, truth = case
    ccs = truth["tender"]["completeness_check_schedule"]
    letters: list[str] = []
    for page in ccs["pages"]:
        text = _text(out / ccs["file"], page)
        assert text.startswith("Tender Ref.: SYN-2026-001\nCompleteness Check Schedule\nPage "), "found by its running header"
        letters += re.findall(r"(?m)^\(([a-o])\) ", text)
    assert letters == list("abcdefghijklmno")
    assert [i["letter"] for i in ccs["items"]] == list("abcdefghijklmno")
    for item in ccs["items"]:
        text = _text(out / ccs["file"], item["schedule_page"])
        assert f"({item['letter']}) " in text
        assert re.search(rf"(?m)^Part {item['part']}$", text), "items sit under a Part heading line"
        assert re.search(r"Paragraphs? [\d.]+", text)
        for ref in item["references"]:
            clause_text = _text(out / ref["file"], ref["page"])
            assert re.search(rf"(?m)^\s*{re.escape(ref['paragraph'])}[.\s]", clause_text), (item["letter"], ref)
            combined_text = _text(out / truth["tender"]["combined"]["file"], ref["combined_page"])
            assert re.search(rf"(?m)^\s*{re.escape(ref['paragraph'])}[.\s]", combined_text)


def test_bids_cover_native_scanned_missing_and_not_manufacturer(case):
    out, truth = case
    bids = truth["bids"]
    assert set(bids) == {"Tenderer_A", "Tenderer_B", "Tenderer_C", "Tenderer_D"}
    for bid in bids.values():
        assert set(bid["items"]) == set("abcdefghijklmno")
    a, b, c, d = (bids[k] for k in ("Tenderer_A", "Tenderer_B", "Tenderer_C", "Tenderer_D"))
    assert "Non-collusive Tendering Certificate" in _text(out / a["file"], a["items"]["l"]["page"])
    assert "Unit Price" in _text(out / a["file"], a["items"]["b"]["page"])
    assert a["items"]["b"]["page"] == a["items"]["c"]["page"], "items (b) and (c) share one page"
    assert not c["items"]["l"]["present"] and c["items"]["l"]["page"] is None
    assert a["items"]["i"]["not_applicable"] and d["items"]["i"]["present"]
    assert not d["items"]["j"]["present"]
    scanned = PdfReader(str(out / b["file"]))
    assert len(scanned.pages) == PROFILES["small"]["scan_pages"]
    assert all(not (p.extract_text() or "").strip() for p in scanned.pages), "scanned bid has no text layer"
    assert b["items"]["l"]["page"] == PROFILES["small"]["cert_page"]
    assert b["injection_page"] == PROFILES["small"]["injection_page"]


def test_generation_is_deterministic(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    generate(first, "small")
    generate(second, "small")
    files = sorted(p for p in first.rglob("*") if p.is_file())
    assert files
    for f in files:
        assert f.read_bytes() == (second / f.relative_to(first)).read_bytes(), f.name


def test_committed_fixture_matches_the_generator(case):
    if not (FIXTURE / "ground_truth.json").exists():
        pytest.skip("fixture not generated; run tools/make_synthetic_tender.py")
    _, truth = case
    assert json.loads((FIXTURE / "ground_truth.json").read_text()) == truth
