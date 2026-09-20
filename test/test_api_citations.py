"""Page citations a reviewer can see highlighted: a value found on the page's text layer
comes back with its quote, box and a signed highlighted image link; a scanned page
keeps the plain citation. Documents carry the project path a rule-set Citation names.
Synthetic case only; no Postgres (the result is built from a stored-result stand-in)."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from app.checks.extract_item_l import PREFIX
from test.checks.conftest import CASE
from test.test_api import make_client
from test.test_api_errors import _upload_offer

KEY = {"X-API-Key": "sesame"}


def _project(tmp_path, monkeypatch, *tenderers):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = make_client(tmp_path, monkeypatch, api_key="sesame")
    pid = client.post("/projects", json={"name": "cite", "synthetic": True}, headers=KEY).json()["id"]
    for t in tenderers:
        _upload_offer(client, pid, t)
    return client, pid, tmp_path / "data" / "projects" / pid


def _result(tenderer: str, page: int) -> tuple[dict, SimpleNamespace]:
    """Item (l) as the FakeLLM reads it: title and signatory are on Tenderer_A's text
    layer, the date it reports (12 August) is not (the page says 14 August)."""
    ref = {"doc": "offer.pdf", "page": page, "seq": page}
    values = {"document": "Non-collusive Tendering Certificate", "tenderer_name": tenderer.replace("_", " "),
              "signature": "authorised signatory", "date": "12 August 2026"}
    fields = {}
    for name, value in values.items():
        fields[f"{PREFIX}.{name}"] = value
        fields[f"{PREFIX}.{name}_redacted"] = False
        fields[f"{PREFIX}.{name}_confidence"] = 0.92
        fields[f"{PREFIX}.{name}_page"] = ref
    verdict = {"item": "l", "part": "A", "outcome": "pass", "worst": "pass", "rule_ids": ["l-1"], "reasons": [],
               "fields": [{"field_id": f"{PREFIX}.{n}", "status": "pass", "value": v, "page": ref} for n, v in values.items()]}
    run = {"tenderer": tenderer, "run_id": "r1"}
    return run, SimpleNamespace(fields=fields, corrections={}, verdict=verdict, ruleset_version=1)


def _bid_result(pid, pdir, tenderer, page):
    from backend.routes.checks import _bid_result
    run, result = _result(tenderer, page)
    return _bid_result(pid, pdir, run, result, {"data": {}}).model_dump()


def test_a_value_on_a_text_layer_is_cited_with_its_quote_box_and_a_highlighted_image(tmp_path, monkeypatch):
    client, pid, pdir = _project(tmp_path, monkeypatch, "Tenderer_A")
    res = _bid_result(pid, pdir, "Tenderer_A", 10)
    sig = res["fields"]["l"]["signature"]["page"]
    assert sig["quote"] == "authorised signatory" and sig["page"] == 10 and sig["page_size"] == [612.0, 792.0]
    x0, y0, x1, y1 = sig["box"]
    assert 0 <= x0 < x1 <= 612 and 0 <= y0 < y1 <= 792 and y0 > 100      # top-left origin: the line is near the top
    query = parse_qs(urlsplit(sig["image_url"]).query)
    assert query["highlight"] == ["authorised signatory"] and query["sig"] and query["exp"]

    marked = client.get(sig["image_url"])                                # no key: the signature opens it
    assert marked.status_code == 200 and marked.content[:4] == b"\x89PNG"
    plain = client.get(f"/projects/{pid}/documents/{sig['doc_id']}/pages/10/image", headers=KEY)
    assert marked.content != plain.content
    tampered = sig["image_url"].replace("highlight=authorised", "highlight=Tenderer")
    assert client.get(tampered).status_code == 403                       # the highlight is inside the signature

    date = res["fields"]["l"]["date"]["page"]                            # not on the page: a plain citation
    assert date["quote"] is None and date["box"] is None and "highlight" not in date["image_url"]
    assert any(e["quote"] == "Non-collusive Tendering Certificate" for e in res["verdicts"]["l"]["evidence"])


def test_a_scanned_page_keeps_the_plain_citation(tmp_path, monkeypatch):
    client, pid, pdir = _project(tmp_path, monkeypatch, "Tenderer_B")
    cite = _bid_result(pid, pdir, "Tenderer_B", 13)["fields"]["l"]["signature"]["page"]
    assert cite["quote"] is None and cite["box"] is None and cite["page_size"] is None
    assert "highlight" not in cite["image_url"] and client.get(cite["image_url"]).status_code == 200


def test_a_page_link_with_an_appended_highlight_still_opens(tmp_path, monkeypatch):
    """Old clients append ?highlight= to a page-only link; that keeps working."""
    client, pid, _ = _project(tmp_path, monkeypatch, "Tenderer_A")
    doc_id = client.get(f"/projects/{pid}/documents", headers=KEY).json()[0]["doc_id"]
    url = client.get(f"/projects/{pid}/documents/{doc_id}/pages", headers=KEY).json()[9]["image_url"]
    assert "highlight" not in url
    r = client.get(url + "&highlight=authorised+signatory")
    assert r.status_code == 200 and r.content != client.get(url).content


def test_documents_carry_the_project_path_a_rule_set_citation_names(tmp_path, monkeypatch):
    client, pid, pdir = _project(tmp_path, monkeypatch, "Tenderer_A")
    (pdir / "tender").mkdir(exist_ok=True)
    (pdir / "tender" / "09 Schedules.pdf").write_bytes((CASE / "tender" / "09 Schedules.pdf").read_bytes())
    docs = client.get(f"/projects/{pid}/documents", headers=KEY).json()
    assert {d["path"] for d in docs} == {"tender/09 Schedules.pdf", "bids/Tenderer_A/offer.pdf"}
    tender = next(d for d in docs if d["kind"] == "tender")
    assert tender["file"] == "09 Schedules.pdf"                          # Citation.file == Document.path
