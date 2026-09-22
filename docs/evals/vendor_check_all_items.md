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

Call counts (`test/checks/test_vendor_check_pipeline.py`): a 16-page scanned offer with
eleven forms costs 3 triage + 2 resolve (the two absent forms) + 11 extracts + 11 second
reads = 27 calls; a 12-page digital one 2 + 2 + 11 + 0 = 15; a retried extract step reads
only the forms not yet read.

## Live run through the stack (compose, DeepSeek vision, `tools/check_synthetic_case.py --ruleset test/data/synthetic_tender/ruleset_all_items.json`)

_pending: the run of 2026-09-22 is recorded below when it finishes._

## Boundaries

- Conditions on items ("where the Tenderer is not the manufacturer") are prose in the rule
  set; the engine does not evaluate them. Until it does, such a rule carries its own
  outcomes that send a blank to a reviewer.
- A form absent from an offer costs one resolve call (the model is asked whether any page
  is that form); a form present costs one read and, on a scan, one second read.
- The letter-to-form mapping for an item without a template comes from the page-label
  vocabulary (the Authority schedule's letters). A rule set built for a tender with different
  letters needs the template to name the form; L1's closed menu will carry the form at S5.
