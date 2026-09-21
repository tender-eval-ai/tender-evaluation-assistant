"""The rule builder, layer by layer, on located items: L1 match, L2 slots (S3-2); L3
novel rules and L4 coverage follow (S3-3). Every layer has a fixed input, a fixed output
shape, a code check on the model's answer and a call-count test on the FakeLLM."""
from __future__ import annotations

from app.rulesets import match as l1, slots as l2
from app.rulesets.nodes import NodeIndex
from app.rulesets.schema import DataClass, RuleSetItem, Template


def build_items(items: list[RuleSetItem], templates: dict[str, Template], index: NodeIndex, llm,
                data_class: DataClass) -> list[RuleSetItem]:
    matched = l1.match_items(items, templates, index, llm)
    return l2.fill_items(matched, templates, index, llm, data_class)
