"""Hierarchical document index: parse tender documents into a node tree.

A **node** is one addressable piece of a document - a row with an id, a parent, a
kind, and a span of text at a page position. Clause, sub-clause and sub-item are
the same shape, so they share one self-referencing table (adjacency list); the
node_id additionally encodes the path, so the common "everything under X" query
needs no recursion.

Why this exists rather than searching pages with a regex per lookup:

1. **Clause numbering restarts per part.** In TERMS-1, `9` is both Part 1's
   "Certification Requirement" (p.37) and Part 2's "Acceptance" (p.88). The key
   must be (part, number); a number alone cannot identify a clause.
2. **Sub-numbers were being dropped.** The previous resolver parsed "Paragraph
   20.2" to number="20" and searched for a literal "20." - so it landed on ¶20
   (p.47) instead of ¶20.2 (p.49), and the old "100% resolution" metric scored
   that as success because *a* page came back. It measured coverage, not
   correctness.

The distinction that fixes (2): a top-level clause is written "20." with a
trailing period, a sub-clause is written "20.2" without one. Confirmed on real
data (TERMS-1 p.23, p.47).
"""

import re

# Page furniture repeated on every page of the Authority standard terms. Left in place it
# would land inside whichever clause happens to span the page break, and "Page 47
# of 161" would then read as clause text.
_PAGE_HEADER = re.compile(
    r"^[\s]*\n?\s*Ref\.\s*No\.[^\n]*\n\s*Page\s+\d+\s+of\s+\d+\s*\n",
    re.IGNORECASE,
)
_DECORATIVE = re.compile(r"[]+")

# Two shapes of PART heading appear in the corpus: the title on its own line
# ("PART 5 \nMEMORANDUM OF ACCEPTANCE") in the standard-terms documents, and the
# title on the same line after an em-dash ("PART 4 — OFFER TO BE BOUND") in the
# Tender Form (G.F.230) used by all three sample tenders. Missing the second shape
# meant every PART in that form - including PART 4, the signature page - was
# invisible, so its clauses (1/2/3, "Having read the Tender Documents...") had no
# real parent and fell back to whatever scope happened to precede them on the page.
# "3A"/"3B"/"3C" also appear as part numbers in that form's own contents summary.
_PART = re.compile(
    r"(?m)^[ \t]*PART[ \t]+(\d+[A-Z]?|[IVX]+)[ \t]*"
    r"(?:[—\-][ \t]*([A-Z][^\n]*)|[ \t]*\n[ \t]*([A-Z][^\n]*))"
)
# A standalone instrument bound into a document under its own heading - "Annex A to
# the Terms of Tender" followed by "SUB-CONTRACTOR'S UNDERTAKING" - restarts
# numbering on its own, the same way a PART does, but shares neither of the other
# two reset signals: no PART heading precedes it, and it carries the surrounding
# document's own footer (or none, as here) rather than a footer change. Without
# this, Tender 3's embedded Sub-contractor's Undertaking reused clause numbers
# 8/9/11/12 already taken by Part 1 of the Terms of Tender, so a citation to
# "clause 8 of the Terms of Tender" came back ambiguous between "Delivery" (the
# real clause 8) and the Undertaking's own clause 8.
# The negative lookahead excludes the *other* shape this same phrase takes: some
# annexes are their own separately-footed sub-document, where "Annex A to the Terms
# of Tender (Supplement)" is the running header repeated on every page, immediately
# followed by "Page N of M" - that repeat is already handled by the footer-based
# subdocument detection below, and without the exclusion this pattern re-fired on
# every single page of it as a spurious reset.
_ANNEX = re.compile(
    r"(?m)^[ \t]*Annex[ \t]+([A-Z0-9]+)[ \t]+to[ \t]+the\b[^\n]*\n[ \t]*\n?[ \t]*(?!Page\s+\d+\s+of\s+\d+)([A-Z][^\n]*)"
)
# An Authority tender PDF often concatenates several documents, each keeping its own
# footer and its own page numbering: "Compliance Schedule  Page 1 of 6". A reset to
# "Page 1 of N" therefore marks a sub-document boundary, and the text before it
# names that sub-document. This matters because clause numbering restarts at each
# boundary - without it, Tender 3's 366-page combined PDF yields 170 colliding
# (part, number) keys, since a dozen embedded documents each have a clause 1.
_FOOTER = re.compile(r"([A-Z][A-Za-z ()\-]{4,45}?)\s+Page\s+(\d+)\s+of\s+(\d+)")
# "20." + newline/space + Title  -> a top-level clause. The trailing period is what
# separates it from a sub-clause.
_CLAUSE = re.compile(r"(?m)^[ \t]*(\d+)\.[ \t]*\n?[ \t]*([A-Z][^\n]*)")
# "20.2" with no trailing period, followed by body text on the same or next line.
# The body must begin with a capital: a real clause opens a sentence ("20.2 For the
# purposes of…"), whereas a cross-reference that happens to wrap onto a new line
# continues in lowercase ("…under Clause 19.5 \nof the General Conditions…").
# Without this, wrapped citations are parsed as clause starts and collide with the
# genuine clause of the same number.
_SUBCLAUSE = re.compile(r"(?m)^[ \t]*(\d+(?:\.\d+)+)(?:[ \t]+(?=[\"'(]?[A-Z])|[ \t]*\n[ \t]*(?=[\"'(]?[A-Z]))")
_SUBITEM = re.compile(r"(?m)^[ \t]*\(([a-z]{1,2}|[ivx]{1,4})\)[ \t]*\n?")

# A contents page lists many headings with almost no body under each.
_TOC_MIN_HEADINGS = 8
_TOC_MAX_CHARS_PER_HEADING = 200
# How many consecutive footer-less pages a sub-document may absorb before it is
# treated as ended.
_MAX_UNFOOTED_RUN = 3


# "Ref. No. TERMS-1 (December 2022)" - sometimes wrapped between the reference
# and the date. This is the only place the governing ruleset version appears, and
# context.md 7.4 requires it pinned per procurement: TERMS-1 is reissued
# periodically (Dec 2022 / Sept 2024 / June 2025, different page counts) and a
# report must record which dated version governed the tender. Stripping the footer
# without capturing this discards a compliance field.
_REF_NO = re.compile(r"Ref\.\s*No\.\s*([A-Z0-9][A-Z0-9\-]*)\s*\(\s*([^)\n]+?)\s*\)", re.I | re.S)


def extract_page_furniture(text: str) -> dict:
    """Pull identity out of the page furniture before it is stripped.

    Returns {ref_no, rule_version, doc_name, page_no, page_total} - any of which
    may be None. ref_no/rule_version identify the governing ruleset; doc_name is
    the footer label used to tell co-numbered documents apart at retrieval time.
    """
    text = text or ""
    info: dict = {"ref_no": None, "rule_version": None, "doc_name": None, "page_no": None, "page_total": None}

    ref = _REF_NO.search(text)
    if ref:
        info["ref_no"] = normalize_whitespace(ref.group(1))
        info["rule_version"] = normalize_whitespace(ref.group(2))

    footer = _FOOTER.search(text)
    if footer:
        info["doc_name"] = footer.group(1).strip()
        info["page_no"] = int(footer.group(2))
        info["page_total"] = int(footer.group(3))
    else:
        numbering = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", text)
        if numbering:
            info["page_no"] = int(numbering.group(1))
            info["page_total"] = int(numbering.group(2))
    return info


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_page_furniture(text: str) -> str:
    text = _PAGE_HEADER.sub("", text or "")
    return _DECORATIVE.sub("", text)


def looks_like_toc(text: str) -> bool:
    headings = _CLAUSE.findall(text or "")
    if len(headings) < _TOC_MIN_HEADINGS:
        return False
    return len(text) / len(headings) < _TOC_MAX_CHARS_PER_HEADING


def detect_subdocuments(pages) -> list[dict]:
    """Segment a combined PDF into its constituent documents using page footers.

    Returns [{name, first_page, last_page}]. Verified on 09 Schedules.pdf, which
    splits exactly into Price Schedule (p.1-3), Particulars of Goods Schedule
    (4-5), Compliance Schedule (6-11), Information Schedule (12-15) and
    Completeness Check Schedule (16-18).
    """
    segments: list[dict] = []
    unfooted = 0
    for page in pages:
        match = _FOOTER.search(page.native_text or "")
        if not match:
            # Carry a segment across the odd unfooted page (a full-page table, an
            # image), but not across a long run - TERMS-1's own footer carries a
            # version number the pattern can't match, so without this bound the
            # preceding segment swallowed 150 pages of it on Tender 3.
            unfooted += 1
            if segments and unfooted <= _MAX_UNFOOTED_RUN:
                segments[-1]["last_page"] = page.page_number
            continue
        unfooted = 0
        name, position = match.group(1).strip(), int(match.group(2))
        if position == 1 or not segments or segments[-1]["name"] != name:
            segments.append({"name": name, "first_page": page.page_number, "last_page": page.page_number})
        else:
            segments[-1]["last_page"] = page.page_number
    return segments


class DocumentText:
    """One document's pages concatenated, with a map back to page numbers.

    Clauses span page breaks, so offsets have to be document-level; the page map
    turns an offset back into the page a reviewer should be shown.
    """

    def __init__(self, pages):
        self.text = ""
        self._offsets: list[tuple[int, int]] = []  # (char_offset, page_number)
        self.toc_pages: list[int] = []
        # Identity lives in the furniture we are about to strip, so read it first.
        self.furniture_by_page: dict[int, dict] = {}
        self.ref_no: str | None = None
        self.rule_version: str | None = None
        for page in pages:
            if not page.native_text:
                continue
            furniture = extract_page_furniture(page.native_text)
            self.furniture_by_page[page.page_number] = furniture
            if furniture["ref_no"] and not self.ref_no:
                self.ref_no = furniture["ref_no"]
                self.rule_version = furniture["rule_version"]
            cleaned = strip_page_furniture(page.native_text)
            if looks_like_toc(cleaned):
                self.toc_pages.append(page.page_number)
                continue
            self._offsets.append((len(self.text), page.page_number))
            self.text += cleaned + "\n"

    def page_at(self, offset: int) -> int | None:
        found = None
        for start, page_number in self._offsets:
            if start <= offset:
                found = page_number
            else:
                break
        return found


def _marker_positions(text: str) -> list[tuple[int, str, str, str | None]]:
    """All structural markers in document order: (offset, kind, number, title)."""
    marks: list[tuple[int, str, str, str | None]] = []
    for m in _PART.finditer(text):
        # Tagged "part_inline" for now so _drop_referenced_parts_without_content can
        # tell it apart from the long-standing block form below; both become "part"
        # by the time this function returns.
        kind = "part_inline" if m.group(2) is not None else "part"
        marks.append((m.start(), kind, m.group(1), (m.group(2) or m.group(3)).strip()))
    for m in _ANNEX.finditer(text):
        marks.append((m.start(), "annex", m.group(1), m.group(2).strip()))
    marks = _drop_annex_reference_lists(marks)
    for m in _CLAUSE.finditer(text):
        marks.append((m.start(), "clause", m.group(1), m.group(2).strip()))
    for m in _SUBCLAUSE.finditer(text):
        number = m.group(1)
        marks.append((m.start(), "subclause", number, None))
    for m in _SUBITEM.finditer(text):
        marks.append((m.start(), "subitem", m.group(1), None))
    marks = _drop_referenced_parts_without_content(marks)

    marks.sort(key=lambda x: x[0])
    # A clause and a sub-clause can both match at the same offset ("9." vs "9.1");
    # keep the first only, so one position yields one node.
    deduped: list[tuple[int, str, str, str | None]] = []
    for mark in marks:
        if deduped and mark[0] == deduped[-1][0]:
            continue
        deduped.append(mark)
    return _drop_decimals_masquerading_as_subclauses(deduped)


def _drop_referenced_parts_without_content(marks):
    """Reject inline "PART N — TITLE" matches that merely *reference* a part whose
    real content lives elsewhere, rather than starting it.

    The Tender Form's own summary page names PART 1 through PART 3C this way
    ("PART 1 — TERMS OF TENDER", "PART 3A — TECHNICAL SPECIFICATIONS", ...) as a
    table of contents pointing at other documents or at "Attached to this Tender
    Form (if any)" - no clause ever follows before the next boundary. PART 4 on the
    following page uses the identical inline shape but *is* the real section: its
    clauses 1/2/3 ("Having read the Tender Documents...") follow directly. The
    distinction can't be proximity to the previous heading - PART 4 sits closer to
    its predecessor (321 chars) than some of the bogus references do to theirs (556
    chars) - so it has to be "does content actually follow", checked structurally
    the same way `_drop_decimals_masquerading_as_subclauses` does.

    Scoped to the inline shape only: the older "PART N \n TITLE" block shape is
    left untouched, since one of its own real sections (PART 5, Memorandum of
    Acceptance) legitimately has no clause children and must not be dropped by a
    rule aimed at a defect the block shape doesn't have.
    """
    boundaries = sorted(
        offset for offset, kind, _, _ in marks if kind in ("part", "part_inline", "annex")
    )
    content_positions = sorted(
        offset for offset, kind, _, _ in marks if kind in ("clause", "subclause", "subitem")
    )
    kept = []
    for offset, kind, number, title in marks:
        if kind == "part_inline":
            end = next((b for b in boundaries if b > offset), float("inf"))
            if not any(offset < pos < end for pos in content_positions):
                continue
            kind = "part"
        kept.append((offset, kind, number, title))
    return kept


def _drop_annex_reference_lists(marks):
    """Reject `_ANNEX` matches that are really a contents-page listing of names.

    The Tender Form's own index page names every annex/schedule in one paragraph
    ("Annex A to the Terms of Tender \n Annex B to the Terms of Tender \n Annex C to
    the Terms of Tender \n The Appendix - Contact Details \n ..."), which reads as
    two back-to-back _ANNEX matches (each swallowing the next list entry as its
    "title"). A real annex heading is pages away from its neighbour; here they are
    tens of characters apart. Dropping both spurious matches mattered concretely:
    left in place, "Annex C" became the active scope on the Tender Form's summary
    page and silently adopted PART 4's real clauses (1/2/3, "Having read the Tender
    Documents...") as its own children.
    """
    annex_offsets = sorted(offset for offset, kind, _, _ in marks if kind == "annex")
    clustered = {
        offset for i, offset in enumerate(annex_offsets)
        if (i > 0 and offset - annex_offsets[i - 1] < 300)
        or (i + 1 < len(annex_offsets) and annex_offsets[i + 1] - offset < 300)
    }
    return [mark for mark in marks if not (mark[1] == "annex" and mark[0] in clustered)]


def _drop_decimals_masquerading_as_subclauses(marks):
    """Reject decimal numbers in body text that look like sub-clause markers.

    Real examples caught by this on the sample tenders: "93.70" (a CPI index in a
    price-adjustment formula), "0.001 g on a weighing paper" (a lab procedure), and
    "0.3 / 0.6" (rows of a specification table).

    The test is structural rather than a magnitude threshold: a sub-clause is only
    real if its parent clause is itself present in the document. Special Conditions
    has no clause 93, and no document has a clause 0.
    """
    clause_numbers = {number for _, kind, number, _ in marks if kind == "clause"}
    kept = []
    for offset, kind, number, title in marks:
        if kind == "subclause":
            head = number.split(".")[0]
            if head == "0" or head not in clause_numbers:
                continue
        kept.append((offset, kind, number, title))
    return kept


def _ident(doc: "DocumentText", page: int | None) -> dict:
    furniture = doc.furniture_by_page.get(page) or {}
    return {
        "doc_name": furniture.get("doc_name"),
        "ref_no": doc.ref_no,
        "rule_version": doc.rule_version,
    }


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:40] or "doc"


def _unique(node_id: str, seen: dict) -> str:
    """Guarantee node_id uniqueness, suffixing repeats as `…#2`, `…#3`.

    Some documents genuinely repeat a numbered block: a per-line-item schedule form
    reprinted eight times, each page carrying its own "2.4". Those are distinct
    occurrences at distinct pages, so collapsing them onto one id would lose seven
    of them. Keeping them separate also makes a citation to such a number resolve to
    several nodes - which is the honest answer, and lands it in front of a reviewer
    instead of silently picking the first.
    """
    seen[node_id] = seen.get(node_id, 0) + 1
    return node_id if seen[node_id] == 1 else f"{node_id}#{seen[node_id]}"


def derive_doc_id(pages) -> str:
    """The document's id prefix, derived from the source file rather than passed in.

    An earlier version took this as a caller argument, so the same node had a
    different node_id depending on who parsed it ("GLD1:P1:20.2" from one caller,
    "02 Interpretation,:P1:20.2" from another, the latter truncated mid-word by a
    filename[:18] slice). A primary key cannot depend on the caller.
    """
    for page in pages:
        source = getattr(page, "source_file", None)
        if source:
            return _slug(source.split("/")[-1].rsplit(".", 1)[0])
    return "doc"


# Sub-item markers run in two series that overlap at "i": (a)(b)(c)… and (i)(ii)(iii)…
# Which one "(i)" belongs to is decided by what precedes it - after "(h)" it
# continues the alphabet, after "(c)" it opens a nested roman list.
_ROMAN_SEQ = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
              "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx")


def _successors(marker: str) -> set[str]:
    """Markers that may legitimately follow `marker` at the same nesting level.

    Both readings are returned where a marker is ambiguous, so "(i)" is accepted
    as the successor of "(h)" (alphabetic) and "(ii)" as the successor of "(i)"
    (roman) without having to know which series a level is in up front.

    Digit succession ("1" -> "2") is included for `layout_document_index`,
    which (unlike this module's own `_SUBITEM`) does match plain-digit
    sub-items - safe there because every match is gated on starting its own
    layout-classified block, removing the false-positive risk (a CPI formula
    constant, a lab measurement) that keeps digits out of `_SUBITEM` here.
    """
    out: set[str] = set()
    if marker.isdigit():
        out.add(str(int(marker) + 1))
        return out
    if marker.isalpha() and marker.islower():
        if len(marker) == 1:
            out.add("aa" if marker == "z" else chr(ord(marker) + 1))
        elif len(marker) == 2 and marker[1] != "z":
            out.add(marker[0] + chr(ord(marker[1]) + 1))
    if marker in _ROMAN_SEQ:
        index = _ROMAN_SEQ.index(marker)
        if index + 1 < len(_ROMAN_SEQ):
            out.add(_ROMAN_SEQ[index + 1])
    return out


def parse_document(doc_id: str | None, pages) -> list[dict]:
    """Parse one document's pages into a flat list of node dicts (tree via parent_id).

    `doc_id` may be None, in which case it is derived from the source filename -
    that is the form production should use, so a node's id does not depend on which
    caller produced it. Passing one explicitly is for tests that want a short prefix.

    Numbering is scoped to whichever container actually restarts it. A combined PDF
    restarts per embedded sub-document (detected from footers); a single document
    like TERMS-1 restarts per PART. Scoping to the wrong one is what produced
    170 colliding keys on Tender 3, where a dozen embedded documents each have a
    clause 1 but only three PART headings exist in the whole file.
    """
    doc_id = doc_id or derive_doc_id(pages)
    seen_ids: dict[str, int] = {}
    doc = DocumentText(pages)
    if not doc.text.strip():
        return []

    subdocs = detect_subdocuments(pages)
    subdoc_by_page: dict[int, dict] = {}
    if len(subdocs) > 1:
        for index, segment in enumerate(subdocs):
            segment["node_id"] = f"{doc_id}:{index:02d}-{_slug(segment['name'])}"
            for page_number in range(segment["first_page"], segment["last_page"] + 1):
                subdoc_by_page[page_number] = segment

    nodes: list[dict] = [
        {
            "node_id": doc_id,
            "parent_id": None,
            "kind": "document",
            "part": None,
            "number": None,
            "label": None,
            "title": None,
            "page": None,
            "char_start": 0,
            "char_end": len(doc.text),
            "text": "",
            "is_coarse": 0,
            "doc_name": None,
            "ref_no": doc.ref_no,
            "rule_version": doc.rule_version,
        }
    ]

    # Emit a node per detected sub-document so clauses can hang off the right one.
    for segment in subdocs if len(subdocs) > 1 else []:
        nodes.append(
            _node(segment["node_id"], doc_id, "subdocument", None, None, segment["name"],
                  segment["first_page"], 0, 0, "", 0, doc_name=segment["name"],
                  ref_no=doc.ref_no, rule_version=doc.rule_version)
        )

    marks = _marker_positions(doc.text)
    current_part = None
    part_node = None
    clause_node = None
    subclause_node = None
    current_scope = None
    # Open sub-item levels, outermost first: [(marker, node_id)]. Sub-items nest -
    # clause 17 has (a),(b),(c) each containing their own (i),(ii),(iii) - and
    # flattening them collapsed four distinct sub-items onto one id. On Tender 3
    # that produced 117 duplicate node_ids across 306 nodes.
    subitem_stack: list[tuple[str, str]] = []

    for index, (offset, kind, number, title) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(doc.text)
        body = doc.text[offset:end].strip()
        page = doc.page_at(offset)

        # Crossing into a new sub-document resets the numbering context, the same
        # way a new PART does.
        segment = subdoc_by_page.get(page) if subdoc_by_page else None
        if segment and segment.get("node_id") != current_scope:
            current_scope = segment["node_id"]
            part_node = None
            current_part = None
            clause_node = subclause_node = None
            subitem_stack = []

        if kind == "part":
            current_part = f"Part {number}"
            part_node = _unique(f"{doc_id}:P{number}", seen_ids)
            # Parts and footer-detected sub-documents are alternative scoping
            # signals, so the most recent one wins. Without this, a sub-document
            # whose footer simply stopped matching keeps extending and swallows the
            # PART-structured tail of a combined PDF - on Tender 3 the "Annex B"
            # segment absorbed 150 pages of TERMS-1 from p.236 onward.
            current_scope = None
            clause_node = subclause_node = None
            subitem_stack = []
            nodes.append(_node(part_node, doc_id, "part", current_part, number, title, page, offset, end, "", 0,
                               **_ident(doc, page)))
            continue

        if kind == "annex":
            current_part = f"Annex {number}"
            part_node = _unique(f"{doc_id}:ANNEX-{number}", seen_ids)
            # Same precedence rule as PART: whichever reset signal (sub-document
            # footer, PART, or annex heading) appeared most recently wins.
            current_scope = None
            clause_node = subclause_node = None
            subitem_stack = []
            nodes.append(_node(part_node, doc_id, "annex", current_part, number, title, page, offset, end, "", 0,
                               **_ident(doc, page)))
            continue

        # Scope precedence: sub-document (combined PDFs) > PART/annex > the document.
        parent_for_clause = current_scope or part_node or doc_id

        if kind == "clause":
            clause_node = _unique(f"{parent_for_clause}:{number}", seen_ids)
            subclause_node = None
            subitem_stack = []
            nodes.append(
                _node(clause_node, parent_for_clause, "clause", current_part, number, title, page, offset, end, body, 1,
                      **_ident(doc, page))
            )
        elif kind == "subclause":
            parent = clause_node or parent_for_clause
            subclause_node = _unique(f"{parent_for_clause}:{number}", seen_ids)
            subitem_stack = []
            nodes.append(
                _node(subclause_node, parent, "subclause", current_part, number, None, page, offset, end, body, 1,
                      **_ident(doc, page))
            )
        elif kind == "subitem":
            # Find the deepest open level this marker continues; anything below it
            # is closed. If it continues nothing, it opens a nested level - that is
            # what tells "(a)(b)(c) then (i)" apart from "(g)(h) then (i)".
            depth = next(
                (d for d in range(len(subitem_stack) - 1, -1, -1)
                 if number in _successors(subitem_stack[d][0])),
                None,
            )
            if depth is None:
                parent = (subitem_stack[-1][1] if subitem_stack
                          else subclause_node or clause_node or parent_for_clause)
                subitem_stack.append((number, _unique(f"{parent}:({number})", seen_ids)))
            else:
                del subitem_stack[depth + 1:]
                parent = (subitem_stack[depth - 1][1] if depth
                          else subclause_node or clause_node or parent_for_clause)
                subitem_stack[depth] = (number, _unique(f"{parent}:({number})", seen_ids))
            nodes.append(
                _node(
                    subitem_stack[-1][1], parent, "subitem", current_part, None, None, page, offset, end, body, 0,
                    label=f"({number})", **_ident(doc, page),
                )
            )

    return nodes


def _node(node_id, parent_id, kind, part, number, title, page, start, end, text, is_coarse, label=None,
          doc_name=None, ref_no=None, rule_version=None) -> dict:
    return {
        # Footer identity travels with the node: doc_name distinguishes co-numbered
        # documents inside one PDF at retrieval time, and ref_no/rule_version pin
        # which dated edition of the ruleset governed this tender (context.md 7.4).
        "doc_name": doc_name,
        "ref_no": ref_no,
        "rule_version": rule_version,
        "node_id": node_id,
        "parent_id": parent_id,
        "kind": kind,
        "part": part,
        "number": number,
        "label": label,
        "title": title,
        "page": page,
        "char_start": start,
        "char_end": end,
        "text": text,
        "is_coarse": is_coarse,
    }
