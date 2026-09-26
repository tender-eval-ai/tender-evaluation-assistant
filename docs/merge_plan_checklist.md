# Merge Plan Checklist

Joint review of the "Tender Review Merge Plan" (10-day version, 2026-09-15). This file is the place where both of us record a position on each open item and where the decision is written once it is made. It is updated by pull request; either of us may edit any item.

**How to use.** Every item has five lines. *Plan* quotes what the plan currently says. *Proposal* is the change suggested by Chenyu's review. *Chenyu* and *Nasi* hold each person's position, written in their own words and dated. *Decision* is filled in when both agree, together with the status. An empty position means "not yet stated", not agreement.

**Status values.** `open` (a position is missing), `agreed` (both agree, plan to be updated), `decided` (already settled outside this file), `deferred` (out of the ten days, kept on a later list), `dropped`.

**Context both of us share.** Two bootcamp students, both in the US, no client and no pilot. Each person works on their own area independently and stops at the joint stop points in section D. The goal is the strongest possible joint project for job applications.

Last updated: 2026-09-20 (Chenyu).

## Status board

| ID | Item | Status | Waiting on |
|---|---|---|---|
| A2 | Branch protection on a private repo | decided | — |
| A3 | MinIO as file storage | decided | — |
| A4 | "Redis queue" in AI_camp | agreed | — (update the plan) |
| A5 | Capacity estimate (calls per minute) | agreed | — (update the plan) |
| A6 | Real documents from day 4; live evals | agreed | — (update the plan) |
| A7 | Eval sets ported as they are | agreed | — (update the plan) |
| B1 | Client pilot (and hosting region, pilot slot) | agreed | — (update the plan) |
| B2 | SSO / OIDC identity provider | agreed | — (update the plan) |
| B3 | Retention period with logged deletion | agreed | — (update the plan) |
| B4 | Upload quarantine with malware scan | agreed | — (update the plan) |
| B5 | Restore and rollback drills with RPO / RTO | agreed | — (update the plan) |
| B6 | Infrastructure-as-code profile, two API replicas | agreed | — (update the plan) |
| B7 | Dashboards, alerts, runbook | agreed | — (update the plan) |
| B8 | Daily and weekly ceremonies | agreed | — (update the plan) |
| B9 | Cheap security items kept, done last | agreed | — (update the plan) |
| C1 | What stays from the plan unchanged | agreed | — (update the plan) |
| D1 | Independent tracks and six stop points | agreed | — (update the plan) |
| D2 | Pacing: S0 to S3 in ten days, S4 stretch, S5 after | agreed | — (update the plan) |
| E1 | LLM cache before the orchestrator decision | agreed | — (update the plan) |
| E2 | Procrastinate as the run queue in both variants | agreed | — (update the plan) |
| E3 | Neutral framing of the two variants in the plan | agreed | — (update the plan) |
| E4 | One full day for the comparison, decision next morning | agreed | — (update the plan) |
| E5 | Orchestrator decision record 0001 (S1) | decided | — |
| F1 | Repo stays private until publishable, then org and public | decided | — |
| F2 | Data classes and endpoints named per fixture and eval | agreed | — (update the plan) |
| F3 | Files excluded from the port (commit `7e8e273`, see F5) | agreed | — (update the plan) |
| F4 | Public-release audit at S5 | agreed | — (update the plan) |
| F5 | Port source: pushed commit, no `aicamp-final` tag | agreed | — |
| F6 | Public naming: an AI tender evaluation assistant, no tender numbers or Hong Kong wording | agreed | — (description set 2026-09-26; clean-up PR at S5) |
| G1 | Two independent demos, same image | agreed | Nasi: domain, when chosen |
| G2 | No cloud named in code; configuration only | agreed | — (update the plan) |
| G3 | Abuse limits before a public demo | agreed | — (update the plan) |
| H1 | Portfolio finish checklist | agreed | — (update the plan) |
| I1 | Contract gaps found at S2 (locate, web mock, Rules window) | decided | 1–2 done (#35); 3–10, 14, 16, 17 done (#41, #44); 11–13, 15 at S3 |
| J1 | Parser follow-ups after the S3 recall gate | part done | 1 and 4 done; 2 and 3 open |
| J2 | Where a form's own notes and trigger live | decided | option 1 (#59); next: template ids = form ids, the field map |
| J3 | S4 windows: Scoring and Report | done | — |
| J4 | S4 review: corrections and confirmation in the UI | done | — |
| J5 | S4 review flow in a browser (Playwright) | done | — |
| J6 | Re-evaluate against a confirmed rule-set version | done | — |
| J7 | S3 joint rule-set eval: L0 done; L1-L4 once the templates exist | part done | Nasi: field map and templates (J2 decided) |
| J8 | S5: README results, who built what, CITATION.cff | part done | Nasi: licence (F4), diagram, GIF |
| J10 | The MCP server: retire it with the legacy stack at S5 (amends C1's "Kept, ported, removed") | proposed | Nasi: position |

## A. Corrections to the plan

These are facts, checked against both repositories on 2026-09-15. They need a confirmation, not a debate. (The base repo name and the day-1 git commands were settled on 2026-09-15 and are no longer listed: the joint repo is `chenyufang-data/tender-evaluation-assistant`, the tag `v0-hk-baseline` is pushed, and both of us have push access.)

### A2. Branch protection on a private repo
- Plan: "Settings → Branches → protect main: PR, 1 approval, tests check, no force push".
- Proposal: not available on a private repository on GitHub Free. Until the repo is public: a pre-push hook that refuses pushes to `main`, CODEOWNERS (auto-requests the reviewer for free), and a CI job that fails on a commit to `main` that did not arrive through a merged pull request.
- Chenyu (2026-09-15): stay in the current private repo until publishable, then transfer to an organisation and make it public, where protection is free. Use the convention until then.
- Nasi (2026-09-16): acknowledged; use the convention until the repo is public.
- Decision: decided (Chenyu, 2026-09-15); Nasi acknowledged 2026-09-16.

### A3. MinIO as file storage
- Plan: "Postgres for all records and MinIO for files, started with one command".
- Proposal: MinIO's open-source repository entered maintenance mode in December 2025 and was archived on 25 April 2026; no official binaries and no security fixes. Keep `app/storage.py` as one S3-compatible client configured by endpoint, bucket and credentials, so the same code talks to S3, to GCS through its S3-interoperability keys, or to local disk.
- Chenyu (2026-09-15): Nasi's shared AWS storage is the development store. Only synthetic and redacted sample documents go there; each person uses their own IAM user limited to that bucket; the bucket stays blocked from public access; keys live only in the gitignored `.env`.
- Nasi (2026-09-15): S3 bucket.
- Nasi (2026-09-16): the shared bucket now lives in a new AWS account, because an access key on the old account was exposed; that key is revoked and the old account's resources are removed (done 2026-09-16). The new account is `tender-review-dev` in `us-east-1`, managed by Terraform in `infra/` (PR #21); each of us signs in through IAM Identity Center (`dev-admin` to run Terraform, `dev-synthetic` for the bucket), so there are no long-lived access keys. Chenyu has been given both (done 2026-09-16). Proposal (PR #21): the bucket holds synthetic data only, and the redacted cases stay in each person's private local data folder.
- Chenyu (2026-09-17): agree: the shared bucket holds synthetic data only; the redacted cases stay in each person's local data folder. Signed in through Identity Center on 2026-09-17; both profiles verified, no keys on disk.
- Decision: decided (2026-09-15), amended 2026-09-17: the `tender-review-dev` bucket is the shared development store and holds synthetic data only; `storage.py` stays one S3-compatible client.

### A4. "Redis queue" in AI_camp
- Plan: "AI_camp Flask API, Redis queue, per-page tasks, JSON caches: not ported".
- Proposal: there is no Redis in the repository; `service/batch_jobs.py` uses `ThreadPoolExecutor(3)`. Wording only.
- Chenyu (2026-09-17): agree; wording fix in the plan.
- Nasi (2026-09-16): confirmed: AI_camp has no Redis; `service/batch_jobs.py` uses a thread pool. Fix the wording.
- Decision: agreed (2026-09-17). Plan to be updated.

### A5. Capacity estimate
- Plan: 15,000 scanned pages, 2,500 triage calls plus 2,500 other calls, about 83 minutes at 60 requests per minute and 17 minutes at 300.
- Proposal: those are cloud-provider rate limits. On one DGX Spark running vLLM, a six-page vision call at 150 DPI is roughly 15k input tokens for a Qwen-VL-class model, and one box handles a few such calls per minute, not 60. Measure calls per minute on the real box (or a rented equivalent) at S2 and quote the measured number. "100-vendor batch under 8 hours" is a hypothesis until then.
- Chenyu (2026-09-17): agree: measure on the real endpoint at S2 and quote the measured number; the 8-hour batch stays a hypothesis until then.
- Nasi (2026-09-16): agree: measure calls per minute on the real endpoint at S2 and quote that number.
- Decision: agreed (2026-09-17). Plan to be updated.

### A6. Real documents from day 4; live evals
- Plan: "Real documents are used from D4"; live evals at CP3 and CP4; "real client documents arrive for the pilot tomorrow" on D9.
- Proposal: real client documents never reach a cloud endpoint. Only the redacted sample cases are cleared for cloud models, and that clearance is Chenyu's decision. Every fixture carries a `data_class`, and every live eval names the endpoint it runs against.
- Chenyu (2026-09-17): agree. My clearance covers the camp's redacted sample cases only, per run and named in the stored eval result; nothing confidential leaves the approved environment.
- Nasi (2026-09-16): agree: real client documents never reach a cloud endpoint; every fixture carries a `data_class` and every live eval names its endpoint.
- Decision: agreed (2026-09-17). Plan to be updated.

### A7. Eval sets ported as they are
- Plan: "Rule engine, rule files, leaf extractor, checker prompts, eval sets: port to app/engine/, templates/, novel.py, app/prompts/, test/evals/".
- Proposal: `tests/evals/*` in AI_camp contain vendor values from the redacted bid; the repository also holds `retrieval_eval/production_parser_nodes_full.json`, `ground_truth_full.md` and `archive/reports/tender_compliance_*`, all derived from the redacted documents. Exclude these from the port; keep ground truth and eval sets in the private data folder the plan already describes on D5.
- Chenyu (2026-09-17): agree: exclude them; ground truth and eval sets stay in the private data folder.
- Nasi (2026-09-16): agree: exclude the eval sets and the files derived from the redacted documents; keep them in the private data folder.
- Decision: agreed (2026-09-17). Plan to be updated.

## B. Scope: drop or defer

Proposed because none of these help a job application, and several need a client that does not exist. Each is listed on its own so it can be kept individually.

### B1. Client pilot, hosting region, pilot slot
- Plan: D1 confirms the client's availability; D10 15:00 to 17:00 is "pilot tender with the client in the approved environment"; CP5 KR5 is "pilot tender evaluated with the client's reviewers; findings list recorded"; open decisions include a hosting region for Hong Kong public data and a pilot slot.
- Proposal: there is no client. The sample cases came from the camp as redacted documents, so nobody sends real documents and nobody sits as a reviewer on day 10. CP4 KR1 (run the redacted Tender 1 bid and compare with the historical Summary List and Price Summary) already provides the strongest evidence available. Drop the pilot, the "real documents arrive" line, the hosting-region decision and the pilot-slot decision. If a camp mentor or the person who supplied the sample cases is reachable, replace the pilot with a recorded 30-minute walkthrough on the synthetic case, as a stretch item rather than a key result.
- Chenyu (2026-09-15): keep on the list for Nasi to check; drop unless a camp mentor can act as reviewer.
- Nasi (2026-09-16): agree: drop the pilot, the "real documents arrive" line and the hosting-region and pilot-slot decisions; a recorded walkthrough only if a mentor becomes available.
- Decision: agreed (2026-09-16). Plan to be updated.

### B2. SSO / OIDC identity provider
- Plan: open decision by D8, "client SSO (OIDC or SAML) or per-user accounts with MFA, before D9 auth work"; users, roles and project membership "OIDC-ready".
- Proposal: no client, so no identity provider to integrate. Keep per-user accounts with a role (see B9); drop the OIDC and SAML work.
- Chenyu (2026-09-17): agree: per-user accounts with a role, after S4 (B9).
- Nasi (2026-09-16): agree: per-user accounts with a role; drop OIDC and SAML.
- Decision: agreed (2026-09-17). Plan to be updated.

### B3. Retention period with logged deletion
- Plan: D9, "documents are deleted after the agreed retention period, and the deletion is logged"; a retention job and a retention test.
- Proposal: a retention policy is agreed with a client. Defer.
- Chenyu (2026-09-17): agree: defer.
- Nasi (2026-09-16): agree: defer.
- Decision: agreed (2026-09-17). Plan to be updated.

### B4. Upload quarantine with malware scan
- Plan: D9, "uploaded files wait in quarantine until their size and file type are checked and a malware scan passes".
- Proposal: keep the size cap and file-type check (they are small and part of B9). Defer the quarantine flow and the malware scanner.
- Chenyu (2026-09-17): agree: keep the size cap and file-type check under B9; defer the rest.
- Nasi (2026-09-16): agree: keep the size cap and file-type check; defer quarantine and malware scanning.
- Decision: agreed (2026-09-17). Plan to be updated.

### B5. Restore and rollback drills with RPO / RTO
- Plan: CP5 KR4, "recovery point at most 15 minutes, recovery time at most 4 hours measured; rollback with no data loss"; point-in-time recovery, object versioning, drill records.
- Proposal: defer. A measured recovery objective only matters for an operated service.
- Chenyu (2026-09-17): agree: defer.
- Nasi (2026-09-16): agree: defer.
- Decision: agreed (2026-09-17). Plan to be updated.

### B6. Infrastructure-as-code production profile, two API replicas
- Plan: D10, "two copies of the API, three workers, the database, file storage and the model service, defined in files rather than clicked together, with an automatic check that nothing is publicly exposed".
- Proposal: keep one compose file that runs the whole stack on one machine (this is also the demo setup, see G1). Defer the multi-replica profile and the policy check.
- Chenyu (2026-09-17): agree: one compose file; it is also the demo setup.
- Nasi (2026-09-16): agree: one compose file for the whole stack; defer the multi-replica profile.
- Decision: agreed (2026-09-17). Plan to be updated.

### B7. Dashboards, alerts, runbook
- Plan: D10, dashboards and alerts for stuck checks, model errors, cost, screen speed and backup age; a runbook for the client's IT staff.
- Proposal: defer dashboards and alerts. Keep a short "how to run it" section in the README instead of a runbook.
- Chenyu (2026-09-17): agree: defer; a "how to run it" section in the README.
- Nasi (2026-09-16): agree: defer dashboards and alerts; a "how to run it" section in the README.
- Decision: agreed (2026-09-17). Plan to be updated.

### B8. Daily and weekly ceremonies
- Plan: 09:30 written check-in, 09:40 call, review windows at 13:00 and 16:30, 17:30 KR update, 17:45 evening note, Monday kickoff, Wednesday knowledge swap, Friday demo and retro, a KR tracker with one issue per task.
- Proposal: replace all of it with three rules. Every change is a pull request reviewed by the other person. Shared shapes live in `app/rulesets/schema.py`, `docs/api_contract.md` and the migrations, and change only in their own PR with both approvals. Each person works independently up to the next stop point in section D and stops there.
- Chenyu (2026-09-15): agreed. We do our own jobs and stop before the work that needs both of us to check.
- Nasi (2026-09-16): agree: the three rules replace the ceremonies.
- Decision: agreed (2026-09-16). Plan to be updated.

### B9. Cheap security items, kept and done last
- Plan: spread over D9.
- Proposal: keep only the items interviewers ask about and do them after S4 if time remains: per-user login with a role, signed image URLs instead of the key in the link, `/health` without model names, explicit CORS origins, secret scanning in CI, upload size cap and file-type check.
- Chenyu (2026-09-17): agree: these six items only, after S4 if time remains.
- Nasi (2026-09-16): agree: only these items, after S4 if time remains.
- Decision: agreed (2026-09-17). Plan to be updated.

## C. What stays from the plan

### C1. Unchanged
- Plan and proposal are the same: the split (Chenyu: pipeline, LLM layers L1 to L4 and V0 to V5, worker, gateway, pricing, reports; Nasi: parser and locator L0, rule engine and templates V6, the React three-column UI for L5 and V7); contracts before code; item (l) through every layer before widening; each LLM layer with fixed input, fixed output shape, code checks and a FakeLLM call-count test; human editing as versioned, attributed records with reasons and engine-only re-evaluation; the orchestrator comparison with its decision record; the "Kept, ported, removed" table apart from A7.
- Progress (2026-09-17, Nasi): S1 is closed (E5, PR #29) and API contract questions 1, 3 and 4 are settled. Chenyu's worker is on `main` (PR #24, migration 001). PRs #25 to #28 (gateway, item (l) check, S2 routes with `openapi.json`, compose with Postgres and the worker) were merged into their stacked base branches, not into `main`; all four commits sit on `feat/item-l` and reach `main` with one pull request from that branch. Nasi's S2 work, on branches not yet pushed: parser fixes (`port/parser`), `app/rulesets/locate.py` finding every schedule item with the right Part and page on all three tenders (15/15, 13/13, 21/21; `feat/locate`), and the React UI in `web/` on an MSW mock of the S2 contract with `StageResultsWindow` and `DocumentViewer` (`feat/web-mock`). Contract gaps found on the way are in I1.
- Chenyu (2026-09-15): agreed.
- Nasi (2026-09-16): agreed.
- Decision: agreed (2026-09-16). Plan to be updated.

## D. Working mode: independent tracks and stop points

### D1. Six stop points
- Proposal: work independently up to each stop point; at the stop point both check together in one call, then continue. Nothing below a stop point depends on the other person's unfinished work: the UI runs on `web/mock/`, the rule builder runs on fixture nodes, every LLM layer runs on the FakeLLM.

| Stop point | Both check together | Chenyu does before it (alone) | Nasi does before it (alone) |
|---|---|---|---|
| S0 Contracts | `schema.py` (Citation, 12 CheckTypes, SlotSpec, SlotValue, TemplateRule, RuleSet), `api_contract.md`, migration 001, compose file. Half a day. | FakeLLM (`test/fakes.py`), the failure-scenario harness (`test/jobs`), the synthetic tender-style case via `tools/make_synthetic_tender.py` (235-page combined tender, four bids with scanned pages) | Record the port source commit (F5), rotate the RDS password and IAM key, map the 44 check names to 12 kinds, ground truth for Tender 2 and Tender 3 (private folder, never in git) |
| S1 Orchestrator | Read both sets of harness numbers, write `docs/decisions/0001-orchestrator.md`, pick one. | Both spikes (LangGraph + Postgres checkpointer; Procrastinate job queue), both run through the same harness | Port `validator/engine` unchanged, split the 13 rule files into templates + `params/Tender 1.json`, golden test proving verdicts are identical |
| S2 One item end to end | Replace the UI stub with real routes; item (l) on the synthetic tender shows in the Stage I window with its page highlighted. | Worker on the winner, V0 without page cap, V1 triage, V2 resolve, V3 extract for item (l), results API, LLM gateway (fallback, cache, budget, allowlist by `data_class`) | Port the parser, split combined PDFs, clause tree, `locate.py` finding 15 items with Parts on all 3 tenders, `StageResultsWindow` and `DocumentViewer` on the mock |
| S3 Rule sets on 3 tenders | Run the rule-set evals together and record the numbers. | L1 match, L2 slots with quote verification, L3 novel rules (ported `extract_leaf_requirements`), L4 coverage, rulesets backend (edit, versions, diff, confirm) | Parser recall at or above 95% against the ground truth, `RulesWindow` with full editing, Vitest and API-contract snapshot |
| S4 Vendor checks, all items | Run the Tender 1 redacted bid and compare with the historical Summary List and Price Summary. | V3 for every document type using Nasi's checker prompts, V4 negative verification, field corrections and the engine-only re-evaluate job, V5 agent with the injection test, pricing and Word reports from the confirmed rubric | Stage I / II screens for all items with corrections, Scoring and Report windows, engine switched to each tender's confirmed rubric, Playwright review flow |
| S5 Portfolio finish | README, demos, eval report, decision records, public release (section H). | Remove the losing orchestrator and the API threads; GCP demo | Remove Streamlit; final UI polish; screenshots and the demo recording; AWS demo |

- Chenyu (2026-09-15): agreed.
- Nasi (2026-09-16): agreed; already working this way (engine port PR #19 before S1).
- Decision: agreed (2026-09-16). Plan to be updated.

### D2. Pacing
- Proposal: S0 to S3 in the first ten working days, S4 as the stretch, S5 the week after. If S4 slips, the project is complete and demonstrable at S3, which is why S3 comes before S4. Start date and holidays are for us to pick; nothing in the plan depends on 21 September.
- Chenyu (2026-09-17): agree. The ten days count from S0; S3 is the point at which the project is complete and demonstrable.
- Nasi (2026-09-16): agree: S0 to S3 in ten days, S4 stretch, S5 after.
- Decision: agreed (2026-09-17). Plan to be updated.

## E. Orchestrator comparison

As written, the day-2 comparison decides itself. These four changes make it a fair experiment, and its decision record becomes the best interview artefact in the project.

### E1. LLM cache before the decision
- Plan: gates 1 and 2 require "0 repeated LLM calls" after SIGKILL or SIGTERM; the LLM cache is built on D3, after the decision.
- Proposal: a killed LangGraph node re-runs from its start, so LangGraph can only pass those gates through the cache. Build a cache stub inside the spike (a dict keyed by model, prompt version and input hash) or measure "repeated paid calls, cache allowed" for both variants.
- Chenyu (2026-09-17): agree. Outcome: the harness counts repeated LLM calls directly through the FakeLLM's cross-process log, so no cache was needed to measure the gates; both variants scored 0 repeated calls after SIGKILL and SIGTERM because both resume from saved steps. The gateway cache is still built at S2.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

### E2. Procrastinate as the run queue in both variants
- Plan: the LangGraph variant hand-writes "claiming, retries, dead jobs, shared rate limit"; the queue variant gets them from Procrastinate.
- Proposal: use Procrastinate as the run queue in both variants. Then the only difference measured is per-node checkpoints plus `interrupt()` versus a hand-written `job_steps` table plus status-column pauses.
- Chenyu (2026-09-17): agree; done: both spikes run on Procrastinate (PRs #8 and #9).
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

### E3. Neutral framing
- Plan: "the queue is what this plan recommends"; the repo layout removes `langgraph*`; the data model lists "Procrastinate tables"; the production diagram says "procrastinate worker"; the scalability row says "LangGraph and threads removed".
- Proposal: keep the queue as the default and say so once. Keep the one-paragraph LangGraph layout already present in the "Alternative" section so the losing variant is not pre-deleted from the document.
- Chenyu (2026-09-17): agree; the decision record names the queue as the proposed default and keeps the LangGraph variant runnable under `spikes/langgraph` until the decision is final.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

### E4. One full day, decision the next morning
- Plan: build both variants in the morning of D2, run twelve scenarios in the afternoon, decide by 17:00.
- Proposal: the harness (kill, SIGTERM, two workers and two API copies, 429 then permanent failure, pause-edit-resume, re-check after a new version, field correction, plus the three "should" scenarios) is one to two days of work and is reused later as CP2 KR3 and CP4 KR6. Build it before S0, give the comparison a full day, and write the decision at S1 the next morning.
- Chenyu (2026-09-17): agree; done: harness before S0 (PR #6), a full day of measurements, record written (`docs/decisions/0001-orchestrator.md`). See E5.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

### E5. Orchestrator decision record (S1)
- Proposal: `docs/decisions/0001-orchestrator.md` (PR #9) proposes the Postgres job queue on the plan's own decision rule: both variants pass every must-pass gate with identical numbers, and the queue variant has fewer moving parts (115 against 162 variant-specific lines, one table against four). The LangGraph variant stays runnable under `spikes/langgraph` until the record is accepted.
- Chenyu (2026-09-17): accept the queue variant as the pipeline runner; the V5 agent loop may still be a graph inside a job.
- Nasi (2026-09-17): accept the queue variant as the pipeline runner, on the numbers in the record; LangGraph only inside a job for the V5 agent, if it reads better there.
- Decision: decided (2026-09-17). S1 closed; record 0001 accepted.

## F. Repository, data and confidentiality

### F1. Repository
- Decision (Chenyu, 2026-09-15): stay in the current private repo `chenyufang-data/tender-evaluation-assistant` until the project is publishable, then transfer it to an organisation and make it public. A transfer does not carry collaborators, so Nasi is added to the organisation at that point. Status: decided.
- Nasi (2026-09-16): acknowledged.

### F2. Data classes and endpoints
- Proposal: every fixture and every project carries a `data_class` (`synthetic`, `redacted_sample`, `confidential`). The gateway allowlist keys on it. Each live eval names the endpoint it ran against in its stored result.
- Chenyu (2026-09-17): agree; `DataClass` is in `schema.py` and every fixture under `test/data` is synthetic.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

### F3. Files excluded from the port
- Proposal: the port from commit `7e8e273` (F5) excludes `retrieval_eval/production_parser_nodes_full.json`, `ground_truth_full.md`, `archive/reports/tender_compliance_*`, and the vendor values in `tests/evals/*`. The port PR checklist lists them. Ground truth for all three tenders lives in the private data folder.
- Chenyu (2026-09-17): agree; PR #19 carried the checklist, and I diffed every ported file against `7e8e273`: imports only.
- Nasi (2026-09-16): agree: exclude these files; the port PR checklist lists them.
- Decision: agreed (2026-09-17). Plan to be updated.

### F4. Public-release audit at S5
- Proposal: before the transfer and the switch to public, run gitleaks over the full history and search the history for the three tender numbers and the vendor names. The joint repo's history is Chenyu's old repo, which committed only code, tests and the synthetic demo case; the risk is what the port brings in.
- Chenyu (2026-09-17): agree; add `docs/` (the check-kind mapping quotes a few tender values) and `infra/README.md` (Identity Center start URL, company account name) to the audit scope.
- Nasi (2026-09-16): agree.
- Chenyu (2026-09-18): two more items for the S5 list, from decision 0002: a LICENSE file (AGPL-3.0, or MIT for our code plus a README note that the program combined with `app/parsing/` is under AGPL terms), and the README licence notice the record promises. Nothing changes for the private demo or a non-commercial public one.
- Decision: agreed (2026-09-17). Plan to be updated.

### F5. Port source
- Plan: "Commit the 50 uncommitted files, tag them" as `aicamp-final`; every port copies from that tag.
- Proposal: port from what is already pushed to `nlp4725/Bidding-AI-expert` and do not push the local uncommitted work. The fixed source is branch `redesign/stage1-panel` at commit `7e8e273dfd24c8fefeffc43a2014e0ddbc267d30` (2026-08-10); every port PR names this commit (`git show 7e8e273:<path>`) instead of the tag. The 52 uncommitted local files are mostly the AI_camp job runtime (`service/worker.py`, `queue_client.py`, `rate_limiter.py`, `task_store.py`, `storage.py`, `s3_docs.py`, `aws_config.py`, `infra/`), which the worker and gateway replace, plus 21 test files. `validator/engine/` has no local changes. The few local changes in ported areas (`ingest/layout_document_index.py`, `validator/checkers/information_schedule_checker.py`, `extract/fields.py`, `extract/llm_client.py`, `extract/vision_client.py`, `frontend/src/api.js`, `frontend/src/components/VendorCompletenessList.jsx`) are kept in a local patch (saved 2026-09-16, with the untracked files, outside git) and brought over by hand in the matching port PR only if needed. Key rotation (RDS password, IAM key) is unaffected and still happens before S0.
- Chenyu (2026-09-17): acknowledged: port from `7e8e273`, no tag. One request: keep the local patch in a private branch of your own repo as well, not only on the laptop.
- Nasi (2026-09-16): port from the pushed commit; no push of the local work and no `aicamp-final` tag.
- Decision: agreed (2026-09-17).

### F6. Public naming
- Found by: getting the project's public face ready (CV text, README, repository description) on 2026-09-25.
- Proposal: everything public presents the project as an **AI tender evaluation assistant**, with no tender reference numbers and no Hong Kong public wording ("Hong Kong", "Hong Kong", "Authority" or "the Authority"). Private working material, such as this checklist and the eval docs while the repository is private, may keep them where accuracy needs them.
  1. **The repository description, now.** It reads "…Stage I and Stage II review of Hong Kong public tenders…". Proposed: "AI tender evaluation assistant: builds a page-cited rule set from the tender documents, checks every bid against it with verified evidence, ranks prices deterministically and exports editable Word reports. Joint project by Chenyu Fang and Nasi." The description is a repository setting, not a file, so this PR can only propose it; once agreed, either of us sets it (`gh repo edit --description`).
  2. **New documents, from now on,** call the real tenders Tender 1, 2 and 3, in the order of the README's results table. The table matching each name to its reference number stays outside git, next to the answer keys, and each of us keeps a copy.
  3. **One clean-up PR at S5,** as counted on `main` on 2026-09-25:
     - tender numbers become the three names: 144 mentions in 18 files, mostly `docs/evals/parser_l0.md` and comments in `app/parsing/`;
     - Hong Kong and Authority wording becomes neutral: about 37 mentions in 17 files;
     - `sample` in file names becomes `sample`: `test/data/synthetic_tender*`, `tools/make_synthetic_tender.py`, `tools/make_synthetic_tender_ruleset.py`, `test/test_synthetic_tender.py`;
     - `HK$` stays for now. It is the currency of the synthetic bids and of the pricing code (90 mentions in 30 files), and removing it means regenerating the synthetic data and its goldens. Revisit at release.
  4. **History, at release.** Earlier commits and commit messages carry the same names. The public repository is a copy whose history is rewritten with `git filter-repo`: the names are replaced, and both authors' commits are kept. This private repository stays as it is, so nobody force-pushes and no clone breaks. The F4 audit adds a search of the rewritten history for the three numbers and the Hong Kong wording.
- Chenyu (2026-09-25): proposed. Chenyu's old personal repository, `tender-evaluation-assistant`, gets a new name before it is ever made public.
- Nasi (2026-09-26): agree to 1–4, including the proposed repository description, which is set once this merges.
- Decision: agreed (2026-09-26).

## G. Deployment and demo

### G1. Two independent demos, same image
- Proposal: Chenyu deploys on GCP Cloud Run under the cyfang domain; Nasi deploys on AWS under her own domain. Each deployment has its own Postgres and object store and holds synthetic data only. CI builds one image per tag and pushes it to a registry both pull from, so the two demos are the same build.
- Chenyu (2026-09-15): proposed.
- Nasi (2026-09-16): AWS side confirmed: the `tender-review-dev` account in `us-east-1`, Terraform in `infra/` (PR #21), synthetic data only. Domain not chosen yet.
- Decision: agreed (2026-09-17); Nasi's domain to be added when chosen.

### G2. Configuration only
- Proposal: nothing in the code names a cloud. Database URL, storage endpoint, LLM endpoint and public base URL come from environment variables. `deploy/cloudrun/` stays for GCP; Nasi adds the AWS equivalent (one EC2 host with the compose file and Caddy for TLS is the simplest).
- Chenyu (2026-09-17): agree.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

### G3. Abuse limits before a public demo
- Proposal: a public demo needs, before it goes live, a demo login or a read-only mode with pre-computed synthetic results, the gateway's per-day LLM budget, and an upload size cap. Otherwise anyone can upload PDFs and spend our model credits.
- Chenyu (2026-09-17): agree; the LLM budget and the upload cap are gateway work at S2, the demo login is under B9.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

## H. Portfolio finish

### H1. Checklist for S5
- Proposal: the end state is a public repo containing only code, tests and synthetic data, with results on the redacted cases reported as numbers.
  1. README a recruiter reads in two minutes: one architecture diagram, a 30-second GIF of the three-column review, a results table (parser recall on 3 tenders, rule-set eval, agreement with the historical Stage I / II decisions and price ranking on Tender 1), the test count and CI badge.
  2. A "who built what" section naming both of us with our areas, an Authors section and a `CITATION.cff` with both names.
  3. `docs/decisions/0001-orchestrator.md` with the harness numbers for both variants, written so it can be linked on its own.
  4. Two live demos (G1) or a two-minute video if a demo has to stay private.
  5. One-command setup: `docker compose up` brings up Postgres, the API, a worker and the UI on the synthetic case.
  6. Descriptive test names for the tests that tell a story: call-count tests, the prompt-injection test, the golden engine test, the resume-after-kill test.
- Chenyu (2026-09-17): agree.
- Nasi (2026-09-16): agree.
- Decision: agreed (2026-09-17). Plan to be updated.

## I. Contract gaps found at S2

### I1. Gaps in `schema.py` and the S2 API contract
- Found by: building `locate.py` against `schema.py`, and the React UI against PR #27's `openapi.json` through the mock. Each change goes in a `contract` PR with both approvals.
- Proposal, needed for the S2 check (item (l) with its page highlighted):
  1. `PageCitation` has no box or quote, and the served `image_url` has no `highlight`, so nothing on the page can be highlighted. Add an optional `box` (and the quote) to `PageCitation`; if `?highlight=` stays, include it in the signature.
  2. A rule-set `Citation` names a file by project path (`tender/09 Schedules.pdf`) while `Document` has `doc_id` and the bare file name. Add `doc_id` to `Citation` (or the path to `Document`).
- Proposal, `schema.py` (from `locate.py`):
  3. `RuleSet` has nowhere to store a Part's intro and its clauses (the paragraph that makes a missing Part A item disqualify). Add `parts: [{part, title, citation, clauses}]`.
  4. No `ItemStatus` for "located, no rules yet"; `locate` uses `needs_input` for now. Add `located`, or agree that `needs_input` covers it.
  5. `Citation` cannot say that one citation resolved to more than one node. Allow a list, or an `ambiguous` flag.
- Proposal, `openapi.json` and `api_contract.md` agree with each other:
  6. `GET /ruleset`, `GET /projects` and `GET /projects/{pid}` are untyped in `openapi.json` (so `RuleSet` is not in the spec); type them.
  7. `GET /jobs` and events are paged (`{items, next_cursor}`) in `openapi.json` but plain lists in the doc; `Job.state` includes `paused`, missing from the doc; `Job.progress` is untyped. Update the doc and type `progress`.
  8. `Correction` is the stored record in `openapi.json` and the request body in the doc; name them apart (`Correction`, `CorrectionRequest`).
  9. 422 responses are FastAPI's default body, not the error envelope. `image_url` is relative to the API base; say so in the doc.
  10. A verdict's checks link to field values only by the last part of `field_id`; give each check its `field` key.
- Proposal, rule-set editing routes (found building the Rules window on the mock, PR #36):
  11. `openapi.json` is missing GET diff, GET gaps and POST/PATCH/DELETE items, and the `ItemPatch`, `NewItem` and `Diff` schemas; GET ruleset, PUT draft and POST confirm return an untyped dict instead of `RuleSet`.
  12. No route sets a gap reason (only a whole-draft PUT), and `Gap` has no edit record, so the reason is unattributed. Add `PATCH /ruleset/gaps/{id}` with `reason`, recorded as an `Edit`.
  13. `ItemPatch.note` is a string but `ItemNote` needs a `kind`; there is no way to edit or remove a note.
  14. Only `SlotValue` keeps `model_value`; a rule or template edit keeps its original only in the parent version. `Diff.changed[].edit` must allow `null` for changes made by the rule builder.
  15. PATCH sets `edited`, which does not block confirm, so an edit can clear `needs_input` while a required slot is still empty. Confirm should check the template's required slots, not the status alone.
  16. The status of an item a person adds is unstated (`edited` or `novel`).
  17. `RuleSetVersion` timestamps are float seconds while `RuleSet` uses ISO datetimes; the draft's last editor is not exposed, so the UI cannot warn before a `self_approval` 403.
- Items 1 and 2 are proposed in PR #35.
- Chenyu (2026-09-18): 1 and 2 agreed and merged in #35. 3: agreed, RuleSet.parts: [{part, title, citation, clauses}] in the S3 contract PR. 4: needs_input covers "located, no rules yet"; no new status. 5: keep one node_id and add optional candidates: [node_id] when the resolver returns several; the person picks. 6 to 9: agreed, my routes; the S3 contract PR types the three GETs, pages the doc, names CorrectionRequest, and puts the error envelope on 422 in openapi (the server already returns it). 10: agreed, CheckedField.field (the engine bridge already emits it). 11: agreed, typed when the S3 routes are built. 12: agreed, PATCH /ruleset/gaps/{id} with reason, stored as an Edit. 13: ItemPatch.note becomes an ItemNote; notes addressed by index for edit and delete. 14: Diff.changed[].edit: Edit | null; model_value stays on slots only, the parent version is the model's original for rules and templates. 15: confirm validates each template's required slots and answers 409 naming the items (S3, with the editing routes; nothing enforces it yet). 16: a person-added item is edited with its edit record; novel stays for L3 drafts. 17: RuleSetVersion timestamps become ISO datetimes and RuleSet exposes updated_by.
- Nasi (2026-09-18): proposed; 1 and 2 before the S2 check, the rest at S3.
- Decision: decided (2026-09-20): positions approved by Nasi in the review of PR #40. 1 and 2 in #35; 3 to 10, 14, 16 and 17 in #41 and #44; 11 to 13 and 15 with the S3 rule-set editing routes (Chenyu).

### J1. Parser follow-ups after the S3 recall gate
- Found by: scoring all three tenders against the deep keys on 2026-09-21, with the
  benchmark pinned in `tools/benchmark.py` (`09f277c`). All three clear the S3 gate
  of 95% recall: 95.6 / 97.8 / 95.2, exact location 92.3 / 95.2 / 91.8.
- Open, in the order proposed:
  1. A `Table A` heading records `part = "Part A"`, and the Chinese Tender Form's
     `第 4 部分` records `"Part 4"`: the scope is named for the word "Part" whatever
     the document prints. 11 of Tender 3's 64 references fail exact location on
     this, so the reference-level metric reads 75.0% against 91.8% at node level. It
     is also what a citation would show a reviewer, so the label is wrong in the UI,
     not only in the score.
  2. Tender 3 clears the S3 recall gate by 4 nodes (1506/1582). Worth widening
     before the number is quoted anywhere.
  3. Five sub-document nodes (POGS, NCTC, Compliance Schedule, two annexes) carry no
     bbox, and `exact_location_correct` requires one. Either the parser gives a
     container a bbox, or the metric stops asking a container for one - a decision to
     make deliberately, since it changes what the benchmark means.
  4. `hierarchy_correctness` on POGS is 0/21 on Tender 1: every node found, every
     parent wrong. Not a gate (it is a diagnostic, see `tools/benchmark.py`), but a
     whole document's parenting being wrong is one containment bug, and it breaks
     "everything under this schedule" queries.
- Nasi (2026-09-21): proposed. 1 first - bounded, measurable, and user-visible.

### J2. Where a form's own notes and trigger live (blocks the rule-file split)
- Found by: starting the S1 split of the 13 rule files (`tools/split_rule_files.py`).
  The classifier reproduces `check_kind_mapping.md`'s own totals independently: 126
  rules, 99 checks, 27 not a rule, 0 unmapped.
- The problem: S0 gap 6 put `notes` and `condition` on `RuleSetItem`, and both are
  implemented there. But the split produces **templates**, not items - items are built
  per tender by L1. So the 27 non-rules have nowhere to go. They are facts about the
  FORM, not the tender: when a form is needed at all (only if the tenderer does not
  make the goods itself), that the tender's supplementary terms may ask for
  certification, and that extra sheets may be attached when the space is too small.
  Left on the item only, every tender has to rediscover them,
  which is what a template library exists to prevent.
- Options:
  1. `Template.notes: list[ItemNote]` and `Template.condition: str | None`, inherited
     when L1 matches an item to the template; the item may override `condition` and
     never loses the form's notes. Prototyped on `feat/production-templates`.
  2. Keep them item-only: the split drops all 27, and each tender's build re-derives
     them through the model. Cheapest now, but the library carries less than the rule
     files it replaced, and a trigger the model misses silently changes an item's
     applicability.
  3. Put them in the per-tender params file. Wrong shape: they do not vary by tender,
     which is the test for what belongs in params.
- Not decided here: `schema.py` is the shared contract, so this is a `contract` PR
  with both approvals (the I1 convention).
- Nasi (2026-09-22): proposes 1. `na_allowed` needs nothing - the engine already reads
  "N/A" as `not_applicable` (`app/engine/state.py`). `overflow_allowed` becomes a note
  under whichever option wins.
- Chenyu (2026-09-23): decided, option 1. Before the 13 templates are written: (a) each
  template's id is our form id (`app/checks/forms.py`); only 4 of the 13 rule-file names
  are one today. (b) Every rule's `field` is a `<form>.<field>` key, through a field map
  in `split_rule_files.py` that reports a field with no home rather than guessing;
  Chenyu adds the fields a rule checks to `forms.py` in a `contract` PR (mostly the
  Information Schedule, 30 names in the rules against 4 fields, and the Particulars of
  Goods, 14 against 7). (c) The templates are written in our own words, never the rule
  files' text. (d) `params/<tender>.json` stays outside git, beside the answer keys.

### J3. The Scoring and Report windows (S4)
- The last two stages of the pipeline stepper, stubbed `built: false` since it was
  written. Both read S4 routes already finished on the API side; neither recomputes
  anything. Done: `web/src/windows/ScoringWindow.jsx`, `ReportWindow.jsx`, their
  mock routes and fixtures, and 10 tests.
- A report is fetched with the X-API-Key header and saved from the Blob, not linked:
  the reports route requires the key and a plain `<a href>` cannot send it (review
  of #60, Chenyu). The evaluation names who is unconfirmed (`reviewed_by` is null), so
  the buttons wait and say why before a click; a 409 `review_pending` from a stale
  evaluation is shown with the tenderers it names.
- Left for the rest of S4: Stage I/II corrections across all items, the engine
  switched to each tender's confirmed rubric, and the wider Playwright review flow
  (one spec today, `e2e/item-l.spec.js`).

### J4. Corrections and review confirmation in the Stage windows (S4)
- The review half of S4 on the UI side: a reviewer corrects a field (value, a document
  marked present or absent, or a page) with a required reason, and confirms the review
  once nothing needs one. Both routes were already finished on the API side.
- The model's value is kept beside the person's and shown with who changed it and why,
  which is what `FieldValue.model_value` and `Correction` are for: a reviewer looking
  at a corrected field can see what it used to say.
- A correction and a confirmation each answer with the whole re-decided `BidResult`,
  so the window takes the answer as its new state rather than reloading - there is
  then no window in which it shows a verdict computed from a value the server has
  since changed.
- Confirming answers 409 `conflict` with `details.fields`; the window names them
  rather than saying it failed.
- Left for S4: the engine switched to each tender's confirmed rubric, and the wider
  Playwright review flow (one spec today, `e2e/item-l.spec.js`).

### J5. The Playwright review flow (S4)
- `e2e/item-l.spec.js` had been a stub since S2, with a comment saying Playwright was
  left uninstalled "to keep `npm ci` light". Its four selectors were all still valid,
  so it had not rotted - it had simply never run, which is a test that proves nothing.
- Playwright is now a dev dependency with a config, and `e2e/review-flow.spec.js`
  walks the whole S4 sequence in a real browser on the MSW mock: run a check on a
  tenderer that has none, find the field the model could not read, be refused a
  confirmation and told which field, correct it with a reason, watch the verdict
  change while the model's value stays visible, confirm, then Scoring and Report.
- It runs as its OWN CI job, not inside `web`: it needs a dev server and a browser
  download, which would slow the fast feedback loop on every PR. A failure uploads
  the trace and screenshots.
- The first real run caught one thing the unit tests could not: the spec asserted the
  wire value `needs_review`, but the badge renders "Needs human review". A Vitest
  test on the component would have used the same rendered text; only a browser walking
  the flow compares what a reviewer actually sees.
- 4 specs pass. Depends on J3 and J4, both merged into this branch so the flow is
  runnable rather than aspirational.

### J6. Re-evaluating against a confirmed rule-set version (S4)
- The plan's S4 row asks for "the engine switched to each tender's confirmed rubric".
  `rubric` is the legacy word - deprecated since S2, removed at S5 - and the live
  equivalent is a confirmed `RuleSet` version. `POST /projects/{pid}/evaluate` has
  been finished on the API side since #53, and `JobProgress` already knew the
  `evaluate` job kind, but nothing in the UI ever started one.
- Now offered in the Rules window, on a CONFIRMED version only: a draft has not been
  agreed, which is what the confirm step is for.
- Offered rather than run automatically on confirm, because a result whose verdict
  changes loses its review confirmation. A reviewer is told that before it happens
  rather than discovering it afterwards, and chooses the moment.

### J8. The S5 README (H1 items 1 and 2)
- Added, not restructured: a **Results** section a reader reaches in the first screen
  (parser on three tenders, the rule set's L0 layer, the test counts), a **Who built
  what** section naming both of us with our areas, an **Authors** section, and
  `CITATION.cff`.
- One thing this turned up: the repository has **no LICENSE file**, and the choice is
  constrained rather than free. `pymupdf` is AGPL-3.0 and `pymupdf-layout` is PolyForm
  Noncommercial (decision 0002), so commercial reuse needs Artifex licences or a
  replacement for `app/parsing/`. Decision 0002 said the README would say so before the
  repository is made public (F4); it now does. A first draft of `CITATION.cff` claimed
  Apache-2.0, which would have been inventing a licence the project has not chosen.
- Still open in H1: the architecture diagram, the 30-second GIF of the three-column
  review (the Playwright review flow already walks exactly that sequence, so it can
  record it), the two live demos (G1), and settling the licence itself.

### J10. The MCP server at S5: retire it with the legacy stack
- Found by: planning what the S5 legacy removal takes with it (2026-09-25).
- The plan's "Kept, ported, removed" table (kept by C1) marks `mcp_server/` as *keep*, and D9 guards it by data class. Nobody scheduled the port, so it still runs on the prototype: `app/tools.BidTools` (otherwise used only by the legacy `app/agent.py`), the legacy rubric, and the `synthetic` flag. Nothing in the new stack calls it. Removing the legacy agent and the rubric at S5 breaks it.
- Proposal: **retire it at S5**, in the legacy-removal PR:
  1. Remove `mcp_server/`, `test/test_mcp.py` and `docs/mcp_traces/`.
  2. Keep what was measured: the two-driver experiment (2026-09-08, synthetic) and the confidentiality guard's design go into `docs/archive/mcp_2026-09.md`, dated and marked as describing the prototype.
  3. C1's table entry changes from *keep* to *removed*, and the MCP part of D9 lapses.
- Why not port it (about 3.5 days of work):
  - On real bids, only a local client may connect, because the bids are confidential and the common MCP clients are cloud-driven. That makes it a second copy of the checker's own search agent.
  - A chat client answering free-form questions sits outside the attributed review record, which is what the product is built around.
  - It adds a third surface to keep in step with the contract, next to the UI and the REST API.
  - The S4 real-bid result, the README and the demos matter more for the portfolio.
- If S4 and S5 finish with time left, Chenyu has a port plan: read-only, stateless tools over the rule set, results and pages, with the gateway's data-class rule applied per client.
- Chenyu (2026-09-26): proposed.
- Nasi:
- Decision:

## Verified facts (no action needed)

Checked on 2026-09-15. In `tender-evaluation-assistant`: jobs run as daemon threads in `backend/api.py`; the Cloud Run deploy pins `--max-instances 1`; LangGraph SQLite checkpoints are copied to a scratch directory; routes `/run`, `/resume`, `/graph`, `/evaluate`, `/evaluation` and `/reports/{name}` exist; `/health` returns model names; the image link carries the key; `max_ocr_pages=8`; `max_total_chars=45000`; Python 3.12 in CI and both Dockerfiles; tests live in `test/`; `python run_demo.py offline-demo` is the right command. In `Bidding-AI-expert`: `validator/engine/core.py` exists; `extract_leaf_requirements` is in `rules/requirement_extraction.py`; branch `redesign/stage1-panel` is merged via PR #1; letters (l) Non-collusive Certificate, (i) Manufacturer's Letter of Intent and (b)/(c) Price Schedule Part A match the orchestrator's registry; 44 check names and 13 rule files; evals cover Tender 1 only. Tender 3 is one 366-page PDF. Procrastinate 3.9.0 has worker heartbeats and stalled-job retry; `langgraph-checkpoint-postgres` 3.1.2 is MIT; LangGraph Server is Elastic License 2.0 and self-hosting needs an Enterprise plan, so excluding it is right.

## Sources

- Procrastinate stalled-job retry: https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
- MinIO maintenance mode and archive: https://github.com/minio/minio/issues/21714
- LangGraph Server licensing: https://docs.langchain.com/langsmith/deploy-standalone-server
- GitHub branch protection availability: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
