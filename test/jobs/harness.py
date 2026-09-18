"""The failure scenarios, the measures, and the results table.

    DATABASE_URL=postgresql://postgres:dev@localhost:55432/harness \\
    python -m test.jobs.harness reference --out output/orchestrator

Every scenario starts from a reset adapter and an empty FakeLLM log, runs one situation,
and returns a Measure. Scenarios 1 to 7 are must-pass gates for a candidate orchestrator;
8 to 10 are should-pass; 11 and 12 are measurements. The reference adapter fails most
gates on purpose: that is the baseline, and it proves the harness sees failures.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import signal
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from test.fakes import read_log
from test.jobs.adapters import Orchestrator, load

TENDER = "SYN-2026-001"


@dataclass
class Measure:
    scenario: int
    title: str
    gate: str                         # must | should | compare
    passed: bool | None               # None for pure measurements
    lost_jobs: int = 0
    repeated_llm_calls: int = 0
    duplicates: int = 0
    llm_calls: int = 0
    recover_seconds: float | None = None
    notes: str = ""


class Bench:
    """One scenario's context: a reset adapter, a fresh log, helpers."""

    def __init__(self, adapter: Orchestrator, log_dir: Path):
        self.adapter = adapter
        stamp = int(time.time() * 1000)
        self.log = log_dir / f"calls-{stamp}.jsonl"
        self.knobs = log_dir / f"knobs-{stamp}.json"
        os.environ["FAKE_LLM_LOG"] = str(self.log)
        os.environ["HARNESS_KNOBS"] = str(self.knobs)
        for stale in ("FAKE_FAULTS", "SLICE_EXTRA_STEP"):
            os.environ.pop(stale, None)
        self.set(FAKE_DELAY="0.25,0.5")
        adapter.setup()

    def set(self, **values) -> None:
        """Change a knob for this scenario. Written to the knob file, which every worker
        process reads on each job, so it reaches workers started before the scenario."""
        current = json.loads(self.knobs.read_text()) if self.knobs.exists() else {}
        current.update(values)
        self.knobs.write_text(json.dumps(current))
        for k, v in values.items():
            os.environ[k] = str(v)

    def calls(self) -> list[dict]:
        return read_log(self.log) if self.log.exists() else []

    def repeated(self) -> int:
        """Calls answered more than once for the same scope, kind and prompt: paid twice."""
        counts = Counter((c["scope"], c["kind"], c["prompt_sha"]) for c in self.calls() if not c.get("error"))
        return sum(n - 1 for n in counts.values() if n > 1)

    def wait(self, pred, timeout: float, every: float = 0.1) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return True
            time.sleep(every)
        return pred()

    def wait_state(self, run_id: str, *states: str, timeout: float = 30) -> bool:
        return self.wait(lambda: self.adapter.status(run_id).state in states, timeout)

    def wait_step_progress(self, run_id: str, step: str, done_at_least: int, timeout: float = 30) -> bool:
        def ok():
            s = self.adapter.status(run_id)
            return s.step == step and s.progress.get("done", 0) >= done_at_least
        return self.wait(ok, timeout)


def _kill_mid_check(bench: Bench, sig: int, number: int, title: str) -> Measure:
    a = bench.adapter
    run = a.start_check(TENDER, "Tenderer_B")
    assert bench.wait_step_progress(run, "triage", 6), "the worker never reported triage progress"
    holder = a.status(run).worker_pid                    # the process running this job, when the variant reports it
    pids = [holder] if holder and holder in a.workers() else a.workers()
    os.kill(pids[0], sig)
    killed_at = time.time()
    a.confirm_rubric(TENDER)
    finished = bench.wait_state(run, "done", timeout=25)
    state = a.status(run).state
    return Measure(number, title, "must", passed=finished and bench.repeated() == 0,
                   lost_jobs=0 if finished else 1, repeated_llm_calls=bench.repeated(), llm_calls=len(bench.calls()),
                   recover_seconds=round(time.time() - killed_at, 2) if finished else None,
                   notes=f"final state {state}; killed pid {pids[0]} with {signal.Signals(sig).name} after the first triage batch")


def s1_kill(bench: Bench) -> Measure:
    return _kill_mid_check(bench, signal.SIGKILL, 1, "Kill a worker in the middle of a vendor check")


def s2_sigterm(bench: Bench) -> Measure:
    return _kill_mid_check(bench, signal.SIGTERM, 2, "Stop a worker the way a deploy does (SIGTERM)")


def s3_two_api_copies(bench: Bench, vendors: int = 12) -> Measure:
    """Two API instances receive the same 'check these vendors' request at once."""
    a, b = bench.adapter, load(bench.adapter.name)
    names = [f"Tenderer_{i:02d}" for i in range(vendors)]
    runs = [a.start_check(TENDER, n) for n in names] + [b.start_check(TENDER, n) for n in names]
    a.confirm_rubric(TENDER)
    bench.wait(lambda: all(a.status(r).state in ("done", "failed", "lost") for r in runs), timeout=120)
    per_vendor = Counter(a.status(r).vendor for r in set(runs) if a.status(r).state == "done")   # distinct runs
    duplicates = sum(n - 1 for n in per_vendor.values() if n > 1)
    b.shutdown()
    return Measure(3, "Two workers and two API copies, the same vendors submitted twice", "must",
                   passed=duplicates == 0, duplicates=duplicates, llm_calls=len(bench.calls()),
                   notes=f"{len(per_vendor)} vendors finished; a vendor run twice is paid twice")


def s4_provider_errors(bench: Bench) -> Measure:
    """Two 429s, then one permanent failure. Retries must not skip ahead; the failure must be visible."""
    bench.set(FAKE_FAULTS="2:429,3:429,6:permanent")
    a = bench.adapter
    run = a.start_check(TENDER, "Tenderer_B")
    a.confirm_rubric(TENDER)
    bench.wait_state(run, "done", "failed", "dead", "lost", timeout=40)
    s = a.status(run)
    calls = bench.calls()
    transient = [c for c in calls if c.get("error", "") and "429" in c["error"]]
    retried = len(calls) > 3 and any(not c.get("error") for c in calls[3:])   # kept going after the 429s
    visible = s.state in ("failed", "dead")
    return Measure(4, "Provider returns 429s, then one permanent failure", "must",
                   passed=retried and visible, llm_calls=len(calls),
                   notes=f"final state {s.state}; {len(transient)} transient errors seen; retried after 429: {retried}; "
                         f"permanent failure visible as failed/dead: {visible}")


def s5_pause_edit_resume(bench: Bench) -> Measure:
    a = bench.adapter
    run = a.start_check(TENDER, "Tenderer_B")
    assert bench.wait_state(run, "paused", timeout=30), "the run never paused for the rubric"
    a.edit_rubric(TENDER, {"requires_date": True})     # the fake certificate is signed but not dated
    a.confirm_rubric(TENDER)
    bench.wait_state(run, "done", timeout=20)
    res = a.results(run)
    picked_up = res is not None and res.verdict["outcome"] == "disqualified" and "not dated" in res.verdict["reasons"]
    return Measure(5, "Pause for rubric confirmation; edit the rubric while paused; resume", "must",
                   passed=picked_up, llm_calls=len(bench.calls()),
                   notes="verdict reflects the edit made while paused" if picked_up else "edit was not seen")


def s6_new_version_recheck(bench: Bench, vendors: int = 10) -> Measure:
    a = bench.adapter
    runs = [a.start_check(TENDER, f"Tenderer_{i:02d}") for i in range(vendors)]
    a.confirm_rubric(TENDER)
    assert bench.wait(lambda: all(a.status(r).state == "done" for r in runs), timeout=90)
    before = len(bench.calls())
    version = a.publish_rubric_version(TENDER, {"requires_date": True})
    after = len(bench.calls())
    rechecked = all((a.results(r).rubric_version == version and a.results(r).verdict["outcome"] == "disqualified")
                    for r in runs)
    return Measure(6, "Rubric edited after confirming: new version, re-check every vendor", "must",
                   passed=rechecked and after == before, llm_calls=after - before,
                   notes=f"{vendors} vendors re-checked to v{version} with {after - before} LLM calls")


def s7_correction(bench: Bench) -> Measure:
    a = bench.adapter
    run = a.start_check(TENDER, "Tenderer_B")
    a.confirm_rubric(TENDER)
    assert bench.wait_state(run, "done", timeout=30)
    a.publish_rubric_version(TENDER, {"requires_date": True})   # now disqualified: not dated
    before = len(bench.calls())
    res = a.correct_field(run, "l", "dated", True, "date is on the stamp, page 13")
    instant = res.verdict["outcome"] == "pass" and len(bench.calls()) == before
    a.rerun(run)
    assert bench.wait(lambda: a.status(run).state in ("done", "failed", "lost") and a.results(run) is not None, timeout=30)
    again = a.results(run)
    survived = "dated" in again.corrections and again.verdict["outcome"] == "pass"
    return Measure(7, "Reviewer corrects one field", "must", passed=instant and survived, llm_calls=len(bench.calls()),
                   notes=f"verdict updated with 0 calls: {instant}; correction survived a re-run: {survived}")


def s8_rate_limit(bench: Bench, vendors: int = 20, rpm: int = 60) -> Measure:
    a = bench.adapter
    bench.set(FAKE_DELAY="0.05,0.1", LLM_RPM=str(rpm))      # the provider's limit, as a variant would be configured
    runs = [a.start_check(TENDER, f"Tenderer_{i:02d}") for i in range(vendors)]
    a.confirm_rubric(TENDER)
    bench.wait(lambda: all(a.status(r).state in ("done", "failed", "lost") for r in runs), timeout=120)
    times = sorted(c["t"] for c in bench.calls())
    peak = 0
    for i, t in enumerate(times):     # busiest 60-second window
        j = i
        while j < len(times) and times[j] < t + 60:
            j += 1
        peak = max(peak, j - i)
    return Measure(8, f"{vendors} vendors at once under a {rpm}/min provider limit", "should", passed=peak <= rpm,
                   llm_calls=len(times), notes=f"peak {peak} calls in any 60 s window (limit {rpm})")


def s9_add_step_while_paused(bench: Bench, vendors: int = 5) -> Measure:
    a = bench.adapter
    runs = [a.start_check(TENDER, f"Tenderer_{i:02d}") for i in range(vendors)]
    assert bench.wait(lambda: all(a.status(r).state == "paused" for r in runs), timeout=60)
    bench.set(SLICE_EXTRA_STEP="1")             # "deploy" a pipeline with one more step
    a.confirm_rubric(TENDER)
    resumed = bench.wait(lambda: all(a.status(r).state == "done" for r in runs), timeout=60)
    new_step_applied = all(a.results(r) and a.results(r).fields.get("extra_step") for r in runs)
    return Measure(9, "Add a pipeline step while 5 jobs are paused mid-way", "should", passed=resumed,
                   notes=f"paused runs finished: {resumed}; the new step ran for them: {new_step_applied}")


def s10_whats_stuck(bench: Bench) -> Measure:
    """After a kill, how soon does one call list the run as stuck, with why and since,
    and does the orchestrator then recover it on its own? Either answer passes: a run
    that is healed before anyone asks is not stuck; a run that is listed can be acted on."""
    a = bench.adapter
    run = a.start_check(TENDER, "Tenderer_B")
    assert bench.wait_step_progress(run, "triage", 6)
    holder = a.status(run).worker_pid
    os.kill(holder if holder and holder in a.workers() else a.workers()[0], signal.SIGKILL)
    killed = time.time()
    detected: float | None = None
    while time.time() - killed < 8 and detected is None:
        if any(s["run_id"] == run and s.get("why") and s.get("since") for s in a.list_stuck()):
            detected = round(time.time() - killed, 2)
        time.sleep(0.25)
    a.confirm_rubric(TENDER)
    recovered = bench.wait_state(run, "done", timeout=20)
    return Measure(10, "Which vendors are stuck, why, since when", "should", passed=detected is not None or recovered,
                   recover_seconds=round(time.time() - killed, 2) if recovered else None,
                   notes=(f"listed as stuck {detected} s after the kill, with why and since" if detected is not None
                          else "never listed as stuck within 8 s") + f"; recovered without help: {recovered}")


def s11_glue_code(bench: Bench) -> Measure:
    files = [Path(f) for f in getattr(bench.adapter, "glue_files", [inspect.getsourcefile(inspect.getmodule(type(bench.adapter)))])]
    counts = {f.name: sum(1 for ln in f.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#"))
              for f in files}
    services = getattr(bench.adapter, "services", "Postgres")
    return Measure(11, "Glue code and infrastructure outside the pipeline steps", "compare", passed=None,
                   notes=f"{sum(counts.values())} non-blank lines in {', '.join(f'{k} ({v})' for k, v in counts.items())}; "
                         f"extra services: {services}")


def s12_step_alone(bench: Bench) -> Measure:
    from test.jobs import slice as sl
    llm = sl.make_llm(cert_page=3, delay=None)
    labels = sl.triage(sl.make_vendor("solo", 8, 3)["pages"], "solo", llm, lambda *_: None)
    ok = len(labels) == 8 and llm.count() == 2
    return Measure(12, "Testing one step on its own, without the orchestrator", "compare", passed=ok,
                   llm_calls=llm.count(), notes="triage ran alone on 8 pages in 2 calls" if ok else "step is not callable alone")


SCENARIOS = {1: s1_kill, 2: s2_sigterm, 3: s3_two_api_copies, 4: s4_provider_errors, 5: s5_pause_edit_resume,
             6: s6_new_version_recheck, 7: s7_correction, 8: s8_rate_limit, 9: s9_add_step_while_paused,
             10: s10_whats_stuck, 11: s11_glue_code, 12: s12_step_alone}


def run_scenario(adapter: Orchestrator, number: int, log_dir: Path) -> Measure:
    bench = Bench(adapter, log_dir)
    try:
        return SCENARIOS[number](bench)
    finally:
        adapter.shutdown()


def markdown_table(results: list[Measure], adapter_name: str) -> str:
    rows = ["| # | Scenario | Gate | Result | Lost | Repeated LLM calls | Duplicates | LLM calls | Recover (s) | Notes |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for m in results:
        result = "-" if m.passed is None else ("pass" if m.passed else "FAIL")
        rows.append(f"| {m.scenario} | {m.title} | {m.gate} | {result} | {m.lost_jobs} | {m.repeated_llm_calls} | "
                    f"{m.duplicates} | {m.llm_calls} | {'' if m.recover_seconds is None else m.recover_seconds} | {m.notes} |")
    return f"### Orchestrator: {adapter_name}\n\n" + "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("adapter", choices=["reference", "langgraph", "queue", "app"])
    parser.add_argument("--out", default="output/orchestrator")
    parser.add_argument("--only", type=int, nargs="*", help="scenario numbers")
    args = parser.parse_args(argv)
    adapter = load(args.adapter)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log_dir = Path(tempfile.mkdtemp(prefix="harness-"))
    results = []
    for number in args.only or sorted(SCENARIOS):
        m = run_scenario(adapter, number, log_dir)
        results.append(m)
        print(f"{m.scenario:2d} {'-' if m.passed is None else ('pass' if m.passed else 'FAIL'):4s} {m.title}: {m.notes}")
    (out / f"{args.adapter}.json").write_text(json.dumps([asdict(m) for m in results], indent=2) + "\n")
    (out / f"{args.adapter}.md").write_text(markdown_table(results, args.adapter))
    print(f"wrote {out / (args.adapter + '.json')} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
