"""Model-fallback chain and per-model request parameters (no network)."""
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError
from pydantic import BaseModel

from app.config import Config
from app.llm import LLM


class Out(BaseModel):
    ok: bool


def make_llm(fail_models: set[str], content: str = '{"ok": true}'):
    cfg = Config(
        token="test-token",
        text_model="openai/primary", text_fallbacks=["openai/fb1", "openai/fb2"],
        vision_model="openai/vision", vision_fallbacks=["openai/vfb"],
    )
    llm = LLM(cfg)
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] in fail_models:
            raise APIConnectionError(request=httpx.Request("POST", "http://test"))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return llm, calls


def test_primary_used_when_healthy():
    llm, calls = make_llm(fail_models=set())
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    assert [c["model"] for c in calls] == ["openai/primary"]


def test_falls_back_in_order():
    llm, calls = make_llm(fail_models={"openai/primary", "openai/fb1"})
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    assert [c["model"] for c in calls] == ["openai/primary", "openai/fb1", "openai/fb2"]


def test_all_models_failing_raises():
    llm, _ = make_llm(fail_models={"openai/primary", "openai/fb1", "openai/fb2"})
    with pytest.raises(RuntimeError, match="All models in chain failed"):
        llm.chat_json("sys", "user", Out)


def test_ocr_uses_vision_chain():
    llm, calls = make_llm(fail_models={"openai/vision"}, content="page text")
    assert llm.ocr_page(b"\x89PNG") == "page text"
    assert [c["model"] for c in calls] == ["openai/vision", "openai/vfb"]


def test_reasoning_models_get_no_temperature():
    # o-series models reject the temperature parameter; others pin temperature=0.
    assert "temperature" not in LLM._params("openai/o3", [], json_mode=True)
    assert LLM._params("openai/gpt-4.1", [], json_mode=True)["temperature"] == 0
    assert LLM._params("openai/gpt-4.1", [], json_mode=True)["response_format"] == {"type": "json_object"}
    assert "response_format" not in LLM._params("openai/gpt-4.1", [], json_mode=False)
