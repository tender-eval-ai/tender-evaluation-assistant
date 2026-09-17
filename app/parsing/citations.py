"""Resolve a citation in prose - "Paragraph 20.2 of the Terms of Tender" - to a node.

This is deliberately **not** a search. Full-text search was tried and is the wrong
tool: querying "Terms of Tender" over the node text returns 80 rows, every one of
which merely *mentions* the phrase, while the row that *is* the Terms of Tender
(the part node titled "TERMS OF TENDER") never surfaces at all. Ranking cannot fix
that, because the target is not the most relevant mention - it is a different kind
of thing from any mention.

Resolution is two exact lookups instead:

    "Paragraph 20.2 of the Terms of Tender"
       -> name "Terms of Tender"  -> scope prefix  <doc>:P1     (metadata)
       -> number "20.2" within that prefix         -> p.49      (exact match)

Both come from data captured at parse time - the page footer's document label and
the PART heading - so the same citation always resolves to the same node, or to an
explicit miss. No model, no threshold, no ranking.

Measured on the internal cross-references of three real tenders (675 citations):
98% / 98% / 84% resolve to exactly one node. See tests/test_citations.py, which
grades against the corpus itself rather than hand labels.
"""

import re
from collections import defaultdict
from typing import NamedTuple

# "Paragraph 20.2 of the Terms of Tender", and its sub-item forms "Paragraph
# 10.1(j) of…" and "Paragraph 17(a)(i) of…". The name is a run of capitalised words
# with lowercase connectors, because that is how these documents write their own
# titles ("General Conditions of Contract", "Terms of Tender (Supplement)").
_WORD = r"(?:[A-Z][a-zA-Z\-]+|[A-Z]{2,})"
_CITATION = re.compile(
    rf"(?:Paragraph|Clause)s?\s+(\d+(?:\.\d+)*)((?:\s*\([a-z]{{1,4}}\))*)\s+of\s+the\s+"
    rf"({_WORD}(?:\s+(?:of|the|to|and|for|in)\s+{_WORD}|\s+{_WORD})*(?:\s*\([A-Za-z]+\))?)"
)
_ITEM_MARKER = re.compile(r"\(([a-z]{1,4})\)")


class Citation(NamedTuple):
    """A parsed reference. `items` is the sub-item path, e.g. ("a", "i")."""

    number: str
    name: str
    items: tuple[str, ...] = ()
# The name run above will happily continue into the rest of the sentence when the
# next word is capitalised ("…of the Terms of Tender and Paragraph 5…" captured
# "Terms of Tender and Paragraph"). Cut at the connectives that resume prose.
_RESUMES_PROSE = re.compile(r"\s+(?:and|please|shall|which|is|are|to|or)\b.*$", re.I)
# A sub-item marker that leaked into the name: "Technical Specifications (e)".
# "(Supplement)" must survive, so only short markers are stripped.
_TRAILING_MARKER = re.compile(r"\s*\((?:[a-z]{1,2}|[ivx]{1,4})\)\s*$")


def normalise_name(name: str) -> str:
    """Fold a document name to a comparison key.

    Trailing plurals are dropped word by word so the corpus's own inconsistencies
    match: the documents cite both "Technical Specifications" and "Technical
    Specification", and one place writes "General Condition of Contract" for the
    General Conditions. Folding both sides identically costs nothing and recovers
    those without a special case per typo.
    """
    name = _TRAILING_MARKER.sub("", name or "")
    name = re.sub(r"[^a-z0-9()]+", " ", name.lower()).strip()
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") else word
                    for word in name.split())


def parse_citations(text: str) -> list[Citation]:
    """Every scoped citation in `text`."""
    flattened = re.sub(r"\s+", " ", text or "")
    return [
        Citation(
            number=m.group(1),
            name=_RESUMES_PROSE.sub("", m.group(3).strip()),
            items=tuple(_ITEM_MARKER.findall(m.group(2) or "")),
        )
        for m in _CITATION.finditer(flattened)
    ]


def _minimal_roots(node_ids) -> list[str]:
    """Drop any id that already sits under another in the set.

    A name can denote more than one subtree - Tender 3 contains two separate
    "Special Conditions of Contract" sub-documents - and those must stay separate.
    Folding them into a common prefix collapsed to the whole 366-page file, so
    every number in it matched and 31 citations came back spuriously ambiguous.
    """
    roots: list[str] = []
    for node_id in sorted(set(node_ids), key=len):
        if not any(node_id.startswith(f"{root}:") for root in roots):
            roots.append(node_id)
    return roots


class CitationIndex:
    """The lookup tables a citation needs, built once per tender."""

    def __init__(self, nodes):
        self._by_number: dict[str, list[dict]] = defaultdict(list)
        self._by_id: dict[str, dict] = {}
        for node in nodes:
            self._by_id[node["node_id"]] = node
            if node.get("number"):
                self._by_number[node["number"]].append(node)

        # A document names itself in two places and neither alone is sufficient.
        # The page footer carries a label for most documents, but TERMS-1's
        # footer has none (all 863 of its nodes have doc_name=None) - there,
        # "Terms of Tender" and "General Conditions of Contract" are PART titles.
        # Together they cover every document the citations actually reference.
        # Only container nodes define a scope. Reading the name off ordinary clause
        # nodes instead made every clause that merely carries a footer label a
        # candidate boundary, which is how two same-named sub-documents ended up
        # folded together.
        named: dict[str, list[str]] = defaultdict(list)
        roots_with_subdocs = {n["node_id"].split(":")[0] for n in nodes if n["kind"] == "subdocument"}
        for node in nodes:
            if node["kind"] == "part" and node.get("title"):
                named[normalise_name(node["title"])].append(node["node_id"])
            elif node["kind"] == "subdocument" and node.get("doc_name"):
                named[normalise_name(node["doc_name"])].append(node["node_id"])
            elif node["kind"] == "document":
                continue
            elif node.get("doc_name") and node["node_id"].split(":")[0] not in roots_with_subdocs:
                # A standalone file - one document, no embedded sub-documents - names
                # itself only in its page footer, so the whole file is the scope.
                named[normalise_name(node["doc_name"])].append(node["node_id"].split(":")[0])
        self.scopes = {name: _minimal_roots(ids) for name, ids in named.items()}

    def resolve(self, number: str, name: str, items: tuple[str, ...] = ()) -> list[dict]:
        """Nodes matching this citation. Empty = unresolved, >1 = genuinely ambiguous.

        Sub-items carry number=None, so a lookup on `number` structurally cannot
        return one; the sub-item path is walked by id instead.
        """
        prefixes = self.scopes.get(normalise_name(name))
        if not prefixes:
            return []
        hits = [node for node in self._by_number.get(number, [])
                if any(node["node_id"].startswith(f"{prefix}:") for prefix in prefixes)]
        if not items:
            return hits

        # "Paragraph 10.1(j)" names a sub-item, which the node_id path already
        # encodes - so this is another exact lookup, not a search.
        suffix = "".join(f":({marker})" for marker in items)
        deeper = [self._by_id[node["node_id"] + suffix]
                  for node in hits if node["node_id"] + suffix in self._by_id]
        # Falling back to the containing clause is a coarser answer but still a
        # correct location; returning nothing would hide a clause we did resolve.
        return deeper or hits

    def resolve_citation(self, citation: Citation) -> list[dict]:
        return self.resolve(citation.number, citation.name, citation.items)

    def resolve_text(self, text: str) -> list[tuple[Citation, list[dict]]]:
        """Resolve every citation in a block of prose, keeping unresolved ones."""
        return [(citation, self.resolve_citation(citation)) for citation in parse_citations(text)]
