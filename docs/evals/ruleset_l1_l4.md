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

### The three real tenders

Not yet run: the joint S3 check. They need (1) the production templates split out of the 13 rule files (Nasi's S1 leftover; without them every item goes to L3), (2) a key per tender in the format above, derivable from the checklist keys for Part and page, with templates and slots added by hand, kept outside git, (3) `RULESET_TEMPLATES_DIR` and `DATA_DIR` pointing at the private folders, a build per tender through the API, and `tools/eval_ruleset.py --api ... --project ... --key <private>/<tender>.ruleset_key.json --out <private>/<tender>.eval.json`. Numbers only come back here.
