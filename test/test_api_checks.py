"""The S2 routes on Postgres: rule-set draft and confirmation with the approval rules,
one job per tenderer, jobs and their pages, and the result of a check that ran through
a real worker with the FakeLLM. Opt-in (-m postgres); CI's integration job runs it."""
from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from test.checks.conftest import CASE, RULESET

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
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict" and "need input" in json.dumps(r.json())


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
    assert sig["confidence"] == 0.92 and sig["redacted"] is False
    assert client.get(sig["page"]["image_url"]).headers["content-type"] == "image/png"
    verdict = res["verdicts"]["l"]
    assert verdict["outcome"] == "pass" and verdict["part"] == "A" and len(verdict["checks"]) == 4 and verdict["evidence"]
    assert res["stage1"] == {"outcome": "pass", "items": {"l": "pass"}} and res["stage2"] is None
    assert res["cost"]["calls"] == 4 and res["cost"]["usd"] == 0
    assert client.get(f"/projects/{pid}/bids/Tenderer_B/results", params={"version": 2}).status_code == 404
    doc = next(d for d in client.get(f"/projects/{pid}/documents").json() if d["tenderer"] == "Tenderer_B")
    pages = client.get(f"/projects/{pid}/documents/{doc['doc_id']}/pages").json()
    assert pages[12]["label"] == "noncollusive_certificate" and pages[12]["signed"] is True
    assert pages[0]["label"] == "company_profile"
