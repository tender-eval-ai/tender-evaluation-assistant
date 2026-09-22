"""The S2 routes on Postgres: rule-set draft and confirmation with the approval rules,
one job per tenderer, jobs and their pages, and the result of a check that ran through
a real worker with the FakeLLM. Opt-in (-m postgres); CI's integration job runs it."""
from __future__ import annotations

import copy
import importlib
import os
import shutil
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from test.checks.conftest import CASE, RULESET, RULESET_ALL, TEMPLATES

pytestmark = pytest.mark.postgres

CHENYU, NASI = {"X-User": "chenyu"}, {"X-User": "nasi"}


def draft_body() -> dict:
    """A fresh copy every time: one test marks an item needs_input and must not leak it."""
    return {k: copy.deepcopy(v) for k, v in RULESET.items()
            if k not in ("status", "confirmed_by", "confirmed_at", "version", "project_id")}


@pytest.fixture
def api(tmp_path, monkeypatch):
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("VENDOR_CHECK_LLM_FACTORY", "test.checks.fake_factory:factory")
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    for k, v in {"JOBS_HEARTBEAT": "1", "JOBS_STALLED_AFTER": "3", "JOBS_SWEEP_EVERY": "1", "JOBS_POLL": "0.5"}.items():
        monkeypatch.setenv(k, v)
    from app import db
    from app.jobs import queue as q, tasks
    db.reset_for_tests()
    db.migrate()
    q.apply_schema(tasks.app)
    import backend.api as api
    importlib.reload(api)
    client = TestClient(api.app)
    pid = client.post("/projects", json={"name": "synthetic case", "data_class": "synthetic"}).json()["id"]
    pdir = tmp_path / "data" / "projects" / pid
    shutil.rmtree(pdir / "bids")
    shutil.copytree(CASE / "bids", pdir / "bids")
    shutil.copy(CASE / "tender" / "09 Schedules.pdf", pdir / "tender" / "09 Schedules.pdf")
    yield client, pid
    api.deps.reset_runner()


@pytest.fixture
def worker():
    proc = subprocess.Popen([sys.executable, "-m", "app.jobs.worker", "--name", "api-test", "--pipelines",
                             "app.checks.vendor_check", "--no-migrate"], env=os.environ.copy())
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)                # SIGTERM drains a running job; a slow runner may need longer
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def confirm_v1(client, pid) -> dict:
    assert client.put(f"/projects/{pid}/ruleset/draft", json=draft_body(), headers=CHENYU).status_code == 200
    r = client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI)
    assert r.status_code == 200, r.json()
    return r.json()


def test_a_draft_is_validated_confirmed_by_someone_else_and_versioned(api):
    client, pid = api
    assert client.get(f"/projects/{pid}/ruleset").status_code == 404
    r = client.put(f"/projects/{pid}/ruleset/draft", json=draft_body(), headers=CHENYU)
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["status"] == "draft"
    assert r.json()["created_by"] == "chenyu" and r.json()["project_id"] == pid
    assert client.get(f"/projects/{pid}/ruleset").json()["status"] == "draft"
    bad = client.put(f"/projects/{pid}/ruleset/draft", json={**draft_body(), "items": [{"letter": "zz"}]}, headers=CHENYU)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_failed" and bad.json()["error"]["details"]["errors"]
    self_ok = client.post(f"/projects/{pid}/ruleset/confirm", headers=CHENYU)
    assert self_ok.status_code == 403 and self_ok.json()["error"]["code"] == "self_approval"
    confirmed = client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).json()
    assert confirmed["status"] == "confirmed" and confirmed["confirmed_by"] == "nasi" and confirmed["version"] == 1
    assert client.get(f"/projects/{pid}/ruleset", params={"version": 1}).json()["status"] == "confirmed"
    assert client.get(f"/projects/{pid}/ruleset", params={"version": 9}).status_code == 404
    again = client.put(f"/projects/{pid}/ruleset/draft", json=draft_body(), headers=NASI).json()
    assert again["version"] == 2 and again["parent_version"] == 1 and again["status"] == "draft"
    versions = client.get(f"/projects/{pid}/ruleset/versions").json()
    assert [(v["version"], v["status"], v["parent_version"]) for v in versions] == [(1, "confirmed", None), (2, "draft", 1)]
    kinds = [e["kind"] for e in client.get(f"/projects/{pid}/events").json()["items"]]
    assert kinds == ["ruleset.draft_saved", "ruleset.confirmed", "ruleset.draft_saved"]
    assert client.get(f"/projects/{pid}/events").json()["items"][1]["user"] == "nasi"


def test_a_draft_that_still_needs_input_cannot_be_confirmed(api):
    client, pid = api
    body = draft_body()
    body["items"][0]["status"] = "needs_input"
    assert client.put(f"/projects/{pid}/ruleset/draft", json=body, headers=CHENYU).status_code == 200
    r = client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict" and r.json()["error"]["details"]["blockers"][0]["kind"] == "item_status"


def test_checks_need_a_confirmed_rule_set_then_run_one_job_per_tenderer(api):
    client, pid = api
    r = client.post(f"/projects/{pid}/checks")
    assert r.status_code == 409 and r.json()["error"]["code"] == "unconfirmed_ruleset"
    confirm_v1(client, pid)
    r = client.post(f"/projects/{pid}/checks", json={"tenderers": ["Nobody"]})
    assert r.status_code == 404 and r.json()["error"]["details"] == {"tenderers": ["Nobody"]}
    r = client.post(f"/projects/{pid}/checks")
    assert r.status_code == 202 and sorted(r.json()["job_ids"]) == ["Tenderer_A", "Tenderer_B", "Tenderer_C", "Tenderer_D"]
    job_ids = r.json()["job_ids"]
    page = client.get(f"/projects/{pid}/jobs", params={"limit": 3}).json()
    assert len(page["items"]) == 3 and page["next_cursor"]
    rest = client.get(f"/projects/{pid}/jobs", params={"limit": 3, "cursor": page["next_cursor"]}).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    job = client.get(f"/projects/{pid}/jobs/{job_ids['Tenderer_B']}").json()
    assert job["kind"] == "vendor_check" and job["tenderer"] == "Tenderer_B" and job["state"] in ("queued", "running")
    assert client.get(f"/projects/{pid}/jobs/nope").status_code == 404
    again = client.post(f"/projects/{pid}/checks", json={"tenderers": ["Tenderer_B"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"
    assert again.json()["error"]["details"]["job_ids"] == {"Tenderer_B": job_ids["Tenderer_B"]}
    assert client.get(f"/projects/{pid}/bids/Tenderer_B/results").status_code == 404
    assert "checks.started" in [e["kind"] for e in client.get(f"/projects/{pid}/events").json()["items"]]


def _wait_done(client, pid, job_id, timeout=90) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/projects/{pid}/jobs/{job_id}").json()
        if job["state"] in ("done", "failed", "dead"):
            return job
        time.sleep(0.3)
    pytest.fail(f"job {job_id} did not finish: {job}")


def test_a_check_through_the_worker_yields_fields_with_citations_a_verdict_and_its_cost(api, worker):
    client, pid = api
    confirm_v1(client, pid)
    job_id = client.post(f"/projects/{pid}/checks", json={"tenderers": ["Tenderer_B"]}).json()["job_ids"]["Tenderer_B"]
    job = _wait_done(client, pid, job_id)
    assert job["state"] == "done" and job["ruleset_version"] == 1, job
    res = client.get(f"/projects/{pid}/bids/Tenderer_B/results").json()
    assert res["tenderer"] == "Tenderer_B" and res["run_id"] == job_id and res["ruleset_version"] == 1
    sig = res["fields"]["l"]["signature"]
    assert sig["value"] == "authorised signatory" and sig["page"]["page"] == 13 and sig["page"]["file"] == "offer.pdf"
    assert sig["confidence"] == 0.9 and sig["redacted"] is False, "V4: the mean of the two reads"
    assert sig["verification"] == {"verified": True, "method": "second_read", "second_value": "authorised signatory",
                                   "note": "a second, independent read agrees"}
    assert sig["page"]["quote"] is None and sig["page"]["box"] is None      # Tenderer_B is scanned: no text layer
    assert client.get(sig["page"]["image_url"]).headers["content-type"] == "image/png"
    verdict = res["verdicts"]["l"]
    assert verdict["outcome"] == "pass" and verdict["part"] == "A" and len(verdict["checks"]) == 4 and verdict["evidence"]
    # I1.10: every check's `field` indexes res["fields"][letter]; the engine's display
    # text ("tenderer name") does not, which is what this asserts against.
    assert all(c["field"] in res["fields"]["l"] for c in verdict["checks"]), verdict["checks"]
    assert res["stage1"] == {"outcome": "pass", "items": {"l": "pass"}} and res["stage2"] is None
    assert res["cost"]["calls"] == 27 and res["cost"]["usd"] == 0, "3 triage, 2 resolve, 11 extracts, 11 second reads"
    assert list(res["fields"]) == ["l"] and list(res["verdicts"]) == ["l"], "the rule set names item (l) alone"
    assert client.get(f"/projects/{pid}/bids/Tenderer_B/results", params={"version": 2}).status_code == 404
    doc = next(d for d in client.get(f"/projects/{pid}/documents").json() if d["tenderer"] == "Tenderer_B")
    pages = client.get(f"/projects/{pid}/documents/{doc['doc_id']}/pages").json()
    assert pages[12]["label"] == "noncollusive_certificate" and pages[12]["signed"] is True
    assert pages[0]["label"] == "company_profile"


def test_the_driver_script_runs_the_case_end_to_end(api, worker, tmp_path, monkeypatch):
    """tools/check_synthetic_case.py against the same API: import from the inbox, draft
    and confirm, check every tenderer, read the results."""
    from tools.check_synthetic_case import Api, run, table
    client, _ = api
    monkeypatch.setenv("INBOX_DIR", str(CASE.parent))
    import backend.api as backend_api
    backend_api.deps.configure()
    rows = run(Api(client), case="synthetic_tender", tenderers=["Tenderer_B", "Tenderer_C"], timeout=120, log=lambda *_: None)
    by = {r["tenderer"]: r for r in rows}
    assert by["Tenderer_B"]["outcome"] == "pass" and by["Tenderer_B"]["page"] == 13 and by["Tenderer_B"]["calls"] == 27
    assert by["Tenderer_B"]["verified"] is True and by["Tenderer_B"]["confidence"] == 0.9
    assert by["Tenderer_C"]["outcome"] == "disqualified" and by["Tenderer_C"]["signature"] is None
    assert "Tenderer_B" in table(rows)


def test_every_item_is_checked_against_a_fifteen_item_rule_set_and_corrected_per_form(api, worker):
    """S4-3: Tenderer_D (scanned, not the manufacturer) against the all-items rule set: one
    verdict per item, the fields of every form, Stage I and II summaries; a correction on the
    price schedule's unit price is judged by the math rule at once."""
    client, pid = api
    body = {k: copy.deepcopy(v) for k, v in RULESET_ALL.items() if k not in ("status", "confirmed_by", "confirmed_at", "version", "project_id")}
    assert client.put(f"/projects/{pid}/ruleset/draft", json=body, headers=CHENYU).status_code == 200
    assert client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).status_code == 200
    job_id = client.post(f"/projects/{pid}/checks", json={"tenderers": ["Tenderer_D"]}).json()["job_ids"]["Tenderer_D"]
    assert _wait_done(client, pid, job_id)["state"] == "done"
    res = client.get(f"/projects/{pid}/bids/Tenderer_D/results").json()
    assert set(res["verdicts"]) == set("abcdefghijklmno") and set(res["fields"]) == set("abcdefghijklmno")
    assert res["stage1"]["outcome"] == "pass" and res["stage1"]["items"]["j"] == "dormant" and res["stage2"]["outcome"] == "pass"
    price = res["fields"]["b"]
    assert price["unit_price"]["value"] == 7.22 and price["unit_price"]["page"]["page"] == 3 and price["currency"]["value"] == "US$"
    assert price["unit_price"]["verification"]["method"] == "second_read" and price["unit_price"]["confidence"] == 0.9
    assert res["fields"]["c"]["optimal_dosage"]["value"] == 3.0 and res["fields"]["i"]["manufacturer"]["value"] == "Northfield Polymers D Inc"
    assert res["fields"]["l"]["signature"]["value"] == "authorised signatory" and res["verdicts"]["l"]["outcome"] == "pass"
    checks = {c["field"]: c for c in res["verdicts"]["b"]["checks"]}
    assert checks["total"]["status"] == "pass" and checks["total"]["field_id"] == "price_schedule.total"
    r = client.patch(f"/projects/{pid}/bids/Tenderer_D/fields/b/unit_price", json={"value": 7.5, "reason": "misread 7.22"}, headers=NASI)
    assert r.status_code == 200, r.json()
    after = r.json()
    assert after["fields"]["b"]["unit_price"]["value"] == 7.5 and after["fields"]["b"]["unit_price"]["model_value"] == 7.22
    assert after["fields"]["b"]["unit_price"]["verification"] is None, "a person's value carries no verification record"
    total = next(c for c in after["verdicts"]["b"]["checks"] if c["field"] == "total")
    assert total["status"] == "needs_review" and "product" in total["note"] and after["verdicts"]["b"]["outcome"] == "needs_review"
    assert after["stage1"]["outcome"] == "needs_review"
    assert client.patch(f"/projects/{pid}/bids/Tenderer_D/fields/q/nothing", json={"value": 1, "reason": "x"}, headers=NASI).status_code == 404
    confirm = client.post(f"/projects/{pid}/bids/Tenderer_D/review/confirm", headers=NASI)
    assert confirm.status_code == 409 and confirm.json()["error"]["details"]["fields"] == ["price_schedule.total"]
