# ruff: noqa: F811  the fixtures are imported from test_api_checks
"""The S4-4 routes on Postgres through a real worker: the price summary and the evaluation
from two checked tenderers, the reports refused until every review is confirmed, then
listed and downloaded as Word files. Opt-in (-m postgres)."""
from __future__ import annotations

import copy

import pytest

from backend import deps
from test.checks.conftest import RULESET_ALL
from test.test_api_checks import CHENYU, NASI, _wait_done, api, worker  # noqa: F401  fixtures

pytestmark = pytest.mark.postgres


def test_price_summary_evaluation_and_reports_from_checked_results(api, worker):
    client, pid = api
    assert client.get(f"/projects/{pid}/price-summary").status_code == 409, "no confirmed rule set yet"
    body = {k: copy.deepcopy(v) for k, v in RULESET_ALL.items() if k not in ("status", "confirmed_by", "confirmed_at", "version", "project_id")}
    assert client.put(f"/projects/{pid}/ruleset/draft", json=body, headers=CHENYU).status_code == 200
    assert client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).status_code == 200
    empty = client.get(f"/projects/{pid}/price-summary").json()
    assert empty["rows"] == [] and empty["scheme"]["type"] == "cost_effectiveness" and empty["scheme"]["quantity"] == 875000
    assert client.get(f"/projects/{pid}/reports/price_summary.docx").status_code == 404, "nothing checked yet"

    jobs = client.post(f"/projects/{pid}/checks", json={"tenderers": ["Tenderer_A", "Tenderer_D"]}).json()["job_ids"]
    for job_id in jobs.values():
        assert _wait_done(client, pid, job_id)["state"] == "done"
    summary = client.get(f"/projects/{pid}/price-summary").json()
    rows = {r["tenderer"]: r for r in summary["rows"]}
    assert rows["Tenderer_A"]["cost_effectiveness"] == 18.92 and rows["Tenderer_D"]["cost_effectiveness"] == 168.95
    assert rows["Tenderer_A"]["ranking"] == 1 and rows["Tenderer_A"]["stage1"] == "needs_review", "the conditional letter of intent"
    assert summary["recommended"] == "Tenderer_D", "the only conforming offer until a reviewer decides on (i)"
    listed = client.get(f"/projects/{pid}/reports").json()
    assert [r["name"] for r in listed] == ["price_summary.docx", "summary_list.docx", "evaluation_record.docx"]
    assert listed[0]["version"] == 1 and listed[0]["generated_at"] is None and listed[0]["approver"] is None
    refused = client.get(f"/projects/{pid}/reports/summary_list.docx")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "review_pending"
    assert refused.json()["error"]["details"]["tenderers"] == ["Tenderer_A", "Tenderer_D"]
    assert client.get(f"/projects/{pid}/reports/nope.docx").status_code == 404

    r = client.patch(f"/projects/{pid}/bids/Tenderer_A/fields/i/document", json={"value": "N/A", "reason": "the tenderer is the manufacturer"}, headers=NASI)
    assert r.status_code == 200 and r.json()["verdicts"]["i"]["outcome"] == "pass" and r.json()["stage1"]["outcome"] == "pass"
    for t in ("Tenderer_A", "Tenderer_D"):
        assert client.post(f"/projects/{pid}/bids/{t}/review/confirm", headers=NASI).status_code == 200, t
    summary = client.get(f"/projects/{pid}/price-summary").json()
    assert summary["recommended"] == "Tenderer_A" and {r["reviewed_by"] for r in summary["rows"]} == {"nasi"}
    assert {r["tenderer"]: r["corrected"] for r in summary["rows"]} == {"Tenderer_A": [], "Tenderer_D": []}
    ev = client.get(f"/projects/{pid}/evaluation").json()
    assert ev["stage1_conclusion"] == "Stage I: Tenderer_A and Tenderer_D passed Stage I." and ev["recommended"] == "Tenderer_A"
    assert ev["tenderers"][0]["corrections"] == 1 and ev["tenderers"][0]["conforming"] is True
    docx = client.get(f"/projects/{pid}/reports/price_summary.docx")
    assert docx.status_code == 200 and docx.headers["content-type"].startswith(deps.DOCX_MIME) and docx.content[:2] == b"PK"
    from app.checks.reports import text_of
    text = text_of(docx.content)
    assert "Rule set version 1, confirmed by nasi" in text and "Reviews confirmed by: nasi" in text
    assert "Tenderer_A | 3,850,000.00 | 4.3 | 4.40 | 18.92 | 1" in text
    assert "Tenderer_A: manufacturer_letter.document corrected by nasi" not in text, "the price summary marks price corrections only"
    record = text_of(client.get(f"/projects/{pid}/reports/evaluation_record.docx").content)
    assert "Tenderer_A: manufacturer_letter.document corrected by nasi to 'N/A'" in record
    listed = client.get(f"/projects/{pid}/reports").json()
    assert listed[0]["generated_at"] is not None and listed[0]["approver"] == "nasi"
    assert client.get(f"/projects/{pid}/price-summary", params={"version": 2}).status_code == 404
