"""The worker container's health check (J11-3): healthy while the sweeper keeps finishing
sweeps, unhealthy before the first one and once three are missed."""
import time

from app.jobs import health


def test_the_check_follows_the_sweepers_mark(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "ALIVE", tmp_path / "alive")
    monkeypatch.setenv("JOBS_SWEEP_EVERY", "5")
    monkeypatch.setenv("JOBS_STALLED_AFTER", "30")
    assert health.check() == (False, "no sweep has finished yet") and health.main() == 1
    health.mark_alive()
    ok, why = health.check()
    assert ok and why.startswith("the last sweep finished") and health.main() == 0
    assert health.max_age() == 30, "the stalled-job timeout, when it is longer than three sweeps"
    ok, why = health.check(now=time.time() + 31)
    assert not ok and "limit 30 s" in why
    monkeypatch.setenv("JOBS_SWEEP_EVERY", "20")
    assert health.max_age() == 60
