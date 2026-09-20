"""The S2 conventions that need no database: the error envelope, the project's data
class, the queue's absence reported as such, signed page-image links."""
import time

from test.checks.conftest import CASE
from test.test_api import make_client


def test_errors_use_the_envelope_and_keep_detail_for_the_old_ui(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    r = client.get("/projects/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found" and body["detail"] == body["error"]["message"] and body["error"]["details"] == {}
    r = client.post("/projects", json={"nam": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert r.json()["error"]["details"]["errors"][0]["loc"] == ["body", "name"]


def test_projects_carry_a_data_class_derived_from_synthetic_when_absent(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.post("/projects", json={"name": "a"}).json()["data_class"] == "confidential"
    assert client.post("/projects", json={"name": "b", "synthetic": True}).json()["data_class"] == "synthetic"
    p = client.post("/projects", json={"name": "c", "data_class": "redacted_sample"}).json()
    assert p["data_class"] == "redacted_sample" and p["synthetic"] is False
    assert client.get(f"/projects/{p['id']}").json()["data_class"] == "redacted_sample"
    assert client.post("/projects", json={"name": "d", "data_class": "public"}).status_code == 422


def test_queue_routes_say_the_queue_is_missing_without_postgres(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "q"}).json()["id"]
    for method, path in [("post", f"/projects/{pid}/checks"), ("get", f"/projects/{pid}/jobs"),
                         ("get", f"/projects/{pid}/ruleset"), ("get", f"/projects/{pid}/events")]:
        r = getattr(client, method)(path)
        assert r.status_code == 503 and r.json()["error"]["code"] == "queue_unavailable", (path, r.json())


def _upload_offer(client, pid, tenderer="Tenderer_B"):
    pdf = (CASE / "bids" / tenderer / "offer.pdf").read_bytes()
    assert client.post(f"/projects/{pid}/bids/{tenderer}", files=[("files", ("offer.pdf", pdf, "application/pdf"))],
                       headers={"X-API-Key": "sesame"}).status_code == 200


def test_documents_and_pages_are_listed_and_images_open_by_signed_link(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    key = {"X-API-Key": "sesame"}
    pid = client.post("/projects", json={"name": "v", "synthetic": True}, headers=key).json()["id"]
    _upload_offer(client, pid)
    docs = client.get(f"/projects/{pid}/documents", headers=key).json()
    assert len(docs) == 1 and docs[0]["kind"] == "bid" and docs[0]["tenderer"] == "Tenderer_B" and docs[0]["pages"] == 16
    assert docs[0]["data_class"] == "synthetic"
    doc_id = docs[0]["doc_id"]
    pages = client.get(f"/projects/{pid}/documents/{doc_id}/pages", headers=key).json()
    assert len(pages) == 16 and pages[12]["page"] == 13 and pages[12]["has_text"] is False and pages[12]["label"] is None
    url = pages[12]["image_url"]
    assert "sig=" in url and "exp=" in url and "key=" not in url
    r = client.get(url)                                       # no header: the signature opens it
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get(url.replace("sig=", "sig=0")).status_code == 403
    expired = url.replace(f"exp={url.split('exp=')[1].split('&')[0]}", f"exp={int(time.time()) - 5}")
    assert client.get(expired).status_code == 403
    assert client.get(f"/projects/{pid}/documents/{doc_id}/pages/13/image", headers=key).status_code == 200
    assert client.get(f"/projects/{pid}/documents/{doc_id}/pages/13/image").status_code == 403
    assert client.get(f"/projects/{pid}/documents/{doc_id}/pages/99/image", headers=key).status_code == 404
    assert client.get(f"/projects/{pid}/documents/nope/pages", headers=key).status_code == 404
