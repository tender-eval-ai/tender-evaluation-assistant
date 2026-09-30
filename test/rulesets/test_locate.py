"""L0 locate: the Completeness Check Schedule's items, their Part and the clauses they cite.

The unit tests run on generated text and a hand-built node table (no tender data).
The `realdata` tests read the redacted tenders and answer keys from paths in the
environment and skip without them:

    TENDER_DATA_DIR   folder holding <tender>/招标文件*/ (the tender documents)
    GROUND_TRUTH_DIR  folder holding <tender>.json and deep/<tender>.json
    LOCATE_NODES_DIR  optional cache of parsed nodes, <tender>.json (parsing takes minutes)

    pytest -m realdata test/rulesets/test_locate.py -s
"""
import json
import os
from pathlib import Path

import pytest

from app.parsing.loader import Page
from app.rulesets.locate import (_item_starts, _strip_page_header, find_completeness_check_schedule_pages,
                                 locate, parse_tender)
from app.rulesets.schema import DataClass, ItemStatus, RuleSetItem, Part

FOOTER = "Completeness Check Schedule"


def _page(number, lines, file="02 Schedules.pdf"):
    return Page(source_file=f"/case/tender/{file}", page_number=number, has_native_text=True,
                native_text="\n".join(lines))


def _node(node_id, kind, page, file, number=None, label=None, part=None, doc_name=None, text=""):
    return {"node_id": node_id, "parent_id": node_id.rpartition(":")[0] or None, "kind": kind, "page": page,
            "number": number, "label": label, "title": None, "part": part, "doc_name": doc_name,
            "text": text, "source_file": file}


TERMS = "01 Sample Terms.pdf"
SCHED = "02 Schedules.pdf"

PAGES = [
    _page(1, ["Sample Terms", "3.3 A tender without the documents below is not considered.",
              "Sample Terms of Tender Page 1 of 1"], TERMS),
    _page(1, ["Tender Ref.: SYN-1", f"{FOOTER} Page 1 of 2",
              "Part A", "Items (a) and (b) are required, see Paragraph 3.3 of the Sample Terms of Tender.",
              "(a) The signed offer form.",
              "(b) One sample under Paragraph 5.1 of the Sample Terms of Tender.",
              "Part B", "The Authority may request items (c) to", "(e) below.",
              "(c) The label details in Paragraph 5.2(b) of the Sample Terms of Tender:",
              "(i) the tender reference; and", "(ii) the name.",
              "(d) The company registration, see Paragraph 9.9 of the Sample Terms of Tender."]),
    _page(2, ["Tender Ref.: SYN-1", f"{FOOTER} Page 2 of 2",
              "(e) The delivery plan.", "Part C", "Discretionary items.", "(f) A brochure."]),
]

NODES = [
    _node("T", "document", 1, TERMS),
    _node("T:3.3", "subclause", 1, TERMS, number="3.3", doc_name="Sample Terms of Tender",
          text="3.3 A tender without the documents below is not considered."),
    _node("T:5.1", "subclause", 1, TERMS, number="5.1", doc_name="Sample Terms of Tender", text="5.1 One sample."),
    _node("T:5.2", "subclause", 1, TERMS, number="5.2", doc_name="Sample Terms of Tender", text="5.2 Labels:"),
    _node("T:5.2:(b)", "subitem", 1, TERMS, label="(b)", doc_name="Sample Terms of Tender", text="(b) the name."),
    _node("S", "document", 1, SCHED),
    _node("S:PA", "part", 1, SCHED, number="A", part="Part A", doc_name=FOOTER,
          text="Part A Items (a) and (b) are required, see Paragraph 3.3 of the Sample Terms of Tender."),
    _node("S:PA:(a)", "subitem", 1, SCHED, label="(a)", part="Part A", doc_name=FOOTER,
          text="(a) The signed offer form."),
    _node("S:PA:(b)", "subitem", 1, SCHED, label="(b)", part="Part A", doc_name=FOOTER,
          text="(b) One sample under Paragraph 5.1 of the Sample Terms of Tender."),
    _node("S:PB", "part", 1, SCHED, number="B", part="Part B", doc_name=FOOTER,
          text="Part B The Authority may request items (c) to (e) below."),
    _node("S:PB:(c)", "subitem", 1, SCHED, label="(c)", part="Part B", doc_name=FOOTER,
          text="(c) The label details:"),
    # The citation sits in a sub-item of (c): an item's clauses include its sub-items'.
    _node("S:PB:(c):(i)", "subitem", 1, SCHED, label="(i)", part="Part B", doc_name=FOOTER,
          text="(i) as in Paragraph 5.2(b) of the Sample Terms of Tender; and"),
    _node("S:PB:(d)", "subitem", 1, SCHED, label="(d)", part="Part B", doc_name=FOOTER,
          text="(d) The company registration, see Paragraph 9.9 of the Sample Terms of Tender."),
    # (e) has no node: the layout reading missed it, the page text still has it.
    _node("S:PC", "part", 2, SCHED, number="C", part="Part C", doc_name=FOOTER, text="Part C Discretionary items."),
    _node("S:PC:(f)", "subitem", 2, SCHED, label="(f)", part="Part C", doc_name=FOOTER, text="(f) A brochure."),
]


def _schedule():
    return locate(PAGES, NODES, data_class=DataClass.SYNTHETIC, root=Path("/case"))


def test_every_item_is_found_with_its_part():
    schedule = _schedule()

    assert [(i.letter, i.part) for i in schedule.items] == [
        ("a", Part.A), ("b", Part.A), ("c", Part.B), ("d", Part.B), ("e", Part.B), ("f", Part.C)]
    assert [p.part for p in schedule.parts] == [Part.A, Part.B, Part.C]


def test_an_item_cites_its_own_node_with_a_verbatim_quote():
    item = _schedule().item("b")

    assert item.citation.node_id == "S:PA:(b)"
    assert item.citation.file == "tender/02 Schedules.pdf"
    assert item.citation.page == 1
    assert item.citation.quote.startswith("(b) One sample")
    assert item.citation.data_class == DataClass.SYNTHETIC


def test_cited_paragraphs_resolve_to_their_nodes():
    schedule = _schedule()

    assert [c.node_id for c in schedule.item("b").clauses] == ["T:5.1"]
    assert schedule.item("b").clauses[0].file == "tender/01 Sample Terms.pdf"
    assert [c.node_id for c in schedule.item("c").clauses] == ["T:5.2:(b)"]
    assert [c.node_id for c in schedule.parts[0].clauses] == ["T:3.3"]


def test_a_part_with_no_text_of_its_own_is_quoted_by_its_heading():
    """A quote is checked against the node it cites, so it has to be that node's text:
    a Part heading with no text is quoted by its title, not by its first child."""
    price = "03 Sample Price.pdf"
    pages = [_page(1, ["Tender Ref.: SYN-2", f"{FOOTER} Page 1 of 1", "Part A",
                       "(a) The price, see Part B of the Sample Price Schedule."])]
    nodes = [
        _node("P", "document", 1, price),
        _node("P:PB", "part", 1, price, number="B", doc_name="Sample Price Schedule"),
        _node("P:PB:1", "clause", 1, price, number="1", doc_name="Sample Price Schedule",
              text="1 Payment is made in arrears."),
        _node("S", "document", 1, SCHED),
        _node("S:PA", "part", 1, SCHED, number="A", part="Part A", doc_name=FOOTER, text="Part A"),
        _node("S:PA:(a)", "subitem", 1, SCHED, label="(a)", part="Part A", doc_name=FOOTER,
              text="(a) The price, see Part B of the Sample Price Schedule."),
    ]
    nodes[1]["title"] = "PAYMENT"

    (clause,) = locate(pages, nodes, data_class=DataClass.SYNTHETIC).item("a").clauses

    assert clause.node_id == "P:PB"
    assert clause.quote == "PAYMENT"


def test_a_citation_that_resolves_to_nothing_is_kept_as_written():
    item = _schedule().item("d")

    assert item.clauses == []
    assert item.unresolved == ["Paragraph 9.9 of the Sample Terms of Tender"]


def test_an_item_without_a_node_still_gets_a_page_level_citation():
    item = _schedule().item("e")

    assert item.citation.node_id is None
    assert item.citation.page == 2
    assert item.citation.quote == "(e) The delivery plan."


def test_a_located_item_becomes_a_rule_set_item():
    rule_item = _schedule().item("b").as_rule_set_item()

    assert isinstance(rule_item, RuleSetItem)
    assert rule_item.status == ItemStatus.NEEDS_INPUT
    assert rule_item.part == Part.A and rule_item.template is None
    assert [c.node_id for c in rule_item.clauses] == ["T:5.1"]


def test_no_schedule_footer_means_no_items():
    assert locate(PAGES[:1], NODES, data_class=DataClass.SYNTHETIC).items == []


def test_intro_range_and_roman_sub_items_are_not_items():
    block = "\nThe Authority may request items (c) to\n(e) below.\n(c) first\n(i) sub\n(ii) sub\n(d) second\n(e) third"
    assert [m.group(1) for m in _item_starts(block)] == ["c", "d", "e"]
    # A last item's roman sub-items: "(i)" is followed by "(ii)", so it is not item (i).
    assert [m.group(1) for m in _item_starts("\n(g) last\n(i) sub\n(ii) sub")] == ["g"]
    # A real item (i) right after (h)'s sub-items still counts.
    assert [m.group(1) for m in _item_starts("\n(h) x\n(i) sub\n(ii) sub\n(i) real\n(j) y")] == ["h", "i", "j"]


def test_a_deep_roman_sub_list_does_not_fabricate_items_v_and_x():
    """(v) and (x) are roman numerals too, on a schedule whose items reach (u)."""
    sub_list = "\n(i) sub\n(ii) sub\n(iii) sub\n(iv) sub\n(v) sub"
    assert [m.group(1) for m in _item_starts(f"\n(s) x\n(t) y\n(u) z{sub_list}")] == ["s", "t", "u"]
    assert [m.group(1) for m in _item_starts("\n(g) x\n(viii) sub\n(ix) sub\n(x) sub")] == ["g"]
    # A real item (v) or (x), with no roman sub-list before it, still counts.
    assert [m.group(1) for m in _item_starts("\n(t) a\n(u) b\n(v) c\n(w) d")] == ["t", "u", "v", "w"]


def test_a_label_on_a_pages_first_line_is_still_the_page_footer():
    """The loader strips a page's extracted text, so the label that names the document
    has no newline before it when the text layer puts it first."""
    first_line = _page(1, [f"{FOOTER} Page 1 of 1", "Part A", "(a) The signed offer form."])

    assert find_completeness_check_schedule_pages([first_line]) == [first_line]
    assert [i.letter for i in locate([first_line], [], data_class=DataClass.SYNTHETIC).items] == ["a"]


def test_page_header_is_stripped_only_when_it_is_a_header():
    top = f"Tender Ref.: SYN-1\n{FOOTER} Page 1 of 2\nPart A\n(a) x"
    assert _strip_page_header(top, FOOTER) == "Part A\n(a) x"
    bottom = f"Part A\n(a) x\n{FOOTER} Page 1 of 2"
    assert _strip_page_header(bottom, FOOTER).split() == ["Part", "A", "(a)", "x"]


def test_generated_pdf_end_to_end(tmp_path):
    """The real pipeline on a generated two-file tender: loader, layout parser, locate."""
    from tools.pdfgen import LINES_PER_PAGE, make_text_pdf

    def page(lines, footer):
        spaced = [x for line in lines for x in (line, "")]
        return spaced + [""] * (LINES_PER_PAGE - 1 - len(spaced)) + [footer]

    (tmp_path / "tender").mkdir()
    make_text_pdf(tmp_path / "tender" / TERMS,
                  page(["Sample Terms of Tender", "5. Samples", "5.1 The Tenderer shall supply one sample."],
                       "Sample Terms of Tender Page 1 of 1"))
    schedule_lines = [FOOTER, "Part A", "Items (a) and (b) below are required.",
                      "(a) The signed offer form.",
                      "(b) One sample under Paragraph 5.1 of the Sample Terms of Tender.",
                      "Part B", "Items (c) may be requested.", "(c) A brochure."]
    make_text_pdf(tmp_path / "tender" / SCHED, page(schedule_lines, f"{FOOTER} Page 1 of 1"))
    pages, nodes = parse_tender([tmp_path / "tender" / TERMS, tmp_path / "tender" / SCHED])

    schedule = locate(pages, nodes, data_class=DataClass.SYNTHETIC)

    assert [(i.letter, i.part) for i in schedule.items] == [("a", Part.A), ("b", Part.A), ("c", Part.B)]
    assert all(i.citation.node_id for i in schedule.items)
    assert [c.quote[:41] for c in schedule.item("b").clauses] == ["5.1 The Tenderer shall supply one sample."]
    # Without a root, a file is still named the way app.ingest.Document.path names it,
    # from the relative path parse_tender recorded.
    assert schedule.item("b").citation.file == f"tender/{SCHED}"
    assert [c.file for c in schedule.item("b").clauses] == [f"tender/{TERMS}"]
    # A root the caller gives still wins.
    assert locate(pages, nodes, data_class=DataClass.SYNTHETIC,
                  root=tmp_path / "tender").item("b").citation.file == SCHED


# ---------------------------------------------------------------- real tenders

def _tender(n: int) -> str:
    """Tender n's folder name. The real tender numbers stay outside git (F6), so
    TENDER_IDS lists them, comma-separated, Tender 1 first."""
    ids = [t for t in os.environ.get("TENDER_IDS", "").split(",") if t]
    if len(ids) < n:
        pytest.skip("TENDER_IDS not set; real tender names stay outside git")
    return ids[n - 1]


def _env_dir(name: str) -> Path:
    value = os.environ.get(name)
    if not value or not Path(value).is_dir():
        pytest.skip(f"{name} not set; real tender data stays outside git")
    return Path(value)


def _tender_pdfs(tender: str) -> list[Path]:
    folders = sorted((_env_dir("TENDER_DATA_DIR") / tender).glob("招标文件*"))
    pdfs = sorted(p for folder in folders for p in folder.rglob("*.pdf"))
    if not pdfs:
        pytest.skip(f"no tender PDFs for {tender}")
    return pdfs


def _parsed(tender: str, pdfs: list[Path]):
    cache_dir = os.environ.get("LOCATE_NODES_DIR")
    cache = Path(cache_dir) / f"{tender}.json" if cache_dir else None
    if cache and cache.exists():
        from app.parsing.loader import load_pdf
        return [p for pdf in pdfs for p in load_pdf(pdf)], json.loads(cache.read_text())
    pages, nodes = parse_tender(pdfs)
    if cache:
        cache.write_text(json.dumps(nodes, ensure_ascii=False))
    return pages, nodes


def _expected(tender: str, truth: Path) -> tuple[dict, dict]:
    """{letter: (part, page)} and {cited by: [reference]} from the checklist key, or
    from the deep key's level-0 rows when a tender has no checklist key."""
    key_path = truth / f"{tender}.json"
    if key_path.exists():
        key = json.loads(key_path.read_text())
        items = {i["letter"]: (i["part"], i["page"]) for i in key["items"]}
        refs: dict[str, list] = {}
        for ref in key["references"]:
            for citer in ref["cited_by"]:
                letter = citer if len(citer) == 1 else f"Part {citer.split()[1]}"
                refs.setdefault(letter, []).append(("key", ref))
        return items, refs
    deep = json.loads((truth / "deep" / f"{tender}.json").read_text())
    items, refs = {}, {}
    for node in deep["nodes"]:
        segments = node["node_id"].split(":")
        if node["level"] == 0 and len(segments) == 3 and segments[2].startswith("Item("):
            items[segments[2][5:-1]] = (segments[1][-1], node["page"][0])
    for node in deep["nodes"]:
        if node["level"] != 1 or ":field:" in node["node_id"]:
            continue
        for citer in node.get("cited_via") or []:
            if citer.startswith("CCS:Part"):
                segments = citer.split(":")
                letter = segments[2][5:-1] if len(segments) == 3 else f"Part {segments[1][-1]}"
                refs.setdefault(letter, []).append(("deep", node))
    return items, refs


@pytest.mark.realdata
@pytest.mark.parametrize("n", [1, 2, 3])
def test_real_tender_items_parts_and_clauses(n):
    from test.rulesets.checklist_key import candidates
    from tools.eval_parser import match_deep_key

    truth = _env_dir("GROUND_TRUTH_DIR")
    tender = _tender(n)
    pdfs = _tender_pdfs(tender)
    pages, nodes = _parsed(tender, pdfs)
    expected_items, expected_refs = _expected(tender, truth)

    schedule = locate(pages, nodes, data_class=DataClass.REDACTED_SAMPLE)
    found = {i.letter: i for i in schedule.items}
    parts = {p.part.value: p for p in schedule.parts}

    # The reference nodes each key row should resolve to, found the way the parser
    # evaluator finds them (tools/eval_parser.py).
    single_file = len(pdfs) == 1
    deep_match = {}
    if any(kind == "deep" for rows in expected_refs.values() for kind, _ in rows):
        deep_key = json.loads((truth / "deep" / f"{tender}.json").read_text())
        deep_match = {k: (m["node"] or {}).get("node_id")
                      for k, m in match_deep_key(deep_key["nodes"], nodes, single_file).items()}
    by_id = {n["node_id"]: n for n in nodes}

    def first_text_node(node_id):
        # A whole-document or heading target is found as its first text node. A
        # document's own text and its unnumbered headings are only its title and
        # preamble, so a whole-document target is found as its first marked node.
        whole = by_id[node_id]["kind"] in ("document", "subdocument")
        for n in nodes:
            if whole:
                inside = n["node_id"].startswith(f"{node_id}:") and (n.get("number") or n.get("label"))
            else:
                inside = n["node_id"] == node_id or n["node_id"].startswith(f"{node_id}:")
            if inside and (n.get("text") or "").strip():
                return n["node_id"]
        return None

    def deep_hit(ref, clause_ids):
        # The evaluator finds a key node by its marker path, or by its marked ancestor
        # and first words; when that finds nothing, fall back to the marker on the page.
        want = deep_match.get(ref["node_id"])
        segment = ref["node_id"].split(":")[-1]
        if segment == "title":
            # A whole-document target: any clause in that document's file.
            file = by_id[want]["source_file"] if want else ref.get("file")
            return any(by_id[c]["source_file"] == file for c in clause_ids)
        if want is not None:
            if want in clause_ids or any(first_text_node(c) == want for c in clause_ids):
                return True
            # The deep key expands a whole-document citation into the document's Parts.
            return segment.startswith(("Part", "Table")) and any(
                by_id[c]["kind"] in ("document", "subdocument") and want.startswith(f"{c}:") for c in clause_ids)
        marker = segment.removeprefix("Part").removeprefix("Table")
        return any(by_id[c].get("page") == ref["page"][0]
                   and marker in (by_id[c].get("number"), by_id[c].get("label")) for c in clause_ids)

    def hit(kind, ref, clause_ids):
        if kind == "deep":
            return deep_hit(ref, clause_ids)
        want = {n["node_id"] for n in candidates(nodes, ref, ref["pages"], single_file)
                + candidates(nodes, ref, ref.get("alt_pages"), single_file)}
        return bool(want & clause_ids) or any(first_text_node(c) in want for c in clause_ids)

    refs_ok = refs_total = 0
    missed = []
    for citer, rows in expected_refs.items():
        located = parts.get(citer.split()[-1]) if citer.startswith("Part") else found.get(citer)
        clause_ids = {c.node_id for c in located.clauses} if located else set()
        for kind, ref in rows:
            refs_total += 1
            if hit(kind, ref, clause_ids):
                refs_ok += 1
            else:
                missed.append(f"{citer}->{ref.get('clause_id') or ref['node_id']}")

    part_ok = sum(found[letter].part.value == part for letter, (part, _) in expected_items.items() if letter in found)
    page_ok = sum(found[letter].citation.page == page for letter, (_, page) in expected_items.items()
                  if letter in found)
    own_node = sum(found[letter].citation.node_id is not None for letter in expected_items if letter in found)
    print(f"\n{tender}: items {len(set(found) & set(expected_items))}/{len(expected_items)}"
          f" (extra {sorted(set(found) - set(expected_items))}), Part {part_ok}/{len(expected_items)},"
          f" page {page_ok}/{len(expected_items)}, own node {own_node}/{len(expected_items)},"
          f" cited clauses {refs_ok}/{refs_total}; missed {missed}")

    assert sorted(found) == sorted(expected_items)
    assert part_ok == len(expected_items)
    assert page_ok == len(expected_items)
    # Measured 2026-09-17: 45/49, 41/43, 58/65; 2026-09-18, after the third parser
    # pass: 45/49, 43/43, 63/65; 2026-09-29, matching deep keys by marker path: 45/49,
    # 39/43, 56/65. The misses left are deep-key links the row does not write out,
    # the Tender Form of the combined PDF, which no scope is named after, and the
    # Particulars of Goods Schedule rows the parser nests under row 1; see
    # docs/evals/parser_l0.md.
    assert refs_ok >= 0.85 * refs_total
