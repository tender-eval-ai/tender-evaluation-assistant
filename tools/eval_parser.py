"""Score the tender parser (app/parsing) and the citation resolver (app/parsing/citations.py).

Two evaluations, reported separately so a miss points at the layer to fix:

1. Parser recall - of the nodes in a hand-built answer key (a deep key, see
   `ground_truth/deep/SPEC.md`), how many the parser produced.

   A key node with a marker path (`ToT:3.3(a)(i)`, `CCS:PartA:Item(c)`) is found when
   a parser node is in the same document, starts on the key node's first page, and
   its id ends with the same marker path (`...:3.3:(a):(i)`, `...:PA:(c)`).
   A whole document (`NCTC`) is found as a document or sub-document node on its
   first page.

   A key node with no marker path - a heading, a "Notes:" line, a note, a form
   field, a tail - is found when a parser node inside the node matched to its
   nearest marked ancestor starts on the key node's first page with the key node's
   first words. The ancestor must itself be found; a key node with no marked
   ancestor is looked for on its page alone. Notes count here although they print
   a marker: the key nests them under a "Notes" level the parser does not have.

   Recall = found / key nodes, reported for all, marked and unmarked nodes.

2. Citation resolution - every citation `parse_citations` finds in the tender's own
   page text, resolved by `CitationIndex` over the parser's nodes. Each is unique
   (exactly one node), ambiguous (several) or unresolved (none). The score is
   unique / all; no hand labelling, the tender's cross-references grade themselves.

The keys and the tender PDFs are redacted sample documents and stay outside git.
Usage:

    python tools/eval_parser.py --deep-key <dir>/deep/Tender 2.json --pdfs <tender folder or PDF> \\
        [--nodes cache.json] [--out report.json]

Results are recorded in docs/evals/parser_l0.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.parsing.citations import CitationIndex, parse_citations  # noqa: E402
from app.parsing.layout_document_index import parse_document  # noqa: E402
from app.parsing.loader import load_pdf  # noqa: E402

#: Squashed characters of a key node's first words that must open the parser node.
PREFIX = 24
#: Squashed characters allowed before them (a short heading the key leaves out).
HEADING_SLACK = 12
CONTAINER_KINDS = ("document", "subdocument")


def parse_pdfs(pdfs: list[Path]) -> list[dict]:
    nodes: list[dict] = []
    for pdf in pdfs:
        for node in parse_document(None, load_pdf(pdf)):
            node["source_file"] = pdf.name
            nodes.append(node)
    return nodes


def squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").lower()


# ---------------------------------------------------------------- 1. parser recall

_SCOPE = re.compile(r"(?:Part|Table)([A-Z0-9]+|I[AB])")
_MARKED = re.compile(r"(?:Item|Para|Row)?(\d+(?:\.\d+)*|\([^)]+\))((?:\([^)]+\))*)")


def key_marker_path(node_id: str) -> list[set[str]] | None:
    """The parser id segments a key id's path must end with, each as the set of forms
    the parser writes it in; None when the key node has no marker path.

    `ToT:3.3(a)(i)` -> [{3.3}, {(a)}, {(i)}]; `InfoSchedule:TableB:Row(c)` -> [{PB, TB},
    {(c)}]; `PriceSchedule:PartA:Item1` -> [{PA, TA}, {1, (1)}]; `NCTC` -> [] (a whole
    document); `TechSpec:2:Glossary`, `POGS:Notes`, `...:Note(ii)` -> None.
    """
    path: list[set[str]] = []
    for segment in node_id.split(":")[1:]:
        scope = _SCOPE.fullmatch(segment)
        marked = None if segment.startswith("Note") else _MARKED.fullmatch(segment)
        if scope:
            path.append({f"P{scope.group(1)}", f"T{scope.group(1)}"})
        elif marked:
            head = marked.group(1).strip("()")
            path.append({head, f"({head})"})
            path.extend({item} for item in re.findall(r"\([^)]+\)", marked.group(2)))
        else:
            return None
    return path


def _ends_with(node: dict, path: list[set[str]]) -> bool:
    if not path:
        return node["kind"] in CONTAINER_KINDS
    # "#2" tells apart a marker repeated under one parent; it is not part of the marker.
    segments = [re.sub(r"#\d+$", "", s) for s in node["node_id"].split(":")[1:]]
    return len(segments) >= len(path) and all(s in forms for s, forms in zip(segments[-len(path):], path))


def _opens_with(node: dict, first_words: str) -> bool:
    return 0 <= squash(node.get("text")).find(squash(first_words)[:PREFIX]) <= HEADING_SLACK


def _file_name(source_file: str | None) -> str | None:
    # A parser run may record the file with its folder ("tender/1 Tender Form.pdf"); keys name the file.
    return Path(source_file).name if source_file else None


def match_deep_key(key_nodes: list[dict], nodes: list[dict], single_file: bool) -> dict[str, dict]:
    """{key node id: {"marked", "node" (the parser node or None), "why"}} by the rules above."""
    on_page: dict[tuple, list[dict]] = {}
    for node in nodes:
        if node.get("page"):
            file = None if single_file else _file_name(node.get("source_file"))
            on_page.setdefault((file, node["page"]), []).append(node)
    by_key = {k["node_id"]: k for k in key_nodes}

    def page_of(key_node):
        return on_page.get((None if single_file else key_node.get("file"), key_node["page"][0]), [])

    result: dict[str, dict] = {}
    for key_node in key_nodes:
        path = key_marker_path(key_node["node_id"])
        if path is None:
            continue
        hits = [n for n in page_of(key_node) if _ends_with(n, path)]
        hits.sort(key=lambda n: not _opens_with(n, key_node["first_words"]))
        result[key_node["node_id"]] = {"marked": True, "node": hits[0] if hits else None,
                                       "why": "" if hits else "no node with this path on this page"}

    for key_node in key_nodes:
        if key_node["node_id"] in result:
            continue
        ancestor = key_node.get("parent_id")
        while ancestor and key_marker_path(ancestor) is None:
            ancestor = by_key.get(ancestor, {}).get("parent_id")
        candidates = page_of(key_node)
        if ancestor is not None:
            anchor = (result.get(ancestor) or {}).get("node")
            if anchor is None:
                result[key_node["node_id"]] = {"marked": False, "node": None, "why": "marked ancestor not found"}
                continue
            candidates = [n for n in candidates
                          if n["node_id"] == anchor["node_id"] or n["node_id"].startswith(anchor["node_id"] + ":")]
        hits = [n for n in candidates if _opens_with(n, key_node["first_words"])]
        why = "" if hits else ("first words not inside the ancestor on this page" if ancestor
                               else "first words not on this page")
        result[key_node["node_id"]] = {"marked": False, "node": hits[0] if hits else None, "why": why}
    return result


def parser_recall(deep_key: dict, nodes: list[dict], single_file: bool) -> dict:
    matches = match_deep_key(deep_key["nodes"], nodes, single_file)
    rows = [{"key_node": k, "marked": m["marked"], "found": m["node"] is not None,
             "parser_node": m["node"]["node_id"] if m["node"] else None, "why": m["why"]}
            for k, m in matches.items()]

    def rate(subset):
        return sum(r["found"] for r in subset), len(subset)

    return {"all": rate(rows), "marked": rate([r for r in rows if r["marked"]]),
            "unmarked": rate([r for r in rows if not r["marked"]]), "rows": rows}


# ---------------------------------------------------------------- 2. citation resolution

def citation_resolution(pages_by_file: dict[str, list], nodes: list[dict]) -> dict:
    index = CitationIndex(nodes)
    rows = []
    for file, pages in pages_by_file.items():
        for page in pages:
            for citation in parse_citations(page.native_text or ""):
                hits = index.resolve_citation(citation)
                outcome = "unique" if len(hits) == 1 else "ambiguous" if hits else "unresolved"
                rows.append({"file": file, "page": page.page_number, "name": citation.name,
                             "target": "/".join(ident for _, ident in citation.path) or "(whole document)",
                             "outcome": outcome, "nodes": [n["node_id"] for n in hits]})
    counts = Counter(r["outcome"] for r in rows)
    return {"unique": (counts["unique"], len(rows)), "ambiguous": counts["ambiguous"],
            "unresolved": counts["unresolved"], "rows": rows}


# ---------------------------------------------------------------- report

def _pct(pair) -> str:
    ok, total = pair
    return f"{ok}/{total} {100 * ok / total:5.1f}%" if total else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deep-key", type=Path, required=True, help="ground_truth/deep/<tender>.json")
    parser.add_argument("--pdfs", type=Path, required=True, help="the tender's folder of PDFs, or its combined PDF")
    parser.add_argument("--nodes", type=Path, help="reuse (or write) parsed nodes as JSON")
    parser.add_argument("--out", type=Path, help="write the full report, every row, as JSON")
    args = parser.parse_args()

    pdfs = sorted(args.pdfs.glob("*.pdf")) if args.pdfs.is_dir() else [args.pdfs]
    if args.nodes and args.nodes.exists():
        nodes = json.loads(args.nodes.read_text())
    else:
        nodes = parse_pdfs(pdfs)
        if args.nodes:
            args.nodes.write_text(json.dumps(nodes, ensure_ascii=False))
    deep_key = json.loads(args.deep_key.read_text())

    recall = parser_recall(deep_key, nodes, single_file=len(pdfs) == 1)
    citations = citation_resolution({pdf.name: load_pdf(pdf) for pdf in pdfs}, nodes)

    print(f"{deep_key['tender']}: {len(nodes)} parser nodes, {len(deep_key['nodes'])} key nodes")
    print(f"  parser recall        {_pct(recall['all'])}")
    print(f"    marked             {_pct(recall['marked'])}")
    print(f"    unmarked           {_pct(recall['unmarked'])}")
    print(f"  citations unique     {_pct(citations['unique'])}"
          f"   ambiguous {citations['ambiguous']}, unresolved {citations['unresolved']}")
    if args.out:
        args.out.write_text(json.dumps({"tender": deep_key["tender"], "parser_recall": recall,
                                        "citations": citations}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
