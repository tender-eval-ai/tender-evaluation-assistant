# Tender Evaluation Assistant

Demo of an AI-assisted **procurement review pipeline** for tender evaluation.
Input: a tender document set + one bid (offer) per tenderer. Output: an editable Word
**procurement review report** — Price Summary table, Stage I / Stage II conclusions, and a
detailed evaluation record sheet.

![A reviewer checks item (l) with its page highlighted, runs a check on a scanned offer, corrects a field the model could not read, and confirms the review](docs/images/review.gif)

*The review UI on its built-in mock and the synthetic tender: every verdict cites its page,
and a person's correction keeps the model's value beside it, with who and why.*

<details>
<summary>Screens</summary>

| Rules: the rule set drafted from the tender, confirmed by a second person | Stage I: the offer's page, the items, the evidence and rules |
|---|---|
| ![Rules window](docs/images/rules.png) | ![Stage I window](docs/images/stage1.png) |

![A field corrected by a reviewer](docs/images/correction.png)

| Scoring: every offer ranked, the recommended one marked | Report: the conclusions, each tenderer's review, the Word reports |
|---|---|
| ![Scoring window](docs/images/scoring.png) | ![Report window](docs/images/report.png) |

</details>

> **CONFIDENTIALITY WARNING**
> The models are whatever `.env` points at: the measured demo configurations use
> **cloud APIs** (DeepSeek, Gemini on Vertex AI) or local Ollama. **Never** feed real
> client tender/bid documents through any cloud path. Use the bundled synthetic
> fixtures, or your own sanitized samples. The production design targets fully local
> inference (Qwen3-VL / Qwen3.6 / DeepSeek on DGX Spark via vLLM) — the LLM client is
> OpenAI-compatible, so production points the base URL at vLLM with no code change.

## Results

Measured on three real tenders (redacted samples kept outside the repository;
only numbers are recorded here). The answer keys were built by reading the PDFs, never by
running the parser that is scored against them.

**Parser (L0) and citations** — two separate scores (`tools/eval_parser.py`):

- *Parser recall*: of the answer key's nodes, how many the parser produced in the same
  document, on the same page, at the same place in the clause tree.
- *Citation resolution*: of the citations in the tender's own text ("Paragraph 20.2 of the
  Terms of Tender"), how many the resolver takes to exactly one node of the parser's table.

| Tender | Parser recall | Citation resolution |
|---|---|---|
| Tender 1 | 97.8% of 454 key nodes | 90.2% of 520 citations |
| Tender 2 | 95.0% of 756 key nodes | 93.8% of 566 citations |
| Tender 3 | 91.1% of 1582 key nodes | 87.0% of 801 citations |

Tender 3 is 25 documents inside one 366-page PDF. Two of the three tenders were held out
when the parser was ported; fixes since then were driven by failures found on them, so they
are no longer unseen. The answer keys were built by agents and are not yet verified by a person.

**Rule set (L0 layer)** — the Completeness Check Schedule's items located with their Part
and page, scored against a separate key:

| Tender | items found | Part right | page right | invented |
|---|---|---|---|---|
| Tender 1 | 15/15 | 15/15 | 15/15 | none |
| Tender 2 | 13/13 | 13/13 | 13/13 | none |
| Tender 3 | 21/21 | 21/21 | 21/21 | none |

**Tests** — 623 Python (606 offline, 17 against Postgres), 74 browser-component (Vitest), 4
end-to-end (Playwright), run by CI on every pull request: lint and a secrets and dependency
scan, the offline suite, Postgres integration, web and e2e.

Full method and per-document numbers: [`docs/evals/parser_l0.md`](docs/evals/parser_l0.md)
and [`docs/evals/ruleset_l1_l4.md`](docs/evals/ruleset_l1_l4.md).

## Architecture

```mermaid
flowchart LR
    T["📄 Tender PDFs"]
    B["📠 Bid PDFs<br/>(often scans)"]

    subgraph RB["ruleset_build job · per tender"]
        direction TB
        L0["<b>L0 · parse + locate</b><br/>layout parser: clause tree,<br/>schedule items and Parts"]
        L1["<b>L1 · match</b><br/>item → form template"]
        L2["<b>L2 · slots</b><br/>the template's blanks,<br/>quotes verified"]
        L3["<b>L3 · novel + additions</b><br/>rules no template has"]
        L4["<b>L4 · coverage</b><br/>obligations no rule covers"]
        L0 --> L1 --> L2 --> L3 --> L4
    end

    HC1["✋ rule set edited,<br/>confirmed by a<br/>second person"]

    subgraph VC["vendor_check job · per tenderer"]
        direction TB
        V0["<b>render + triage</b><br/>label every page<br/>by form"]
        V2["<b>resolve + extract</b><br/>each form's fields,<br/>page-cited"]
        V4["<b>verify</b><br/>values checked against<br/>the text, or a second<br/>read of a scan"]
        AG["<b>search agent</b><br/>bounded, forms<br/>still not found"]
        V0 --> V2 --> V4 --> AG
    end

    ENG["<b>rules engine</b><br/>Stage I / II verdict<br/>per item"]
    HC2["✋ reviewer corrects<br/>fields, confirms<br/>the review"]
    OUT["<b>pricing + reports</b><br/>Price Summary, ranking,<br/>Word × 3"]

    T --> L0
    L4 --> HC1
    HC1 --> ENG
    B --> V0
    AG --> ENG --> HC2 --> OUT
    HC1 -. "new version:<br/>evaluate job re-decides" .-> ENG

    classDef llm fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef code fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef human fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef docs fill:#f3f4f6,stroke:#9ca3af,color:#374151
    class T,B docs
    class L1,L2,L3,V0,V2,V4,AG llm
    class L0,L4,ENG,OUT code
    class HC1,HC2 human
```

🔵 a model reads &nbsp;·&nbsp; 🟢 code decides &nbsp;·&nbsp; 🟡 a person decides. The parser, the
rules engine, pricing and the reports make no model call. Every model call goes through
one gateway (`app/gateway.py`), which applies the project's data class (confidential
text never leaves the local network), a cache, a daily budget and a rate limit.

| Runs as | What it is |
|---|---|
| `web` | the React review UI (Rules, Stage I, Stage II, Scoring, Report), on :8080 |
| `backend` | FastAPI (`backend/`), the routes of [`docs/api_contract.md`](docs/api_contract.md), on :8000 |
| `worker` | Procrastinate workers running the three jobs: `ruleset_build`, `vendor_check`, `evaluate`. Checkpointed after every step, so a killed job resumes; `--scale worker=N` adds more |
| `postgres` | projects, versioned rule sets, results, the audit events, the job queue, and the gateway's cache and budget |

## Pipeline (mirrors the TAP workflow)

This is the prototype's flow, still served by the legacy routes until the S5 legacy removal
(checklist J11-7). The current system is the one under Architecture above.

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
# demo_case/ is committed; regenerate it (same content) with: tools/make_demo_case.py
# test/data/synthetic_tender/ is a synthetic tender case (17 tender documents, running headers, PART
# numbering, a Completeness Check Schedule with items (a)-(o), four bids incl. scans); the
# real-size tender is in test/data/synthetic_tender_full/. Regenerate: tools/make_synthetic_tender.py [--full]
# --bids-dir holds one subfolder (or one PDF) per tenderer; --acknowledge-cloud is the
# confidentiality gate — it only matters when .env points at a cloud endpoint.
GITHUB_MODELS_BASE_URL=http://localhost:11434/v1 .venv/bin/python run_demo.py run \
    --tender-dir demo_case/tender --bids-dir demo_case/bids \
    --out output/live_demo --acknowledge-cloud

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
), so a fallback chain can span providers. Chains
(`*_MODEL_FALLBACKS`) are tried automatically when the model before them fails.
Production swaps the base URL for vLLM on the client's hardware. (The original demo
backend, GitHub Models, was retired in 2026.)

## Development workflow

Two people share this repo, so every change reaches `main` through a pull request reviewed by the other person (ownership and open decisions: `docs/merge_plan_checklist.md`).

```bash
pip install -r requirements-dev.txt     # ruff, pre-commit, pip-audit on top of requirements.txt
git config core.hooksPath .githooks     # runs the pre-commit hooks on commit; refuses direct pushes to main
pre-commit run --all-files              # exactly what CI's lint job runs
# after changing requirements*.txt:
uv pip compile requirements.txt --python-version 3.12 --universal --generate-hashes -o requirements.lock
# after changing a route (review docs/api_contract.md first; the snapshot is docs/openapi.json):
UPDATE_OPENAPI=1 python -m pytest test/test_api_contract.py
# the Postgres-backed tests (CI's integration job): the check API, the worker, migrations
DATABASE_URL=postgresql://postgres:dev@localhost:55432/harness python -m pytest -m postgres -q
```

CI on every pull request (`.github/workflows/ci.yml`), with each heavy job running only when a change touches what it tests:
- `checks`: pre-commit (ruff, gitleaks, large files, merge markers, PDF placement), gitleaks over the full history, pip-audit over the lockfile, and on `main` the guard that fails a commit not merged through a pull request;
- `test`: the offline suite, installed from `requirements.lock`;
- `integration`: the Postgres-backed tests;
- `web`: Vitest, lint and the build;
- `e2e`: Playwright on the mock.

Every action is pinned by commit, and the workflow token is read-only unless a job asks for more. `deploy-azure.yml` validates the Bicep on pull requests and deploys by hand. Opt-in test levels are the pytest markers `orchestrator`, `realdata` and `live`; the default run excludes them and needs no network, tokens or client data. Dependabot watches only the GitHub Actions versions; Python versions are fixed by `requirements.lock`, refreshed by hand at each stop point or when pip-audit fails.

## Repository layout

```
app/                the pipeline library (shared by CLI and backend)
  config.py         env + model configuration (the cloud ⇄ local vLLM swap point)
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
  gcp.py            Vertex AI auth: OAuth token provider over Application Default Credentials
  usage.py          per-bid token / call / $ accounting, price table, run summaries
  graph.py          LangGraph orchestration: state, checkpoints, interrupts, Send fan-out
  pipeline.py       bidder discovery, offline (fixture) run, console summary
  parsing/          the tender parser (L0): PDF loading, the layout-model node tree, the document
                    split, and the citation resolver; the only code that imports PyMuPDF
  checks/           the vendor check for every form of a bid, layer by layer: V0 page rendering, V1 triage,
                    V2 resolve, V3 extract (the form menu in forms.py), V4 verify, V5 the bounded search
                    agent, the engine bridge; reviewer corrections, pricing in the tender's currency, the
                    Word reports; the `vendor_check` pipeline
  gateway.py        the LLM gateway every pipeline call goes through: endpoint policy by data class,
                    cache, per-project daily budget, shared rate limiter (gateway_pg.py: the Postgres backends)
  jobs/             the run queue and check worker (Procrastinate on Postgres): step pipelines with
                    per-step checkpoints, pause/resume, results + corrections, `python -m app.jobs.worker`
  db.py             plain-SQL migrations (migrations/NNN_name.sql, up and down sections)
  rulesets/         the rule-set builder (the `ruleset_build` pipeline): locate (L0), match to a template
                    (L1), fill its slots (L2), draft novel rules and additions (L3), coverage gaps (L4);
                    the template library (templates/), editing, versions and diffs; the shared contract
                    in schema.py, changed only by a `contract` PR
  engine/           Nasi's rule engine, ported unchanged from Bidding-AI-expert@7e8e273
backend/            FastAPI service (projects, uploads, jobs, reports API) + Dockerfile
web/                the review UI (React, Vite): Rules, Stage I/II, Scoring, Report; nginx image for compose
mcp_server/         MCP server over the prototype's read-only tools + local-model MCP client (retired at S5, J10)
docs/               the API contract and its OpenAPI snapshot, decisions/ (orchestrator, PDF licences), evals/
                    (parser, rule set, vendor check, verification, bid keys), the merge-plan checklist, plan,
                    specification, interview prep, project report; images/ for this README
migrations/         SQL migrations applied by app.db.migrate (the worker runs it at start)
docker-compose.yml  Postgres, the API, the check worker (same image) and the UI together
deploy/azure/       the shared demo on Azure: Bicep, setup/deploy scripts (workflow: .github/workflows/deploy-azure.yml)
run_demo.py         CLI (offline demo + orchestrated run over real folders)
test/               606 offline tests and 17 against Postgres: parser, rule sets, checks, engine, jobs,
                    gateway, API and its contract (no network, no client data)
tools/              synthetic case generators (tender and bids, with ground truth), the demo case, PDF
                    generator; the evals (parser, rule set, bid key scoring) and end-to-end checks
                    through the API; stress driver, evidence-search benchmark, OCR comparison
LICENSE             GNU AGPL-3.0
```

## Service mode — frontend + backend

The API's requirements are `backend/requirements.txt`; root `requirements.txt` is the dev
aggregate (the API's plus pytest and the MCP client). The image installs
`backend/requirements.lock`, hashed, at the same versions as the root lock CI tests, and
runs as the unprivileged user `app` (uid 1000). **On a Linux host,** `./data` must be
writable by uid 1000; a folder an older root-run stack wrote needs
`sudo chown -R 1000:1000 data` once. `docker compose ps` shows the API and the worker as
healthy once `/health` answers and the worker's sweeper has reached Postgres. The UI in `web/` is an npm project;
its image serves the built app with nginx, forwards the API's paths to the backend and adds
`API_KEY` there, so the key never reaches the browser.

```bash
# Docker (recommended): Postgres, the API, the check worker and the UI.
cp .env.example .env       # point the models at Ollama/DeepSeek/Vertex; set API_KEY on any shared machine
docker compose up -d --build
# UI:  http://localhost:8080     API: http://localhost:8000/docs     (workers: docker compose up -d --scale worker=3)

# The synthetic tender case end to end through the API: project, import, rule set drafted and
# confirmed by a second person, one check per tenderer on the worker, the results per tenderer.
python tools/check_synthetic_case.py             # add --key when API_KEY is set

# Local dev without Docker (needs a Postgres for the check routes and the worker):
docker run -d --name tea-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=tender -p 55432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:dev@localhost:55432/tender
.venv/bin/uvicorn backend.api:app --reload --port 8000
.venv/bin/python -m app.jobs.worker --pipelines app.checks.vendor_check,app.rulesets.build_job,app.jobs.evaluate_job
cd web && VITE_API_BASE=http://localhost:8000 npm run dev   # the UI on :5173 (without VITE_API_BASE: the mock)
```

**How a project runs.** The worker runs three jobs, each checkpointed after every step, so a crash or a deploy
resumes where it stopped. Every model call goes through the gateway (endpoint policy by data class, cache, daily
budget, one shared pace per provider).

1. **`ruleset_build`** (`POST /projects/{pid}/ruleset/build`) drafts the tender's rule set: parse and locate the
   Completeness Check Schedule, match each item to a template, fill its slots, draft what no template has, and list
   the obligations no rule covers. A person edits the draft in the Rules window, and a second person confirms it.
2. **`vendor_check`** (`POST /projects/{pid}/checks`, one job per tenderer) renders every page of the offer, labels
   them by form, finds each form's pages, reads its fields with page citations, verifies them against the text or
   by a second read of a scan, and sends the bounded search agent after any form still not found. Once a rule set
   is confirmed, the rules engine decides each item.
3. **`evaluate`** re-decides every stored result against a newly confirmed rule-set version, with no model call.

A reviewer corrects any field in Stage I or II (the model's value is kept beside the correction, with who and why)
and confirms the review. Scoring needs a confirmed rule set, and the Word reports also wait until every
review is confirmed. `GET /projects/{pid}/jobs`
follows the jobs, and `GET /projects/{pid}/bids/{t}/results` has the fields, the verdicts and their evidence. Page
images open by signed links. An upload is capped from its declared length before any of it is received
(`MAX_UPLOAD_MB`, default 512, per request). The measurements behind the design are in
`docs/decisions/0001-orchestrator.md`.

**The prototype's flow (legacy routes, removed at S5, J11-7).** The Streamlit UI that drove it is gone; the routes
remain until the legacy removal. It was **one orchestrated run with two human checkpoints** (`POST /run`,
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
  with it; a local Ollama simply queues the requests. 30 bidders: 82.6–115 s end to end
  on the cloud text models (measured table below; 116 s on the 2026-09-03 run).
- **Citation grounding** (`app/grounding.py`): "present on page 11" is not accepted if
  page 11 was never read — the finding is demoted so verification and the agent
  actually look. Refutations and agent results must quote text on the cited page.
- **Evidence-search agent** (`app/agent.py`, `app/tools.py`): for findings still
  missing/unclear after verification, and for a price the first pass never saw, a
  bounded tool-using loop reads the contents page, OCRs the pages it points to (on
  demand, within `AGENT_OCR_PAGES`), and finishes only with a quote verified on that
  page. `AGENT_SEARCH=0` disables it. First measured on the `--buried` case (schedules
  on pages 9–12 of scan-only offers, first pass capped at 4 pages; 2026-09-03 run,
  DeepSeek text + local OCR — the per-provider reruns are in the table further down):

  | run | certificate recall | false restores | price extracted | unclear findings w/ evidence |
  | --- | --- | --- | --- | --- |
  | agent off | 0/2 | 0 | 0/3 | 0/9 |
  | agent on | **2/2** | **0** | **3/3** | **8/9** |

Project data lives in `./data/` on the host (bind-mounted volume). CI runs the full
offline test suite on every push (`.github/workflows/ci.yml`). The same read-only
tools are exposed as an MCP server — see the next section.

## MCP server — the tools as a product surface

*Retired at S5 (checklist J10): these are the prototype's tools, and the server goes with the legacy stack.
What it measured moves to `docs/archive/`.*

The read-only tools the evidence-search agent uses are also exposed over the
[Model Context Protocol](https://modelcontextprotocol.io) (`mcp_server/server.py`,
official `mcp` SDK 2.2), so any MCP client can walk a tender or an offer and answer a
reviewer's question with page citations: `list_projects` → `list_bids` →
`select_bid` / `select_tender` → `list_pages`, `search_pages`, `read_page`,
`ocr_page` (on-demand OCR of scanned pages, `AGENT_OCR_PAGES` budget, cache shared
with the pipeline), plus `get_rubric`. The server never writes anything but that
cache.

> **Confidentiality rule.** An MCP server only moves *tool execution* onto the
> machine holding the documents — every tool result (page listings, snippets, page
> text, OCR output) goes to whatever model drives the connected client. Claude
> Desktop, Cursor and similar clients are driven by cloud models, so connecting them
> is cloud egress of document content: **synthetic or sanitized projects only**.
> This is enforced in code, not left to the operator: a project is served only if it
> was created with the *synthetic* flag (checkbox in the UI, `"synthetic": true` in
> `meta.json`); unflagged projects are not even listed. The exception is an
> on-premises client, declared by starting the server with `MCP_LOCAL_MODEL=1` — the
> bundled local client does that itself. The HTTP transport is off unless
> `ALLOW_CLOUD_CLIENTS=1`, binds to loopback, requires `X-API-Key` and serves
> synthetic projects only, whatever `MCP_LOCAL_MODEL` says.

**Production-compatible client** — the project's own `LLM` class on a *local* model
drives the same tools over stdio, so nothing leaves the machine (Ollama on a laptop,
vLLM on the DGX Spark); cloud endpoints are refused unless `--allow-cloud-model`:

```bash
python -m mcp_server.local_client \
  "Does the offer include the Non-collusive Tendering Certificate?" \
  --project <project-id> --tenderer Tenderer_03 --trace trace.json
# --model qwen3:8b@http://localhost:11434/v1 is the default (LOCAL_TEXT_MODEL)
# native runs: GITHUB_MODELS_BASE_URL=http://localhost:11434/v1 (not host.docker.internal)
```

It keeps the agent's guardrails: schema-validated JSON actions, a step budget, the
server's OCR budget, and a quote-on-page check — `found=true` is accepted only if the
quoted text is on a page the client actually read, so the failure mode is "not
found", never a fabricated citation.

**Claude Desktop (demo, synthetic projects only)** — `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tender-assistant": {
      "command": "/abs/path/tender_evaluation_assistant/.venv/bin/python",
      "args": ["/abs/path/tender_evaluation_assistant/mcp_server/server.py"]
    }
  }
}
```

`python -m mcp_server.server --list` prints what a given policy would serve. Measured
on the synthetic `--buried` case (12-page scan-only offers, first pass cached pages
1–4 only, agent off), same question, same tools, two drivers:

| driver (model reading the tool results) | tenderer | truth | outcome | steps | OCR calls | seconds | path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cloud — DeepSeek via `--allow-cloud-model` | Tenderer_01 | cert on p.11 | **found p.11**, quote verified | 3 | 1 | 32 | contents → `read_page(11)` (hint) → `ocr_page(11)` → finish |
| cloud — DeepSeek | Tenderer_03 | no cert | **not found** (correct) | 7 | 3 | 127 | contents → `ocr_page(11)`, `(12)`, `(5)` → search → finish(found=false) |
| local — `qwen3:8b`, cold cache | Tenderer_02 | cert on p.11 | **found p.11**, quote verified | 4 | 1 | 111 | contents → `ocr_page(11)` → finish rejected (no `page`) → finish(page=11) |
| local — `qwen3:8b`, warm cache | Tenderer_03 | no cert | **not found** (correct) | 3 | 0 | 158 | contents → `ocr_page(11)` (cached) → `read_page(12)` → finish(found=false) |
| local — `qwen3:8b`, warm cache, *before* the clearer rejection message | Tenderer_01 | cert on p.11 | budget exhausted — **no answer, no fabricated citation** | 10 | 0 | 243 | read p.11 four times, six `finish` attempts without `page`, all rejected |

Both drivers follow the same contents-page → page 11 path the pipeline's agent
takes. The 8B local model is slower and clumsier (it forgot the `page` field until
the rejection message named it), but the guardrails hold: every "found" carries a
quote verified on the cited page, and every failure is "not found" or "budget
exhausted", never an invented citation. Traces: `docs/mcp_traces/`. The cloud
driver here plays the role of Claude Desktop — structurally the same egress — on
a project created with the *synthetic* flag; unflagged projects are refused (tested
live over HTTP: no key → 401, unflagged → refused, synthetic → served).

## Measured across providers — Gemini on Vertex AI, DeepSeek, fully local

"Provider-agnostic" is a claim until it is measured. The model layer takes any
OpenAI-compatible endpoint per chain entry (`model@base_url`), and step 2 of the plan
added the two things a real comparison needs:

- **Vertex AI auth.** Google's OpenAI-compatible endpoint takes no API key: requests
  carry a short-lived OAuth token from Application Default Credentials
  (`gcloud auth application-default login`). `app/gcp.py` refreshes it ahead of
  expiry under a lock, because the parallel fan-out calls the model from several
  threads; `key_for()` never hands the AI Studio key to a Vertex host.
- **Cost accounting.** Every call is recorded per bid and per served model — prompt,
  cached and billable output tokens (Gemini's thinking tokens are billed as output,
  DeepSeek's cache hits are cheaper), seconds, dollars from a price table verified
  on the day (`app/usage.py`, overridable with `MODEL_PRICES`). The graph writes
  `work/usage/<bid>.json` and a `summary.json`; `GET /projects/{id}/usage` and the
  evaluation page show **$ per bid**; failed calls (fallbacks) are counted so a
  provider that silently shifted work to the local model cannot skew a number.

Same synthetic cases, same code, three configurations (`tools/stress_test.py --out`,
`tools/benchmark_buried.py`, `tools/ocr_compare.py`, tables by
`tools/compare_runs.py`; prices of 2026-09-09, standard tier):

<!-- STEP2_TABLES_START -->
**30-bidder stress case** (two scan-only bids; agreement = 116 checks against the seeded
ground truth: Stage I and II verdicts, arithmetic flags, unit prices):

| configuration | agreement | wall clock | rubric | extraction | $ total | $ / bid (mean · median) | tokens / bid | model s / bid (median) | failed calls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini 2.5 Flash on Vertex AI (text + OCR) | 116/116 (100.0%) | 82.6 s | 8.0 s | 72.4 s | $0.1621 | $0.0053 · $0.0047 | 4788 | 6.8 s | 0 |
| DeepSeek-V4-Flash + local qwen3-vl OCR | 116/116 (100.0%) | 115.2 s | 4.0 s | 109.0 s | $0.0303 | $0.001 · $0.0008 | 3294 | 2.9 s | 0 |
| fully local qwen3:8b + qwen3-vl:8b (laptop) | 116/116 (100.0%) | 2731.4 s | 98.4 s | 2631 s | $0.0 | $0.0 · $0.0 | 4145 | 131.3 s | 0 |
| Gemini on Vertex AI, **deployed on Cloud Run** (driven from the laptop through the IAM proxy, 2026-09-10) | 116/116 (100.0%) | 100.9 s (12.8 s of it upload) | 11.0 s | 76.0 s | $0.1621 | $0.0053 · $0.0047 | 4788 | 6.4 s | 0 |

**Buried-evidence benchmark** (12-page scan-only offers, schedules on pages 9–12, first
pass capped at 4 pages):

| configuration | run | certificate recall | false restores | price extracted | unclear w/ evidence | agent OCR pages | time | $ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Vertex Gemini | baseline | 0/2 | 0 | 0/3 | 0/9 | 0 | 30 s | $0.0323 |
| Vertex Gemini | agent | 2/2 | 0 | 3/3 | 9/9 | 15 | 228 s | $0.1209 |
| DeepSeek + local OCR | baseline | 0/2 | 0 | 0/3 | 0/9 | 0 | 585 s | $0.0038 |
| DeepSeek + local OCR | agent | 2/2 | 0 | 3/3 | 6/9 | 16 | 856 s | $0.0162 |
| fully local | baseline | 0/2 | 0 | 0/3 | 0/9 | 0 | 1106 s | $0.0 |
| fully local | agent (bids 1–2 of 3; 3rd ran away) | 0/2 | 0 | 1/2 | 0/6 | 10 | 3818 s | $0 |

*Fully local agent run: the 3-way-parallel attempt aborted on a 600 s timeout; run sequentially, the 8B model drove the tools for 27 and 37 minutes on bids 1–2 without finding either certificate (both exist on page 11) and restored one price; the third bid — the one with no certificate, where the search must exhaust its budget — ran away twice (14k generated tokens per request, with a 4k and then a 16k context) and was stopped. 0 false restores, no fabricated citation: the guardrails held, the search did not.*

**OCR, page by page** (the benchmark's 36 scanned pages, separate caches):

| chain | served | s / page | $ / page | ground-truth facts found | failed calls |
| --- | --- | --- | --- | --- | --- |
| A `qwen3-vl:8b` | qwen3-vl:8b | 48.7 | $0.0 | 14/14 | 0 |
| B `google/gemini-2.5-flash` | google/gemini-2.5-flash | 3.8 | $0.00105 | 14/14 | 0 |

Transcript similarity A vs B over 36 pages: mean 0.952, median 1.0, min 0.0. Missed by A: none. Missed by B: none. Empty transcripts — A: ['Tenderer_01 p.6']; B: none.

What the numbers say. All three configurations reach the **same verdicts** on both
cases — the deterministic layers decide, the model only extracts. Cloud models finish
30 bidders in under two minutes for **cents per tender** (Gemini ≈ $0.005 per bid,
DeepSeek ≈ $0.001, the rubric included); the fully local 8B stack reaches the same
100% for $0 but took **45 minutes in two passes** on the laptop: with four bids in
parallel a local OCR page exceeded the 10-minute client timeout at bid 29/30, and the
run was resumed from its checkpoints sequentially (`MAX_PARALLEL_BIDS=1`,
`LLM_TIMEOUT_S`) — the checkpointing did exactly what it is for. The local 8B model
also needed one more deterministic guard: it cited a contents entry as evidence for
three checklist items, which grounding now demotes in code — and it cannot drive the
evidence-search agent on this laptop (see the benchmark note; `LLM_MAX_TOKENS` now
bounds a runaway generation, and Ollama's default 4k context, which silently
truncated the agent's transcripts, needs a 16k model variant). Local OCR recovered every
ground-truth fact Gemini did, blanked one filler page, and is 13× slower per page.
These laptop numbers bound the *demo*; production inference on the client's DGX is a
different class of hardware. Metered spend for the whole step: **$0.35** (Vertex) +
**$0.05** (DeepSeek).
<!-- STEP2_TABLES_END -->

## The shared demo on Azure — private, scale-to-zero

The whole stack runs as **one private Azure Container Apps app** (`deploy/azure/`,
checklist G4):
- **Three containers:** `web`, the React UI behind nginx, as ingress; the API; and the worker.
- **Data:** Postgres Flexible Server and an Azure Files share for the project files.
- **Model:** Azure OpenAI through the gateway, on synthetic projects only.
- **Access:** Entra ID sign-in in front of every path, for assigned users only.
- **Deploys** by hand from the `deploy-azure` workflow, through OIDC with no stored cloud secret.

Setup, costs, security and teardown are in [`deploy/azure/README.md`](deploy/azure/README.md).

Until 2026-09-26, the prototype stack ran as a private Cloud Run service on GCP. The
30-bidder case measured 116/116 agreement, 100.9 s end to end and $0.16 of model time
(the Cloud Run row above). That deployment and `deploy/cloudrun/` are retired; git
history has them.

## Client-site (production) deployment

The product is NDA-bound to **local** deployment — real tender/bid documents never
leave the client's network. The same compose stack is the deliverable for the client's
DGX Spark: stand up vLLM serving the local models, point `GITHUB_MODELS_BASE_URL` at
it in `.env`, and build the images for ARM (`docker compose build` on the GB10, or
`--platform linux/arm64`). Set a strong `API_KEY` whenever the services are reachable
by anyone but you, and keep port 8000 (API) firewalled — the UI on 8080 is the only
thing users need.

## Demo ⇄ production mapping

| Demo (this repo)                      | Production (client site)                          |
| ------------------------------------- | ------------------------------------------------- |
| DeepSeek API `deepseek-chat` (text), or Gemini 2.5 Flash on Vertex AI | Qwen3.6-35B-A3B / DeepSeek-V4-Flash via vLLM |
| Ollama `qwen3-vl:8b` vision OCR, or Gemini 2.5 Flash on Vertex AI | Qwen3-VL-30B-A3B (MoE) page OCR, batched |
| Docker on a laptop (x86/arm)          | Same compose stack on DGX Spark GB10 (arm64)      |
| Synthetic fixtures                    | Real tender/bid sets, fully local                 |

Known demo limitations: the first-pass OCR cap per document (`MAX_OCR_PAGES` /
`--max-ocr-pages`, default 8 — the evidence-search agent reads further pages on demand
within `AGENT_OCR_PAGES`), local OCR speed (measured 48.7 s per page on `qwen3-vl:8b`
on the laptop; 3.8 s on Gemini), and no Stage III–V yet (technical marking / combined score —
phase 2).

## Licence, before you reuse this

The repository is licensed under the **GNU AGPL-3.0** ([LICENSE](LICENSE)). The choice
was constrained rather than free: `app/parsing/` depends on two Artifex packages (decision
[0002](docs/decisions/0002-pymupdf-licences.md)):

| Package | Licence |
|---|---|
| `pymupdf` | GNU AGPL-3.0, or an Artifex commercial licence |
| `pymupdf-layout` | PolyForm Noncommercial 1.0.0, or an Artifex commercial licence |

So: anyone using this **commercially** needs commercial licences for both, or must
replace `app/parsing/`. No application code outside `app/parsing/` imports either package
(only one parser test, `test/parsing/test_layout_parser_tables.py`), so that replacement stays a
contained change. A hosted demo carries AGPL obligations — the
running service must offer its source, which a public repository satisfies.

The AGPL covers our own code. It does not change `pymupdf-layout`'s terms: its
noncommercial licence still applies to anyone who runs the parser.

## Who built what

Two people, working to a written contract (`docs/api_contract.md`) with the schema agreed
before the code, so both halves could be built in parallel.

**Nasi Purcell** — the document parser and locator (L0): turning a tender's PDFs into an
addressable node tree, splitting combined documents, resolving the citations a schedule
makes into that tree, and locating the Completeness Check Schedule's items. The rule
engine and its templates. The React three-column review UI: the Rules window with full
editing, Stage I and II with corrections, Scoring and Report, and the browser review flow.

**Chenyu Fang** — the original prototype this repository grew from (the Streamlit UI, the
MCP server, and the Vertex AI / Cloud Run demo); the API backend and the API contract
(`backend/`, `docs/api_contract.md`); the pipeline and the worker: the LLM layers that read
a tender into a draft rule set (L1 to L4) and a bid into checked fields (V0 to V5), the job
queue and its recovery, the LLM gateway with its cache, budget and data-class allowlist;
pricing, the Word reports, and the synthetic evaluation cases.

Decisions that shaped the build are recorded as they were taken, with the numbers behind
them: [`docs/decisions/`](docs/decisions/), and the running record in
[`docs/merge_plan_checklist.md`](docs/merge_plan_checklist.md).

## Authors

- Nasi Purcell
- Chenyu Fang

Cite this work with the metadata in [`CITATION.cff`](CITATION.cff).
