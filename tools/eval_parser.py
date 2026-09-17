"""Score the tender parser (app/parsing) against a ground-truth answer key.

The answer keys and the tender PDFs are redacted sample documents, so they live
outside git; this script only reads them. Usage:

    python tools/eval_parser.py --key <dir>/Tender 2.json --pdfs <tender folder> [--nodes cache.json] [--out report.json]

`--pdfs` is a folder of PDFs (one tender, several files) or a single combined PDF.

Every answer-key entry is scored on the node the parser produced for it:

- coverage   a node exists for the entry (right file, starting inside the entry's pages)
- page       that node starts on the entry's first page
- position   the node's text starts with its own marker and that text is really on the page
- length     items and Part intros: node length within 10% of the key's `chars`;
             references: the node's subtree ends on the entry's last page
- citation   references only: `CitationIndex.resolve_text` on the citation as written
             returns that node (or another node for the same target on the same pages)
- split      combined PDFs only: document start pages found, recall and precision
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from app.parsing.citations import CitationIndex  # noqa: E402
from app.parsing.layout_document_index import parse_document  # noqa: E402
from app.parsing.loader import load_pdf  # noqa: E402

LENGTH_TOLERANCE = 0.10
CONTAINER_KINDS = ("document", "subdocument", "part", "annex")


def parse_pdfs(pdfs: list[Path]) -> list[dict]:
    nodes: list[dict] = []
    for pdf in pdfs:
        for node in parse_document(None, load_pdf(pdf)):
            node["source_file"] = pdf.name
            nodes.append(node)
    return nodes


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").lower()


class Tender:
    """Parser nodes plus the page text they came from, indexed for matching."""

    def __init__(self, nodes: list[dict], pdfs: list[Path]):
        self.nodes = nodes
        self.single_file = len(pdfs) == 1
        self.children: dict[str, list[dict]] = defaultdict(list)
        for node in nodes:
            if node.get("parent_id"):
                self.children[node["parent_id"]].append(node)
        self._page_text: dict[tuple[str, int], str] = {}
        self._docs = {pdf.name: fitz.open(pdf) for pdf in pdfs}
        self.citations = CitationIndex(nodes)

    def page_text(self, file: str, page: int) -> str:
        key = (file, page)
        if key not in self._page_text:
            doc = self._docs[file]
            self._page_text[key] = _squash(doc[page - 1].get_text()) if 1 <= page <= len(doc) else ""
        return self._page_text[key]

    def last_page(self, node: dict) -> int | None:
        pages = [node["page"]] if node.get("page") else []
        stack = list(self.children.get(node["node_id"], []))
        while stack:
            child = stack.pop()
            if child.get("page"):
                pages.append(child["page"])
            stack.extend(self.children.get(child["node_id"], []))
        return max(pages) if pages else None

    def in_file(self, node: dict, file: str | None) -> bool:
        return self.single_file or file is None or node["source_file"] == file


def _part_letter(node: dict) -> str | None:
    part = node.get("part") or ""
    return part.split()[-1] if part else None


def _marker_ok(node: dict, expected: str | None) -> bool:
    text = _squash(node.get("text"))
    if not text:
        return True  # containers carry no text of their own; page decides
    return expected is None or text.startswith(_squash(expected))


def _on_page(tender: Tender, node: dict) -> bool:
    text = _squash(node.get("text"))
    if not text:
        return True
    return text[:30] in tender.page_text(node["source_file"], node["page"])


# ---------------------------------------------------------------- references

_SUBITEMS = re.compile(r"\(([a-z]{1,4})\)")


def reference_matcher(clause_id: str):
    """Turn an answer-key clause id into (predicate, expected marker)."""
    head, _, rest = clause_id.partition(":")
    if head in ("ToT", "TermsSupp") and rest and rest[0].isdigit():
        number = re.match(r"[\d.]+", rest).group(0).rstrip(".")
        items = _SUBITEMS.findall(rest)
        if items:
            path = f":{number}" + "".join(f":({i})" for i in items)
            return (lambda n, t, p=path: n["node_id"].endswith(p)), f"({items[-1]})"
        return (lambda n, t, num=number: n.get("number") == num and n["kind"] in ("clause", "subclause")), number
    if head in ("ToT",) and rest.startswith("Annex"):
        letter = rest[len("Annex"):].split(".")[0]
        return (lambda n, t, a=letter: n["kind"] in CONTAINER_KINDS
                and re.search(rf"\bannex {a.lower()}\b", " ".join(
                    filter(None, [n.get("title"), n.get("doc_name"), n.get("part")])).lower())), None
    m = re.fullmatch(r"(?:Part|Table)([A-Z0-9]+|I[AB])(?:[.:](?:Item|Para)?(\d+))?", rest or "")
    if m:
        part, number = m.group(1), m.group(2)
        if number:
            return (lambda n, t, p=part, num=number: _part_letter(n) == p and n.get("number") == num), number
        return (lambda n, t, p=part: n["kind"] == "part" and _part_letter(n) == p), None
    m = re.fullmatch(r"(?:Part)?\(?(\d+)\)?", rest or "")
    if m:
        return (lambda n, t, lab=f"({m.group(1)})": n.get("label") == lab), f"({m.group(1)})"
    # A whole document, or a named annex of one: a container starting on the page.
    return (lambda n, t: n["kind"] in CONTAINER_KINDS), None


def _candidates(tender: Tender, ref: dict, pages: list[int] | None):
    if not pages:
        return []
    predicate, marker = reference_matcher(ref["clause_id"])
    start, end = pages
    found = [n for n in tender.nodes
             if n.get("page") and start <= n["page"] <= end and tender.in_file(n, ref.get("file"))
             and predicate(n, tender)]
    found.sort(key=lambda n: (n["page"] != start, CONTAINER_KINDS.index(n["kind"])
                              if n["kind"] in CONTAINER_KINDS else len(CONTAINER_KINDS)))
    return [(n, marker, pages) for n in found]


def score_reference(tender: Tender, ref: dict) -> dict:
    hits = _candidates(tender, ref, ref["pages"]) + _candidates(tender, ref, ref.get("alt_pages"))
    result = {"id": ref["id"], "clause_id": ref["clause_id"], "text": ref["text"],
              "coverage": bool(hits), "page": False, "position": False, "length": False, "citation": False}
    if not hits:
        return result
    node, marker, pages = hits[0]
    result.update(
        node_id=node["node_id"], node_page=node["page"],
        page=node["page"] == pages[0],
        position=node["page"] == pages[0] and _marker_ok(node, marker) and _on_page(tender, node),
        length=tender.last_page(node) == pages[1],
    )
    hit_ids = {n["node_id"] for n, _, _ in hits}
    resolved = [n for _, nodes in tender.citations.resolve_text(ref["text"]) for n in nodes]
    result["citation"] = any(n["node_id"] in hit_ids for n in resolved)
    return result


# ---------------------------------------------------------------- schedule items

def score_schedule_entry(tender: Tender, entry: dict, schedule_file: str | None, schedule_pages) -> dict:
    is_item = "letter" in entry
    label = f"({entry['letter']})" if is_item else None
    part = entry["part"]
    lo, hi = schedule_pages
    found = [n for n in tender.nodes
             if n.get("page") and lo <= n["page"] <= hi and tender.in_file(n, schedule_file)
             and _part_letter(n) == part
             and ((n["kind"] == "subitem" and n.get("label") == label) if is_item else n["kind"] == "part")]
    name = label or f"Part {part} intro"
    result = {"entry": f"Part {part} {name}" if is_item else name,
              "coverage": bool(found), "page": False, "position": False, "length": False}
    if not found:
        return result
    node = min(found, key=lambda n: n["page"] != entry["page"])
    length = len(node["text"])
    result.update(
        node_id=node["node_id"], node_page=node["page"], node_chars=length, key_chars=entry["chars"],
        page=node["page"] == entry["page"],
        position=node["page"] == entry["page"] and _marker_ok(node, label or f"Part {part}") and _on_page(tender, node),
        length=abs(length - entry["chars"]) <= LENGTH_TOLERANCE * entry["chars"],
    )
    return result


# ---------------------------------------------------------------- report

def score(key: dict, tender: Tender) -> dict:
    items = key["items"]
    schedule_file = items[0].get("file")
    pages = [e["page"] for e in items + key["part_intros"]]
    schedule_pages = (min(pages), max(pages))

    schedule = [score_schedule_entry(tender, e, schedule_file, schedule_pages)
                for e in key["part_intros"] + items]
    references = [score_reference(tender, r) for r in key["references"]]

    report = {"tender": key["tender"], "schedule": schedule, "references": references}
    metrics = {}
    for group, rows, names in (("schedule", schedule, ("coverage", "page", "position", "length")),
                               ("references", references, ("coverage", "citation", "page", "position", "length"))):
        for name in names:
            metrics[f"{group}.{name}"] = (sum(r[name] for r in rows), len(rows))

    if tender.single_file:
        truth = {d["first_page"] for d in key["documents"]}
        starts = {n["page"] for n in tender.nodes if n["kind"] == "subdocument" and n.get("page")} | {1}
        metrics["split.recall"] = (len(truth & starts), len(truth))
        metrics["split.precision"] = (len(truth & starts), len(starts))
        report["split"] = {"missed": sorted(truth - starts), "extra": sorted(starts - truth)}
    report["metrics"] = metrics
    return report


def print_report(report: dict, show_failures: bool) -> None:
    print(f"\n{report['tender']}")
    for name, (ok, total) in report["metrics"].items():
        rate = ok / total if total else 0.0
        flag = "" if rate >= 0.9 else "  < 90%"
        print(f"  {name:<22} {ok:>3}/{total:<3} {rate:6.1%}{flag}")
    if not show_failures:
        return
    if "split" in report:
        print(f"  split missed starts {report['split']['missed']} extra {report['split']['extra']}")
    for row in report["schedule"]:
        bad = [k for k in ("coverage", "page", "position", "length") if not row[k]]
        if bad:
            print(f"  schedule {row['entry']:<18} fails {bad}  node={row.get('node_id', '-')}"
                  f" chars={row.get('node_chars')}/{row.get('key_chars')}")
    for row in report["references"]:
        bad = [k for k in ("coverage", "citation", "page", "position", "length") if not row[k]]
        if bad:
            print(f"  ref {row['id']} {row['clause_id']:<28} fails {bad}  node={row.get('node_id', '-')}"
                  f" p={row.get('node_page')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--pdfs", type=Path, required=True)
    parser.add_argument("--nodes", type=Path, help="reuse (or write) parsed nodes as JSON")
    parser.add_argument("--out", type=Path, help="write the full report as JSON")
    parser.add_argument("--failures", action="store_true", help="list every failing entry")
    args = parser.parse_args()

    key = json.loads(args.key.read_text())
    pdfs = sorted(args.pdfs.glob("*.pdf")) if args.pdfs.is_dir() else [args.pdfs]
    if args.nodes and args.nodes.exists():
        nodes = json.loads(args.nodes.read_text())
    else:
        nodes = parse_pdfs(pdfs)
        if args.nodes:
            args.nodes.write_text(json.dumps(nodes, ensure_ascii=False))

    report = score(key, Tender(nodes, pdfs))
    print_report(report, args.failures)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
