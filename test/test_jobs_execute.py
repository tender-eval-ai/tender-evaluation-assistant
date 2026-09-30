"""The pipeline executor (app/jobs/execute.py) and the pieces of the runner that need
no database: skip finished steps, resume from a checkpoint inside a step, pause and
resume, the retry policy, the migration file format, the settings."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import db
from app.jobs.execute import run_pipeline
from app.jobs.models import Pause, Pipeline, Step
from app.jobs.queue import MAX_ATTEMPTS, Settings, TransientRetry
from test.jobs.memory_context import MemoryContext


def pipeline(*steps: Step) -> Pipeline:
    return Pipeline(kind="k", steps=list(steps), fields_key="fields", decide=lambda f, s: {"ok": True})


def test_finished_steps_are_skipped_and_outputs_accumulate():
    calls = []
    p = pipeline(Step("a", lambda ctx: calls.append("a") or {"x": 1}), Step("b", lambda ctx: calls.append("b") or {"y": ctx.data["x"] + 1}))
    ctx = MemoryContext()
    assert run_pipeline(p, ctx).state == "done"
    assert ctx.data == {"x": 1, "y": 2} and ctx.done == ["a", "b"]
    run_pipeline(p, ctx)                       # a second execution of a finished run does nothing
    assert calls == ["a", "b"]


def test_a_step_continues_from_its_own_checkpoint_after_a_crash():
    """Triage-like: batches checkpointed one at a time; the crash after batch 2 costs
    nothing already labelled."""
    labelled = []

    def triage(ctx):
        nxt = ctx.data.get("next", 0)
        while nxt < 4:
            labelled.append(nxt)
            nxt += 1
            ctx.checkpoint(next=nxt)
            if nxt == 2 and not ctx.data.get("crashed"):
                ctx.checkpoint(crashed=True)
                raise RuntimeError("killed")
        return {"fields": {"n": nxt}}

    p = pipeline(Step("triage", triage))
    ctx = MemoryContext()
    with pytest.raises(RuntimeError):
        run_pipeline(p, ctx)
    assert labelled == [0, 1] and ctx.done == []
    assert run_pipeline(p, ctx).state == "done"
    assert labelled == [0, 1, 2, 3] and ctx.data["fields"] == {"n": 4}


def test_pause_parks_the_run_and_resume_runs_the_same_step_again():
    def wait(ctx):
        return None if ctx.ruleset() else Pause("ruleset_confirmed")

    p = pipeline(Step("extract", lambda ctx: {"fields": {"f": 1}}), Step("await", wait, "steps"), Step("decide", lambda ctx: {"d": 1}))
    ctx = MemoryContext()
    out = run_pipeline(p, ctx)
    assert out.state == "paused" and out.step == "await" and out.reason == "ruleset_confirmed"
    assert ctx.done == ["extract"] and ("paused", "await", "ruleset_confirmed") in ctx.events
    ctx.confirm({"version": 1})
    assert run_pipeline(p, ctx).state == "done"
    assert ctx.done == ["extract", "await", "decide"]


def test_an_unblock_written_between_pause_and_recheck_is_not_missed():
    """The step is asked twice: the second answer sees a confirmation written after the
    first, so the run never waits for a sweeper it does not need."""
    ctx = MemoryContext()
    answers = iter([Pause("ruleset_confirmed"), None])

    def wait(ctx_):
        return next(answers)

    p = pipeline(Step("await", wait, "steps"))
    assert run_pipeline(p, ctx).state == "done"
    assert [e[0] for e in ctx.events] == ["paused", "resumed", "complete"]


def test_only_transient_errors_are_retried_and_only_up_to_the_limit():
    policy = TransientRetry()
    transient = SimpleNamespace(transient=True)
    assert policy.get_retry_decision(exception=transient, job=SimpleNamespace(attempts=0)) is not None
    assert policy.get_retry_decision(exception=transient, job=SimpleNamespace(attempts=MAX_ATTEMPTS)) is None
    assert policy.get_retry_decision(exception=RuntimeError("permanent"), job=SimpleNamespace(attempts=0)) is None


def test_a_transient_error_waits_longer_each_time_past_a_providers_minute():
    """A 429 on a token-per-minute limit clears only when the minute rolls over."""
    waits = [TransientRetry(base=10).wait(n) for n in range(MAX_ATTEMPTS)]
    assert waits == [10, 20, 40, 80, 120] and sum(waits[:3]) > 60


def test_every_migration_has_an_up_and_a_down_section():
    paths = db.files()
    assert [p.name for p in paths][:3] == ["001_jobs.sql", "002_gateway.sql", "003_api.sql"]
    for path in paths:
        up, down = db.split(path.read_text())
        assert ("create table if not exists" in up or "alter table" in up) and "drop" in down, path.name
    with pytest.raises(ValueError, match="sections"):
        db.split("create table x (a int);")


def test_settings_come_from_the_environment_with_production_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    for k in ("JOBS_HEARTBEAT", "JOBS_STALLED_AFTER", "JOBS_SWEEP_EVERY", "JOBS_POLL", "JOBS_CONCURRENCY"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert (s.heartbeat, s.stalled_after, s.sweep_every, s.poll, s.concurrency) == (10.0, 30.0, 5.0, 2.0, 2)
    monkeypatch.setenv("JOBS_STALLED_AFTER", "3")
    assert Settings.from_env().stalled_after == 3.0
