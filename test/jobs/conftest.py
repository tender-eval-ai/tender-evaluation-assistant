"""The harness is opt-in: it needs Postgres and spawns worker subprocesses. Without
`-m orchestrator` on the command line its tests are skipped, so the default suite
stays offline and fast."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "orchestrator: needs Postgres and subprocess workers; opt-in (-m orchestrator)")


def pytest_collection_modifyitems(config, items):
    expr = config.getoption("-m") or ""
    if "orchestrator" in expr and not expr.strip().startswith("not"):
        return
    skip = pytest.mark.skip(reason="opt-in: run with -m orchestrator and DATABASE_URL set")
    for item in items:
        if "orchestrator" in item.keywords:
            item.add_marker(skip)
