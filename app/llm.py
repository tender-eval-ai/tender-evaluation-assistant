"""OpenAI-compatible LLM client: schema-validated JSON chat + page OCR, with
model-fallback chains (primary -> fallbacks on rate limits, outages, bad requests).

Works against GitHub Models (demo) or any local vLLM endpoint (production) unchanged.
"""
from __future__ import annotations

import base64
import json
import sys
from typing import Type, TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from .config import Config

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
    def __init__(self, cfg: Config):
        if not cfg.token:
            raise RuntimeError(
                "No GitHub token found. Set GITHUB_TOKEN (fine-grained PAT with "
                "'Models: read' permission) or run `gh auth login`. See .env.example."
            )
        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.base_url, api_key=cfg.token)
        self.text_chain = [cfg.text_model] + cfg.text_fallbacks
        self.vision_chain = [cfg.vision_model] + cfg.vision_fallbacks

    @staticmethod
    def _params(model: str, messages: list, json_mode: bool) -> dict:
        params: dict = {"model": model, "messages": messages}
        if not _is_reasoning_model(model):
            params["temperature"] = 0
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        return params

    def _complete(self, chain: list[str], messages: list, json_mode: bool = False) -> str:
        """Try each model in the chain until one answers."""
        last_err: OpenAIError | None = None
        for i, model in enumerate(chain):
            try:
                resp = self.client.chat.completions.create(
                    **self._params(model, messages, json_mode))
                return resp.choices[0].message.content or ""
            except OpenAIError as err:
                last_err = err
                nxt = f"; falling back to {chain[i + 1]}" if i + 1 < len(chain) else ""
                print(f"[llm] {model} failed ({err.__class__.__name__}){nxt}", file=sys.stderr)
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
