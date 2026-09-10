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
| 11 | Offline test suite | Grown across phases | 22 → 30 → 45 → 50 → 69 → 81 → **91** tests, all offline, CI on every push |
| 12 | MCP tools, two drivers (2026-09-08) | `buried_case` as a synthetic project, first pass cached pages 1–4 only, agent off (pipeline says "certificate missing" for all three bidders); same question, same tools over the MCP server; cloud driver = DeepSeek through the local client with `--allow-cloud-model` (Claude Desktop is not installed on this Mac; structurally the same egress), local driver = `qwen3:8b` on Ollama | Cloud: Tenderer_01 **found p.11** in 3 steps / 32 s, Tenderer_03 **not found** (correct) in 7 steps / 127 s. Local, cold cache: Tenderer_02 **found p.11** in 4 steps / 111 s (one rejected finish — it omitted `page`); Tenderer_03 **not found** in 3 steps. Both followed the contents page → page 11 path. One local run before the rejection message was made explicit exhausted its 10 steps (six `finish` attempts without `page`) — no fabricated citation. Traces in `docs/mcp_traces/` |
| 13 | MCP confidentiality guard, live | HTTP transport without `ALLOW_CLOUD_CLIENTS` / without `API_KEY`; guarded server probed with and without the key on an unflagged and a synthetic project (`MCP_LOCAL_MODEL=1` also set) | Refused to start (exit 2) in both misconfigurations; no key → 401; unflagged project → refused even with the local flag; synthetic project → served. `--list` withholds the 8 unflagged projects on this machine (count only) |
| 14 | Three backends, 30-bidder stress (2026-09-09) | Same case and code; Gemini 2.5 Flash on Vertex AI (text + OCR, OAuth via ADC), DeepSeek-V4-Flash + local qwen3-vl OCR, fully local qwen3:8b + qwen3-vl:8b; agreement scored by `tools/score_case.py` against seeded ground truth; cost from the per-call ledger | **116/116 (100%) on all three.** Vertex **82.6 s**, $0.162 ($0.005/bid, 4.8k tokens/bid, 6.8 s model time/bid); DeepSeek **115 s**, $0.030 ($0.001/bid); fully local **2731 s in two passes** (first pass aborted at bid 29/30 on a 600 s OCR timeout under 4-way contention, resumed from checkpoints sequentially), $0, 131 s model time/bid; 0 failed calls on the cloud runs |
| 15 | Three backends, buried benchmark | `--buried` case, first pass capped at 4 pages, agent off vs on | Vertex: 0/2→**2/2** certs, 0 false restores, 0/3→**3/3** prices, 0/9→**9/9** evidence, 30 s / 228 s, $0.03 / $0.12. DeepSeek + local OCR: 2/2, 0 false, 3/3, **6/9**, 585 s / 856 s, $0.004 / $0.016. Fully local baseline 1106 s with **1 first-pass false positive** (contents entry cited as evidence — now a deterministic grounding rule); agent run: aborted under 3-way parallelism (600 s timeout); sequential rerun on bids 1–2 took 27 and 37 min per bid and found **neither certificate** (0/2; both exist on p.11), 1/2 prices, 0/6 evidence — **0 false restores**; bid 3 (no certificate; the search must exhaust its budget) ran away twice (14k generated tokens per request, 4k and then 16k context) and was stopped. Verdict: an 8B local text model does not drive the agent on this laptop; the guardrails held |
| 16 | OCR comparison, 36 scanned pages | `tools/ocr_compare.py`: qwen3-vl:8b (Ollama) vs Gemini 2.5 Flash (Vertex), separate caches, ground-truth facts (prices, totals, certificate lines, delivery, shelf life) | Both **14/14 facts**; transcript similarity mean 0.95, median 1.0; local blanked 1 filler page; **48.7 s vs 3.8 s per page**; $0 vs $0.00105 per page ($0.038 for all 36) |
| 17 | Local failure modes | Parallel fan-out on one laptop GPU; Ollama defaults | Two timeouts (OCR page, then a text call) at the 600 s client default → `LLM_TIMEOUT_S` knob and sequential bids for local; run/resume recovery kept 29 finished bids; the 8B text model ignored the "contents entry is not evidence" prompt rule → enforced in `app/grounding.py`. **Ollama's default 4k context silently truncated the pipeline's prompts** (server log: `truncated = 1` on 12 of 574 local requests — the long agent transcripts) — the local agent benchmark's third bid ran away for 14k generated tokens on a truncated transcript; mitigated with a 16k-context model variant (`qwen3:8b-16k`, documented in `.env.example`); the runaway recurred at 16k, so `LLM_MAX_TOKENS` now bounds generation per call |

## 4. Next plan — MCP server, Vertex AI Gemini backend, Cloud Run

Goal: turn "provider-agnostic, zero code change" into *measured* multi-provider
claims, and expose the bounded tool layer as a product surface. Order chosen by value
per hour: step 1 needs nothing from outside; step 2 carries the substantive claim;
step 3 adds the "deployed on GCP" line and can be dropped if budget or time is tight.
Azure is deliberately skipped (one cloud, done properly).

### 4.1 Step 1 — MCP server over the read-only tools, with a local-model client (1–1.5 days) — DONE 2026-09-08

*Status: implemented and measured (commits `e7203ca` +docs). Delivered as planned
with one deliberate tightening: the synthetic-only guard applies to the **stdio**
transport as well, because the server cannot tell Claude Desktop from the local
client by transport alone — unflagged projects are withheld unless the operator
starts the server with `MCP_LOCAL_MODEL=1` (the local client does so itself). The
per-connection selection lives on the SDK's lifespan object (entered once per stdio
process / HTTP session), and the SDK turned out to be v2 (`MCPServer`, not
`FastMCP`), pinned at 2.2.0. Results in §3 rows 12–13.*

**Confidentiality rule (governs this whole step).** An MCP server only moves *tool
execution* onto the machine that holds the documents. Every tool result — page
listings, snippets, full page text, OCR output — is sent to whatever model drives the
connected client. Claude Desktop, Cursor and similar clients are driven by cloud
models, so connecting them is cloud egress of document content: **synthetic or
sanitized projects only**, exactly like the demo's DeepSeek text path. The
production-compatible client is one driven by a *local* model (Ollama / the DGX vLLM
endpoint). Consequences for the implementation: stdio transport by default; the HTTP
transport is off unless explicitly enabled, binds to localhost, requires `X-API-Key`,
and the server refuses to serve a project unless it is marked demo/synthetic
(`ALLOW_CLOUD_CLIENTS=1` + a per-project `synthetic: true` flag in `meta.json`).

**Steps**
1. `mcp_server/server.py` on the official `mcp` Python SDK (FastMCP), pinned. Tools
   mirror `app/tools.BidTools` one-to-one: `list_pages`, `search_pages(query)`,
   `read_page(page, file?)`, `ocr_page(page, file?)`; plus `list_bids()` and
   `select_bid(project, tenderer)` so a client can navigate a project. Documents load
   through `load_folder` with the project's own OCR cache; the OCR budget is
   `AGENT_OCR_PAGES`.
2. Transports: stdio (Claude Desktop / Cursor) and streamable HTTP guarded by
   `X-API-Key` (reuse the backend's key).
3. **Local-model MCP client** — `mcp_server/local_client.py`: a small client that
   connects to the server over stdio and drives the tools with the project's own
   `LLM` class (structured `AgentAction` steps, same budgets), so the *whole loop stays
   on-premises* with `qwen3:8b` locally or the DGX models in production. This is the
   artifact that proves MCP and the NDA are compatible; Claude Desktop is the
   convenience demo on synthetic data.
4. Tests: in-process MCP client session exercising all tools, the OCR budget, the
   "skipped page → use ocr_page" hint, the synthetic-only guard on the HTTP transport,
   and the local client answering a scripted question; the server must never write
   except to the OCR cache.
5. README section: the confidentiality rule up front, a Claude Desktop config snippet
   (demo), the local-client command (production-compatible), and a screenshot of a
   tool-walked answer.

**Experiment / acceptance** (done — results in §3 rows 12–13; Claude Desktop is not
installed here, so the cloud driver was DeepSeek through the local client's
`--allow-cloud-model`, which is the same egress). Ask *"Does Tenderer_C's offer
include the Non-collusive Tendering Certificate?"* two ways on the same synthetic
project: (a) Claude Desktop
connected over stdio — expect a tool trace (list → search → read/OCR) and an answer
with page citations; (b) the local-model client on `qwen3:8b` — same question, same
tools, nothing leaves the machine; record both traces and step counts. On
`buried_case` both should show the contents-page → `ocr_page(11)` path; (c) attempt
to serve a project without the synthetic flag over HTTP → refused.

**Requirements / tools.** `mcp` SDK; Claude Desktop or Cursor for the demo (optional);
no cloud. **API spend:** none (local tools; OCR through the configured vision chain —
local Ollama is free).

**Lessons from the run.** (1) The server subprocess inherits the caller's
environment — `.env`'s Docker-style Ollama URL (`host.docker.internal`) does not
resolve natively, so the OCR chain failed until `GITHUB_MODELS_BASE_URL` was
overridden; and a crashed OCR reached the model as a bare "Error executing tool", so
it retried five times — the server now raises a descriptive `ToolError` ("OCR
unavailable … decide with the pages already read"). (2) Without the contents page in
its first observation the cloud driver hunted through filler pages 5–8; the client
now reads page 1 up front, exactly as the pipeline's agent does. (3) `qwen3:8b`
omitted `page` in its finish until the rejection message said which field was
missing — the message now names it, and the cold-cache run then succeeded.

**Difficulties (as anticipated).** The egress point above is the one that matters — it must be stated
in the README and enforced in code, not left to the operator; SDK API churn (pin, thin
adapter); a stdio server must not print to stdout (log to stderr); interactive OCR
latency on local `qwen3-vl` (~25 s/page — say so, or point the vision chain at a cloud
model *for synthetic demos only*); an 8B local model drives the tools less reliably
than Claude — the local client keeps the step budget and the quote-on-page check, so
the failure mode is "not found", never a fabricated citation.

### 4.2 Step 2 — Vertex AI Gemini as a measured fourth backend (1.5–2 days) — DONE 2026-09-09

*Status: implemented and measured on the owner's GCP project (free trial, Vertex AI
API, `us-central1`, Application Default Credentials; no service account needed on the
laptop). Delivered as planned: `app/gcp.py` token provider, Vertex entries for text
and vision, `app/usage.py` cost ledger with a verified price table, per-bid usage
files and `GET /usage`, ground truth for the N-bidder case plus `tools/score_case.py`
so agreement is computed rather than eyeballed, `tools/ocr_compare.py`, and
`tools/compare_runs.py` for the tables. Results in §3 rows 14–17. Spend: $0.40 metered ($0.35 Vertex, $0.05 DeepSeek).*

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
| 1 MCP server + local-model client — **done** | 1 day | $0 (a few DeepSeek cents for the cloud-driver run) | — |
| 2 Vertex AI Gemini + measurement — **done** | 1 day | $0.40 metered ($0.35 Vertex, $0.05 DeepSeek) (of ≤ $5 budgeted) | GCP project with billing, Vertex API on, ADC login, region |
| 3 Cloud Run | 1.5–2 days | ≈ $5–10 | same project, budget alert |
| 4 Docs | 0.5 day | $0 | — |

## 5. Standing backlog (unchanged, client-gated)

vLLM bring-up on the DGX Spark and pages/hour measurement (P3); golden regression
against three real historical cases — the honest accuracy test (P4); Word template
fidelity to the client's exact formats (P4); batch queue for overnight 60-bidder runs
and multi-project operations (P5); per-finding audit trail and deterministic FX table
(P2 leftovers); Stages III–V once the marking sheet arrives.
