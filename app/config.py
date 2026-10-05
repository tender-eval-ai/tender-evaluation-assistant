"""Environment / model configuration.

Demo backend: any OpenAI-compatible endpoint — DeepSeek cloud, local Ollama, or a mix
via fallback chains. Production backend: local vLLM serving Qwen3.6 / Qwen3-VL /
DeepSeek — same client, different BASE_URL and model names.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Defaults = a keyless local Ollama (what .env.example ships); .env overrides. The
# original demo provider (GitHub Models) was retired in 2026-08 and is gone from here.
DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_TEXT_MODEL = "qwen3:8b"
DEFAULT_VISION_MODEL = "qwen3-vl:8b"
DEFAULT_FALLBACKS = ""
# The step budget of V5, the check's bounded form search (per missing Part A form;
# docs/api_contract.md). AGENT_MAX_STEPS overrides it.
DEFAULT_AGENT_STEPS = 6


def _model_list(env_var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(env_var, default).split(",") if m.strip()]


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); does not override existing env vars."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    # Historic name (the first demo provider was GitHub Models, retired 2026-08); it is
    # simply "the base URL for unqualified model names".
    base_url: str = field(default_factory=lambda: os.environ.get("GITHUB_MODELS_BASE_URL", DEFAULT_BASE_URL))
    text_model: str = field(default_factory=lambda: os.environ.get("TEXT_MODEL", DEFAULT_TEXT_MODEL))
    vision_model: str = field(default_factory=lambda: os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL))
    # Tried in order when the model before them fails (rate limit, outage, bad request).
    text_fallbacks: list[str] = field(
        default_factory=lambda: _model_list("TEXT_MODEL_FALLBACKS", DEFAULT_FALLBACKS))
    vision_fallbacks: list[str] = field(
        default_factory=lambda: _model_list("VISION_MODEL_FALLBACKS", DEFAULT_FALLBACKS))
    cache_dir: Path = Path("cache")
    # Free-tier friendliness: cap how much of each document is OCR'd / prompted.
    max_ocr_pages: int = 8

    # Per-request timeout for model calls. The OpenAI client's default (600 s) is
    # plenty for cloud endpoints; a local vision model under load (several bids in
    # parallel on one GPU) can legitimately take longer per page.
    request_timeout: float = field(
        default_factory=lambda: float(os.environ.get("LLM_TIMEOUT_S", "600")))
    # Cap on generated tokens per call (LLM_MAX_TOKENS; unset = provider default). The
    # pipeline's JSON outputs are small; the cap exists because a local 8B model in
    # JSON mode was seen generating 14k tokens without stopping. Thinking models count
    # their reasoning against it, so keep it generous (4096+) if set.
    max_tokens: int | None = field(
        default_factory=lambda: int(os.environ["LLM_MAX_TOKENS"]) if os.environ.get("LLM_MAX_TOKENS") else None)
    # How hard a reasoning model thinks (LLM_REASONING_EFFORT: minimal, low, medium, high;
    # unset = the provider's default). Sent to reasoning models only.
    reasoning_effort: str | None = field(default_factory=lambda: os.environ.get("LLM_REASONING_EFFORT") or None)
    # Structured output as a server-enforced grammar: LLM_JSON_SCHEMA=1 sends the
    # Pydantic schema as response_format={"type": "json_schema"} (vLLM guided decoding,
    # Ollama structured outputs, Gemini) — the model then cannot emit a malformed object
    # or run away. Endpoints that reject it (DeepSeek) fall back to json_object.
    json_schema_mode: bool = field(
        default_factory=lambda: os.environ.get("LLM_JSON_SCHEMA", "0").lower() in ("1", "true", "yes"))
    # The server's context window in tokens (Ollama num_ctx, vLLM --max-model-len).
    # When set, a prompt estimated above it is refused with a clear error instead of
    # being truncated silently (what Ollama does by default — wrong answers, no signal).
    context_tokens: int | None = field(
        default_factory=lambda: int(os.environ["LLM_CONTEXT_TOKENS"]) if os.environ.get("LLM_CONTEXT_TOKENS") else None)
    # USD per 1M tokens, overriding app.llm.usage.DEFAULT_PRICES: MODEL_PRICES='{"m": {"in":
    # 0.3, "out": 2.5, "cached_in": 0.01}}'. Recorded next to every published cost.
    model_prices_json: str | None = field(default_factory=lambda: os.environ.get("MODEL_PRICES"))

    def key_for(self, base_url: str) -> str | None:
        """API key for an endpoint, selected by hostname — lets fallback-chain entries
        span providers with different credentials. Vertex AI (aiplatform.googleapis.com)
        takes no key at all: the client fetches OAuth tokens through app.llm.gcp.ADCToken —
        so it must not fall through to the GEMINI_API_KEY (AI Studio) rule below. Any
        other host — local Ollama, the client's vLLM — gets a non-empty placeholder and
        never a real credential."""
        if "aiplatform.googleapis.com" in base_url:
            return None
        for marker, env_var in (("openai.azure.com", "AZURE_OPENAI_API_KEY"),
                                ("cognitiveservices.azure.com", "AZURE_OPENAI_API_KEY"),
                                ("deepseek", "DEEPSEEK_API_KEY"),
                                ("googleapis", "GEMINI_API_KEY"),
                                ("dashscope", "DASHSCOPE_API_KEY"),
                                ("bigmodel", "ZHIPU_API_KEY")):
            if marker in base_url:
                return os.environ.get(env_var)
        return "local"
