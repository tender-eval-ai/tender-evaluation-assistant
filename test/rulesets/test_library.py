"""An empty or broken template library is never silent (J11-1): the status /health reports,
the worker's start-up warning, and the note a build with no templates leaves in its event."""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.jobs.worker import template_warnings
from app.rulesets import build_job
from app.rulesets.library import EMPTY, library_status
from test.rulesets.conftest import DATA


def test_the_status_counts_the_templates_and_names_a_file_that_does_not_load(tmp_path):
    assert library_status(DATA / "templates") == {"count": 2, "valid": True, "error": None}
    assert library_status(tmp_path / "missing") == {"count": 0, "valid": True, "error": None}
    (tmp_path / "price_schedule.json").write_text('{"id": "price_schedule"}')
    status = library_status(tmp_path)
    assert status["valid"] is False and status["count"] == 0
    assert status["error"].startswith("template file price_schedule.json is not a valid template: form_name: ")


def test_a_worker_that_builds_rule_sets_says_what_it_loaded(tmp_path, monkeypatch):
    assert template_warnings(["vendor_check"]) == [], "a worker that builds no rule set says nothing"
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(DATA / "templates"))
    assert template_warnings(["ruleset_build"]) == [f"templates: 2 from {DATA / 'templates'}"]
    monkeypatch.setenv("RULESET_TEMPLATES_DIR", str(tmp_path))
    assert template_warnings(["ruleset_build"]) == [f"WARNING: {EMPTY} ({tmp_path})"]
    (tmp_path / "broken.json").write_text("{")
    [line] = template_warnings(["ruleset_build"])
    assert line.startswith(f"WARNING: the template library at {tmp_path} does not load: template file broken.json")


class FakeStore:
    def __init__(self):
        self.events = []

    def draft(self, pid):
        return None

    def latest_confirmed(self, pid):
        return None

    def save_draft(self, pid, spec, by):
        self.spec = spec
        return 1, True

    def get_version(self, pid, version):
        return self.spec

    def event(self, kind, pid, subject, before, after, actor, reason=None):
        self.events.append((kind, reason))


def _save(tmp_path, monkeypatch, templates: int | None) -> str:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    located = json.loads((DATA / "synthetic_tender_nodes" / "located.json").read_text())["items"]
    data = {"items": located[:1], "parts": [], "gaps": []}
    if templates is not None:
        data["templates"] = templates
    store = FakeStore()
    build_job.save(SimpleNamespace(store=store, run={"project": "p1"}, data=data))
    [(kind, reason)] = store.events
    assert kind == "ruleset.built"
    return reason


def test_a_build_with_no_templates_says_so_in_its_event(tmp_path, monkeypatch):
    assert _save(tmp_path, monkeypatch, 0) == f"new draft; {EMPTY}"
    assert _save(tmp_path, monkeypatch, 2) == "new draft"
    assert _save(tmp_path, monkeypatch, None) == "new draft", "a run that began before the count was recorded"
