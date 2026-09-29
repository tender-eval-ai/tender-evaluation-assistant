"""The parser nodes a checklist key's reference row points at, for test_locate's
real-tender test. A checklist key (`ground_truth/<tender>.json`) names each clause the
Completeness Check Schedule cites as `ToT:10.1(j)`, `PriceSchedule:PartA`, and so on;
this turns that id into the nodes it should resolve to."""
from __future__ import annotations

import re
from pathlib import Path

CONTAINER_KINDS = ("document", "subdocument", "part", "annex")
_SUBITEMS = re.compile(r"\(([a-z]{1,4})\)")


def _part_letter(node: dict) -> str | None:
    part = node.get("part") or ""
    return part.split()[-1] if part else None


def reference_matcher(clause_id: str, text: str = ""):
    """Turn an answer-key clause id into a predicate on a parser node.

    `text` is the reference as written. "PartN" is the id shape of both "Part 4 of
    the Tender Form" (a Part heading) and "part (4) in the Appendix" (a numbered
    entry labelled "(4)"); only the written form tells them apart.
    """
    head, _, rest = clause_id.partition(":")
    numbered_part = re.search(r"\bpart\s*\((\d+)\)", text, re.I)
    if numbered_part and re.fullmatch(r"(?:Part)?\(?\d+\)?", rest or ""):
        label = f"({numbered_part.group(1)})"
        return lambda n, lab=label: n.get("label") == lab
    if head in ("ToT", "TermsSupp") and rest and rest[0].isdigit():
        number = re.match(r"[\d.]+", rest).group(0).rstrip(".")
        items = _SUBITEMS.findall(rest)
        if items:
            path = f":{number}" + "".join(f":({i})" for i in items)
            return lambda n, p=path: n["node_id"].endswith(p)
        return lambda n, num=number: n.get("number") == num and n["kind"] in ("clause", "subclause")
    if head in ("ToT",) and rest.startswith("Annex"):
        letter = rest[len("Annex"):].split(".")[0]
        return lambda n, a=letter: n["kind"] in CONTAINER_KINDS and bool(re.search(
            rf"\bannex {a.lower()}\b", " ".join(filter(None, [n.get("title"), n.get("doc_name"), n.get("part")])).lower()))
    m = re.fullmatch(r"(?:Part|Table)([A-Z0-9]+|I[AB])(?:[.:](?:Item|Para)?(\d+))?", rest or "")
    if m:
        part, number = m.group(1), m.group(2)
        if number:
            return lambda n, p=part, num=number: _part_letter(n) == p and n.get("number") == num
        return lambda n, p=part: n["kind"] == "part" and _part_letter(n) == p
    m = re.fullmatch(r"(?:Part)?\(?(\d+)\)?", rest or "")
    if m:
        return lambda n, lab=f"({m.group(1)})": n.get("label") == lab
    # A whole document, or a named annex of one: a container starting on the page.
    return lambda n: n["kind"] in CONTAINER_KINDS


def candidates(nodes: list[dict], ref: dict, pages: list[int] | None, single_file: bool) -> list[dict]:
    """The parser nodes a reference row points at, within its page range."""
    if not pages:
        return []
    predicate = reference_matcher(ref["clause_id"], ref.get("text", ""))
    start, end = pages
    return [n for n in nodes
            if n.get("page") and start <= n["page"] <= end
            and (single_file or ref.get("file") is None or Path(n["source_file"]).name == ref["file"])
            and predicate(n)]
