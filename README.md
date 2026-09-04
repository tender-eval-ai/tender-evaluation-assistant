# Tender Evaluation Assistant

Demo of an AI-assisted **procurement review pipeline** for public tender evaluation.
Input: a tender document set + one bid (offer) per tenderer. Output: an editable Word
**procurement review report** — Price Summary table, Stage I / Stage II conclusions, and a
detailed evaluation record sheet.

> **CONFIDENTIALITY WARNING**
> The demo's default text model is a **cloud API** (DeepSeek) for document understanding.
> **Never** feed real client tender/bid documents through any cloud path. Use the bundled
> synthetic fixtures, or your own sanitized samples. The production design targets fully
> local inference (Qwen3-VL / Qwen3.6 / DeepSeek on DGX Spark via vLLM) — the LLM client
> here is OpenAI-compatible, so production swaps `GITHUB_MODELS_BASE_URL` for a local
> vLLM endpoint with no code change.

## Pipeline (mirrors the TAP workflow)

```mermaid
flowchart LR
    T["📄 Tender PDFs<br/>text layer"] --> ING
    B["📠 Bid PDFs<br/>pure scans"] --> ING

    ING["<b>1 · Ingest</b><br/>text /<br/>VLM OCR"]
    RUB["<b>2 · Rubric</b><br/>Stage I + II<br/>price scheme"]
    HC1["✋ confirm<br/>rubric"]
    EXT["<b>3 · Extraction</b><br/>per tenderer,<br/>page-cited"]
    VER["🛡️ refute<br/>negative<br/>findings"]
    AG["🧭 evidence-search<br/>agent (bounded,<br/>unresolved only)"]
    HC2["✋ correct<br/>extractions"]
    EVA["<b>4 · Evaluation</b><br/>deterministic<br/>code, no LLM"]
    REP["<b>5 · Reports</b><br/>editable<br/>Word × 3"]

    ING --> RUB --> HC1 --> EXT --> VER --> AG --> HC2 --> EVA --> REP

    classDef llm fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef code fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef human fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef docs fill:#f3f4f6,stroke:#9ca3af,color:#374151
    class T,B docs
    class ING,RUB,EXT,VER,AG llm
    class HC1,HC2 human
    class EVA,REP code
```

🔵 LLM reads &nbsp;·&nbsp; 🟢 deterministic code computes &nbsp;·&nbsp; 🟡 human decides —
rubric derives Stage I checklist, Stage II essential requirements and the price formula
from *this* tender's documents; extraction cites file + page for every fact; evaluation
covers both stage matrices plus rounding, FX, arithmetic tally and ranking. The whole
flow runs as a **LangGraph state graph** (`app/graph.py`): durable per-project
checkpoints, the two human checkpoints as `interrupt()`s, bids fanned out in parallel.
The agent step is the only place an LLM chooses its own actions — and it is bounded:
read-only tools, step and OCR budgets, quotes verified on the cited page.

Design principles:

- **LLMs extract and classify; code calculates and ranks.** All arithmetic (totals,
  cost-effectiveness `D × M`, 2-significant-figure rounding, rankings, FX conversion,
  quoted-total tally check) is deterministic Python.
- **Every tender is different** → the rubric is *derived from the tender documents* per
  project, and is saved as editable JSON (`rubric.json`) for human confirmation before
  evaluation.
- **Evidence-first**: extracted facts carry page references; the evaluation record sheet
  shows them so the Tender Assessment Panel can verify every cell.
- **Citations are grounded in code** (`app/grounding.py`): a finding that cites a page
  nobody read is demoted (present → missing, yes/no → unclear); verification
  refutations and agent results must quote text that appears on the cited page.
- **Bounded agency** (`app/agent.py`): the top-level flow is a fixed workflow. The one
  agentic step — evidence search for findings still missing/unclear after
  verification — picks its own tool calls (list/search/read pages, OCR a page on
  demand) under step and OCR budgets, can only *add* verified evidence, and never
  changes a compliance verdict.

## Quickstart

```bash
cd tender_evaluation_assistant
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1) Offline demo — no network, runs the synthetic case end-to-end:
.venv/bin/python run_demo.py offline-demo
# → output/offline_demo/reports/{price_summary,summary_list,evaluation_record}.docx

# 2) Run tests:
.venv/bin/python -m pytest test/ -q

# 3) Live demo with local Ollama (default backend — no key, no cloud):
#    Install https://ollama.com then:
#      ollama pull qwen3:8b && ollama pull qwen3-vl:8b
.venv/bin/python tools/make_demo_case.py     # generates synthetic demo_case/
GITHUB_MODELS_BASE_URL=http://localhost:11434/v1 .venv/bin/python run_demo.py run \
    --tender-dir demo_case/tender \
    --bids-dir demo_case/bids \      # one subfolder (or one PDF) per tenderer
    --out output/live_demo \
    --acknowledge-cloud              # only actually cloud if you point at a cloud URL

# 4) Evidence-search benchmark — the agent OFF vs ON, scored against ground truth:
.venv/bin/python tools/make_demo_case.py --buried --bidders 3 --out buried_case
GITHUB_MODELS_BASE_URL=http://localhost:11434/v1 .venv/bin/python tools/benchmark_buried.py \
    --case buried_case --max-ocr-pages 4
```

The synthetic live case is designed to exercise the interesting paths: Tenderer C is
cheapest but omits the Non-collusive Tendering Certificate (fails Stage I), and
Tenderer B's quoted total contains a deliberate arithmetic error that the price engine
flags — while B is still (correctly) the recommended conforming offer. Checkpoint files
under `output/live_demo/` (`rubric.json`, `bids/*.json`) are editable; delete one to
re-derive/re-extract it on the next run.

**LLM backend**: any OpenAI-compatible endpoint, configured entirely in `.env`. Two
ready-made setups: fully **local Ollama** (free, keyless —
`ollama pull qwen3:8b && ollama pull qwen3-vl:8b`), or a cheap **cloud text primary**
such as DeepSeek (`TEXT_MODEL=deepseek-chat@https://api.deepseek.com/v1` +
`DEEPSEEK_API_KEY`) with local Ollama as automatic fallback — synthetic/sanitized
documents only on any cloud path. Hosted endpoints pick their key by hostname
(`DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `ZHIPU_API_KEY`,
`GITHUB_TOKEN`), so a fallback chain can span providers. Chains
(`*_MODEL_FALLBACKS`) are tried automatically when the model before them fails.
Production swaps the base URL for vLLM on the client's hardware. (The original demo
backend, GitHub Models, was retired in 2026.)

## Repository layout

```
app/                the pipeline library (shared by CLI and backend)
  config.py         env + model configuration (GitHub Models ⇄ local vLLM swap point)
  llm.py            OpenAI-compatible client: fallback chains, JSON-validated chat, OCR
  ingest.py         PDF classification (text vs scan), text extraction, VLM OCR + cache
  schemas.py        pydantic models: Rubric, BidExtraction, EvaluationResult…
  rubric.py         tender understanding → evaluation rubric (Stage I/II + price scheme)
  bid_extract.py    per-bid field extraction with page citations
  evaluate.py       Stage I / Stage II matrices + English conclusions (deterministic)
  pricing.py        deterministic price engine (both Price Summary formats)
  report.py         Word report generation (python-docx)
  grounding.py      citation grounding: unread-page citations are not evidence
  tools.py          the agent's read-only tools, incl. on-demand OCR with a budget
  agent.py          bounded evidence-search agent: structured actions, budgets, trace
  graph.py          LangGraph orchestration: state, checkpoints, interrupts, Send fan-out
  pipeline.py       bidder discovery, offline (fixture) run, console summary
backend/            FastAPI service (projects, uploads, jobs, reports API) + Dockerfile
frontend/           Streamlit review UI (HTTP client of the backend only) + Dockerfile
docker-compose.yml  runs both services together
run_demo.py         CLI (offline demo + orchestrated run over real folders)
test/               69 offline tests incl. API, graph, agent (no network, no client data)
tools/              case generator (incl. --buried benchmark case), PDF generator,
                    stress driver, evidence-search benchmark
```

## Service mode — frontend + backend

Requirements are split per service: `backend/requirements.txt` (FastAPI + pipeline) and
`frontend/requirements.txt` (Streamlit + requests only). Root `requirements.txt` is the
dev aggregate (both + pytest).

```bash
# Local dev, two terminals:
.venv/bin/uvicorn backend.api:app --reload --port 8000
BACKEND_URL=http://localhost:8000 .venv/bin/streamlit run frontend/ui.py

# Docker (recommended):
cp .env.example .env       # set GITHUB_TOKEN; set API_KEY on any shared machine
docker compose up -d --build
# UI:  http://localhost:8501     API: http://localhost:8000/health
```

UI flow = **one orchestrated run with two human checkpoints** (`POST /run`,
`POST /resume`): upload documents → *Run* derives the rubric and pauses → review it
(every item shows its source citation — file, page, quoted clause — next to a
rendered tender-page preview; edit the JSON if needed) → *Confirm & continue*
extracts all bids in parallel, verifies them and runs the evidence-search agent on
whatever is still unresolved, then pauses → triaged review (negative findings first
with 🔴/🟠 badges, passed checks collapsed, 🔎 marks evidence the agent found, its
step trace in an expander, jump-to-cited-page preview) → *Confirm & continue*
evaluates and renders the Word reports. Edits made while paused are picked up on
resume; corrected bids are never re-extracted. Layers that run automatically:

- **Targeted retrieval** (`app/retrieval.py`): pages are keyword-scored and only the
  relevant ones enter the prompt — a Price Schedule on page 40 of a 300-page bid is
  found, not truncated away.
- **Adversarial verification** (`app/verify.py`): every negative finding (document
  missing / non-compliant) gets an independent refutation attempt before it can reach
  a report; refuted "missing" is restored with evidence, refuted "non-compliant" is
  demoted to *unclear* for human clarification — never auto-passed. Disable with
  `VERIFY_FINDINGS=0`.
- **Per-page OCR routing** (`app/ingest.py`): the text-vs-scan decision is per page,
  so a digital document with a scanned annex OCRs only the annex, and a scan with an
  embedded text layer on some pages skips OCR there.
- **Parallel extraction** (`app/graph.py`): bids without a stored extraction fan out
  as parallel graph branches (`MAX_PARALLEL_BIDS`, default 4) — cloud endpoints scale
  with it; a local Ollama simply queues the requests. 30 bidders: 116 s end to end.
- **Citation grounding** (`app/grounding.py`): "present on page 11" is not accepted if
  page 11 was never read — the finding is demoted so verification and the agent
  actually look. Refutations and agent results must quote text on the cited page.
- **Evidence-search agent** (`app/agent.py`, `app/tools.py`): for findings still
  missing/unclear after verification, and for a price the first pass never saw, a
  bounded tool-using loop reads the contents page, OCRs the pages it points to (on
  demand, within `AGENT_OCR_PAGES`), and finishes only with a quote verified on that
  page. `AGENT_SEARCH=0` disables it. Measured on the `--buried` case (schedules on
  pages 9–12 of scan-only offers, first pass capped at 4 pages):

  | run | certificate recall | false restores | price extracted | unclear findings w/ evidence |
  | --- | --- | --- | --- | --- |
  | agent off | 0/2 | 0 | 0/3 | 0/9 |
  | agent on | **2/2** | **0** | **3/3** | **8/9** |

Project data lives in `./data/` on the host (bind-mounted volume). CI runs the full
offline test suite on every push (`.github/workflows/ci.yml`).

## Client-site (production) deployment

The product is NDA-bound to **local** deployment — real tender/bid documents never
leave the client's network. The same compose stack is the deliverable for the client's
DGX Spark: stand up vLLM serving the local models, point `GITHUB_MODELS_BASE_URL` at
it in `.env`, and build the images for ARM (`docker compose build` on the GB10, or
`--platform linux/arm64`). Set a strong `API_KEY` whenever the services are reachable
by anyone but you, and keep port 8000 (API) firewalled — the UI on 8501 is the only
thing users need.

## Demo ⇄ production mapping

| Demo (this repo)                      | Production (client site)                          |
| ------------------------------------- | ------------------------------------------------- |
| DeepSeek API `deepseek-chat` (text)   | Qwen3.6-35B-A3B / DeepSeek-V4-Flash via vLLM      |
| Ollama `qwen3-vl:8b` vision OCR       | Qwen3-VL-30B-A3B (MoE) page OCR, batched          |
| Docker on a laptop (x86/arm)          | Same compose stack on DGX Spark GB10 (arm64)      |
| Synthetic fixtures                    | Real tender/bid sets, fully local                 |

Known demo limitations: the first-pass OCR cap per document (`MAX_OCR_PAGES` /
`--max-ocr-pages`, default 8 — the evidence-search agent reads further pages on demand
within `AGENT_OCR_PAGES`), local OCR speed (~25 s per page on `qwen3-vl:8b`; seconds
on a cloud vision model), and no Stage III–V yet (technical marking / combined score —
phase 2).
