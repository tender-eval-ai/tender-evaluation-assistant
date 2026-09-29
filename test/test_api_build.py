# ruff: noqa: F811  (the `api` fixture is imported from test_api_checks and named in each test)
"""The rule-set build through the API and a real worker with the FakeLLM: L0 to L4 on the
synthetic tender, the draft it saves, the nodes route, and a rebuild that keeps a person's
edit. Opt-in (-m postgres); CI's integration job runs it."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test.checks.conftest import CASE
from test.test_api_checks import CHENYU, _wait_done, api  # noqa: F401  (the fixture)

pytestmark = pytest.mark.postgres

TEMPLATES = Path(__file__).resolve().parent / "data" / "templates"


@pytest.fixture
def build_worker(monkeypatch):
    monkeypatch.setenv("RULESET_BUILD_LLM_FACTORY", "test.rulesets.fake_factory:factory")
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    proc = subprocess.Popen([sys.executable, "-m", "app.jobs.worker", "--name", "build-test", "--pipelines",
                             "app.rulesets.build_job", "--no-migrate"], env=os.environ.copy())
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)                # SIGTERM drains a running job; a slow runner may need longer
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _whole_tender(client, pid):
    pdir = Path(os.environ["DATA_DIR"]) / "projects" / pid
    for pdf in (CASE / "tender").glob("*.pdf"):
        shutil.copy(pdf, pdir / "tender" / pdf.name)
    return pdir


def _build(client, pid) -> dict:
    r = client.post(f"/projects/{pid}/ruleset/build", headers=CHENYU)
    assert r.status_code == 202, r.text
    job = _wait_done(client, pid, r.json()["job_id"], timeout=240)
    assert job["state"] == "done", job
    return job


def test_the_build_job_drafts_the_rule_set_from_the_tender(api, build_worker):
    client, pid = api
    _whole_tender(client, pid)
    docs = client.get(f"/projects/{pid}/documents").json()
    form = next(d for d in docs if d["file"] == "01 Tender Form.pdf")
    assert client.get(f"/projects/{pid}/documents/{form['doc_id']}/nodes").status_code == 409, "not parsed yet"

    r = client.post(f"/projects/{pid}/ruleset/build", headers=CHENYU)
    assert r.status_code == 202
    twice = client.post(f"/projects/{pid}/ruleset/build", headers=CHENYU)
    assert twice.status_code == 409 and twice.json()["error"]["details"]["job_id"] == r.json()["job_id"]
    job = _wait_done(client, pid, r.json()["job_id"], timeout=240)
    assert job["state"] == "done", job
    assert job["kind"] == "ruleset_build" and job["tenderer"] is None and job["step"] is None

    rs = client.get(f"/projects/{pid}/ruleset").json()
    assert rs["version"] == 1 and rs["status"] == "draft" and rs["created_by"] == "rule_builder"
    assert rs["prompt_version"] == "match-v1+slots-v2+novel-v2+additions-v1" and rs["updated_by"] == "rule_builder"
    by = {i["letter"]: i for i in rs["items"]}
    assert sorted(by) == list("abcdefghijklmno") and [p["part"] for p in rs["parts"]] == ["A", "B", "C"]
    assert by["l"]["template"] == "noncollusive_certificate" and by["l"]["status"] == "verified" and len(by["l"]["rules"]) == 4
    quantity = by["b"]["slots"]["estimated_quantity"]
    assert by["b"]["status"] == "verified" and quantity["value"] == 875000 and quantity["verified"]
    assert quantity["citation"]["node_id"] == "09-Schedules:00-Price-Schedule:PA:(2)" and quantity["citation"]["file"] == "tender/09 Schedules.pdf"
    assert [r["id"] for r in by["b"]["rules"]][-1] == "price_schedule.certificate_of_analysis", "the additions step ran"
    assert "04-Terms-of-Tender-Supplement:5.1" in [g["node_id"] for g in rs["gaps"]], "a templated item's clauses are walked by L4"
    assert by["a"]["status"] == "novel" and [r["id"] for r in by["a"]["rules"]] == ["offer_to_be_bound.offer_signed"]
    assert by["a"]["notes"][-1]["citation"]["node_id"] == "01-Tender-Form:P4:3"
    assert sum(i["status"] == "gap" for i in rs["items"]) == 12 and rs["gaps"] and all(g["reason"] is None for g in rs["gaps"])

    nodes = client.get(f"/projects/{pid}/documents/{form['doc_id']}/nodes").json()
    assert nodes and all(n["node_id"].startswith("01-Tender-Form") for n in nodes)
    clause = next(n for n in nodes if n["node_id"] == "01-Tender-Form:P4:3")
    assert clause["kind"] == "clause" and clause["number"] == "3" and clause["page"] == 3 and len(clause["box"]) == 4
    assert clause["part"] == "Part 4" and clause["text"] and clause["is_coarse"] is True, "the parser's fields come through"
    assert {"label", "char_start", "char_end", "doc_name", "ref_no", "rule_version"} <= clause.keys()
    kinds = [e["kind"] for e in client.get(f"/projects/{pid}/events").json()["items"]]
    assert kinds[-2:] == ["ruleset.build_started", "ruleset.built"] or kinds[-1] == "ruleset.built"


def test_a_rebuild_keeps_a_persons_edit_and_the_cached_parse(api, build_worker):
    client, pid = api
    pdir = _whole_tender(client, pid)
    _build(client, pid)
    parsed_at = (pdir / "work" / "nodes.json").stat().st_mtime
    r = client.patch(f"/projects/{pid}/ruleset/items/a", headers=CHENYU,
                     json={"note": {"kind": "reference", "text": "keep me"}, "reason": "a reviewer's note"})
    assert r.status_code == 200 and r.json()["status"] == "edited"

    _build(client, pid)
    rs = client.get(f"/projects/{pid}/ruleset").json()
    by = {i["letter"]: i for i in rs["items"]}
    assert rs["version"] == 1 and by["a"]["status"] == "edited" and by["a"]["notes"][-1]["text"] == "keep me"
    assert by["l"]["status"] == "verified" and rs["updated_by"] == "rule_builder"
    assert (pdir / "work" / "nodes.json").stat().st_mtime == parsed_at, "the parse is cached; only the model layers ran again"
    versions = client.get(f"/projects/{pid}/ruleset/versions").json()
    assert [(v["version"], v["status"]) for v in versions] == [(1, "draft")]
