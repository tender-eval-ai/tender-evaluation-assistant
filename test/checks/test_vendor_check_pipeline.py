"""The whole vendor check on the synthetic case, through the runner's executor with an
in-memory context: rendering, triage, resolve, extract, verify (every form), the pause
for the rule set, and the engine's verdict on every item. Call counts are exact: a
16-page scanned offer with eleven forms costs 3 triage + 3 resolve (the two absent forms and
the contract deposit, which no synthetic bid has) + 11 extract + 11 second reads = 28; a
12-page digital one 2 + 3 + 11 + 0 = 16."""
import pytest

from app.checks import vendor_check
from app.checks.extract_item_l import PREFIX
from app.checks.verify import SecondRead
from app.jobs.execute import run_pipeline
from test.checks import conftest as vendor_check_conftest
from test.checks.conftest import PID, RULESET, RULESET_ALL, fake_llm
from test.jobs.memory_context import MemoryContext


def run_for(tenderer: str, monkeypatch, **fake_kw):
    llm = fake_llm(tenderer, **fake_kw)
    monkeypatch.setattr(vendor_check, "LLM_FACTORY", lambda pdir, project, tenderer: llm)
    ctx = MemoryContext(run={"run_id": "r1", "project": PID, "tenderer": tenderer, "kind": "vendor_check"})
    return llm, ctx


def test_a_scanned_offer_is_checked_end_to_end_with_twenty_eight_calls(project, monkeypatch):
    llm, ctx = run_for("Tenderer_B", monkeypatch)
    out = run_pipeline(vendor_check.PIPELINE, ctx)
    assert out.state == "paused" and out.reason == "ruleset_confirmed"
    assert ctx.done == ["render", "triage", "resolve", "extract", "verify"]
    assert len(ctx.data["pages"]) == 16 and ctx.data["next_batch"] == 16
    assert ctx.data["form_pages"]["noncollusive_certificate"]["pages"] == [13] and ctx.data["form_pages"]["price_schedule"]["pages"] == [3]
    assert ctx.data["form_pages"]["tender_sample_declaration"]["pages"] == [] and ctx.data["form_pages"]["manufacturer_letter"]["pages"] == []
    assert llm.count(out_model=vendor_check.v1.PageLabels) == 3 and llm.count(out_model=vendor_check.resolve_form.__globals__["ItemPages"]) == 3
    assert llm.count(match=r"extract form ") == 11 and llm.count(out_model=SecondRead) == 11 and llm.count() == 28
    checkpoints = [e for e in ctx.events if e[0] == "checkpoint"]
    assert len(checkpoints) == 3 + 2 * len(vendor_check.FORMS), "one per triage batch, one per form extracted, one per form verified"
    assert sorted(ctx.data["extracted"]) == sorted(vendor_check.FORMS) and sorted(ctx.data["verified"]) == sorted(vendor_check.FORMS)
    ctx.confirm(RULESET)
    assert run_pipeline(vendor_check.PIPELINE, ctx).state == "done" and llm.count() == 28
    verdict = vendor_check.PIPELINE.decide(ctx.data["fields"], RULESET)
    assert verdict["ruleset_version"] == 1 and list(verdict["items"]) == ["l"] and verdict["items"]["l"]["outcome"] == "pass"
    fields = ctx.data["fields"]
    assert fields[f"{PREFIX}.signature_page"]["page"] == 13
    assert fields[f"{PREFIX}.signature_verification"]["method"] == "second_read" and fields[f"{PREFIX}.signature_confidence"] == 0.9
    assert fields["price_schedule.unit_price"] == 4.86 and fields["price_schedule.unit_price_verification"]["verified"] is True


def test_a_digital_offer_is_verified_on_its_text_layer_with_sixteen_calls(project, monkeypatch):
    llm, ctx = run_for("Tenderer_A", monkeypatch)
    ctx.confirm(RULESET_ALL)
    assert run_pipeline(vendor_check.PIPELINE, ctx).state == "done"
    assert ctx.data["form_pages"]["noncollusive_certificate"]["pages"] == [10] and llm.count() == 16 + 1, \
        "two triage calls for 12 pages, three resolve calls (the two absent forms, the contract deposit), eleven " \
        "extracts, no second read; " \
        "then one agent step for the absent Part A letter of intent, finished not found"
    assert [e["tool"] for e in ctx.data["agent_trace"]["manufacturer_letter"]] == ["finish"] and ctx.data["agent_done"] == ["manufacturer_letter"]
    fields = ctx.data["fields"]
    assert all(fields[f"{PREFIX}.{n}_verification"]["method"] == "text_layer" and fields[f"{PREFIX}.{n}_confidence"] == 1.0
               for n in ("document", "tenderer_name", "signature", "date"))
    assert fields[f"{PREFIX}.date_quote"] == "14 August 2026"
    assert fields["price_schedule.total_quote"] == "HK$ 3,850,000.00" and fields["compliance_schedule.delivery_days"] == 28
    verdict = vendor_check.PIPELINE.decide(fields, RULESET_ALL)
    assert len(verdict["items"]) == 15 and verdict["stage2"]["outcome"] == "pass"
    assert verdict["items"]["l"]["outcome"] == "pass" and verdict["items"]["b"]["outcome"] == "pass"


def test_a_reading_the_text_layer_contradicts_pauses_for_a_person_not_the_engine(project, monkeypatch):
    monkeypatch.setitem(vendor_check_conftest.DATES, "Tenderer_A", "12 August 2026")   # not what page 10 says
    llm, ctx = run_for("Tenderer_A", monkeypatch)
    ctx.confirm(RULESET)
    assert run_pipeline(vendor_check.PIPELINE, ctx).state == "done"
    verdict = vendor_check.PIPELINE.decide(ctx.data["fields"], RULESET)
    assert verdict["outcome"] == "needs_review" and verdict["items"]["l"]["reasons"] == ["unverified: not on the text layer of page 10"]


def test_an_offer_without_the_certificate_is_disqualified_after_four_resolve_calls(project, monkeypatch):
    llm, ctx = run_for("Tenderer_C", monkeypatch)
    ctx.confirm(RULESET)
    assert run_pipeline(vendor_check.PIPELINE, ctx).state == "done"
    assert ctx.data["form_pages"]["noncollusive_certificate"]["pages"] == []
    assert llm.count() == 2 + 4 + 10 + 1, "two triage calls for 12 pages, four resolve calls (certificate, sample, letter, contract " \
        "deposit), ten " \
        "extracts; then the agent's one look for the absent Part A certificate, finished not found"
    verdict = vendor_check.PIPELINE.decide(ctx.data["fields"], RULESET)
    assert verdict["outcome"] == "disqualified" and verdict["items"]["l"]["fields"][0]["value"] is None
    assert ctx.data["fields"][f"{PREFIX}.document_verification"]["note"] == "no page to check against"


def test_a_retried_extract_step_continues_with_the_forms_not_yet_read(project, monkeypatch):
    llm, ctx = run_for("Tenderer_A", monkeypatch)
    run_pipeline(vendor_check.PIPELINE, ctx)
    before = llm.count()
    ctx.done.remove("extract")                       # as a crash mid-step would leave it
    ctx.data["extracted"] = ["offer_to_be_bound", "price_schedule"]
    ctx.done.remove("verify")
    ctx.data["verified"] = []
    run_pipeline(vendor_check.PIPELINE, ctx)
    assert llm.count(match=r"extract form ") == 11 + 9, "the two forms already read were not read again"
    assert llm.count() == before + 9


def test_the_pipeline_is_registered_for_the_worker():
    from app.jobs import registry
    assert registry.get("vendor_check") is vendor_check.PIPELINE
    assert [s.name for s in vendor_check.PIPELINE.steps] == ["render", "triage", "resolve", "extract", "verify", "await_ruleset", "agent"]


def test_the_project_data_class_decides_where_the_model_may_be(project):
    assert vendor_check.data_class_of(project) == "synthetic"
    (project / "meta.json").write_text('{"synthetic": false}')
    assert vendor_check.data_class_of(project) == "confidential"


def test_a_missing_offer_folder_fails_loudly(project, monkeypatch):
    _, ctx = run_for("Nobody", monkeypatch)
    with pytest.raises(FileNotFoundError):
        run_pipeline(vendor_check.PIPELINE, ctx)
