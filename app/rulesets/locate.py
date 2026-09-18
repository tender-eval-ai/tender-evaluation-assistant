"""Locate the Completeness Check Schedule (plan item L0): every item with its Part and
the clauses it points to. This is the map every rule and every vendor check hangs off.

Two readings of the same pages are combined, each doing what it is good at:

- **Which items exist, and in which Part** comes from the schedule's own page text
  (ported from Bidding-AI-expert@7e8e273, rules/completeness_schedule.py). The
  schedule is found by its page footer, split at its "Part A/B/C" headings and at
  line-start "(x)" markers. This reading does not depend on the layout model, so a
  layout mistake cannot drop an item: on the unchanged parser port, items (j) and (k)
  of one tender's schedule were merged into (i) in the node table while the page text
  still had all three.
- **Where each item and each cited clause is** comes from the parser's node table
  (`app.parsing`): the item's own node (id, page, verbatim text), and every citation
  written in the item resolved to a node by `CitationIndex` - exact lookups, not
  search. The port's own citation pattern understood only "Paragraph N of the Terms of
  Tender"; Tables, schedule Parts, Price Schedule items and whole documents, which are
  more than half of what the schedules cite, came back empty.

The result is shaped to the rule-set contract (`schema.py`): `LocatedItem` carries the
`RuleSetItem` fields L0 can fill (letter, title, part, citation, clauses) and turns
into one with `as_rule_set_item`. A citation that did not resolve is kept, as written,
in `unresolved` rather than dropped, so a missing clause is visible.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.parsing.citations import CitationIndex, normalise_name
from app.parsing.document_index import normalize_whitespace
from app.rulesets.schema import Citation, DataClass, ItemStatus, RuleSetItem, Tier

# Copied from procurement_agent.rules.stage1 at 7e8e273 (stage1 is not ported).
# Matches the document-name line printed immediately before a page's own "Page X
# of Y" pagination marker - confirmed present on every real tender sampled, and
# position-independent within the page's extracted text (PyMuPDF's get_text() does
# NOT reliably put this line last - confirmed on real data, it can come first).
# This is what makes document identification work on a combined single-PDF tender
# (Tender 3, 366 pages, one filename) where the filename itself carries no
# document-name signal at all.
_PAGE_FOOTER_PATTERN = re.compile(r"\n([^\n]+?)\s{1,}Page \d+ of \d+")


def _page_footer_text(page) -> str:
    if not page.has_native_text or not page.native_text:
        return ""
    match = _PAGE_FOOTER_PATTERN.search(page.native_text)
    return match.group(1).strip() if match else ""


# The Completeness Check Schedule is a standalone public-authored document (not
# prose requiring LLM interpretation) - every real tender sampled prints "Completeness
# Check Schedule" in its own page footer (confirmed on Tender 1, Tender 2,
# Tender 3's 366-page combined PDF). A "SAMPLE COMPLETENESS CHECK SCHEDULE" also
# exists in some tenders (a filled-in example under a differently-footered Annex) -
# it never carries this exact footer, so the footer check alone excludes it without
# needing a separate "SAMPLE" keyword guard.
SCHEDULE_NAME = "Completeness Check Schedule"
_PART_HEADING_PATTERN = re.compile(r"\nPart ([A-Z])\b")
_LETTERED_ITEM_PATTERN = re.compile(r"\n\(([a-z])\)\s*")
_ROMAN_II = re.compile(r"\n\(ii\)")
_TITLE_CHARS = 120


# ---------------------------------------------------------------- page text (ported)

def find_completeness_check_schedule_pages(pages) -> list:
    matches = [
        page
        for page in pages
        if page.has_native_text and SCHEDULE_NAME.lower() in _page_footer_text(page).lower()
    ]
    return sorted(matches, key=lambda p: (p.source_file, p.page_number))


def _page_number_at(offsets: list[tuple[int, int]], pos: int) -> int:
    result = offsets[0][1]
    for offset, page_number in offsets:
        if offset <= pos:
            result = page_number
        else:
            break
    return result


def _strip_page_header(text: str, footer_text: str) -> str:
    # Every schedule page repeats "Tender Ref.: X ... {footer_text} Page N of M" at
    # its own top (confirmed on real data - Tender 3 also inserts an extra
    # "TECHNICAL PROPOSAL" section label after this block, tenders may vary here,
    # but the footer_text + "Page N of M" anchor is the one thing already confirmed
    # stable across all 3 tenders). Without stripping this, an item that happens to
    # end right at a page boundary swallows the next page's own header as trailing
    # content (confirmed real bug: Tender 1 item (l) captured "Tender Ref.:
    # Tender 1 Completeness Check Schedule Completeness Check Schedule Page 3 of
    # 3" after its real text). Non-greedy from page start, so it only removes up to
    # the first (i.e. the header's own) occurrence.
    #
    # Only when that block really is a header: the port removed everything up to
    # the label wherever it was, so a page whose text layer puts the label last (a
    # generated PDF does) lost its whole text. A header holds no Part heading or item
    # marker; if the text before the label does, only the label line is removed.
    if not footer_text:
        return text
    pattern = re.compile(re.escape(footer_text) + r"\s*Page\s+\d+\s+of\s+\d+\s*", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return text
    before = "\n" + text[:match.start()]
    if not (_PART_HEADING_PATTERN.search(before) or _LETTERED_ITEM_PATTERN.search(before)):
        return text[match.end():]
    return text[:match.start()] + "\n" + text[match.end():]


@dataclass
class _TextItem:
    letter: str
    text: str
    page: int


@dataclass
class _TextPart:
    part: Tier
    intro: str
    page: int
    items: list[_TextItem]


def _read_schedule_text(schedule_pages: list) -> list[_TextPart]:
    # Concatenate all schedule pages into one string, tracking where each page starts,
    # so a lettered item that begins on one page and continues onto the next is still
    # captured whole, while each match can still be attributed back to its real source
    # page.
    combined = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for page in schedule_pages:
        offsets.append((pos, page.page_number))
        text = _strip_page_header(page.native_text or "", _page_footer_text(page))
        combined.append(text)
        pos += len(text) + 1
    full_text = "\n" + "\n".join(combined)
    offsets = [(offset + 1, number) for offset, number in offsets]

    part_matches = [m for m in _PART_HEADING_PATTERN.finditer(full_text) if m.group(1) in Tier.__members__]
    parts: list[_TextPart] = []
    for index, part_match in enumerate(part_matches):
        block_start = part_match.end()
        block_end = part_matches[index + 1].start() if index + 1 < len(part_matches) else len(full_text)
        block_text = full_text[block_start:block_end]
        items = _read_items(block_text, offsets, block_start)
        first = _item_starts(block_text)
        intro = block_text[: first[0].start()] if first else block_text
        parts.append(_TextPart(Tier(part_match.group(1)), normalize_whitespace(intro),
                               _page_number_at(offsets, part_match.start() + 1), items))
    return parts


def _item_starts(block_text: str) -> list[re.Match]:
    """The markers that really open an item, in order.

    A line-start "(x)" is not always an item. The Part intro names its own range
    ("items (d) to (o) specified below"), and when that wraps right before a letter
    the port kept only the last match per letter, since the intro always comes first
    (Tender 3 p204). That rule fails the other way round: an item's own roman
    sub-items (i), (ii) come after it, and "(i)" is also a letter - a later item's
    "(i)" sub-item would replace the real item (i) and hand its text to (h).

    Items run in alphabetical order, so the items are the longest run of markers whose
    letters go up one at a time; where two markers could continue the run, the later
    one wins (the intro's mention comes before the item). A roman "(i)" followed by
    "(ii)" is a sub-item even when no item (i) comes after it.
    """
    matches = []
    found = list(_LETTERED_ITEM_PATTERN.finditer(block_text))
    for index, match in enumerate(found):
        following = block_text[match.end():found[index + 1].start() if index + 1 < len(found) else None]
        if not (match.group(1) == "i" and _ROMAN_II.search(following)):
            matches.append(match)
    if not matches:
        return []
    length = [1] * len(matches)
    previous: list[int | None] = [None] * len(matches)
    for index, match in enumerate(matches):
        for earlier in range(index):
            if (ord(matches[earlier].group(1)) == ord(match.group(1)) - 1
                    and length[earlier] + 1 >= length[index]):
                length[index], previous[index] = length[earlier] + 1, earlier
    end = max(range(len(matches)), key=lambda i: (length[i], i))
    chain: list[re.Match] = []
    at: int | None = end
    while at is not None:
        chain.append(matches[at])
        at = previous[at]
    return chain[::-1]


def _read_items(block_text: str, offsets: list[tuple[int, int]], block_offset: int) -> list[_TextItem]:
    starts = _item_starts(block_text)
    items = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(block_text)
        items.append(_TextItem(
            letter=match.group(1),
            text=normalize_whitespace(block_text[match.start():end]),
            page=_page_number_at(offsets, block_offset + match.start() + 1),
        ))
    return items


# ---------------------------------------------------------------- located schedule

@dataclass
class LocatedItem:
    """One schedule item: the fields of `RuleSetItem` that L0 fills, plus the
    citations written in the row that did not resolve to a node."""

    letter: str
    title: str
    part: Tier
    citation: Citation
    clauses: list[Citation] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_rule_set_item(self, status: ItemStatus = ItemStatus.NEEDS_INPUT) -> RuleSetItem:
        """A rule-set item with no template, slots or rules yet (L1-L3 fill those)."""
        return RuleSetItem(letter=self.letter, title=self.title, part=self.part, citation=self.citation,
                           clauses=list(self.clauses), status=status)


@dataclass
class LocatedPart:
    """A Part intro. Its clauses (e.g. the paragraph that says a missing Part A item
    disqualifies) apply to every item in the Part, so they are kept here, not
    copied onto each item."""

    part: Tier
    citation: Citation
    clauses: list[Citation] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    items: list[LocatedItem] = field(default_factory=list)


@dataclass
class Schedule:
    parts: list[LocatedPart]

    @property
    def items(self) -> list[LocatedItem]:
        return [item for part in self.parts for item in part.items]

    def item(self, letter: str) -> LocatedItem:
        for item in self.items:
            if item.letter == letter:
                return item
        raise KeyError(letter)


def _file_name(path: str | None) -> str:
    return Path(path or "").name


def describe(citation) -> str:
    """A parsed citation written back out, for `unresolved` ("Part 4 of the Tender Form")."""
    if not citation.path:
        return f"{citation.number} of the {citation.name}" if citation.number else citation.name
    words = {"part": "Part", "annex": "Annex", "number": "Paragraph", "label": "part"}
    chain = " of ".join(f"{words[kind]} {ident}" for kind, ident in reversed(citation.path))
    return f"{chain} of the {citation.name}"


class _NodeTable:
    """The parser's nodes for a tender, each tagged with the file it came from."""

    def __init__(self, nodes: list[dict]):
        self.nodes = nodes
        self.by_id = {n["node_id"]: n for n in nodes}
        self.children: dict[str, list[dict]] = {}
        for node in nodes:
            if node.get("parent_id"):
                self.children.setdefault(node["parent_id"], []).append(node)
        self.citations = CitationIndex(nodes)

    def subtree(self, node: dict) -> list[dict]:
        out, stack = [], [node]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(reversed(self.children.get(current["node_id"], [])))
        return out

    def quote(self, node: dict) -> str:
        """The node's own text, or for a container (a document, a Part heading with no
        text of its own) the first text inside it - verbatim either way."""
        for current in self.subtree(node):
            if (current.get("text") or "").strip():
                return current["text"].strip()
        return normalize_whitespace(node.get("title") or node.get("doc_name") or "")

    def schedule_part(self, file: str, part: Tier, pages: set[int]) -> dict | None:
        found = [n for n in self.nodes
                 if n["kind"] == "part" and _file_name(n.get("source_file")) == file
                 and n.get("page") in pages and (n.get("number") or "") == part.value
                 and _is_schedule(n)]
        return found[0] if found else None

    def schedule_item(self, file: str, part_node: dict | None, part: Tier, letter: str, page: int) -> dict | None:
        """The item's own node: labelled "(x)" in the right Part of the schedule.
        A direct child of the Part node when there is one, so an item's roman sub-item
        "(i)" is never taken for item (i)."""
        label = f"({letter})"
        found = [n for n in self.nodes
                 if n["kind"] == "subitem" and n.get("label") == label
                 and _file_name(n.get("source_file")) == file and _is_schedule(n)
                 and (n.get("part") or "").split()[-1:] == [part.value]
                 and (part_node is None or n.get("parent_id") == part_node["node_id"])]
        found.sort(key=lambda n: n.get("page") != page)
        return found[0] if found else None

    def resolve(self, text: str, own_scope: set[str]) -> tuple[list[dict], list[str]]:
        """Every node the text cites, in order, without repeats; and the citations
        that resolved to nothing. The schedule mentioning itself is not a clause."""
        resolved: list[dict] = []
        unresolved: list[str] = []
        for citation, nodes in self.citations.resolve_text(text):
            nodes = [n for n in nodes if not any(n["node_id"] == s or n["node_id"].startswith(f"{s}:")
                                                 for s in own_scope)]
            if not nodes:
                written = describe(citation)
                if normalise_name(citation.name) != normalise_name(SCHEDULE_NAME) and written not in unresolved:
                    unresolved.append(written)
                continue
            for node in nodes:
                if all(node["node_id"] != r["node_id"] for r in resolved):
                    resolved.append(node)
        return resolved, unresolved


def _is_schedule(node: dict) -> bool:
    return normalise_name(node.get("doc_name") or "") == normalise_name(SCHEDULE_NAME)


def _schedule_scopes(table: _NodeTable) -> set[str]:
    """The node ids that are the schedule itself: its sub-document, or the Parts of a
    schedule that is not split out as a sub-document."""
    scopes = {n["node_id"] for n in table.nodes if n["kind"] == "subdocument" and _is_schedule(n)}
    if not scopes:
        scopes = {n["node_id"] for n in table.nodes if n["kind"] == "part" and _is_schedule(n)}
    return scopes


def _title(text: str) -> str:
    """The item's text without its marker, cut at the first sentence end or a
    word boundary near `_TITLE_CHARS` - a label for people, not a quote."""
    text = re.sub(r"^\([a-z]\)\s*", "", normalize_whitespace(text))
    sentence = re.split(r"(?<=[.;:])(?<!\b[a-z]\.[a-z]\.)\s", text, maxsplit=1)[0]  # not after "i.e."
    if len(sentence) <= _TITLE_CHARS:
        return sentence
    return sentence[:_TITLE_CHARS].rsplit(" ", 1)[0] + " ..."


def locate(pages, nodes: list[dict], *, data_class: DataClass, root: Path | None = None) -> Schedule:
    """Find the Completeness Check Schedule's Parts and items, and the clauses each cites.

    `pages` are `app.parsing.loader.Page`s for every file of the tender; `nodes` are
    `parse_document` nodes for the same files, each with `source_file` set (see
    `parse_tender`). `root` makes `Citation.file` relative to the project; without it
    the file name is used.
    """
    schedule_pages = find_completeness_check_schedule_pages(pages)
    if not schedule_pages:
        return Schedule(parts=[])
    # A tender has one schedule; if the footer matched in two files, read the first.
    source = schedule_pages[0].source_file
    schedule_pages = [p for p in schedule_pages if p.source_file == source]
    file = _file_name(source)
    relative = str(Path(source).relative_to(root)) if root and Path(source).is_relative_to(root) else file
    page_numbers = {p.page_number for p in schedule_pages}

    table = _NodeTable(nodes)
    own_scope = _schedule_scopes(table)
    paths = {_file_name(p.source_file): p.source_file for p in pages}

    def cite(node: dict | None, page: int, fallback_quote: str) -> Citation:
        quote = table.quote(node) if node else fallback_quote
        return Citation(file=relative, page=(node or {}).get("page") or page,
                        node_id=node["node_id"] if node else None, quote=quote or fallback_quote,
                        data_class=data_class)

    def clause_citation(node: dict) -> Citation:
        source_file = paths.get(_file_name(node.get("source_file")), node.get("source_file") or "")
        path = Path(source_file)
        clause_file = str(path.relative_to(root)) if root and path.is_relative_to(root) else path.name
        return Citation(file=clause_file, page=node["page"], node_id=node["node_id"],
                        quote=table.quote(node) or node["node_id"], data_class=data_class)

    def clauses_of(node: dict | None, fallback_text: str) -> tuple[list[Citation], list[str]]:
        # The row's own text plus its sub-items, which cite clauses of their own.
        text = "\n".join(n.get("text") or "" for n in table.subtree(node)) if node else fallback_text
        resolved, unresolved = table.resolve(text, own_scope)
        return [clause_citation(n) for n in resolved if n.get("page")], unresolved

    parts: list[LocatedPart] = []
    for text_part in _read_schedule_text(schedule_pages):
        part_node = table.schedule_part(file, text_part.part, page_numbers)
        part_clauses, part_unresolved = table.resolve(
            part_node.get("text") or "" if part_node else text_part.intro, own_scope)
        located = LocatedPart(
            part=text_part.part,
            citation=cite(part_node, text_part.page, f"Part {text_part.part.value} {text_part.intro}".strip()),
            clauses=[clause_citation(n) for n in part_clauses if n.get("page")],
            unresolved=part_unresolved,
        )
        for text_item in text_part.items:
            node = table.schedule_item(file, part_node, text_part.part, text_item.letter, text_item.page)
            clauses, unresolved = clauses_of(node, text_item.text)
            located.items.append(LocatedItem(
                letter=text_item.letter,
                title=_title(node["text"] if node and node.get("text") else text_item.text) or text_item.letter,
                part=text_part.part,
                citation=cite(node, text_item.page, text_item.text),
                clauses=clauses,
                unresolved=unresolved,
            ))
        parts.append(located)
    return Schedule(parts=parts)


def parse_tender(pdfs: list[Path]) -> tuple[list, list[dict]]:
    """Load and parse a tender's PDFs: (pages, nodes), each node tagged with the file
    it came from. Slow (the layout model runs on every page)."""
    from app.parsing.layout_document_index import parse_document
    from app.parsing.loader import load_pdf

    pages, nodes = [], []
    for pdf in pdfs:
        file_pages = load_pdf(pdf)
        pages.extend(file_pages)
        for node in parse_document(None, file_pages):
            node["source_file"] = pdf.name
            nodes.append(node)
    return pages, nodes
