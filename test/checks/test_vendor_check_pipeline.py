"""The whole vendor check for item (l) on the synthetic case, through the runner's
executor with an in-memory context: rendering, triage, resolve, extract, the pause for
the rule set, and the engine's verdict. Four model calls for a 16-page scanned offer."""
import pytest

from app.checks import vendor_check
from app.checks.extract_item_l import PREFIX
from app.jobs.execute import run_pipeline
from test.checks.conftest import PID, RULESET, fake_llm
from test.jobs.memory_context import MemoryContext


def run_for(tenderer: str, monkeypatch, **fake_kw):
    llm = fake_llm(tenderer, **fake_kw)
    monkeypatch.setattr(vendor_check, "LLM_FACTORY", lambda pdir, project, tenderer: llm)
    ctx = MemoryContext(run={"run_id": "r1", "project": PID, "tenderer": tenderer, "kind": "vendor_check"})
    return llm, ctx


def test_a_scanned_offer_is_checked_end_to_end_with_four_calls(project, monkeypatch):
    llm, ctx = run_for("Tenderer_B", monkeypatch)
    out = run_pipeline(vendor_check.PIPELINE, ctx)
    assert out.state == "paused" and out.reason == "ruleset_confirmed"
    assert ctx.done == ["render", "triage", "resolve", "extract"]
    assert len(ctx.data["pages"]) == 16 and ctx.data["next_batch"] == 16
    assert ctx.data["item_pages"]["pages"] == [13]
    assert llm.count(out_model=vendor_check.v1.PageLabels) == 3 and llm.count() == 4
    checkpoints = [e for e in ctx.events if e[0] == "checkpoint"]
    assert len(checkpoints) == 3, "one checkpoint per triage batch"
    ctx.confirm(RULESET)
    assert run_pipeline(vendor_check.PIPELINE, ctx).state == "done" and llm.count() == 4
    verdict = vendor_check.PIPELINE.decide(ctx.data["fields"], RULESET)
    assert verdict["outcome"] == "pass" and verdict["ruleset_version"] == 1
    assert ctx.data["fields"][f"{PREFIX}.signature_page"]["page"] == 13


def test_an_offer_without_the_certificate_is_disqualified_after_one_resolve_call(project, monkeypatch):
    llm, ctx = run_for("Tenderer_C", monkeypatch)
    ctx.confirm(RULESET)
    assert run_pipeline(vendor_check.PIPELINE, ctx).state == "done"
    assert ctx.data["item_pages"]["pages"] == [] and llm.count() == 2 + 1, "two triage calls for 12 pages, one resolve"
    verdict = vendor_check.PIPELINE.decide(ctx.data["fields"], RULESET)
    assert verdict["outcome"] == "disqualified" and verdict["fields"][0]["value"] is None


def test_the_pipeline_is_registered_for_the_worker():
    from app.jobs import registry
    assert registry.get("vendor_check") is vendor_check.PIPELINE
    assert [s.name for s in vendor_check.PIPELINE.steps] == ["render", "triage", "resolve", "extract", "await_ruleset"]


def test_the_project_data_class_decides_where_the_model_may_be(project):
    assert vendor_check.data_class_of(project) == "synthetic"
    (project / "meta.json").write_text('{"synthetic": false}')
    assert vendor_check.data_class_of(project) == "confidential"


def test_a_missing_offer_folder_fails_loudly(project, monkeypatch):
    _, ctx = run_for("Nobody", monkeypatch)
    with pytest.raises(FileNotFoundError):
        run_pipeline(vendor_check.PIPELINE, ctx)
