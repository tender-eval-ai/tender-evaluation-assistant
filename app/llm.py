"""OpenAI-compatible LLM client: schema-validated JSON chat + page OCR, with
model-fallback chains (primary -> fallbacks on rate limits, outages, bad requests).

Works unchanged against any OpenAI-compatible endpoint: DeepSeek or Gemini on Vertex AI
(demo, synthetic documents only), local Ollama (demo), vLLM on the client's hardware.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from typing import Type, TypeVar

from openai import APIConnectionError, APIStatusError, BadRequestError, OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from .config import Config
from .gcp import ADCToken, is_vertex
from .usage import UsageLedger, load_prices

T = TypeVar("T", bound=BaseModel)

# Status codes a provider returns when trying again later may succeed. Everything else
# (400 bad request, 401/403 credentials, 404, 422) is the caller's problem.
TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def is_transient(err: BaseException | None) -> bool:
    """Whether a provider error is worth retrying: no answer at all (connection,
    timeout) or a status in TRANSIENT_STATUSES."""
    if isinstance(err, APIStatusError):
        return err.status_code in TRANSIENT_STATUSES
    return isinstance(err, APIConnectionError)


class LLMError(RuntimeError):
    """Every entry of a chain failed. `transient` is what the job queue reads to decide
    between retrying and failing the run; `last` is the last provider error."""

    def __init__(self, chain: list[str], last: BaseException | None):
        super().__init__(f"All models in chain failed ({' -> '.join(chain)}): {last}")
        self.chain, self.last = chain, last
        self.transient = is_transient(last)
        self.status = getattr(last, "status_code", None)

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


_CJK = re.compile(r"[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]")


def estimate_tokens(messages: list) -> int:
    """Approximate prompt size from the text parts (images excluded): about one
    token per CJK character, about 3.5 characters per token for everything else.
    Used only for the context-window guard, where a rough number is enough to catch
    the failure that matters — a prompt several times larger than the window."""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            texts = [content]
        else:
            texts = [part.get("text", "") for part in (content or [])
                     if isinstance(part, dict) and part.get("type") == "text"]
        for text in texts:
            cjk = len(_CJK.findall(text))
            total += cjk + int((len(text) - cjk) / 3.5)
    return total


class LLM:
    """Chain entries are "model" (served from cfg.base_url) or "model@base_url" —
    the @ form lets a fallback live on a different endpoint entirely, e.g. a cloud
    primary with a local Ollama/vLLM safety net. Every call is recorded in `usage`
    (tokens, seconds, USD) under the current scope — see `scope()`."""

    def __init__(self, cfg: Config, token_provider: ADCToken | None = None):
        # Local OpenAI-compatible servers (Ollama, vLLM) need no real key; hosted
        # endpoints do (per-host lookup in Config.key_for).
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

    def _params(self, model: str, messages: list, json_mode: bool,
                schema: dict | None = None) -> dict:
        params: dict = {"model": model, "messages": messages}
        if not _is_reasoning_model(model):
            params["temperature"] = 0
        if json_mode and schema is not None and getattr(self.cfg, "json_schema_mode", False):
            params["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.get("title", "output"), "schema": schema}}
        elif json_mode:
            params["response_format"] = {"type": "json_object"}
        if getattr(self.cfg, "max_tokens", None):
            params["max_tokens"] = self.cfg.max_tokens
        return params

    def _attempt(self, entry: str, messages: list, json_mode: bool, schema: dict | None):
        """One request to one chain entry. A json_schema response_format the endpoint
        rejects (HTTP 400) is retried once as plain json_object — the same request the
        pipeline made before LLM_JSON_SCHEMA existed."""
        model, base_url = self._split(entry)
        client = self._client(base_url)
        try:
            return client.chat.completions.create(**self._params(model, messages, json_mode, schema))
        except BadRequestError:
            if schema is None or not getattr(self.cfg, "json_schema_mode", False):
                raise
            print(f"[llm] {entry} rejected the json_schema response_format; "
                  "retrying as json_object", file=sys.stderr)
            return client.chat.completions.create(**self._params(model, messages, json_mode, None))

    def _guard_context(self, messages: list) -> None:
        limit = getattr(self.cfg, "context_tokens", None)
        if not limit:
            return
        est = estimate_tokens(messages)
        if est > limit:
            raise RuntimeError(
                f"prompt of ~{est} tokens exceeds LLM_CONTEXT_TOKENS={limit}; the server "
                "would truncate it silently. Raise the model's context (Ollama num_ctx, "
                "vLLM --max-model-len).")

    def _complete(self, chain: list[str], messages: list, json_mode: bool = False,
                  schema: dict | None = None) -> str:
        """Try each chain entry (model, endpoint) until one answers."""
        self._guard_context(messages)
        last_err: OpenAIError | None = None
        for i, entry in enumerate(chain):
            t0 = time.time()
            try:
                resp = self._attempt(entry, messages, json_mode, schema)
            except OpenAIError as err:
                last_err = err
                self.usage.fail(entry, f"{err.__class__.__name__}: {err}")
                nxt = f"; falling back to {chain[i + 1]}" if i + 1 < len(chain) else ""
                print(f"[llm] {entry} failed ({err.__class__.__name__}){nxt}", file=sys.stderr)
                continue
            self.usage.record(entry, getattr(resp, "model", None), getattr(resp, "usage", None),
                              time.time() - t0)
            return resp.choices[0].message.content or ""
        raise LLMError(chain, last_err)

    # ---------------------------------------------------------------- JSON extraction
    def chat_json(self, system: str, user: str, out_model: Type[T],
                  chain: list[str] | None = None, images: list[bytes] | None = None) -> T:
        """Chat with JSON-mode output, validated against `out_model`; one retry with
        the validation error fed back to the model. With `images` (PNG bytes) the user
        turn carries them as data URLs and the vision chain is the default."""
        chain = chain or (self.vision_chain if images else self.text_chain)
        schema = out_model.model_json_schema()
        system = (f"{system}\n\nRespond with a single JSON object matching this JSON Schema:\n"
                  f"{json.dumps(schema, ensure_ascii=False)}")
        content: str | list = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(b).decode()}"}}
                for b in images]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        last_err: Exception | None = None
        for _ in range(2):
            content = self._complete(chain, messages, json_mode=True, schema=schema)
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
