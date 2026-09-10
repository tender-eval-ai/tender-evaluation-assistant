"""Token, call and cost accounting for every model call.

`UsageLedger` is attached to the LLM client. Calls are recorded per *scope* (the bid
being extracted, or "rubric") and per chain entry, with the model the provider says it
served, so a fallback that shifted work to another model is visible in the numbers
rather than hidden in an average. Dollars come from a per-1M-token price table
(built-in defaults, overridable with MODEL_PRICES in .env — record the prices used
next to any published result; providers change them).

Billable output is `total_tokens - prompt_tokens` when the provider reports a total:
Gemini counts its thinking tokens there and bills them as output. DeepSeek reports
cached prompt tokens separately (cheaper); they are priced with `cached_in`.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path

# USD per 1M tokens. Verified 2026-09-09 against the providers' pricing pages:
# Gemini 2.5 Flash $0.30 in (text/image) / $2.50 out incl. thinking (Vertex and AI
# Studio); DeepSeek-V4-Flash (the `deepseek-chat` alias) standard-time $0.44 in
# (cache miss) / $0.014 in (cache hit) / $1.32 out — off-peak is half. Local
# models (Ollama, vLLM) cost $0 per token here; their cost is the hardware.
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "google/gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "google/gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
    "deepseek-chat": {"in": 0.44, "cached_in": 0.014, "out": 1.32},
    "deepseek-v4-flash": {"in": 0.44, "cached_in": 0.014, "out": 1.32},
}

FIELDS = ("calls", "failed", "prompt_tokens", "cached_tokens", "output_tokens", "seconds", "usd")


def load_prices(env_json: str | None = None) -> dict[str, dict[str, float]]:
    prices = {k: dict(v) for k, v in DEFAULT_PRICES.items()}
    if env_json:
        for model, p in json.loads(env_json).items():
            prices[model] = {**prices.get(model, {}), **p}
    return prices


def _get(obj, name: str, default=0):
    if obj is None:
        return default
    if isinstance(obj, dict):
        v = obj.get(name, default)
    else:
        v = getattr(obj, name, None)
        if v is None:
            extra = getattr(obj, "model_extra", None) or {}
            v = extra.get(name, default)
    return v if v is not None else default


def tokens_of(usage) -> dict[str, int]:
    """Normalise an OpenAI-style usage object: prompt, cached (subset of prompt) and
    billable output tokens."""
    prompt = int(_get(usage, "prompt_tokens"))
    total = int(_get(usage, "total_tokens"))
    completion = int(_get(usage, "completion_tokens"))
    output = total - prompt if total >= prompt and total else completion
    cached = int(_get(usage, "prompt_cache_hit_tokens"))
    if not cached:
        details = _get(usage, "prompt_tokens_details", None)
        cached = int(_get(details, "cached_tokens"))
    return {"prompt_tokens": prompt, "cached_tokens": min(cached, prompt), "output_tokens": max(output, 0)}


def cost_usd(model: str, tokens: dict[str, int], prices: dict[str, dict[str, float]]) -> float:
    p = prices.get(model) or prices.get(model.split("/")[-1])
    if not p:
        return 0.0
    cached = tokens["cached_tokens"]
    uncached = tokens["prompt_tokens"] - cached
    return (uncached * p.get("in", 0.0) + cached * p.get("cached_in", p.get("in", 0.0))
            + tokens["output_tokens"] * p.get("out", 0.0)) / 1_000_000


class UsageLedger:
    def __init__(self, prices: dict[str, dict[str, float]] | None = None):
        self.prices = prices or load_prices()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._data: dict[str, dict[str, dict]] = {}     # scope -> entry -> counters
        self.fallbacks: list[dict] = []                # every failed entry, in order

    # ---------------------------------------------------------------- scoping
    @property
    def scope(self) -> str:
        return getattr(self._local, "scope", "default")

    @contextmanager
    def scoped(self, name: str):
        prev = getattr(self._local, "scope", None)
        self._local.scope = name
        try:
            yield
        finally:
            if prev is None:
                del self._local.scope
            else:
                self._local.scope = prev

    # ---------------------------------------------------------------- recording
    def _bucket(self, entry: str) -> dict:
        scope = self._data.setdefault(self.scope, {})
        return scope.setdefault(entry, {f: 0 for f in FIELDS} | {"served": ""})

    def record(self, entry: str, served_model: str | None, usage, seconds: float) -> None:
        toks = tokens_of(usage)
        model = served_model or entry.partition("@")[0]
        usd = cost_usd(model, toks, self.prices) or cost_usd(entry.partition("@")[0], toks, self.prices)
        with self._lock:
            b = self._bucket(entry)
            b["calls"] += 1
            b["seconds"] += seconds
            b["usd"] += usd
            b["served"] = model
            for k, v in toks.items():
                b[k] += v

    def fail(self, entry: str, error: str) -> None:
        with self._lock:
            self._bucket(entry)["failed"] += 1
            self.fallbacks.append({"scope": self.scope, "entry": entry, "error": error[:200]})

    # ---------------------------------------------------------------- reading
    def snapshot(self, scope: str | None = None) -> dict:
        """{"models": {entry: counters}, "totals": counters} for one scope (or all)."""
        with self._lock:
            scopes = [self._data.get(scope, {})] if scope else list(self._data.values())
            models: dict[str, dict] = {}
            for s in scopes:
                for entry, b in s.items():
                    m = models.setdefault(entry, {f: 0 for f in FIELDS} | {"served": b["served"]})
                    for f in FIELDS:
                        m[f] += b[f]
            totals = {f: sum(m[f] for m in models.values()) for f in FIELDS}
        for m in list(models.values()) + [totals]:
            m["seconds"] = round(m["seconds"], 2)
            m["usd"] = round(m["usd"], 6)
        return {"models": models, "totals": totals}

    def scopes(self) -> list[str]:
        with self._lock:
            return sorted(self._data)


# ---------------------------------------------------------------- files

def write_usage(path: Path, ledger: UsageLedger, scope: str) -> dict | None:
    """Persist one scope's usage as JSON (None if the scope made no calls)."""
    snap = ledger.snapshot(scope)
    if not snap["totals"]["calls"] and not snap["totals"]["failed"]:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2))
    return snap


def summarize_usage(usage_dir: Path, bids: list[str]) -> dict:
    """Aggregate usage/<scope>.json files into per-bid and total figures — the
    "$ per bid" number. Bids without a usage file (stored/corrected extractions)
    are listed as skipped, not averaged in."""
    per_bid, missing = {}, []
    for name in bids:
        p = usage_dir / f"{name}.json"
        if p.is_file():
            per_bid[name] = json.loads(p.read_text())["totals"]
        else:
            missing.append(name)
    rubric = json.loads((usage_dir / "rubric.json").read_text())["totals"] \
        if (usage_dir / "rubric.json").is_file() else None
    n = len(per_bid)
    bid_totals = {f: sum(t[f] for t in per_bid.values()) for f in FIELDS}
    totals = {f: bid_totals[f] + (rubric[f] if rubric else 0) for f in FIELDS}
    usd = sorted(t["usd"] for t in per_bid.values())
    secs = sorted(t["seconds"] for t in per_bid.values())
    models: dict[str, str] = {}
    for p in sorted(usage_dir.glob("*.json")):
        if p.name == "summary.json":
            continue
        for entry, m in json.loads(p.read_text())["models"].items():
            models[entry] = m.get("served", "")
    return {
        "bids": n, "skipped": missing,
        "usd_total": round(totals["usd"], 4),
        "usd_per_bid_mean": round(bid_totals["usd"] / n, 4) if n else None,
        "usd_per_bid_median": round(usd[n // 2], 4) if n else None,
        "tokens_per_bid": round((bid_totals["prompt_tokens"] + bid_totals["output_tokens"]) / n) if n else None,
        "calls_per_bid": round(bid_totals["calls"] / n, 1) if n else None,
        "model_seconds_per_bid_median": round(secs[n // 2], 1) if n else None,
        "failed_calls": totals["failed"],
        "rubric": rubric, "totals": totals, "models": models, "per_bid": per_bid,
    }
