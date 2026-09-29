# The vendor check on every item of the synthetic case (S4-3, 2026-09-22)

What S4-3 does: one generic V3 reads any form of a closed menu (`app/checks/forms.py`,
thirteen forms, each with a fixed field menu, one page label each), the pipeline resolves,
extracts and verifies every form, and the engine bridge decides every item of the confirmed
rule set, with the comparison checks (`value`, `range`, `unit`, `date`, `math`,
`cross_document_match`, `contains`) computed in code and never disqualifying on their own.
The all-items rule set for the synthetic tender (`test/data/synthetic_tender/ruleset_all_items.json`,
15 items, 33 rules; two template items, thirteen novel) is what a person would have confirmed
after L1 to L4; `tools/make_synthetic_tender_ruleset.py` regenerates it.

## FakeLLM, against `ground_truth.json` (`test/checks/test_ground_truth.py`)

| tenderer | offer | forms found | numbers | verified | Stage I | Stage II | items not passing |
|---|---|---|---|---|---|---|---|
| Tenderer_A | digital, 12 pages | 11 of 11 on their pages | unit price, dosage, total, quantity, shelf life, delivery: all equal | every value on the text layer | needs_review | pass | (g) dormant, (i) needs_review |
| Tenderer_B | scanned, 16 pages | 11 of 11 | all equal | every value by a second read | needs_review | pass | (e), (g) dormant, (i) needs_review |
| Tenderer_C | digital, no certificate | 10 of 10 | all equal | text layer | disqualified | pass | (g) dormant, (i) needs_review, (l) disqualified |
| Tenderer_D | scanned, not the manufacturer, US$ | 11 of 11 | all equal | second read | pass | pass | (e), (g), (j) dormant |

Why those conclusions: (g) samples were never requested, a Part B item that may be asked
for later; (e) the country of origin is read off the text layer only, so the scans leave it
blank and the Part B item is dormant; (i) the letter of intent is conditional on the tenderer
not being the manufacturer, and the engine has no condition support yet, so the rule's own
outcomes send a blank to a reviewer instead of disqualifying; (j) Tenderer_D has no board
resolution, Part B; (l) Tenderer_C has no certificate, Part A.

Call counts (`test/checks/test_vendor_check_pipeline.py`, as of 2026-09-23): a 16-page
scanned offer with eleven forms costs 3 triage + 3 resolve (the two absent forms, and the
contract-deposit form added then, which no synthetic bid has) + 11 extracts + 11 second
reads = 28 calls; a 12-page digital one 2 + 3 + 11 + 0 = 16. When a Part A form is absent,
the V5 agent adds its steps after the rule set is confirmed (one for a quick "not found").
A retried extract step reads only the forms not yet read. The live-run counts below were
measured before V5 and the contract-deposit form.

## Live run through the stack (compose, DeepSeek vision, `tools/check_synthetic_case.py --ruleset test/data/synthetic_tender/ruleset_all_items.json`)

Vision model: the local Ollama `qwen3-vl:8b-16k` (the stack's `VISION_MODEL`); text model
DeepSeek. Two workers' worth of concurrency on one laptop, so the four bids took about
three hours in all; the numbers are the point, not the time.

| tenderer | offer | Stage I | Stage II | items not passing | values read | verified | caught by V4 | unchecked | numbers vs truth | new calls (cached) |
|---|---|---|---|---|---|---|---|---|---|---|
| Tenderer_A | digital, 12 pages | needs_review | pass | (g) dormant, (i) needs_review | 46 | 43 | 1: contact-details name read as "Tender A" (page says "Tenderer A"), confidence 0 | 2 signatures | unit price 4.40 HK$, dosage 4.3, total 3,850,000, shelf life 12, delivery 28: all equal | 13 (2) |
| Tenderer_B | scanned, 16 pages | needs_review | pass | (g) dormant, (i) needs_review | 46 | 46 | 0 | 0 | 4.86 HK$, 4.3, 4,252,500, 18, 21: all equal | 24 (3) |
| Tenderer_C | digital, no certificate | disqualified | pass | (g) dormant, (i) needs_review, (l) disqualified | 42 | 40 | 1: contact-details name read as "Tender C" | 1 signature | 5.89 HK$, 3.3, 5,153,750, 24, 28: all equal | 13 (2) |
| Tenderer_D | scanned, not the manufacturer, US$ | pass | pass | (g), (j) dormant | 46 | 46 | 0 | 0 | 7.22 US$, 3.0, 6,317,500, 18, 28: all equal | 30 (0) |

"Values read" counts the fields with a value across the eleven forms present (the two
letters that share a form with another are counted once). Every price, dosage, total,
shelf life and delivery period equals the generator's. The two misreads (the local model
dropped two letters of a tenderer's name on the contact page) were caught on the text
layer and flagged unverified at confidence 0; no rule reads that field, so no verdict
changed, but a reviewer sees the flag. On the scans every value agreed with its second
read. (e) passed on the scans here, unlike in the fake's tests: the real model reads the
country off the image.

Tenderer_D's first two attempts failed in triage: the local model answered a six-page
labelling batch with an empty object twice, the schema check refused it, and the job
failed loudly (`RuntimeError: ... PageLabels ... Field required`). The third attempt, with
`TRIAGE_PAGES_PER_CALL=3` on the worker, went through (6 triage calls instead of 3). A
small local vision model wants smaller batches; the design number of six stays for the
cloud models. `POST /jobs/{id}/retry` continued each attempt from the rendered pages.

## Boundaries

- Conditions on items ("where the Tenderer is not the manufacturer") are prose in the rule
  set; the engine does not evaluate them. Until it does, such a rule carries its own
  outcomes that send a blank to a reviewer.
- A form absent from an offer costs one resolve call (the model is asked whether any page
  is that form); a form present costs one read and, on a scan, one second read.
- The letter-to-form mapping for an item without a template comes from the page-label
  vocabulary (the synthetic schedule's letters). A rule set built for a tender with different
  letters needs the template to name the form; L1's closed menu will carry the form at S5.
