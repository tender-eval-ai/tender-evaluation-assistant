# Parser (L0) evaluation

How well `app/parsing` turns the tender PDFs into a node table, scored with `tools/eval_parser.py` against the answer keys for the two tenders held out when the parser was ported (fixes since then were driven by failures found on them, so they are no longer unseen). The keys and PDFs are redacted sample documents and stay outside git; this file records numbers only.

## Answer keys

Built on 2026-09-16 without any parser code: five independent agents per tender plus an earlier draft, merged by a combiner that settled every disagreement from the PDF text. Not yet verified by Nasi.

| Tender | Documents | Pages | Schedule items (A/B/C) | Part intros | References |
|---|---|---|---|---|---|
| Tender 2 | 12 files | 222 | 13 (3/7/3) | 3 | 40 |
| Tender 3 | 25 inside one PDF | 366 | 21 (3/12/6) | 3 | 64 |

### Deep keys (node level)

Built on 2026-09-17 the same way, following the depth of AI_camp's 458-node key for Tender 1: every Part intro and item, every cited section expanded to its deepest sub-item (run-in sub-items inside a sentence included), forms and tables expanded to rows, fields and notes, sections cited inside those expanded the same way (level 2), and citations one step further recorded as leaves (level 3). Each node has its page range, own-text length, first words and parent. Not yet verified by Nasi.

| Tender | Nodes | Level 0 | Level 1 | Level 2 | Level 3 | Candidates |
|---|---|---|---|---|---|---|
| Tender 2 | 756 | 18 | 389 | 296 | 53 | 5 (708–760 nodes) |
| Tender 3 | 1582 | 27 | 594 | 883 | 78 | 5 (1337–1522 nodes), combined in two halves |

## Metrics

| Metric | Scored on | Correct when |
|---|---|---|
| coverage | schedule entries, references | a node exists for the entry, in the right file, starting inside the entry's pages |
| page | schedule entries, references | that node starts on the entry's first page |
| position | schedule entries, references | the node's text starts with its own marker and that text is on the page |
| length | schedule entries | node length within 10% of the key's character count |
| length | references | the node's subtree ends on the entry's last page |
| citation | references | `CitationIndex.resolve_text` on the citation as written returns that node |
| own node | deep-key nodes | a parser node starts with the key node's first words on its first page |
| reachable | deep-key nodes | the key node's first words are inside some parser node on that page (merged or not) |
| length (deep) | deep-key nodes | the parser node's text is within 10% of the key node's own-text length |
| parent | deep-key nodes | the parser node's parent is the node matched to the key node's parent |
| split | combined PDFs | document start pages found (recall, precision) |

Earlier evaluation in AI_camp (`retrieval_eval/traceability_groundtruth_eval_2.md`, Tender 1 only): 241 rule citations resolved by hand against the node table, page 99.2%, characters 99.2%, exact location 97.9%. It did not measure coverage against an independent key, the automatic citation resolver, section extent or the document split.

## Results

Target: every metric at or above 90% on both tenders, with no regression on Tender 1.

### Baseline: `Bidding-AI-expert@7e8e273`, unchanged (2026-09-16)

| Metric | Tender 2 | Tender 3 |
|---|---|---|
| schedule coverage | 16/16 100.0% | 22/24 91.7% |
| schedule page | 16/16 100.0% | 22/24 91.7% |
| schedule position | 16/16 100.0% | 21/24 87.5% |
| schedule length | 15/16 93.8% | 21/24 87.5% |
| references coverage | 35/40 87.5% | 58/64 90.6% |
| references citation | 20/40 50.0% | 26/64 40.6% |
| references page | 35/40 87.5% | 58/64 90.6% |
| references position | 34/40 85.0% | 56/64 87.5% |
| references length | 31/40 77.5% | 52/64 81.2% |
| split recall | — | 23/25 92.0% |
| split precision | — | 23/23 100.0% |

Main causes: the resolver only understands "Paragraph N of the X" (Tables, schedule Parts, appendix parts and whole documents all miss); a standalone file's document node has no page; sub-document nodes have no children, so a schedule's extent is unknown; "Part IA"/"Part IB" are not Parts; items (j) and (k) of one schedule merge into (i); the Chinese Tender Form and the bundled TERMS-1 booklet are not split out.

### Per commit on `port/parser`, both keys (2026-09-17)

The first improvement pass ran before the deep keys existed and was stopped so the node-level baseline could be measured first. Every column is scored with the current evaluator; the checklist-level baseline is slightly higher than the table above because commit `79c106a` fixed how "part (N)" references are scored.

Columns: `a45f300` unchanged port · `93f0ab7` document node page · `e14f121` Parts under their sub-document · `b6a69cb` block lines by vertical overlap · `96857ed` resolver for Tables/Parts/rows/annexes/whole documents · `11ae315` split blocks at a marker in the marker column · `6bca266` table blocks split into rows from the detected grid, read cell by cell (measured with `9877109`, which changes only the evaluator).

**Tender 2**

| Metric | a45f300 | 93f0ab7 | e14f121 | b6a69cb | 96857ed | 11ae315 | 6bca266 |
|---|---|---|---|---|---|---|---|
| schedule coverage / page / position | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 |
| schedule length | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 |
| references coverage / page | 92.5 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 |
| references position | 90.0 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 | 95.0 |
| references length | 82.5 | 85.0 | 90.0 | 90.0 | 90.0 | 90.0 | 87.5 |
| references citation | 50.0 | 50.0 | 50.0 | 50.0 | 87.5 | 87.5 | 87.5 |
| deep own node / page | 79.5 | 79.5 | 79.5 | 80.7 | 80.7 | 80.8 | 85.1 |
| deep reachable | 93.3 | 93.3 | 93.3 | 94.7 | 94.7 | 94.7 | 96.3 |
| deep length | 71.7 | 71.7 | 71.7 | 72.9 | 72.9 | 73.0 | 78.2 |
| deep parent | 68.0 | 68.0 | 68.0 | 68.4 | 68.4 | 68.4 | 70.8 |

**Tender 3**

| Metric | a45f300 | 93f0ab7 | e14f121 | b6a69cb | 96857ed | 11ae315 | 6bca266 |
|---|---|---|---|---|---|---|---|
| schedule coverage / page | 91.7 | 91.7 | 91.7 | 91.7 | 91.7 | 100 | 100 |
| schedule position | 87.5 | 87.5 | 87.5 | 91.7 | 91.7 | 100 | 100 |
| schedule length | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 100 | 100 |
| references coverage / page | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 |
| references position | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 89.1 |
| references length | 81.2 | 81.2 | 82.8 | 82.8 | 82.8 | 82.8 | 85.9 |
| references citation | 40.6 | 40.6 | 40.6 | 40.6 | 84.4 | 84.4 | 84.4 |
| split recall / precision | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 |
| deep own node / page | 70.2 | 70.2 | 70.2 | 70.8 | 70.8 | 71.0 | 82.9 |
| deep reachable | 83.9 | 83.9 | 83.9 | 84.5 | 84.5 | 84.5 | 94.9 |
| deep length | 64.2 | 64.2 | 64.2 | 64.7 | 64.7 | 65.0 | 75.9 |
| deep parent | 48.6 | 48.6 | 48.6 | 49.2 | 49.2 | 49.9 | 53.2 |

Up to `11ae315` no commit lowers any metric; the resolver commit is the only large gain (citation +37 and +44 points), and the structural commits move the deep metrics by under 1.5 points. `6bca266` raises deep own node by 4.3 and 11.9 points but lowers Tender 2's references length (90.0 → 87.5) and fails Tender 1's no-regression table (125/142 nodes still correct, from 142); both are recovered by the commits below.

**Deep baseline by document** (unchanged port, own node / parent, %):

| Tender 2 | Nodes | Own | Parent | Tender 3 | Nodes | Own | Parent |
|---|---|---|---|---|---|---|---|
| SCC | 165 | 90.3 | 83.6 | TechSpec | 269 | 90.0 | 46.8 |
| ToT | 151 | 86.1 | 85.4 | InfoSchedule | 178 | 20.8 | 10.7 |
| TermsSupp | 79 | 94.9 | 94.9 | ToT | 154 | 84.4 | 83.8 |
| GCC | 78 | 92.3 | 89.7 | TermsSupp | 113 | 88.5 | 88.5 |
| ComplianceSchedule | 62 | 74.2 | 32.3 | AnnexSCCB | 112 | 96.4 | 90.2 |
| InfoSchedule | 55 | 56.4 | 43.6 | SCC | 83 | 92.8 | 78.3 |
| NCTC | 33 | 66.7 | 48.5 | AttTechSpec | 82 | 0.0 | 0.0 |
| PriceSchedule | 25 | 84.0 | 36.0 | GCC | 77 | 98.7 | 97.4 |
| POGS | 19 | 89.5 | 42.1 | PriceSchedule | 75 | 57.3 | 16.0 |
| CCS | 18 | 88.9 | 88.9 | AnnexSCCC | 72 | 87.5 | 75.0 |
| TechSpec | 17 | 11.8 | 5.9 | ComplianceSchedule | 64 | 90.6 | 32.8 |
| AppendixToT | 14 | 28.6 | 28.6 | ISS | 52 | 50.0 | 3.8 |
| AnnexToTA | 14 | 21.4 | 0.0 | AnnexToTA | 50 | 60.0 | 20.0 |
| TenderForm-EN | 13 | 76.9 | 30.8 | POGS | 47 | 66.0 | 23.4 |
| TenderForm-ZH | 13 | 23.1 | 0.0 | NCTC | 34 | 64.7 | 47.1 |

By level (unchanged port, own / length / parent): Tender 2 L1 74.0 / 65.6 / 55.8, L2 82.8 / 75.3 / 78.0; Tender 3 L1 56.4 / 48.5 / 33.5, L2 77.0 / 72.0 / 54.1. Numbered terms documents (ToT, Supplement, GCC, SCC and its annexes) are at 84–99% own node; tables, forms and schedules are where nodes are missing and parents are wrong (the Information Schedule, glossary attachment, Innovative Suggestion Schedule, Price Schedule, Particulars of Goods, Annex A, Appendix, Chinese Tender Form).

### Second pass on tables, forms and the document split (2026-09-17)

Every column is scored with the evaluator as of `1770505`, which adds two evaluator fixes to `9877109`: `e5458c0` matches a Completeness Check Schedule item to a direct child of its Part (a sub-item with the same label no longer stands in for it) and `738d38c` judges exact location by a node's own marker rather than its enclosing Part's name; neither lowers any earlier score. The first five deep rows are AI_camp's metric names (`c2b4107`); "reachable", "length (within 10%)" and "parent" are the definitions used in the tables above, scored with the evaluator as of `22e840a`. Tender 1 has no checklist key and is scored on its deep key (454 nodes, converted from AI_camp's hand-built key).

Columns: `11ae315` and `6bca266` as above · `6410fa2` a paragraph in a nested list's marker column closes only that list · `582fc37` sub-items listed inside one sentence become nodes · `14dee7e` text before a document's first marker is the document's own text · `0b9b82a` document split from page numbering printed above/below the name or in Chinese · `5dfdb0b` "Notes:" split from a first note numbered by letter or roman numeral · `b304107` "Part IA"/"Part IB" are Parts · `56dfa87` a heading with no marker is its own node · `ee8cd7b` a "picture" carrying its own text layer is read as a table · `1770505` a table row keyed by a bare number carries that number.

**Tender 2**

| Metric | 11ae315 | 6bca266 | 6410fa2 | 582fc37 | 14dee7e | 0b9b82a | 5dfdb0b | b304107 | 56dfa87 | ee8cd7b | 1770505 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule coverage / page / position | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| schedule length | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 |
| references coverage / page | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 100 | 100 | 100 | 100 |
| references position | 92.5 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 100 | 100 | 100 | 100 |
| references length | 90.0 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 92.5 | 92.5 | 92.5 | 92.5 |
| references citation | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 92.5 | 92.5 | 92.5 | 92.5 |
| deep recall (= own node, page) | 80.8 | 85.1 | 85.2 | 91.5 | 91.8 | 91.8 | 92.3 | 92.5 | 93.0 | 93.1 | 93.1 |
| deep exact_location_correct | 75.4 | 81.3 | 81.5 | 87.8 | 87.8 | 87.8 | 88.6 | 88.6 | 89.2 | 89.2 | 89.2 |
| deep kind_correctness | 89.4 | 91.5 | 91.5 | 98.8 | 98.8 | 98.8 | 99.1 | 99.4 | 99.4 | 99.4 | 99.4 |
| deep hierarchy_correctness | 65.0 | 67.7 | 69.5 | 76.4 | 76.5 | 76.5 | 76.7 | 77.0 | 77.0 | 77.1 | 77.1 |
| deep avg_node_length_ratio | 1.75 | 1.62 | 1.61 | 1.53 | 1.54 | 1.54 | 1.53 | 1.52 | 1.51 | 1.51 | 1.51 |
| deep reachable | 94.7 | 96.3 | 96.3 | 96.3 | 97.5 | 97.5 | 97.5 | 97.5 | 97.5 | 97.6 | 97.6 |
| deep length (within 10%) | 73.0 | 78.2 | 78.3 | 84.7 | 84.7 | 84.7 | 85.4 | 85.4 | 86.1 | 86.1 | 86.1 |
| deep parent | 68.4 | 70.8 | 72.4 | 78.6 | 78.7 | 78.7 | 78.8 | 79.1 | 79.2 | 79.4 | 79.4 |

**Tender 3**

| Metric | 11ae315 | 6bca266 | 6410fa2 | 582fc37 | 14dee7e | 0b9b82a | 5dfdb0b | b304107 | 56dfa87 | ee8cd7b | 1770505 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule coverage / page / position | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| schedule length | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| references coverage / page | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 96.9 |
| references position | 87.5 | 89.1 | 89.1 | 89.1 | 89.1 | 89.1 | 89.1 | 89.1 | 89.1 | 89.1 | 95.3 |
| references length | 82.8 | 85.9 | 85.9 | 85.9 | 85.9 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 92.2 |
| references citation | 84.4 | 84.4 | 84.4 | 84.4 | 84.4 | 84.4 | 84.4 | 84.4 | 84.4 | 84.4 | 90.6 |
| split recall / precision | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 |
| deep recall (= own node, page) | 71.0 | 82.9 | 83.1 | 88.1 | 89.0 | 89.0 | 89.6 | 89.6 | 90.6 | 90.8 | 90.8 |
| deep exact_location_correct | 67.1 | 80.2 | 80.3 | 85.3 | 85.3 | 85.3 | 86.0 | 86.0 | 87.0 | 87.2 | 87.2 |
| deep kind_correctness | 87.1 | 90.8 | 90.8 | 97.3 | 97.6 | 97.6 | 98.0 | 98.0 | 98.0 | 98.0 | 98.0 |
| deep hierarchy_correctness | 45.8 | 49.4 | 50.0 | 55.2 | 63.7 | 63.7 | 63.7 | 63.7 | 64.8 | 65.0 | 65.0 |
| deep avg_node_length_ratio | 1.78 | 1.59 | 1.58 | 1.59 | 1.60 | 1.57 | 1.57 | 1.57 | 1.61 | 1.61 | 1.61 |
| deep reachable | 84.5 | 94.9 | 94.9 | 94.9 | 96.5 | 96.5 | 97.2 | 97.2 | 97.3 | 97.6 | 97.6 |
| deep length (within 10%) | 65.0 | 75.9 | 76.1 | 80.1 | 80.3 | 80.3 | 80.9 | 80.9 | 81.9 | 82.0 | 82.0 |
| deep parent | 49.9 | 53.2 | 53.7 | 58.5 | 66.9 | 66.9 | 66.9 | 66.9 | 67.8 | 68.0 | 68.0 |

**Tender 1**

| Metric | 11ae315 | 6bca266 | 6410fa2 | 582fc37 | 14dee7e | 0b9b82a | 5dfdb0b | b304107 | 56dfa87 | ee8cd7b | 1770505 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| deep recall (= own node, page) | 90.7 | 91.2 | 91.4 | 91.4 | 91.9 | 91.9 | 91.9 | 91.9 | 92.3 | 92.5 | 92.5 |
| deep exact_location_correct | 81.9 | 85.9 | 86.1 | 86.1 | 86.1 | 86.1 | 86.1 | 86.1 | 86.6 | 86.6 | 86.6 |
| deep kind_correctness | 97.2 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 |
| deep hierarchy_correctness | 75.6 | 74.5 | 76.4 | 76.4 | 76.4 | 76.4 | 76.4 | 76.4 | 76.4 | 76.7 | 76.7 |
| deep avg_node_length_ratio | 1.12 | 1.09 | 1.08 | 1.08 | 1.11 | 1.11 | 1.11 | 1.11 | 1.11 | 1.11 | 1.11 |

No commit after `6bca266` lowers any metric on any of the three tenders. Tender 1's no-regression table (AI_camp's 142 hand-checked nodes, page and length within 10%): 142/142 at `11ae315`, 125/142 at `6bca266`, 141/142 from `6410fa2` on; the one left is a paragraph after a nested list that the table counts in the list's last item and the parser gives to the item holding the list. Its node count is 1583 at `11ae315` and 1882 at `1770505`, and its Completeness Check Schedule still parses to Parts A-C with items (a)-(o).

**Deep recall / hierarchy by document**, `6bca266` → `1770505` (%):

| Tender 2 | Nodes | Recall | Hierarchy | Tender 3 | Nodes | Recall | Hierarchy |
|---|---|---|---|---|---|---|---|
| SCC | 165 | 92.1 → 100 | 83.1 → 95.5 | TechSpec | 269 | 92.6 → 93.7 | 47.2 → 48.5 |
| ToT | 151 | 89.4 → 99.3 | 87.5 → 97.3 | InfoSchedule | 178 | 61.8 → 76.4 | 31.2 → 49.4 |
| TermsSupp | 79 | 97.5 → 100 | 91.3 → 100 | ToT | 154 | 88.3 → 98.1 | 85.5 → 94.9 |
| GCC | 78 | 96.2 → 100 | 84.5 → 93.1 | TermsSupp | 113 | 89.4 → 96.5 | 84.4 → 95.6 |
| ComplianceSchedule | 62 | 91.9 → 96.8 | 34.4 → 37.7 | AnnexSCCB | 112 | 99.1 → 100 | 91.0 → 100 |
| InfoSchedule | 55 | 58.2 → 80.0 | 46.3 → 68.5 | SCC | 83 | 95.2 → 95.2 | 74.7 → 78.7 |
| NCTC | 33 | 66.7 → 78.8 | 50.0 → 53.1 | AttTechSpec | 82 | 97.6 → 98.8 | 0.0 → 98.8 |
| PriceSchedule | 25 | 88.0 → 88.0 | 41.7 → 41.7 | GCC | 77 | 100 → 100 | 97.1 → 97.1 |
| POGS | 19 | 89.5 → 89.5 | 44.4 → 44.4 | PriceSchedule | 75 | 70.7 → 86.7 | 24.3 → 43.2 |
| CCS | 18 | 88.9 → 100 | 86.7 → 100 | AnnexSCCC | 72 | 87.5 → 97.2 | 76.1 → 91.5 |
| TechSpec | 17 | 88.2 → 100 | 81.2 → 87.5 | ComplianceSchedule | 64 | 90.6 → 93.8 | 33.3 → 42.9 |
| AppendixToT | 14 | 28.6 → 28.6 | 0.0 → 0.0 | ISS | 52 | 57.7 → 82.7 | 11.8 → 51.0 |
| AnnexToTA | 14 | 21.4 → 50.0 | 0.0 → 23.1 | AnnexToTA | 50 | 62.0 → 76.0 | 20.4 → 28.6 |
| TenderForm-EN | 13 | 76.9 → 76.9 | 25.0 → 25.0 | POGS | 47 | 68.1 → 91.5 | 26.1 → 26.1 |
| TenderForm-ZH | 13 | 46.2 → 53.8 | 0.0 → 0.0 | NCTC | 34 | 64.7 → 82.4 | 48.5 → 66.7 |
| | | | | CCS | 27 | 88.9 → 96.3 | 87.5 → 95.8 |
| | | | | AnnexSuppA | 26 | 61.5 → 92.3 | 0.0 → 32.0 |
| | | | | AppendixToT | 23 | 47.8 → 52.2 | 9.1 → 9.1 |
| | | | | TenderForm-EN | 13 | 76.9 → 76.9 | 27.3 → 27.3 |
| | | | | AttAnnexSCCA | 13 | 84.6 → 84.6 | 25.0 → 25.0 |
| | | | | TenderForm-ZH | 12 | 50.0 → 58.3 | 0.0 → 0.0 |
| | | | | AnnexToTB | 5 | 40.0 → 40.0 | 25.0 → 25.0 |
| | | | | AttAnnexSuppA | 1 | 0.0 → 100 | - → - |

By level at `1770505` (recall / hierarchy): Tender 2 L0 100 / 100, L1 86.9 / 62.8, L2 100 / 94.3, L3 98.1 / 91.3; Tender 3 L0 96.3 / 95.8, L1 84.5 / 52.8, L2 94.2 / 72.0, L3 98.7 / 100.

Still below target at `1770505`: deep recall (93.1 and 90.8, target 95), hierarchy (77.1 and 65.0) and exact location (89.2 and 87.2) on both tenders, and Tender 3's references citation (90.6). Main causes of the remaining misses: form fields without a marker (signature, name and date lines; the Appendix's address fields), paragraphs and "tail" text the keys count as their own nodes under a heading or after a list, headings and notes that the keys nest their following items under (the parser keeps them as leaves, so every child's parent is off), the Chinese Tender Form's Parts (not recognised as Parts), a desirable-feature flag set as its own block before an item of the Technical Specifications, and Tender 3's Annex A to the Terms of Tender inside TERMS-1, which is not recognised as an annex, so its recitals and execution block run into the clause before it.

### Third pass toward the S3 target (2026-09-18)

Target for this pass: deep recall at or above 95% on both new tenders, with no metric lower on Tender 1. Every column is a fresh parse of all three tenders (layout model output cached, node tables byte-identical to an uncached parse), scored with the evaluator as of `7e5b731`. The first column is the second pass's parser (`1770505`) with the locate branch merged (`75a12a2`); its node tables are byte-identical to `1770505`'s, and only its citation resolver differs (`8b5ce90`), which is why its references citation reads 100 / 95.3 rather than 92.5 / 90.6 above. `b338288` (a locate test fix, below) and `d531643` (two lines put back where a merge left them) change no node.

Columns: `75a12a2` start · `d5335b8` blank form fields (signature, name and date lines, contact-list labels, the tenderer's name line the layout model took for page furniture, colons set in their own column) are nodes · `22d5d95` a paragraph under a heading-only node (a schedule's preamble, a titled Part's body, an addressee) is a node · `3daa151` an item flagged as desirable in the margin is still its own item · `62a98cd` an annex named only in its page header (the terms booklet's Annex A) is an annex · `12b2426` a Part of the Chinese Tender Form is a Part · `f6d2307` several dash-named Parts in brackets each resolve (citation resolver only) · `3396216` every field of a form row is a node · `7d4dfd9` the sentence resuming after a run-in list is a tail node · `7e5b731` a list lettered or numbered in capitals is a list.

The field, paragraph and tail nodes are added the way run-in sub-items are: the node they came from keeps its whole text. Splitting them off instead raised deep length further but lowered Tender 1's no-regression table (AI_camp's hand-checked lengths count a signature block in the clause above it and a Part's body in the Part) and lost key nodes whose first words run from a Part heading into its body (Tender 2's Price Schedule Part B, the last item of a run-in list), so both were measured and not kept.

**Tender 2**

| Metric | 75a12a2 | d5335b8 | 22d5d95 | 3daa151 | 62a98cd | 12b2426 | f6d2307 | 3396216 | 7d4dfd9 | 7e5b731 |
|---|---|---|---|---|---|---|---|---|---|---|
| schedule coverage / page / position | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| schedule length | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 |
| references coverage / page | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| references position | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| references length | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 |
| references citation | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| deep recall (= own node, page) | 93.1 | 96.3 | 97.4 | 97.4 | 97.5 | 97.8 | 97.8 | 97.8 | 97.8 | 97.8 |
| deep exact_location_correct | 89.2 | 92.3 | 93.4 | 93.4 | 93.4 | 93.4 | 93.4 | 93.4 | 93.4 | 93.4 |
| deep kind_correctness | 99.4 | 99.4 | 99.4 | 99.4 | 99.4 | 99.5 | 99.5 | 99.5 | 99.5 | 99.5 |
| deep hierarchy_correctness | 77.1 | 78.6 | 79.1 | 79.1 | 79.4 | 80.0 | 80.0 | 80.0 | 80.0 | 80.0 |
| deep avg_node_length_ratio | 1.51 | 1.49 | 1.49 | 1.49 | 1.49 | 1.49 | 1.49 | 1.49 | 1.49 | 1.49 |
| deep reachable | 97.6 | 98.5 | 98.5 | 98.5 | 98.7 | 98.9 | 98.9 | 98.9 | 98.9 | 98.9 |
| deep length (within 10%) | 86.1 | 89.2 | 90.2 | 90.2 | 90.3 | 90.2 | 90.2 | 90.2 | 90.2 | 90.2 |
| deep parent | 79.4 | 80.7 | 81.6 | 81.6 | 82.0 | 82.7 | 82.7 | 82.7 | 82.7 | 82.7 |

**Tender 3**

| Metric | 75a12a2 | d5335b8 | 22d5d95 | 3daa151 | 62a98cd | 12b2426 | f6d2307 | 3396216 | 7d4dfd9 | 7e5b731 |
|---|---|---|---|---|---|---|---|---|---|---|
| schedule coverage / page / position | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| schedule length | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| references coverage / page | 96.9 | 96.9 | 96.9 | 96.9 | 98.4 | 100 | 100 | 100 | 100 | 100 |
| references position | 95.3 | 95.3 | 95.3 | 95.3 | 96.9 | 98.4 | 98.4 | 98.4 | 98.4 | 98.4 |
| references length | 92.2 | 92.2 | 92.2 | 92.2 | 93.8 | 95.3 | 95.3 | 95.3 | 95.3 | 95.3 |
| references citation | 95.3 | 95.3 | 95.3 | 95.3 | 96.9 | 96.9 | 96.9 | 96.9 | 96.9 | 96.9 |
| split recall / precision | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 |
| deep recall (= own node, page) | 90.8 | 92.2 | 92.9 | 93.4 | 93.5 | 93.6 | 93.6 | 94.2 | 94.8 | 95.2 |
| deep exact_location_correct | 87.2 | 88.6 | 89.3 | 89.3 | 89.4 | 89.4 | 89.4 | 90.1 | 90.6 | 91.0 |
| deep kind_correctness | 98.0 | 98.0 | 98.0 | 98.6 | 98.7 | 98.8 | 98.8 | 98.8 | 98.8 | 98.8 |
| deep hierarchy_correctness | 65.0 | 65.8 | 66.5 | 66.5 | 66.8 | 67.0 | 67.0 | 67.0 | 67.5 | 68.7 |
| deep avg_node_length_ratio | 1.61 | 1.60 | 1.60 | 1.59 | 1.60 | 1.60 | 1.60 | 1.59 | 1.59 | 1.49 |
| deep reachable | 97.6 | 97.9 | 97.9 | 98.2 | 98.2 | 98.3 | 98.3 | 98.3 | 98.3 | 98.4 |
| deep length (within 10%) | 82.0 | 83.1 | 83.8 | 84.3 | 84.3 | 84.3 | 84.3 | 85.0 | 85.5 | 86.2 |
| deep parent | 68.0 | 68.7 | 69.4 | 69.8 | 70.1 | 70.4 | 70.4 | 70.4 | 70.9 | 71.9 |

**Tender 1**

| Metric | 75a12a2 | d5335b8 | 22d5d95 | 3daa151 | 62a98cd | 12b2426 | f6d2307 | 3396216 | 7d4dfd9 | 7e5b731 |
|---|---|---|---|---|---|---|---|---|---|---|
| deep recall (= own node, page) | 92.5 | 94.5 | 95.4 | 95.4 | 95.6 | 95.6 | 95.6 | 95.6 | 95.6 | 95.6 |
| deep exact_location_correct | 86.6 | 88.5 | 89.4 | 89.4 | 89.4 | 89.4 | 89.4 | 89.4 | 89.4 | 89.4 |
| deep kind_correctness | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 |
| deep hierarchy_correctness | 76.7 | 76.7 | 77.2 | 77.2 | 77.2 | 77.2 | 77.2 | 77.2 | 77.2 | 77.2 |
| deep avg_node_length_ratio | 1.11 | 1.10 | 1.10 | 1.10 | 1.10 | 1.10 | 1.10 | 1.10 | 1.10 | 1.10 |

Tender 1's no-regression table: 141/142 at every column (the same paragraph after a nested list as before). Its Completeness Check Schedule still parses to Parts A-C with items (a)-(o).

Two numbers move the wrong way by one node or less and were kept: `12b2426` takes the next Part's heading out of the Chinese Tender Form's last note of Part 4, where it had been absorbed, and that note (now its own text only) falls outside 10% of the key's length, so Tender 2's deep length (within 10%) goes 90.3 → 90.2; and avg_node_length_ratio is an average over found nodes, so newly found nodes move it slightly up as well as down (Tender 2 1.488 → 1.490 at `12b2426`, Tender 3 1.595 → 1.596 at `62a98cd`). No node found at one column is lost at a later one, on any of the three tenders.

**Deep recall / hierarchy by document**, `75a12a2` → `7e5b731` (%, documents that changed):

| Tender 2 | Nodes | Recall | Hierarchy | Tender 3 | Nodes | Recall | Hierarchy |
|---|---|---|---|---|---|---|---|
| ComplianceSchedule | 62 | 96.8 → 98.4 | 37.7 → 37.7 | TechSpec | 269 | 93.7 → 96.7 | 48.5 → 48.5 |
| InfoSchedule | 55 | 80.0 → 83.6 | 68.5 → 68.5 | InfoSchedule | 178 | 76.4 → 87.1 | 49.4 → 52.8 |
| NCTC | 33 | 78.8 → 97.0 | 53.1 → 53.1 | ToT | 154 | 98.1 → 100 | 94.9 → 97.4 |
| PriceSchedule | 25 | 88.0 → 96.0 | 41.7 → 41.7 | SCC | 83 | 95.2 → 98.8 | 78.7 → 98.7 |
| POGS | 19 | 89.5 → 100 | 44.4 → 44.4 | PriceSchedule | 75 | 86.7 → 89.3 | 43.2 → 44.6 |
| AppendixToT | 14 | 28.6 → 100 | 0.0 → 100 | AnnexSCCC | 72 | 97.2 → 98.6 | 91.5 → 93.0 |
| AnnexToTA | 14 | 50.0 → 85.7 | 23.1 → 61.5 | ComplianceSchedule | 64 | 93.8 → 95.3 | 42.9 → 42.9 |
| TenderForm-EN | 13 | 76.9 → 92.3 | 25.0 → 25.0 | ISS | 52 | 82.7 → 86.5 | 51.0 → 52.9 |
| TenderForm-ZH | 13 | 53.8 → 92.3 | 0.0 → 33.3 | AnnexToTA | 50 | 76.0 → 88.0 | 28.6 → 38.8 |
| | | | | POGS | 47 | 91.5 → 95.7 | 26.1 → 28.3 |
| | | | | NCTC | 34 | 82.4 → 88.2 | 66.7 → 72.7 |
| | | | | CCS | 27 | 96.3 → 100 | 95.8 → 100 |
| | | | | AppendixToT | 23 | 52.2 → 100 | 9.1 → 59.1 |
| | | | | TenderForm-EN | 13 | 76.9 → 92.3 | 27.3 → 27.3 |
| | | | | TenderForm-ZH | 12 | 58.3 → 91.7 | 0.0 → 36.4 |
| | | | | AnnexToTB | 5 | 40.0 → 80.0 | 25.0 → 50.0 |

By level at `7e5b731` (recall / hierarchy): Tender 2 L0 100 / 100, L1 95.9 / 68.1, L2 100 / 94.3, L3 98.1 / 91.3; Tender 3 L0 100 / 100, L1 92.4 / 58.0, L2 96.6 / 74.7, L3 98.7 / 100.

Deep recall is now above 95% on both tenders (97.8 and 95.2) and on Tender 1 (95.6). Still below target: hierarchy (80.0 and 68.7), exact location on Tender 3 (91.0; the desirable-flag items start with the flag, not their own marker), references citation on Tender 3 (96.9) and schedule length on Tender 2 (93.8, unchanged). Remaining misses: a Part heading whose key text runs on into the bracketed note below it (4 on the two tenders), Price Schedule tables and their totals (Tender 3, 6), the Information Schedule's paragraphs inside bracketed notes, dash lists and notes (Tender 3, about 15), the booklet's Annex A execution block and a scrambled signature block of the certificate and the Chinese form, and keys that disagree with each other (Tender 2 counts a titled Part's body and a list's closing words in the Part and the last item; Tender 3 and Tender 1 count them as nodes of their own). Hierarchy (nesting items under a heading or a "Notes:" line) was left alone: it changes the ids of every nested node, and no measurement here shows the ids locate and the citation resolver use would stay stable.


## Locate (L0 `app/rulesets/locate.py`, 2026-09-17)

`test/rulesets/test_locate.py -m realdata` on nodes parsed at `9877109`. Items and Parts come from the schedule's page text (ported reader); each item's node and its cited clauses come from the node table and `CitationIndex`. Tender 1 has no checklist key, so its items come from the deep key's level-0 rows and its cited clauses from the deep key's `cited_via`. That key also lists links the item text does not write out, which accounts for all 4 of its misses.

| Tender | Items found | Right Part | Right page | Own node | Cited clauses resolved |
|---|---|---|---|---|---|
| Tender 1 | 15/15 | 15/15 | 15/15 | 15/15 | 45/49 (91.8%) |
| Tender 2 | 13/13 | 13/13 | 13/13 | 13/13 | 41/43 (95.3%) |
| Tender 3 | 21/21 | 21/21 | 21/21 | 21/21 | 58/65 (89.2%) |

Remaining misses are parser gaps, not locate: no node for the Parts of the Annex A deposit form (Tender 2, 2), the Tender Form in the combined PDF (Tender 3, 2), the numbered items of Price Schedule Part A (Tender 3, 4), or the TERMS Annex A (Tender 3, 1).

The resolver fixes in `8b5ce90` (chains sharing one document name, numbered file names, "respectively", wrapped footer labels) also raise the parser evaluator's references citation: Tender 2 87.5% to 95.0%, Tender 3 84.4% to 89.1%. No other metric changes.

After the second parser pass (`1770505`, fresh parse, same test): items, Parts, pages and own nodes unchanged on all three tenders; cited clauses resolved Tender 1 43/49, Tender 2 42/43, Tender 3 62/65. The two new Tender 1 misses (items (d) and (e) to the Particulars of Goods Schedule's first clause) came from `14dee7e`: locate still resolves both items to the whole schedule, but the document node now holds its own title and preamble (and, since `56dfa87`, an unnumbered heading is a node), so the test's "first node with text below a whole document" became the document or its heading instead of the first clause. `b338288` makes the test take the first marked node below a whole document: 45/49 again, and the same scores on every earlier commit's nodes.

After the third parser pass (`7e5b731`, same test): items, Parts, pages and own nodes unchanged on all three tenders; cited clauses resolved Tender 1 45/49 (the 4 key links the item text does not write out), Tender 2 43/43 (from 42/43: `f6d2307` resolves Part IB of the Annex A deposit form, whose Parts were already nodes), Tender 3 63/65 (from 62/65: `62a98cd` makes the booklet's Annex A a node). The two left on Tender 3 are Part 4 of the Tender Form in the combined PDF: its sub-documents are named by their footer, so "the Tender Form" names no scope for the resolver.

### Correction to the exact-location rule (2026-09-20)

`738d38c` stopped `part` being read as a marker for every node inside a Part, but
kept `label or number or part`, and `or` takes the first value that is set. A Part
node carries both `number` ("A") and `part` ("Part A"), so it stopped at "A" and
every Part heading still failed - "Part A\nThe Tenderer shall note..." does not
start with "A" - which is the case that commit was written to catch. All of a
node's candidate markers are now tried, and `part` counts for an annex as well.

The parser is unchanged; these are the same node tables scored under the corrected
rule. It lifts Tender 1's exact location over the target it was under, so all
four metrics clear 90% on all three tenders.

| Tender | recall | page correct | char correct | exact location |
|---|---|---|---|---|
| Tender 1 | 95.6% | 95.6% | 95.6% | 92.3% (was 89.4%) |
| Tender 2 | 97.8% | 97.8% | 97.8% | 95.2% (was 93.4%) |
| Tender 3 | 95.2% | 95.2% | 95.2% | 91.8% (was 91.0%) |
### Review fixes on the third pass (2026-09-20)

The fixes from the review of the locate and third-parser-pass PRs (`6c4ec2f` .. `131ed48`: the citation pattern's backtracking, the annex-head fallback, roman markers `(v)` and `(x)`, the page-footer anchor, project-relative citation files, a Part's quote, and the run-in tail's own node id) change no metric. A fresh parse of all three tenders scores exactly as `7e5b731`: deep recall 97.8 / 95.2 / 95.6, references citation 100 / 96.9, schedule 100 / 93.8 and 100 / 100, guard 141 of 142; and `test/rulesets/test_locate.py -m realdata` on those nodes gives the same 45/49, 43/43 and 63/65.

The node tables differ only in the ids of the run-in tail nodes, now `:run-in-tail` rather than `:tail` (18, 23 and 12 of them); every other id, page and text is byte-identical, and no clause in these three tenders had both tails, which is how the `:tail#2` collision stayed invisible. The citation resolver's own answers are unchanged: the atomic identifier token is a performance fix only (a plain 14-item list took 17.7 s before it and under a millisecond after), and the annex-head guard is narrowed to a head carrying an identifier plus a bare "Supplement/Schedule to the", because excluding a bare "Appendix to the" and "Annex (title) of" as well loses the two real wrapped footer labels on Tender 3 (locate 63/65 to 60/65).

## 2026-09-21: the benchmark pinned, and where the parser stands

The four metrics now live in `tools/benchmark.py`, which the evaluator imports rather
than restating; `test/parsing/test_benchmark.py` pins them. `kind_correctness` and
`hierarchy_correctness` are still computed but are not the benchmark, and the module
says why. Scored on `faa8671`, all three tenders, deep keys:

| Tender | Nodes | recall | page correct | char correct | exact location |
|---|---|---|---|---|---|
| Tender 1 | 454 | 95.6% | 95.6% | 95.6% | 92.3% |
| Tender 2 | 756 | 97.8% | 97.8% | 97.8% | 95.2% |
| Tender 3 | 1582 | 95.2% | 95.2% | 95.2% | 91.8% |

All three clear the S3 gate of 95% recall, Tender 3 by 4 nodes.

On Tender 3, the hardest of the three (25 documents inside one 366-page PDF), the
checklist-level metrics read: schedule coverage / page / position / length 100%,
references coverage / page 100%, references citation 96.9%, position 98.4%, length
95.3%, and **document split recall and precision both 100%** (25/25) - it was 92%
recall when this file's first section was written, with two documents never found.

One number is out of line and is recorded as checklist J1: references
`exact_location_correct` is **75.0%** (48/64) against 91.8% at node level. All 16
failures are containers - 11 are `Table A`/`第 4 部分` headings whose scope is named
"Part A"/"Part 4" whatever the document prints, and 5 are sub-documents with no bbox.

## 2026-09-22: J1, a scope named for the word it prints

A Part-ranked heading is not always written "Part": the Information Schedule names
its scopes "Table A", the Chinese Tender Form writes "第 4 部分". The rank is the same,
so they share a kind; the NAME is not, and the name is what a node records as its own
marker and what a citation shows a reviewer. Naming every one of them "Part A" made
the marker something the node's own text never starts with, and told a reviewer that
Table A of the Information Schedule was Part A of it.

The Particulars of Goods Schedule showed the same confusion one level down: it has a
clause "1. Particulars of Offer" and then a field table whose rows are also numbered
1., 2., 3. Read as clauses, all 21 rows became siblings of the clause they belong
under. A row comes out of a `table` block and a clause never does, which is what tells
them apart - and a row prints "1.", not "(1)", so that is its label while its id keeps
the parenthesised form every other sub-item is addressed by.

| Tender | recall | exact location | references exact location | POGS hierarchy |
|---|---|---|---|---|
| Tender 1 | 95.6% (=) | 92.3% -> **93.2%** | — | 0.0% -> **66.7%** |
| Tender 2 | 97.8% (=) | 95.2% -> **96.4%** | 75.0% -> **82.5%** | — |
| Tender 3 | 95.2% (=) | 91.8% -> **92.9%** | 75.0% -> **79.7%** | — |

Worth recording how the second half was found. Making the rows sub-items fixed
hierarchy and *broke* exact location on 14 of them, because a sub-item's label is
"(1)" while the row's text starts "1." - 14 benchmark passes traded for 21 diagnostic
ones, and Tender 1 fell to 90.1%. All 513 tests passed throughout: none of them
exercises a real tender's Particulars of Goods Schedule. Only re-scoring against a
recorded baseline caught it.
