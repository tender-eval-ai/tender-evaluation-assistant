"""Resolve a citation in prose - "Paragraph 20.2 of the Terms of Tender" - to a node.

This is deliberately **not** a search. Full-text search was tried and is the wrong
tool: querying "Terms of Tender" over the node text returns 80 rows, every one of
which merely *mentions* the phrase, while the row that *is* the Terms of Tender
(the part node titled "TERMS OF TENDER") never surfaces at all. Ranking cannot fix
that, because the target is not the most relevant mention - it is a different kind
of thing from any mention.

Resolution is exact lookups instead:

    "Paragraph 20.2 of the Terms of Tender"
       -> name "Terms of Tender"  -> scope prefix  <doc>:P1     (metadata)
       -> number "20.2" within that prefix         -> p.49      (exact match)

Both come from data captured at parse time - the page footer's document label and
the PART heading - so the same citation always resolves to the same node, or to an
explicit miss. No model, no threshold, no ranking.

A citation is a chain of targets, innermost first, ending in a document name:

    "Paragraph 2 of Table A of the Particulars of Goods Schedule"
       -> scope "Particulars of Goods Schedule" -> Part/Table "A" -> number "2"
    "Item 1 in Part A of the Price Schedule"       (a numbered row of a Part)
    "part (4) in the Appendix to the Terms of Tender - Contact Details"
                                                   (an entry labelled "(4)")
    "Annex A to the Terms of Tender - Part IA - Method of providing ..."
                                                   (a Part of a named annex)
    "the Non-collusive Tendering Certificate"      (a whole document)

Lists and ranges are expanded ("Paragraphs 2 and 3 of Tables A and B", "Items 2
to 4"), one citation per target, so each resolves to its own node.

Measured on the internal cross-references of three real tenders (675 citations):
98% / 98% / 84% resolve to exactly one node. See tests/test_citations.py, which
grades against the corpus itself rather than hand labels.
"""

import itertools
import re
from collections import defaultdict
from typing import NamedTuple

# A capitalised word of a document title ("General", "Non-collusive", "TAP").
_WORD = r"(?:[A-Z][a-zA-Z\-]+|[A-Z]{2,})"
# A target keyword is never part of a name: "...of the Terms of Tender and
# Paragraph 5..." must stop before "Paragraph".
_KEYWORD = r"(?:Paragraphs?|Clauses?|Items?|Parts?|Tables?|Annex(?:es)?)\b"
_NAME_WORD = rf"(?!{_KEYWORD}){_WORD}"
_CONNECTOR = r"(?:of|the|to|and|for|in|on)"
# "(Supplement)", "(Contact Details)", "(Details of Local Support)" belong to a
# name; a lowercase aside ("(if applicable)", "(English or Chinese version)") does not.
_TITLE_PAREN = rf"\({_WORD}(?:\s+(?:{_CONNECTOR}|{_WORD}))*\)"
_PLAIN_NAME = (
    rf"{_NAME_WORD}(?:(?:\s+{_CONNECTOR})*\s+{_NAME_WORD})*"
    rf"(?:\s*{_TITLE_PAREN})?"
    # "Appendix to the Terms of Tender - Contact Details": a dash-joined subtitle,
    # unless what follows the dash is itself a target ("- Part IA").
    rf"(?:\s+[-–—]\s+{_NAME_WORD}(?:(?:\s+{_CONNECTOR})*\s+{_NAME_WORD})*(?:\s*{_TITLE_PAREN})?)?"
)
# "Annex A to the Terms of Tender", "Annex (Details of Local Support) of the
# Information Schedule": an annex is named after the document it is attached to.
_ANNEX_NAME = rf"Annex\s+(?:[A-Z0-9]{{1,2}}|\([^)]+\))\s+(?:to|of)\s+the\s+{_PLAIN_NAME}"
_NAME = rf"(?:{_ANNEX_NAME}|{_PLAIN_NAME})"

_LABEL = r"\(\d+\)"
# One identifier of whatever kind, longest form first: a parenthesised label or annex
# title ("(4)", "(Details of Local Support)"), a number with its sub-item markers
# ("20.2(a)", "3A"), a roman Part ("IA") or a letter ("B", "A1").
#
# Written as one **atomic** token, not as an alternation of a number pattern, a Part
# pattern and an annex pattern: those overlap, so every id in a list matched three
# ways ("1" is all three, over the same text) and a list of n ids could be read 3**n
# ways. Which kind an id is comes from the keyword before the list
# (`_level_targets`), never from which alternative matched, so the engine was
# re-splitting ids that are all the same to us: when the chain around the list failed
# (a list with no document name after it - "Paragraphs 1, 2 ... and 14 above"), it
# tried every reading, and a 14-item list took 18 seconds, a 20-item list minutes.
# Atomic fixes each id at its longest form and never re-splits it: a 20-item list now
# parses in under a millisecond (test_a_long_list_with_no_document_name_parses_quickly).
_ID = (r"(?>\([^)]+\)"
       r"|\d+(?:\.\d+)*[A-Z]?(?:\s*\([a-z]{1,4}\))*"
       r"|[IVX]{1,4}[AB]?"
       r"|[A-Z]{1,2}\d?)(?![a-zA-Z])")
# A lowercase aside may sit inside a list: "Tables A, B, C (if applicable), D and E".
_ASIDE = r"(?:\s*\([a-z]+\s[^)]*\))?"
_LIST = rf"{_ID}(?:{_ASIDE}\s*(?:,\s*(?:and\s+)?|\s+and\s+|\s+to\s+|\s*[-–]\s*){_ID})*"
_LEVEL_KEYWORD = r"(?:[Pp]aragraphs?|[Cc]lauses?|[Ii]tems?|[Pp]arts?|[Tt]ables?|Annex(?:es)?)"
_LEVEL = rf"{_LEVEL_KEYWORD}\s+{_LIST}{_ASIDE}"
_LEVEL_RE = re.compile(rf"(?P<kw>{_LEVEL_KEYWORD})\s+(?P<ids>{_LIST}){_ASIDE}")
# One target chain written innermost first: "paragraph 1 of Table D".
_GROUP = rf"{_LEVEL}(?:\s+(?:of|in)\s+(?:the\s+)?{_LEVEL})*"
_GROUP_RE = re.compile(_GROUP)
_CHAIN = re.compile(
    # "<Name> - Part IA": the dash form names the document first. Tried first, so
    # "Annex A to the Terms of Tender - Part IA" is not read as the whole annex.
    # Several Parts may follow in brackets, each with its own dash subtitle:
    # "<Name> - (Part IA - <title> and Part IB - <title>)"; read as the first Part
    # alone, the second was never cited.
    rf"(?P<dname>{_NAME})\s+[-–—]\s+\(?(?P<dlevel>(?:Part|Table)\s+{_LIST}"
    rf"(?:(?:\s+[-–—]\s+[^()]*?)?\s+and\s+(?:Part|Table)\s+{_LIST})*)"
    # Several chains may share one document name: "paragraphs 1 and 2 of Tables A to
    # C, paragraph 1 of Table D and Part F of the X Schedule". Read as one chain, only
    # the last group had a name and the others were silently dropped (twelve targets
    # of one schedule item on Tender 3).
    # "parts (2) and (3) respectively in the X": an adverb may sit before the name.
    rf"|(?P<levels>{_GROUP}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+){_GROUP})*)(?:\s+respectively)?"
    rf"\s+(?:of|in|to)\s+the\s+(?P<name>{_NAME})"
)
_ITEM_MARKER = re.compile(r"\(([a-z]{1,4})\)")
_ID_TOKEN = re.compile(_ID)


class Citation(NamedTuple):
    """A parsed reference.

    `number` and `items` describe the innermost numbered target ("20.2", ("a", "i"));
    `path` is the whole target chain, outermost first, as (kind, id) pairs where
    kind is "part", "annex", "number" or "label". A whole-document citation has an
    empty number and path.
    """

    number: str
    name: str
    items: tuple[str, ...] = ()
    path: tuple[tuple[str, str], ...] = ()


# The name run above will happily continue into the rest of the sentence when the
# next word is capitalised. Cut at the words that resume prose.
_RESUMES_PROSE = re.compile(r"\s+(?:please|shall|which|is|are|or|respectively)\b.*$", re.I)
# A sub-item marker that leaked into the name: "Technical Specifications (e)".
_TRAILING_MARKER = re.compile(r"\s*\((?:[a-z]{1,2}|[ivx]{1,4})\)\s*$")


def _fold_word(word: str) -> str:
    word = word.lower()
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def normalise_name(name: str) -> str:
    """Fold a document name to a comparison key.

    Trailing plurals are dropped word by word so the corpus's own inconsistencies
    match: the documents cite both "Technical Specifications" and "Technical
    Specification", and one place writes "General Condition of Contract" for the
    General Conditions. Punctuation is folded too, so "Appendix to the Terms of
    Tender - Contact Details" and "Appendix to the Terms of Tender (Contact
    Details)" are the same name. A leading "the" is not part of a name.
    """
    name = _TRAILING_MARKER.sub("", name or "")
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(_fold_word(word) for word in words)


_ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv")
_ITEM_ONLY = re.compile(r"\(([a-z]{1,4})\)")
# A number with its sub-item markers, split before its last marker: "24.4(b)(i)" ->
# ("24.4(b)", "i"); "24.4" -> ("24.4", None).
_NUMBERED = re.compile(r"(\d[\d.]*[A-Z]?(?:\([a-z]{1,4}\))*?)(?:\(([a-z]{1,4})\))?")


def _item_series(first: str, last: str) -> list[str] | None:
    """The markers after `first` up to `last`: ("a", "c") -> [b, c], ("i", "iii") ->
    [ii, iii]. Roman when both are roman numerals, since "(i) to (iii)" is the form
    that occurs; None when the two are not one series."""
    if first in _ROMAN and last in _ROMAN and _ROMAN.index(first) < _ROMAN.index(last):
        return list(_ROMAN[_ROMAN.index(first) + 1:_ROMAN.index(last) + 1])
    if re.fullmatch(r"[a-z]", first) and re.fullmatch(r"[a-z]", last) and first < last:
        return [chr(c) for c in range(ord(first) + 1, ord(last) + 1)]
    return None


def _expand(ids_text: str) -> list[str]:
    """ "2, 3 and 5" -> [2, 3, 5]; "A to D" -> [A, B, C, D]; "2 to 4" -> [2, 3, 4];
    "24.4(a) to (c)" -> [24.4(a), 24.4(b), 24.4(c)]."""
    ids_text = re.sub(r"\([a-z]+\s[^)]*\)", lambda m: " " * len(m.group(0)), ids_text)
    tokens = [(m.group(0), m.start(), m.end()) for m in _ID_TOKEN.finditer(ids_text)]
    out: list[str] = []
    for index, (token, start, _) in enumerate(tokens):
        between = ids_text[tokens[index - 1][2]:start] if index else ""
        previous = out[-1] if out else None
        is_range = bool(re.fullmatch(r"\s+to\s+|\s*[-–]\s*", between))
        # A bare "(c)" after a number continues that number's items: "24.4(a) to (c)",
        # "3.3(a), (b) and (d)". Read as a number of its own it has no digits.
        item = _ITEM_ONLY.fullmatch(token)
        numbered = _NUMBERED.fullmatch(previous) if item and previous else None
        if numbered:
            base, last = numbered.group(1), numbered.group(2)
            series = _item_series(last, item.group(1)) if is_range and last else None
            out.extend(f"{base}({marker})" for marker in (series or [item.group(1)]))
            continue
        if previous is not None and is_range:
            if previous.isdigit() and token.isdigit() and int(previous) < int(token) <= int(previous) + 50:
                out.extend(str(n) for n in range(int(previous) + 1, int(token) + 1))
                continue
            if re.fullmatch(r"[A-Z]", previous) and re.fullmatch(r"[A-Z]", token) and previous < token:
                out.extend(chr(c) for c in range(ord(previous) + 1, ord(token) + 1))
                continue
        out.append(token if token.startswith("(") else re.sub(r"\s+", "", token))
    return out


def _level_targets(keyword: str, ids_text: str) -> list[tuple[str, str]]:
    word = keyword.lower().rstrip("s")
    targets = []
    for ident in _expand(ids_text):
        if re.fullmatch(_LABEL, ident):
            targets.append(("label", ident))
        elif word in ("part", "table"):
            targets.append(("part", ident))
        elif word.startswith("annex"):
            targets.append(("annex", ident))
        elif ident[0].isdigit():
            targets.append(("number", ident))
        else:
            # "Clause (b) of Part B": a lettered item is found by its label. Any other
            # id with no number ("Paragraph A") is looked up the same way, and finds
            # nothing rather than being read as a number.
            targets.append(("label", ident))
    return targets


def _clean_name(name: str) -> str:
    return _RESUMES_PROSE.sub("", re.sub(r"\s+", " ", name).strip())


def _chain_citations(match: re.Match) -> list[Citation]:
    if match.group("dname"):
        name = _clean_name(match.group("dname"))
        return [c for level in _LEVEL_RE.finditer(match.group("dlevel"))
                for c in _citations_for(name, [_level_targets(level.group("kw"), level.group("ids"))])]
    name = _clean_name(match.group("name"))
    # Written innermost first ("Paragraph 2 of Table A"); resolved outermost first.
    groups = [[_level_targets(m.group("kw"), m.group("ids")) for m in _LEVEL_RE.finditer(group.group(0))][::-1]
              for group in _GROUP_RE.finditer(match.group("levels"))]
    return [c for levels in groups for c in _citations_for(name, levels)]


def _citations_for(name: str, levels: list[list[tuple[str, str]]]) -> list[Citation]:
    citations = []
    for path in itertools.product(*levels):
        kind, ident = path[-1]
        number, items = "", ()
        if kind == "number":
            number = re.match(r"[\d.]+", ident).group(0).rstrip(".")
            items = tuple(_ITEM_MARKER.findall(ident))
        citations.append(Citation(number=number, name=name, items=items, path=tuple(path)))
    return citations


def parse_citations(text: str) -> list[Citation]:
    """Every scoped citation in `text` (whole-document mentions need an index; see
    `CitationIndex.citations_in`)."""
    flattened = re.sub(r"\s+", " ", text or "")
    return [c for m in _CHAIN.finditer(flattened) for c in _chain_citations(m)]


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


# A tender issued as separate files numbers them "01 Tender Form (G.F.999).pdf",
# "10 Appendix to the Terms of Tender - Contact Details.pdf": after the number, the
# file name is the document's title.
_NUMBERED_FILE = re.compile(r"^\d{1,2}[A-Z]?\s+(?P<title>.+?)\.pdf$", re.I)


def _file_title(source_file: str | None) -> list[str]:
    """The names a numbered file gives its document: its title, and the title without
    a parenthesised form or version number ("(G.F.999)"; a parenthesis without a
    digit, such as "(Supplement)", is part of the name and stays).

    Some documents name themselves nowhere else: the Tender Form has no footer label,
    and the Appendix's footer label wraps, so citations of a Part of the Tender Form
    or an entry of the Appendix resolved to nothing on both multi-file tenders. Only nodes that carry `source_file` (set by whoever
    parsed the files, as tools/eval_parser.py and app/rulesets/locate.py do) get
    these names."""
    match = _NUMBERED_FILE.match((source_file or "").replace("\\", "/").rsplit("/", 1)[-1])
    if not match:
        return []
    title = match.group("title").strip()
    bare = re.sub(r"\s*\((?=[^()]*\d)[^()]*(?:\([^()]*\))?[^()]*\)\s*", " ", title).strip()
    # "Appendix to the Terms of Tender - Contact Details" is also cited without its
    # subtitle.
    main = re.split(r"\s+[-–—]\s+", bare, maxsplit=1)[0]
    return list(dict.fromkeys(name for name in (title, bare, main) if name))


_TAIL_WORDS = 5
# A head that names a container of its own inside another document, rather than
# the first words of a label that wrapped: "Annex 1 to the", "Supplement to the".
# An annex or appendix named by an identifier is one of these; named by nothing
# ("Appendix to the ...") or by a title ("Annex (Details of Local Support) of
# ...") it is exactly how a wrapped footer label reads, and both of those are
# real wrapped labels on Tender 3. See `CitationIndex._truncated_scope`.
_CONTAINER_HEAD = re.compile(
    r"(?:annex|appendix|supplement|schedule)\s+(?:\d{1,3}|[a-z]|[ivx]{1,4})\s+(?:to|of)\s+the"
    r"|(?:supplement|schedule)\s+(?:to|of)\s+the")
_ANNEX_HEADING = re.compile(r"^\s*(Annex\s+\S+\s+(?:to|of)\s+the\s+[^\n]+?)\s*$", re.M)


class CitationIndex:
    """The lookup tables a citation needs, built once per tender."""

    def __init__(self, nodes):
        self._by_number: dict[str, list[dict]] = defaultdict(list)
        self._by_id: dict[str, dict] = {}
        self._nodes = list(nodes)
        for node in self._nodes:
            self._by_id[node["node_id"]] = node
            if node.get("number"):
                self._by_number[node["number"]].append(node)

        # A document names itself in several places and no one of them is enough.
        # The page footer carries a label for most documents, but TERMS-1's
        # footer has none - there, "Terms of Tender" and "General Conditions of
        # Contract" are PART titles. An annex bound into a document names itself
        # in its heading ("Annex A to the Terms of Tender"), and a form with no
        # footer label is known by the title lines the parser records as aliases.
        # Only container nodes define a scope. Reading the name off ordinary clause
        # nodes instead made every clause that merely carries a footer label a
        # candidate boundary, which is how two same-named sub-documents ended up
        # folded together.
        named: dict[str, list[str]] = defaultdict(list)
        # Names that denote a whole document, as opposed to a Part title such as
        # "Estimated Goods Price"; only these are looked for as bare mentions.
        self._document_names: set[str] = set()

        def register(name, node_id, document=True):
            key = normalise_name(name)
            if key:
                named[key].append(node_id)
                if document and len(key.split()) >= 2:
                    self._document_names.add(key)

        roots_with_subdocs = {n["node_id"].split(":")[0] for n in nodes if n["kind"] == "subdocument"}
        for node in self._nodes:
            for alias in node.get("aliases") or ():
                register(alias, node["node_id"])
            if node["kind"] == "part" and node.get("title"):
                title = node["title"]
                register(title, node["node_id"], document=title.upper() == title)
            elif node["kind"] == "annex":
                heading = _ANNEX_HEADING.match(node.get("text") or "")
                if heading:
                    register(heading.group(1), node["node_id"])
            elif node["kind"] == "subdocument" and node.get("doc_name"):
                register(node["doc_name"], node["node_id"])
            elif node["kind"] == "document":
                for name in _file_title(node.get("source_file")):
                    register(name, node["node_id"])
            elif node.get("doc_name") and node["node_id"].split(":")[0] not in roots_with_subdocs:
                # A standalone file - one document, no embedded sub-documents - names
                # itself only in its page footer, so the whole file is the scope.
                register(node["doc_name"], node["node_id"].split(":")[0])
        self.scopes = {name: _minimal_roots(ids) for name, ids in named.items()}
        self._name_tokens = sorted((key.split() for key in self._document_names), key=len, reverse=True)

    # ------------------------------------------------------------------ lookup

    def _scope(self, name: str) -> list[str]:
        """Scope prefixes for a name; if the full name is unknown, try it without a
        trailing " and ...", " - subtitle" or " in ..." (a name run that kept going:
        "Part A of the Price Schedule in Local Currency" reads the connector "in"
        and the capitalised words after it as part of the name)."""
        candidates = [name]
        for separator in (" and ", " - ", " – ", " in "):
            if separator in name:
                candidates.append(name.rsplit(separator, 1)[0])
        for candidate in candidates:
            prefixes = self.scopes.get(normalise_name(candidate))
            if prefixes:
                return prefixes
        return self._truncated_scope(normalise_name(name))

    def _truncated_scope(self, key: str) -> list[str]:
        """A footer label that wrapped keeps only its last line: on the combined tender
        the Appendix to the Terms of Tender is known only by the words after "Appendix
        to the", and an annex of the Information Schedule only by the end of its
        parenthesised title. A known name of at
        least five words that ends the cited name is taken for it; shorter tails ("Terms
        of Tender" at the end of "Annex A to the Terms of Tender") are real documents
        of their own, so the longest matching tail wins and short ones never match.

        A head that names a container of its own is not a wrapped label: "Annex 1 to
        the <X>" and "Supplement to the <X>" are parts of <X>, not <X>, so dropping
        the head resolved a paragraph of an annex that has no node to <X>'s own
        clause of that number - a wrong location, where an unresolved citation is at
        least visible as `unresolved` in what locate reports."""
        words = key.split()
        for start in range(1, len(words) - _TAIL_WORDS + 1):
            if _CONTAINER_HEAD.fullmatch(" ".join(words[:start])):
                continue
            prefixes = self.scopes.get(" ".join(words[start:]))
            if prefixes:
                return prefixes
        return []

    def _under(self, prefixes: list[str]):
        return [n for n in self._nodes if any(n["node_id"].startswith(f"{p}:") for p in prefixes)]

    def resolve(self, number: str, name: str, items: tuple[str, ...] = ()) -> list[dict]:
        """Nodes matching "Paragraph <number>(<items>) of the <name>". Empty =
        unresolved, >1 = genuinely ambiguous.

        Sub-items carry number=None, so a lookup on `number` structurally cannot
        return one; the sub-item path is walked by id instead.
        """
        prefixes = self._scope(name)
        if not prefixes:
            return []
        return self._numbered(prefixes, number, items)

    def _numbered(self, prefixes: list[str], number: str, items: tuple[str, ...]) -> list[dict]:
        hits = [node for node in self._by_number.get(number, [])
                if node["kind"] not in ("part", "annex")
                and any(node["node_id"].startswith(f"{prefix}:") for prefix in prefixes)]
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

    def _annex(self, prefixes: list[str], name: str, ident: str) -> list[dict]:
        # An annex is usually its own named document ("Annex A to the Terms of
        # Tender"); failing that, an annex heading numbered `ident` inside the scope.
        named = self._scope(f"Annex {ident} to the {name}")
        if named:
            return [self._by_id[p] for p in named if p in self._by_id]
        wanted = ident.strip("()").lower()
        return [n for n in self._under(prefixes)
                if n["kind"] == "annex" and (n.get("number") or "").lower() == wanted]

    def resolve_citation(self, citation: Citation) -> list[dict]:
        if not citation.path:
            if citation.number:
                return self.resolve(citation.number, citation.name, citation.items)
            return [self._by_id[p] for p in self._scope(citation.name) if p in self._by_id]

        prefixes = self._scope(citation.name)
        if not prefixes and citation.path[0][0] == "annex":
            prefixes = ["\0"]  # the annex may still be a document named on its own
        if not prefixes:
            return []
        hits: list[dict] = []
        for depth, (kind, ident) in enumerate(citation.path):
            if kind == "annex":
                hits = self._annex(prefixes, citation.name, ident) if depth == 0 else [
                    n for n in self._under(prefixes)
                    if n["kind"] == "annex" and (n.get("number") or "") == ident.strip("()")]
            elif kind == "part":
                hits = [n for n in self._under(prefixes)
                        if n["kind"] == "part" and (n.get("number") or "").upper() == ident.upper()]
            elif kind == "label":
                hits = [n for n in self._under(prefixes) if n.get("label") == ident]
                # "(b) of Part B" is Part B's own item (b); a (b) nested deeper inside
                # one of its items is another item.
                depth = min((n["node_id"].count(":") for n in hits), default=0)
                hits = [n for n in hits if n["node_id"].count(":") == depth]
            else:
                number = re.match(r"[\d.]+", ident).group(0).rstrip(".")
                hits = self._numbered(prefixes, number, tuple(_ITEM_MARKER.findall(ident)))
            if not hits:
                return []
            prefixes = [n["node_id"] for n in hits]
        return hits

    # ------------------------------------------------------------------ text

    def citations_in(self, text: str) -> list[Citation]:
        """Every citation in `text`: target chains first, then bare mentions of a
        known document name ("the Compliance Schedule") outside those chains."""
        flattened = re.sub(r"\s+", " ", text or "")
        citations: list[Citation] = []
        remaining = list(flattened)
        for match in _CHAIN.finditer(flattened):
            found = _chain_citations(match)
            if found:
                citations.extend(found)
                remaining[match.start():match.end()] = " " * (match.end() - match.start())
        citations.extend(self._document_mentions("".join(remaining)))
        return citations

    def _document_mentions(self, text: str) -> list[Citation]:
        words = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9]+", text)]
        folded = [_fold_word(w) for w, _, _ in words]
        taken = [False] * len(words)
        found: list[tuple[int, Citation]] = []
        for tokens in self._name_tokens:
            size = len(tokens)
            for start in range(len(words) - size + 1):
                if any(taken[start:start + size]) or folded[start:start + size] != tokens:
                    continue
                if not words[start][0][0].isupper():
                    continue
                # Stay within one run of text: a name does not span a sentence break.
                span = text[words[start][1]:words[start + size - 1][2]]
                if re.search(r"[.;:]\s", span):
                    continue
                taken[start:start + size] = [True] * size
                found.append((start, Citation(number="", name=span)))
        return [c for _, c in sorted(found, key=lambda f: f[0])]

    def resolve_text(self, text: str) -> list[tuple[Citation, list[dict]]]:
        """Resolve every citation in a block of prose, keeping unresolved ones."""
        return [(citation, self.resolve_citation(citation)) for citation in self.citations_in(text)]
