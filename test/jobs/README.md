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

## Baseline: the reference adapter (2026-09-15, 69 s for all twelve)

What a naive "one process per job" orchestrator does. A candidate must turn the must-pass rows green.

| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kill a worker in the middle of a vendor check | must | FAIL | 1 | 0 | 0 | 1 |  | final state lost; killed pid 24297 with SIGKILL after the first triage batch |
| 2 | Stop a worker the way a deploy does (SIGTERM) | must | FAIL | 1 | 0 | 0 | 2 |  | final state lost; killed pid 24400 with SIGTERM after the first triage batch |
| 3 | Two workers and two API copies, the same vendors submitted twice | must | FAIL | 0 | 0 | 12 | 120 |  | 12 vendors finished; a vendor run twice is paid twice |
| 4 | Provider returns 429s, then one permanent failure | must | FAIL | 0 | 0 | 0 | 2 |  | final state failed; 1 transient errors seen; retried after 429: False; permanent failure visible as failed/dead: True |
| 5 | Pause for rubric confirmation; edit the rubric while paused; resume | must | pass | 0 | 0 | 0 | 5 |  | verdict reflects the edit made while paused |
| 6 | Rubric edited after confirming: new version, re-check every vendor | must | pass | 0 | 0 | 0 | 0 |  | 10 vendors re-checked to v2 with 0 LLM calls |
| 7 | Reviewer corrects one field | must | FAIL | 0 | 0 | 0 | 10 |  | verdict updated with 0 calls: True; correction survived a re-run: False |
| 8 | 20 vendors at once under a 60/min provider limit | should | FAIL | 0 | 0 | 0 | 100 |  | peak 100 calls in any 60 s window (limit 60) |
| 9 | Add a pipeline step while 5 jobs are paused mid-way | should | pass | 0 | 0 | 0 | 0 |  | paused runs finished: True; the new step ran for them: False |
| 10 | Which vendors are stuck, why, since when | should | pass | 0 | 0 | 0 | 0 |  | 1 stuck run(s) listed in 13 ms; killed run listed with why/since: True |
| 11 | Glue code and infrastructure outside the pipeline steps | compare | - | 0 | 0 | 0 | 0 |  | 193 non-blank lines in reference.py; extra services: Postgres |
| 12 | Testing one step on its own, without the orchestrator | compare | pass | 0 | 0 | 0 | 2 |  | triage ran alone on 8 pages in 2 calls |
