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
    monkeypatch.setenv("GITHUB_MODELS_BASE_URL", "http://localhost:11434/v1")  # keyless client
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
        if status["state"] in ("done", "error", "waiting"):
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

    # With every bid already extracted the orchestrated run needs no LLM at all: it
    # goes straight to the review checkpoint and pauses there.
    assert client.post(f"/projects/{pid}/run").status_code == 200
    status = wait_done(client, pid)
    assert status["state"] == "waiting" and "review" in status["detail"]

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


def test_tender_page_image(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "tp"}).json()["id"]
    assert client.get(f"/projects/{pid}/tender/page").status_code == 404

    from tools.pdfgen import make_text_pdf
    pdf = tmp_path / "terms.pdf"
    make_text_pdf(pdf, "Terms of Tender. Delivery within 45 days is essential.")
    client.post(f"/projects/{pid}/tender",
                files=[("files", ("terms.pdf", pdf.read_bytes(), "application/pdf"))])
    img = client.get(f"/projects/{pid}/tender/page", params={"page": 1})
    assert img.status_code == 200
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/projects/{pid}/tender/page", params={"page": 99}).status_code == 400

    # Highlighting the quoted evidence visibly changes the render; a quote that is
    # nowhere on the page falls back to the clean render.
    marked = client.get(f"/projects/{pid}/tender/page",
                        params={"page": 1, "highlight": "Delivery within 45 days"})
    assert marked.status_code == 200 and marked.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert marked.content != img.content
    unfound = client.get(f"/projects/{pid}/tender/page",
                         params={"page": 1, "highlight": "totally absent wording zz"})
    assert unfound.content == img.content


def test_page_image_accepts_query_key(tmp_path, monkeypatch):
    """Evidence links open in a browser tab (no headers): page endpoints accept
    ?key=…, but the data API must still require the header."""
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    h = {"X-API-Key": "sesame"}
    pid = client.post("/projects", json={"name": "k"}, headers=h).json()["id"]
    from tools.pdfgen import make_text_pdf
    pdf = tmp_path / "t.pdf"
    make_text_pdf(pdf, "Terms of Tender apply here.")
    client.post(f"/projects/{pid}/tender", headers=h,
                files=[("files", ("t.pdf", pdf.read_bytes(), "application/pdf"))])
    assert client.get(f"/projects/{pid}/tender/page").status_code == 401
    assert client.get(f"/projects/{pid}/tender/page",
                      params={"key": "wrong"}).status_code == 401
    assert client.get(f"/projects/{pid}/tender/page",
                      params={"key": "sesame"}).status_code == 200
    assert client.get("/projects", params={"key": "sesame"}).status_code == 401


def test_api_key_enforced(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    assert client.get("/health").status_code == 200  # health stays open
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "sesame"}).status_code == 200


def stub_pipeline(monkeypatch) -> dict:
    """Replace the LLM-backed graph nodes with fixtures: the orchestrated run then
    exercises checkpoints, pauses and edits without any model. Returns the bids."""
    monkeypatch.setenv("VERIFY_FINDINGS", "0")
    monkeypatch.setenv("AGENT_SEARCH", "0")
    import app.graph as graph_mod
    from app.schemas import BidExtraction, Rubric
    fixture_rubric = Rubric.model_validate_json((FIXTURES / "rubric.json").read_text())
    fixture_bids = {e.tenderer: e for e in (BidExtraction.model_validate_json(p.read_text())
                                            for p in sorted((FIXTURES / "bids").glob("*.json")))}
    monkeypatch.setattr(graph_mod, "load_folder", lambda *a, **k: [])
    monkeypatch.setattr(graph_mod, "load_pdf", lambda *a, **k: None)
    monkeypatch.setattr(graph_mod, "derive_rubric",
                        lambda docs, cfg, llm: fixture_rubric.model_copy(deep=True))
    monkeypatch.setattr(graph_mod, "extract_bid",
                        lambda name, docs, rubric, cfg, llm: fixture_bids[name].model_copy(deep=True))
    monkeypatch.setattr("app.llm.LLM", lambda cfg: object())
    return fixture_bids


def make_project_with_docs(client, fixture_bids, name="graph") -> str:
    pid = client.post("/projects", json={"name": name}).json()["id"]
    stub = b"%PDF-1.4 stub"
    client.post(f"/projects/{pid}/tender", files=[("files", ("terms.pdf", stub, "application/pdf"))])
    for bidder in fixture_bids:
        client.post(f"/projects/{pid}/bids/{bidder}", files=[("files", ("offer.pdf", stub, "application/pdf"))])
    return pid


def test_orchestrated_run_pauses_at_both_checkpoints_and_honours_edits(tmp_path, monkeypatch):
    """/run -> paused at rubric -> PUT edit -> /resume -> paused at review -> PUT
    correction -> /resume -> done, with the edits visible in the evaluation."""
    fixture_bids = stub_pipeline(monkeypatch)
    client = make_client(tmp_path, monkeypatch)

    pid = client.post("/projects", json={"name": "graph"}).json()["id"]
    assert client.post(f"/projects/{pid}/run").status_code == 400   # no tender docs yet
    stub = b"%PDF-1.4 stub"
    client.post(f"/projects/{pid}/tender", files=[("files", ("terms.pdf", stub, "application/pdf"))])
    for name in fixture_bids:
        client.post(f"/projects/{pid}/bids/{name}", files=[("files", ("offer.pdf", stub, "application/pdf"))])

    assert client.post(f"/projects/{pid}/run").json()["started"] is True
    status = wait_done(client, pid)
    assert status["state"] == "waiting" and "rubric" in status["detail"]
    assert client.get(f"/projects/{pid}/graph").json()["pending"] == "rubric"
    assert client.post(f"/projects/{pid}/run").status_code == 409         # paused: must resume

    rubric = client.get(f"/projects/{pid}/rubric").json()
    rubric["subject"] = "EDITED IN THE UI"
    client.put(f"/projects/{pid}/rubric", json=rubric)
    assert client.post(f"/projects/{pid}/resume", json={}).json()["resumed"] == "rubric"
    status = wait_done(client, pid)
    assert status["state"] == "waiting" and "extractions" in status["detail"]
    assert client.get(f"/projects/{pid}/graph").json()["pending"] == "review"
    assert len(client.get(f"/projects/{pid}").json()["extracted"]) == len(fixture_bids)

    fixed = client.get(f"/projects/{pid}/bids/Bidder A/extraction").json()
    fixed["documents"][0]["present"] = False
    client.put(f"/projects/{pid}/bids/Bidder A/extraction", json=fixed)
    assert client.post(f"/projects/{pid}/resume", json={}).json()["resumed"] == "review"
    status = wait_done(client, pid)
    assert status["state"] == "done", status

    ev = client.get(f"/projects/{pid}/evaluation").json()
    assert ev["rubric"]["subject"] == "EDITED IN THE UI"
    assert next(r for r in ev["stage1"] if r["tenderer"] == "Bidder A")["passed"] is False
    g = client.get(f"/projects/{pid}/graph").json()
    assert g["pending"] is None and g["corrected"] == ["Bidder A"]
    assert client.post(f"/projects/{pid}/resume", json={}).status_code == 409
    assert client.get(f"/projects/{pid}/bids/Bidder A/agent").status_code == 404
    assert sorted(client.get(f"/projects/{pid}/reports").json()) == [
        "evaluation_record.docx", "price_summary.docx", "summary_list.docx"]


def test_pause_state_survives_losing_the_scratch_disk(tmp_path, monkeypatch):
    """Cloud Run mode: the graph's SQLite DB is worked on under GRAPH_DB_SCRATCH_DIR
    (instance-local) and copied to the project's work/ dir (the bucket) after every
    job. Wiping the scratch dir between two human checkpoints — an instance restart
    — must lose nothing: the next call restores the working copy from work/."""
    import shutil
    fixture_bids = stub_pipeline(monkeypatch)
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("GRAPH_DB_SCRATCH_DIR", str(scratch))
    client = make_client(tmp_path, monkeypatch)
    pid = make_project_with_docs(client, fixture_bids)
    canonical = tmp_path / "data" / "projects" / pid / "work" / "graph.sqlite"

    assert client.post(f"/projects/{pid}/run").json()["started"] is True
    assert wait_done(client, pid)["state"] == "waiting"
    assert canonical.is_file() and (scratch / pid / "graph.sqlite").is_file()
    assert not list(canonical.parent.glob(".graph.sqlite.*")), "temp copy left behind"

    shutil.rmtree(scratch)                                  # "instance restarted"
    assert client.get(f"/projects/{pid}/graph").json()["pending"] == "rubric"
    assert client.post(f"/projects/{pid}/resume", json={}).json()["resumed"] == "rubric"
    assert client.get(f"/projects/{pid}/graph").json()["pending"] in ("rubric", "review", None)
    assert wait_done(client, pid)["state"] == "waiting"

    shutil.rmtree(scratch)                                  # and again
    assert client.post(f"/projects/{pid}/resume", json={}).json()["resumed"] == "review"
    assert wait_done(client, pid)["state"] == "done"
    assert client.get(f"/projects/{pid}/graph").json()["pending"] is None
    assert sorted(client.get(f"/projects/{pid}/reports").json()) == [
        "evaluation_record.docx", "price_summary.docx", "summary_list.docx"]

    # Deleting the project removes its scratch copy too.
    client.delete(f"/projects/{pid}")
    assert not (scratch / pid).exists()


def test_project_synthetic_flag(tmp_path, monkeypatch):
    # The flag the MCP server keys its confidentiality guard on: explicit at creation,
    # off by default, visible on the project.
    client = make_client(tmp_path, monkeypatch)
    real = client.post("/projects", json={"name": "Real Tender"}).json()
    demo = client.post("/projects", json={"name": "Demo Case", "synthetic": True}).json()
    assert real["synthetic"] is False and demo["synthetic"] is True
    assert client.get(f"/projects/{real['id']}").json()["synthetic"] is False
    assert client.get(f"/projects/{demo['id']}").json()["synthetic"] is True
