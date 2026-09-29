"""The S3 eval scorer on the FakeLLM build of the synthetic tender: what it counts and how
it reads a key that names only Part and page."""
from __future__ import annotations

import json

from app.rulesets.builder import build_items
from app.rulesets.evaluate import score, table
from app.rulesets.schema import DataClass, RuleSet
from test.fakes import FakeLLM
from test.rulesets.conftest import NODES_DIR
from test.rulesets.fake_factory import rules

KEY = json.loads((NODES_DIR / "ruleset_key.json").read_text())


def fake_build(located, templates, index) -> RuleSet:
    llm = FakeLLM(rules=rules())
    out = build_items(located, templates, index, llm, DataClass.SYNTHETIC)
    return RuleSet(project_id="SYN-2026-001", version=1, data_class=DataClass.SYNTHETIC, items=out.items, gaps=out.gaps,
                   created_by="rule_builder", created_at="2026-09-20T00:00:00Z", model="fake", prompt_version="fake")


def test_the_scorer_counts_what_the_key_names(located, templates, index):
    result = score(fake_build(located, templates, index), KEY)
    t, p = result["totals"], result["percent"]
    assert t["items_found"] == [15, 15] and t["part_right"] == [15, 15] and t["page_right"] == [15, 15]
    # The scripted matcher picks (b) and (l) only; the key also expects (c) and (m) on the price schedule.
    assert t["template_right"] == [13, 15] and p["template_right"] == 86.7
    assert t["slots_right"] == [1, 2], "(b)'s quantity verified; (c) was not matched, so its slot is not filled"
    assert t["checks_recall"] == [1, 8], "the fake drafts one rule, (a)'s signature"
    assert t["statuses"] == {"gap": 12, "novel": 1, "verified": 2} and t["rules_total"] == 4 + (2 + 1) + 1, "(b): one addition"
    assert t["unverified_notes"] == 0 and t["gaps"] > 0 and t["gaps_reasoned"] == 0 and t["extra_items"] == []
    rows = result["rows"]
    assert rows["b"]["slots"]["estimated_quantity"] == {"value_ok": True, "verified": True, "node": "09-Schedules:00-Price-Schedule:PA:(2)"}
    assert rows["a"]["checks_found"] == ["signature"] and rows["n"]["checks_missing"] == ["document_present"]
    text = table(result)
    assert "| (b) | verified | yes | yes | yes | estimated_quantity: ok | - | 3 | 0 |" in text
    assert "| template_right | 13/15 (86.7%) |" in text


def test_a_key_with_only_part_and_page_scores_l0_alone(located, templates, index):
    thin = {"items": {k: {"part": v["part"], "page": v["page"]} for k, v in KEY["items"].items()}}
    result = score(fake_build(located, templates, index), thin)
    t = result["totals"]
    assert t["template_right"] == [0, 0] and t["slots_right"] == [0, 0] and t["checks_recall"] == [0, 0]
    assert result["percent"]["template_right"] is None and t["items_found"] == [15, 15]


def test_a_missing_item_and_an_extra_one_are_reported(located, templates, index):
    rs = fake_build(located, templates, index)
    fewer = rs.model_copy(update={"items": [i.model_copy(update={"letter": "x1"}) if i.letter == "o" else i for i in rs.items]})
    result = score(fewer, KEY)
    assert result["rows"]["o"] == {"found": False} and result["totals"]["extra_items"] == ["x1"]
    assert result["totals"]["items_found"] == [14, 15] and "| (o) | MISSING |" in table(result)
