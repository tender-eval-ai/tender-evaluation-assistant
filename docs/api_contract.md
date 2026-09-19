# API contract

Status: **agreed at S0 (2026-09-17)**. This file and `app/rulesets/schema.py` change only through a pull request labelled `contract` with both approvals, and `docs/openapi.json` (the FastAPI app's OpenAPI, checked by `test/test_api_contract.py`) must match, so an accidental API change fails CI. Rows marked *done* are served by `backend/`; the others are still the mock's.

The React UI is built against this file through `web/mock/`, which answers exactly as written here, so the screens do not wait for the real routes. The "Ready" column says at which stop point the real route replaces the mock.

## Conventions

- **Base path and ids.** Routes stay under `/projects/{pid}/...` as today. `pid` is the project slug; `t` is the tenderer folder name; `letter` is a Completeness Check Schedule item `a` to `o`; `version` is the rule-set version integer.
- **Authentication.** `X-API-Key` header today. Per-user sessions with a role (`reviewer`, `approver`, `admin`) arrive with checklist item B9; until then the API takes the acting user from the `X-User` header in development, so events and edits already carry a name. Without the header the user is `anonymous`.
- **Data class.** Every project carries a `data_class` (`synthetic`, `redacted_sample`, `confidential`). The LLM gateway refuses to send anything but synthetic text to an endpoint that is not allow-listed for the class; the API surfaces that as `403 data_class_forbidden`. `POST /projects` takes `data_class`; when absent it is derived from today's `synthetic` flag (`synthetic`, else `confidential`) so existing clients keep working.
- **Errors.** Every error body is `{"error": {"code": "<snake_case>", "message": "<for a person>", "details": {...}}}`. Until the Streamlit UI goes at S5 the body also carries `detail` (the message), which that UI reads. Codes used below: `not_found`, `validation_failed` (422), `conflict` (409), `forbidden` (403), `data_class_forbidden` (403), `self_approval` (403), `unconfirmed_ruleset` (409). A `422` carries the same envelope; `openapi.json` documents it as `ErrorBody` (amended at S2, checklist I1.9).
- **Jobs.** Anything that calls a model returns `202 {"job_id": ...}` at once and runs on the worker. `GET /projects/{pid}/jobs/{job_id}` reports `{state: queued|running|paused|done|failed|dead, progress: Progress {done, total?, unit?}, error}` (`paused`: waiting for a rule-set confirmation). A second job for the same project and tenderer while one is running returns `409 conflict`.
- **Versions.** Every stored result carries the `ruleset_version` it was computed against. Confirming a new version does not rewrite old results; re-evaluation creates new ones.
- **Audit.** Every mutating route writes one event `{kind, project, subject, before, after, user, at, reason}` to the append-only `events` table.
- **Pagination.** List routes accept `?limit=` (default 100, max 1000) and `?cursor=`; paginated responses are `{items: [...], next_cursor}` with `next_cursor` set when more exist (`jobs`, `events`).
- **Image links.** `image_url` in `Page` and `PageCitation` is a path relative to the API base, signed and short-lived; use it as given (I1.9).

## Rules window (L0 to L5)

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| POST | `/projects/{pid}/ruleset/build` | `{}` | `202 {job_id}` | S3 | Runs L0 to L4. A rebuild never overwrites a human edit; it stores the new suggestion beside it (`model_value`). |
| GET | `/projects/{pid}/ruleset` | `?version=` | `RuleSet` | S2 done | Latest draft by default; a confirmed version by number. Typed as `RuleSet` in `openapi.json`; `updated_by` is the draft's last editor (I1.6, I1.17). |
| GET | `/projects/{pid}/ruleset/versions` | | `[RuleSetVersion]` | S2 done | ISO datetimes; `updated_by` is the draft's last editor (I1.17). |
| GET | `/projects/{pid}/ruleset/diff` | `?from=&to=` | `Diff` | S3 | Items added, removed, changed; per changed item the fields and the edit record. |
| PATCH | `/projects/{pid}/ruleset/items/{letter}` | `ItemPatch` | `RuleSetItem` | S3 | Change a slot value, a rule, the template or a note (`note` is an `ItemNote`, I1.13). `reason` required. Sets `status: edited`; an item a person adds is `edited` too, with its edit record (I1.16). |
| POST | `/projects/{pid}/ruleset/items` | `NewItem` | `RuleSetItem` | S3 | Add an item from clause text selected in the viewer; the selection becomes its citation. `reason` required. |
| DELETE | `/projects/{pid}/ruleset/items/{letter}` | `{reason}` | `204` | S3 | |
| PUT | `/projects/{pid}/ruleset/draft` | `RuleSet` | `RuleSet` | S2 done | Whole-draft JSON editor. Validated against `schema.py`; `422 validation_failed` lists the errors. |
| POST | `/projects/{pid}/ruleset/confirm` | `{}` | `RuleSet` | S2 done | `403 self_approval` if the approver is the last editor; `409 conflict` while an item needs input, a required slot of its template is empty whatever the item's status (I1.15), or a gap has no reason. Creates version N, status confirmed. |
| GET | `/projects/{pid}/ruleset/gaps` | | `[Gap]` | S3 | Uncovered clauses and "shall/must" sentences, with reasons once given. |
| PATCH | `/projects/{pid}/ruleset/gaps/{node_id}` | `{reason}` | `Gap` | S3 | Gives a gap its reason, recorded as `Gap.edit` (I1.12). |
| PATCH, DELETE | `/projects/{pid}/ruleset/items/{letter}/notes/{i}` | `ItemNote` / `{reason}` | `RuleSetItem` | S3 | Edit or remove note `i` of an item (I1.13). |

## Stage I and II window (V0 to V7)

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| POST | `/projects/{pid}/checks` | `{tenderers?: [t]}` | `202 {job_ids: {t: job_id}}` | S2 done | `409 unconfirmed_ruleset` unless a confirmed rule set exists. One job per vendor. |
| GET | `/projects/{pid}/jobs` | | `[Job]` | S2 | S2 done
| GET | `/projects/{pid}/jobs/{job_id}` | | `Job` | S2 | S2 done
| POST | `/projects/{pid}/jobs/{job_id}/retry` | `{}` | `202` | S4 | For `failed` and `dead` jobs. |
| GET | `/projects/{pid}/bids/{t}/results` | `?version=` | `BidResult` | S2 done | Fields with citations and confidence, item verdicts, Stage I and II conclusion, `ruleset_version`, agent trace, cost. |
| PATCH | `/projects/{pid}/bids/{t}/fields/{letter}/{field}` | `Correction` | `BidResult` | S4 | Correct a value, mark a document present or absent, or point to another page. `reason` required. The model's value is kept; the verdict is recomputed by the engine with zero LLM calls. |
| POST | `/projects/{pid}/bids/{t}/review/confirm` | `{}` | `BidResult` | S4 | `409 conflict` while any field is still `needs_review`. Reports wait for this. |
| POST | `/projects/{pid}/evaluate` | `{version?}` | `202 {job_id}` | S4 | Re-evaluate every checked vendor against a rule-set version. Engine only; LLM calls only for fields a new rule needs that were never extracted. Kept from today's API, now a job. |

## Document viewer

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| GET | `/projects/{pid}/documents` | | `[Document]` | S2 | S2 done
| GET | `/projects/{pid}/documents/{doc_id}/pages` | | `[Page]` | S2 | S2 done
| GET | `/projects/{pid}/documents/{doc_id}/pages/{n}/image` | `?highlight=` | `image/png` | S2 done | Served through a signed, short-lived URL returned inside `BidResult` and `Page`; the API key never appears in a query string. A `PageCitation` with a `quote` carries `highlight` inside the signature: use `image_url` as given. A page-only link with a client-appended `highlight` still opens (pre-S2 clients); that fallback goes once the web UI uses the signed link. |
| GET | `/projects/{pid}/documents/{doc_id}/nodes` | | `[Node]` | S3 | Clause tree from L0: `{node_id, parent_id, kind, number, title, page, box}`. |

## Scoring, report, audit

| Method | Path | Request | Response | Ready | Notes |
|---|---|---|---|---|---|
| GET | `/projects/{pid}/price-summary` | `?version=` | `PriceSummary` | S4 | Rows and ranking from the confirmed rule set's price parameters. |
| GET | `/projects/{pid}/evaluation` | `?version=` | `Evaluation` | S4 | Summary across vendors. |
| GET | `/projects/{pid}/reports` | | `[{name, version, generated_at, approver}]` | S4 | |
| GET | `/projects/{pid}/reports/{name}` | | `.docx` | S4 | Word reports state the rule-set version, model and approver, and mark human corrections and edited rules. |
| GET | `/projects/{pid}/events` | `?since=&kind=&limit=&cursor=` | `[Event]` | S2 done | The audit panel. |

## Projects and uploads (today's routes, kept)

`POST/GET /projects`, `GET/DELETE /projects/{pid}`, `POST /projects/{pid}/tender`, `POST /projects/{pid}/bids/{t}`, `POST /projects/{pid}/import`, `GET /inbox`, `GET /projects/{pid}/status`, `GET /projects/{pid}/usage` stay as they are. `POST /projects` gains a required `data_class`.

## Routes removed at S5

`POST /projects/{pid}/run`, `POST /projects/{pid}/resume`, `GET /projects/{pid}/graph`, `GET/PUT /projects/{pid}/rubric`, `GET/PUT /projects/{pid}/bids/{t}/extraction`, and the `?key=` image routes are deprecated from S2 and kept only for the Streamlit UI, which goes at S5 together with them.

## Models

From `app/rulesets/schema.py` (shared): `RuleSet`, `RuleSetItem`, `ItemNote`, `SlotSpec`, `SlotValue`, `TemplateRule`, `Outcome`, `FollowUp`, `Normalise`, `Template`, `ConsequenceDefaults`, `FollowUpDeadline`, `Citation`, `Gap`, `PartSpec`, `Edit`, and the enums `DataClass`, `CheckType`, `Part`, `Consequence`, `ItemStatus`; the closed outcome vocabulary is `OUTCOME_KEYS`. (S0 amendments of 2026-09-17: `Tier` became `Part` on an item; a rule names a `Consequence` tier or carries its own `outcomes`.) (S2 amendments of 2026-09-18, checklist I1: `RuleSet.parts: [PartSpec {part, title, citation, clauses}]` holds the Part intros L0 locates; `RuleSet.updated_by` is server-owned; `Citation.candidates` lists every node the resolver matched when there were several, `node_id` being the chosen one; `Gap.edit` attributes a gap's reason; `needs_input` also covers an item located with no rules yet.)

API-only models, defined in `backend/schemas_api.py` and exported into `docs/openapi.json`:

- `Job {job_id, kind, project, tenderer?, state, step?, progress: Progress {done, total?, unit?}, attempt, error?, ruleset_version?, created_at, updated_at}`
- `ItemPatch {slot?: {name, value}, rule?: TemplateRule, template?: str, note?: ItemNote, reason: str}`
- `NewItem {title, part, citation: Citation, rules: [TemplateRule], reason: str}`
- `Diff {from, to, added: [letter], removed: [letter], changed: [{letter, fields: [str], edit: Edit | null}]}`; `edit` is null for a change the rule builder made, not a person (I1.14)
- `Project {id, name, synthetic, data_class, created, status: ProjectStatus {state, detail?, updated?}, tender_files?, bidders?, extracted?, has_rubric?, has_evaluation?, reports?}`; `GET /projects` lists them without the detail fields; `status` is an object (`status.state` is `idle|running|waiting|done|error`), not a string (I1.6)
- `RuleSetVersion {version, status, parent_version, created_by, created_at, confirmed_by, confirmed_at, updated_by}`, ISO datetimes (I1.17)
- `ErrorBody {error: {code, message, details}, detail}` (I1.9)
- `BidResult {tenderer, run_id, ruleset_version, fields: {letter: {field: FieldValue}}, verdicts: {letter: Verdict}, stage1: StageSummary, stage2?: StageSummary, trace?, cost: {calls, cache_hits, usd, waited_seconds}, review_confirmed_by?}`
- `FieldValue {value, redacted, confidence, page?: PageCitation, correction?: {value, by, reason, model_value}, model_value?}`
- `PageCitation {doc_id, file, page, image_url, quote?, box?, page_size?}`: where a value was read and a signed link to the page. When the value is found on the page's text layer, `quote` is that text as the page has it, `box` is `[x0, y0, x1, y1]` around it in PDF points with the origin at the page's top-left (y down, as on the image), `page_size` is the page's `[width, height]` in points (to scale `box` onto the image: multiply by image width / `page_size[0]`), and `image_url` renders the quote highlighted. Otherwise (scanned page, value not on the text layer) all three are null and `image_url` is the plain page. Quote verification on scanned pages arrives with V4 (S4). (Amended at S2, checklist I1.)
- `Verdict {outcome, worst, part, rule_ids, reason, checks: [CheckedField], evidence: [PageCitation]}`; `outcome` is the engine's overall status (dormant fields do not count against a tender as submitted), `worst` includes dormant
- `CheckedField {field_id, field, status, note?, redacted, stage, follow_up?}`; `field` is the key into `BidResult.fields[letter]` (I1.10), `StageSummary {outcome, items: {letter: outcome}}`
- `CorrectionRequest {value?: any, present?: bool, page?: int, reason: str}`, the body of the S4 field PATCH; `Correction {value, by, reason, model_value}` is the stored record inside `FieldValue` (I1.8)
- `Document {doc_id, file, path, kind, tenderer?, pages, data_class}`; `path` is relative to the project (`tender/09 Schedules.pdf`, `bids/Tenderer_A/offer.pdf`), the form a rule-set `Citation.file` uses, so a citation finds its document by `Document.path == Citation.file` (amended at S2, checklist I1), `Page {page, has_text, label?, title?, summary?, signed?, has_table?, image_url}`, `Event {id, kind, project, subject?, before?, after?, user, reason?, at}`; `Node`, `PriceSummary`, `Evaluation` as described in the tables.

## Questions settled at S2 (checklist I1, 2026-09-18)

Items 1 and 2 landed in PR #35. The rest, proposed by Chenyu on 2026-09-18 for Nasi's approval in the same PR as this text:

3. `RuleSet.parts: [PartSpec]` for the Part intros. 4. `needs_input` covers "located, no rules yet"; no new status. 5. `Citation.candidates` beside `node_id`; a person picks. 6. `GET /projects`, `GET /projects/{pid}` and the three rule-set routes are typed (`Project`, `RuleSet`). 7. `jobs` and `events` are paged; `Job.state` includes `paused`; `Job.progress` is `Progress`. 8. `CorrectionRequest` is the request body, `Correction` the stored record. 9. `422` is `ErrorBody` in `openapi.json`; `image_url` is relative to the API base. 10. `CheckedField.field`. 11. The S3 rule-set routes get typed as they are built. 12. `PATCH /ruleset/gaps/{node_id}` with `reason`, recorded as `Gap.edit`. 13. `ItemPatch.note` is an `ItemNote`; notes are edited and removed by index. 14. `Diff.changed[].edit` may be null; `model_value` stays on slots only, the parent version is the model's original for rules and templates. 15. Confirm checks every template's required slots, not the status alone. 16. An item a person adds is `edited` with its edit record; `novel` stays for L3 drafts. 17. `RuleSetVersion` uses ISO datetimes and carries `updated_by`; `RuleSet.updated_by` too.

## Questions settled at S0

1. Resolved (2026-09-17, both): `ruleset` for the new routes; `rubric` survives only on the legacy routes, which go at S2.
2. Resolved (2026-09-17, in `schema.py`): `letter` is `a` to `z` for schedule items and `x1`, `x2`, ... for items a person adds.
3. Resolved (2026-09-17, both): `POST /checks` always uses the latest confirmed rule set; `?version=` exists only on `evaluate`. Implemented at S2.
4. Resolved (2026-09-17, both): `test/test_api_contract.py` checks `docs/openapi.json`; regenerate with `UPDATE_OPENAPI=1`.
