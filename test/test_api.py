"""The API's project, upload, inbox, key and health routes, offline (no Postgres, no model).
The rule-set, check and review routes have their own files (test_api_*.py)."""
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEMPLATES = Path(__file__).resolve().parent / "data" / "templates"


def make_client(tmp_path, monkeypatch, api_key: str | None = None):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("GITHUB_MODELS_BASE_URL", "http://localhost:11434/v1")  # keyless client
    # A developer's .env may point the models at a cloud host; the API's tests run on the
    # local defaults, as CI does, so the data-class checks see the same endpoints. Set, not
    # deleted: reloading the API re-reads .env, which only fills variables that are unset.
    from app.config import DEFAULT_TEXT_MODEL, DEFAULT_VISION_MODEL
    monkeypatch.setenv("TEXT_MODEL", DEFAULT_TEXT_MODEL)
    monkeypatch.setenv("VISION_MODEL", DEFAULT_VISION_MODEL)
    monkeypatch.setenv("TEXT_MODEL_FALLBACKS", "")
    monkeypatch.setenv("VISION_MODEL_FALLBACKS", "")
    if api_key:
        monkeypatch.setenv("API_KEY", api_key)
    else:
        monkeypatch.delenv("API_KEY", raising=False)
    import backend.api as api
    importlib.reload(api)  # module reads DATA_DIR / INBOX_DIR / API_KEY at import time
    return TestClient(api.app)


def test_unknown_project_404(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.get("/projects/nope").status_code == 404


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


def test_api_key_enforced(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    assert client.get("/health").status_code == 200  # health stays open
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/projects", headers={"X-API-Key": "sesame"}).status_code == 200


def test_health_reports_the_template_library_without_naming_a_path(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    body = client.get("/health").json()
    assert body["templates"] == 2 and body["templates_valid"] is True
    library = tmp_path / "templates"
    library.mkdir()
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(library))
    assert client.get("/health").json()["templates"] == 0, "an empty library, reported rather than hidden"
    (library / "broken.json").write_text("{")
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["templates"] == 0 and r.json()["templates_valid"] is False
    assert str(tmp_path) not in r.text and "broken.json" not in r.text, "an open route names no path and no file"


def test_project_synthetic_flag(tmp_path, monkeypatch):
    # Kept for older clients beside data_class: explicit at creation, off by default.
    client = make_client(tmp_path, monkeypatch)
    real = client.post("/projects", json={"name": "Real Tender"}).json()
    demo = client.post("/projects", json={"name": "Demo Case", "synthetic": True}).json()
    assert real["synthetic"] is False and demo["synthetic"] is True
    assert client.get(f"/projects/{real['id']}").json()["synthetic"] is False
    assert client.get(f"/projects/{demo['id']}").json()["synthetic"] is True


def test_project_id_is_validated_before_touching_the_filesystem(tmp_path, monkeypatch):
    """'..' as a project id resolves to DATA_DIR itself — and DELETE calls rmtree on
    the resolved directory. Ids must match the generated <slug>-<hex> shape."""
    from fastapi import HTTPException
    client = make_client(tmp_path, monkeypatch)
    import backend.api as api
    keep = client.post("/projects", json={"name": "keep me"}).json()["id"]
    for bad in ("..", ".", "../keep", "keep/../..", "A B", "", "%2e%2e"):
        with pytest.raises(HTTPException) as err:
            api._project_dir(bad)
        assert err.value.status_code == 404
    assert client.delete("/projects/%2e%2e").status_code == 404
    assert client.delete("/projects/..").status_code in (404, 405)
    assert (tmp_path / "data" / "projects" / keep).is_dir()
    assert client.delete(f"/projects/{keep}").json() == {"deleted": keep}


def test_node_table_needs_the_key(tmp_path, monkeypatch):
    """The parsed clause tree is document content: behind X-API-Key like every other
    document route (it sat on the unkeyed router with the page image until ST-5)."""
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    h = {"X-API-Key": "sesame"}
    pid = client.post("/projects", json={"name": "n"}, headers=h).json()["id"]
    from tools.pdfgen import make_text_pdf
    pdf = tmp_path / "t.pdf"
    make_text_pdf(pdf, "Terms of Tender apply here.")
    client.post(f"/projects/{pid}/tender", headers=h, files=[("files", ("t.pdf", pdf.read_bytes(), "application/pdf"))])
    doc = client.get(f"/projects/{pid}/documents", headers=h).json()[0]["doc_id"]
    assert client.get(f"/projects/{pid}/documents/{doc}/nodes").status_code == 401
    assert client.get(f"/projects/{pid}/documents/{doc}/nodes", headers=h).status_code == 409, "keyed: not parsed yet"
