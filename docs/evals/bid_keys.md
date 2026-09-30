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
   | values | matches, as numbers, dates, signature presence or text |
   | invented | values the checker reports where the key says the field is blank or blacked out |

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

## Real bids
Not run yet. It needs the reconciled keys (#69), and a confirmed rule set for each tender.
