"""Token/cost accounting (app/usage.py), Vertex auth (app/gcp.py) and the case
scorer: prices applied per served model, Gemini thinking tokens billed as output,
DeepSeek cache hits priced separately, per-bid scopes across threads, fallbacks
counted, files summarised into $ per bid — all offline."""
import datetime as dt
import json
import threading
from types import SimpleNamespace

from app.config import Config
from app.gcp import ADCToken, is_vertex
from app.usage import UsageLedger, cost_usd, load_prices, tokens_of

VERTEX = "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/endpoints/openapi"


def _usage(prompt, completion, total=None, **extra):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           total_tokens=total if total is not None else prompt + completion,
                           model_extra=extra, prompt_tokens_details=None)


def test_gemini_thinking_tokens_are_billed_as_output():
    toks = tokens_of(_usage(1000, 100, total=1300))       # 200 reasoning tokens
    assert toks == {"prompt_tokens": 1000, "cached_tokens": 0, "output_tokens": 300}
    usd = cost_usd("google/gemini-2.5-flash", toks, load_prices())
    assert abs(usd - (1000 * 0.30 + 300 * 2.50) / 1e6) < 1e-12


def test_deepseek_cache_hits_priced_separately_and_local_is_free():
    toks = tokens_of(_usage(1000, 100, prompt_cache_hit_tokens=400, prompt_cache_miss_tokens=600))
    assert toks["cached_tokens"] == 400
    usd = cost_usd("deepseek-v4-flash", toks, load_prices())
    assert abs(usd - (600 * 0.44 + 400 * 0.014 + 100 * 1.32) / 1e6) < 1e-12
    assert cost_usd("qwen3:8b", toks, load_prices()) == 0.0


def test_model_prices_env_override():
    prices = load_prices(json.dumps({"deepseek-chat": {"in": 0.22, "out": 0.66}, "mine": {"in": 1, "out": 2}}))
    assert prices["deepseek-chat"] == {"in": 0.22, "cached_in": 0.014, "out": 0.66}   # merged
    assert cost_usd("mine", {"prompt_tokens": 1_000_000, "cached_tokens": 0, "output_tokens": 0}, prices) == 1.0
    cfg = Config()
    cfg.model_prices_json = json.dumps({"x": {"in": 5, "out": 5}})
    from app.llm import LLM
    assert LLM(cfg).usage.prices["x"] == {"in": 5, "out": 5}


def test_ledger_scopes_per_thread_and_counts_fallbacks():
    ledger = UsageLedger()

    def bid(name, n):
        with ledger.scoped(name):
            for _ in range(n):
                ledger.record("deepseek-chat@https://api.deepseek.com/v1", "deepseek-v4-flash",
                              _usage(100, 10), 0.5)
            ledger.fail("deepseek-chat@https://api.deepseek.com/v1", "RateLimitError: 429")

    threads = [threading.Thread(target=bid, args=(f"T{i}", i + 1)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ledger.scopes() == ["T0", "T1", "T2"]
    t2 = ledger.snapshot("T2")["totals"]
    assert t2["calls"] == 3 and t2["failed"] == 1 and t2["prompt_tokens"] == 300 and t2["seconds"] == 1.5
    assert ledger.snapshot()["totals"]["calls"] == 6 and len(ledger.fallbacks) == 3
    assert ledger.snapshot("T1")["models"]["deepseek-chat@https://api.deepseek.com/v1"]["served"] == "deepseek-v4-flash"
    assert ledger.scope == "default"                       # main thread never scoped


class FakeCreds:
    def __init__(self, expiry):
        self.token, self.valid, self.expiry, self.refreshes = None, False, expiry, 0

    def refresh(self, _request):
        self.refreshes += 1
        self.token, self.valid = f"tok{self.refreshes}", True
        self.expiry = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=1)


def test_adc_token_refreshes_only_when_stale():
    creds = FakeCreds(expiry=None)
    provider = ADCToken(creds)
    assert provider.token() == "tok1" and provider.token() == "tok1"   # cached while valid
    creds.expiry = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(minutes=2)     # inside the 5-min margin
    assert provider.token() == "tok2" and creds.refreshes == 2
    assert is_vertex(VERTEX) and not is_vertex("https://generativelanguage.googleapis.com/v1beta/openai")


def test_vertex_entries_take_no_key_but_a_fresh_token_per_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ai-studio-key")
    cfg = Config()
    assert cfg.key_for(VERTEX) is None                                  # never the AI Studio key
    assert cfg.key_for("https://generativelanguage.googleapis.com/v1beta/openai") == "ai-studio-key"

    from test.test_llm import Out, RecordingClients
    from app.llm import LLM
    cfg.text_model, cfg.text_fallbacks = "google/gemini-2.5-flash@" + VERTEX, []
    creds = FakeCreds(expiry=None)
    llm = LLM(cfg, token_provider=ADCToken(creds))
    calls = []
    llm._clients = RecordingClients(calls, set(), '{"ok": true}')
    assert llm.chat_json("s", "u", Out).ok and llm.chat_json("s", "u", Out).ok
    assert [c[1] for c in calls] == [VERTEX, VERTEX] and creds.refreshes == 1


# ---------------------------------------------------------------- ground truth + scorer

def _evaluation_from_truth(truth: dict) -> dict:
    # Like the evaluator: Stage II rows exist only for bids that passed Stage I.
    return {
        "stage1": [{"tenderer": n, "passed": t["certificate"]} for n, t in truth.items()],
        "stage2": [{"tenderer": n, "passed": t["shelf_life_months"] >= 12}
                   for n, t in truth.items() if t["certificate"]],
        "price_rows": [{"tenderer": n, "arithmetic_ok": not t["arithmetic_error"],
                        "unit_price": t["unit_price"]} for n, t in truth.items()],
    }
