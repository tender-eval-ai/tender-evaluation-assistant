# Slice specification for the orchestrator comparison (S1)

Two implementations of the same slice are built, one on LangGraph with the Postgres checkpointer and one on a Postgres job queue (Procrastinate), and both are run through `test/jobs/harness.py`. This page is what "the same slice" means. Chenyu builds the LangGraph variant; the queue variant is built from this page alone, so anything not written here is out of scope for both.

## 1. What the slice does

One vendor's bid is checked for one Completeness Check Schedule item, (l), the Non-collusive Tendering Certificate.

| Step | Layer | Input | Output | LLM |
|---|---|---|---|---|
| triage | V1 | the bid's page images | one label per page | one call per six pages |
| resolve | V2 | the page labels | the page numbers that hold item (l), with a confidence | one call |
| extract | V3 | the images of those pages | `{present, signed, dated, page}` | one call |
| await rubric | L5 | the tender's rubric | nothing; the run waits until a person confirms the rubric | none |
| decide | V6 | the fields and the confirmed rubric | `{outcome: pass \| disqualified, reasons, rubric_version}` | none |
| store | | the fields and the verdict | a result row pinned to the rubric version | none |

The step functions already exist in `test/jobs/slice.py` (`triage`, `resolve`, `extract`, `decide`) and must be called, not re-implemented. The LLM is `slice.make_llm(cert_page)`, a FakeLLM whose rules compute their replies from the prompt; it reads `FAKE_DELAY` and `FAKE_FAULTS` from the environment.

## 2. What a variant must expose

The `Orchestrator` interface in `test/jobs/adapters.py`, in full. In words:

- `start_check(tender, vendor)` enqueues one run and returns its id at once. The work happens in a worker process, never in the caller.
- `status(run_id)` reports `state` (queued, running, paused, done, failed, dead, lost), the current `step`, and `progress` as `{done, total, unit}` for the current step.
- `results(run_id)` returns the stored fields, verdict, rubric version and corrections, or `None`.
- `confirm_rubric(tender)` lets paused runs proceed. `edit_rubric(tender, patch)` changes the draft before confirmation; a paused run must decide with the edited rubric.
- `publish_rubric_version(tender, patch)` confirms a new version and re-decides every finished vendor against it using the stored fields. No LLM call is allowed.
- `correct_field(run_id, item, name, value, reason)` stores the correction beside the model's value and re-decides at once with no LLM call. `rerun(run_id)` re-extracts the vendor; the correction must still apply afterwards.
- `list_stuck()` returns runs that are not progressing, with why and since when, from one call.
- `workers()` returns the PIDs of live worker processes so the harness can kill one. `setup()` resets storage; `shutdown()` stops workers.

Workers are started as `python -m test.jobs.worker <adapter> <run_id>` and implement `execute(run_id)`.

## 3. What each variant must decide, and write down in its adapter's docstring

1. **Where progress lives.** After which points a crash resumes without redoing work: per triage batch (the queue variant's `job_steps` table) or per node (the checkpointer). The harness measures the difference as repeated LLM calls after a kill.
2. **How the pause works.** A status column polled by the worker, or `interrupt()` with `Command(resume=...)` from the API. Either way `edit_rubric` while paused must be visible to the decision.
3. **How a second worker takes over.** Heartbeats and stalled-job retry, or a run queue with claiming and leases around the graphs. Scenario 3 sends the same vendors twice from two API copies and counts duplicates.
4. **How provider errors are handled.** 429 is transient and must be retried without skipping the failed call; `permanent` must end the run in a visible `failed` or `dead` state.
5. **How the LLM cache is used.** A variant that re-runs an interrupted step may avoid paying twice only through a cache keyed by model, prompt version and input hash. If a variant relies on one, it builds a minimal one inside the spike; the harness counts repeated calls with the cache in place.

## 4. Out of scope for both variants

More than one item, more than one tender per run, the real parser, the real gateway, authentication, the UI, Word reports, a rate limiter beyond what scenario 8 needs to be measured, and any change to `slice.py` or `harness.py`. If a scenario cannot be passed without one of these, that is a finding to record, not a reason to widen the slice.

## 5. What is recorded

`python -m test.jobs.harness <adapter> --out output/orchestrator` writes `<adapter>.json` and `<adapter>.md`. The decision record `docs/decisions/0001-orchestrator.md` pastes both tables under the reference baseline's table, states which must-pass gates (1 to 7) each variant passed, compares glue code (11) and the "what is stuck" answer (10), and names the winner with the decision rule from the plan: failing any must-pass gate rules a variant out; between variants that pass, fewer moving parts, less glue code and the clearer answer to scenario 10 win; licence and on-prem fit break a tie.

## 6. Reading before building (two hours, with these questions)

LangGraph 1.2 with `langgraph-checkpoint-postgres` 3.1: how a `thread_id` maps to a run and what `PostgresSaver.setup()` creates; how `interrupt()` stops a node and `Command(resume=...)` continues it; what a checkpoint holds when the graph's shape changes between deploys; how to run one node's function alone in a test.

Procrastinate 3.9: how tasks are declared and a worker claims jobs; what the heartbeat and stalled-job retry do and their timing parameters; how a `queueing_lock` prevents the same vendor running twice; how graceful shutdown behaves on SIGTERM; where per-step progress would live (Procrastinate has no such table; the variant adds `job_steps`).
