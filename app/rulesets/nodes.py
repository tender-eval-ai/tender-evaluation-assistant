"""The parser's node table (app/parsing, L0) indexed for the rule builder: nodes by id,
their children, a subtree's text, and where a quote sits."""
from __future__ import annotations

import re
from collections import defaultdict

_WS = re.compile(r"\s+")


def squash(text: str | None) -> str:
    """Whitespace-insensitive, case-insensitive form for verbatim comparison."""
    return _WS.sub(" ", text or "").strip().casefold()


class NodeIndex:
    def __init__(self, nodes: list[dict]):
        self.nodes = nodes
        self.by_id: dict[str, dict] = {n["node_id"]: n for n in nodes}
        self.children: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            if n.get("parent_id"):
                self.children[n["parent_id"]].append(n["node_id"])

    def get(self, node_id: str | None) -> dict | None:
        return self.by_id.get(node_id) if node_id else None

    def text(self, node_id: str) -> str:
        node = self.by_id.get(node_id)
        return (node.get("text") or "") if node else ""

    def subtree(self, node_id: str) -> list[dict]:
        """The node and every descendant, depth first, in table order."""
        out, stack = [], [node_id]
        while stack:
            current = stack.pop()
            node = self.by_id.get(current)
            if node is None:
                continue
            out.append(node)
            stack.extend(reversed(self.children.get(current, [])))
        return out

    def subtree_text(self, node_id: str, limit: int = 4000) -> str:
        """Every node of the subtree as "[node_id] text" lines, cut at `limit` characters."""
        lines = []
        size = 0
        for node in self.subtree(node_id):
            text = _WS.sub(" ", node.get("text") or "").strip()
            if not text:
                continue
            line = f"[{node['node_id']}] {text}"
            if size + len(line) > limit:
                lines.append("[...]")
                break
            lines.append(line)
            size += len(line) + 1
        return "\n".join(lines)

    def find_quote(self, quote: str, roots: list[str], prefer: str | None = None) -> dict | None:
        """The node whose text holds `quote` verbatim (whitespace and case aside), looking at
        `prefer` first, then every node under `roots` in order. None when no node has it."""
        needle = squash(quote)
        if not needle:
            return None
        order: list[str] = [prefer] if prefer else []
        for root in roots:
            order.extend(n["node_id"] for n in self.subtree(root))
        seen = set()
        for node_id in order:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self.by_id.get(node_id)
            if node and needle in squash(node.get("text")):
                return node
        return None
