# Parser (L0) evaluation

How well `app/parsing` turns the tender PDFs into a node table, scored with `tools/eval_parser.py` against the answer keys for the two tenders the parser was never tuned on. The keys and PDFs are redacted sample documents and stay outside git; this file records numbers only.

## Answer keys

Built on 2026-09-16 without any parser code: five independent agents per tender plus an earlier draft, merged by a combiner that settled every disagreement from the PDF text. Not yet verified by Nasi.

| Tender | Documents | Pages | Schedule items (A/B/C) | Part intros | References |
|---|---|---|---|---|---|
| Tender 2 | 12 files | 222 | 13 (3/7/3) | 3 | 40 |
| Tender 3 | 25 inside one PDF | 366 | 21 (3/12/6) | 3 | 64 |

## Metrics

| Metric | Scored on | Correct when |
|---|---|---|
| coverage | schedule entries, references | a node exists for the entry, in the right file, starting inside the entry's pages |
| page | schedule entries, references | that node starts on the entry's first page |
| position | schedule entries, references | the node's text starts with its own marker and that text is on the page |
| length | schedule entries | node length within 10% of the key's character count |
| length | references | the node's subtree ends on the entry's last page |
| citation | references | `CitationIndex.resolve_text` on the citation as written returns that node |
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
