# The bid checker against answer keys (S4 on real bids)

The S4 stop point was "compare Tender 1's bid with the historical Summary List and Price Summary". The camp brief calls those three PDFs **examples**, and none of them names a tender. We also have one bid per tender, where a real procurement has 20–60 tenderers. So S4 is measured against **answer keys** instead (proposed as checklist J9, issue #69).

## Method
1. **One key per bid**, written in `answer_keys/tool/keyer.py`. The keys stay outside git, beside the bids. For each schedule item a key records facts, not verdicts:
   - whether the item is present, absent or not applicable;
   - its pages and form;
   - signed, dated, chop and blacked-out flags;
   - each value exactly as printed.
   
   A frozen key stores a SHA-256 of its content, and unfreezing is logged with a reason.
2. **Two independent keys per bid** (Chenyu's and Nasi's), compared field by field. Every disagreement is settled at the page, and the result is the final key.
3. **The checker is scored against the final key** by `tools/score_bid_key.py`:

   | Measure | What it counts |
   |---|---|
   | presence | items present or absent as the key says |
   | pages | cited pages that hit the key's pages and lie within them |
   | value pages | values cited on the page the key gives for them, overall and on forms of several pages |
   | values | matches, as numbers, dates, signature presence or text |
   | invented | values the checker reports where the key says the field is blank or blacked out |
   | verification | where each scored value went: accepted by V4, flagged for a reviewer, or not checkable; and how many of each were wrong. A wrong value V4 accepted is the one that reaches a verdict unseen |

   Items the checker's form menu can't read count as *not covered*, a measure of the menu.
4. **Which bids play which role:**
   - **Tender 1** is the development bid: we run it first and fix what it shows.
   - **Tender 2 and Tender 3** are held out: we freeze the prompts, templates and form menu before they run, run them once, and log any fix made after seeing them. The Tender 2 key was prefilled by a model that read its pages, so changes must cite the tender documents or the development bid as their source.

Only numbers come back here. `--details` prints the disagreeing values, which come from the bid, so it is for local use only.

## The scorer on the synthetic case (2026-09-23)
The keys were built from the generator's ground truth by `tools/key_from_ground_truth.py`. The results are the synthetic live all-items run of 2026-09-22 (`vendor_check_all_items.md`: vision `qwen3-vl:8b-16k` on local Ollama, text `deepseek-chat`), read back through the API.

| Tenderer | presence | pages hit / within | values | invented |
|---|---|---|---|---|
| Tenderer_A | 14/14 | 13/13, 13/13 | 15/15 | 0 |
| Tenderer_B (scanned) | 14/14 | 13/13, 13/13 | 15/15 | 0 |
| Tenderer_C | 14/14 | 12/12, 12/12 | 14/14 | 0 |
| Tenderer_D (scanned, US$) | 15/15 | 13/13, 13/13 | 16/16 | 0 |

**These numbers validate the tool, not the checker.** The ground truth holds only what the generator printed: prices, dosage, totals, shelf life, manufacturer and signatures. So the keys can't test blacked-out fields or anything a person would add. The unit tests (`test/test_score_bid_key.py`) cover the failure paths:
- a wrong presence;
- pages missed or outside the key's;
- a missed or wrong value;
- a value invented under a black bar;
- items outside the menu or not decided;
- multi-file page mapping.

## Real bids (2026-10-05)

### Setup
**The bids.** Two of the three tenders have one bid each in the samples. Both are 62-page scanned offers with parts blacked out.
- **Tender 1 is the development bid.** Every fix made before the held-out run (#9–#12) was found on it. The later ones (#13–#19) came from the results of both bids and from the cloud runs.
- **Tender 2 is held out.** It ran once, at `main@f710a99`, with the settings recorded before the run. The scores of that run stand. Later runs on it are labelled "after the fixes".

**The keys.** There is one answer key per bid, frozen. A model prefilled it from the page images, then a person checked it value by value and froze it. The plan's second, independent key per bid was not made (J9). The Tender 2 key was prefilled by a model that read the bid's pages, which is a bias toward models that read the way that one did.

**The rule set.** Each run drafted its own rule set with the build job (L0 to L4) and confirmed it as drafted:
- the open gaps got one reason;
- no person edited it.

So the scores measure the bid check, not a reviewer's rule set.

**Local runs.**
- **Model:** Qwen3-VL-8B-Instruct, for both text and vision, on Ollama with a 32k context and the 8-bit KV cache, on a 16 GB Mac mini.
- **Server settings:** llama-server's prompt cache was turned off; at its default of 8 GB it pushed the machine into swap.
- **App settings:** `TRIAGE_PAGES_PER_CALL=3`, `LLM_JSON_SCHEMA=1`, `LLM_MAX_TOKENS=4096`, one job at a time.
- **Data class:** confidential projects, so the gateway refuses any cloud endpoint.
- **Why not plain qwen3:8b or qwen3-vl:8b:** both think before answering, about 2,400 tokens for a one-line question, and one hit a 10,000-token runaway. The instruct build doesn't think first.

**Cloud runs.**
- **Data class:** `redacted_sample` projects, with the instructor's clearance. `LLM_CLEARED_HOSTS` names one Azure OpenAI endpoint.
- **Models:**
  - gpt-4.1-mini (2025-04-14);
  - gpt-5-mini (2025-08-07), a reasoning model at effort "medium", with `LLM_MAX_TOKENS=16000` because its reasoning counts against the cap.
- **Cost:** from Azure's token metrics.

### Results
| | T1 local 8B | T1 gpt-4.1-mini | T1 gpt-5-mini | T2 local 8B (held out) | T2 gpt-4.1-mini | T2 gpt-5-mini |
|---|---|---|---|---|---|---|
| presence | 13/15 | 15/15 | 14/15 | 13/13 | 13/13 | 12/13 |
| values, exact | 23/38 | 20/38 | 21/37 | 21/35 | 18/35 | 18/34 |
| of which numbers and dates | 9/9 | 9/9 | 9/9 | 5/5 | 5/5 | 5/5 |
| short text (40 characters or less) | 8/16 | 8/16 | 10/16 | 10/15 | 8/15 | 7/15 |
| long text | 6/12 | 3/12 | 2/12 | 6/15 | 5/15 | 6/15 |
| invented | 3 | 2 | 0 | 2 | 1 | 1 |
| V4 accepted (wrong) | 32 (12) | 31 (13) | 30 (12) | 29 (8) | 27 (10) | 29 (15) |
| V4 flagged (wrong) | 9 (6) | 7 (5) | 5 (2) | 8 (8) | 9 (8) | 6 (2) |
| value pages, own page | 26/33 | 27/31 | 24/28 | 12/30 (28/30 after #13) | 28/28 | 27/29 |
| rule-set gaps | 43 | 40 | 29 | 41 | 38 | 32 |
| checks for a person | 51 of 155 | 46 of 117 | 105 of 188 | 42 of 123 | 29 of 104 | 123 of 190 |
| disqualifying checks | 0 | 0 | 0 | 0 | 0 | 0 |
| rule set, bid check | 20:44, ~35 min | 2:40, ~4 min (est.) | 15:12, 9:51 | 16:43, 38:47 | 2:10, 6:51 | 14:02, 11:01 |

Notes on the table:
- **Kinds of value:** the number, date and text rows exclude signatures, which are scored from the key's item-level flag.
- **Totals:** values are compared only in items that both the key and the checker call present, which is why gpt-5-mini is out of 37 and 34.
- **Value pages:** this covers only the values a model read, so each model has its own total.
- **Tender 1 timing:**
  - Its first local pass was split by fixes, so its page-sorting time (14 min) comes from the run before it.
  - Its gpt-4.1-mini bid check is an estimate that leaves out the answer which ran on for 8 minutes (#17).
- **Tender 1's local column is a development result.** It reflects #9–#13 and #16, which were all found on it.

### What changed because of these runs
Each fix has its own PR and test:

| PR | Fix |
|---|---|
| #9 | The redacted list is bounded: a 12-page form had looped forever, listing 223 names. |
| #10 | A number printed with spaces between its thousands reads whole. |
| #11 | The scorer compares number fields by their number. |
| #12 | A value the model read beats its own redacted mark. This undid a regression from #9, which had offered the names as an enum: 19 of 28 fields were marked redacted, against 0 before. |
| #13 | Each value cites its own page, through a separate locate call. Putting a page per value inside the reading had flipped a 5-page form to "absent". |
| #14 | The scorer adds the per-value page measure. |
| #15 | The UI lists values that no rule checks. |
| #16 | A form found on its pages but read as absent goes to review. |
| #17 | An unusable second read flags its values instead of stopping the check. |
| #18 | `""` is a blank: two blanks had disqualified an offer through the cloud model. |
| #19 | gpt-5 models are treated as reasoning models. |

An experiment on Tender 1's information schedule didn't help: rendering pages at 3x instead of 1.5x, and one call per page instead of one per form, scored 4–5 of 14 every way.

### Limits
- **Two bids, about 70 values.** "14 of 14 numbers and dates" means that much, not a rate.
- **Exact matching.** Text is compared by V4's `agree`, which is whole-word containment. A long answer worded differently from the key scores as wrong. At most a third of the wrong values share half the key's words, so most aren't near misses, but no meaning-based score was run.
- **Model-prefilled keys.** Both keys were prefilled by a model before a person checked them.
- **Rule-set gaps.** The rule sets were confirmed as drafted. A reviewer would have closed gaps that here stay as checks for a person.
