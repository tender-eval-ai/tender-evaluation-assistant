"""The FakeLLM answers only what is scripted, counts what it answered, and can fail or
stall on purpose."""
import hashlib
import json
import time

import pytest
from pydantic import BaseModel

from test.fakes import Call, FakeLLM, Rule, UnexpectedCall, read_log


class Label(BaseModel):
    page: int
    label: str


class Answer(BaseModel):
    text: str


def test_rules_match_on_scope_model_prompt_and_image():
    png = b"\x89PNG fake"
    llm = FakeLLM(rules=[
        Rule(reply=Label(page=1, label="price_schedule"), scope="bid-1", out_model=Label, match=r"page 1"),
        Rule(reply=Label(page=2, label="other"), out_model=Label),
        Rule(reply="certificate text", image=hashlib.sha256(png).hexdigest()[:8]),
    ])
    with llm.scope("bid-1"):
        assert llm.chat_json("s", "classify page 1", Label).label == "price_schedule"
        assert llm.chat_json("s", "classify page 9", Label).label == "other"
    assert llm.chat_json("s", "classify page 1", Label).label == "other", "scope rule does not fire outside its scope"
    assert llm.ocr_page(png) == "certificate text"
    assert llm.count(scope="bid-1") == 2 and llm.count(kind="ocr") == 1 and llm.ocr_calls == 1


def test_sequence_answers_in_order_then_unexpected_call_shows_the_prompt():
    llm = FakeLLM(sequence=[Answer(text="first"), Answer(text="second")])
    assert llm.chat_json("s", "q1", Answer).text == "first"
    assert llm.chat_json("s", "q2", Answer).text == "second"
    with pytest.raises(UnexpectedCall, match="q3 with details"):
        llm.chat_json("s", "q3 with details", Answer)
    assert llm.count() == 3 and llm.count(failed=True) == 1 and llm.calls[-1].error.startswith("UnexpectedCall")


def test_json_string_and_dict_replies_are_validated_like_the_real_class():
    llm = FakeLLM(rules=[Rule(reply='{"page": 3, "label": "tender_form"}', match=r"^json"),
                         Rule(reply={"page": 4, "label": "other"}, match=r"^dict"),
                         Rule(reply='{"page": "not a number"}', match=r"^bad")])
    assert llm.chat_json("s", "json please", Label) == Label(page=3, label="tender_form")
    assert llm.chat_json("s", "dict please", Label) == Label(page=4, label="other")
    with pytest.raises(Exception):
        llm.chat_json("s", "bad json", Label)


def test_a_reply_of_the_wrong_model_is_refused():
    llm = FakeLLM(sequence=[Answer(text="x")])
    with pytest.raises(UnexpectedCall, match="asked for Label"):
        llm.chat_json("s", "q", Label)


def test_rules_can_be_consumed_and_can_compute_the_reply():
    llm = FakeLLM(rules=[Rule(reply=Answer(text="once"), times=1),
                         Rule(reply=lambda call: Answer(text=f"call {call.n} in {call.scope}"))])
    assert llm.chat_json("s", "a", Answer).text == "once"
    with llm.scope("rubric"):
        assert llm.chat_json("s", "b", Answer).text == "call 2 in rubric"


def test_faults_by_call_index_and_delay():
    llm = FakeLLM(sequence=[Answer(text="ok")] * 3, faults={2: TimeoutError}, delay=0.01)
    started = time.perf_counter()
    assert llm.chat_json("s", "1", Answer).text == "ok"
    with pytest.raises(TimeoutError):
        llm.chat_json("s", "2", Answer)
    assert llm.chat_json("s", "3", Answer).text == "ok"
    assert time.perf_counter() - started >= 0.03
    assert llm.count(failed=True) == 1 and llm.usage.fallbacks[0]["error"].startswith("TimeoutError")


def test_ocr_text_can_be_a_list_used_in_order():
    llm = FakeLLM(ocr_text=["page one", "page two"])
    assert llm.ocr_page(b"1") == "page one" and llm.ocr_page(b"2") == "page two"
    with pytest.raises(UnexpectedCall, match="no OCR text left"):
        llm.ocr_page(b"3")


def test_usage_ledger_records_per_scope_like_the_real_class():
    llm = FakeLLM(sequence=[Answer(text="a"), Answer(text="b")], ocr_text="t")
    with llm.scope("bid-1"):
        llm.chat_json("s", "q", Answer)
        llm.ocr_page(b"png")
    with llm.scope("bid-2"):
        llm.chat_json("s", "q", Answer)
    assert llm.usage.snapshot("bid-1")["totals"]["calls"] == 2
    assert llm.usage.snapshot("bid-2")["totals"]["calls"] == 1
    assert llm.usage.snapshot("bid-1")["models"]["fake-vision"]["calls"] == 1


def test_log_file_accumulates_calls_from_several_instances(tmp_path):
    log = tmp_path / "calls.jsonl"
    FakeLLM(sequence=[Answer(text="a")], log_path=log).chat_json("s", "first", Answer)
    second = FakeLLM(ocr_text="t", log_path=log)
    with second.scope("bid-7"):
        second.ocr_page(b"png")
    lines = read_log(log)
    assert [(line["kind"], line["scope"]) for line in lines] == [("chat_json", "default"), ("ocr", "bid-7")]
    assert all({"n", "pid", "model", "prompt_sha", "seconds", "error"} <= set(line) for line in lines)
    assert json.loads(log.read_text().splitlines()[0])["out_model"] == "Answer"


def test_call_records_what_was_asked():
    llm = FakeLLM(sequence=[Answer(text="a")])
    with llm.scope("bid-1"):
        llm.chat_json("system text", "user text", Answer, images=[b"img"])
    call: Call = llm.calls[0]
    assert (call.scope, call.out_model, call.system, call.user, call.model) == \
        ("bid-1", "Answer", "system text", "user text", "fake-text")
    assert len(call.images) == 1 and call.reply == Answer(text="a")
