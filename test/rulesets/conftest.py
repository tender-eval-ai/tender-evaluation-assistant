"""Fixtures for the rule builder: the synthetic tender's node table and located schedule
(tools/locate_case.py on test/data/synthetic_tender), the two test templates, and a FakeLLM."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rulesets.library import load_templates
from app.rulesets.nodes import NodeIndex
from app.rulesets.schema import RuleSetItem

DATA = Path(__file__).resolve().parents[1] / "data"
NODES_DIR = DATA / "synthetic_tender_nodes"


@pytest.fixture(scope="session")
def index() -> NodeIndex:
    return NodeIndex(json.loads((NODES_DIR / "nodes.json").read_text()))


@pytest.fixture
def located() -> list[RuleSetItem]:
    return [RuleSetItem.model_validate(i) for i in json.loads((NODES_DIR / "located.json").read_text())["items"]]


@pytest.fixture(scope="session")
def templates():
    return load_templates(DATA / "templates")
