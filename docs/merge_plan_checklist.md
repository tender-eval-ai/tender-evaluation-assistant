# Merge Plan Checklist

Joint review of the "Tender Review Merge Plan" (10-day version, 2026-09-15). This file is the place where both of us record a position on each open item and where the decision is written once it is made. It is updated by pull request; either of us may edit any item.

**How to use.** Every item has five lines. *Plan* quotes what the plan currently says. *Proposal* is the change suggested by Chenyu's review. *Chenyu* and *Nasi* hold each person's position, written in their own words and dated. *Decision* is filled in when both agree, together with the status. An empty position means "not yet stated", not agreement.

**Status values.** `open` (a position is missing), `agreed` (both agree, plan to be updated), `decided` (already settled outside this file), `deferred` (out of the ten days, kept on a later list), `dropped`.

**Context both of us share.** Two bootcamp students, both in the US, no client and no pilot. Each person works on their own area independently and stops at the joint stop points in section D. The goal is the strongest possible joint project for job applications.

Last updated: 2026-09-16 (Nasi).

## Status board

| ID | Item | Status | Waiting on |
|---|---|---|---|
| A2 | Branch protection on a private repo | decided | — |
| A3 | MinIO as file storage | decided | — |
| A4 | "Redis queue" in AI_camp | open | Nasi to confirm |
| A5 | Capacity estimate (calls per minute) | open | both |
| A6 | Real documents from day 4; live evals | open | both |
| A7 | Eval sets ported as they are | open | Nasi |
| B1 | Client pilot (and hosting region, pilot slot) | open | Nasi |
| B2 | SSO / OIDC identity provider | open | both |
| B3 | Retention period with logged deletion | open | both |
| B4 | Upload quarantine with malware scan | open | both |
| B5 | Restore and rollback drills with RPO / RTO | open | both |
| B6 | Infrastructure-as-code profile, two API replicas | open | both |
| B7 | Dashboards, alerts, runbook | open | both |
| B8 | Daily and weekly ceremonies | open | Nasi |
| B9 | Cheap security items kept, done last | open | both |
| C1 | What stays from the plan unchanged | open | Nasi to confirm |
| D1 | Independent tracks and six stop points | open | Nasi |
| D2 | Pacing: S0 to S3 in ten days, S4 stretch, S5 after | open | both |
| E1 | LLM cache before the orchestrator decision | open | both |
| E2 | Procrastinate as the run queue in both variants | open | both |
| E3 | Neutral framing of the two variants in the plan | open | Nasi |
| E4 | One full day for the comparison, decision next morning | open | both |
| F1 | Repo stays private until publishable, then org and public | decided | — |
| F2 | Data classes and endpoints named per fixture and eval | open | both |
| F3 | Files excluded from the port (commit `7e8e273`, see F5) | open | Nasi |
| F4 | Public-release audit at S5 | open | both |
| F5 | Port source: pushed commit, no `aicamp-final` tag | open | Chenyu to acknowledge |
| G1 | Two independent demos, same image | open | Nasi: domain; Chenyu to agree |
| G2 | No cloud named in code; configuration only | open | both |
| G3 | Abuse limits before a public demo | open | both |
| H1 | Portfolio finish checklist | open | both |

## A. Corrections to the plan

These are facts, checked against both repositories on 2026-09-15. They need a confirmation, not a debate. (The base repo name and the day-1 git commands were settled on 2026-09-15 and are no longer listed: the joint repo is `chenyufang-data/tender-evaluation-assistant`, the tag `v0-hk-baseline` is pushed, and both of us have push access.)

### A2. Branch protection on a private repo
- Plan: "Settings → Branches → protect main: PR, 1 approval, tests check, no force push".
- Proposal: not available on a private repository on GitHub Free. Until the repo is public: a pre-push hook that refuses pushes to `main`, CODEOWNERS (auto-requests the reviewer for free), and a CI job that fails on a commit to `main` that did not arrive through a merged pull request.
- Chenyu (2026-09-15): stay in the current private repo until publishable, then transfer to an organisation and make it public, where protection is free. Use the convention until then.
- Nasi:
- Decision: decided (Chenyu, 2026-09-15); Nasi to acknowledge.

### A3. MinIO as file storage
- Plan: "Postgres for all records and MinIO for files, started with one command".
- Proposal: MinIO's open-source repository entered maintenance mode in December 2025 and was archived on 25 April 2026; no official binaries and no security fixes. Keep `app/storage.py` as one S3-compatible client configured by endpoint, bucket and credentials, so the same code talks to S3, to GCS through its S3-interoperability keys, or to local disk.
- Chenyu (2026-09-15): Nasi's shared AWS storage is the development store. Only synthetic and redacted sample documents go there; each person uses their own IAM user limited to that bucket; the bucket stays blocked from public access; keys live only in the gitignored `.env`.
- Nasi (2026-09-15): S3 bucket.
- Nasi (2026-09-16): the shared bucket now lives in a new AWS account, because an access key on the old account was exposed; that key is revoked. Still to do: remove the old account's resources. The new account is `tender-review-dev` in `us-east-1`, managed by Terraform in `infra/` (PR #21); each of us signs in through IAM Identity Center (`dev-admin` to run Terraform, `dev-synthetic` for the bucket), so there are no long-lived access keys. Proposal (PR #21): the bucket holds synthetic data only, and the redacted cases stay in each person's private local data folder.
- Decision: decided (2026-09-15). Nasi's S3 bucket is the shared development store; `storage.py` stays one S3-compatible client.

### A4. "Redis queue" in AI_camp
- Plan: "AI_camp Flask API, Redis queue, per-page tasks, JSON caches: not ported".
- Proposal: there is no Redis in the repository; `service/batch_jobs.py` uses `ThreadPoolExecutor(3)`. Wording only.
- Chenyu:
- Nasi:
- Decision: open

### A5. Capacity estimate
- Plan: 15,000 scanned pages, 2,500 triage calls plus 2,500 other calls, about 83 minutes at 60 requests per minute and 17 minutes at 300.
- Proposal: those are cloud-provider rate limits. On one DGX Spark running vLLM, a six-page vision call at 150 DPI is roughly 15k input tokens for a Qwen-VL-class model, and one box handles a few such calls per minute, not 60. Measure calls per minute on the real box (or a rented equivalent) at S2 and quote the measured number. "100-vendor batch under 8 hours" is a hypothesis until then.
- Chenyu:
- Nasi:
- Decision: open

### A6. Real documents from day 4; live evals
- Plan: "Real documents are used from D4"; live evals at CP3 and CP4; "real client documents arrive for the pilot tomorrow" on D9.
- Proposal: real client documents never reach a cloud endpoint. Only the redacted sample cases are cleared for cloud models, and that clearance is Chenyu's decision. Every fixture carries a `data_class`, and every live eval names the endpoint it runs against.
- Chenyu:
- Nasi:
- Decision: open

### A7. Eval sets ported as they are
- Plan: "Rule engine, rule files, leaf extractor, checker prompts, eval sets: port to app/engine/, templates/, novel.py, app/prompts/, test/evals/".
- Proposal: `tests/evals/*` in AI_camp contain vendor values from the redacted bid; the repository also holds `retrieval_eval/production_parser_nodes_full.json`, `ground_truth_full.md` and `archive/reports/tender_compliance_*`, all derived from the redacted documents. Exclude these from the port; keep ground truth and eval sets in the private data folder the plan already describes on D5.
- Chenyu:
- Nasi:
- Decision: open

## B. Scope: drop or defer

Proposed because none of these help a job application, and several need a client that does not exist. Each is listed on its own so it can be kept individually.

### B1. Client pilot, hosting region, pilot slot
- Plan: D1 confirms the client's availability; D10 15:00 to 17:00 is "pilot tender with the client in the approved environment"; CP5 KR5 is "pilot tender evaluated with the client's reviewers; findings list recorded"; open decisions include a hosting region for Hong Kong public data and a pilot slot.
- Proposal: there is no client. The sample cases came from the camp as redacted documents, so nobody sends real documents and nobody sits as a reviewer on day 10. CP4 KR1 (run the redacted Tender 1 bid and compare with the historical Summary List and Price Summary) already provides the strongest evidence available. Drop the pilot, the "real documents arrive" line, the hosting-region decision and the pilot-slot decision. If a camp mentor or the person who supplied the sample cases is reachable, replace the pilot with a recorded 30-minute walkthrough on the synthetic case, as a stretch item rather than a key result.
- Chenyu (2026-09-15): keep on the list for Nasi to check; drop unless a camp mentor can act as reviewer.
- Nasi:
- Decision: open

### B2. SSO / OIDC identity provider
- Plan: open decision by D8, "client SSO (OIDC or SAML) or per-user accounts with MFA, before D9 auth work"; users, roles and project membership "OIDC-ready".
- Proposal: no client, so no identity provider to integrate. Keep per-user accounts with a role (see B9); drop the OIDC and SAML work.
- Chenyu:
- Nasi:
- Decision: open

### B3. Retention period with logged deletion
- Plan: D9, "documents are deleted after the agreed retention period, and the deletion is logged"; a retention job and a retention test.
- Proposal: a retention policy is agreed with a client. Defer.
- Chenyu:
- Nasi:
- Decision: open

### B4. Upload quarantine with malware scan
- Plan: D9, "uploaded files wait in quarantine until their size and file type are checked and a malware scan passes".
- Proposal: keep the size cap and file-type check (they are small and part of B9). Defer the quarantine flow and the malware scanner.
- Chenyu:
- Nasi:
- Decision: open

### B5. Restore and rollback drills with RPO / RTO
- Plan: CP5 KR4, "recovery point at most 15 minutes, recovery time at most 4 hours measured; rollback with no data loss"; point-in-time recovery, object versioning, drill records.
- Proposal: defer. A measured recovery objective only matters for an operated service.
- Chenyu:
- Nasi:
- Decision: open

### B6. Infrastructure-as-code production profile, two API replicas
- Plan: D10, "two copies of the API, three workers, the database, file storage and the model service, defined in files rather than clicked together, with an automatic check that nothing is publicly exposed".
- Proposal: keep one compose file that runs the whole stack on one machine (this is also the demo setup, see G1). Defer the multi-replica profile and the policy check.
- Chenyu:
- Nasi:
- Decision: open

### B7. Dashboards, alerts, runbook
- Plan: D10, dashboards and alerts for stuck checks, model errors, cost, screen speed and backup age; a runbook for the client's IT staff.
- Proposal: defer dashboards and alerts. Keep a short "how to run it" section in the README instead of a runbook.
- Chenyu:
- Nasi:
- Decision: open

### B8. Daily and weekly ceremonies
- Plan: 09:30 written check-in, 09:40 call, review windows at 13:00 and 16:30, 17:30 KR update, 17:45 evening note, Monday kickoff, Wednesday knowledge swap, Friday demo and retro, a KR tracker with one issue per task.
- Proposal: replace all of it with three rules. Every change is a pull request reviewed by the other person. Shared shapes live in `app/rulesets/schema.py`, `docs/api_contract.md` and the migrations, and change only in their own PR with both approvals. Each person works independently up to the next stop point in section D and stops there.
- Chenyu (2026-09-15): agreed. We do our own jobs and stop before the work that needs both of us to check.
- Nasi:
- Decision: open

### B9. Cheap security items, kept and done last
- Plan: spread over D9.
- Proposal: keep only the items interviewers ask about and do them after S4 if time remains: per-user login with a role, signed image URLs instead of the key in the link, `/health` without model names, explicit CORS origins, secret scanning in CI, upload size cap and file-type check.
- Chenyu:
- Nasi:
- Decision: open

## C. What stays from the plan

### C1. Unchanged
- Plan and proposal are the same: the split (Chenyu: pipeline, LLM layers L1 to L4 and V0 to V5, worker, gateway, pricing, reports; Nasi: parser and locator L0, rule engine and templates V6, the React three-column UI for L5 and V7); contracts before code; item (l) through every layer before widening; each LLM layer with fixed input, fixed output shape, code checks and a FakeLLM call-count test; human editing as versioned, attributed records with reasons and engine-only re-evaluation; the orchestrator comparison with its decision record; the "Kept, ported, removed" table apart from A7.
- Chenyu (2026-09-15): agreed.
- Nasi:
- Decision: open

## D. Working mode: independent tracks and stop points

### D1. Six stop points
- Proposal: work independently up to each stop point; at the stop point both check together in one call, then continue. Nothing below a stop point depends on the other person's unfinished work: the UI runs on `web/mock/`, the rule builder runs on fixture nodes, every LLM layer runs on the FakeLLM.

| Stop point | Both check together | Chenyu does before it (alone) | Nasi does before it (alone) |
|---|---|---|---|
| S0 Contracts | `schema.py` (Citation, 12 CheckTypes, SlotSpec, SlotValue, TemplateRule, RuleSet), `api_contract.md`, migration 001, compose file. Half a day. | FakeLLM (`test/fakes.py`), the failure-scenario harness, synthetic 366-page combined tender and 100-page scanned bid via `tools/make_demo_case.py` and `tools/pdfgen.py` | Record the port source commit (F5), rotate the RDS password and IAM key, map the 44 check names to 12 kinds, ground truth for Tender 2 and Tender 3 (private folder, never in git) |
| S1 Orchestrator | Read both sets of harness numbers, write `docs/decisions/0001-orchestrator.md`, pick one. | Both spikes (LangGraph + Postgres checkpointer; Procrastinate job queue), both run through the same harness | Port `validator/engine` unchanged, split the 13 rule files into templates + `params/Tender 1.json`, golden test proving verdicts are identical |
| S2 One item end to end | Replace the UI stub with real routes; item (l) on the synthetic tender shows in the Stage I window with its page highlighted. | Worker on the winner, V0 without page cap, V1 triage, V2 resolve, V3 extract for item (l), results API, LLM gateway (fallback, cache, budget, allowlist by `data_class`) | Port the parser, split combined PDFs, clause tree, `locate.py` finding 15 items with Parts on all 3 tenders, `StageResultsWindow` and `DocumentViewer` on the mock |
| S3 Rule sets on 3 tenders | Run the rule-set evals together and record the numbers. | L1 match, L2 slots with quote verification, L3 novel rules (ported `extract_leaf_requirements`), L4 coverage, rulesets backend (edit, versions, diff, confirm) | Parser recall at or above 95% against the ground truth, `RulesWindow` with full editing, Vitest and API-contract snapshot |
| S4 Vendor checks, all items | Run the Tender 1 redacted bid and compare with the historical Summary List and Price Summary. | V3 for every document type using Nasi's checker prompts, V4 negative verification, field corrections and the engine-only re-evaluate job, V5 agent with the injection test, pricing and Word reports from the confirmed rubric | Stage I / II screens for all items with corrections, Scoring and Report windows, engine switched to each tender's confirmed rubric, Playwright review flow |
| S5 Portfolio finish | README, demos, eval report, decision records, public release (section H). | Remove the losing orchestrator and the API threads; GCP demo | Remove Streamlit; final UI polish; screenshots and the demo recording; AWS demo |

- Chenyu (2026-09-15): agreed.
- Nasi:
- Decision: open

### D2. Pacing
- Proposal: S0 to S3 in the first ten working days, S4 as the stretch, S5 the week after. If S4 slips, the project is complete and demonstrable at S3, which is why S3 comes before S4. Start date and holidays are for us to pick; nothing in the plan depends on 21 September.
- Chenyu:
- Nasi:
- Decision: open

## E. Orchestrator comparison

As written, the day-2 comparison decides itself. These four changes make it a fair experiment, and its decision record becomes the best interview artefact in the project.

### E1. LLM cache before the decision
- Plan: gates 1 and 2 require "0 repeated LLM calls" after SIGKILL or SIGTERM; the LLM cache is built on D3, after the decision.
- Proposal: a killed LangGraph node re-runs from its start, so LangGraph can only pass those gates through the cache. Build a cache stub inside the spike (a dict keyed by model, prompt version and input hash) or measure "repeated paid calls, cache allowed" for both variants.
- Chenyu:
- Nasi:
- Decision: open

### E2. Procrastinate as the run queue in both variants
- Plan: the LangGraph variant hand-writes "claiming, retries, dead jobs, shared rate limit"; the queue variant gets them from Procrastinate.
- Proposal: use Procrastinate as the run queue in both variants. Then the only difference measured is per-node checkpoints plus `interrupt()` versus a hand-written `job_steps` table plus status-column pauses.
- Chenyu:
- Nasi:
- Decision: open

### E3. Neutral framing
- Plan: "the queue is what this plan recommends"; the repo layout removes `langgraph*`; the data model lists "Procrastinate tables"; the production diagram says "procrastinate worker"; the scalability row says "LangGraph and threads removed".
- Proposal: keep the queue as the default and say so once. Keep the one-paragraph LangGraph layout already present in the "Alternative" section so the losing variant is not pre-deleted from the document.
- Chenyu:
- Nasi:
- Decision: open

### E4. One full day, decision the next morning
- Plan: build both variants in the morning of D2, run twelve scenarios in the afternoon, decide by 17:00.
- Proposal: the harness (kill, SIGTERM, two workers and two API copies, 429 then permanent failure, pause-edit-resume, re-check after a new version, field correction, plus the three "should" scenarios) is one to two days of work and is reused later as CP2 KR3 and CP4 KR6. Build it before S0, give the comparison a full day, and write the decision at S1 the next morning.
- Chenyu:
- Nasi:
- Decision: open

## F. Repository, data and confidentiality

### F1. Repository
- Decision (Chenyu, 2026-09-15): stay in the current private repo `chenyufang-data/tender-evaluation-assistant` until the project is publishable, then transfer it to an organisation and make it public. A transfer does not carry collaborators, so Nasi is added to the organisation at that point. Status: decided.
- Nasi:

### F2. Data classes and endpoints
- Proposal: every fixture and every project carries a `data_class` (`synthetic`, `redacted_sample`, `confidential`). The gateway allowlist keys on it. Each live eval names the endpoint it ran against in its stored result.
- Chenyu:
- Nasi:
- Decision: open

### F3. Files excluded from the port
- Proposal: the port from commit `7e8e273` (F5) excludes `retrieval_eval/production_parser_nodes_full.json`, `ground_truth_full.md`, `archive/reports/tender_compliance_*`, and the vendor values in `tests/evals/*`. The port PR checklist lists them. Ground truth for all three tenders lives in the private data folder.
- Chenyu:
- Nasi:
- Decision: open

### F4. Public-release audit at S5
- Proposal: before the transfer and the switch to public, run gitleaks over the full history and search the history for the three tender numbers and the vendor names. The joint repo's history is Chenyu's old repo, which committed only code, tests and the synthetic demo case; the risk is what the port brings in.
- Chenyu:
- Nasi:
- Decision: open

### F5. Port source
- Plan: "Commit the 50 uncommitted files, tag them" as `aicamp-final`; every port copies from that tag.
- Proposal: port from what is already pushed to `nlp4725/Bidding-AI-expert` and do not push the local uncommitted work. The fixed source is branch `redesign/stage1-panel` at commit `7e8e273dfd24c8fefeffc43a2014e0ddbc267d30` (2026-08-10); every port PR names this commit (`git show 7e8e273:<path>`) instead of the tag. The 52 uncommitted local files are mostly the AI_camp job runtime (`service/worker.py`, `queue_client.py`, `rate_limiter.py`, `task_store.py`, `storage.py`, `s3_docs.py`, `aws_config.py`, `infra/`), which the worker and gateway replace, plus 21 test files. `validator/engine/` has no local changes. The few local changes in ported areas (`ingest/layout_document_index.py`, `validator/checkers/information_schedule_checker.py`, `extract/fields.py`, `extract/llm_client.py`, `extract/vision_client.py`, `frontend/src/api.js`, `frontend/src/components/VendorCompletenessList.jsx`) are kept in a local patch and brought over by hand in the matching port PR only if needed. Key rotation (RDS password, IAM key) is unaffected and still happens before S0.
- Chenyu:
- Nasi (2026-09-16): port from the pushed commit; no push of the local work and no `aicamp-final` tag.
- Decision: open

## G. Deployment and demo

### G1. Two independent demos, same image
- Proposal: Chenyu deploys on GCP Cloud Run under the cyfang domain; Nasi deploys on AWS under her own domain. Each deployment has its own Postgres and object store and holds synthetic data only. CI builds one image per tag and pushes it to a registry both pull from, so the two demos are the same build.
- Chenyu (2026-09-15): proposed.
- Nasi (2026-09-16): AWS side confirmed: the `tender-review-dev` account in `us-east-1`, Terraform in `infra/` (PR #21), synthetic data only. Domain not chosen yet.
- Decision: open

### G2. Configuration only
- Proposal: nothing in the code names a cloud. Database URL, storage endpoint, LLM endpoint and public base URL come from environment variables. `deploy/cloudrun/` stays for GCP; Nasi adds the AWS equivalent (one EC2 host with the compose file and Caddy for TLS is the simplest).
- Chenyu:
- Nasi:
- Decision: open

### G3. Abuse limits before a public demo
- Proposal: a public demo needs, before it goes live, a demo login or a read-only mode with pre-computed synthetic results, the gateway's per-day LLM budget, and an upload size cap. Otherwise anyone can upload PDFs and spend our model credits.
- Chenyu:
- Nasi:
- Decision: open

## H. Portfolio finish

### H1. Checklist for S5
- Proposal: the end state is a public repo containing only code, tests and synthetic data, with results on the redacted cases reported as numbers.
  1. README a recruiter reads in two minutes: one architecture diagram, a 30-second GIF of the three-column review, a results table (parser recall on 3 tenders, rule-set eval, agreement with the historical Stage I / II decisions and price ranking on Tender 1), the test count and CI badge.
  2. A "who built what" section naming both of us with our areas, an Authors section and a `CITATION.cff` with both names.
  3. `docs/decisions/0001-orchestrator.md` with the harness numbers for both variants, written so it can be linked on its own.
  4. Two live demos (G1) or a two-minute video if a demo has to stay private.
  5. One-command setup: `docker compose up` brings up Postgres, the API, a worker and the UI on the synthetic case.
  6. Descriptive test names for the tests that tell a story: call-count tests, the prompt-injection test, the golden engine test, the resume-after-kill test.
- Chenyu:
- Nasi:
- Decision: open

## Verified facts (no action needed)

Checked on 2026-09-15. In `tender-evaluation-assistant`: jobs run as daemon threads in `backend/api.py`; the Cloud Run deploy pins `--max-instances 1`; LangGraph SQLite checkpoints are copied to a scratch directory; routes `/run`, `/resume`, `/graph`, `/evaluate`, `/evaluation` and `/reports/{name}` exist; `/health` returns model names; the image link carries the key; `max_ocr_pages=8`; `max_total_chars=45000`; Python 3.12 in CI and both Dockerfiles; tests live in `test/`; `python run_demo.py offline-demo` is the right command. In `Bidding-AI-expert`: `validator/engine/core.py` exists; `extract_leaf_requirements` is in `rules/requirement_extraction.py`; branch `redesign/stage1-panel` is merged via PR #1; letters (l) Non-collusive Certificate, (i) Manufacturer's Letter of Intent and (b)/(c) Price Schedule Part A match the orchestrator's registry; 44 check names and 13 rule files; evals cover Tender 1 only. Tender 3 is one 366-page PDF. Procrastinate 3.9.0 has worker heartbeats and stalled-job retry; `langgraph-checkpoint-postgres` 3.1.2 is MIT; LangGraph Server is Elastic License 2.0 and self-hosting needs an Enterprise plan, so excluding it is right.

## Sources

- Procrastinate stalled-job retry: https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
- MinIO maintenance mode and archive: https://github.com/minio/minio/issues/21714
- LangGraph Server licensing: https://docs.langchain.com/langsmith/deploy-standalone-server
- GitHub branch protection availability: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
