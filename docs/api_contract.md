# API contract

Status: **agreed at S0 (2026-09-17)**. This file and `app/rulesets/schema.py` change only through a pull request labelled `contract` with both approvals, and `docs/openapi.json` (the FastAPI app's OpenAPI, checked by `test/test_api_contract.py`) must match, so an accidental API change fails CI. Rows marked *done* are served by `backend/`; the others are still the mock's.

The React UI is built against this file through `web/mock/`, which answers exactly as written here, so the screens do not wait for the real routes. The "Ready" column says at which stop point the real route replaces the mock.

## Conventions

- **Base path and ids.** Routes stay under `/projects/{pid}/...` as today. `pid` is the project slug; `t` is the tenderer folder name; `letter` is a Completeness Check Schedule item `a` to `o`; `version` is the rule-set version integer.
- **Authentication.** `X-API-Key` header today. Per-user sessions with a role (`reviewer`, `approver`, `admin`) arrive with checklist item B9; until then the API takes the acting user from the `X-User` header in development, so events and edits already carry a name. Without the header the user is `anonymous`.
- **Data class.** Every project carries a `data_class` (`synthetic`, `redacted_sample`, `confidential`). The LLM gateway refuses to send anything but synthetic text to an endpoint that is not allow-listed for the class; the API surfaces that as `403 data_class_forbidden`. `POST /projects` takes `data_class`; when absent it is derived from today's `synthetic` flag (`synthetic`, else `confidential`) so existing clients keep working.
- **Errors.** Every error body is `{"error": {"code": "<snake_case>", "message": "<for a person>", "details": {...}}}`. Until the Streamlit UI goes at S5 the body also carries `detail` (the message), which that UI reads. Codes used below: `not_found`, `validation_failed` (422), `conflict` (409), `forbidden` (403), `data_class_forbidden` (403), `self_approval` (403), `unconfirmed_ruleset` (409). A `422` carries the same envelope; `openapi.json` documents it as `ErrorBody` (amended at S2, checklist I1.9).
- **Jobs.** Anything that calls a model returns `202 {"job_id": ...}` at once and runs on the worker. `GET /projects/{pid}/jobs/{job_id}` reports `{state: queued|running|paused|done|failed|dead, progress: Progress {done, total?, unit?}, error}` (`paused`: waiting for a rule-set confirmation). A second job for the same project and tenderer while one is running returns `409 conflict`. A rule-set build is a job of kind `ruleset_build` with `tenderer: null`.
- **Versions.** Every stored result carries the `ruleset_version` it was computed against. Confirming a new version does not touch results; `POST /evaluate` re-decides them against a version and pins them to it, and the verdict it replaced is kept in the `result.reevaluated` event (amended at S4: one result per check, its history in the events).
- **Audit.** Every mutating route writes one event `{kind, project, subject, before, after, user, at, reason}` to the append-only `events` table.
- **Pagination.** List routes accept `?limit=` (default 100, max 1000) and `?cursor=`; paginated responses are `{items: [...], next_cursor}` with `next_cursor` set when more exist (`jobs`, `events`).
- **Timestamps.** Every timestamp the API sends is an ISO-8601 datetime in UTC (`created_at`, `updated_at`, `at`, `created`, `updated`, `confirmed_at`); a query parameter that filters by time (`since`) takes epoch seconds (I1.17, S3).
- **Image links.** `image_url` in `Page` and `PageCitation` is a path relative to the API base, signed and short-lived; use it as given (I1.9).

## Rules window (L0 to L5)

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| POST | `/projects/{pid}/ruleset/build` | `{}` | `202 {job_id}` | S3 done | Runs L0 to L4 on the worker (job kind `ruleset_build`, `tenderer: null`); the parse is cached under the project. The result is the draft: a new one, or the open one replaced. A rebuild never overwrites a human edit: an edited item keeps its rules, template and notes, a corrected slot gets the new suggestion as `model_value`, a person's own items and gap reasons stay. `409` while a build runs or without tender documents. |
| GET | `/projects/{pid}/ruleset` | `?version=` | `RuleSet` | S2 done | Latest draft by default; a confirmed version by number. Typed as `RuleSet` in `openapi.json`; `updated_by` is the draft's last editor (I1.6, I1.17). |
| GET | `/projects/{pid}/ruleset/versions` | | `[RuleSetVersion]` | S2 done | ISO datetimes; `updated_by` is the draft's last editor (I1.17). |
| GET | `/projects/{pid}/ruleset/diff` | `?from=&to=` | `Diff` | S3 done | Items added, removed, changed; per changed item the fields and the edit record, `null` when the rule builder made the change (I1.14). |
| PATCH | `/projects/{pid}/ruleset/items/{letter}` | `ItemPatch` | `RuleSetItem` | S3 done | One of a slot value, a rule (replaced by id or appended), the template or a note (`ItemNote`, I1.13); `reason` required, else `400 bad_request`. Sets `status: edited` with the person's `edit`; a corrected slot keeps the model's value in `model_value` through every later correction. An edit to a confirmed set opens draft N+1 (parent N). |
| POST | `/projects/{pid}/ruleset/items` | `NewItem` | `201 RuleSetItem` | S3 done | An item a person adds from a clause; lettered `x1`, `x2`, ...; `edited` with their record (I1.16). No template, so its rules carry their own outcomes or the body is `422`. |
| DELETE | `/projects/{pid}/ruleset/items/{letter}` | `{reason}` | `204` | S3 done | |
| PUT | `/projects/{pid}/ruleset/draft` | `RuleSet` | `RuleSet` | S2 done | Whole-draft JSON editor. Validated against `schema.py`; `422 validation_failed` lists the errors. |
| POST | `/projects/{pid}/ruleset/confirm` | `{}` | `RuleSet` | S2 done | `403 self_approval` if the approver is the last editor; `409 conflict` with `details.blockers` naming each cause: an item that needs input or is a gap, an empty required slot of the item's template whatever the item's status (I1.15, S3), a template the server cannot load, a gap without a reason. Creates version N, status confirmed. |
| GET | `/projects/{pid}/ruleset/gaps` | | `[Gap]` | S3 done | The current rule set's gaps (uncovered clauses, filled by L4 at S3-4), with reasons once given. |
| PATCH | `/projects/{pid}/ruleset/gaps/{node_id}` | `{reason}` | `Gap` | S3 done | Gives a gap its reason, recorded as `Gap.edit` (I1.12). |
| PATCH, DELETE | `/projects/{pid}/ruleset/items/{letter}/notes/{i}` | `NotePatch {note, reason}` / `{reason}` | `RuleSetItem` | S3 done | Edit or remove note `i` of an item (I1.13); `404` past the last note. |

## Stage I and II window (V0 to V7)

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| POST | `/projects/{pid}/checks` | `{tenderers?: [t]}` | `202 {job_ids: {t: job_id}}` | S2 done | `409 unconfirmed_ruleset` unless a confirmed rule set exists. One job per vendor. |
| GET | `/projects/{pid}/jobs` | | `[Job]` | S2 | S2 done
| GET | `/projects/{pid}/jobs/{job_id}` | | `Job` | S2 | S2 done
| POST | `/projects/{pid}/jobs/{job_id}/retry` | `{}` | `202 {job_id}` | S4 done | For `failed` and `dead` jobs; the run continues from its saved steps. `409` for any other state. |
| GET | `/projects/{pid}/bids/{t}/results` | `?version=` | `BidResult` | S2 done, S4 verification | Fields with citations and confidence, item verdicts, Stage I and II conclusion, `ruleset_version`, agent trace, cost. Since S4-2 every value carries `FieldValue.verification` (V4): checked on the page's text layer, or by a second, independent read on a scan; `confidence` is per field; an unverified value is `needs_review` in `checks`, never a pass or a disqualification. |
| PATCH | `/projects/{pid}/bids/{t}/fields/{letter}/{field}` | `CorrectionRequest` | `BidResult` | S4 done | Correct a value, mark a document present or absent, or point to another page; `reason` required, an empty request is `400`. The model's value is kept beside the person's (`FieldValue.correction`); the verdict is re-decided by the engine at once, no model call; a review confirmation on the tenderer is withdrawn. `404` for a field the result does not have. |
| POST | `/projects/{pid}/bids/{t}/review/confirm` | `{}` | `BidResult` | S4 done | `409 conflict` with `details.fields` while any checked field is still `needs_review`. Sets `review_confirmed_by`; a later correction or a re-evaluation that changes the verdict clears it. Reports wait for this. |
| POST | `/projects/{pid}/evaluate` | `EvaluateRequest {version?}` | `202 {job_id}` | S4 done | Every checked tenderer re-decided against a confirmed rule-set version (default: the latest confirmed) as a job of kind `evaluate` (`tenderer: null`). Engine only, no model call; fields a new rule needs that were never extracted read as blank until S4-3 extracts them. Results are pinned to the version; a result whose verdict changed loses its review confirmation and gets a `result.reevaluated` event with the verdict before and after. |

## Document viewer

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| GET | `/projects/{pid}/documents` | | `[Document]` | S2 | S2 done
| GET | `/projects/{pid}/documents/{doc_id}/pages` | | `[Page]` | S2 | S2 done
| GET | `/projects/{pid}/documents/{doc_id}/pages/{n}/image` | `?highlight=` | `image/png` | S2 done | Served through a signed, short-lived URL returned inside `BidResult` and `Page`; the API key never appears in a query string. A `PageCitation` with a `quote` carries `highlight` inside the signature: use `image_url` as given. A page-only link with a client-appended `highlight` still opens (pre-S2 clients); that fallback goes once the web UI uses the signed link. |
| GET | `/projects/{pid}/documents/{doc_id}/nodes` | | `[Node]` | S3 done | Clause tree from L0: `{node_id, parent_id, kind, number, title, page, box}`; `409 not_built` before the first build. |

## Scoring, report, audit

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| GET | `/projects/{pid}/price-summary` | `?version=` | `PriceSummary` | S4 done | Rows and ranking from the confirmed rule set's price parameters (the estimated quantity from the price schedule item's slot; cost-effectiveness when a rule reads the optimal dosage) and each checked tenderer's extracted prices with the reviewer's corrections applied. No model. Every computable offer is ranked; `recommended` is the best-ranked conforming one (Stage I and II pass, as the client's Price Summary). A US$ quotation is converted at `PRICING_USD_HKD` (7.8 unless set) and says so in `remark`. `missing` lists tenderers checked against another version. `409 unconfirmed_ruleset` without a confirmed rule set; `404` for a version that is not confirmed. |
| GET | `/projects/{pid}/evaluation` | `?version=` | `Evaluation` | S4 done | The summary across tenderers: each one's stages, items, review and corrections, the Stage I and II conclusions in the Summary List's voice, the recommendation, and the `PriceSummary`. |
| GET | `/projects/{pid}/reports` | `?version=` | `[ReportInfo]` | S4 done | The three reports (`price_summary.docx`, `summary_list.docx`, `evaluation_record.docx`) with `generated_at` (null until first downloaded) and `approver` (who confirmed the reviews). |
| GET | `/projects/{pid}/reports/{name}` | `?version=` | `.docx` | S4 done | Rendered fresh from the stored results. `409 review_pending` with `details.tenderers` while any checked tenderer's review is not confirmed; `404` for an unknown name or nothing checked. Each report states the rule-set version and its confirmer, the models, who confirmed the reviews and when it was generated, and marks every reviewer's correction and every edited rule-set item. The Streamlit pipeline's routes moved to `/legacy/evaluation` and `/legacy/reports` until S5. |
| GET | `/projects/{pid}/events` | `?since=&kind=&limit=&cursor=` | `[Event]` | S2 done | The audit panel. |

## Projects and uploads (today's routes, kept)

`POST/GET /projects`, `GET/DELETE /projects/{pid}`, `POST /projects/{pid}/tender`, `POST /projects/{pid}/bids/{t}`, `POST /projects/{pid}/import`, `GET /inbox`, `GET /projects/{pid}/status`, `GET /projects/{pid}/usage` stay as they are. `POST /projects` gains a required `data_class`.

## Routes removed at S5

`POST /projects/{pid}/run`, `POST /projects/{pid}/resume`, `GET /projects/{pid}/graph`, `GET/PUT /projects/{pid}/rubric`, `GET/PUT /projects/{pid}/bids/{t}/extraction`, `POST /projects/{pid}/legacy/evaluate` (the old evaluation, moved off `/evaluate` at S4 so the contract's route could take the path), and the `?key=` image routes are deprecated from S2 and kept only for the Streamlit UI, which goes at S5 together with them.

## Models

From `app/rulesets/schema.py` (shared): `RuleSet`, `RuleSetItem`, `ItemNote`, `SlotSpec`, `SlotValue`, `TemplateRule`, `Outcome`, `FollowUp`, `Normalise`, `Template`, `ConsequenceDefaults`, `FollowUpDeadline`, `Citation`, `Gap`, `PartSpec`, `Edit`, and the enums `DataClass`, `CheckType`, `Part`, `Consequence`, `ItemStatus`; the closed outcome vocabulary is `OUTCOME_KEYS`. (S0 amendments of 2026-09-17: `Tier` became `Part` on an item; a rule names a `Consequence` tier or carries its own `outcomes`.) (S2 amendments of 2026-09-18, checklist I1: `RuleSet.parts: [PartSpec {part, title, citation, clauses}]` holds the Part intros L0 locates; `RuleSet.updated_by` is server-owned; `Citation.candidates` lists every node the resolver matched when there were several, `node_id` being the chosen one; `Gap.edit` attributes a gap's reason; `needs_input` also covers an item located with no rules yet.)

API-only models, defined in `backend/schemas_api.py` and exported into `docs/openapi.json`:

- `Job {job_id, kind, project, tenderer?, state, step?, progress: Progress {done, total?, unit?}, attempt, error?, ruleset_version?, created_at, updated_at}`
- `ItemPatch {slot?: {name, value}, rule?: TemplateRule, template?: str, note?: ItemNote, reason: str}`
- `NewItem {title, part, citation: Citation, rules: [TemplateRule], reason: str}`
- `Diff {from, to, added: [letter], removed: [letter], changed: [{letter, fields: [str], edit: Edit | null}]}`; `edit` is null for a change the rule builder made, not a person (I1.14)
- `Project {id, name, synthetic, data_class, created, status: ProjectStatus {state: idle|running|waiting|done|error, detail?, updated?}, tender_files?, bidders?, extracted?, has_rubric?, has_evaluation?, reports?}`; `GET /projects` lists them without the detail fields; `status` is an object (`status.state` is `idle|running|waiting|done|error`), not a string (I1.6)
- `RuleSetVersion {version, status, parent_version, created_by, created_at, confirmed_by, confirmed_at, updated_by}`, ISO datetimes (I1.17)
- `NotePatch {note: ItemNote, reason}`, `ReasonBody {reason}` (the DELETE bodies and the gap PATCH)
- `Node {node_id, parent_id?, kind, number?, title?, page?, box?}` (the marker's box in PDF points), `BuildResponse {job_id}`
- `EvaluateRequest {version?}`, `JobStarted {job_id}` (evaluate and retry)
- `ErrorBody {error: {code, message, details}, detail}` (I1.9)
- `BidResult {tenderer, run_id, ruleset_version, fields: {letter: {field: FieldValue}}, verdicts: {letter: Verdict}, stage1: StageSummary, stage2?: StageSummary, trace?, cost: {calls, cache_hits, usd, waited_seconds}, review_confirmed_by?}`. Since S4-3 every item of the rule set has a verdict and its fields come through the item's form (the template's form, else the form serving the item's letter; see Forms and fields); `stage1` and `stage2` roll up the rules' stages (`stage2` is null when no rule is Stage II; an item whose every field is dormant is `dormant`). A comparison check (`value`, `range`, `unit`, `date`, `math`, `cross_document_match`, `contains`) never disqualifies: a mismatch is `needs_review` with the reading and the expectation in `note`; `human_only` is always `needs_review`; a rule on a field no form reads is `needs_review` (`unextracted:`), never a blank; an item whose template is not in the library is `needs_review`, never a silent pass.
- `FieldValue {value, redacted, confidence, page?: PageCitation, correction?: {value, by, reason, model_value}, model_value?, verification?: Verification}`; `confidence` is per field after V4: 1 for a value found on the text layer, the fraction of its words found otherwise (at least two words and half of them, else 0); on a scan the mean of the two reads when they agree, half the lower when they differ; the model's own figure when nothing could be checked
- `Verification {verified: bool | null, method: text_layer | second_read | null, second_value?, note}` (S4-2, V4): on a page with a text layer the value was looked for verbatim (case and punctuation aside), and `page.quote` is the text as the page has it; on a scanned page the fields were read a second time, independently (the first reading is never shown to the model), and compared, agreement on wording (whole-word containment counts, months abbreviate) or, for a signature, on presence alone; `second_value` is that second reading. `verified` is null when nothing could be checked (redacted, blank on a text page, a signature on a text layer, no page); a person's correction carries no `verification`. One model call per scanned offer, none for a digital one.
- `PageCitation {doc_id, file, page, image_url, quote?, box?, page_size?}`: where a value was read and a signed link to the page. When the value is found on the page's text layer, `quote` is that text as the page has it, `box` is `[x0, y0, x1, y1]` around it in PDF points with the origin at the page's top-left (y down, as on the image), `page_size` is the page's `[width, height]` in points (to scale `box` onto the image: multiply by image width / `page_size[0]`), and `image_url` renders the quote highlighted. Otherwise (scanned page, value not on the text layer) all three are null and `image_url` is the plain page; on a scan V4 verifies by a second read instead (`FieldValue.verification`, S4-2). (Amended at S2, checklist I1.)
- `Verdict {outcome, worst, part, rule_ids, reason, checks: [CheckedField], evidence: [PageCitation]}`; `outcome` is the engine's overall status (dormant fields do not count against a tender as submitted), `worst` includes dormant
- `CheckedField {field_id, field, status, note?, redacted, stage, follow_up?}`; `field` is the key into `BidResult.fields[letter]` (I1.10); a field whose value V4 could not verify is `needs_review` with `note` starting `unverified:` whatever the rule says (S4-2). `StageSummary {outcome, items: {letter: outcome}}`
- `CorrectionRequest {value?: any, present?: bool, page?: int, reason: str}`, the body of the S4 field PATCH; `Correction {value, by, reason, model_value}` is the stored record inside `FieldValue` (I1.8)
- `PriceSummary {ruleset_version, scheme: {type: cost_effectiveness | unit_price_x_quantity, quantity, unit, currency, usd_hkd, source}, rows: [PriceRow], recommended?, missing: [t]}`; `PriceRow {tenderer, run_id, conforming, currency, unit_price, unit_price_hkd, dosage, dosage_rounded, estimated_goods_price, quoted_total, arithmetic_ok, cost_effectiveness, ranking, remark, stage1, stage2, reviewed_by, corrected: [field]}` (S4-4)
- `Evaluation {ruleset_version, tenderers: [{tenderer, run_id, stage1, stage2, items: {letter: outcome}, reviewed_by, corrections, conforming}], stage1_conclusion, stage2_conclusion, recommendation, recommended?, price: PriceSummary}`, `ReportInfo {name, version, generated_at?, approver?}` (S4-4)
- `Document {doc_id, file, path, kind, tenderer?, pages, data_class}`; `path` is relative to the project (`tender/09 Schedules.pdf`, `bids/Tenderer_A/offer.pdf`), the form a rule-set `Citation.file` uses, so a citation finds its document by `Document.path == Citation.file` (amended at S2, checklist I1), `Page {page, has_text, label?, title?, summary?, signed?, has_table?, image_url}`, `Event {id, kind, project, subject?, before?, after?, user, reason?, at}`; `Node`, `PriceSummary`, `Evaluation` as described in the tables.

## Questions settled at S2 (checklist I1, positions agreed 2026-09-20)

Items 1 and 2 landed in PR #35; 3 to 10, 14, 16 and 17 in #41 and #44. Items 8 (`CorrectionRequest`) and 12 (`PATCH /ruleset/gaps/{node_id}`) are rows in this file only until S4 and S3; 11 to 13 and 15 land with the S3 rule-set editing routes, when `ItemPatch`, `NewItem` and `Diff` enter `openapi.json`.

3. `RuleSet.parts: [PartSpec]` for the Part intros. 4. `needs_input` covers "located, no rules yet"; no new status. 5. `Citation.candidates` beside `node_id`; a person picks. 6. `GET /projects`, `GET /projects/{pid}` and the three rule-set routes are typed (`Project`, `RuleSet`). 7. `jobs` and `events` are paged; `Job.state` includes `paused`; `Job.progress` is `Progress`. 8. `CorrectionRequest` is the request body, `Correction` the stored record. 9. `422` is `ErrorBody` in `openapi.json`; `image_url` is relative to the API base. 10. `CheckedField.field`. 11. The S3 rule-set routes are typed (done at S3-1). 12. `PATCH /ruleset/gaps/{node_id}` with `reason`, recorded as `Gap.edit` (done). 13. `ItemPatch.note` is an `ItemNote`; notes are edited and removed by index (done). 14. `Diff.changed[].edit` may be null; `model_value` stays on slots only, the parent version is the model's original for rules and templates (done). 15. Confirm checks every template's required slots, not the status alone (done: `details.blockers`). 16. An item a person adds is `edited` with its edit record; `novel` stays for L3 drafts. 17. `RuleSetVersion` uses ISO datetimes and carries `updated_by`; `RuleSet.updated_by` too. Every other timestamp is ISO as well and `ProjectStatus.state` is a closed list (S3-1, from the #41 review).

## Questions settled at S0

1. Resolved (2026-09-17, both): `ruleset` for the new routes; `rubric` survives only on the legacy routes, which go at S2.
2. Resolved (2026-09-17, in `schema.py`): `letter` is `a` to `z` for schedule items and `x1`, `x2`, ... for items a person adds.
3. Resolved (2026-09-17, both): `POST /checks` always uses the latest confirmed rule set; `?version=` exists only on `evaluate`. Implemented at S2.
4. Resolved (2026-09-17, both): `test/test_api_contract.py` checks `docs/openapi.json`; regenerate with `UPDATE_OPENAPI=1`.

## Forms and fields (S4-3)

The closed menu of forms an offer is made of (`app/checks/forms.py`): one per page label that serves a Completeness Check Schedule item, each with a fixed field menu. A form's id is the prefix of its flat keys and of `BidResult.fields[letter]`; a template's rules and a drafted rule name these fields (`price_schedule.unit_price`), so production templates must use them. Every form has `document` (its heading as printed; null when the form is absent). A `number` is read as printed and coerced (the printed form stays beside it and is what V4 checks); a `signature` holds the printed name or title next to the signature, `signature present` when only a signature or chop is visible, null when unsigned; a `date` is kept as printed and parsed by the `date` check.

| Form (key prefix) | Page label | Fields (kind) |
|---|---|---|
| `offer_to_be_bound` (Tender Form, Offer to be Bound) | `tender_form_offer_to_be_bound` | `document` (text), `tenderer_name` (text), `signature` (signature), `date` (date), `chop` (text) |
| `price_schedule` (Price Schedule, Part A) | `price_schedule_part_a` | `document` (text), `unit_price` (number), `currency` (text), `optimal_dosage` (number), `quantity` (number), `total` (number), `signature` (signature) |
| `price_schedule_parts_c_d` (Price Schedule, Parts C and D) | `price_schedule_parts_c_d` | `document` (text), `part_c` (text), `part_d` (text) |
| `particulars_of_goods` (Particulars of Goods Schedule) | `particulars_of_goods_schedule` | `document` (text), `product_name` (text), `manufacturer` (text), `country_of_origin` (text), `shelf_life_months` (number), `packaging` (text), `active_ingredient_pct` (number), `bulk_density` (number) |
| `information_schedule` (Information Schedule) | `information_schedule` | `document` (text), `track_record` (text), `quality_certification` (text), `production_capacity` (text) |
| `tender_sample_declaration` (Tender Sample Declaration) | `tender_sample_declaration` | `document` (text), `declaration` (text) |
| `documentary_evidence` (Documentary Evidence of Compliance) | `documentary_evidence_of_compliance` | `document` (text), `evidence` (text) |
| `manufacturer_letter` (Manufacturer's Letter of Intent) | `manufacturer_letter_of_intent` | `document` (text), `manufacturer` (text), `tenderer_name` (text), `signature` (signature) |
| `board_resolution` (Certified Extract of Board Resolution) | `board_resolution` | `document` (text), `resolution` (text), `certified_by` (text) |
| `contact_details` (Appendix to the Terms of Tender, Contact Details) | `contact_details` | `document` (text), `tenderer_name` (text), `contact_person` (text), `telephone` (text), `email` (text), `address` (text) |
| `noncollusive_certificate` (Non-collusive Tendering Certificate) | `noncollusive_certificate` | `document` (text), `tenderer_name` (text), `signature` (signature), `date` (date) |
| `compliance_schedule` (Compliance Schedule) | `compliance_schedule` | `document` (text), `delivery_days` (number), `non_compliances` (text) |
| `method_of_production` (Method of Production Statement) | `method_of_production_statement` | `document` (text), `statement` (text) |

One model call reads one form (all its pages, one fixed reading); an absent form costs one resolve call and no read; a scanned form costs one more call for V4's second read.
