# V4 verification on the synthetic case (S4-2, 2026-09-20)

What V4 does: after V3 has read item (l), every value is checked before the engine sees it.
On a page with a text layer the value is looked for verbatim (case and punctuation aside);
found, the field is verified with its quote and box at confidence 1, no model call. On a
scanned page the fields are read a second time, independently (the first reading is never
shown to the model), and compared; agreement verifies, disagreement leaves the value
unverified with both readings kept. An unverified value is `needs_review` in the verdict,
never a pass and never a disqualification. Confidence is per field from then on
(`FieldValue.confidence`, `FieldValue.verification` in the contract).

## Live run through the stack (compose, DeepSeek vision, `tools/check_synthetic_case.py`)

| tenderer | offer | item (l) | fields verified | method | confidence | new calls | cache hits |
|---|---|---|---|---|---|---|---|
| Tenderer_A | digital, 12 pages | pass | 4 of 4 | text layer, quote and box on each citation | 1.0 each | 0 | 3 |
| Tenderer_B | scanned, 16 pages | pass | 4 of 4 | second read, agreement on all four | 1.0 each | 2 | 3 |

Both jobs finished in 1 min 45 s together (rendering included). The second read reported
the same heading, tenderer name, signatory and date as the first, each at confidence 1,
so the mean is 1.0. Tenderer_A's quotes are the page's own text (`Tenderer_A` from the
header, the first hit; `14 August 2026` at box [324.4, 136.1, 399.9, 146.4] on page 10).

## FakeLLM tests (`test/checks/test_verify.py`, 17 tests)

- Text page: every field found (no call), a date the page does not have (unverified at
  0, `needs_review` through the bridge), a value found in part (`14 August` of `14 August
  2025`: 0.67), a value on another of the item's pages (citation moved), a signature
  without a printed name (unchecked, not unverified).
- Scan: one second read that never shows the first reading; agreement (mean confidence);
  disagreement (both readings kept, 0.44, `needs_review`); a blank the second read fills
  (the engine's disqualification withheld); a blank both reads agree on (verified blank);
  a signature agreeing on presence, not wording; a redacted field and an absent
  certificate left unchecked.
- Partial credit needs at least two words and half the value: a lone `12` matching
  `Page 10 of 12` proves nothing.

## Boundaries

- A false "certificate absent" (no item page at all) is not challenged here: V4 has no
  page to check against. That is the S4-5 agent's case (page tools, a budget).
- A correction by a person carries no verification record; the engine takes the
  person's value as given.
- Only item (l) has field specs yet; S4-3 adds one spec list per form.
