"""LangGraph orchestration (app/graph.py): same outputs as the legacy pipeline,
stored checkpoints skip the LLM, human checkpoints pause/resume, bids fan out."""
import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

import app.graph as graph_mod
from app.config import Config
from app.graph import build_graph, graph_config, initial_state, pending_checkpoint, resume, run_graph
from app.pipeline import run_offline
from app.schemas import BidExtraction, Rubric
from test.conftest import FIXTURES

FIXTURE_RUBRIC = Rubric.model_validate_json((FIXTURES / "rubric.json").read_text())
FIXTURE_BIDS = {e.tenderer: e for e in (BidExtraction.model_validate_json(p.read_text())
                                        for p in sorted((FIXTURES / "bids").glob("*.json")))}


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.cache_dir = tmp_path / "cache"
    cfg.verify_findings = False
    cfg.agent_enabled = False      # LLM steps are stubbed; no model available here
    return cfg


def _bids_dir(tmp_path) -> Path:
    bids = tmp_path / "bids_in"
    for name in FIXTURE_BIDS:
        (bids / name).mkdir(parents=True)
        (bids / name / "offer.pdf").write_bytes(b"%PDF-1.4 stub")
    return bids


@pytest.fixture
def stubs(monkeypatch):
    """Replace every LLM-touching step with fixture-backed fakes; record calls."""
    calls = {"derive": 0, "extract": []}

    def fake_derive(docs, cfg, llm):
        calls["derive"] += 1
        return FIXTURE_RUBRIC.model_copy(deep=True)

    def fake_extract(name, docs, rubric, cfg, llm):
        calls["extract"].append(name)
        return FIXTURE_BIDS[name].model_copy(deep=True)

    monkeypatch.setattr(graph_mod, "load_folder", lambda *a, **k: [])
    monkeypatch.setattr(graph_mod, "load_pdf", lambda *a, **k: None)
    monkeypatch.setattr(graph_mod, "derive_rubric", fake_derive)
    monkeypatch.setattr(graph_mod, "extract_bid", fake_extract)
    return calls


def test_graph_run_from_scratch_matches_legacy(tmp_path, stubs):
    out = tmp_path / "out"
    result = run_graph(tmp_path / "tender", _bids_dir(tmp_path), out, _cfg(tmp_path), None,
                       log=lambda *a: None)
    assert stubs["derive"] == 1
    assert sorted(stubs["extract"]) == sorted(FIXTURE_BIDS)
    assert result.recommended == "Bidder B"
    # Same checkpoint files the legacy pipeline writes, byte-identical evaluation.
    assert (out / "rubric.json").is_file()
    assert sorted(p.stem for p in (out / "bids").glob("*.json")) == sorted(FIXTURE_BIDS)
    legacy = run_offline(FIXTURES, tmp_path / "legacy", log=lambda *a: None)
    assert (out / "evaluation.json").read_text() == (tmp_path / "legacy" / "evaluation.json").read_text()
    assert sorted(p.name for p in (out / "reports").glob("*.docx")) == [
        "evaluation_record.docx", "price_summary.docx", "summary_list.docx"]
    assert legacy.recommended == result.recommended


def test_graph_uses_stored_checkpoints_without_llm(tmp_path, stubs):
    out = tmp_path / "out"
    (out / "bids").mkdir(parents=True)
    (out / "rubric.json").write_text(FIXTURE_RUBRIC.model_dump_json(indent=2))
    for name, ext in FIXTURE_BIDS.items():
        (out / "bids" / f"{name}.json").write_text(ext.model_dump_json(indent=2))
    result = run_graph(tmp_path / "tender", _bids_dir(tmp_path), out, _cfg(tmp_path), None,
                       log=lambda *a: None)
    assert stubs["derive"] == 0 and stubs["extract"] == []   # nothing re-derived/re-extracted
    assert result.recommended == "Bidder B"


def test_graph_partial_checkpoints_extract_only_missing(tmp_path, stubs):
    out = tmp_path / "out"
    (out / "bids").mkdir(parents=True)
    (out / "rubric.json").write_text(FIXTURE_RUBRIC.model_dump_json(indent=2))
    (out / "bids" / "Bidder A.json").write_text(FIXTURE_BIDS["Bidder A"].model_dump_json())
    run_graph(tmp_path / "tender", _bids_dir(tmp_path), out, _cfg(tmp_path), None,
              log=lambda *a: None)
    assert stubs["derive"] == 0
    assert sorted(stubs["extract"]) == sorted(n for n in FIXTURE_BIDS if n != "Bidder A")


def test_graph_human_checkpoints_pause_and_resume(tmp_path, stubs):
    cfg = _cfg(tmp_path)
    out = tmp_path / "out"
    graph = build_graph(cfg, None, checkpointer=MemorySaver(), interactive=True,
                        log=lambda *a: None)
    config = graph_config(cfg, "t1")

    state = graph.invoke(initial_state(tmp_path / "tender", _bids_dir(tmp_path), out), config)
    pause = pending_checkpoint(state)
    assert pause and pause["checkpoint"] == "rubric"
    assert stubs["extract"] == []                      # nothing extracted before confirmation

    edited = {**pause["rubric"], "subject": "EDITED BY HUMAN"}
    state = resume(graph, cfg, "t1", {"rubric": edited})
    pause = pending_checkpoint(state)
    assert pause and pause["checkpoint"] == "review"
    assert sorted(pause["extractions"]) == sorted(FIXTURE_BIDS)
    assert json.loads((out / "rubric.json").read_text())["subject"] == "EDITED BY HUMAN"

    # Human flips Bidder A's first document to missing; correction must win.
    fixed = json.loads(json.dumps(pause["extractions"]["Bidder A"]))
    fixed["documents"][0]["present"] = False
    state = resume(graph, cfg, "t1", {"extractions": {"Bidder A": fixed}})
    assert pending_checkpoint(state) is None
    assert state["corrected"] == ["Bidder A"]
    assert state["evaluation"]["rubric"]["subject"] == "EDITED BY HUMAN"
    stage1_a = next(r for r in state["evaluation"]["stage1"] if r["tenderer"] == "Bidder A")
    assert stage1_a["passed"] is False
    assert json.loads((out / "bids" / "Bidder A.json").read_text())["documents"][0]["present"] is False


def test_graph_resumes_after_node_failure(tmp_path, stubs, monkeypatch):
    """A crash mid fan-out resumes from the checkpoint: successful bids are kept."""
    cfg = _cfg(tmp_path)
    out = tmp_path / "out"
    attempts = {"Bidder C": 0}
    real_extract = graph_mod.extract_bid

    def flaky(name, docs, rubric, c, llm):
        if name == "Bidder C" and attempts["Bidder C"] == 0:
            attempts["Bidder C"] += 1
            raise RuntimeError("endpoint down")
        return real_extract(name, docs, rubric, c, llm)

    monkeypatch.setattr(graph_mod, "extract_bid", flaky)
    graph = build_graph(cfg, None, checkpointer=MemorySaver(), interactive=False,
                        log=lambda *a: None)
    config = graph_config(cfg, "t2")
    with pytest.raises(RuntimeError, match="endpoint down"):
        graph.invoke(initial_state(tmp_path / "tender", _bids_dir(tmp_path), out), config)
    state = graph.invoke(None, config)                 # resume from last checkpoint
    assert sorted(state["extractions"]) == sorted(FIXTURE_BIDS)
    assert state["evaluation"]["recommended"] == "Bidder B"


def test_graph_resume_picks_up_checkpoints_edited_on_disk(tmp_path, stubs):
    """Service mode: the human edits rubric.json / bids/*.json (PUT) while the graph is
    paused, then resumes with an empty payload — the edits must be honoured."""
    cfg = _cfg(tmp_path)
    out = tmp_path / "out"
    graph = build_graph(cfg, None, checkpointer=MemorySaver(), interactive=True,
                        log=lambda *a: None)
    config = graph_config(cfg, "t3")
    state = graph.invoke(initial_state(tmp_path / "tender", _bids_dir(tmp_path), out), config)
    rubric = json.loads((out / "rubric.json").read_text())
    rubric["subject"] = "EDITED ON DISK"
    (out / "rubric.json").write_text(json.dumps(rubric))
    state = resume(graph, cfg, "t3", {})
    assert pending_checkpoint(state)["checkpoint"] == "review"
    fixed = json.loads((out / "bids" / "Bidder A.json").read_text())
    fixed["documents"][0]["present"] = False
    (out / "bids" / "Bidder A.json").write_text(json.dumps(fixed))
    state = resume(graph, cfg, "t3", {})
    assert pending_checkpoint(state) is None
    assert state["corrected"] == ["Bidder A"]
    assert state["evaluation"]["rubric"]["subject"] == "EDITED ON DISK"
    assert not next(r for r in state["evaluation"]["stage1"] if r["tenderer"] == "Bidder A")["passed"]
