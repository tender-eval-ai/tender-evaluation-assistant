"""The run queue and the check job: the orchestrator chosen at stop point S1
(docs/decisions/0001-orchestrator.md), promoted from spikes/queue.

    queue.py     Procrastinate app, settings, retry policy, stalled-job query
    models.py    RunStatus, Result, Step, Pipeline, Pause, the Context a step sees
    execute.py   runs a pipeline over a context: skip finished steps, pause, resume
    store.py     runs, job_steps, results, corrections and rule-set versions in Postgres
    registry.py  pipelines by kind
    tasks.py     the Procrastinate tasks run_check / resume_check
    runner.py    the port the API calls: start, status, results, rerun, list_stuck, ...
    sweeper.py   inside every worker: retry stalled jobs, resume paused runs
    worker.py    python -m app.jobs.worker
"""
