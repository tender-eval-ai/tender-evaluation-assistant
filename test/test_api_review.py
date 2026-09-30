# ruff: noqa: F811  (the `api` fixture is imported from test_api_checks and named in each test)
"""The S4 review routes on Postgres with a real worker and the FakeLLM: a correction keeps the
model's value and re-decides at once, a review is confirmed only when nothing needs review and
is withdrawn by a later correction, an evaluation re-decides every result against a rule-set
version as a job, a finished job cannot be retried. Opt-in (-m postgres)."""
from __future__ import annotations

import copy
import os
import subprocess
import sys

import psycopg
import pytest
from psycopg.types.json import Json

from test.test_api_checks import CHENYU, NASI, _wait_done, api, draft_body  # noqa: F401  (the fixture)

pytestmark = pytest.mark.postgres


@pytest.fixture
def worker():
    proc = subprocess.Popen([sys.executable, "-m", "app.jobs.worker", "--name", "review-test", "--pipelines",
                             "app.checks.vendor_check,app.jobs.evaluate_job", "--no-migrate"], env=os.environ.copy())
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)                # SIGTERM drains a running job; a slow runner may need longer
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _checked(client, pid, tenderers: list[str]) -> dict:
    assert client.put(f"/projects/{pid}/ruleset/draft", json=draft_body(), headers=CHENYU).status_code == 200
    assert client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).status_code == 200
    job_ids = client.post(f"/projects/{pid}/checks", json={"tenderers": tenderers}).json()["job_ids"]
    for t, job_id in job_ids.items():
        assert _wait_done(client, pid, job_id)["state"] == "done", t
    return job_ids


def _result(client, pid, tenderer) -> dict:
    return client.get(f"/projects/{pid}/bids/{tenderer}/results").json()


def test_a_correction_keeps_the_models_value_and_redecides_at_once(api, worker):
    client, pid = api
    _checked(client, pid, ["Tenderer_C"])                          # no certificate: every field blank, disqualified
    assert _result(client, pid, "Tenderer_C")["verdicts"]["l"]["outcome"] == "disqualified"
    url = f"/projects/{pid}/bids/Tenderer_C/fields/l"

    r = client.patch(f"{url}/document", json={"present": True, "reason": "found it stapled to the offer"}, headers=CHENYU)
    assert r.status_code == 200, r.text
    doc = r.json()["fields"]["l"]["document"]
    assert doc["value"] == "present" and doc["correction"] == {"value": "present", "by": "chenyu", "reason": "found it stapled to the offer", "model_value": None}
    assert r.json()["verdicts"]["l"]["outcome"] == "needs_review", \
        "the model read no signature on a form that is there: a reviewer confirms before it disqualifies"

    for field, value in [("signature", "authorised signatory of Tenderer C"), ("tenderer_name", "Tenderer C"), ("date", "1 September 2026")]:
        r = client.patch(f"{url}/{field}", json={"value": value, "reason": "read from the stapled copy"}, headers=NASI)
        assert r.status_code == 200, r.text
    res = r.json()
    assert res["verdicts"]["l"]["outcome"] == "pass" and res["fields"]["l"]["date"]["correction"]["by"] == "nasi"
    assert res["fields"]["l"]["signature"]["model_value"] is None and res["fields"]["l"]["signature"]["value"].endswith("Tenderer C")

    r = client.patch(f"{url}/date", json={"page": 10, "reason": "the date is on page 10"}, headers=NASI)
    assert r.status_code == 200 and r.json()["fields"]["l"]["date"]["page"]["page"] == 10

    assert client.patch(f"{url}/nothing", json={"value": 1, "reason": "x"}, headers=NASI).status_code == 404
    assert client.patch(f"/projects/{pid}/bids/Tenderer_C/fields/q/document", json={"value": 1, "reason": "x"}, headers=NASI).status_code == 404
    r = client.patch(f"{url}/date", json={"reason": "nothing given"}, headers=NASI)
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"
    assert client.patch(f"/projects/{pid}/bids/Tenderer_B/fields/l/date", json={"value": 1, "reason": "x"}, headers=NASI).status_code == 404
    events = [e for e in client.get(f"/projects/{pid}/events").json()["items"] if e["kind"] == "result.corrected"]
    assert len(events) == 5 and events[0]["subject"] == "Tenderer_C:l.document" and events[0]["reason"] == "found it stapled to the offer"


def test_a_review_is_confirmed_only_when_nothing_needs_review_and_a_correction_withdraws_it(api, worker):
    client, pid = api
    job_ids = _checked(client, pid, ["Tenderer_A"])
    r = client.post(f"/projects/{pid}/bids/Tenderer_A/review/confirm", headers=NASI)
    assert r.status_code == 200 and r.json()["review_confirmed_by"] == "nasi"
    assert _result(client, pid, "Tenderer_A")["review_confirmed_by"] == "nasi"

    r = client.patch(f"/projects/{pid}/bids/Tenderer_A/fields/l/date", json={"value": "13 August 2026", "reason": "re-read"}, headers=CHENYU)
    assert r.status_code == 200 and r.json()["review_confirmed_by"] is None, "a correction withdraws the confirmation"

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:          # a field the engine flagged
        verdict = c.execute("select verdict from results where run_id=%s", (job_ids["Tenderer_A"],)).fetchone()[0]
        verdict["items"]["l"]["fields"][0]["status"] = "needs_review"
        c.execute("update results set verdict=%s where run_id=%s", (Json(verdict), job_ids["Tenderer_A"]))
    r = client.post(f"/projects/{pid}/bids/Tenderer_A/review/confirm", headers=NASI)
    assert r.status_code == 409 and r.json()["error"]["details"]["fields"] == [verdict["items"]["l"]["fields"][0]["field_id"]]
    assert client.post(f"/projects/{pid}/bids/Tenderer_B/review/confirm", headers=NASI).status_code == 404
    kinds = [e["kind"] for e in client.get(f"/projects/{pid}/events").json()["items"]]
    assert "review.confirmed" in kinds


def test_an_evaluation_redecides_every_result_against_a_confirmed_version(api, worker):
    client, pid = api
    _checked(client, pid, ["Tenderer_A", "Tenderer_C"])
    assert _result(client, pid, "Tenderer_C")["verdicts"]["l"]["outcome"] == "disqualified"

    r = client.post(f"/projects/{pid}/evaluate", headers=CHENYU)                    # against v1: nothing changes
    assert r.status_code == 202, r.text
    job = _wait_done(client, pid, r.json()["job_id"])
    assert job["state"] == "done" and job["kind"] == "evaluate" and job["tenderer"] is None
    assert _result(client, pid, "Tenderer_C")["ruleset_version"] == 1

    v2 = copy.deepcopy(draft_body())                                                 # v2: a missing certificate needs review, not disqualification
    for rule in v2["items"][0]["rules"]:
        rule["outcomes"]["blank"] = {"status": "needs_review", "note": "ask for the certificate"}
    assert client.put(f"/projects/{pid}/ruleset/draft", json=v2, headers=CHENYU).status_code == 200
    assert client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).json()["version"] == 2
    assert client.post(f"/projects/{pid}/evaluate", json={"version": 9}, headers=CHENYU).status_code == 404

    r = client.post(f"/projects/{pid}/evaluate", json={}, headers=CHENYU)
    assert r.status_code == 202
    assert _wait_done(client, pid, r.json()["job_id"])["state"] == "done"
    c = _result(client, pid, "Tenderer_C")
    assert c["ruleset_version"] == 2 and c["verdicts"]["l"]["outcome"] == "needs_review"
    assert _result(client, pid, "Tenderer_A")["ruleset_version"] == 2 and _result(client, pid, "Tenderer_A")["verdicts"]["l"]["outcome"] == "pass"
    assert client.get(f"/projects/{pid}/bids/Tenderer_C/results", params={"version": 1}).status_code == 404
    events = client.get(f"/projects/{pid}/events").json()["items"]
    assert [e["subject"] for e in events if e["kind"] == "result.reevaluated"] == ["Tenderer_C"]
    assert [e["kind"] for e in events].count("evaluate.started") == 2


def test_a_finished_job_is_not_retried_and_an_unknown_one_is_404(api, worker):
    client, pid = api
    job_ids = _checked(client, pid, ["Tenderer_A"])
    r = client.post(f"/projects/{pid}/jobs/{job_ids['Tenderer_A']}/retry", headers=CHENYU)
    assert r.status_code == 409 and "done" in r.json()["error"]["message"]
    assert client.post(f"/projects/{pid}/jobs/nope/retry", headers=CHENYU).status_code == 404
