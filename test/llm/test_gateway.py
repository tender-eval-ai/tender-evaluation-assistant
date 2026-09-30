"""The LLM gateway (app/llm/gateway.py): policy by data class, cache, budget, rate limiter,
typed provider errors, and images through the real client's message shape."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, BadRequestError, InternalServerError, RateLimitError
from pydantic import BaseModel

from app.config import Config
from app.llm.gateway import (BudgetExceeded, DataClassForbidden, EndpointPolicy, Gateway, GatewaySettings, MemoryBudget,
                         MemoryCache, MemoryLimiter, endpoint_class, spacing)
from app.llm.client import LLM, LLMError, is_transient
from app.llm.usage import UsageLedger
from test.fakes import FakeLLM, Rule


class Out(BaseModel):
    ok: bool


def fake(**kw) -> FakeLLM:
    return FakeLLM([Rule(reply=Out(ok=True), out_model=Out)], ocr_text="page text", **kw)


def gateway(backend=None, **kw) -> Gateway:
    kw.setdefault("project", "p")
    kw.setdefault("data_class", "synthetic")
    return Gateway(backend or fake(), **kw)


# ---------------------------------------------------------------- cache

def test_identical_work_is_answered_from_the_cache_and_paid_once():
    llm = fake()
    g = gateway(llm, cache=MemoryCache())
    assert g.chat_json("s", "u", Out) == Out(ok=True)
    assert g.chat_json("s", "u", Out) == Out(ok=True)
    assert llm.count() == 1 and g.stats == {"calls": 1, "cache_hits": 1, "waited_seconds": 0.0, "usd": 0.0}
    assert g.ocr_page(b"png") == "page text" and g.ocr_page(b"png") == "page text"
    assert llm.count(kind="ocr") == 1


def test_the_cache_key_changes_with_prompt_version_images_and_output_shape():
    llm = fake()
    cache = MemoryCache()
    gateway(llm, cache=cache).chat_json("s", "u", Out)
    gateway(llm, cache=cache, settings=GatewaySettings(prompt_version="v2")).chat_json("s", "u", Out)
    gateway(llm, cache=cache).chat_json("s", "u", Out, images=[b"page-1"])
    gateway(llm, cache=cache).chat_json("s", "u", Out, images=[b"page-2"])
    assert llm.count() == 4 and len(cache.data) == 4


# ---------------------------------------------------------------- policy

CLOUD, LOCAL, CLEARED = "https://api.deepseek.com/v1", "http://localhost:11434/v1", "https://aiplatform.googleapis.com/v1"


def test_endpoint_classes():
    assert endpoint_class(LOCAL) == "local" and endpoint_class("http://10.0.0.7:8000/v1") == "local"
    assert endpoint_class(CLOUD) == "cloud"
    assert endpoint_class("http://spark.lan:8000/v1", frozenset({"spark.lan"})) == "local"


@pytest.mark.parametrize("data_class, chain, expected", [
    ("synthetic", ["cloud", "local@" + LOCAL], ["cloud", "local@" + LOCAL]),
    ("redacted_sample", ["cloud", "local@" + LOCAL], ["local@" + LOCAL]),
    ("redacted_sample", ["cloud", "gemini@" + CLEARED], ["gemini@" + CLEARED]),
    ("confidential", ["cloud", "gemini@" + CLEARED, "local@" + LOCAL], ["local@" + LOCAL]),
])
def test_the_chain_is_filtered_by_data_class(data_class, chain, expected):
    policy = EndpointPolicy(cleared_hosts=frozenset({"aiplatform.googleapis.com"}))
    assert policy.filter_chain(chain, default_base_url=CLOUD, data_class=data_class) == expected


def test_confidential_text_never_reaches_a_cloud_only_chain():
    llm = fake()
    g = gateway(llm, data_class="confidential", base_url=CLOUD)
    with pytest.raises(DataClassForbidden) as err:
        g.chat_json("s", "u", Out)
    assert err.value.code == "data_class_forbidden" and err.value.transient is False and llm.count() == 0
    g = gateway(llm, data_class="confidential", base_url=LOCAL)
    assert g.chat_json("s", "u", Out) == Out(ok=True)


# ---------------------------------------------------------------- budget

class BillingBackend:
    """Records a paid DeepSeek call in its ledger on every chat, like app.llm.client.LLM does."""

    text_chain, vision_chain = ["deepseek-chat"], ["deepseek-chat"]

    def __init__(self):
        self.usage = UsageLedger()

    def chat_json(self, system, user, out_model, chain=None, images=None):
        self.usage.record("deepseek-chat", "deepseek-chat", {"prompt_tokens": 1_000_000, "total_tokens": 1_000_000}, 0.1)
        return out_model(ok=True)


def test_the_daily_budget_stops_calls_visibly_and_permanently():
    budget = MemoryBudget()
    g = gateway(BillingBackend(), budget=budget, settings=GatewaySettings(daily_usd=0.5), today=lambda: "2026-09-17")
    g.chat_json("s", "u", Out)                       # $0.44
    assert budget.spent("p", "2026-09-17") == (1, pytest.approx(0.44))
    g.chat_json("s", "u", Out)                       # $0.88 > 0.5, allowed to finish: the check is before a call
    with pytest.raises(BudgetExceeded) as err:
        g.chat_json("s", "u", Out)
    assert err.value.code == "budget_exceeded" and err.value.transient is False
    g2 = gateway(fake(), budget=MemoryBudget(), settings=GatewaySettings(daily_calls=1))
    g2.chat_json("s", "u", Out)
    with pytest.raises(BudgetExceeded, match="1 calls today"):
        g2.chat_json("s", "u", Out)


# ---------------------------------------------------------------- rate limiter

def test_calls_are_spaced_at_the_provider_limit():
    clock = SimpleNamespace(t=100.0)
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        clock.t += s

    limiter = MemoryLimiter(clock=lambda: clock.t, sleep=sleep)
    llm = fake()
    g = gateway(llm, limiter=limiter, settings=GatewaySettings(rpm=60), limiter_key="provider")
    for _ in range(3):
        g.chat_json("s", str(_), Out)
    assert slept == pytest.approx([spacing(60), spacing(60)]) and g.stats["waited_seconds"] == pytest.approx(2 * spacing(60))
    assert spacing(60) == pytest.approx(1.02)
    assert gateway(llm, limiter=limiter).stats["waited_seconds"] == 0.0     # no rpm configured: no limiter


# ---------------------------------------------------------------- typed errors

def _status_error(cls, status):
    request = httpx.Request("POST", "http://x")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_provider_errors_are_typed_for_the_queue():
    assert is_transient(_status_error(RateLimitError, 429)) and is_transient(_status_error(InternalServerError, 503))
    assert is_transient(APITimeoutError(request=httpx.Request("POST", "http://x")))
    assert not is_transient(_status_error(BadRequestError, 400)) and not is_transient(None)
    err = LLMError(["a", "b"], _status_error(RateLimitError, 429))
    assert err.transient and err.status == 429 and "All models in chain failed (a -> b)" in str(err)
    assert isinstance(err, RuntimeError)


def test_images_travel_as_data_urls_on_the_vision_chain():
    cfg = Config(base_url=LOCAL, text_model="text", vision_model="vision")
    llm = LLM(cfg)
    seen = []

    def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])

    llm._clients = {LOCAL: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))}
    assert llm.chat_json("s", "label these", Out, images=[b"\x89PNG-1", b"\x89PNG-2"]) == Out(ok=True)
    call = seen[0]
    assert call["model"] == "vision"
    parts = call["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "label these"}
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
