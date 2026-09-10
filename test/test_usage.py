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
from app.usage import (UsageLedger, cost_usd, load_prices, summarize_usage, tokens_of,
                       write_usage)
from tools.make_demo_case import synth_truth
from tools.score_case import score

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


def test_usage_files_summarise_to_dollars_per_bid(tmp_path):
    ledger = UsageLedger()
    with ledger.scoped("rubric"):
        ledger.record("google/gemini-2.5-flash@" + VERTEX, "gemini-2.5-flash", _usage(10_000, 1_000), 3)
    for name, prompt in (("A", 20_000), ("B", 40_000)):
        with ledger.scoped(name):
            ledger.record("google/gemini-2.5-flash@" + VERTEX, "gemini-2.5-flash", _usage(prompt, 2_000), 4)
            ledger.record("google/gemini-2.5-flash@" + VERTEX, "gemini-2.5-flash", _usage(1_000, 100), 1)
    usage_dir = tmp_path / "usage"
    for scope in ("rubric", "A", "B"):
        assert write_usage(usage_dir / f"{scope}.json", ledger, scope)["totals"]["calls"] >= 1
    assert write_usage(usage_dir / "C.json", ledger, "C") is None       # C made no calls
    s = summarize_usage(usage_dir, ["A", "B", "C"])
    assert s["bids"] == 2 and s["skipped"] == ["C"] and s["failed_calls"] == 0
    per_a = (21_000 * 0.30 + 2_100 * 2.50) / 1e6
    per_b = (41_000 * 0.30 + 2_100 * 2.50) / 1e6
    rubric = (10_000 * 0.30 + 1_000 * 2.50) / 1e6
    assert abs(s["usd_total"] - (per_a + per_b + rubric)) < 1e-4
    assert abs(s["usd_per_bid_mean"] - (per_a + per_b) / 2) < 1e-4
    assert s["calls_per_bid"] == 2.0 and s["tokens_per_bid"] == (23_100 + 43_100) // 2
    assert s["models"] == {"google/gemini-2.5-flash@" + VERTEX: "gemini-2.5-flash"}


# ---------------------------------------------------------------- Vertex auth

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


def test_seeded_defects_are_scored_against_ground_truth():
    truth = {f"Tenderer_{i:02d}": synth_truth(i) for i in range(1, 31)}
    assert [n for n, t in truth.items() if not t["certificate"]] == ["Tenderer_03", "Tenderer_10", "Tenderer_17", "Tenderer_24"]
    assert [n for n, t in truth.items() if t["shelf_life_months"] < 12] == ["Tenderer_05", "Tenderer_16", "Tenderer_27"]
    assert [n for n, t in truth.items() if t["arithmetic_error"]] == ["Tenderer_04", "Tenderer_13", "Tenderer_22"]
    perfect = score(_evaluation_from_truth(truth), truth)
    assert perfect["stage2"]["of"] == 26                  # 4 Stage I failures have no Stage II row
    assert perfect["overall"] == {"agree": 116, "of": 116, "pct": 100.0}

    ev = _evaluation_from_truth(truth)
    ev["stage1"][2]["passed"] = True                      # Tenderer_03's missing cert not caught
    ev["price_rows"][0]["unit_price"] = 10.38             # off by a cent
    s = score(ev, truth)
    assert s["stage1"]["agree"] == 29 and s["stage1"]["disagreements"] == ["Tenderer_03: passed=True truth cert=False"]
    assert s["unit_price"]["disagreements"] == ["Tenderer_01: got=10.38 truth=10.37"]
    assert s["overall"]["agree"] == 114
