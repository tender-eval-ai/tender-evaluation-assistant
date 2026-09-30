"""The recorded guest run (#132): a GET path's file name, the same in Python (tools/record_run.py)
and in the browser (web/src/replayKey.js), both tested against test/data/replay_keys.json."""
import json
from pathlib import Path

import pytest

from tools.record_run import citations_in, route_key, urls_in

VECTORS = json.loads((Path(__file__).resolve().parent / "data" / "replay_keys.json").read_text())


@pytest.mark.parametrize("case", VECTORS, ids=[c["path"][:60] for c in VECTORS])
def test_a_path_names_its_file_the_way_the_browser_does(case):
    assert route_key(case["path"]) == case["key"]


def test_a_signature_and_the_order_of_parameters_dont_change_the_file():
    a = route_key("/projects/p/documents/d/pages/1/image?highlight=x&sig=1&exp=2")
    assert a == route_key("/projects/p/documents/d/pages/1/image?exp=9&highlight=x&sig=8")
    assert a != route_key("/projects/p/documents/d/pages/1/image")
    assert all(c.isalnum() or c in "._-" for c in a) and len(route_key("/x?q=" + "y" * 400)) <= 150


def test_the_recorder_finds_every_image_and_every_quoted_citation():
    result = {"verdicts": {"l": {"evidence": [{"image_url": "/a?sig=1"}]}}, "fields": {"l": {"x": {"page": {"image_url": "/b"}}}}}
    assert sorted(urls_in(result)) == ["/a?sig=1", "/b"]
    cite = {"file": "tender/09 Schedules.pdf", "page": 7, "quote": "(a) The Offer"}
    ruleset = {"items": [{"citation": cite, "clauses": [{**cite, "quote": None}],
                          "slots": {"q": {"citation": {**cite, "page": 2}}}, "notes": []}], "parts": []}
    assert [c["page"] for c in citations_in(ruleset)] == [7, 2], "a citation without a quote needs no highlighted image"
