"""The LLM gateway: every model call the pipeline makes goes through here, and the
pipeline never talks to a provider directly.

    typed errors     app.llm.client.LLMError.transient tells the job queue whether to retry
    endpoint policy  by the project's data class: confidential text never leaves the
                     local network; redacted samples reach only hosts cleared by name;
                     synthetic text may go anywhere
    cache            identical work (same chain, prompt version, prompt, images, output
                     shape) is answered from the cache and never paid twice
    budget           a per-project daily cap on calls and dollars; exceeding it fails
                     the run visibly instead of running up a bill
    rate limiter     one shared pace per provider across every worker process

The backend is anything with the `app.llm.client.LLM` surface (`chat_json`, `ocr_page`,
`scope`, `text_chain`, `vision_chain`, `usage`), including `test.fakes.FakeLLM`. The
memory backends here suit one process; `app.llm.gateway_pg` holds the Postgres ones the
workers share."""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Protocol, Type, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- errors

class GatewayError(RuntimeError):
    """A refusal by the gateway. Never transient: retrying would not change the answer."""

    code = "gateway_error"
    transient = False


class DataClassForbidden(GatewayError):
    code = "data_class_forbidden"


class BudgetExceeded(GatewayError):
    code = "budget_exceeded"


# ---------------------------------------------------------------- endpoint policy

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})


def host_of(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def endpoint_class(base_url: str, local_hosts: frozenset[str] = frozenset()) -> str:
    """'local' for loopback, private-network and named local hosts; 'cloud' otherwise."""
    host = host_of(base_url)
    if host in LOCAL_HOSTS or host in local_hosts:
        return "local"
    try:
        return "local" if ipaddress.ip_address(host).is_private else "cloud"
    except ValueError:
        return "cloud"


@dataclass(frozen=True)
class EndpointPolicy:
    """Which endpoints a data class may reach. `cleared_hosts` are the cloud hosts an
    explicit decision cleared for the redacted sample cases (checklist A6)."""

    cleared_hosts: frozenset[str] = frozenset()
    local_hosts: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls) -> "EndpointPolicy":
        split = lambda v: frozenset(h.strip().lower() for h in v.split(",") if h.strip())   # noqa: E731
        return cls(cleared_hosts=split(os.environ.get("LLM_CLEARED_HOSTS", "")),
                   local_hosts=split(os.environ.get("LLM_LOCAL_HOSTS", "")))

    def allowed(self, base_url: str, data_class: str) -> bool:
        if data_class == "synthetic":
            return True
        if endpoint_class(base_url, self.local_hosts) == "local":
            return True
        if data_class == "redacted_sample":
            return host_of(base_url) in self.cleared_hosts
        return False                                   # confidential: local only

    def filter_chain(self, chain: list[str], default_base_url: str, data_class: str) -> list[str]:
        """The entries of a chain ("model" or "model@base_url") this class may use."""
        return [e for e in chain if self.allowed(e.partition("@")[2] or default_base_url, data_class)]


# ---------------------------------------------------------------- backends

class Cache(Protocol):
    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str, meta: dict) -> None: ...


class RateLimiter(Protocol):
    def acquire(self, key: str, rpm: int) -> float:
        """Wait for the next slot of `key` at `rpm` requests per minute; return the seconds waited."""


class Budget(Protocol):
    def spent(self, project: str, day: str) -> tuple[int, float]: ...

    def add(self, project: str, day: str, calls: int, usd: float) -> None: ...


class MemoryCache:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.meta: dict[str, dict] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def put(self, key: str, value: str, meta: dict) -> None:
        self.data[key] = value
        self.meta[key] = meta


SAFETY = 1.02      # spacing margin: provider limits are not measured to the millisecond


def spacing(rpm: int) -> float:
    return 60.0 / rpm * SAFETY


class MemoryLimiter:
    """One process's pace per key: each call takes the next slot, `spacing(rpm)` after
    the previous one (or now), and sleeps until it. `clock` and `sleep` are injectable
    for tests."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.next_slot: dict[str, float] = {}

    def acquire(self, key: str, rpm: int) -> float:
        now = self.clock()
        slot = max(self.next_slot.get(key, now), now)
        self.next_slot[key] = slot + spacing(rpm)
        wait = slot - now
        if wait > 0:
            self.sleep(wait)
        return max(wait, 0.0)


class MemoryBudget:
    def __init__(self):
        self.rows: dict[tuple[str, str], list] = {}

    def spent(self, project: str, day: str) -> tuple[int, float]:
        calls, usd = self.rows.get((project, day), [0, 0.0])
        return calls, usd

    def add(self, project: str, day: str, calls: int, usd: float) -> None:
        row = self.rows.setdefault((project, day), [0, 0.0])
        row[0] += calls
        row[1] += usd


# ---------------------------------------------------------------- settings

@dataclass(frozen=True)
class GatewaySettings:
    rpm: int | None = None                  # LLM_RPM: requests per minute per provider; unset = no limiter
    daily_usd: float | None = None          # LLM_DAILY_BUDGET_USD per project
    daily_calls: int | None = None          # LLM_DAILY_BUDGET_CALLS per project
    prompt_version: str = "v1"              # PROMPT_VERSION: part of every cache key
    policy: EndpointPolicy = field(default_factory=EndpointPolicy)

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        env = os.environ
        return cls(rpm=int(env["LLM_RPM"]) if env.get("LLM_RPM") else None,
                   daily_usd=float(env["LLM_DAILY_BUDGET_USD"]) if env.get("LLM_DAILY_BUDGET_USD") else None,
                   daily_calls=int(env["LLM_DAILY_BUDGET_CALLS"]) if env.get("LLM_DAILY_BUDGET_CALLS") else None,
                   prompt_version=env.get("PROMPT_VERSION", "v1"),
                   policy=EndpointPolicy.from_env())


def _sha(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            h.update(hashlib.sha256(part).digest())
        else:
            h.update(json.dumps(part, sort_keys=True, ensure_ascii=False, default=str).encode())
        h.update(b"\x1f")
    return h.hexdigest()


# ---------------------------------------------------------------- the gateway

class Gateway:
    def __init__(self, backend, *, project: str, data_class: str, settings: GatewaySettings | None = None,
                 cache: Cache | None = None, limiter: RateLimiter | None = None, budget: Budget | None = None,
                 limiter_key: str | None = None, base_url: str | None = None, today=None):
        self.backend = backend
        self.project = project
        self.data_class = str(getattr(data_class, "value", data_class))
        self.settings = settings or GatewaySettings()
        self.cache, self.limiter, self.budget = cache, limiter, budget
        self.limiter_key = limiter_key
        self.base_url = base_url or getattr(getattr(backend, "cfg", None), "base_url", "") or "local://"
        self.today = today or (lambda: dt.date.today().isoformat())
        self.stats = {"calls": 0, "cache_hits": 0, "waited_seconds": 0.0, "usd": 0.0}

    # the same surface as the backend
    @property
    def text_chain(self) -> list[str]:
        return list(self.backend.text_chain)

    @property
    def vision_chain(self) -> list[str]:
        return list(self.backend.vision_chain)

    @property
    def usage(self):
        return getattr(self.backend, "usage", None)

    def scope(self, name: str):
        return self.backend.scope(name) if hasattr(self.backend, "scope") else nullcontext()

    def chat_json(self, system: str, user: str, out_model: Type[T], chain: list[str] | None = None,
                  images: list[bytes] | None = None) -> T:
        chain = self._chain(chain or (self.vision_chain if images else self.text_chain))
        key = _sha("chat_json", chain, self.settings.prompt_version, system, user, out_model.model_json_schema(),
                   *(images or []))
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            self.stats["cache_hits"] += 1
            return out_model.model_validate_json(cached)
        result = self._call(chain, lambda: self.backend.chat_json(system, user, out_model, chain=chain, images=images))
        if self.cache:
            self.cache.put(key, result.model_dump_json(), self._meta("chat_json", chain))
        return result

    def ocr_page(self, png_bytes: bytes, chain: list[str] | None = None) -> str:
        chain = self._chain(chain or self.vision_chain)
        key = _sha("ocr", chain, self.settings.prompt_version, png_bytes)
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached
        text = self._call(chain, lambda: self.backend.ocr_page(png_bytes, chain=chain))
        if self.cache:
            self.cache.put(key, text, self._meta("ocr", chain))
        return text

    # ---------------------------------------------------------------- the checks around a call
    def _chain(self, chain: list[str]) -> list[str]:
        allowed = self.settings.policy.filter_chain(chain, self.base_url, self.data_class)
        if not allowed:
            raise DataClassForbidden(f"no endpoint in {chain} may receive {self.data_class} text "
                                     f"(project {self.project})")
        return allowed

    def _call(self, chain: list[str], fn):
        self._check_budget()
        if self.limiter and self.settings.rpm:
            key = self.limiter_key or host_of(chain[0].partition("@")[2] or self.base_url) or "default"
            self.stats["waited_seconds"] += self.limiter.acquire(key, self.settings.rpm)
        before = self._usd()
        result = fn()
        spent = self._usd() - before
        self.stats["calls"] += 1
        self.stats["usd"] += spent
        if self.budget:
            self.budget.add(self.project, self.today(), 1, spent)
        return result

    def _check_budget(self) -> None:
        if not self.budget or (self.settings.daily_calls is None and self.settings.daily_usd is None):
            return
        calls, usd = self.budget.spent(self.project, self.today())
        if self.settings.daily_calls is not None and calls >= self.settings.daily_calls:
            raise BudgetExceeded(f"project {self.project}: {calls} calls today, limit {self.settings.daily_calls}")
        if self.settings.daily_usd is not None and usd >= self.settings.daily_usd:
            raise BudgetExceeded(f"project {self.project}: ${usd:.4f} today, limit ${self.settings.daily_usd:.2f}")

    def _usd(self) -> float:
        ledger = self.usage
        return float(ledger.snapshot()["totals"]["usd"]) if ledger is not None else 0.0

    def _meta(self, kind: str, chain: list[str]) -> dict:
        return {"kind": kind, "chain": chain, "prompt_version": self.settings.prompt_version, "project": self.project}
