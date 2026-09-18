"""Layout-based document index: same node schema as `document_index.parse_document`,
but block boundaries and hierarchy come from PyMuPDF-layout's classified blocks
instead of a single regex scan over the flattened page text.

Validated against hand-built ground truth (see `plan.md`, "Structural parser
comparison: PyMuPDF vs. Docling") on two real sections of Tender 1:
clause 13 of `04 Terms of Tender (Supplement).pdf` (58 nodes) and pages 1-2 of
`01 Tender Form (G.F.230).pdf` (PART/clause/Notes structure) - 100% recall,
kind correctness, and hierarchy correctness on both, average node-length ratio
0.991 against ground truth once paragraph-run absorption was generalized to
absorb a marker's *entire* leading run of trailing plain blocks, not just the
first one.

Reuses `document_index`'s own regex vocabulary and subitem-succession logic
directly rather than reinventing marker classification, which is already
tested against three real tenders - this module only changes HOW text is
segmented into blocks (PyMuPDF-layout instead of one flat-text regex scan) and
HOW a node's own span is determined (its own block plus any immediately
trailing plain blocks, absorbed up to the next real marker, instead of
"regex-match position to next regex-match position").

Two categories of marker, exactly as in `document_index`:
  - **Categorical** (part/annex/clause/subclause): a fixed, known rank in this
    document family regardless of position - a PART always contains clauses.
    Nested by category (current_part/current_clause tracking), never by x0.
  - **Positional** (subitem, i.e. the letter/roman/digit markers below clause/
    subclause level): these have no fixed rank on their own - clause 13 nests
    roman under letter, another clause elsewhere nests the reverse - so their
    relative depth is resolved via `_successors()` (does this marker continue
    an already-open level?), exactly as `document_index` already does. No x0
    needed here either; the marker-continuation check is what determines
    depth, which is also why this module needs no float-jitter tolerance band
    the earlier prototype scripts needed.

Digit subitems (`(1)(2)(3)...`) are supported here in a way the flat-text
regex scan could not safely do: `document_index._SUBITEM` deliberately never
matches plain digits, because a digit in parentheses appearing anywhere in a
wall of prose is usually not a real subitem (a CPI formula constant, a lab
measurement) - see `_drop_decimals_masquerading_as_subclauses` for the same
problem one level up. Gating on "is this the first text of its own
layout-classified block" removes that ambiguity: a digit marker that opens its
own list-item/text block is reliably a real subitem, since prose numbers don't
start their own paragraph.
"""

import re
from dataclasses import dataclass
from types import SimpleNamespace

import fitz

from app.parsing.document_index import (
    _ANNEX,
    _SUBCLAUSE,
    _ident,
    _successors,
    _unique,
    derive_doc_id,
    detect_subdocuments,
    extract_page_furniture,
    looks_like_toc,
)

# Same shape as document_index._SUBITEM, plus plain digits - safe here because
# every match is already gated on being the start of its own layout block.
# Second alternative: `10 Non-collusive Tendering Certificate.pdf` nests its
# roman-numeral items under (b)/(c) as bare "i)", "ii)", ... - no opening
# parenthesis - confirmed in the source PDF's own raw text (fitz), not a
# layout-model artifact. Restricted to roman numerals only (never plain
# letters or digits bare) since "i)"/"ii)" is unambiguous but a bare
# "a)"/"1)" is common as ordinary prose punctuation elsewhere in the corpus.
_SUBITEM_WITH_DIGITS = re.compile(r"^(?:\(([a-z]{1,2}|[ivx]{1,4}|\d+)\)|([ivx]{1,4})\))[ \t]*")

# Looser than document_index._PART: that pattern requires either an em-dash
# ("PART 4 — TITLE") or a literal newline before the title ("PART 5 \n TITLE"),
# because on a flat-text scan that's the only way to tell "this is one heading"
# from "this is just the word PART followed by unrelated text". Neither survives
# here: MarkdownGenerator._group_text() joins a block's constituent lines with a
# single space, so a genuine two-line block heading like "PART 1 \n TERMS OF
# TENDER" arrives as "PART 1 TERMS OF TENDER" - no dash, no newline - and the
# original pattern silently fails to match it. Not needed here regardless: the
# layout block itself already establishes "these belong to one heading" (that's
# what merged them into a single classified block in the first place), so this
# module doesn't need the dash/newline signal to tell them apart from unrelated
# text the way the flat-text scan does.
#
# Second alternative: the Schedules family (`09 Schedules.pdf`) uses a
# completely different convention for its own internal Parts - title-case,
# single-letter ("Part A", "Part B", "Part C"), never all-caps and never
# numbered. Confirmed real: without this, "Part B"'s own clean, correctly-
# isolated section-header block was never recognized as a marker at all, so
# the entire next Part's intro paragraph silently absorbed into whatever the
# previous item was (items (d) and (l) both ballooned to ~5x their true
# length this way). Case-sensitive "Part" vs "PART" means the two
# alternatives never collide; `(?![a-zA-Z])` after the letter guards against
# ever matching a real word like "Party" or "Parts".
_PART_LAYOUT = re.compile(
    r"^PART[ \t]+(?P<num>\d+[A-Z]?|[IVX]+)[ \t]*(?:[—\-][ \t]*)?(?P<title>[A-Z][^\n]*)?"
    # Annex A to the Terms of Tender numbers its Parts "Part IA", "Part IB" - a
    # roman numeral with a letter - which the single letter never matched, so
    # both Parts read as plain text of the Annex.
    r"|^Part[ \t]+(?P<letter>[IVX]{1,4}[A-H]|[A-Z])(?![a-zA-Z])[ \t]*(?:[—\-][ \t]*)?(?P<title2>[A-Z][^\n]*)?"
    # Third alternative: `09 Schedules.pdf`'s Information Schedule names its
    # own sub-tables "Table A - Information required in..." / "Table B -
    # ..." - the same role as a "Part" heading (opens a new scope, resets
    # subitem nesting) under a different keyword. Confirmed real: without
    # this, the heading text absorbs into whatever preceded it instead of
    # becoming its own node, and the table's own (a)(b)(c) rows end up
    # parented to that unrelated preceding node instead of to the table.
    r"|^Table[ \t]+(?P<tletter>[A-Z])(?![a-zA-Z])[ \t]*(?:[—\-][ \t]*)?(?P<title3>[A-Z][^\n]*)?"
)

# Looser than document_index._CLAUSE: that pattern requires the clause's own
# text to start with a capital letter, specifically to reject a line-wrapped
# citation continuation ("...under Clause 19.5 \nof the General Conditions...")
# that happens to start a new line with a bare number. That protection isn't
# needed here - a genuine mid-sentence wrap never starts its own PyMuPDF-layout
# block, since layout groups by paragraph proximity, not by literal newline.
# Confirmed real without it: PART 4's clause "3." on the Tender Form opens with
# a lowercase parenthetical ("3.  (Applicable only where...)"), which the
# capital-letter requirement would silently drop.
#
# The `(?!\d)` after the period is still required, though: without it, "20.1"
# (a real subclause) matches this pattern too, reading "20" as the clause
# number and ".1 Notwithstanding..." as its title - confirmed real on clause
# 20's own subclauses, which all collided onto one "clause 20" id before this
# was added. A genuine clause never has a digit immediately after its period.
_CLAUSE_LAYOUT = re.compile(r"^(\d+)\.(?!\d)[ \t]*\n?[ \t]*(.*)", re.S)


def _expected_next_subclause(number: str | None) -> str | None:
    """'7.3' -> '7.4'. None if `number` isn't a dotted clause.subclause number."""
    if not number or "." not in number:
        return None
    major, _, minor = number.rpartition(".")
    return f"{major}.{int(minor) + 1}" if minor.isdigit() else None


# Citation keyword immediately before a candidate marker means it's a
# cross-reference to another clause ("...pursuant to Paragraph 7.4 above..."),
# not this block's own marker - see _find_displaced_marker.
_CITATION_PRECEDER = re.compile(r"(?i)(paragraph|clause|sub-paragraph|subparagraph|sub-clause|subclause)\s*$")


def _find_displaced_marker(text: str, candidate: str, parenthesized: bool) -> bool:
    """Does `text` contain `candidate` as a standalone token within roughly its
    own first sentence, not immediately preceded by a citation keyword?

    Confirmed real: MarkdownGenerator._group_text() occasionally reorders a
    block's own leading marker to land ~11-13 words into its first sentence
    instead of at the front - e.g. clause 7.4's block reads "A Tenderer's
    Tender will not be considered further if the Tenderer 7.4 expressly
    indicates...". _classify_marker() only ever checks position 0, so these
    blocks read as kind=None and silently absorb into the previous node
    (confirmed on clauses 7.4, 9.3, and subitem 10.1(g), which then also
    mis-parented (h)-(l) as children of (f) since (g) never reached
    subitem_stack). The search window is bounded to before the first '. ' or
    160 chars, whichever is shorter - every confirmed case landed within the
    first ~13 words, so this is not a generic scan of the whole block, and
    the citation-keyword guard keeps a genuine forward cross-reference
    ("see Paragraph 7.4 below") from being mistaken for the marker itself.

    A second guard rejects a match immediately preceded by a digit or ")"
    with no space - confirmed real on `20.2(f)`, whose own text legitimately
    cites "Paragraphs 20.1(a) to 20.1(g) above": the keyword guard alone
    missed it, since "Paragraph" isn't the word immediately before "(g)"
    here - "20.1" is. A standalone marker is never glued directly onto a
    preceding number this way; a nested citation like "20.1(g)" always is.
    """
    window = text[:160]
    period = window.find(". ")
    if period != -1:
        window = window[:period]
    pattern = re.escape(f"({candidate})") if parenthesized else r"\b" + re.escape(candidate) + r"\b"
    m = re.search(pattern, window)
    if not m:
        return False
    preceding = window[: m.start()]
    if _CITATION_PRECEDER.search(preceding):
        return False
    if preceding and preceding[-1] in ")0123456789":
        return False
    return True


_MARKER_AT_START = re.compile(r"^\(([a-z]{1,2}|[ivx]{1,4}|\d+)\)")


def _split_table_row_markers(text: str) -> list[str]:
    """Split a PyMuPDF-layout `table`-class block into one piece per
    row/field marker it fuses together.

    Confirmed real on `09 Schedules.pdf`'s Compliance/Information/
    Completeness Check Schedules: unlike a `list-item` block (one marker,
    one block - the normal case everywhere else in this module), a `table`
    block holds an entire table's cells as one flat string with no visual
    paragraph gap between rows, e.g. "(a) Name of the Tenderer (b) Contact
    details (i) telephone number: (ii) facsimile number: (iii) email
    address:" as a *single* raw block. Every marker after the first is
    therefore invisible to the rest of this module (which only ever
    classifies a block's own leading text) and silently vanishes into
    whichever node opened before the table.

    Walks a local marker stack exactly the way the main loop's
    `subitem_stack` does (new nested level if the next marker isn't a
    successor of anything open, otherwise pop/replace at the matching
    depth), splitting the text at each successor's position. Reuses the
    same citation-reference guard `_find_displaced_marker` relies on
    (rejecting a match preceded by a citation keyword or glued directly onto
    a preceding digit/")") so a genuine in-cell citation like "Paragraph
    13(a)(i) of the Terms of Tender (Supplement)" is never mistaken for a
    real row boundary - confirmed necessary on Table A, whose own row (a)
    cites exactly that paragraph inline.
    """
    m = _MARKER_AT_START.match(text)
    if not m:
        return _split_numbered_table_rows(text)
    stack = [m.group(1)]
    starts = [0]
    pos = m.end()
    while True:
        best = None
        for cand in {c for level in stack for c in _successors(level)}:
            for cm in re.finditer(r"\(" + re.escape(cand) + r"\)", text[pos:]):
                start = pos + cm.start()
                preceding = text[max(0, start - 40):start]
                if _CITATION_PRECEDER.search(preceding):
                    continue
                if preceding and preceding[-1] in ")0123456789":
                    continue
                if best is None or start < best[0]:
                    best = (start, cand)
                break
        if best is None:
            break
        start, marker = best
        starts.append(start)
        depth = next((i for i in range(len(stack) - 1, -1, -1) if marker in _successors(stack[i])), None)
        if depth is None:
            stack.append(marker)
        else:
            stack[:] = stack[:depth + 1]
            stack[depth] = marker
        pos = start + len(f"({marker})")
    if len(starts) > 1:
        return [
            text[start:(starts[i + 1] if i + 1 < len(starts) else len(text))].strip()
            for i, start in enumerate(starts)
        ]
    return _split_numbered_table_rows(text)


# A flat "1.* Place of Origin  2.* Name of Manufacturer ... 6. # Packing
# (for the plant only) ... 14. pH of 0.5% (w/v) ..." row list - `09
# Schedules.pdf`'s Particulars of Goods Schedule table, confirmed real: no
# nesting, no parentheses, an optional single annotation glyph (*/#/^)
# between the number and its row text - sometimes glued to the period
# ("1.*"), sometimes its own space-separated token ("6. #"). The final
# `(?!\d)` (rather than requiring a capital letter next, which "14. pH of
# ..." fails - "pH" starts lowercase) is what rules out a decimal like
# row 14's own "0.5%" being misread as a new row "0.": a genuine row number
# is never immediately followed by another digit.
_NUMBERED_ROW = re.compile(r"(?<![\d.])(\d{1,2})\.[ \t]*(?:[*#^][ \t]*)?(?!\d)")


def _split_numbered_table_rows(text: str) -> list[str]:
    starts = [m.start() for m in _NUMBERED_ROW.finditer(text)]
    if len(starts) < 2:
        return [text]
    pieces = []
    if starts[0] > 0:
        pieces.append(text[:starts[0]].strip())
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        pieces.append(text[start:end].strip())
    return [p for p in pieces if p]


# A bare subitem marker with zero content of its own, immediately followed by
# its first nested child - "(a) (i) (for Paper-based Tendering)..." - arrives
# as ONE raw PyMuPDF-layout block, not two, because there's no visual gap for
# the layout model to split on (unlike every other case in this module, where
# a marker's own body text separates it from whatever follows). Confirmed
# real on `3.3(a)(i)` and Supplement `11(b)(i)`: both landed as a single
# block with the nested marker glued directly onto the bare parent, silently
# absorbing the child's entire content into the parent's own text and losing
# the child as a node entirely.
_BARE_MARKER_THEN_NESTED = re.compile(
    r"^(\([a-z]{1,2}\))[ \t]*(\((?:[a-z]{1,2}|[ivx]{1,4}|\d+)\)[ \t]*.*)$", re.S
)


def _split_leading_bare_marker(text: str) -> list[str]:
    """Split `text` into [outer, inner] if it opens with a bare marker glued
    directly onto a nested one, else return [text] unchanged.

    Guarded two ways, both confirmed necessary by real cases:

    1. _successors(): only split when the second marker is NOT a valid
       same-level continuation of the first (e.g. "(a)(i)" splits, since "i"
       is never a successor of "a" - but "(h)(i)" would not, since "i"
       legitimately continues an a-z run after "h").

    2. Inline enumeration: "(e) (i) the Tenderer; or (ii) a related
       person...; or (iii) a director...has been convicted" (clause 20.1(e))
       has the exact same shape as a real nested list, but is one sentence
       enumerating alternatives, not a genuine sub-list - confirmed by the
       fact that (ii)/(iii) are also inline in this same block, whereas in
       both real cases (3.3(a)(i), Supplement 11(b)(i)) the next marker in
       sequence is a wholly separate block and never appears inside this
       one. So: don't split if the inner marker's own successor shows up
       anywhere later in the text - that means the "list" never actually
       breaks into its own blocks, i.e. it isn't one.
    """
    m = _BARE_MARKER_THEN_NESTED.match(text)
    if not m:
        return [text]
    outer_marker = m.group(1)[1:-1]
    inner_marker = re.match(r"\((.+?)\)", m.group(2)).group(1)
    if inner_marker in _successors(outer_marker):
        return [text]
    if any(f"({s})" in m.group(2) for s in _successors(inner_marker)):
        return [text]
    return [m.group(1), m.group(2)]


# "Notes:  (1)   ^ Please tick..." / "Notes: (1) In preparing this Price
# Schedule..." - a "Notes:" heading with note (1)'s own text glued directly
# onto it, no visual gap for the layout model to split on (same root cause
# as `_BARE_MARKER_THEN_NESTED` - the heading has no content of its own to
# separate it from what follows). Confirmed real across every Part of
# `09 Schedules.pdf`'s Price/Compliance Schedules: without this, "Notes:"
# and note (1) both silently absorb into whichever subitem preceded them.
# The notes are numbered with letters or roman numerals as often as digits -
# "Notes: (i) Please use separate sheet(s)..." under every table of the
# Particulars of Goods Schedule - and those were never split off.
_NOTES_HEADING_THEN_MARKER = re.compile(r"^(Notes?:)[ \t]*(\((?:\d+|[a-z]{1,2}|[ivx]{1,4})\)[ \t]*.*)$", re.S)


def _split_notes_heading(text: str) -> list[str]:
    m = _NOTES_HEADING_THEN_MARKER.match(text)
    return [m.group(1), m.group(2)] if m else [text]


# A run-in list: sub-items written inside one sentence rather than set out as
# their own paragraphs - "(c) in the event of (i) a claim ...; (ii) the
# Authority having grounds ...; or (iii) an agreement ...", "Contact details
# (i) telephone number (ii) facsimile number (iii) email address". The layout
# model has no gap to split on, so the whole list arrives inside its parent's
# block and only the parent was ever a node. The answer keys address each such
# sub-item on its own (confirmed on the Terms of Tender's 9.1, 14.1 and 20.1(c),
# the Special Conditions' 6(g) and 12(d), the Information Schedule's contact and
# insurance rows and the Innovative Suggestion Schedule's notes).
#
# A list is only recognised from its FIRST marker - "(a)", "(i)" or "(1)" -
# followed later in the same text by that marker's successor, so a lone "(b)"
# or a citation of one item never splits. The guards that keep a citation from
# splitting are the same ones the table split uses (a citation keyword before
# the marker, or the marker glued onto a number), widened to plural keywords
# ("Paragraphs (a) and (b)"); a digit marker after a number word ("two (2)
# weeks") is a quantity, not an item.
_RUN_IN_OPENERS = ("a", "i", "1")
_RUN_IN_PRECEDER = re.compile(
    r"(?i)(?:paragraphs?|clauses?|sub-?paragraphs?|sub-?clauses?|items?|sub-?items?|rows?|notes?|"
    r"sections?|parts?|tables?|annex(?:es)?|appendix|schedules?)\s*$"
)
_NUMBER_WORD = re.compile(
    r"(?i)\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety|hundred|thousand)(?:-\w+)?\s*$"
)
# Shortest own text a run-in item can have: "(a) and (b)" is a citation of two
# items, not a list whose first item says "and".
_RUN_IN_MIN_TEXT = 3


def _run_in_marker_at(text: str, marker: str, start: int) -> int | None:
    """Position of the first "(marker)" at or after `start` that reads as an
    item marker rather than a citation, or None."""
    for m in re.finditer(r"\(" + re.escape(marker) + r"\)", text[start:]):
        at = start + m.start()
        preceding = text[max(0, at - 40):at]
        if preceding and preceding[-1] in ")0123456789":
            continue
        if _RUN_IN_PRECEDER.search(preceding):
            continue
        if marker.isdigit() and _NUMBER_WORD.search(preceding):
            continue
        return at
    return None


def _run_in_chain(text: str, start: int) -> list[int]:
    """Start positions of the first run-in list at or after `start`: an opener
    and each successor after it, in order. [] when there is no list."""
    candidates = sorted(
        (at, marker) for marker in _RUN_IN_OPENERS
        if (at := _run_in_marker_at(text, marker, start)) is not None
    )
    for at, marker in candidates:
        chain = [at]
        pos, current = at + len(marker) + 2, marker
        while True:
            found = sorted(
                (nxt, succ) for succ in _successors(current)
                if (nxt := _run_in_marker_at(text, succ, pos)) is not None
            )
            if not found:
                break
            nxt, current = found[0]
            chain.append(nxt)
            pos = nxt + len(current) + 2
        if len(chain) < 2:
            continue
        ends = chain[1:] + [len(text)]
        bodies = [re.sub(r"^\([^)]*\)", "", text[s:e]).strip(" \t\n;,") for s, e in zip(chain, ends)]
        if all(len(b) >= _RUN_IN_MIN_TEXT and b.lower() not in ("and", "or", "to", "and/or") for b in bodies):
            return chain
    return []


def _split_run_in_items(text: str) -> list[tuple[str, bool]]:
    """Split `text` at each item of every run-in list inside it, nested lists
    included. Each piece is (text, opens_list): True for a list's first item,
    which nests under the piece before it rather than continuing whatever list
    is open - "(i)" after "(h)" would otherwise read as "(h)"'s successor."""
    own = _SUBITEM_WITH_DIGITS.match(text) or re.match(r"^\d+(?:\.\d+)*\.?[ \t]", text)
    chain = _run_in_chain(text, own.end() if own else 0)
    if not chain:
        return [(text, False)]
    pieces: list[tuple[str, bool]] = []
    head = text[:chain[0]].strip()
    if head:
        pieces.append((head, False))
    for i, start in enumerate(chain):
        end = chain[i + 1] if i + 1 < len(chain) else len(text)
        for j, (piece, opens) in enumerate(_split_run_in_items(text[start:end].strip())):
            pieces.append((piece, opens or (i == 0 and j == 0)))
    return pieces


def _split_block(raw_text: str, class_name: str) -> list[str]:
    """The one entry point every raw layout block goes through before
    classification - chains all the block-splitting heuristics above."""
    if class_name == "table":
        return _split_table_row_markers(raw_text)
    pieces = []
    for piece in _split_notes_heading(raw_text):
        pieces.extend(_split_leading_bare_marker(piece))
    return pieces


def _detect_running_furniture(blocks_by_page: dict, scope_of_page) -> dict[str, set[str]]:
    """Text that repeats verbatim on 2+ pages within the same scope (a
    subdocument segment, or the whole document if there are none) and never
    classifies as a real marker - a running page masthead/title repeated by
    the source PDF itself, not body content.

    Restricted to blocks that already classify as kind=None, so a
    genuinely repeated *marker* (e.g. "Part A", reused by name across four
    of `09 Schedules.pdf`'s five sub-schedules) is never at risk - markers
    are classified independently of this set and this function never sees
    them as candidates.

    Confirmed real on `09 Schedules.pdf`: the section title ("Price
    Schedule") and the instruction line ("(To be completed and returned
    together with the tender submission)") repeat on every page of that
    sub-schedule. Neither is a page-header/footer the layout model itself
    recognizes (those are already excluded in `_layout_blocks`) - they are
    ordinary section-header/text blocks that happen to repeat, and without
    this, each repeat absorbs into whatever node preceded it on the
    previous page, inflating it by the masthead's own length every time the
    page turns.
    """
    texts_by_scope: dict[str, dict[str, set[int]]] = {}
    for page_number, blocks in blocks_by_page.items():
        scope = scope_of_page(page_number)
        seen = texts_by_scope.setdefault(scope, {})
        for _, class_name, raw_text, _bbox, _label in blocks:
            for piece in _split_block(raw_text, class_name):
                if _classify_marker(piece)[0] is None:
                    seen.setdefault(piece, set()).add(page_number)
    return {
        scope: {text for text, pages_ in seen.items() if len(pages_) >= 2 and len(text) >= 8}
        for scope, seen in texts_by_scope.items()
    }


_model = None
_fitz_docs: dict[str, fitz.Document] = {}


def _get_model():
    global _model
    if _model is None:
        from pymupdf.layout import DocumentLayoutAnalyzer

        _model = DocumentLayoutAnalyzer.get_model()._model
    return _model


def _fitz_page(source_file: str, page_number: int):
    doc = _fitz_docs.get(source_file)
    if doc is None:
        doc = fitz.open(source_file)
        _fitz_docs[source_file] = doc
    return doc[page_number - 1]


def _reading_lines(items: list[tuple[str, list[float]]]) -> list[list[tuple[str, list[float]]]]:
    """Group a block's text items into visual lines, top to bottom, each left to right.

    Replaces MarkdownGenerator._group_text's ordering, which sorts by
    `(y0 // 5, x0)`: two items on the same line whose tops straddle a 5-point
    bucket boundary land in different "lines". A drop capital or a marker set a
    fraction of a point lower than its line's text then reads after the whole
    line - "(f) The information ..." came out as "he information ... of the (f) T
    Information Schedule", so the item never opened with its own marker. That is
    the same mis-ordering `_find_displaced_marker` works around after the fact.
    Here an item joins the current line when its vertical centre is within half
    a line height of the line's own centre, so jitter of a point or two (or a
    raised superscript) no longer splits a line, while the next line of text,
    a full line height below, still starts a new one.
    """
    def centre(bbox):
        return (bbox[1] + bbox[3]) / 2

    valid = sorted(((t.strip(), b) for t, b in items if t and t.strip()), key=lambda it: centre(it[1]))
    lines: list[list[tuple[str, list[float]]]] = []
    for text, bbox in valid:
        if lines:
            line = lines[-1]
            line_centre = sum(centre(b) for _, b in line) / len(line)
            height = max([b[3] - b[1] for _, b in line] + [bbox[3] - bbox[1]])
            if abs(centre(bbox) - line_centre) <= height / 2:
                line.append((text, bbox))
                continue
        lines.append([(text, bbox)])
    return [sorted(line, key=lambda it: it[1][0]) for line in lines]


_STANDALONE_MARKER = re.compile(r"^[*^#]*\((?:[a-z]{1,2}|[ivx]{1,4}|\d+)\)$")


def _split_at_marker_lines(lines):
    """Split one layout block into several where later lines open with their own
    list marker in the same column as the block's first marker.

    The layout model sometimes merges consecutive list items into a single
    `text` block when nothing but the marker column separates them: "(i) Where
    ... (j) Where ... (k) Where ..." came back as one block, so (j) and (k) never
    became nodes and (i) swallowed both. Only this module's first-text-of-block
    rule classifies markers, so each item has to start its own piece.

    Two conditions keep an inline enumeration ("(i) the Tenderer; or (ii) a
    related person") from being split: the marker must be a text item on its
    own (a hanging marker set apart from its paragraph, not a token inside a
    sentence), and it must be the first item of its line at the x position of
    the block's opening marker (within 2 points).
    """
    if len(lines) < 2 or not _STANDALONE_MARKER.match(lines[0][0][0]):
        return [lines]
    column = lines[0][0][1][0]
    pieces = [[lines[0]]]
    for line in lines[1:]:
        text, bbox = line[0]
        if _STANDALONE_MARKER.match(text) and abs(bbox[0] - column) <= 2:
            pieces.append([line])
        else:
            pieces[-1].append(line)
    return pieces


def _join_lines(lines) -> str:
    return " ".join(text for line in lines for text, _ in line)


# How much of a layout `table` block a detected grid must cover before its rows
# are trusted as that block's row boundaries.
_GRID_MIN_OVERLAP = 0.5
_GRID_CACHE: dict[tuple[str, int], list] = {}


def _page_grids(source_file: str, page_number: int, page):
    """Detected grids for one page, keeping only those that can describe a
    block: at least two rows, and a readable bbox.

    A detected table can carry no cells at all, and PyMuPDF then raises
    `ValueError: min() iterable argument is empty` from `Table.bbox` rather
    than reporting an empty table - so every grid is probed once, here, and a
    grid that cannot answer for its own geometry is dropped instead of being
    re-probed (and re-raised) at each block that overlaps it."""
    key = (source_file, page_number)
    if key not in _GRID_CACHE:
        usable = []
        try:
            for table in page.find_tables().tables:
                try:
                    if table.row_count >= 2 and len(table.bbox) == 4 and table.rows:
                        usable.append(table)
                except (ValueError, TypeError, IndexError):
                    continue
        except Exception:
            usable = []
        _GRID_CACHE[key] = usable
    return _GRID_CACHE[key]


def _grid_for_block(source_file: str, page_number: int, page, group_bbox):
    """The detected grid covering a layout `table` block, or None.

    `pymupdf-layout` hands an entire table back as ONE group whose cells are
    already flattened into one string, so the row structure has to be
    reconstructed. `_split_table_row_markers` does that from the text alone by
    walking the markers it can see, which holds while every row opens with a
    marker and fails two ways when they don't: a markerless row is invisible,
    and a marker the flattened reading order places away from its own row's
    start splits in the wrong place - confirmed on the Information Schedule's
    Table B, where row (g) absorbed the opening of row (h) and row (h) then
    began mid-sentence.

    Returns None for a borderless table - the Attachment to the Technical
    Specifications' glossary yields no rows under the default line-based
    strategy - and the caller then falls back to the text-only split.
    """
    rect = fitz.Rect(*group_bbox)
    if rect.is_empty:
        return None
    best, best_share = None, 0.0
    for table in _page_grids(source_file, page_number, page):
        overlap = rect & fitz.Rect(*table.bbox)
        if overlap.is_empty:
            continue
        share = overlap.get_area() / rect.get_area()
        if share > best_share:
            best, best_share = table, share
    if best is None or best_share < _GRID_MIN_OVERLAP:
        return None
    return best


def _table_row_pieces(items, table) -> list:
    """One piece per grid row, each row read cell by cell in column order.

    Reading a row cell by cell rather than by vertical position is what puts a
    row's marker at its own start: `_reading_lines` orders a whole block by
    vertical centre, so a marker set lower than the first line of the cell
    beside it reads after that line ("Business profile information of the
    Tenderer including (h) the number and location..." for Table B's row (h)).
    Within a cell the same vertical grouping is still what orders the text.

    Only the row and cell BOUNDARIES come from the grid; every piece's text is
    still the layout model's own items, so the text extraction path and every
    character count are unchanged.
    """
    def centre(bbox):
        return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    try:
        rows = [(row.bbox[1], row.bbox[3], [c for c in row.cells if c]) for row in table.rows]
    except (ValueError, TypeError, IndexError):
        return []
    if not rows or not all(cells for _, _, cells in rows):
        return []
    placed = [[[] for _ in cells] + [[]] for _, _, cells in rows]  # a trailing bucket per row for gutter items
    leftovers = []
    for text, bbox in items:
        x, y = centre(bbox)
        index = next((i for i, (top, bottom, _) in enumerate(rows) if top <= y < bottom), None)
        if index is None:
            leftovers.append((text, bbox))
            continue
        cells = rows[index][2]
        cell = next((j for j, c in enumerate(cells) if c[0] <= x < c[2] and c[1] <= y < c[3]), None)
        placed[index][cell if cell is not None else len(cells)].append((text, bbox))
    if leftovers:
        return []  # items outside every row: the grid does not describe this block
    pieces = []
    seen: set[str] = set()
    for index, buckets in enumerate(placed):
        lines = [line for bucket in buckets if bucket for line in _reading_lines(bucket)]
        if not lines:
            continue
        first_cell = " ".join(text for text, _ in (buckets[0] or []))
        pieces.append((lines, _row_label(first_cell, index, seen)))
    return pieces


# A markerless table row still needs a name. Its first cell is the row's own
# key wherever the table has one - a glossary's abbreviation ("β", "μSv/h"), a
# form's field label - which reads correctly in a citation and matches how the
# ground-truth keys name these nodes. A first cell that is long (a whole
# sentence of body text) or repeated elsewhere in the same table is no key at
# all, and the row falls back to its position.
_ROW_LABEL_MAX = 40


def _row_label(first_cell: str, index: int, seen: set[str]) -> str:
    text = " ".join(first_cell.split())
    if text and len(text) <= _ROW_LABEL_MAX and text not in seen:
        seen.add(text)
        return text
    return f"r{index + 1}"


# A borderless table has no ruled lines for PyMuPDF's table finder to detect:
# on the Attachment to the Technical Specifications' three-page glossary it
# returns a table carrying no cells at all (the one `_page_grids` drops), and
# `strategy="text"` is not an alternative - it fires on 100% of prose pages
# tested, shredding paragraphs into mid-token columns. What the page does have
# is geometry: the layout model's own items are already cell-level, and their
# left edges fall into a small number of sharp bands (x=58.7 and x=186.0 on that
# glossary). Grouping items into visual lines and splitting each at the second
# band recovers all 82 of its rows.
#
# Deliberately reached ONLY from a block the layout model already classified as
# a table, and only once the grid has failed, so it can never see prose.
_BAND_GAP = 6.0          # left edges this close belong to the same band
_BAND_SLACK = 2.0        # tolerance when testing which side of a band an item sits
_BAND_MIN_SHARE = 0.08   # a band needs this share of the block's items to count
_MIN_CLUSTERED_ROWS = 3  # fewer rows than this is not a table worth splitting


def _left_edge_bands(items) -> list[float]:
    """The sharp left-edge bands of a block's items, or [] when there are not
    at least two - one band is a paragraph, not a table."""
    edges = sorted(round(bbox[0], 1) for _, bbox in items)
    bands: list[list[float]] = []
    for edge in edges:
        if bands and edge - bands[-1][-1] <= _BAND_GAP:
            bands[-1].append(edge)
        else:
            bands.append([edge])
    need = max(2, int(len(items) * _BAND_MIN_SHARE))
    strong = [band[0] for band in bands if len(band) >= need]
    return strong if len(strong) >= 2 else []


def _column_row_pieces(items) -> list:
    """One piece per row of a borderless table, named by its first column.

    A line with nothing in the first column is a wrapped continuation of the row
    above, not a row of its own - without that, a definition running onto a
    second line ("DEPT | The Example Services Department")
    leaves an orphan fragment behind."""
    bands = _left_edge_bands(items)
    if not bands:
        return []
    second = bands[1] - _BAND_SLACK
    pieces: list = []
    seen: set[str] = set()
    for line in _reading_lines(items):
        label_text = " ".join(text for text, bbox in line if bbox[0] < second)
        if not label_text.strip() and pieces:
            pieces[-1][0].append(line)
            continue
        pieces.append(([line], _row_label(label_text, len(pieces), seen)))
    return pieces if len(pieces) >= _MIN_CLUSTERED_ROWS else []


# How far a block's left edge may sit from a list's marker column and still
# count as being in it.
_MARKER_COLUMN_SLACK = 2.0


def _closed_list_depth(x0: float, class_name: str, subitem_stack, nodes_by_id) -> int | None:
    """The depth of the open sub-item list this markerless block ends, or None
    when it continues the list's last item instead.

    A list ends where a block starts in the list's own marker column and the
    layout model did not classify it as a list item. A genuine continuation of an
    item wraps to the item's TEXT column, which is indented past the marker
    column, so the two never collide.

    Only the list whose marker column matches is closed, not every open level:
    a paragraph after a nested "(a) ... (b) ..." list that sits in the column of
    (a)/(b) resumes the item that holds that list, and the outer list stays open
    - the Terms of Tender (Supplement)'s paragraph 13 carries on with (2), (3) of
    the outer list after such a paragraph, and closing the whole stack re-rooted
    them under the paragraph and lost 13(b)'s items entirely.
    """
    if not subitem_stack or class_name == "list-item":
        return None
    for depth in range(len(subitem_stack) - 1, -1, -1):
        opener = nodes_by_id.get(subitem_stack[depth][1])
        if opener is not None and opener.bbox and abs(x0 - opener.bbox[0]) <= _MARKER_COLUMN_SLACK:
            return depth
def _is_heading(text: str, x0: float, class_name: str, subitem_stack, nodes_by_id, last_marker_id) -> bool:
    """Is this markerless block a heading of its own rather than text of the
    node before it?

    The layout model's `section-header` class, less three things it also
    covers: a label ending in a colon ("Glossary:") introduces what follows
    inside the current node; a line indented past the open list's marker column
    is part of the item (an address block's "the Authority"
    inside an item of the Appendix's contact list); and the first heading after
    a Part heading that has no title of its own ("Part I" over "Method of
    providing the Contract Deposit") is that Part's title.
    """
    if class_name != "section-header" or text.rstrip().endswith(":"):
        return False
    if subitem_stack:
        opener = nodes_by_id.get(subitem_stack[-1][1])
        if opener is not None and opener.bbox and x0 > opener.bbox[0] + _MARKER_COLUMN_SLACK:
            return False
    last = nodes_by_id.get(last_marker_id)
    if last is not None and last.kind in ("part", "annex") and not last.title and "\n" not in last.text:
        return False
    return True


    return None


def _layout_blocks(source_file: str, page_number: int) -> list[tuple[float, str, str, list[float]]]:
    """Ordered (x0, class_name, text, bbox) blocks for one page, boilerplate
    excluded. `bbox` is the block's own [x0, y0, x1, y1] in PDF point
    coordinates (page-relative, origin top-left) - carried through to each
    node's output so a node can be located exactly on the page, not just
    which page it's on."""
    from pymupdf.layout.pymupdf_util import create_input_data_from_page

    model = _get_model()
    page = _fitz_page(source_file, page_number)
    groups = model.predict(page, return_raw=True)
    if not groups:
        return []
    data_dict = create_input_data_from_page(page, options={
        "input_type": model.input_type,
        "feature_set_name": model.feature_set_name,
        "feature_extractor": model.feature_extractor,
    })
    all_texts = data_dict.get("text", [])
    all_bboxes = data_dict.get("bboxes", [])

    blocks = []
    for g in groups:
        if g["class_name"] in ("page-header", "page-footer", "picture"):
            continue
        items = [(all_texts[i], all_bboxes[i]) for i in g.get("indicies", [])
                 if 0 <= i < len(all_texts) and i < len(all_bboxes)]
        lines = _reading_lines(items)
        if g["class_name"] == "table":
            grid = _grid_for_block(source_file, page_number, page, g["group_bbox"])
            rows = _table_row_pieces(items, grid) if grid else []
            pieces = (rows or _column_row_pieces(items)) or [(lines, None)]
        else:
            pieces = [(piece, None) for piece in _split_at_marker_lines(lines)]
        for piece, row_label in pieces:
            text = _join_lines(piece).strip()
            if not text:
                continue
            bbox = list(g["group_bbox"]) if len(pieces) == 1 else [
                min(b[0] for line in piece for _, b in line), min(b[1] for line in piece for _, b in line),
                max(b[2] for line in piece for _, b in line), max(b[3] for line in piece for _, b in line),
            ]
            blocks.append((bbox[0], g["class_name"], text, bbox, row_label))
    return blocks


def _classify_marker(text: str):
    """Return (kind, number, title_or_none) for a block's own leading marker,
    or (None, None, None) if it isn't one. Checked in categorical-rank order:
    part/annex outrank clause, clause outranks subclause, subclause outranks
    subitem - matching document_index's own precedence."""
    pm = _PART_LAYOUT.match(text)
    if pm:
        number = pm.group("num") or pm.group("letter") or pm.group("tletter")
        title = pm.group("title") or pm.group("title2") or pm.group("title3") or ""
        return "part", number, title.strip()
    am = _ANNEX.match(text)
    if am:
        return "annex", am.group(1), am.group(2).strip()
    cm = _CLAUSE_LAYOUT.match(text)
    if cm:
        return "clause", cm.group(1), cm.group(2).strip()
    scm = _SUBCLAUSE.match(text)
    if scm:
        return "subclause", scm.group(1), None
    sm = _SUBITEM_WITH_DIGITS.match(text)
    if sm:
        return "subitem", sm.group(1) or sm.group(2), None
    # `09 Schedules.pdf`'s Compliance Schedule glues a footnote-reference
    # glyph (*/^/#) directly onto a subitem's own opening marker - "^(a)
    # I/We confirm...", "^(b) I/We confirm...not in compliance..." - the
    # same annotation convention already handled for a marker continuing an
    # *open* subitem_stack (see the main loop's displaced-marker fallback),
    # but this is a block's own *leading* marker, which only this function
    # ever classifies. Without it, a Part's first "^(a)" item never opens a
    # node at all and silently absorbs into whatever preceded the Part.
    if text[:1] in "*^#":
        # Sometimes more than one glyph stacks up - "*# Signed by the
        # Tenderer/Signed by an authorised..." (`01 Tender Form.pdf`'s own
        # signature-block label) glues an asterisk *and* a hash onto one
        # field label.
        rest = text.lstrip("*^#").lstrip(" \t")
        sm2 = _SUBITEM_WITH_DIGITS.match(rest)
        if sm2:
            return "subitem", sm2.group(1) or sm2.group(2), None
        # A glyph-prefixed field *label*, not a marker - "# Earlier delivery
        # schedule offered:", "^ Please tick ( ) the appropriate box...".
        # Confirmed real on `09 Schedules.pdf`'s Compliance Schedule: without
        # this, the label (and everything that follows it, since it never
        # opens a node to absorb into) merges into whichever subitem came
        # before it, inflating that subitem by the label's own length plus
        # its answer field. Gated on a capital letter so a stray glyph mid
        # footnote text doesn't get mistaken for a label.
        if rest[:1].isupper():
            return "note", None, None
    # A standalone bracketed instruction - "[Please refer to Paragraph 7 of
    # the Terms of Tender.]" - the *entire* block, not a parenthetical inside
    # a sentence. Confirmed real immediately after every Part/Table heading
    # in `09 Schedules.pdf`: without this it absorbs into the heading's own
    # node instead of staying the separate node ground truth treats it as.
    if text.startswith("[") and text.endswith("]"):
        return "note", None, None
    # "Notes:" heading, already split from its own note (1) by
    # _split_notes_heading - a leaf note in its own right, same as a
    # bracketed instruction.
    if text in ("Notes:", "Note:"):
        return "note", None, None
    return None, None, None


@dataclass
class _WorkingNode:
    node_id: str
    parent_id: str | None
    kind: str
    part: str | None
    number: str | None
    title: str | None
    page: int | None
    text: str
    is_coarse: int
    label: str | None = None
    doc_name: str | None = None
    ref_no: str | None = None
    rule_version: str | None = None
    # The block's own [x0, y0, x1, y1] in PDF point coordinates (page-
    # relative, origin top-left) - the block that opened this node, not
    # every block subsequently absorbed into it. Lets a node be located
    # exactly on the page, not just which page it's on.
    bbox: list[float] | None = None


def parse_document(doc_id: str | None, pages) -> list[dict]:
    """Layout-based equivalent of `document_index.parse_document`. Same input
    contract (a list of `ingest.Page`), same output contract (a flat list of
    node dicts, tree via parent_id)."""
    doc_id = doc_id or derive_doc_id(pages)
    seen_ids: dict[str, int] = {}
    pages = [p for p in pages if p.native_text]
    if not pages:
        return []

    furniture_by_page = {p.page_number: extract_page_furniture(p.native_text) for p in pages}
    doc_ref_no = next((f["ref_no"] for f in furniture_by_page.values() if f["ref_no"]), None)
    doc_rule_version = next((f["rule_version"] for f in furniture_by_page.values() if f["rule_version"]), None)

    doc_ident = SimpleNamespace(
        ref_no=doc_ref_no, rule_version=doc_rule_version, furniture_by_page=furniture_by_page,
    )

    subdocs = detect_subdocuments(pages)
    subdoc_by_page: dict[int, dict] = {}
    if len(subdocs) > 1:
        for index, segment in enumerate(subdocs):
            segment["node_id"] = f"{doc_id}:{index:02d}-{re.sub(r'[^A-Za-z0-9]+', '-', segment['name']).strip('-')[:40]}"
            for page_number in range(segment["first_page"], segment["last_page"] + 1):
                subdoc_by_page[page_number] = segment

    def _scope_of_page(page_number: int) -> str:
        segment = subdoc_by_page.get(page_number) if subdoc_by_page else None
        return segment["node_id"] if segment else doc_id

    blocks_by_page = {p.page_number: _layout_blocks(p.source_file, p.page_number) for p in pages}
    # `looks_like_toc` (shared with document_index's flat-text scan) flags a
    # page by heading density alone - >=8 clause-shaped headings averaging
    # under 200 chars each. Confirmed a false positive on `09 Schedules.pdf`
    # page 4 (the Particulars of Goods Schedule's own 14-row numbered field
    # table, "1. Place of Origin  2. Name of Manufacturer ..."): a genuine
    # data table has exactly the same statistical shape as a genuine table
    # of contents, and the false hit silently dropped the entire page. A
    # real TOC in this corpus is prose headings only - it never contains a
    # PyMuPDF-layout `table`-class block - so a page carrying one is
    # reclassified as real content regardless of what the density check says.
    toc_pages = {
        p.page_number for p in pages
        if looks_like_toc(p.native_text)
        and not any(cls == "table" for _, cls, _, _, _ in blocks_by_page.get(p.page_number, []))
    }
    furniture_by_scope = _detect_running_furniture(
        {pn: b for pn, b in blocks_by_page.items() if pn not in toc_pages}, _scope_of_page
    )

    # The document starts on its first page. Left as None, a standalone file (one
    # document, no sub-documents) could not be located at all: a citation of the
    # whole document ("the Non-collusive Tendering Certificate") resolved to a node
    # with no page, and anything that filters nodes by page skipped it.
    nodes: list[_WorkingNode] = [
        _WorkingNode(doc_id, None, "document", None, None, None, pages[0].page_number, "", 0)
    ]
    for segment in subdocs if len(subdocs) > 1 else []:
        nodes.append(_WorkingNode(
            segment["node_id"], doc_id, "subdocument", None, None, segment["name"],
            segment["first_page"], "", 0, doc_name=segment["name"],
            ref_no=doc_ref_no, rule_version=doc_rule_version,
        ))

    current_scope = None
    # Tracks which subdocument segment page-boundary crossings were last
    # detected against - deliberately separate from `current_scope`. A
    # "part"/"annex" marker sets current_scope = None on purpose (so
    # `parent_for_clause = current_scope or part_node or doc_id` lets the
    # more specific part_node win over the subdoc as parent) - but reusing
    # that same None for the page-boundary check below made the *next*
    # page's "did the segment change?" test misfire every time, since
    # segment.node_id (still the real segment) no longer equalled the
    # wiped-out current_scope. That falsely re-triggered reset_below_part()
    # on every page after a Part heading, deleting the part_node and
    # subitem_stack the Part heading had just built - confirmed on `09
    # Schedules.pdf`: any Part inside a multi-page schedule segment (Price/
    # Compliance/Information Schedule) lost its own children the moment the
    # page turned, because the reset fired again with no real segment change.
    subdoc_scope_id = None
    current_part = None
    part_node = None
    clause_node = None
    subclause_node = None
    subitem_stack: list[tuple[str, str]] = []
    nodes_by_id: dict[str, _WorkingNode] = {n.node_id: n for n in nodes}
    # id of whatever marker node was most recently created - a plain block
    # absorbs into this one, unconditionally, until the next marker of any
    # kind opens (see module docstring: this is what "a node's own span runs
    # up to the next marker" means in a block-based model).
    #
    # Before the first marker, that is the document (or sub-document) itself:
    # its title and preamble are its own text. Left as None, everything ahead of
    # the first marker was dropped from every node - a schedule's heading and
    # its "References to ..." preamble, a certificate's addressee - so the
    # document's own opening could not be located or quoted.
    last_marker_id: str | None = doc_id

    def reset_below_part():
        nonlocal clause_node, subclause_node, subitem_stack, last_marker_id
        clause_node = subclause_node = None
        subitem_stack = []
        last_marker_id = part_node

    def add(n: _WorkingNode) -> str:
        nonlocal last_marker_id
        nodes.append(n)
        nodes_by_id[n.node_id] = n
        last_marker_id = n.node_id
        return n.node_id

    # Run-in sub-items (see `_split_run_in_items`) are added once their piece
    # has been placed, as children of the node its text went into. They are
    # additional nodes, not a re-segmentation: the host keeps its whole text
    # (a citation of "20.1(c)" still returns all of (c), and the answer key for
    # Tender 1 measures such an item whole), and they do not enter
    # subitem_stack or become last_marker_id, so the blocks that follow nest
    # and absorb exactly as they would without them.
    run_in_pending: tuple[str, int, list[float]] | None = None

    def emit_run_in_items():
        nonlocal run_in_pending
        if run_in_pending is None:
            return
        text, page_number, bbox = run_in_pending
        run_in_pending = None
        host = last_marker_id if last_marker_id in nodes_by_id else None
        pieces = _split_run_in_items(text)
        if host is None or len(pieces) < 2:
            return
        levels: list[tuple[str, str]] = []  # (marker, node id) per open run-in level
        last_id = host
        for piece, opens in pieces[1:]:
            number = _SUBITEM_WITH_DIGITS.match(piece)
            marker = number.group(1) or number.group(2)
            if opens:
                parent = last_id
                levels.append((marker, ""))
            else:
                depth = next((d for d in range(len(levels) - 1, -1, -1) if marker in _successors(levels[d][0])), None)
                if depth is None:
                    continue
                del levels[depth + 1:]
                parent = nodes_by_id[levels[depth][1]].parent_id
            node_id = _unique(f"{parent}:({marker})", seen_ids)
            levels[-1] = (marker, node_id)
            node = _WorkingNode(
                node_id, parent, "subitem", nodes_by_id[host].part, None, None, page_number, piece, 0,
                label=f"({marker})", bbox=bbox, **_ident(doc_ident, page_number),
            )
            nodes.append(node)
            nodes_by_id[node_id] = node
            last_id = node_id

    for page in pages:
        emit_run_in_items()
        # A table-of-contents page reads as a dense run of clause-shaped
        # headings with almost no body text each - the same density check
        # document_index.DocumentText already uses to skip these pages before
        # scanning for markers at all. Needed here for the same reason: without
        # it, a TOC's own "PART 1 - TERMS OF TENDER" line (a pointer, not the
        # real heading) matches the same way the real one does 20 pages later,
        # producing a second, spurious node under the same scope name.
        # (`toc_pages` already excludes false positives - see its own note.)
        if page.page_number in toc_pages:
            continue

        segment = subdoc_by_page.get(page.page_number) if subdoc_by_page else None
        if segment and segment.get("node_id") != subdoc_scope_id:
            subdoc_scope_id = segment["node_id"]
            current_scope = segment["node_id"]
            part_node = None
            current_part = None
            reset_below_part()
            last_marker_id = segment["node_id"]

        for x0, class_name, raw_text, bbox, row_label in blocks_by_page.get(page.page_number, []):
            for index, text in enumerate(_split_block(raw_text, class_name)):
                emit_run_in_items()
                run_in_pending = (text, page.page_number, bbox)
                kind, number, title = _classify_marker(text)
                # Only the row's own first piece carries its label: a run-in
                # sub-item split out of the row ("(i) ...; (ii) ...") is a
                # marker of its own and classifies normally.
                label_here = row_label if index == 0 else None

                if kind == "note" and text.startswith("[") and clause_node is not None:
                    # A bracketed note means two different things depending
                    # on what it follows. After a Part/Table heading (no
                    # clause open - `09 Schedules.pdf`), it's a standalone
                    # pointer ground truth counts separately ("Part A intro
                    # bracket"). After a numbered clause heading (clause_node
                    # set - `04 Terms of Tender (Supplement).pdf`'s "[Paragraph
                    # X of the Terms of Tender shall be read subject to this
                    # Paragraph N.]"), it's part of *that clause's own*
                    # header text ground truth counts together as one "N
                    # (header)" node. Confirmed real: splitting it off
                    # unconditionally shrank every Supplement clause header
                    # by the bracket's own length.
                    kind = None

                if kind is None:
                    # Before treating this as plain continuation text, check
                    # whether it's actually this block's own marker, displaced
                    # mid-sentence by MarkdownGenerator's line-reordering (see
                    # _find_displaced_marker) - confirmed real on clauses 7.4,
                    # 9.3, and subitem 10.1(g).
                    if subclause_node is not None:
                        expected = _expected_next_subclause(nodes_by_id[subclause_node].number)
                        if expected and _find_displaced_marker(text, expected, parenthesized=False):
                            kind, number, title = "subclause", expected, None
                    if kind is None and subitem_stack:
                        for cand in _successors(subitem_stack[-1][0]):
                            if _find_displaced_marker(text, cand, parenthesized=True):
                                kind, number, title = "subitem", cand, None
                                break

                if kind is None:
                    scope_root = _scope_of_page(page.page_number)
                    if text in furniture_by_scope.get(scope_root, ()) and last_marker_id != scope_root:
                        # A running masthead is dropped on every page but the one
                        # it opens: there, before any marker, it is the document's
                        continue

                    if _is_heading(text, x0, class_name, subitem_stack, nodes_by_id, last_marker_id) \
                            and nodes_by_id[scope_root].text.strip():
                        # A heading with no marker of its own - "Stage I - ...",
                        # "Non-collusion", "Table 1 - ...", "Section 2 - ...",
                        # "Particulars of Offer". Absorbed into whatever node
                        # preceded it, it could not be located, and it inflated
                        # that node (a clause ran on into the next stage's heading).
                        # Its own node, under the enclosing Part or document, and
                        # the text after it joins it until the next marker - but,
                        # like a note, it is not a nesting level, so markers after
                        # it nest exactly as before. The document's own title (the
                        # first heading, before the document has any text) stays
                        # the document's text; see `_is_heading` for the rest.
                        parent = current_scope or part_node or doc_id
                        node_id = _unique(f"{parent}:heading", seen_ids)
                        add(_WorkingNode(
                            node_id, parent, "subitem", current_part, None, None,
                            page.page_number, text, 0,
                            bbox=bbox, **_ident(doc_ident, page.page_number),
                        ))
                        # own title ("PRICE SCHEDULE (To be completed and returned
                        # ...)") and belongs to the document node.
                        run_in_pending = None
                        continue

                    if label_here is not None:
                        # A table row the grid found but no marker opens: a
                        # glossary's "β Beta", a form's "Name of the Tenderer :".
                        # Without this it absorbs into whatever node preceded the
                        # table and is unaddressable - the whole Attachment to the
                        # Technical Specifications (82 key nodes) produced no node
                        # at all. Named by its own first cell (see `_row_label`),
                        # parented to the enclosing Table/Part or sub-document so a
                        # table's rows are siblings, and deliberately NOT pushed
                        # onto subitem_stack: like a note, it is not a nesting
                        # level and must not intercept which marker a later
                        # (a)/(b)/(i) continues.
                        parent = part_node or current_scope or doc_id
                        # The id parenthesises the key so a citation reads like
                        # every other sub-item ("row (β) of the glossary"), but
                        # `label` is the marker AS WRITTEN: the document prints
                        # "β Beta", not "(β) Beta", and a label the node's own
                        # text does not start with is simply wrong - it also
                        # makes the node fail the exact-location check that asks
                        # precisely that question.
                        node_id = _unique(f"{parent}:({label_here})", seen_ids)
                        add(_WorkingNode(
                            node_id, parent, "subitem", current_part, None, None,
                            page.page_number, text, 0, label=label_here,
                            bbox=bbox, **_ident(doc_ident, page.page_number),
                        ))
                        continue

                    closed = _closed_list_depth(x0, class_name, subitem_stack, nodes_by_id)
                    if closed is not None:
                        # Text that resumes the enclosing clause after a list,
                        # not a continuation of the list's last item: "The
                        # grounds specified in Paragraphs 20.1(a) to 20.1(g)
                        # above are separate and independent...". Two signals
                        # agree and both are already in the block: it sits at
                        # the list's own MARKER column (x=156.5, where (f)/(g)
                        # start) while a real continuation of an item is
                        # indented past it (x=192.5), and the layout model
                        # classifies it `text` where the items are `list-item`.
                        # Absorbed into the last item, it inflates that item and
                        # loses a node the schedules cite in its own right.
                        parent = nodes_by_id[subitem_stack[closed][1]].parent_id
                        del subitem_stack[closed:]
                        node_id = _unique(f"{parent}:tail", seen_ids)
                        add(_WorkingNode(
                            node_id, parent, "subitem", current_part, None, None,
                            page.page_number, text, 0,
                            bbox=bbox, **_ident(doc_ident, page.page_number),
                        ))
                        continue

                    # not a marker - it's the continuation of whatever marker was
                    # opened most recently, however many such blocks follow in a
                    # row (absorbing only the first one here was a real bug,
                    # confirmed on clause 15's bracket-note-then-body-paragraph
                    # pattern - see plan.md).
                    if last_marker_id is not None and last_marker_id in nodes_by_id:
                        nodes_by_id[last_marker_id].text += "\n" + text
                    continue

                # A Part or annex belongs to the sub-document it appears in, not
                # to the file. Parented to the file root, a combined schedule
                # file's "Part A" of the Price Schedule and "Part A" of the
                # Compliance Schedule were siblings told apart only by a `#2`
                # suffix, the sub-document node had no children (so its extent
                # was unknown), and "Part A of the Price Schedule" could not be
                # looked up under the Price Schedule.
                container = (subdoc_by_page.get(page.page_number) or {}).get("node_id") or doc_id

                if kind == "part":
                    current_part = f"Part {number}"
                    part_node = _unique(f"{container}:P{number}", seen_ids)
                    current_scope = None
                    add(_WorkingNode(
                        part_node, container, "part", current_part, number, title, page.page_number, text, 0,
                        bbox=bbox, **_ident(doc_ident, page.page_number),
                    ))
                    reset_below_part()
                    continue

                if kind == "annex":
                    current_part = f"Annex {number}"
                    part_node = _unique(f"{container}:ANNEX-{number}", seen_ids)
                    current_scope = None
                    add(_WorkingNode(
                        part_node, container, "annex", current_part, number, title, page.page_number, text, 0,
                        bbox=bbox, **_ident(doc_ident, page.page_number),
                    ))
                    reset_below_part()
                    continue

                parent_for_clause = current_scope or part_node or doc_id

                if kind == "clause":
                    clause_node = _unique(f"{parent_for_clause}:{number}", seen_ids)
                    subclause_node = None
                    subitem_stack = []
                    add(_WorkingNode(
                        clause_node, parent_for_clause, "clause", current_part, number, title,
                        page.page_number, text, 1, bbox=bbox, **_ident(doc_ident, page.page_number),
                    ))
                    continue

                if kind == "subclause":
                    parent = clause_node or parent_for_clause
                    subclause_node = _unique(f"{parent_for_clause}:{number}", seen_ids)
                    subitem_stack = []
                    add(_WorkingNode(
                        subclause_node, parent, "subclause", current_part, number, None,
                        page.page_number, text, 1, bbox=bbox, **_ident(doc_ident, page.page_number),
                    ))
                    continue

                if kind == "note":
                    # A bracketed instruction or a glyph-prefixed field label
                    # (see _classify_marker) - its own node, but deliberately
                    # NOT pushed onto subitem_stack: it isn't a real nesting
                    # level, so it must not intercept which marker a later
                    # (a)/(b)/(i) continues. It does become last_marker_id,
                    # though, so any plain continuation text right after it
                    # (a field's own answer line) attaches to *it* instead of
                    # inflating whatever subitem preceded it.
                    parent = (subitem_stack[-1][1] if subitem_stack
                              else subclause_node or clause_node or parent_for_clause)
                    node_id = _unique(f"{parent}:note", seen_ids)
                    add(_WorkingNode(
                        node_id, parent, "subitem", current_part, None, None, page.page_number, text, 0,
                        bbox=bbox, **_ident(doc_ident, page.page_number),
                    ))
                    continue

                # kind == "subitem"
                depth = next(
                    (d for d in range(len(subitem_stack) - 1, -1, -1)
                     if number in _successors(subitem_stack[d][0])),
                    None,
                )
                if depth is None:
                    parent = (subitem_stack[-1][1] if subitem_stack
                              else subclause_node or clause_node or parent_for_clause)
                    node_id = _unique(f"{parent}:({number})", seen_ids)
                    subitem_stack.append((number, node_id))
                else:
                    del subitem_stack[depth + 1:]
                    parent = (subitem_stack[depth - 1][1] if depth
                              else subclause_node or clause_node or parent_for_clause)
                    node_id = _unique(f"{parent}:({number})", seen_ids)
                    subitem_stack[depth] = (number, node_id)
                add(_WorkingNode(
                    node_id, parent, "subitem", current_part, None, None, page.page_number, text, 0,
                    label=f"({number})", bbox=bbox, **_ident(doc_ident, page.page_number),
                ))

    emit_run_in_items()
    return [
        {
            "doc_name": n.doc_name,
            "ref_no": n.ref_no,
            "rule_version": n.rule_version,
            "node_id": n.node_id,
            "parent_id": n.parent_id,
            "kind": n.kind,
            "part": n.part,
            "number": n.number,
            "label": n.label,
            "title": n.title,
            "page": n.page,
            "char_start": 0,
            "char_end": len(n.text),
            "text": n.text.strip(),
            "is_coarse": n.is_coarse,
            "bbox": n.bbox,
        }
        for n in nodes
    ]
