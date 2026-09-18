# Orchestrator failure harness

Runs the same vertical slice (one vendor, item (l), the Non-collusive Tendering Certificate) under different orchestrators and subjects each to the same failure scenarios. The numbers feed `docs/decisions/0001-orchestrator.md` at stop point S1.

## Run it

```bash
docker run -d --name tea-harness-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=harness -p 55432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:dev@localhost:55432/harness

python -m test.jobs.harness reference --out output/orchestrator      # all twelve scenarios, JSON + markdown table
python -m test.jobs.harness reference --only 1 5                     # a subset
python -m pytest test/jobs -m orchestrator -q                        # the same scenarios as tests
python -m test.jobs.harness app --out output/orchestrator            # the promoted runner (app/jobs), S2
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
| `app_pipeline.py` | The slice as an `app.jobs` pipeline of kind `slice` (the same FakeLLM steps behind `Step` and `Pipeline`) |
| `app_adapter.py` | The promoted runner under the harness: `python -m app.jobs.worker` subprocesses with second-scale settings (`JOBS_HEARTBEAT=1`, `JOBS_STALLED_AFTER=3`, `JOBS_SWEEP_EVERY=1`) |

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

## The promoted runner (S2)

After the S1 decision the queue variant moved to `app/jobs/` as a generic step pipeline (`docs/decisions/0001-orchestrator.md`, Consequences). `app_adapter.py` puts it under the same scenarios, so the promotion is certified by the same gates that chose it:

```bash
ORCHESTRATOR_ADAPTER=app ORCHESTRATOR_EXPECT_GATES=1 python -m pytest test/jobs -m orchestrator -q
```

### The promoted runner (`app/jobs`, 2026-09-17, with the gateway)

| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kill a worker in the middle of a vendor check | must | pass | 0 | 0 | 0 | 5 | 5.05 | final state done; killed pid 39731 with SIGKILL after the first triage batch |
| 2 | Stop a worker the way a deploy does (SIGTERM) | must | pass | 0 | 0 | 0 | 5 | 1.82 | final state done; killed pid 39756 with SIGTERM after the first triage batch |
| 3 | Two workers and two API copies, the same vendors submitted twice | must | pass | 0 | 0 | 0 | 60 |  | 12 vendors finished; a vendor run twice is paid twice |
| 4 | Provider returns 429s, then one permanent failure | must | pass | 0 | 0 | 0 | 6 |  | final state failed; 2 transient errors seen; retried after 429: True; permanent failure visible as failed/dead: True |
| 5 | Pause for rubric confirmation; edit the rubric while paused; resume | must | pass | 0 | 0 | 0 | 5 |  | verdict reflects the edit made while paused |
| 6 | Rubric edited after confirming: new version, re-check every vendor | must | pass | 0 | 0 | 0 | 0 |  | 10 vendors re-checked to v2 with 0 LLM calls |
| 7 | Reviewer corrects one field | must | pass | 0 | 0 | 0 | 10 |  | verdict updated with 0 calls: True; correction survived a re-run: True |
| 8 | 20 vendors at once under a 60/min provider limit | should | pass | 0 | 0 | 0 | 100 |  | peak 59 calls in any 60 s window (limit 60) |
| 9 | Add a pipeline step while 5 jobs are paused mid-way | should | pass | 0 | 0 | 0 | 0 |  | paused runs finished: True; the new step ran for them: True |
| 10 | Which vendors are stuck, why, since when | should | pass | 0 | 0 | 0 | 0 | 8.28 | never listed as stuck within 8 s; recovered without help: True |
| 11 | Glue code and infrastructure outside the pipeline steps | compare | - | 0 | 0 | 0 | 0 |  | 656 non-blank lines in execute.py (32), models.py (63), queue.py (62), registry.py (20), runner.py (121), store.py (152), sweeper.py (43), tasks.py (72), worker.py (39), db.py (52); extra services: Postgres (Procrastinate tables + runs, job_steps, results, rulesets) |
| 12 | Testing one step on its own, without the orchestrator | compare | pass | 0 | 0 | 0 | 2 |  | triage ran alone on 8 pages in 2 calls |

Same must-pass results as the spike it came from. Scenario 8 passes because every call goes through `app/gateway.py`, whose shared rate limiter (`app/gateway_pg.py`, one pace per provider in Postgres) spaces calls from every worker at the configured `LLM_RPM`; the harness's scenario 8 sets that knob to the provider limit it assumes. Scenario 10 passes on recovery: the killed run is listed as stuck 2.5 s after the kill and the sweeper retries it 0.3 s later, a window the harness's quarter-second poll can miss. Line count 11 is larger than the spike's because the runner is now generic (any pipeline of steps, a registry, migrations) rather than one hard-wired slice.

## Results

All three tables come from `python -m test.jobs.harness <adapter> --out output/orchestrator` on the same machine (2026-09-15). The reference adapter is the naive "one process per job" baseline; both candidates pass every must-pass gate. The comparison and the proposed decision are in `docs/decisions/0001-orchestrator.md`.

### Reference adapter (baseline)

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

### LangGraph + Postgres checkpointer on the Procrastinate queue (`spikes/langgraph`)

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

### Postgres job queue with a job_steps table (`spikes/queue`)

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
