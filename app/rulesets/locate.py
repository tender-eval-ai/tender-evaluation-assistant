import re
from dataclasses import dataclass, field
from typing import Literal

from app.parsing.document_index import normalize_whitespace

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
_PART_HEADING_PATTERN = re.compile(r"\nPart ([A-Z])\b")
_LETTERED_ITEM_PATTERN = re.compile(r"\n\(([a-z])\)\s*")
# A citation can list several numbers sharing one trailing document phrase
# (confirmed on real data: "Paragraphs 9.4, 10.1, 12 and 20.2 of the Terms of
# Tender and Paragraphs 13 and 16 of the Terms of Tender (Supplement)" - two
# groups, each with its own document tail). \s+ throughout, not literal spaces,
# since the document phrase itself can line-wrap mid-phrase on a real page
# ("Terms \nof Tender").
_INLINE_PARAGRAPH_GROUP_PATTERN = re.compile(
    r"Paragraphs?\s+((?:[\d.]+(?:\([a-z]+\))*(?:\s*,\s*|\s+and\s+))*[\d.]+(?:\([a-z]+\))*)"
    r"\s+of\s+the\s+(Terms\s+of\s+Tender(?:\s*\(\s*Supplement\s*\))?)",
    re.IGNORECASE,
)
_NUMBER_TOKEN_PATTERN = re.compile(r"[\d.]+(?:\([a-z]+\))*")

_IF_BLANK_BY_PART: dict[str, Literal["DISQUALIFY", "AMBIGUOUS_NEEDS_HUMAN", "DEEMED_DEFAULT"]] = {
    "A": "DISQUALIFY",
    "B": "AMBIGUOUS_NEEDS_HUMAN",
    "C": "DEEMED_DEFAULT",
}

_CONSEQUENCE_RULE_BY_PART = {
    "A": "Missing = disqualified immediately, no exception",
    "B": "Missing = may allow a late request from the Authority before disqualifying",
    "C": "Discretionary - Authority may request later, or evaluate as submitted",
}


@dataclass
class ScheduleItem:
    letter: str
    part: Literal["A", "B", "C"]
    name: str
    if_blank: Literal["DISQUALIFY", "AMBIGUOUS_NEEDS_HUMAN", "DEEMED_DEFAULT"]
    source_page: int
    references_paragraphs: list[str] = field(default_factory=list)


@dataclass
class SchedulePart:
    part: Literal["A", "B", "C"]
    consequence_rule: str
    consequence_paragraphs: list[str]
    items: list[ScheduleItem]


def _extract_paragraph_descriptors(text: str) -> list[str]:
    descriptors = []
    for numbers_text, document_tail in _INLINE_PARAGRAPH_GROUP_PATTERN.findall(text):
        document = normalize_whitespace(document_tail)
        for number in _NUMBER_TOKEN_PATTERN.findall(numbers_text):
            descriptors.append(f"Paragraph {number} of the {document}")
    return descriptors


def find_completeness_check_schedule_pages(pages) -> list:
    matches = [
        page
        for page in pages
        if page.has_native_text and "completeness check schedule" in _page_footer_text(page).lower()
    ]
    return sorted(matches, key=lambda p: p.page_number)


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
    if not footer_text:
        return text
    pattern = re.compile(r"^.*?" + re.escape(footer_text) + r"\s*Page\s+\d+\s+of\s+\d+\s*", re.IGNORECASE | re.DOTALL)
    return pattern.sub("", text, count=1)


def parse_completeness_check_schedule(schedule_pages: list) -> list[SchedulePart]:
    # Concatenate all schedule pages into one string, tracking where each page starts,
    # so a lettered item that begins on one page and continues onto the next is still
    # captured whole, while each match can still be attributed back to its real source
    # page - the same problem the reference-resolution work solved for footers, applied
    # here to the schedule's own lettered-item structure.
    combined = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for page in schedule_pages:
        offsets.append((pos, page.page_number))
        text = _strip_page_header(page.native_text or "", _page_footer_text(page))
        combined.append(text)
        pos += len(text) + 1
    full_text = "\n".join(combined)

    part_matches = list(_PART_HEADING_PATTERN.finditer(full_text))
    parts: list[SchedulePart] = []
    for index, part_match in enumerate(part_matches):
        part_letter = part_match.group(1)
        if part_letter not in _IF_BLANK_BY_PART:
            continue  # not one of Part A/B/C (defensive - real data only has these three)
        block_start = part_match.end()
        block_end = part_matches[index + 1].start() if index + 1 < len(part_matches) else len(full_text)
        block_text = full_text[block_start:block_end]

        # The consequence-rule paragraph(s) are cited in the intro sentence, before the
        # first lettered item - not per-item, since every item in this Part shares it.
        first_item_match = _LETTERED_ITEM_PATTERN.search(block_text)
        intro_text = block_text[: first_item_match.start()] if first_item_match else block_text
        consequence_paragraphs = _extract_paragraph_descriptors(intro_text)

        items = _parse_items_in_block(block_text, part_letter, offsets, block_start)

        parts.append(
            SchedulePart(
                part=part_letter,
                consequence_rule=_CONSEQUENCE_RULE_BY_PART[part_letter],
                consequence_paragraphs=consequence_paragraphs,
                items=items,
            )
        )
    return parts


def _parse_items_in_block(block_text: str, part_letter: str, offsets: list[tuple[int, int]], block_offset: int) -> list[ScheduleItem]:
    all_matches = list(_LETTERED_ITEM_PATTERN.finditer(block_text))
    # The intro sentence names its own letter range (e.g. "items (d) to (o) specified
    # below") before the real lettered items start - if that range happens to
    # line-wrap right before the letter, it's indistinguishable from a real item
    # marker by position alone. Confirmed on real data (Tender 3 p204). Since the
    # intro always precedes the real items in these documents, a spurious duplicate
    # is always the earlier occurrence - keep only the last match per letter.
    last_match_by_letter: dict[str, re.Match] = {}
    for match in all_matches:
        last_match_by_letter[match.group(1)] = match
    letter_matches = sorted(last_match_by_letter.values(), key=lambda m: m.start())

    items = []
    for index, letter_match in enumerate(letter_matches):
        letter = letter_match.group(1)
        item_start = letter_match.end()
        item_end = letter_matches[index + 1].start() if index + 1 < len(letter_matches) else len(block_text)
        item_text = normalize_whitespace(block_text[item_start:item_end])
        references = _extract_paragraph_descriptors(item_text)
        source_page = _page_number_at(offsets, block_offset + letter_match.start())
        items.append(
            ScheduleItem(
                letter=letter,
                part=part_letter,
                name=item_text,
                if_blank=_IF_BLANK_BY_PART[part_letter],
                source_page=source_page,
                references_paragraphs=references,
            )
        )
    return items
