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

**Tests** — 654 Python (637 offline, 17 against Postgres), 73 browser-component (Vitest), 4
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
one gateway (`app/llm/gateway.py`), which applies the project's data class (confidential
text never leaves the local network), a cache, a daily budget and a rate limit.

| Runs as | What it is |
|---|---|
| `web` | the React review UI (Rules, Stage I, Stage II, Scoring, Report), on :8080 |
| `backend` | FastAPI (`backend/`), the routes of [`docs/api_contract.md`](docs/api_contract.md), on :8000 |
| `worker` | Procrastinate workers running the three jobs: `ruleset_build`, `vendor_check`, `evaluate`. Checkpointed after every step, so a killed job resumes; `--scale worker=N` adds more |
| `postgres` | versioned rule sets, results, the audit events, runs and their steps, the job queue, and the gateway's cache, budget and rate limit |
| `/data` volume | the projects: `meta.json`, the uploaded PDFs, rendered pages, node tables and the Word reports |

## Quickstart

```bash
cd tender-evaluation-assistant
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1) The tests: offline, no network, no keys, no client data.
.venv/bin/python -m pytest test/ -q

# 2) The whole stack in Docker (Postgres, the API, the worker, the UI), then the synthetic
#    tender through it: a project, the rule set confirmed by a second person, one check per tenderer.
cp .env.example .env              # the models; local Ollama by default (see below)
docker compose up -d --build      # UI http://localhost:8080
.venv/bin/python tools/check_synthetic_case.py \
    --ruleset test/data/synthetic_tender/ruleset_all_items.json   # add --key when API_KEY is set
```

`test/data/synthetic_tender/` is the synthetic tender: 17 tender documents with running headers,
PART numbering and a Completeness Check Schedule with items (a) to (o), and four offers, with
the answers in `ground_truth.json`. Tenderer C leaves out the Non-collusive Tendering Certificate
and fails Stage I. Tenderers B and D are scans, and page 9 of each carries an instruction to
"any automated review system" to pass every item, which the check must ignore. Tenderer D is not
the manufacturer, leaves out its board resolution and prices in US$. The real-size tender is in
`test/data/synthetic_tender_full/`; `tools/make_synthetic_tender.py [--full]` regenerates both.

**LLM backend**: any OpenAI-compatible endpoint, configured entirely in `.env`. Two
ready-made setups: fully **local Ollama** (free, keyless —
`ollama pull qwen3:8b && ollama pull qwen3-vl:8b`), or a cheap **cloud text primary**
such as DeepSeek (`TEXT_MODEL=deepseek-chat@https://api.deepseek.com/v1` +
`DEEPSEEK_API_KEY`) with local Ollama as automatic fallback — synthetic/sanitized
documents only on any cloud path. Hosted endpoints pick their key by hostname
(`DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `AZURE_OPENAI_API_KEY`, `DASHSCOPE_API_KEY`,
`ZHIPU_API_KEY`), so a fallback chain can span providers. Chains
(`*_MODEL_FALLBACKS`) are tried automatically when the model before them fails.
Production swaps the base URL for vLLM on the client's hardware. (The original demo
backend, GitHub Models, was retired in 2026; the base URL's variable keeps its name,
`GITHUB_MODELS_BASE_URL`.)

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
app/                the library the API and the worker share
  config.py         env + model configuration (the cloud ⇄ local vLLM swap point)
  db.py             plain-SQL migrations (migrations/NNN_name.sql, up and down sections)
  ingest.py         PDF classification (text vs scan), text extraction, VLM OCR + cache
  llm/              every model call: the OpenAI-compatible client (fallback chains, JSON-validated chat,
                    OCR), the gateway every pipeline call goes through (endpoint policy by data class,
                    cache, per-project daily budget, shared rate limiter; its Postgres backends), token
                    and $ accounting with the price table, Vertex AI auth
  parsing/          the tender parser (L0): PDF loading, the layout-model node tree, the document
                    split, and the citation resolver; the only code that imports PyMuPDF
  rulesets/         the rule-set builder (the `ruleset_build` pipeline): locate (L0), match to a template
                    (L1), fill its slots (L2), draft novel rules and additions (L3), coverage gaps (L4);
                    the template library (templates/), editing, versions and diffs; the shared contract
                    in schema.py, changed only by a `contract` PR
  checks/           the vendor check for every form of a bid, layer by layer: V0 page rendering, V1 triage,
                    V2 resolve, V3 extract (the form menu in forms.py), V4 verify, V5 the bounded search
                    agent, the engine bridge; reviewer corrections, pricing in the tender's currency (over
                    the deterministic price engine), the Word reports; the `vendor_check` pipeline
  engine/           Nasi's rule engine, ported unchanged from Bidding-AI-expert@7e8e273
  jobs/             the run queue and check worker (Procrastinate on Postgres): step pipelines with
                    per-step checkpoints, pause/resume, results + corrections, `python -m app.jobs.worker`
backend/            FastAPI service: the routes of docs/api_contract.md, + Dockerfile
web/                the review UI (React, Vite): Rules, Stage I/II, Scoring, Report; nginx image for compose
docs/               the API contract and its OpenAPI snapshot, decisions/ (orchestrator, PDF licences, tender
                    formats), evals/ (parser, rule set, vendor check, verification, bid keys), the merge-plan
                    checklist; archive/ (the prototype, dated); images/ for this README
migrations/         SQL migrations applied by app.db.migrate (the worker runs it at start)
docker-compose.yml  Postgres, the API, the check worker (same image) and the UI together
deploy/azure/       the shared demo on Azure: Bicep, setup/deploy scripts (workflow: .github/workflows/deploy-azure.yml)
spikes/             the orchestrator spike behind decision 0001 (LangGraph), run by test/jobs/
test/               637 offline tests and 17 against Postgres: parser, rule sets, checks, engine,
                    jobs, gateway, API and its contract (no network, no client data)
tools/              the synthetic tender generator (tender and bids, with ground truth) and its rule set, the
                    PDF generator; the evals (parser, rule set, bid key scoring), the end-to-end check through
                    the API, the OCR comparison, the rule-file splitter
LICENSE             GNU AGPL-3.0
```

## Service mode — frontend + backend

The API's requirements are `backend/requirements.txt`; root `requirements.txt` is the dev
aggregate (the API's plus pytest and the orchestrator spike's LangGraph). The image installs
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
   by a second read of a scan. Once a rule set is confirmed, the bounded search agent looks again for any Part A
   form no page was labelled as, and the rules engine decides each item.
3. **`evaluate`** re-decides every stored result against a newly confirmed rule-set version, with no model call.

A reviewer corrects any field in Stage I or II (the model's value is kept beside the correction, with who and why),
decides any check the engine left to a person (pass, the Authority may ask later, or disqualified, with a reason), and
confirms the review. A blank the model read on a form that is there never disqualifies until a person confirms it. Scoring needs a confirmed rule set, and the Word reports also wait until every
review is confirmed. `GET /projects/{pid}/jobs`
follows the jobs, and `GET /projects/{pid}/bids/{t}/results` has the fields, the verdicts and their evidence. Page
images open by signed links. An upload is capped from its declared length before any of it is received
(`MAX_UPLOAD_MB`, default 512, per request). The measurements behind the design are in
`docs/decisions/0001-orchestrator.md`.

Project data lives in `./data/` on the host (a bind-mounted volume). The prototype this
grew from (one LangGraph run with a derived rubric, an evidence-search agent and a Streamlit UI)
and the MCP server over its tools were removed at S5; what they did and measured is in
[`docs/archive/`](docs/archive/).

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
([`docs/archive/prototype_2026-09.md`](docs/archive/prototype_2026-09.md)). That deployment
and `deploy/cloudrun/` are retired; git history has them.

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

The demo's own limit is local vision speed: the prototype measured 48.7 s per OCR page on
`qwen3-vl:8b` on the laptop, and 3.8 s on Gemini, and the vendor check reads every page of an
offer once, at triage.

## Limitations

Stated, not fixed (checklist J11, item 13):

- **Sign-in.** There is no single sign-on with a client's own identity provider (OIDC). The demo signs people in with Azure in front of the app, and the API trusts one shared key. There are no per-user roles yet; they come after the S4 run (J11, item 12).
- **The model budget.** The gateway checks the daily budget before a call and adds the cost after it, so workers running at once can go slightly over it. A rate-limited job is retried with a growing wait, but a single call is not.
- **Type checking.** Ruff and the tests run in CI, but no type checker does.
- **Metrics and alerts.** The Azure demo writes its logs to Log Analytics. There are no dashboards or alerts.
- **Stages III to V.** Technical marking and the combined score aren't built.
- **PyMuPDF.** The parser depends on PyMuPDF and `pymupdf-layout`, whose licences limit reuse (see [Licence](#licence-before-you-reuse-this)). Replacing them is not planned.
- **Conditions.** A rule's `condition` ("where the tenderer is not the manufacturer") is recorded but not evaluated. Such a rule never disqualifies on a blank; a reviewer confirms instead.

## Next: tenders in other formats

The project stays on procurement, but tenders don't all look alike. The parser was tuned on one authority's
digital PDFs, with numbered clauses and a lettered Completeness Check Schedule. Today:
- only PDFs are read;
- a scanned page, which has no text layer, is skipped without a warning;
- every new layout adds special cases to one parser: "PART 1", "Part A", "Table A" and "第 4 部分" are each a
  hand-written pattern, and a tender that says "Section I" or numbers its checklist "Part 1/2/3" needs another.

The plan, proposed in [decision 0003](docs/decisions/0003-tender-format-router.md):

```mermaid
flowchart LR
    F["📄 Tender files<br/>PDF · scans · Word ·<br/>spreadsheets"]
    R{"<b>router</b><br/>format + layout profile<br/>+ confidence"}
    LP[("<b>layout profiles</b><br/>PART 1 · Part A · Section I<br/>Clause 12 · Article 12 · (a)<br/>what each checklist Part means")]
    U["✋ unsure:<br/>a person decides"]

    subgraph PARSERS["one parser per format · each with its own eval"]
        direction TB
        P1["digital PDF,<br/>numbered clauses<br/><i>(today's parser)</i>"]
        P2["scanned PDF<br/>(OCR first)"]
        P3["Word (DOCX)"]
        P4["table-first<br/>schedules"]
    end

    N["<b>node table</b><br/>one contract,<br/>one validator"]
    L["<b>locate + L1–L4</b><br/>schedule items,<br/>template match, slots,<br/>novel rules, gaps"]
    T[("<b>shared template library</b><br/>keyed by form,<br/>grows with every tender")]
    RS["<b>rule set</b><br/>per tender"]

    F --> R
    R --> P1 & P2 & P3 & P4
    R -. low confidence .-> U
    P1 & P2 & P3 & P4 --> N --> L --> RS
    LP -. names the headings .-> PARSERS
    T --> L
    RS -. "a new form, confirmed:<br/>saved as a template" .-> T

    classDef llm fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef code fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef human fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef docs fill:#f3f4f6,stroke:#9ca3af,color:#374151
    class F docs
    class R,P1,P2,P3,P4,N code
    class L,RS llm
    class U human
    class T,LP docs
```

1. **A router identifies each document's structure first.** It looks at the file type, whether pages have a text
   layer, one document or several in one file, language, numbering style and tables, and records a format label
   with its confidence. When it's unsure, a person is told rather than a guess being made.
2. **One parser per format**, each with its own answer keys and eval. Today's parser becomes the first, for
   digital PDFs with numbered clauses. Scanned PDFs, Word files and table-first schedules are the likely next ones.
   **A layout profile tells a parser what the structure is called.** It is a small data file per tender family:
   heading names and numbering (`PART 1`, `Part A`, `Section I`, `Clause 12`, `Article 12`, `(a)`), running headers,
   and how the checklist is found and what each of its Parts means. A tender that names its sections differently
   then needs a new profile, not a parser change. Today's hand-written patterns become the first profile.
3. **One node-table contract.** Every parser produces the same nodes, checked by one validator, so locating the
   schedule, the rule-set layers L1–L4 and the UI don't change when a format is added.
4. **One shared template library,** keyed by form, not by file layout, and extended with every tender. A form seen
   before reuses its template. A new one is drafted by L3, confirmed by a person, and saved as a template.

The first step changes no behaviour: put today's parser behind a parser interface, write down the node-table
contract as a validator, and keep the Tender 1–3 numbers identical.

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
