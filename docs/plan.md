# Tender Evaluation Assistant — Plan

*The single plan file for this repo (supersedes `plan_report.md`, `plan_report_zh.md`
and `agent_upgrade_plan.md`). Status date 2026-09-08 · repo private · demo phase and
agent upgrade complete; next batch (§4) proposed, not started.*

---

## 1. Product and original plan (summary)

**Who / what.** Procurement assistants supporting a public Tender Assessment Panel
(TAP), reached only through the client's IT. Per procurement: review 20–60 bidders'
offers against *that tender's own rules* and produce the procurement review report —
Price Summary (two formats), Stage I/II conclusions, detailed evaluation record — as
**editable English Word** files. Input: one tender document set (digital PDFs) plus one
offer per bidder (**scanned PDFs**, 60–400 pages). Strict NDA: real documents are
processed **on-premises only** (client DGX Spark GB10); no cloud egress.

**Three findings that shaped the design** (from the client's sample cases): every
tender defines its own checklist, essential requirements and price formula (`D × M`
cost-effectiveness vs unit price × quantity) → the rubric is derived per project and
human-confirmed; bid documents are pure scans (measured: 62 pages, 0 extractable
characters) → vision OCR is core; the TAP audits arithmetic (a sample flags a quoted
total that fails to tally) → deterministic checking is a product feature.

**Design principles.** LLMs extract and classify, code calculates and ranks; every
negative finding carries page-cited evidence a reviewer can open; humans confirm the
rubric and can correct any extraction (corrections are final); the output is a draft
for the TAP, never an auto-final decision; the offline test suite runs with zero
network and zero real data.

**Stack.** Python 3.12 · pydantic v2 contracts · pypdf / pypdfium2 · python-docx ·
FastAPI + Streamlit (two Docker images, arm64-ready) · one OpenAI-compatible LLM
client with cross-provider fallback chains. Demo endpoints: DeepSeek (text) + local
Ollama `qwen3-vl:8b` (vision); production: vLLM on the DGX serving Qwen3.6 /
DeepSeek-V4-Flash and Qwen3-VL — a base-URL swap, no code change.

**Milestones and status**

| Phase | Content | Status |
| --- | --- | --- |
| P0 Understanding & proposal | Business analysis of 3 sample cases, product design | ✅ |
| P1 Stage I/II demo | Pipeline, review UI, Docker split, 30-bidder stress test | ✅ |
| P2 Correctness hardening | Targeted retrieval, adversarial verification, CI + pinned deps *(delivered)*; audit trail per finding, deterministic FX table *(not yet)* | ◐ |
| — Agent upgrade (§2) | LangGraph orchestration, evidence-search agent, grounding | ✅ |
| P3 Local inference | vLLM on DGX Spark, Qwen3-VL batch OCR with resume, throughput measurement | ⏳ client hardware |
| P4 Golden regression & fidelity | Regression vs the client's real historical reports; Word templates matched to client format | ⏳ client materials |
| P5 Production 1.0 | Batch queue for 60-bidder runs, multi-project ops, runbook, UAT | ⏳ |

**Open client items:** Technical Marking Sheet sample (missing from delivered
materials — blocks Stage III), bid folder conventions, Stage III–V scope for 1.0,
turnaround expectations, more sanitized cases for regression, DGX access window.

## 2. Agent upgrade (summary)

**Decision.** Keep the top-level flow a fixed workflow (auditable, predictable) and
add agency in exactly one place where *search* is the problem: findings still
missing/unclear after verification, on bids whose relevant pages sit beyond the
initial OCR cap. Story that is true and defensible: *a LangGraph workflow with durable
human-in-the-loop checkpoints, containing one bounded tool-using sub-agent, with
deterministic guardrails on every number.*

| Phase | Delivered |
| --- | --- |
| A Graph wrapper | `app/graph.py`: `StateGraph` over the existing functions; SQLite checkpointer per project; `interrupt()` at rubric confirmation and extraction review; `Send` fan-out per bid with `max_concurrency`; crash recovery keeps finished bids. Exit test: `evaluation.json` byte-identical to the previous orchestrator. |
| B Evidence-search agent | `app/tools.py` (list / search / read pages, **on-demand OCR** within a per-bid budget), `app/agent.py` (schema-validated `AgentAction` per step via the same `chat_json` path — endpoint-agnostic; step budget; initial observation = page listing + contents page; trace persisted), `app/grounding.py` (a citation of an unread page is not evidence; refutations and agent finishes must quote text on the cited page). Benchmark case `make_demo_case.py --buried` + `tools/benchmark_buried.py`. |
| C Service + UI | `POST /run` → paused → `POST /resume`; `GET /graph`; agent trace endpoint; `waiting` job state; Confirm-&-continue buttons, trace viewer, 🔎 badges. Legacy thread-pool path, `/rubric/derive`, `/extract` and the sequential CLI **removed**. Atomic `status.json` writes. |
| D Docs | README, detailed specification, interview prep updated with measured numbers. Docker images rebuilt and verified. |

**Guardrails (what the agent may and may not do):** read-only tools; `AGENT_MAX_STEPS`
per finding, `AGENT_OCR_PAGES` per bid; `finish(found=true)` accepted only if the
quote is on the cited page; may restore a missing document with verified evidence
(same trust level as the verification pass); attaches evidence + a *suggested* verdict
to "unclear" findings but never changes a compliance verdict; triggers a targeted
price re-extraction when it reads a Price Schedule the first pass never saw.

**Ops note.** After a Docker Desktop update, `docker pull` / `compose build` hung on the
macOS credential helper from non-interactive shells. Workaround: `DOCKER_CONFIG`
pointing at a directory holding `config.json` = `{}` and a `cli-plugins` symlink to
`~/.docker/cli-plugins` (anonymous pulls, compose plugin still found).

## 3. Experiments and results

All on synthetic, deterministic cases with seeded ground truth (never client data).

| # | Experiment | Setup | Result |
| --- | --- | --- | --- |
| 1 | 30-bidder stress test | GitHub Models cloud text, sequential extraction | **287 s** end to end; **100%** agreement: 4/4 missing certificates (one inside a scan-only bid), 3/3 shelf-life breaches, 3/3 arithmetic errors; cheapest non-conforming bid ranked #1 on price but correctly not recommended |
| 2 | Provider retirement mid-project | GitHub Models returned HTTP 410 → fallback chain to local Ollama (`qwen3:8b`, `qwen3-vl:8b`) | Same verdicts, zero code change; rubric 80–133 s, 3-bid evaluation 266–337 s locally |
| 3 | DeepSeek as text primary | `deepseek-chat` (serving DeepSeek-V4-Flash) + local OCR | Rubric **6 s** (was 133 s); 3-bid case incl. scanned OCR + verification **55 s** (was ~337 s) |
| 4 | P2 quality layers, live | Verification pass on a genuinely missing certificate | Upheld the negative (no false restore); evaluation from stored extractions ~5 s (no LLM) |
| 5 | Phase A graph wrapper | Demo case through the graph, then legacy replay on the same checkpoints | 59 s live; `evaluation.json` **byte-identical** |
| 6 | Buried-evidence benchmark, run 1 | 12-page scan-only offers, schedules on pp. 9–12, contents page *named* the certificate, first pass capped at 4 pages | Certificate metric did not discriminate (2/2 both runs — the contents mention counted as presence); prices 0/3 → 2/3; agent wasted OCR on filler pages (18 pages) |
| 7 | Run 2, after initial-observation + generic contents entry | Same case, contents entry now "Certificates and Declarations" | Agent followed the contents page (right pages only); **first-pass false positive discovered**: "present on page 11" claimed without reading page 11 → citation grounding added |
| 8 | Run 3, final | Grounding on; agent off vs on | off: certificate recall 0/2, prices 0/3, unclear findings with evidence 0/9 → on: **2/2, 0 false restores, 3/3, 8/9**; 17 OCR pages (~6 per bid) |
| 9 | 30-bidder regression through the graph, agent on | Same seeded case as #1 | **116 s**; all seeded defects matched exactly; agent ran for the 4 truly-missing-certificate bids and restored nothing |
| 10 | Orchestrated run/resume flow, live | Native services, then the rebuilt Docker stack | Rubric derived + paused **4 s**; 3 bids in parallel incl. OCR + agent **54 s**; evaluation + reports **2 s**; edits made while paused honoured |
| 11 | Offline test suite | Grown across phases | 22 → 30 → 45 → 50 → **69** tests, all offline, CI on every push |

## 4. Next plan — MCP server, Vertex AI Gemini backend, Cloud Run

Goal: turn "provider-agnostic, zero code change" into *measured* multi-provider
claims, and expose the bounded tool layer as a product surface. Order chosen by value
per hour: step 1 needs nothing from outside; step 2 carries the substantive claim;
step 3 adds the "deployed on GCP" line and can be dropped if budget or time is tight.
Azure is deliberately skipped (one cloud, done properly).

### 4.1 Step 1 — MCP server over the read-only tools (0.5–1 day)

**Steps**
1. `mcp_server/server.py` on the official `mcp` Python SDK (FastMCP), pinned. Tools
   mirror `app/tools.BidTools` one-to-one: `list_pages`, `search_pages(query)`,
   `read_page(page, file?)`, `ocr_page(page, file?)`; plus `list_bids()` and
   `select_bid(project, tenderer)` so a client can navigate a project. Documents load
   through `load_folder` with the project's own OCR cache; the OCR budget is
   `AGENT_OCR_PAGES`.
2. Transports: stdio (Claude Desktop / Cursor) and streamable HTTP guarded by
   `X-API-Key` (reuse the backend's key).
3. Tests: in-process MCP client session exercising all tools, the OCR budget, and the
   "skipped page → use ocr_page" hint; server must never write except to the OCR cache.
4. README section with a Claude Desktop config snippet and a screenshot of a
   tool-walked answer.

**Experiment / acceptance.** Connect Claude Desktop to the demo project and ask *"Does
Tenderer_C's offer include the Non-collusive Tendering Certificate?"* — expect a
tool trace (list → search → read/OCR) and an answer with page citations; the same
question on `buried_case` should show the contents-page → `ocr_page(11)` path.

**Requirements / tools.** `mcp` SDK; Claude Desktop or Cursor for the demo (optional);
no cloud. **API spend:** none (local tools; OCR through the configured vision chain —
local Ollama is free).

**Difficulties.** SDK API churn (pin, thin adapter); a stdio server must not print to
stdout (log to stderr); interactive OCR latency on local `qwen3-vl` (~25 s/page —
say so, or point the vision chain at a cloud model for the demo); expose only
synthetic projects on any network transport.

### 4.2 Step 2 — Vertex AI Gemini as a measured fourth backend (1.5–2 days)

**Steps**
1. Auth: Vertex's OpenAI-compatible endpoint
   (`https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/endpoints/openapi`,
   model names like `google/gemini-2.5-flash`) uses short-lived OAuth bearer tokens,
   not API keys. Extend `Config.key_for()` to return a *token provider* for
   `aiplatform.googleapis.com` (google-auth Application Default Credentials, refreshed
   before expiry; the client is recreated when the token changes). Keep
   `generativelanguage.googleapis.com` → `GEMINI_API_KEY` (AI Studio) as the keyed
   alternative — note both hostnames contain "googleapis", so the match order matters.
2. Chain entries for text *and* vision via Vertex; local Ollama stays the fallback.
3. Token and cost accounting in `app/llm.py`: capture `usage` per call, per model;
   price table (`MODEL_PRICES`, JSON in `.env`, verified against the provider's page on
   the day); totals per bid written next to the extraction → **$ per bid**, tokens per
   bid, calls per bid.
4. Experiments (below); publish the table in README / spec / interview prep.

**Experiments.** Run the 30-bidder stress case and the buried benchmark under three
configurations: (a) DeepSeek text + local OCR (current), (b) Gemini text + vision via
Vertex, (c) fully local. Record ground-truth agreement, wall-clock, per-bid latency
(median), $ per bid, and OCR quality on the scan-only bids (page-level diff of the
transcripts between qwen3-vl and Gemini).

**Requirements / tools.** GCP project with billing; Vertex AI API enabled; a region
serving Gemini 2.5 Flash (`us-central1` or `asia-southeast1`); `gcloud auth
application-default login` on the Mac (or a service-account key); IAM role *Vertex AI
User*; `google-auth` package.

**API spend (estimate — verify pricing at run time).** 30-bidder run ≈ 0.5 M input +
0.05 M output tokens; buried benchmark ≈ 40 page images + text. At Gemini 2.5 Flash
list prices this is roughly **$0.30–0.50 per full stress run** and cents for the
benchmark; with reruns and the three-way comparison, budget **≤ $5**. Vertex has no
free tier; AI Studio keys do, and use the same OpenAI-compatible API if a free route is
preferred (the *measured GCP* claim then reads "Gemini via AI Studio").

**Difficulties.** Token expiry (1 h) mid-run → refresh logic must be thread-safe under
the parallel fan-out; new-project quotas (requests/min) can 429 under 4-way
parallelism → the fallback chain would silently shift work to local models and skew
latency, so log fallbacks per call and set `MAX_PARALLEL_BIDS` to the quota; JSON-mode
and image-input support on the compat endpoint need a smoke test before the benchmark;
agreement may differ across models — the validation retry and grounding stay on, and
any disagreement is reported, not hidden; pricing pages change — record the prices
used alongside the results.

### 4.3 Step 3 — Cloud Run deployment, scoped honestly (1.5–2 days, optional)

**Steps**
1. Build `linux/amd64` images (`docker buildx`, QEMU on the arm64 Mac) and push to
   Artifact Registry.
2. Backend service: `min-instances=1`, **CPU always allocated** (background jobs must
   keep running between requests), 2–4 GiB, request timeout 60 min, concurrency ≤ 4;
   a **GCS bucket mounted at `/data`** (Cloud Run volume mount) for uploads, JSON
   checkpoints, OCR cache and reports; secrets (`API_KEY`, provider keys) from Secret
   Manager; service account with *Vertex AI User* + *Storage Object User*.
3. Frontend service: `BACKEND_URL` = backend URL, `PUBLIC_BACKEND_URL` = its public
   URL (the browser-direct folder upload and evidence links need it), `API_KEY`;
   backend `CORS_ORIGINS` = frontend URL; session affinity on for Streamlit websockets.
4. Keep LangGraph's SQLite checkpointer on the instance's local disk (SQLite on a FUSE
   mount is unsafe). Consequence, stated plainly: a restart loses only *pause state*;
   the JSON checkpoint files on GCS make the run resumable via `POST /run` without
   redoing finished LLM work.
5. Run `tools/stress_test.py` against the Cloud Run URL from the laptop and record the
   "measured on GCP" numbers (note upload time separately); then scale to zero or
   delete the services.

**Experiment / acceptance.** The 30-bidder stress case completes through the deployed
services with the same ground-truth agreement; latency and $/bid recorded alongside
step 2's table; a screenshot of the UI on the Cloud Run URL.

**Requirements / tools.** Same GCP project; `gcloud`, Artifact Registry, Secret
Manager, a GCS bucket, a budget alert. **Spend:** an always-on 1 vCPU / 2 GiB instance
≈ **$1.5–2 per day** (keep it up 1–2 days → ≈ $5); registry storage and egress
negligible; plus step 2's model usage. Total for steps 2 + 3 **≤ $15**.

**Difficulties.** SQLite-on-GCS is the trap above; GCS FUSE latency on many small
files (OCR cache, page renders) — acceptable, but measure; instance recycling mid-run
(resumable by design, but the demo should not rely on luck — keep `max-instances=1`);
cold starts of a heavy image (pypdfium2/Pillow, ~10 s); cross-architecture builds are
slow on an arm64 Mac; Streamlit needs session affinity and HTTP/1; the confidentiality
story must be explicit — synthetic data only, production stays on the client's DGX.

### 4.4 Step 4 — Docs and interview material (0.5 day)

README (MCP section, multi-provider table, Cloud Run trade-offs), detailed
specification (new modules, endpoints, results), interview prep (MCP and multi-cloud
Q&As, cost-per-bid numbers), this file (results into §3).

### 4.5 Summary

| Step | Effort | Spend | Needs from the owner |
| --- | --- | --- | --- |
| 1 MCP server | 0.5–1 day | $0 | — |
| 2 Vertex AI Gemini + measurement | 1.5–2 days | ≤ $5 | GCP project with billing, Vertex API on, ADC login, region |
| 3 Cloud Run | 1.5–2 days | ≈ $5–10 | same project, budget alert |
| 4 Docs | 0.5 day | $0 | — |

## 5. Standing backlog (unchanged, client-gated)

vLLM bring-up on the DGX Spark and pages/hour measurement (P3); golden regression
against three real historical cases — the honest accuracy test (P4); Word template
fidelity to the client's exact formats (P4); batch queue for overnight 60-bidder runs
and multi-project operations (P5); per-finding audit trail and deterministic FX table
(P2 leftovers); Stages III–V once the marking sheet arrives.
