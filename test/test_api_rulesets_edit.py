# ruff: noqa: F811  (the `api` fixture is imported from test_api_checks and named in each test)
"""The S3 editing routes on Postgres: an edit to a confirmed rule set opens draft N+1,
every change is attributed and logged, the diff reads back what changed, confirmation is
refused to the last editor and while a required slot is empty. Opt-in (-m postgres)."""
from __future__ import annotations

from pathlib import Path

import pytest

from test.test_api_checks import CHENYU, NASI, api, draft_body  # noqa: F401  (the fixture)

pytestmark = pytest.mark.postgres

TEMPLATES = Path(__file__).resolve().parent / "data" / "templates"
OWN = {"blank": {"status": "disqualified"}, "filled": {"status": "pass"}, "redacted": {"status": "needs_review"}}
CITE = {"file": "tender/09 Schedules.pdf", "page": 2, "node_id": "Sched:Notes:(4)", "quote": "Every page shall bear the chop", "data_class": "synthetic"}


def _confirmed_v1(client, pid):
    assert client.put(f"/projects/{pid}/ruleset/draft", json=draft_body(), headers=CHENYU).status_code == 200
    assert client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).json()["version"] == 1


def test_editing_a_confirmed_rule_set_opens_the_next_draft_and_the_diff_reads_it_back(api, monkeypatch):
    client, pid = api
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    _confirmed_v1(client, pid)

    r = client.patch(f"/projects/{pid}/ruleset/items/l", headers=CHENYU,
                     json={"note": {"kind": "reference", "text": "see Paragraph 9.4"}, "reason": "cross-reference"})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["status"] == "edited" and item["edit"]["by"] == "chenyu" and item["notes"][-1]["text"] == "see Paragraph 9.4"
    current = client.get(f"/projects/{pid}/ruleset").json()
    assert (current["version"], current["parent_version"], current["status"], current["updated_by"]) == (2, 1, "draft", "chenyu")
    versions = client.get(f"/projects/{pid}/ruleset/versions").json()
    assert [(v["version"], v["status"], v["updated_by"]) for v in versions] == [(1, "confirmed", "chenyu"), (2, "draft", "chenyu")]
    assert versions[0]["confirmed_at"].endswith("Z") or "+00:00" in versions[0]["confirmed_at"]   # ISO, not epoch

    diff = client.get(f"/projects/{pid}/ruleset/diff", params={"from": 1, "to": 2}).json()
    assert diff["from"] == 1 and diff["to"] == 2 and diff["added"] == [] and diff["removed"] == []
    assert diff["changed"][0]["letter"] == "l" and set(diff["changed"][0]["fields"]) == {"notes", "status"}
    assert diff["changed"][0]["edit"]["by"] == "chenyu" and diff["changed"][0]["edit"]["reason"] == "cross-reference"
    assert client.get(f"/projects/{pid}/ruleset/diff", params={"from": 1, "to": 9}).status_code == 404

    kinds = [e["kind"] for e in client.get(f"/projects/{pid}/events").json()["items"]]
    assert kinds[-2:] == ["ruleset.draft_opened", "ruleset.item_patched"]
    at = client.get(f"/projects/{pid}/events").json()["items"][-1]["at"]
    assert isinstance(at, str) and at[:4] == "2026"


def test_items_notes_and_gaps_are_added_edited_and_removed_with_a_reason(api, monkeypatch):
    client, pid = api
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    _confirmed_v1(client, pid)
    new = {"title": "Company chop on every page", "part": "B", "citation": CITE, "reason": "clause 22",
           "rules": [{"id": "chop.every_page", "check": "filled", "field": "chop.pages", "outcomes": OWN}]}
    r = client.post(f"/projects/{pid}/ruleset/items", json=new, headers=NASI)
    assert r.status_code == 201 and r.json()["letter"] == "x1" and r.json()["status"] == "edited" and r.json()["edit"]["by"] == "nasi"
    assert client.post(f"/projects/{pid}/ruleset/items", json=new, headers=NASI).json()["letter"] == "x2"
    assert client.request("DELETE", f"/projects/{pid}/ruleset/items/x2", json={"reason": "duplicate"}, headers=NASI).status_code == 204
    assert [i["letter"] for i in client.get(f"/projects/{pid}/ruleset").json()["items"]] == ["l", "x1"]
    assert client.request("DELETE", f"/projects/{pid}/ruleset/items/x2", json={"reason": "again"}, headers=NASI).status_code == 404

    bad = {**new, "rules": [{"id": "chop.every_page", "check": "filled", "field": "chop.pages", "consequence": "critical"}]}
    r = client.post(f"/projects/{pid}/ruleset/items", json=bad, headers=NASI)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    r = client.patch(f"/projects/{pid}/ruleset/items/l", json={"reason": "nothing"}, headers=NASI)
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"

    r = client.patch(f"/projects/{pid}/ruleset/items/x1/notes/0", headers=NASI,
                     json={"note": {"kind": "definition", "text": "chop: the company seal"}, "reason": "define"})
    assert r.status_code == 404                                              # x1 has no notes yet
    client.patch(f"/projects/{pid}/ruleset/items/x1", headers=NASI, json={"note": {"kind": "definition", "text": "chop"}, "reason": "add"})
    r = client.patch(f"/projects/{pid}/ruleset/items/x1/notes/0", headers=NASI,
                     json={"note": {"kind": "definition", "text": "chop: the company seal"}, "reason": "define"})
    assert r.status_code == 200 and r.json()["notes"] == [{"kind": "definition", "text": "chop: the company seal", "citation": None}]
    r = client.request("DELETE", f"/projects/{pid}/ruleset/items/x1/notes/0", json={"reason": "not needed"}, headers=NASI)
    assert r.status_code == 200 and r.json()["notes"] == []

    assert client.get(f"/projects/{pid}/ruleset/gaps").json() == []
    assert client.patch(f"/projects/{pid}/ruleset/gaps/Supp:13:(d)", json={"reason": "x"}, headers=NASI).status_code == 404
    draft = client.get(f"/projects/{pid}/ruleset").json()
    draft["gaps"] = [{"node_id": "Supp:13:(d)", "text": "shall deliver within 14 days"}]
    assert client.put(f"/projects/{pid}/ruleset/draft", json=draft, headers=NASI).status_code == 200
    r = client.patch(f"/projects/{pid}/ruleset/gaps/Supp:13:(d)", json={"reason": "covered by item (e)"}, headers=CHENYU)
    assert r.status_code == 200 and r.json()["reason"] == "covered by item (e)" and r.json()["edit"]["by"] == "chenyu"
    assert client.get(f"/projects/{pid}/ruleset/gaps").json()[0]["edit"]["reason"] == "covered by item (e)"


def test_confirmation_is_refused_to_the_last_editor_and_while_a_required_slot_is_empty(api, monkeypatch):
    client, pid = api
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(TEMPLATES))
    _confirmed_v1(client, pid)
    # I1.15: the item keeps its status, but its template's required slot is empty.
    r = client.patch(f"/projects/{pid}/ruleset/items/l", json={"template": "price_schedule", "reason": "wrong template on purpose"}, headers=CHENYU)
    assert r.status_code == 200 and r.json()["template"] == "price_schedule"
    r = client.post(f"/projects/{pid}/ruleset/confirm", headers=CHENYU)
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_approval"
    r = client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI)
    assert r.status_code == 409 and r.json()["error"]["details"]["blockers"] == [{"kind": "empty_required_slot", "letter": "l", "slot": "estimated_quantity"}]

    r = client.patch(f"/projects/{pid}/ruleset/items/l", headers=NASI,
                     json={"slot": {"name": "estimated_quantity", "value": 875000}, "reason": "from the Price Schedule note"})
    assert r.status_code == 200 and r.json()["slots"]["estimated_quantity"]["origin"] == "manual"
    assert client.post(f"/projects/{pid}/ruleset/confirm", headers=NASI).json()["error"]["code"] == "self_approval"   # nasi edited last
    confirmed = client.post(f"/projects/{pid}/ruleset/confirm", headers=CHENYU).json()
    assert confirmed["version"] == 2 and confirmed["status"] == "confirmed" and confirmed["confirmed_by"] == "chenyu"
    assert client.get(f"/projects/{pid}/ruleset").json()["version"] == 2
