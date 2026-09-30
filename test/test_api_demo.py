"""A hosted demo (#132): GET /settings, synthetic projects only, no uploads, and the case cards
GET /inbox shows. The Azure deployment sets HOSTED_DEMO=1; a local stack leaves it unset."""
import json

import pytest

from backend import deps
from test.test_api import make_client

SOURCE = "https://github.com/tender-eval-ai/tender-evaluation-assistant"


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setenv("HOSTED_DEMO", "1")
    monkeypatch.setenv("SOURCE_URL", SOURCE)
    yield make_client(tmp_path, monkeypatch)
    # Later tests that don't reload the API must not inherit a hosted demo.
    monkeypatch.delenv("HOSTED_DEMO")
    monkeypatch.delenv("SOURCE_URL")
    deps.configure()


def _case(inbox, name="small", card: dict | str | None = None):
    case = inbox / name
    (case / "tender").mkdir(parents=True)
    (case / "tender" / "terms.pdf").write_bytes(b"%PDF-1.4 stub")
    (case / "bids" / "Tenderer_A").mkdir(parents=True)
    (case / "bids" / "Tenderer_A" / "offer.pdf").write_bytes(b"%PDF-1.4 stub")
    if card is not None:
        (case / "case.json").write_text(card if isinstance(card, str) else json.dumps(card))
    return case


def test_a_local_stack_is_not_a_hosted_demo(tmp_path, monkeypatch):
    monkeypatch.delenv("HOSTED_DEMO", raising=False)
    monkeypatch.delenv("SOURCE_URL", raising=False)
    client = make_client(tmp_path, monkeypatch)
    assert client.get("/settings").json() == {"hosted_demo": False, "uploads": True, "source_url": None,
                                              "data_classes": ["synthetic", "redacted_sample", "confidential"]}
    created = client.post("/projects", json={"name": "real", "data_class": "confidential"})
    assert created.status_code == 200 and "status" not in created.json(), "status went at S5 (#129)"


def test_a_hosted_demo_says_so(hosted):
    assert hosted.get("/settings").json() == {"hosted_demo": True, "uploads": False, "source_url": SOURCE,
                                              "data_classes": ["synthetic"]}


@pytest.mark.parametrize("body", [{"name": "x", "data_class": "confidential"},
                                  {"name": "x", "data_class": "redacted_sample"},
                                  {"name": "x"}])                      # no class and not synthetic: confidential
def test_a_hosted_demo_creates_synthetic_projects_only(hosted, body):
    r = hosted.post("/projects", json=body)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "data_class_forbidden"
    assert r.json()["error"]["details"] == {"source_url": SOURCE}
    assert hosted.get("/projects").json() == [], "nothing made"


def test_a_hosted_demo_takes_no_upload_but_imports_a_case(hosted, tmp_path):
    pid = hosted.post("/projects", json={"name": "try 1", "data_class": "synthetic"}).json()["id"]
    for path in (f"/projects/{pid}/tender", f"/projects/{pid}/bids/Tenderer_A"):
        r = hosted.post(path, files=[("files", ("offer.pdf", b"%PDF-1.4 stub", "application/pdf"))])
        assert r.status_code == 403 and r.json()["error"]["code"] == "uploads_disabled", path
        assert r.json()["error"]["details"] == {"source_url": SOURCE}
    assert not any((tmp_path / "data" / "projects" / pid).rglob("*.pdf")), "nothing written"

    _case(tmp_path / "inbox")
    assert hosted.post(f"/projects/{pid}/import", json={"path": "small"}).json() == {"tender_pdfs": 1,
                                                                                     "bidders": {"Tenderer_A": 1}}


def test_the_inbox_shows_each_case_card_and_ignores_a_bad_one(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    _case(tmp_path / "inbox", "a_small", {"title": "Small tender", "summary": "17 documents",
                                          "look_for": ["Tenderer C leaves out the certificate."]})
    _case(tmp_path / "inbox", "b_broken", "{not json")
    _case(tmp_path / "inbox", "c_wrong_types", {"title": 3, "summary": "ok", "look_for": "not a list"})
    _case(tmp_path / "inbox", "d_none")
    cards = {c["name"]: (c["title"], c["summary"], c["look_for"]) for c in client.get("/inbox").json()}
    assert cards == {"a_small": ("Small tender", "17 documents", ["Tenderer C leaves out the certificate."]),
                     "b_broken": (None, None, None),
                     "c_wrong_types": (None, "ok", None),
                     "d_none": (None, None, None)}
