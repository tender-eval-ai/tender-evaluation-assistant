# 0002. PDF libraries for the tender parser

Status: **accepted by both** (Nasi 2026-09-16, Chenyu 2026-09-18 in the review of PR #31) (the plan's open decision "PyMuPDF licence · D3"). Author: Nasi.

## Context

The tender parser (L0: split, clause tree, citations) is ported unchanged from `Bidding-AI-expert@7e8e273` into `app/parsing/`. It reads PDFs with two libraries from Artifex:

| Package | Version | Licence | Used for |
|---|---|---|---|
| `pymupdf` | 1.28.0 | GNU AGPL-3.0, or Artifex commercial | opening PDFs, page text, page rendering |
| `pymupdf-layout` | 1.28.0 | PolyForm Noncommercial 1.0.0, or Artifex commercial | the layout model that groups a page into classified blocks (section header, list item, table, page header/footer) |

The parser's accuracy comes from the layout blocks: a marker only opens a node when it starts its own block, which is what lets it accept digit sub-items and reject numbers inside prose. On Tender 1 it resolved 239 of 241 rule citations to the right page and length.

The repo already has `pypdf` (BSD) and `pypdfium2` (Apache-2.0 / BSD) for other steps, so a permissive parser is possible, but it would start from zero.

## Options

1. **Keep both libraries.** No rework; licences restrict reuse.
2. **AGPL only**: keep `pymupdf`, replace the layout model with PyMuPDF's own text blocks. Lower accuracy expected at first.
3. **Permissive only**: rebuild the parser on `pypdfium2`. The most work, and the measured accuracy is lost.

## Decision

Option 1. The project is a non-commercial portfolio project, and the goal for the ten days is a parser that reaches the key results on all three tenders, not a new parser.

## Consequences

- Anyone who uses this repository commercially needs Artifex commercial licences for both packages, or must replace `app/parsing/`. The README says so before the repo is made public (checklist F4).
- AGPL obligations apply to a hosted demo: the running service must offer its source, which a public repository satisfies.
- In the application, nothing outside `app/parsing/` imports either package, so option 2 or 3 stays a contained change if the project's use changes. One development file also imports them: `test/parsing/test_layout_parser_tables.py`. The parser eval, `tools/eval_parser.py`, reaches them only through `app/parsing/`.
