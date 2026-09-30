# Parser (L0) and citation evaluation

Two separate questions, scored by `tools/eval_parser.py` on three real tenders:

1. **Parser recall.** Does `app/parsing` produce every node the answer key lists?
2. **Citation resolution.** Does `app/parsing/citations.py`, over the parser's node table, resolve each of the tender's own citations to exactly one node?

They are kept apart so a miss points at the layer to fix: a clause the parser never produced is a parser miss, not a citation miss. The keys and PDFs are redacted sample documents and stay outside git; this file records numbers only.

## 1. Parser recall

**Denominator:** every node in the tender's deep key (below).

**A key node with a marker path** is found when a parser node:

- is in the same document (the same file; in a combined PDF, the page decides),
- starts on the key node's first page, and
- has an id ending with the same marker path.

A marker is what the document prints to name a piece of text: `3.3`, `(a)`, `Part A`, `Table B`, a numbered row `2.`. The path is the chain of them: key `ToT:3.3(a)(i)` ↔ parser `…:P1:3.3:(a):(i)`; key `InfoSchedule:TableB:Row(c)` ↔ parser `…:PB:(c)`. A whole document (key `NCTC`) is found as a document or sub-document node on its first page.

**A key node with no marker path** (a heading, a "Notes:" line, a note, a form field, a glossary or other tail) has an invented name on both sides (key `TechSpec:2:Glossary`, parser `…:2:tail`), so names cannot be compared. It is found when a parser node:

- sits inside the parser node matched to the key node's nearest marked ancestor (at any depth),
- starts on the key node's first page, and
- opens with the key node's first words (the first 24 characters without spaces, within 12 characters of the start).

If that ancestor was not found, the node is not found. A key node with no marked ancestor (a document's title) is looked for on its page alone. Notes are counted here although they print a marker: the key nests them under a `Notes` level, the parser under the clause or item above, and a note's `(i)` often repeats an item's.

**Recall = found ÷ key nodes**, reported for all nodes, marked nodes and unmarked nodes.

## 2. Citation resolution

**Denominator:** every citation `parse_citations` finds in the page text of the tender's own PDFs (for example "Paragraph 20.2 of the Terms of Tender"). No hand labelling: the tender's cross-references grade the resolver, as AI_camp's `test_citations.py` did.

Each citation is resolved by `CitationIndex.resolve_citation` over the parser's nodes and is one of:

- **unique**: exactly one node (success),
- **ambiguous**: several nodes,
- **unresolved**: no node.

**Score = unique ÷ all citations.** It measures that a citation lands on one node, not that the node is the right one; the resolver's tests (`test/parsing/test_citations.py`) pin the right node for the forms the tenders use.

## Answer keys (deep keys)

Built without any parser code, following the depth of AI_camp's 458-node key for Tender 1: every Completeness Check Schedule Part intro and item (level 0), every section they cite expanded to its deepest sub-item, with forms and tables expanded to rows, fields and notes (level 1), sections cited inside those expanded the same way (level 2), and citations one step further recorded as leaves (level 3). Each node has its file, page range, first words and parent. Tender 1's key is AI_camp's, converted; the other two were built on 2026-09-17 by five independent agents per tender and a combiner that settled disagreements from the PDF text. **Not yet verified by Nasi.**

| Tender | Documents | Pages | Key nodes | Level 0 | Level 1 | Level 2 | Level 3 |
|---|---|---|---|---|---|---|---|
| Tender 1 | 17 files | 236 | 454 | 18 | 359 | 77 | 0 |
| Tender 2 | 12 files | 222 | 756 | 18 | 389 | 296 | 53 |
| Tender 3 | 25 inside one PDF | 366 | 1582 | 27 | 594 | 883 | 78 |

The key covers what the Completeness Check Schedule reaches, not whole tenders: sections nothing cites (most of the General Conditions of Contract) are not scored.

## How to run

```
python tools/eval_parser.py --deep-key <ground_truth>/deep/<tender>.json \
    --pdfs <the tender's folder of PDFs, or its combined PDF> \
    [--nodes <cache>.json] [--out <report>.json]
```

`--out` writes every key node (found or not, and why) and every citation (outcome and nodes) as JSON. The reports behind the numbers below are kept with the private data in `parser_eval/2026-09-29/`.

## Results (2026-09-29)

Fresh parse at `d64a66d` (`main` at `ba3ebcd` plus the citation-list fix).

| Tender | Parser recall | Marked | Unmarked | Citations unique | Ambiguous | Unresolved |
|---|---|---|---|---|---|---|
| Tender 1 | **444/454 97.8%** | 377/377 100% | 67/77 87.0% | **469/520 90.2%** | 14 | 37 |
| Tender 2 | **718/756 95.0%** | 602/623 96.6% | 116/133 87.2% | **531/566 93.8%** | 14 | 21 |
| Tender 3 | **1441/1582 91.1%** | 1216/1265 96.1% | 225/317 71.0% | **697/801 87.0%** | 24 | 80 |

**Accepted (Nasi, 2026-09-29):** we are happy with these results, and they are the numbers the README quotes. No further parser or citation work is planned. Known limitations from the #104 review, left as they are:

- Since `81ec4c1` a table of numbered paragraphs is nested under its first row where that row opened the clause (Tender 2's Particulars of Goods Table A: rows 2–4 under row 1), so "Paragraph 2 of Table A" does not resolve there. Tender 1's rows are nested under "1. Particulars of Offer" as the key has them, but "Paragraph 4 of the Particulars of Goods Schedule" does not resolve to them either. `test_locate`'s cited-clause counts (39/43, 56/65) include these misses.
- Marker paths are matched by their ending only, so a node in the wrong place can count as found; marked recall may be slightly high.
- A citation counts as resolved when it lands on exactly one node; that node is not checked for being the right one.

A fix for the first two was drafted and tested but not applied.

### What the parser misses

Marked nodes, all parser structure rather than missing text:

- **Particulars of Goods Schedule tables:** rows 2, 3, 4 of each table are nested under row 1 instead of beside it (Tenders 2 and 3).
- **Items under the wrong parent:** Terms of Tender 14.1(b)(i)–(iii) under (c); Special Conditions 16(h)(i)–(iv), 16(j), 16(k) under an earlier item (Tender 2).
- **3.15 not split** into 3.15.1 and 3.15.2 (Tenders 2 and 3), as in AI_camp.
- **Compliance Schedule Part B (b):** the per-location rows (Tender 2).
- **Tender 3 Price Schedule:** its numbered tables (Table 1, 1A and its rows, Table 2, Part D Tables 1–3) have no nodes of their own (13); also Information Schedule rows (9) and items of Annex C to the Special Conditions (4).

Unmarked nodes: the text is on the page but the parser placed it outside the marked ancestor the key names, most often a note hung under a Part's last item rather than the Part, or an Information Schedule row (9, 17 and 49 nodes); and, on Tender 3, content whose marked ancestor is itself missing (39: the Price Schedule tables above, and the booklet's Annex A).

### What the citations miss

Grouped by cause, from the `--out` rows; not fixed here:

- page headers and contents lists read as citations ("Annex A to the Terms of Tender (Supplement) Page 1 of 3" on every page);
- the English and Chinese Tender Form, both with a Part 4 ("Part 4 of the Tender Form" is ambiguous); in Tender 3's combined PDF "Tender Form" names no document;
- a numbered part inside a clause ("Parts 2(a) and 2(b) of Clause 3 of the Technical Specifications");
- names that run on ("Special Conditions of Contract Page", "Compliance Schedule the Tenderer") or are unknown ("Interpretation Section of the Standard Terms and Conditions");
- the parser gaps above (3.15.1, the Price Schedule tables);
- genuine ambiguity: Tender 3 bundles three Special Conditions of Contract, and "Clause 4 of the Special Conditions of Contract" does not say which.

## Retired

Until 2026-09-29 this file recorded a four-metric benchmark (`recall`, `page_correct`, `char_correct`, `exact_location_correct`, from `tools/benchmark.py`) with first-words matching, plus checklist-level coverage, position, length, citation and document-split scores and diagnostics (kind, hierarchy, length ratio). They were retired because three of the four read the same number by construction and first-words matching counted a node in the wrong place as found. The per-commit history they recorded is in git (`git show ba3ebcd:docs/evals/parser_l0.md`).
