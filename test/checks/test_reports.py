"""S4-4: the three Word reports on the synthetic case, as golden text. Each states the
rule-set version and its confirmer, the models, who confirmed the reviews and when it
was generated, and marks every correction and edited rule. `UPDATE_GOLDEN=1` rewrites
test/data/synthetic_tender/golden/*.txt after a deliberate change."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.checks import reports
from app.checks.pricing import evaluation
from app.rulesets.schema import Edit, RuleSet
from test.checks.conftest import CASE, RULESET_ALL, TEMPLATES
from test.checks.test_pricing import offers

GOLDEN = CASE / "golden"
WHEN = datetime(2026, 9, 22, 9, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    monkeypatch.delenv("PRICING_USD_HKD", raising=False)


def bundle() -> reports.Bundle:
    """The four reviewed offers; item (n) of the rule set edited by a person."""
    ruleset = RuleSet.model_validate(RULESET_ALL)
    n = next(i for i in ruleset.items if i.letter == "n")
    n.status = "edited"
    n.edit = Edit(by="chenyu", at=WHEN, reason="delivery within 30 days per the Special Conditions")
    offs = offers()
    return reports.Bundle(project="SYN-2026-001 Supply of Synthetic Coagulant Granules (Type S)", ruleset=ruleset, offers=offs,
                          evaluation=evaluation(ruleset, offs), models={"text": "deepseek-chat", "vision": "qwen3-vl:8b-16k"},
                          generated_at=WHEN)


def check_golden(name: str, text: str) -> None:
    path = GOLDEN / (Path(name).stem + ".txt")
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")
    assert path.is_file(), f"no golden file {path}; run with UPDATE_GOLDEN=1"
    assert text.strip() == path.read_text().strip(), f"{name} differs from its golden text; UPDATE_GOLDEN=1 rewrites it"


@pytest.mark.parametrize("name", reports.NAMES)
def test_each_report_matches_its_golden_text(name):
    text = reports.text_of(reports.render(name, bundle()))
    check_golden(name, text)


def test_every_report_states_version_models_approvers_and_generation_time():
    for name in reports.NAMES:
        text = reports.text_of(reports.render(name, bundle()))
        assert "Rule set version 1, confirmed by nasi on 2026-09-22 12:00 UTC" in text, name
        assert "Models: text deepseek-chat, vision qwen3-vl:8b-16k" in text and "Reviews confirmed by: nasi" in text, name
        assert "Generated 2026-09-22 09:30 UTC" in text, name


def test_the_price_summary_ranks_and_marks_the_recommended_offer():
    data = reports.render("price_summary.docx", bundle())
    text = reports.text_of(data)
    assert "Summary of Cost-effectiveness" in text
    assert "Tenderer_A | 3,850,000.00 | 4.3 | 4.40 | 18.92 | 1" in text
    assert "Tenderer_D | 49,276,500.00 | 3 | 56.32 | 168.95 | 4" in text
    assert "Tenderer_D: quoted in US$, converted at 7.8 HK$/US$" in text and "Tenderer_C: not a conforming offer" in text
    from docx import Document
    import io
    doc = Document(io.BytesIO(data))
    row_a = next(r for r in doc.tables[0].rows if r.cells[0].text == "Tenderer_A")
    assert all(run.bold for cell in row_a.cells for p in cell.paragraphs for run in p.runs), "the recommended offer is in bold"


def test_the_summary_list_and_the_record_mark_corrections_and_edited_rules():
    b = bundle()
    summary = reports.text_of(reports.render("summary_list.docx", b))
    assert "Tenderer_C is not considered further: item (l)" in summary
    assert "recommended acceptance of Tenderer_A's offer with a cost-effectiveness of HK$18.92" in summary
    assert "Tenderer_A: manufacturer_letter.document corrected by nasi to 'N/A' (the model read None): the tenderer is the manufacturer" in summary
    assert "item (n) The Compliance Schedule: chenyu: delivery within 30 days per the Special Conditions" in summary
    record = reports.text_of(reports.render("evaluation_record.docx", b))
    assert "Tenderer_C: Stage I disqualified, Stage II pass, review confirmed by nasi" in record
    assert "(l) The signed Non-collusive Tendering Certificate | A | disqualified | document is missing" in record
    assert "(i) Where the Tenderer is not the manufacturer of the Goods, the letter of intent from the manufacturer | A | pass | - | document by nasi" in record
    assert "Rule-set items edited by a person:" in record


def test_an_unreviewed_bundle_says_so():
    b = bundle()
    for o in b.offers:
        o.reviewed_by = None
    text = reports.text_of(reports.render("evaluation_record.docx", b))
    assert "Reviews confirmed by: none yet" in text and "review not confirmed" in text
