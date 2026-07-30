"""Backend API tests — fully offline: rubric and bid extractions are injected through
the API (the human-correction path), so evaluation runs without any LLM."""
import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from test.conftest import FIXTURES


def make_client(tmp_path, monkeypatch, api_key: str | None = None):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if api_key:
        monkeypatch.setenv("API_KEY", api_key)
    else:
        monkeypatch.delenv("API_KEY", raising=False)
    import backend.api as api
    importlib.reload(api)  # module reads DATA_DIR / API_KEY at import time
    return TestClient(api.app)


def wait_done(client, pid, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/projects/{pid}/status").json()
        if status["state"] in ("done", "error"):
            return status
        time.sleep(0.05)
    pytest.fail("background job did not finish in time")


def test_full_project_flow_offline(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    assert client.get("/health").json()["ok"] is True

    pid = client.post("/projects", json={"name": "Demo Tender 001"}).json()["id"]
    assert pid in [p["id"] for p in client.get("/projects").json()]

    # Human checkpoint: PUT a (fixture) rubric and read it back.
    rubric = json.loads((FIXTURES / "rubric.json").read_text())
    assert client.put(f"/projects/{pid}/rubric", json=rubric).status_code == 200
    assert client.get(f"/projects/{pid}/rubric").json()["tender_ref"] == "DEMO0012026"

    # Evaluation without bids must be rejected.
    assert client.post(f"/projects/{pid}/evaluate").status_code == 400

    # Inject the four fixture extractions (correction path — no LLM involved).
    for path in sorted((FIXTURES / "bids").glob("*.json")):
        ext = json.loads(path.read_text())
        r = client.put(f"/projects/{pid}/bids/{ext['tenderer']}/extraction", json=ext)
        assert r.status_code == 200

    assert client.post(f"/projects/{pid}/evaluate").json()["started"] is True
    status = wait_done(client, pid)
    assert status["state"] == "done", status

    ev = client.get(f"/projects/{pid}/evaluation").json()
    assert ev["recommended"] == "Bidder B"
    assert len(ev["stage1"]) == 4

    reports = client.get(f"/projects/{pid}/reports").json()
    assert sorted(reports) == ["evaluation_record.docx", "price_summary.docx", "summary_list.docx"]
    docx = client.get(f"/projects/{pid}/reports/price_summary.docx")
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"  # docx is a zip container

    # Project summary reflects the finished state.
    proj = client.get(f"/projects/{pid}").json()
    assert proj["has_rubric"] and proj["has_evaluation"]
    assert len(proj["extracted"]) == 4


def test_unknown_project_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.get("/projects/nope/status").status_code == 404


def test_api_key_enforced(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    assert client.get("/health").status_code == 200  # health stays open
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "sesame"}).status_code == 200
