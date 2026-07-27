# Tender Evaluation Assistant — Demo Pipeline

Demo of an AI-assisted **procurement review pipeline** for public tender evaluation.
Input: a tender document set + one bid (offer) per tenderer. Output: an editable Word
**procurement review report** — Price Summary table, Stage I / Stage II conclusions, and a
detailed evaluation record sheet.

> **CONFIDENTIALITY WARNING**
> This demo calls **GitHub Models** (a cloud API, free tier) for document understanding.
> **Never** feed real client tender/bid documents through the cloud path. Use the bundled
> synthetic fixtures, or your own sanitized samples. The production design targets fully
> local inference (Qwen3-VL / Qwen3.6 / DeepSeek on DGX Spark via vLLM) — the LLM client
> here is OpenAI-compatible, so production swaps `GITHUB_MODELS_BASE_URL` for a local
> vLLM endpoint with no code change.

## Pipeline (mirrors the TAP workflow)

```
tender docs (PDF, text) ──► [1 INGEST] ──► [2 RUBRIC]  auto-derive evaluation rubric:
bid docs   (PDF, scans) ──►  text or OCR      │         Stage I checklist, Stage II essential
                             (VLM per page)   │         requirements, price scheme + formula
                                              ▼
                              [3 BID EXTRACTION]  per tenderer: documents present,
                                              │   compliance evidence, price fields
                                              ▼   (every fact cites file + page)
                              [4 EVALUATION — deterministic code, no LLM]
                                              │   Stage I completeness matrix
                                              │   Stage II compliance matrix
                                              │   Price: rounding, FX, arithmetic check,
                                              │   cost-effectiveness or price×qty, ranking
                                              ▼
                              [5 REPORTS — python-docx, editable Word, English]
                                  price_summary.docx · summary_list.docx · evaluation_record.docx
```

Design principles:

- **LLMs extract and classify; code calculates and ranks.** All arithmetic (totals,
  cost-effectiveness `D × M`, 2-significant-figure rounding, rankings, FX conversion,
  quoted-total tally check) is deterministic Python.
- **Every tender is different** → the rubric is *derived from the tender documents* per
  project, and is saved as editable JSON (`rubric.json`) for human confirmation before
  evaluation.
- **Evidence-first**: extracted facts carry page references; the evaluation record sheet
  shows them so the Tender Assessment Panel can verify every cell.

## Quickstart

```bash
cd tender_evaluation_assistant
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1) Offline demo — no network, runs the synthetic case end-to-end:
.venv/bin/python run_demo.py offline-demo
# → output/offline_demo/reports/{price_summary,summary_list,evaluation_record}.docx

# 2) Run tests:
.venv/bin/python -m pytest test/ -q

# 3) Live demo with GitHub Models (sanitized/synthetic documents ONLY):
#    Token: https://github.com/settings/personal-access-tokens  (fine-grained PAT,
#    account permission "Models: read") — put it in .env as GITHUB_TOKEN=...
#    Free tier — small rate limits; the pipeline caches OCR aggressively and caps
#    pages per document.
.venv/bin/python tools/make_demo_case.py     # generates synthetic demo_case/
.venv/bin/python run_demo.py run \
    --tender-dir demo_case/tender \
    --bids-dir demo_case/bids \      # one subfolder (or one PDF) per tenderer
    --out output/live_demo \
    --acknowledge-cloud
```

The synthetic live case is designed to exercise the interesting paths: Tenderer C is
cheapest but omits the Non-collusive Tendering Certificate (fails Stage I), and
Tenderer B's quoted total contains a deliberate arithmetic error that the price engine
flags — while B is still (correctly) the recommended conforming offer. Checkpoint files
under `output/live_demo/` (`rubric.json`, `bids/*.json`) are editable; delete one to
re-derive/re-extract it on the next run.

Models (all on [GitHub Models](https://github.com/marketplace/models)): text defaults
to `openai/gpt-4o-mini`, vision to `openai/gpt-4.1`, each with a fallback chain
(`openai/o3`, then `openai/gpt-4.1-mini`) tried automatically when the model before it
fails — rate limit, outage, or a 403 for models not included in your plan (o3 needs a
paid Copilot plan; on the free tier it is skipped harmlessly). Override via
`TEXT_MODEL` / `VISION_MODEL` / `TEXT_MODEL_FALLBACKS` / `VISION_MODEL_FALLBACKS`.
See `.env.example`.

## Repository layout

```
app/config.py       env + model configuration (GitHub Models ⇄ local vLLM swap point)
app/llm.py          OpenAI-compatible client: JSON-validated chat, page OCR
app/ingest.py       PDF classification (text vs scan), text extraction, VLM OCR + cache
app/schemas.py      pydantic models: Rubric, BidExtraction, EvaluationResult…
app/rubric.py       tender understanding → evaluation rubric (Stage I/II + price scheme)
app/bid_extract.py  per-bid field extraction with page citations
app/evaluate.py     Stage I / Stage II matrices + English conclusions (deterministic)
app/pricing.py      deterministic price engine (both Price Summary formats)
app/report.py       Word report generation (python-docx)
app/pipeline.py     orchestrator; writes rubric.json, bids/*.json, evaluation.json, reports/
run_demo.py         CLI
test/               pytest suite + synthetic fixtures (no network, no real client data)
```

## Demo ⇄ production mapping

| Demo (this repo)                      | Production (client site)                          |
| ------------------------------------- | ------------------------------------------------- |
| GitHub Models `openai/gpt-4o-mini`    | Qwen3.6-35B-A3B / DeepSeek-V4-Flash via vLLM      |
| GitHub Models vision OCR              | Qwen3-VL-30B-A3B (MoE) page OCR, batched          |
| CLI + JSON checkpoint files           | Web app with rubric-confirmation & review UI      |
| Synthetic fixtures                    | Real tender/bid sets, fully local (DGX Spark GB10)|

Known demo limitations: free-tier rate limits (pages per doc capped via
`--max-ocr-pages`), no Stage III–V (technical marking / combined score — phase 2), no
review UI yet.
