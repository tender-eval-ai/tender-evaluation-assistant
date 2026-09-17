# Parser (L0) evaluation

How well `app/parsing` turns the tender PDFs into a node table, scored with `tools/eval_parser.py` against the answer keys for the two tenders the parser was never tuned on. The keys and PDFs are redacted sample documents and stay outside git; this file records numbers only.

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

Columns: `a45f300` unchanged port · `93f0ab7` document node page · `e14f121` Parts under their sub-document · `b6a69cb` block lines by vertical overlap · `96857ed` resolver for Tables/Parts/rows/annexes/whole documents · `11ae315` split blocks at a marker in the marker column.

**Tender 2**

| Metric | a45f300 | 93f0ab7 | e14f121 | b6a69cb | 96857ed | 11ae315 |
|---|---|---|---|---|---|---|
| schedule coverage / page / position | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 | 100 / 100 / 100 |
| schedule length | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 | 93.8 |
| references coverage / page | 92.5 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 |
| references position | 90.0 | 92.5 | 92.5 | 92.5 | 92.5 | 92.5 |
| references length | 82.5 | 85.0 | 90.0 | 90.0 | 90.0 | 90.0 |
| references citation | 50.0 | 50.0 | 50.0 | 50.0 | 87.5 | 87.5 |
| deep own node / page | 79.5 | 79.5 | 79.5 | 80.7 | 80.7 | 80.8 |
| deep reachable | 93.3 | 93.3 | 93.3 | 94.7 | 94.7 | 94.7 |
| deep length | 71.7 | 71.7 | 71.7 | 72.9 | 72.9 | 73.0 |
| deep parent | 68.0 | 68.0 | 68.0 | 68.4 | 68.4 | 68.4 |

**Tender 3**

| Metric | a45f300 | 93f0ab7 | e14f121 | b6a69cb | 96857ed | 11ae315 |
|---|---|---|---|---|---|---|
| schedule coverage / page | 91.7 | 91.7 | 91.7 | 91.7 | 91.7 | 100 |
| schedule position | 87.5 | 87.5 | 87.5 | 91.7 | 91.7 | 100 |
| schedule length | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 100 |
| references coverage / page | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 | 90.6 |
| references position | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 | 87.5 |
| references length | 81.2 | 81.2 | 82.8 | 82.8 | 82.8 | 82.8 |
| references citation | 40.6 | 40.6 | 40.6 | 40.6 | 84.4 | 84.4 |
| split recall / precision | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 | 92.0 / 100 |
| deep own node / page | 70.2 | 70.2 | 70.2 | 70.8 | 70.8 | 71.0 |
| deep reachable | 83.9 | 83.9 | 83.9 | 84.5 | 84.5 | 84.5 |
| deep length | 64.2 | 64.2 | 64.2 | 64.7 | 64.7 | 65.0 |
| deep parent | 48.6 | 48.6 | 48.6 | 49.2 | 49.2 | 49.9 |

No commit lowers any metric. The resolver commit is the only large gain (citation +37 and +44 points); the structural commits move the deep metrics by under 1.5 points.

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
