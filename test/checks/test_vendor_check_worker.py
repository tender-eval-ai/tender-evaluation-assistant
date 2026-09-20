"""The vendor check through a real worker process on Postgres: the run pauses for the
rule set, resumes on confirmation, and the stored verdict comes from the engine.
Opt-in (-m postgres, DATABASE_URL); CI's integration job runs it."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from test.checks.conftest import CASE, PID, RULESET

pytestmark = pytest.mark.postgres


@pytest.fixture
def worker(tmp_path, monkeypatch):
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VENDOR_CHECK_LLM_FACTORY", "test.checks.fake_factory:factory")
    for k, v in {"JOBS_HEARTBEAT": "1", "JOBS_STALLED_AFTER": "3", "JOBS_SWEEP_EVERY": "1", "JOBS_POLL": "0.5"}.items():
        monkeypatch.setenv(k, v)
    pdir = tmp_path / "projects" / PID
    shutil.copytree(CASE / "bids", pdir / "bids")
    (pdir / "work").mkdir()
    (pdir / "meta.json").write_text(json.dumps({"id": PID, "synthetic": True, "data_class": "synthetic"}))

    import app.checks.vendor_check  # noqa: F401  the API side needs the pipeline's decide too
    from app import db
    from app.jobs import queue as q, tasks
    from app.jobs.runner import JobRunner
    db.reset_for_tests()
    db.migrate()
    q.apply_schema(tasks.app)
    proc = subprocess.Popen([sys.executable, "-m", "app.jobs.worker", "--name", "vc-test", "--pipelines",
                             "app.checks.vendor_check", "--no-migrate"], env=os.environ.copy())
    runner = JobRunner(tasks.store).open()
    try:
        yield runner
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        runner.close()


def _wait(runner, run_id, *states, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if runner.status(run_id).state in states:
            return True
        time.sleep(0.25)
    return False


def test_a_vendor_check_runs_through_the_worker_and_stores_the_engine_verdict(worker):
    runner = worker
    runner.store.ensure_draft(PID, RULESET)
    run = runner.start(PID, "Tenderer_B", "vendor_check")
    assert _wait(runner, run, "paused"), runner.status(run)
    status = runner.status(run)
    assert status.step == "await_ruleset" and status.progress == {"reason": "ruleset_confirmed"}
    steps = runner.store.steps(run)
    assert steps["done"] == ["render", "triage", "resolve", "extract", "verify"] and len(steps["data"]["pages"]) == 16
    assert runner.confirm_ruleset(PID) == 1
    assert _wait(runner, run, "done", "failed", "dead"), runner.status(run)
    result = runner.results(run)
    assert runner.status(run).state == "done" and result.ruleset_version == 1
    assert result.verdict["outcome"] == "pass" and result.verdict["part"] == "A"
    assert result.fields["noncollusive_certificate.signature_page"]["page"] == 13
    corrected = runner.correct_field(run, "noncollusive_certificate.signature", None, "signature is a photocopy", by="nasi")
    assert corrected.verdict["outcome"] == "disqualified" and corrected.corrections["noncollusive_certificate.signature"]["by"] == "nasi"
