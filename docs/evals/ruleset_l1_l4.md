# Rule builder (L0 to L4) evaluation

How well `app/rulesets` turns a tender's documents into a rule set, scored with `tools/eval_ruleset.py` against an answer key. This file records numbers only. The synthetic key is `test/data/synthetic_tender_nodes/ruleset_key.json`; the keys for the three real tenders stay outside git, like the parser's.

## What is scored

The builder's output is a draft `RuleSet` (`docs/api_contract.md`). Its layers: L0 locates the schedule's items with their Part, page and cited clauses (Nasi's parser and `locate.py`, scored in `parser_l0.md`); L1 matches each item to a template from the library; L2 fills the template's slots from the cited clauses, every value with a verbatim quote that code verifies; L3 drafts rules for items with no template, each rule from a verified quote; L4 lists the obligations under the cited clauses that no rule covers as gaps.

## Answer key

One entry per schedule letter. `part` and `page` are enough to score L0 (a checklist key can be converted); the rest is optional and only counted where given:

```
"b": {"part": "A", "page": 5, "template": "price_schedule", "slots": {"estimated_quantity": 875000}},
"a": {"part": "A", "page": 5, "template": null, "checks": ["signature"]}
```

## Metrics

| Metric | Correct when |
|---|---|
| items_found | the built rule set has an item with the key's letter (items a person added, x1..., are listed as extra) |
| part_right | the item's Part equals the key's |
| page_right | the item's citation is on the key's page |
| template_right | the item's template equals the key's, including "none" (only letters the key gives a template for) |
| slots_right | the slot's value equals the key's after coercion **and** its quote was found on a clause node by code (`verified`) |
| checks_recall | of the check kinds the key expects on an item, how many a drafted rule carries |
| statuses | how the items ended: verified, needs_input, novel, gap, edited |
| rules_total / unverified_notes | rules drafted; requirements the model gave whose quote was not on any cited clause (kept as notes, never as rules) |
| gaps (reasoned) | L4's uncovered obligations, and how many a person has explained |

## Results

Target for S3: every schedule item found with its Part and page; template and slot metrics at or above 90% where the library has the template; nothing unverified becomes a rule (unverified_notes is a count of what the model wanted to add and could not).

### Synthetic tender SYN-2026-001, live build (2026-09-20)

Compose stack, `deepseek-chat` for L1 to L3, the two test templates (certificate, price schedule) as the library, `python tools/build_synthetic_ruleset.py` then `tools/eval_ruleset.py`. 29 model calls, $0.012, 46 seconds including the parse.

| item | status | Part | page | template | slots | checks | rules | unverified |
|---|---|---|---|---|---|---|---|---|
| (a) | novel | yes | yes | yes | - | 1/1 | 2 | 0 |
| (b) | verified | yes | yes | yes | estimated_quantity: ok | - | 2 | 0 |
| (c) | verified | yes | yes | yes | estimated_quantity: ok | - | 2 | 0 |
| (d) | novel | yes | yes | yes | - | - | 7 | 0 |
| (e) | novel | yes | yes | yes | - | - | 7 | 0 |
| (f) | novel | yes | yes | yes | - | 1/1 | 15 | 0 |
| (g) | gap | yes | yes | yes | - | - | 0 | 0 |
| (h) | novel | yes | yes | yes | - | 1/1 | 3 | 0 |
| (i) | gap | yes | yes | yes | - | 0/1 | 0 | 1 |
| (j) | gap | yes | yes | yes | - | 0/1 | 0 | 1 |
| (k) | novel | yes | yes | yes | - | 1/1 | 4 | 0 |
| (l) | verified | yes | yes | yes | - | - | 4 | 0 |
| (m) | needs_input | yes | yes | yes | - | - | 2 | 0 |
| (n) | gap | yes | yes | yes | - | 0/1 | 0 | 0 |
| (o) | gap | yes | yes | yes | - | 0/1 | 0 | 1 |

| metric | value |
|---|---|
| items_found | 15/15 (100.0%) |
| part_right | 15/15 (100.0%) |
| page_right | 15/15 (100.0%) |
| template_right | 15/15 (100.0%) |
| slots_right | 2/2 (100.0%) |
| checks_recall | 4/8 (50.0%) |
| statuses | gap 5, needs_input 1, novel 6, verified 3 |
| rules_total / unverified_notes | 48 / 3 |
| gaps (reasoned) | 40 (0) |

written <scratch file>

Reading: L0 to L2 are full marks on this tender; L3 drafted rules for six items and found nothing it could quote verbatim for four of the eight keyed checks, three of which it proposed but could not ground (the unverified notes on (i), (j), (o)), and one it did not propose ((n)). Item (m) matched the price schedule but its slots are not stated under Parts C and D, so it waits for a person, which is the intended outcome. The 40 gaps are the synthetic Terms' obligation sentences under the unmatched items' clauses; the synthetic generator writes one such sentence into nearly every clause.

### The three real tenders — L0 (2026-09-22)

`locate` is deterministic: the parser's node table and a regex scan over the
Completeness Check Schedule, with no model call, so this runs offline and costs
nothing. The keys are the L0 half converted from the checklist keys by
`tools/ruleset_key_from_checklist.py` (`part` and `page` per letter, and deliberately
nothing else — a checklist key does not claim a template, a slot value or a check
kind, and the evaluator counts each only where the key gives it). Built with
`tools/build_l0_ruleset.py`, scored with `tools/eval_ruleset.py`.

| Tender | items found | Part right | page right | extra items |
|---|---|---|---|---|
| Tender 1 | 15/15 | 15/15 | 15/15 | none |
| Tender 2 | 13/13 | 13/13 | 13/13 | none |
| Tender 3 | 21/21 | 21/21 | 21/21 | none |

Every item of every schedule, on all three tenders, with the right Part and the right
page, and nothing invented. The S2 target was "`locate.py` finding 15 items with Parts
on all 3 tenders"; this is that, measured rather than asserted.

### The three real tenders — L1 to L4

Still not run, and blocked on one thing rather than several: the production templates
are not split out of the 13 rule files, so L1 matches nothing and every item falls
through to L3. The split is written and classified (126 rules, 99 checks, 27 not a
rule, 0 unmapped) but stops at checklist **J2** — the 27 non-rules are facts about a
FORM, and the schema currently holds notes and conditions only on an item. Once that
is decided, what remains is: the templates and `params/Tender 1.json`, the
template/slot/check half of each key added by hand, and a build per tender through the
API with `RULESET_TEMPLATES_DIR` and `DATA_DIR` pointing at the private folders, scored
with `tools/eval_ruleset.py --api ... --project ... --key <private>/<tender>.ruleset_key.json
--out <private>/<tender>.eval.json`. The keys stay outside git; only numbers come back here.
J2 was decided on 2026-09-23 (option 1, #59).
