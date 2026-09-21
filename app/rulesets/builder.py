"""The rule builder, layer by layer, on located items: L1 match, L2 slots, L3 novel rules,
L4 coverage. Every layer has a fixed input, a fixed output shape, a code check on the
model's answer and a call-count test on the FakeLLM; L4 makes no call."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.rulesets import coverage as l4, match as l1, novel as l3, slots as l2
from app.rulesets.nodes import NodeIndex
from app.rulesets.schema import DataClass, Gap, RuleSetItem, Template


@dataclass
class BuildResult:
    items: list[RuleSetItem]
    gaps: list[Gap] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)     # drafted rule id -> the node it quotes


def build_items(items: list[RuleSetItem], templates: dict[str, Template], index: NodeIndex, llm,
                data_class: DataClass) -> BuildResult:
    matched = l1.match_items(items, templates, index, llm)
    filled = l2.fill_items(matched, templates, index, llm, data_class)
    drafted, sources = l3.draft_items(filled, index, llm, data_class)
    return BuildResult(items=drafted, gaps=l4.gaps_for(drafted, index, sources), sources=sources)
