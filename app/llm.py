"""OpenAI-compatible LLM client: schema-validated JSON chat + page OCR, with
model-fallback chains (primary -> fallbacks on rate limits, outages, bad requests).

Works against GitHub Models (demo) or any local vLLM endpoint (production) unchanged.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from typing import Type, TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from .config import Config
from .gcp import ADCToken, is_vertex
from .usage import UsageLedger, load_prices

T = TypeVar("T", bound=BaseModel)

OCR_SYSTEM = (
    "You transcribe scanned tender/procurement document pages. Output the page content "
    "as GitHub-flavored Markdown. Preserve tables as Markdown tables and keep numbers, "
    "units and clause references exactly as printed. Do not translate, summarize or "
    "invent content. Represent blacked-out/redacted regions as [REDACTED]. If the page "
    "is blank output only: (blank page)"
)


def _is_reasoning_model(model: str) -> bool:
    """o-series models (o1/o3/o4-...) reject the temperature parameter."""
    return model.split("/")[-1].startswith("o")


class LLM:
    """Chain entries are "model" (served from cfg.base_url) or "model@base_url" —
    the @ form lets a fallback live on a different endpoint entirely, e.g. a cloud
    primary with a local Ollama/vLLM safety net. Every call is recorded in `usage`
    (tokens, seconds, USD) under the current scope — see `scope()`."""

    def __init__(self, cfg: Config, token_provider: ADCToken | None = None):
        # Local OpenAI-compatible servers (Ollama, vLLM) need no real key; hosted
        # endpoints like GitHub Models do.
        if not cfg.token and "github" in cfg.base_url:
            raise RuntimeError(
                "No GitHub token found. Set GITHUB_TOKEN (fine-grained PAT with "
                "'Models: read' permission) or run `gh auth login`. See .env.example."
            )
        self.cfg = cfg
        self._clients: dict[str, OpenAI] = {}
        self.text_chain = [cfg.text_model] + cfg.text_fallbacks
        self.vision_chain = [cfg.vision_model] + cfg.vision_fallbacks
        self._adc = token_provider          # built on first Vertex call
        self.usage = UsageLedger(load_prices(getattr(cfg, "model_prices_json", None)))

    def scope(self, name: str):
        """Context manager attributing the calls made inside it (this thread) to
        `name` — one bid, or "rubric"."""
        return self.usage.scoped(name)

    def _split(self, entry: str) -> tuple[str, str]:
        model, _, url = entry.partition("@")
        return model, (url or self.cfg.base_url)

    def _client(self, base_url: str) -> OpenAI:
        if base_url not in self._clients:
            self._clients[base_url] = OpenAI(
                base_url=base_url, api_key=self.cfg.key_for(base_url) or "local",
                timeout=getattr(self.cfg, "request_timeout", 600.0))
        client = self._clients[base_url]
        if is_vertex(base_url):
            # OAuth bearer token, refreshed ahead of expiry (thread-safe provider).
            if self._adc is None:
                self._adc = ADCToken()
            client.api_key = self._adc.token()
        return client

    @staticmethod
    def _params(model: str, messages: list, json_mode: bool) -> dict:
        params: dict = {"model": model, "messages": messages}
        if not _is_reasoning_model(model):
            params["temperature"] = 0
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        return params

    def _complete(self, chain: list[str], messages: list, json_mode: bool = False) -> str:
        """Try each chain entry (model, endpoint) until one answers."""
        last_err: OpenAIError | None = None
        for i, entry in enumerate(chain):
            model, base_url = self._split(entry)
            t0 = time.time()
            try:
                resp = self._client(base_url).chat.completions.create(
                    **self._params(model, messages, json_mode))
            except OpenAIError as err:
                last_err = err
                self.usage.fail(entry, f"{err.__class__.__name__}: {err}")
                nxt = f"; falling back to {chain[i + 1]}" if i + 1 < len(chain) else ""
                print(f"[llm] {entry} failed ({err.__class__.__name__}){nxt}", file=sys.stderr)
                continue
            self.usage.record(entry, getattr(resp, "model", None), getattr(resp, "usage", None),
                              time.time() - t0)
            return resp.choices[0].message.content or ""
        raise RuntimeError(f"All models in chain failed ({' -> '.join(chain)}): {last_err}")

    # ---------------------------------------------------------------- JSON extraction
    def chat_json(self, system: str, user: str, out_model: Type[T],
                  chain: list[str] | None = None) -> T:
        """Chat with JSON-mode output, validated against `out_model`; one retry with
        the validation error fed back to the model."""
        chain = chain or self.text_chain
        schema = json.dumps(out_model.model_json_schema(), ensure_ascii=False)
        system = f"{system}\n\nRespond with a single JSON object matching this JSON Schema:\n{schema}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_err: Exception | None = None
        for _ in range(2):
            content = self._complete(chain, messages, json_mode=True)
            try:
                return out_model.model_validate_json(content)
            except ValidationError as err:
                last_err = err
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": f"Your JSON did not validate:\n{err}\nReturn a corrected JSON object only.",
                })
        raise RuntimeError(f"LLM output failed schema validation after retry: {last_err}")

    # ---------------------------------------------------------------- vision OCR
    def ocr_page(self, png_bytes: bytes, chain: list[str] | None = None) -> str:
        b64 = base64.b64encode(png_bytes).decode()
        messages = [
            {"role": "system", "content": OCR_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Transcribe this page."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]},
        ]
        return self._complete(chain or self.vision_chain, messages)
