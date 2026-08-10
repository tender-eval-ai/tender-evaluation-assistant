"""Environment / model configuration.

Demo backend: any OpenAI-compatible endpoint — DeepSeek cloud, local Ollama, or a mix
via fallback chains. Production backend: local vLLM serving Qwen3.6 / Qwen3-VL /
DeepSeek — same client, different BASE_URL and model names.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://models.github.ai/inference"
DEFAULT_TEXT_MODEL = "openai/gpt-4o-mini"
DEFAULT_VISION_MODEL = "openai/gpt-4.1"
DEFAULT_FALLBACKS = "openai/o3,openai/gpt-4.1-mini"


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


def github_token() -> str | None:
    """GITHUB_TOKEN env var, falling back to the gh CLI's stored token."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")
    if token:
        return token
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


@dataclass
class Config:
    base_url: str = field(default_factory=lambda: os.environ.get("GITHUB_MODELS_BASE_URL", DEFAULT_BASE_URL))
    token: str | None = field(default_factory=github_token)
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
    max_doc_chars: int = 15000
    max_total_chars: int = 45000
    # Adversarial re-check of negative findings (set VERIFY_FINDINGS=0 to disable).
    verify_findings: bool = field(
        default_factory=lambda: os.environ.get("VERIFY_FINDINGS", "1").lower()
        not in ("0", "false", "no"))

    def key_for(self, base_url: str) -> str | None:
        """API key for an endpoint, selected by hostname — lets fallback-chain entries
        span providers with different credentials. Local servers (Ollama, vLLM) accept
        any non-empty placeholder."""
        for marker, env_var in (("deepseek", "DEEPSEEK_API_KEY"),
                                ("googleapis", "GEMINI_API_KEY"),
                                ("dashscope", "DASHSCOPE_API_KEY"),
                                ("bigmodel", "ZHIPU_API_KEY")):
            if marker in base_url:
                return os.environ.get(env_var)
        return self.token or "local"
