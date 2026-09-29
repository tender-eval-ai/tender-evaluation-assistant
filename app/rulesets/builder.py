"""The rule builder, layer by layer, on located items: L1 match, L2 slots, L3 novel rules
and the additions to templates, L4 coverage. Every layer has a fixed input, a fixed output
shape, a code check on the model's answer and a call-count test on the FakeLLM; L4 makes
no call."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.rulesets import additions, coverage as l4, match as l1, novel as l3, slots as l2
from app.rulesets.nodes import NodeIndex
from app.rulesets.schema import DataClass, Gap, RuleSetItem, Template


@dataclass
class BuildResult:
    items: list[RuleSetItem]
    gaps: list[Gap] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)     # drafted or added rule id -> the node it quotes
    covered: list[str] = field(default_factory=list)          # nodes a template's own rule checks


def build_items(items: list[RuleSetItem], templates: dict[str, Template], index: NodeIndex, llm,
                data_class: DataClass) -> BuildResult:
    matched = l1.match_items(items, templates, index, llm)
    filled = l2.fill_items(matched, templates, index, llm, data_class)
    drafted, sources = l3.draft_items(filled, index, llm, data_class)
    added, found, covered = additions.add_to_items(drafted, index, llm, data_class)
    sources = {**sources, **found}
    return BuildResult(items=added, gaps=l4.gaps_for(added, index, sources, covered), sources=sources, covered=covered)
