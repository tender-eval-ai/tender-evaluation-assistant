"""End-to-end offline run: fixtures -> evaluation -> checkpoint JSON -> Word reports."""
import json

from test.conftest import FIXTURES

from app.pipeline import run_offline, summarize


def test_offline_pipeline_end_to_end(tmp_path):
    result = run_offline(FIXTURES, tmp_path, log=lambda *a: None)

    saved = json.loads((tmp_path / "evaluation.json").read_text())
    assert saved["recommended"] == "Bidder B"
    assert len(saved["stage1"]) == 4
    assert len(saved["stage2"]) == 3  # Bidder C eliminated at Stage I

    reports = tmp_path / "reports"
    for name in ("price_summary.docx", "summary_list.docx", "evaluation_record.docx"):
        assert (reports / name).is_file()

    text = summarize(result)
    assert "RECOMMENDED" in text and "Bidder B" in text
