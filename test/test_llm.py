"""Model-fallback chain, cross-endpoint entries, per-model request params (no network)."""
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError
from pydantic import BaseModel

from app.config import Config
from app.llm import LLM


class Out(BaseModel):
    ok: bool


PRIMARY_URL = "http://primary.test/v1"
LOCAL_URL = "http://ollama.test/v1"


class RecordingClients(dict):
    """Stands in for LLM._clients: serves a fake client for every base_url and
    records (model, url) per call; models in fail_models raise a retryable error."""

    def __init__(self, calls: list, fail_models: set[str], content: str):
        super().__init__()
        self.calls, self.fail_models, self.content = calls, fail_models, content

    def __contains__(self, key):
        return True

    def __getitem__(self, url):
        def create(**kwargs):
            self.calls.append((kwargs["model"], url, kwargs))
            if kwargs["model"] in self.fail_models:
                raise APIConnectionError(request=httpx.Request("POST", url))
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.content))])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def make_llm(fail_models: set[str], content: str = '{"ok": true}', **cfg_overrides):
    defaults = dict(token="test-token", base_url=PRIMARY_URL,
                    text_model="openai/primary", text_fallbacks=["openai/fb1", "openai/fb2"],
                    vision_model="openai/vision", vision_fallbacks=["openai/vfb"])
    cfg = Config(**{**defaults, **cfg_overrides})
    llm = LLM(cfg)
    calls: list = []
    llm._clients = RecordingClients(calls, fail_models, content)
    return llm, calls


def test_primary_used_when_healthy():
    llm, calls = make_llm(fail_models=set())
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    assert [(m, u) for m, u, _ in calls] == [("openai/primary", PRIMARY_URL)]


def test_falls_back_in_order():
    llm, calls = make_llm(fail_models={"openai/primary", "openai/fb1"})
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    assert [m for m, _, _ in calls] == ["openai/primary", "openai/fb1", "openai/fb2"]


def test_all_models_failing_raises():
    llm, _ = make_llm(fail_models={"openai/primary", "openai/fb1", "openai/fb2"})
    with pytest.raises(RuntimeError, match="All models in chain failed"):
        llm.chat_json("sys", "user", Out)


def test_cross_endpoint_fallback():
    # Cloud primary fails -> the @url fallback is tried on its own endpoint.
    llm, calls = make_llm(
        fail_models={"cloud-model"},
        text_model="cloud-model", text_fallbacks=[f"local-model@{LOCAL_URL}"])
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    assert [(m, u) for m, u, _ in calls] == [
        ("cloud-model", PRIMARY_URL), ("local-model", LOCAL_URL)]


def test_split_entry():
    llm, _ = make_llm(set())
    assert llm._split("qwen3:8b") == ("qwen3:8b", PRIMARY_URL)
    assert llm._split(f"qwen3:8b@{LOCAL_URL}") == ("qwen3:8b", LOCAL_URL)


def test_ocr_uses_vision_chain():
    llm, calls = make_llm(fail_models={"openai/vision"}, content="page text")
    assert llm.ocr_page(b"\x89PNG") == "page text"
    assert [m for m, _, _ in calls] == ["openai/vision", "openai/vfb"]


def test_reasoning_models_get_no_temperature():
    # o-series models reject the temperature parameter; others pin temperature=0.
    assert "temperature" not in LLM._params("openai/o3", [], json_mode=True)
    assert LLM._params("openai/gpt-4.1", [], json_mode=True)["temperature"] == 0
    assert LLM._params("openai/gpt-4.1", [], json_mode=True)["response_format"] == {"type": "json_object"}
    assert "response_format" not in LLM._params("openai/gpt-4.1", [], json_mode=False)


def test_request_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "1800")
    cfg = Config(token="unused")
    assert cfg.request_timeout == 1800.0
    client = LLM(cfg)._client("http://ollama.test/v1")
    assert client.timeout == 1800.0
