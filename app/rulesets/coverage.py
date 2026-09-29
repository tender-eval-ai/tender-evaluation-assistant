"""L4: what no rule covers. Code only, no model.

For every item, the clauses it cites are walked to `DEPTH` levels below the cited node; a
node whose text carries an obligation ("shall", "must") becomes a Gap unless something
handles it: a drafted rule (L3) or an addition to a template (additions) quotes it, the
additions step verified that one of the template's own rules checks it, or a verified slot
value was read from it. Templated items are walked too: a template no longer stands for
everything its clauses say, since a tender can add to a form. Gaps block confirmation until
a person gives a reason, so the list is kept to the cited clause and its direct
sub-clauses rather than every leaf of a long chapter."""
from __future__ import annotations

import re

from app.rulesets.nodes import NodeIndex
from app.rulesets.schema import Gap, RuleSetItem

DEPTH = 1
MODAL = re.compile(r"\b(shall|must)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.;:])\s+")
CONTAINERS = ("document", "subdocument")


def obligation_sentence(text: str) -> str | None:
    """The first sentence with an obligation in it, or None."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    for sentence in _SENTENCE_END.split(flat):
        if MODAL.search(sentence):
            return sentence[:300]
    return None


def nodes_near(index: NodeIndex, root: str, depth: int = DEPTH) -> list[dict]:
    """The cited node and its descendants down to `depth` levels."""
    out, frontier = [], [(root, 0)]
    while frontier:
        node_id, level = frontier.pop(0)
        node = index.get(node_id)
        if node is None:
            continue
        out.append(node)
        if level < depth:
            frontier.extend((child, level + 1) for child in index.children.get(node_id, []))
    return out


def gaps_for(items: list[RuleSetItem], index: NodeIndex, sources: dict[str, str], covered: list[str] = ()) -> list[Gap]:
    """`sources`: {drafted or added rule id: the node it quotes}; `covered`: nodes a
    template's own rule was verified to check."""
    covered = set(sources.values()) | set(covered) | {
        slot.citation.node_id for item in items for slot in item.slots.values()
        if slot.verified and slot.citation is not None and slot.citation.node_id}
    gaps: list[Gap] = []
    seen: set[str] = set()
    for item in items:
        for clause in item.clauses:
            if not clause.node_id:
                continue
            for node in nodes_near(index, clause.node_id):
                node_id = node["node_id"]
                if node_id in covered or node_id in seen or node.get("kind") in CONTAINERS:
                    continue
                sentence = obligation_sentence(node.get("text") or "")
                if sentence:
                    gaps.append(Gap(node_id=node_id, text=sentence))
                    seen.add(node_id)
    return gaps
