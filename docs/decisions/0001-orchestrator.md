# 0001. Orchestrator for the vendor-check pipeline

Status: **draft for stop point S1**, to be decided by both engineers. Date: 2026-09-15. Author of the measurements: Chenyu.

## Context

Slow work (building a rule set, checking a vendor, re-checking after a correction) runs on a background worker with Postgres. Two ways to chain, pause and resume that work were built against the same specification (`docs/spikes/slice_spec.md`) and run through the same failure harness (`test/jobs/harness.py`):

- **LangGraph + Postgres checkpointer** (`spikes/langgraph`): the slice as a graph, one checkpoint per node (one node per six-page triage batch), `interrupt()` for the human pause, resumed with `Command(resume=...)`.
- **Postgres job queue** (`spikes/queue`): one Procrastinate job per run that saves its own progress in a `job_steps` table after every batch and pauses by writing a status.

Both run on the same Procrastinate queue, the same worker processes, the same stalled-job sweeper and the same run/rubric/result store (`spikes/common`), so the comparison measures only what differs: where progress lives and how the pause works. The naive baseline (`test/jobs/reference.py`, one subprocess per job, nothing else) shows what the harness catches.

## Decision rule (from the plan)

Failing any must-pass scenario (1 to 7) rules an option out. Between options that pass, choose fewer moving parts, less glue code and the clearer answer to scenario 10; licence and on-prem fit break a tie.

## Results

Same machine, same day, FakeLLM with 0.25 to 0.5 s per call, 1 s worker heartbeats, 3 s stalled timeout, two worker processes with two job slots each.

### Baseline: reference adapter

| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kill a worker in the middle of a vendor check | must | FAIL | 1 | 0 | 0 | 1 |  | final state lost; killed pid 52826 with SIGKILL after the first triage batch |
| 2 | Stop a worker the way a deploy does (SIGTERM) | must | FAIL | 1 | 0 | 0 | 2 |  | final state lost; killed pid 52912 with SIGTERM after the first triage batch |
| 3 | Two workers and two API copies, the same vendors submitted twice | must | FAIL | 0 | 0 | 12 | 120 |  | 12 vendors finished; a vendor run twice is paid twice |
| 4 | Provider returns 429s, then one permanent failure | must | FAIL | 0 | 0 | 0 | 2 |  | final state failed; 1 transient errors seen; retried after 429: False; permanent failure visible as failed/dead: True |
| 5 | Pause for rubric confirmation; edit the rubric while paused; resume | must | pass | 0 | 0 | 0 | 5 |  | verdict reflects the edit made while paused |
| 6 | Rubric edited after confirming: new version, re-check every vendor | must | pass | 0 | 0 | 0 | 0 |  | 10 vendors re-checked to v2 with 0 LLM calls |
| 7 | Reviewer corrects one field | must | FAIL | 0 | 0 | 0 | 10 |  | verdict updated with 0 calls: True; correction survived a re-run: False |
| 8 | 20 vendors at once under a 60/min provider limit | should | FAIL | 0 | 0 | 0 | 100 |  | peak 100 calls in any 60 s window (limit 60) |
| 9 | Add a pipeline step while 5 jobs are paused mid-way | should | pass | 0 | 0 | 0 | 0 |  | paused runs finished: True; the new step ran for them: True |
| 10 | Which vendors are stuck, why, since when | should | pass | 0 | 0 | 0 | 0 |  | listed as stuck 0.01 s after the kill, with why and since; recovered without help: False |
| 11 | Glue code and infrastructure outside the pipeline steps | compare | - | 0 | 0 | 0 | 0 |  | 194 non-blank lines in reference.py (194); extra services: Postgres |
| 12 | Testing one step on its own, without the orchestrator | compare | pass | 0 | 0 | 0 | 2 |  | triage ran alone on 8 pages in 2 calls |

### LangGraph + Postgres checkpointer

| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kill a worker in the middle of a vendor check | must | pass | 0 | 0 | 0 | 5 | 5.25 | final state done; killed pid 56173 with SIGKILL after the first triage batch |
| 2 | Stop a worker the way a deploy does (SIGTERM) | must | pass | 0 | 0 | 0 | 5 | 1.66 | final state done; killed pid 56204 with SIGTERM after the first triage batch |
| 3 | Two workers and two API copies, the same vendors submitted twice | must | pass | 0 | 0 | 0 | 60 |  | 12 vendors finished; a vendor run twice is paid twice |
| 4 | Provider returns 429s, then one permanent failure | must | pass | 0 | 0 | 0 | 6 |  | final state failed; 2 transient errors seen; retried after 429: True; permanent failure visible as failed/dead: True |
| 5 | Pause for rubric confirmation; edit the rubric while paused; resume | must | pass | 0 | 0 | 0 | 5 |  | verdict reflects the edit made while paused |
| 6 | Rubric edited after confirming: new version, re-check every vendor | must | pass | 0 | 0 | 0 | 0 |  | 10 vendors re-checked to v2 with 0 LLM calls |
| 7 | Reviewer corrects one field | must | pass | 0 | 0 | 0 | 10 |  | verdict updated with 0 calls: True; correction survived a re-run: True |
| 8 | 20 vendors at once under a 60/min provider limit | should | FAIL | 0 | 0 | 0 | 100 |  | peak 100 calls in any 60 s window (limit 60) |
| 9 | Add a pipeline step while 5 jobs are paused mid-way | should | pass | 0 | 0 | 0 | 0 |  | paused runs finished: True; the new step ran for them: True |
| 10 | Which vendors are stuck, why, since when | should | pass | 0 | 0 | 0 | 0 | 5.32 | listed as stuck 2.5 s after the kill, with why and since; recovered without help: True |
| 11 | Glue code and infrastructure outside the pipeline steps | compare | - | 0 | 0 | 0 | 0 |  | 498 non-blank lines in adapter.py (22), tasks.py (58), graph.py (82), base_adapter.py (132), queue.py (76), store.py (128); extra services: Postgres (Procrastinate tables + LangGraph checkpoints) |
| 12 | Testing one step on its own, without the orchestrator | compare | pass | 0 | 0 | 0 | 2 |  | triage ran alone on 8 pages in 2 calls |

### Postgres job queue

| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kill a worker in the middle of a vendor check | must | pass | 0 | 0 | 0 | 5 | 5.25 | final state done; killed pid 56422 with SIGKILL after the first triage batch |
| 2 | Stop a worker the way a deploy does (SIGTERM) | must | pass | 0 | 0 | 0 | 5 | 1.66 | final state done; killed pid 56449 with SIGTERM after the first triage batch |
| 3 | Two workers and two API copies, the same vendors submitted twice | must | pass | 0 | 0 | 0 | 60 |  | 12 vendors finished; a vendor run twice is paid twice |
| 4 | Provider returns 429s, then one permanent failure | must | pass | 0 | 0 | 0 | 6 |  | final state failed; 2 transient errors seen; retried after 429: True; permanent failure visible as failed/dead: True |
| 5 | Pause for rubric confirmation; edit the rubric while paused; resume | must | pass | 0 | 0 | 0 | 5 |  | verdict reflects the edit made while paused |
| 6 | Rubric edited after confirming: new version, re-check every vendor | must | pass | 0 | 0 | 0 | 0 |  | 10 vendors re-checked to v2 with 0 LLM calls |
| 7 | Reviewer corrects one field | must | pass | 0 | 0 | 0 | 10 |  | verdict updated with 0 calls: True; correction survived a re-run: True |
| 8 | 20 vendors at once under a 60/min provider limit | should | FAIL | 0 | 0 | 0 | 100 |  | peak 100 calls in any 60 s window (limit 60) |
| 9 | Add a pipeline step while 5 jobs are paused mid-way | should | pass | 0 | 0 | 0 | 0 |  | paused runs finished: True; the new step ran for them: True |
| 10 | Which vendors are stuck, why, since when | should | pass | 0 | 0 | 0 | 0 | 5.27 | listed as stuck 2.5 s after the kill, with why and since; recovered without help: True |
| 11 | Glue code and infrastructure outside the pipeline steps | compare | - | 0 | 0 | 0 | 0 |  | 451 non-blank lines in adapter.py (22), tasks.py (93), base_adapter.py (132), queue.py (76), store.py (128); extra services: Postgres (Procrastinate tables + q_steps) |
| 12 | Testing one step on its own, without the orchestrator | compare | pass | 0 | 0 | 0 | 2 |  | triage ran alone on 8 pages in 2 calls |

## Reading the numbers

- **Must-pass gates 1 to 7: both variants pass all seven; the baseline fails five.** Recovery after a SIGKILL is 5.3 s for both, and it is the same 5.3 s because both wait for the same 3 s heartbeat timeout plus the sweeper's 1 s tick before another worker takes the job; the checkpoint and the `job_steps` row both let it continue after the first triage batch with zero repeated LLM calls. A SIGTERM finishes the current job in both (Procrastinate drains gracefully). Duplicates are prevented by the same idempotent start in both. Both retry a 429 from where they stopped and end a permanent failure as `failed`. Both see a rubric edit made while paused, re-check ten vendors with zero calls, and keep a correction across a re-run (the shared store does that).
- **Should-pass: identical.** Neither has a rate limiter (scenario 8, out of scope for the spike; the product needs one either way). Both applied a step deployed while runs were paused (scenario 9): LangGraph rebuilt the graph with the new node and the resumed thread followed the new edge; the queue variant simply read the knob at decision time. Both list a killed run as stuck 2.5 s after the kill and heal it within 5.3 s.
- **Moving parts and glue (scenario 11).** Shared code is 336 lines in both. Variant-specific code: queue 115 lines (`tasks.py` 93, `adapter.py` 22); LangGraph 162 lines (`graph.py` 82, `tasks.py` 58, `adapter.py` 22) plus four checkpoint tables and a checkpointer whose `setup()` must be run once by the adapter, never inside jobs (concurrent `setup()` raced on `checkpoint_migrations` during the spike). LangGraph also needed a thread id per attempt so a re-run does not resume the old checkpoint. The queue variant has one progress table and one task function that serves fresh starts, crash retries and confirmation resumes alike.
- **Licences and on-prem fit.** Procrastinate MIT, `langgraph` and `langgraph-checkpoint-postgres` MIT, both on the same Postgres. No difference.

## Decision (proposed)

**The Postgres job queue variant is the product's background worker.** Both pass every gate, so the rule falls to moving parts and glue, where the queue variant is simpler by one library, four tables, one setup-ordering hazard and about fifty lines, with no loss on any measured behaviour.

What this decision does not say: it is about the pipeline runner for a linear per-vendor slice with one human pause. LangGraph's strengths, branching, loops and fan-out with `Send`, and inspecting a thread's state mid-run, were not exercised by the slice. The evidence-search agent (V5) is a loop and may still be implemented as a LangGraph graph *inside* a job if that reads better than a plain loop; that is an implementation choice within a task, not an orchestration decision. The existing two-interrupt graph in `app/graph.py` is retired at S2 with the job threads, as the plan says.

## Consequences

- `app/tasks.py` and the `job_steps` table are built from `spikes/queue/tasks.py`; `spikes/common/queue.py` (retry strategy, sweeper as a periodic task, worker settings) and `spikes/common/store.py` (results and corrections) move under `app/`.
- The `Orchestrator` interface stays as the port the API calls, so the LangGraph variant remains runnable from `spikes/langgraph` under the harness until the decision is final; it is deleted or frozen under a tag afterwards.
- Production heartbeat and stalled-timeout values are the library defaults (10 s / 30 s), not the harness's 1 s / 3 s; recovery after a crash is then about 35 s.
- A shared rate limiter (scenario 8) is still to be built, for either variant.

## How to reproduce

```
docker run -d --name tea-harness-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=harness -p 55432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:dev@localhost:55432/harness
for v in reference langgraph queue; do python -m test.jobs.harness $v --out output/orchestrator; done
ORCHESTRATOR_ADAPTER=queue ORCHESTRATOR_EXPECT_GATES=1 python -m pytest test/jobs -m orchestrator -q
```
