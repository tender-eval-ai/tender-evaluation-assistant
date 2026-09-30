# 0003. A format router in front of the tender parser

Status: **proposed** (Nasi, 2026-09-29). Author: Nasi.

## Context

The project stays on procurement. What varies is the **format of the tender documents**, and
today the parser (L0) assumes one family:

- **Where the parser was built:** it was tuned on one authority's goods tenders. Those are digital PDFs with a
  text layer, PART headings, numbered clauses and sub-items, running headers and footers, and a lettered
  Completeness Check Schedule. It reads Tender 1 and Tender 2 (12–17 separate files) and Tender 3 (25 documents
  inside one 366-page PDF) at 95% recall or better.
- **Only PDFs are read.** `build_job.tender_pdfs()` collects `tender/*.pdf`, and `app/parsing/loader.py` opens
  PDFs only. A tender issued as Word files, spreadsheets (price schedules) or HTML pages from an e-tendering
  portal is never read.
- **A scanned tender loses its pages.** `layout_document_index.parse_document` begins with
  `pages = [p for p in pages if p.native_text]`, so a page with no text layer never becomes a node. A tender
  issued as scans has no clause tree at all, and nothing says so.
- **One parser serves every layout.** Other authorities number clauses differently (`1.1.1`, "Section / Article",
  "Clause 12(b)(ii)"), put the checklist in a table instead of a lettered list, or issue bilingual documents. Each
  new layout has so far been handled by adding special cases to one 1,767-line module. The parser eval shows the
  risk: a fix for one layout broke exact location on another while every unit test still passed. Only re-scoring
  against the answer keys caught it.

Everything after L0 works on the parser's output and not on the files:

- the **node table** (`node_id`, `kind`, `number`, `title`, `text`, `page`, `bbox`, `parent_id`, `source_file`, …);
- `locate`;
- the L1–L4 rule-set layers;
- the **template library** (`app/rulesets/templates/`, keyed by the form ids in `app/checks/forms.py`).

So a new format needs a new way to *produce* that node table, not a new pipeline.

## Proposal

```
tender files ──► router ──► format-specific parser ──► node table (one contract) ──► locate ──► L1–L4 ──► rule set
                  │              │                                                        ▲
                  │              └─ its own answer keys and eval                           │
                  └─ its own eval (right format?)                   one shared template library, extended per format
```

1. **A router identifies each document's structure before any parsing.**
   - **Signals it can use:** the file type; the share of pages with a text layer; page count and whether one
     file holds several documents (the sub-document split already detects this); the language and script; the
     numbering style of the first headings; table density from the layout model; the running headers and footers.
   - **Output, per file:** a *format* label with a confidence and the signals that decided it, recorded in the
     project's audit log.
   - **When unsure:** below a confidence threshold the file goes to the current parser and is flagged for a
     person, never silently to a wrong one.
2. **One parser per format, behind one interface.** Each parser turns one file's pages into nodes in the existing
   node-table contract. Today's `layout_document_index` becomes the first, for *digital PDFs with numbered
   clauses*. Candidates for the next ones, in the order a real tender needs them:
   - **scanned PDF:** OCR each page, then the same clause structure;
   - **DOCX:** heading styles and list numbering come from the file itself, with no layout model needed;
   - **table-first documents:** schedules and spreadsheets, where a row is an item;
   - **other numbering styles**, if they can't be handled by configuring the existing parser.
3. **One node-table contract, checked in code.** Every parser's output passes the same validator:
   - ids are unique and stable;
   - every node has a page;
   - parents exist;
   - a node's text starts at its own marker;
   - citations resolve.

   `locate`, L1–L4 and the UI don't change when a format is added.
4. **One shared template library, extended as formats are added.** Templates are keyed by *form*: the Offer to be
   Bound, the Price Schedule, the Non-collusive Tendering Certificate. They aren't keyed by file layout. A tender
   in a new format reuses the templates for the forms it shares with earlier tenders. A form seen for the first
   time is drafted by L3 ("novel"), confirmed by a person, and saved as a new template (#89), so the library grows
   with every tender, whatever its format. The form menu (`forms.py`) is extended the same way.

## Evaluation

- **Router:**
  - a labelled set of tender files, with the format a person assigns to each;
  - scored as a confusion matrix;
  - the cost of an error is judged by what the wrong parser would produce, measured by running it.
- **Each parser:**
  - its own answer keys, built the way the current ones were (from the PDFs, never from the parser);
  - scored with the parser eval: recall, and citation resolution;
  - one format's numbers never average another's.
- **No regression:** Tender 1–3 are re-scored on every parser change, as today. The router must send all three to
  today's parser with their numbers unchanged.
- **Downstream:** the rule-set eval (`tools/eval_ruleset.py`) runs on at least one tender per format. A parser that
  scores well but leaves `locate` unable to find the schedule hasn't finished its job.

## Steps

1. **Collect the formats that actually occur.** Gather tender sets from other authorities or other years and
   record what differs: file types, scans, numbering, schedule layout, language. The next parser is chosen from
   this evidence.
2. **Extract the interface, with no behaviour change.**
   - Put a parser registry behind `parse_tender`.
   - Move today's parser behind it as the "digital PDF, numbered clauses" format.
   - Write down the node-table contract as a validator.
   - Tender 1–3 numbers must stay identical.
3. **Add the router** with the signals above, and make its decision visible: in the audit log and in the Rules
   window's source panel.
4. **Stop dropping scanned pages quietly.** Until an OCR parser exists, the router flags a file with no text layer,
   so a person knows the clause tree is missing.
5. **Build the second parser** for the format step 1 finds most often, with answer keys for at least one real
   tender in it.
6. **Grow the template library** from the confirmed rule sets of the new tenders (#89), and extend the form menu
   where a new tender brings a new form.

## Options considered

- **Keep one parser and add special cases (today's path).**
  - *For:* no new structure.
  - *Against:* every case risks every other layout. The module keeps growing. And a format the parser can't read
    at all (Word files, scans) can't be handled by adding special cases.
- **A general document-AI service or a VLM that reads any layout.**
  - *For:* it might cover formats with less code.
  - *Against:* its output still has to meet the node-table contract and be scored against answer keys. Confidential
    tenders have to stay on local models, and a model can be slow or expensive at 300+ pages. It could be one
    parser behind the router, not the router's replacement.
- **Router plus format-specific parsers (proposed).** Each format can fail, and be measured, on its own. The work
  that matters downstream (the node table, locate, templates) is shared.

## Consequences

- **Parser changes stay contained:** a change to one format's parser is scored on that format's keys and can't
  silently move another's numbers.
- **The template library becomes the asset that grows,** because it is shared across formats.
- **The cost is answer keys.** Every format needs its own before its numbers mean anything, as with Tender 1–3.
- **`app/parsing/` grows** from one parser into a registry, a router and several parsers. The licence note in the
  README (PyMuPDF only inside `app/parsing/`) still holds, and a new parser that brings a new library needs the same
  check as decision 0002.

## Open questions

- Which formats occur in the tenders we can realistically get (step 1)?
- Is the router's unit the file or the document? Tender 3 is one file holding 25 documents. The sub-document split
  may belong before the router, so each document can be routed on its own.
- Should the router's decision be editable in the UI, so a reviewer can re-route a file and re-parse it?
