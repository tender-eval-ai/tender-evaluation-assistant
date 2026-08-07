"""Backend API tests — fully offline: rubric and bid extractions are injected through
the API (the human-correction path), so evaluation runs without any LLM."""
import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from test.conftest import FIXTURES


def make_client(tmp_path, monkeypatch, api_key: str | None = None):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
    if api_key:
        monkeypatch.setenv("API_KEY", api_key)
    else:
        monkeypatch.delenv("API_KEY", raising=False)
    import backend.api as api
    importlib.reload(api)  # module reads DATA_DIR / INBOX_DIR / API_KEY at import time
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


def test_inbox_import_and_delete(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    # A case folder in the inbox following the tender/ + bids/<tenderer>/ convention.
    case = tmp_path / "inbox" / "case1"
    (case / "tender").mkdir(parents=True)
    (case / "tender" / "terms.pdf").write_bytes(b"%PDF-1.4 stub")
    for bidder in ("Alpha", "Beta"):
        d = case / "bids" / bidder
        d.mkdir(parents=True)
        (d / "offer.pdf").write_bytes(b"%PDF-1.4 stub")
    (case / "bids" / "Gamma.pdf").write_bytes(b"%PDF-1.4 stub")  # loose PDF = one bidder

    inbox = client.get("/inbox").json()
    assert [e["name"] for e in inbox] == ["case1"]
    assert inbox[0]["tender_pdfs"] == 1 and inbox[0]["bidders"] == ["Alpha", "Beta"]

    pid = client.post("/projects", json={"name": "import test"}).json()["id"]
    result = client.post(f"/projects/{pid}/import", json={"path": "case1"}).json()
    assert result == {"tender_pdfs": 1, "bidders": {"Alpha": 1, "Beta": 1, "Gamma": 1}}
    proj = client.get(f"/projects/{pid}").json()
    assert proj["tender_files"] == ["terms.pdf"]
    assert proj["bidders"] == ["Alpha", "Beta", "Gamma"]

    # Path traversal is rejected; unknown folder is a 404.
    assert client.post(f"/projects/{pid}/import", json={"path": "../data"}).status_code == 404
    assert client.post(f"/projects/{pid}/import", json={"path": "nope"}).status_code == 404

    # Delete removes the project entirely.
    assert client.delete(f"/projects/{pid}").json() == {"deleted": pid}
    assert client.get(f"/projects/{pid}").status_code == 404
    assert client.get("/projects").json() == []


def test_extraction_review_endpoints_and_page_image(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "review"}).json()["id"]
    rubric = json.loads((FIXTURES / "rubric.json").read_text())
    client.put(f"/projects/{pid}/rubric", json=rubric)

    # GET extraction: 404 before, roundtrip after PUT.
    assert client.get(f"/projects/{pid}/bids/Alpha/extraction").status_code == 404
    ext = json.loads((FIXTURES / "bids" / "bidder_a.json").read_text())
    client.put(f"/projects/{pid}/bids/Alpha/extraction", json=ext)
    assert client.get(f"/projects/{pid}/bids/Alpha/extraction").json()["tenderer"] == "Alpha"

    # Extract-only job with everything already extracted completes without any LLM.
    assert client.post(f"/projects/{pid}/extract").status_code == 200
    status = wait_done(client, pid)
    assert status["state"] == "done" and "review" in status["detail"]

    # Evidence page image rendered from a real uploaded PDF.
    from tools.pdfgen import make_text_pdf
    pdf = tmp_path / "offer.pdf"
    make_text_pdf(pdf, "Offer of Alpha. Price Schedule Part A: unit price HK$ 1.00.")
    client.post(f"/projects/{pid}/bids/Alpha",
                files=[("files", ("offer.pdf", pdf.read_bytes(), "application/pdf"))])
    img = client.get(f"/projects/{pid}/bids/Alpha/page", params={"page": 1})
    assert img.status_code == 200
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert img.headers["content-type"] == "image/png"
    assert client.get(f"/projects/{pid}/bids/Alpha/page",
                      params={"page": 99}).status_code == 400
    assert client.get(f"/projects/{pid}/bids/Nobody/page").status_code == 404


def test_api_key_enforced(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    assert client.get("/health").status_code == 200  # health stays open
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "sesame"}).status_code == 200
