"""Model-fallback chain, cross-endpoint entries, per-model request params (no network)."""
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, BadRequestError
from pydantic import BaseModel

from app.config import Config
from app.llm.client import LLM, estimate_tokens


class Out(BaseModel):
    ok: bool


PRIMARY_URL = "http://primary.test/v1"
LOCAL_URL = "http://ollama.test/v1"


class RecordingClients(dict):
    """Stands in for LLM._clients: serves a fake client for every base_url and
    records (model, url) per call; models in fail_models raise a retryable error."""

    def __init__(self, calls: list, fail_models: set[str], content: str,
                 reject_schema: bool = False):
        super().__init__()
        self.calls, self.fail_models, self.content = calls, fail_models, content
        self.reject_schema = reject_schema      # endpoint without json_schema support

    def __contains__(self, key):
        return True

    def __getitem__(self, url):
        def create(**kwargs):
            self.calls.append((kwargs["model"], url, kwargs))
            if kwargs["model"] in self.fail_models:
                raise APIConnectionError(request=httpx.Request("POST", url))
            if self.reject_schema and kwargs.get("response_format", {}).get("type") == "json_schema":
                request = httpx.Request("POST", url)
                raise BadRequestError("response_format json_schema is not supported",
                                      response=httpx.Response(400, request=request), body=None)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.content))])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def make_llm(fail_models: set[str], content: str = '{"ok": true}', reject_schema: bool = False,
             **cfg_overrides):
    defaults = dict(base_url=PRIMARY_URL,
                    text_model="openai/primary", text_fallbacks=["openai/fb1", "openai/fb2"],
                    vision_model="openai/vision", vision_fallbacks=["openai/vfb"])
    cfg = Config(**{**defaults, **cfg_overrides})
    llm = LLM(cfg)
    calls: list = []
    llm._clients = RecordingClients(calls, fail_models, content, reject_schema)
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
    params = LLM(Config())._params
    assert "temperature" not in params("openai/o3", [], json_mode=True)
    assert params("openai/gpt-4.1", [], json_mode=True)["temperature"] == 0
    assert params("openai/gpt-4.1", [], json_mode=True)["response_format"] == {"type": "json_object"}
    assert "response_format" not in params("openai/gpt-4.1", [], json_mode=False)


def test_request_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "1800")
    cfg = Config()
    assert cfg.request_timeout == 1800.0
    client = LLM(cfg)._client("http://ollama.test/v1")
    assert client.timeout == 1800.0


def test_max_tokens_cap_is_optional(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    llm = LLM(Config())
    assert "max_tokens" not in llm._params("m", [], True)
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    llm = LLM(Config())
    assert llm._params("m", [], True)["max_tokens"] == 4096


def test_json_schema_mode_sends_the_pydantic_schema(monkeypatch):
    """LLM_JSON_SCHEMA=1: the response_format carries the output model's schema, so a
    server with guided decoding (vLLM, Ollama, Gemini) enforces it as a grammar."""
    monkeypatch.setenv("LLM_JSON_SCHEMA", "1")
    llm, calls = make_llm(set())
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    fmt = calls[0][2]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Out"
    assert fmt["json_schema"]["schema"]["properties"]["ok"]["type"] == "boolean"
    # OCR (no schema) is unaffected.
    llm.ocr_page(b"\x89PNG")
    assert "response_format" not in calls[-1][2]


def test_json_schema_rejected_by_endpoint_falls_back_to_json_object(monkeypatch):
    """An endpoint without json_schema support (DeepSeek) answers 400: the same model
    is retried once as json_object instead of falling through the chain."""
    monkeypatch.setenv("LLM_JSON_SCHEMA", "1")
    llm, calls = make_llm(set(), reject_schema=True)
    assert llm.chat_json("sys", "user", Out) == Out(ok=True)
    assert [(m, c["response_format"]["type"]) for m, _, c in calls] == [
        ("openai/primary", "json_schema"), ("openai/primary", "json_object")]


def test_json_object_stays_the_default(monkeypatch):
    monkeypatch.delenv("LLM_JSON_SCHEMA", raising=False)
    llm, calls = make_llm(set())
    llm.chat_json("sys", "user", Out)
    assert calls[0][2]["response_format"] == {"type": "json_object"}


def test_context_guard_refuses_prompts_above_the_window(monkeypatch):
    """LLM_CONTEXT_TOKENS: an oversized prompt is refused before any request — the
    alternative (Ollama's default) is silent truncation and a confidently wrong answer."""
    monkeypatch.setenv("LLM_CONTEXT_TOKENS", "200")
    llm, calls = make_llm(set())
    with pytest.raises(RuntimeError, match="exceeds LLM_CONTEXT_TOKENS=200"):
        llm.chat_json("sys", "word " * 500, Out)
    assert calls == []
    assert llm.chat_json("sys", "short question", Out) == Out(ok=True)


def test_estimate_tokens_counts_text_parts_only():
    assert estimate_tokens([{"role": "user", "content": "投標文件" * 10}]) == 40
    mixed = [{"role": "user", "content": [
        {"type": "text", "text": "a" * 35},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    assert estimate_tokens(mixed) == 10


def test_unknown_hosts_only_ever_get_a_placeholder_key(monkeypatch):
    """Provider keys are matched by hostname; Ollama, the client's vLLM or any other
    host gets the placeholder — never a real credential (Vertex: see test_usage)."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-secret")
    cfg = Config()
    assert cfg.key_for("https://api.deepseek.com/v1") == "ds-secret"
    assert cfg.key_for("http://localhost:11434/v1") == "local"
    assert cfg.key_for("http://dgx.internal:8000/v1") == "local"
    assert cfg.key_for("https://models.github.ai/inference") == "local"
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-secret")
    assert cfg.key_for("https://tender-oai-abc123.openai.azure.com/openai/v1") == "az-secret"
    assert cfg.key_for("https://tender-oai-abc123.cognitiveservices.azure.com/openai/v1") == "az-secret"
