# Orchestrator failure harness

Runs the same vertical slice (one vendor, item (l), the Non-collusive Tendering Certificate) under different orchestrators and subjects each to the same failure scenarios. The numbers feed `docs/decisions/0001-orchestrator.md` at stop point S1.

## Run it

```bash
docker run -d --name tea-harness-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=harness -p 55432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:dev@localhost:55432/harness

python -m test.jobs.harness reference --out output/orchestrator      # all twelve scenarios, JSON + markdown table
python -m test.jobs.harness reference --only 1 5                     # a subset
python -m pytest test/jobs -m orchestrator -q                        # the same scenarios as tests
```

Environment knobs read by workers: `FAKE_DELAY="0.25,0.5"` (seconds per LLM call), `FAKE_FAULTS="2:429,3:429,6:permanent"` (fault by call index), `N_PAGES`, `CERT_PAGE`, `SLICE_EXTRA_STEP`.

## Files

| File | What |
|---|---|
| `slice.py` | The steps: triage (6 pages per call), resolve, extract, decide (engine, no LLM); the FakeLLM rules that compute replies from the prompt; `make_llm()` |
| `adapters.py` | The `Orchestrator` interface every variant implements, and the registry |
| `reference.py` | The naive baseline: one subprocess per job, a run table, no retry, no lease, no limiter |
| `worker.py` | `python -m test.jobs.worker <adapter> <run_id>`, the process the harness kills |
| `harness.py` | Scenarios 1 to 12, the `Measure` record, the markdown table, the CLI |
| `test_orchestrator_scenarios.py` | The scenarios as opt-in tests (`-m orchestrator`) |

## Scenarios and measures

| # | Scenario | Gate | Measure |
|---|---|---|---|
| 1 | Kill a worker mid-check (SIGKILL) | must | lost jobs, repeated LLM calls, seconds to recover |
| 2 | Stop a worker like a deploy (SIGTERM) | must | same |
| 3 | Two API copies submit the same vendors | must | vendors run twice |
| 4 | 429s then a permanent failure | must | retried without skipping; failure visible as failed/dead |
| 5 | Pause for the rubric; edit while paused; resume | must | verdict reflects the edit |
| 6 | New rubric version re-checks every vendor | must | LLM calls (should be 0) |
| 7 | Reviewer corrects one field | must | verdict updates with 0 calls; correction survives a re-run |
| 8 | Many vendors under a provider limit | should | peak calls in any 60 s window |
| 9 | Add a step while jobs are paused | should | paused runs finish; new step applied |
| 10 | What is stuck, why, since when | should | one call lists the killed run with why and since |
| 11 | Glue code | compare | non-blank lines of the adapter |
| 12 | One step alone | compare | triage runs without the orchestrator |

"Repeated LLM calls" counts calls answered more than once for the same scope, kind and prompt hash, read from the FakeLLM's JSON-lines log that every worker process appends to. A candidate that re-runs an interrupted node pays those again unless it caches.

## Adding a variant (S1)

Implement `Orchestrator` (see `adapters.py`) in `spikes/<name>/adapter.py`, register it in `ADAPTERS`, and give the worker a `execute(run_id)` that runs the steps of `slice.py`. Then:

```bash
ORCHESTRATOR_ADAPTER=langgraph ORCHESTRATOR_EXPECT_GATES=1 python -m pytest test/jobs -m orchestrator -q
python -m test.jobs.harness langgraph --out output/orchestrator
```

## Results so far

Both tables come from `python -m test.jobs.harness <adapter> --out output/orchestrator` on the same machine (2026-09-15). The reference adapter is the naive "one process per job" baseline; a candidate must turn the must-pass rows green.

### Reference adapter (baseline), 92 s

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

### LangGraph + Postgres checkpointer on the Procrastinate queue (`spikes/langgraph`), 48 s

| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kill a worker in the middle of a vendor check | must | pass | 0 | 0 | 0 | 5 | 1.58 | final state done; killed pid 53406 with SIGKILL after the first triage batch |
| 2 | Stop a worker the way a deploy does (SIGTERM) | must | pass | 0 | 0 | 0 | 5 | 1.57 | final state done; killed pid 53422 with SIGTERM after the first triage batch |
| 3 | Two workers and two API copies, the same vendors submitted twice | must | pass | 0 | 0 | 0 | 60 |  | 12 vendors finished; a vendor run twice is paid twice |
| 4 | Provider returns 429s, then one permanent failure | must | pass | 0 | 0 | 0 | 6 |  | final state failed; 2 transient errors seen; retried after 429: True; permanent failure visible as failed/dead: True |
| 5 | Pause for rubric confirmation; edit the rubric while paused; resume | must | pass | 0 | 0 | 0 | 5 |  | verdict reflects the edit made while paused |
| 6 | Rubric edited after confirming: new version, re-check every vendor | must | pass | 0 | 0 | 0 | 0 |  | 10 vendors re-checked to v2 with 0 LLM calls |
| 7 | Reviewer corrects one field | must | pass | 0 | 0 | 0 | 10 |  | verdict updated with 0 calls: True; correction survived a re-run: True |
| 8 | 20 vendors at once under a 60/min provider limit | should | FAIL | 0 | 0 | 0 | 100 |  | peak 100 calls in any 60 s window (limit 60) |
| 9 | Add a pipeline step while 5 jobs are paused mid-way | should | pass | 0 | 0 | 0 | 0 |  | paused runs finished: True; the new step ran for them: True |
| 10 | Which vendors are stuck, why, since when | should | pass | 0 | 0 | 0 | 0 | 8.27 | never listed as stuck within 8 s; recovered without help: True |
| 11 | Glue code and infrastructure outside the pipeline steps | compare | - | 0 | 0 | 0 | 0 |  | 471 non-blank lines in adapter.py (128), tasks.py (57), graph.py (82), queue.py (76), store.py (128); extra services: Postgres (Procrastinate tables + LangGraph checkpoints) |
| 12 | Testing one step on its own, without the orchestrator | compare | pass | 0 | 0 | 0 | 2 |  | triage ran alone on 8 pages in 2 calls |

Reading the LangGraph rows: a killed worker's job is retried by the sweeper after the 3 s heartbeat timeout and the new worker continues the same thread from its last checkpoint (one checkpoint per six-page triage batch), so nothing is lost and nothing is paid twice; a SIGTERM lets the worker finish its job first; a transient 429 fails the job and the queue's retry strategy re-runs it from the checkpoint; a run interrupted for the rubric is resumed by a second job with `Command(resume=...)`; corrections live in the shared results table and survive a re-run; a pipeline step added while runs were paused was applied to them on resume. Scenario 8 fails because no rate limiter was built (out of the spike's scope). Scenario 11 counts 471 lines, of which `queue.py` and `store.py` (204) are shared with the queue variant.
