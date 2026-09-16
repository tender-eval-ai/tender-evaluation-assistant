"""The failure scenarios as tests. Opt-in: needs Postgres (DATABASE_URL) and spawns
worker subprocesses, so it runs under `-m orchestrator`, never in the default suite.

    DATABASE_URL=postgresql://postgres:dev@localhost:55432/harness \\
    python -m pytest test/jobs -m orchestrator -q

For the reference adapter the expectations are the baseline's known failures: the tests
prove the harness detects them. For a candidate (ORCHESTRATOR_ADAPTER=langgraph|queue)
set ORCHESTRATOR_EXPECT_GATES=1 and the must-pass gates are asserted.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from test.jobs import harness
from test.jobs.adapters import load

pytestmark = pytest.mark.orchestrator

ADAPTER = os.environ.get("ORCHESTRATOR_ADAPTER", "reference")
EXPECT_GATES = os.environ.get("ORCHESTRATOR_EXPECT_GATES") == "1"

# What the naive baseline is known to do. A harness that never fails is untested.
BASELINE = {
    1: lambda m: m.lost_jobs == 1 and not m.passed,
    2: lambda m: m.lost_jobs == 1 and not m.passed,
    3: lambda m: m.duplicates > 0 and not m.passed,
    4: lambda m: not m.passed and "failed" in m.notes,
    5: lambda m: m.passed,
    6: lambda m: m.passed and m.llm_calls == 0,
    7: lambda m: not m.passed and "0 calls: True" in m.notes and "survived a re-run: False" in m.notes,
    8: lambda m: m.llm_calls > 0,
    9: lambda m: m.passed,
    10: lambda m: m.passed,
    11: lambda m: m.passed is None and "lines" in m.notes,
    12: lambda m: m.passed,
}


@pytest.fixture(scope="module")
def adapter():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; start Postgres and export it to run the orchestrator harness")
    a = load(ADAPTER)
    yield a
    a.shutdown()


@pytest.fixture(scope="module")
def log_dir():
    return Path(tempfile.mkdtemp(prefix="harness-"))


@pytest.fixture(scope="module")
def results(adapter):
    collected: list[harness.Measure] = []
    yield collected
    if collected:
        out = Path("output/orchestrator")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{adapter.name}.md").write_text(harness.markdown_table(sorted(collected, key=lambda m: m.scenario), adapter.name))


@pytest.mark.parametrize("number", sorted(harness.SCENARIOS))
def test_scenario(adapter, log_dir, results, number):
    measure = harness.run_scenario(adapter, number, log_dir)
    results.append(measure)
    if EXPECT_GATES and measure.gate == "must":
        assert measure.passed, f"scenario {number} ({measure.title}) failed a must-pass gate: {measure.notes}"
    elif ADAPTER == "reference":
        assert BASELINE[number](measure), f"baseline behaviour changed for scenario {number}: {measure}"
