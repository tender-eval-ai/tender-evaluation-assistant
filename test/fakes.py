"""FakeLLM: a scripted stand-in for `app.llm.client.LLM`, used by every layer test and by the
orchestrator harness.

Why a fake. A test on the real class costs money, takes seconds per call, needs a key,
gives a different answer each run and cannot run in CI. The fake answers from rules you
script, in milliseconds, offline, identically every time. It also does three things only a
fake can: it counts calls, so "a 60-page scan costs at most 10 triage calls" becomes a
failing test; it injects failures (a 429, a timeout) so retry paths are tested; and it adds
delay so a worker can be killed in the middle of a call.

    llm = FakeLLM(rules=[Rule(reply=BidPrice(unit_price=9.5), out_model=BidPrice)],
                  sequence=[AgentAction(tool="list_pages"), AgentAction(tool="finish")],
                  ocr_text="Non-collusive Tendering Certificate ... signed")
    run_agent(docs, llm=llm)
    assert llm.count(out_model=AgentAction) == 2 and llm.ocr_calls == 0

How a call is answered. Rules are tried in order; a rule matches on any combination of
the active scope name, the requested output model, a regex over the user prompt, and a
hash prefix of an attached image. If no rule matches, the next item of `sequence` is
used. If neither applies, `UnexpectedCall` is raised with the prompt, so a test never
passes on an answer nobody scripted. A reply may be a model instance, a dict, a JSON
string (validated against the output model, like the real class), a callable taking the
`Call`, or an exception to raise.

Counting across processes. When `FAKE_LLM_LOG` (or `log_path`) is set, every call appends
one JSON line to that file, so the harness can count calls made by worker subprocesses.
The fake also feeds the same `UsageLedger` the real class uses, so `scope()` and the
per-scope usage files written by the pipeline behave as in production.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from app.llm.usage import UsageLedger


class UnexpectedCall(AssertionError):
    """No rule and no sequence item answered a call."""


@dataclass
class Call:
    n: int
    kind: str                      # "chat_json" | "ocr"
    scope: str
    out_model: str | None
    system: str
    user: str
    images: list[str]              # sha256 hex of each attached image
    model: str                     # first entry of the chain the caller asked for
    seconds: float = 0.0
    reply: Any = None
    error: str | None = None


@dataclass
class Rule:
    reply: Any
    scope: str | None = None
    out_model: type | None = None
    match: str | re.Pattern | None = None
    image: str | None = None       # sha256 hex prefix of any attached image
    times: int | None = None       # stop matching after this many uses
    used: int = field(default=0, init=False)

    def matches(self, call: Call, out_model: type | None) -> bool:
        if self.times is not None and self.used >= self.times:
            return False
        if self.scope is not None and call.scope != self.scope:
            return False
        if self.out_model is not None and out_model is not self.out_model:
            return False
        if self.match is not None and not re.search(self.match, call.user):
            return False
        if self.image is not None and not any(h.startswith(self.image) for h in call.images):
            return False
        return True


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


class FakeLLM:
    text_chain = ["fake-text"]
    vision_chain = ["fake-vision"]

    def __init__(self, rules: list[Rule] | tuple[Rule, ...] = (), *, sequence: list | tuple = (),
                 ocr_text: str | list[str] = "", delay: float | tuple[float, float] | None = None,
                 faults: dict[int, Exception | type[Exception]] | None = None, seed: int = 0,
                 strict: bool = True, log_path: str | os.PathLike | None = None, index_offset: int = 0):
        self.rules = list(rules)
        self.sequence = list(sequence)
        self.ocr_text = ocr_text
        self.delay = delay
        self.faults = dict(faults or {})
        self.rng = random.Random(seed)
        self.strict = strict
        self.log_path = str(log_path) if log_path else os.environ.get("FAKE_LLM_LOG")
        self.index_offset = index_offset      # calls already made elsewhere (other attempts / processes)
        self.usage = UsageLedger()
        self.calls: list[Call] = []
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- same surface as app.llm.client.LLM
    def scope(self, name: str):
        return self.usage.scoped(name)

    def chat_json(self, system: str, user: str, out_model: type, chain: list[str] | None = None,
                  images: list[bytes] | None = None):
        return self._call("chat_json", system, user, out_model, chain or self.text_chain, images or [])

    def ocr_page(self, png_bytes: bytes, chain: list[str] | None = None) -> str:
        return self._call("ocr", "", "Transcribe this page.", None, chain or self.vision_chain, [png_bytes])

    # ---------------------------------------------------------------- counting
    def count(self, *, scope: str | None = None, kind: str | None = None, out_model: type | None = None,
              failed: bool | None = None, match: str | None = None) -> int:
        """Calls so far, filtered by scope, kind, output model, failure, or a regex over the prompt."""
        name = out_model.__name__ if out_model else None
        return sum(1 for c in self.calls
                   if (scope is None or c.scope == scope) and (kind is None or c.kind == kind)
                   and (name is None or c.out_model == name)
                   and (failed is None or (c.error is not None) == failed)
                   and (match is None or re.search(match, c.user)))

    @property
    def ocr_calls(self) -> int:
        return self.count(kind="ocr")

    @property
    def prompts(self) -> list[str]:
        return [c.user for c in self.calls if c.kind == "chat_json"]

    # ---------------------------------------------------------------- internals
    def _call(self, kind: str, system: str, user: str, out_model: type | None, chain: list[str],
              images: list[bytes]):
        with self._lock:
            n = self.index_offset + len(self.calls) + 1
            call = Call(n, kind, self.usage.scope, out_model.__name__ if out_model else None, system, user,
                        [_sha(i) for i in images], chain[0])
            self.calls.append(call)
        started = time.perf_counter()
        try:
            self._sleep()
            fault = self.faults.get(n)
            if fault is not None:
                raise fault() if isinstance(fault, type) else fault
            call.reply = self._reply(call, out_model)
            return call.reply
        except Exception as err:
            call.error = f"{type(err).__name__}: {err}"
            self.usage.fail(call.model, call.error)
            raise
        finally:
            call.seconds = time.perf_counter() - started
            if call.error is None:
                self._record(call)
            self._log(call)

    def _sleep(self) -> None:
        if self.delay is None:
            return
        seconds = self.rng.uniform(*self.delay) if isinstance(self.delay, tuple) else float(self.delay)
        if seconds > 0:
            time.sleep(seconds)

    def _reply(self, call: Call, out_model: type | None):
        with self._lock:
            for rule in self.rules:
                if rule.matches(call, out_model):
                    rule.used += 1
                    return self._materialise(rule.reply, call, out_model)
            if call.kind == "ocr":
                if isinstance(self.ocr_text, list):
                    if not self.ocr_text:
                        raise UnexpectedCall(f"ocr call #{call.n} in scope {call.scope!r}: no OCR text left")
                    return self.ocr_text.pop(0)
                return self.ocr_text
            if self.sequence:
                return self._materialise(self.sequence.pop(0), call, out_model)
        if not self.strict:
            return None
        raise UnexpectedCall(f"call #{call.n} in scope {call.scope!r} for {call.out_model} had no scripted "
                             f"answer.\n--- prompt ---\n{call.user[:2000]}")

    @staticmethod
    def _materialise(reply: Any, call: Call, out_model: type | None):
        if isinstance(reply, type) and issubclass(reply, Exception):
            raise reply()
        if isinstance(reply, Exception):
            raise reply
        if callable(reply) and not isinstance(reply, BaseModel):
            reply = reply(call)
        if out_model is not None and isinstance(out_model, type) and issubclass(out_model, BaseModel):
            if isinstance(reply, str):
                return out_model.model_validate_json(reply)
            if isinstance(reply, dict):
                return out_model.model_validate(reply)
            if isinstance(reply, BaseModel) and not isinstance(reply, out_model):
                raise UnexpectedCall(f"call #{call.n} asked for {out_model.__name__} but the script "
                                     f"holds a {type(reply).__name__}")
        return reply

    def _record(self, call: Call) -> None:
        prompt_tokens = max(1, (len(call.system) + len(call.user)) // 4) + 800 * len(call.images)
        completion = call.reply.model_dump_json() if isinstance(call.reply, BaseModel) else str(call.reply or "")
        usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=max(1, len(completion) // 4),
                                total_tokens=0)
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        self.usage.record(call.model, call.model, usage, call.seconds)

    def _log(self, call: Call) -> None:
        if not self.log_path:
            return
        line = {"n": call.n, "pid": os.getpid(), "t": round(time.time(), 3), "kind": call.kind, "scope": call.scope,
                "out_model": call.out_model, "model": call.model, "prompt_sha": _sha(call.user)[:12],
                "prompt_chars": len(call.user), "images": len(call.images),
                "seconds": round(call.seconds, 4), "error": call.error}
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")


def read_log(path: str | os.PathLike) -> list[dict]:
    """The JSON lines a FakeLLM (or several, in several processes) appended to `path`."""
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
