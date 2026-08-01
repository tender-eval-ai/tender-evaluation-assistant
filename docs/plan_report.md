# Tender Evaluation Assistant — Development & Deployment Plan

*Status date: 2026-08-01 · Repo: `tender-evaluation-assistant` (private) · Demo phase complete*

---

## 1. High-Level Development Plan

### 1.1 User needs

| Aspect | Need |
| --- | --- |
| User | Procurement assistants supporting a Tender Assessment Panel (TAP); reached only through the client's IT department (no direct user access) |
| Task | For each procurement: review 20–60 bidders' offers against that tender's own rules and produce the procurement review report |
| Input | One tender document set (mostly digital PDFs) + one offer per bidder (**scanned PDFs**, 60–400 pages) |
| Output | Price Summary table (2 formats), Stage I & Stage II conclusions, detailed evaluation record — **editable Word, English** |
| Constraint | Strict NDA: all real documents processed **on-premises only** (client DGX Spark GB10); no cloud egress |

Three findings from the client's sample cases that shaped the design:

1. **Every tender defines its own rules** — completeness checklist, essential
   requirements, and price formula (cost-effectiveness `D×M` vs unit-price×quantity)
   live in each tender's Terms of Tender. The rubric must be derived per project,
   not hard-coded.
2. **Bid documents are pure scans** (measured: 62 pages, 0 extractable characters)
   — vision-model OCR is a core capability, not an option.
3. **The TAP audits arithmetic** — the sample Price Summary flags a bidder's quoted
   total that fails to tally with unit×quantity. The product must reproduce this
   class of deterministic checking.

### 1.2 Confirmed requirements vs. open items

**Confirmed** (from client materials): the five-stage TAP workflow with Stage I/II in
scope for 1.0; both Price Summary formats incl. "cannot be calculated / not
applicable" handling and the recommended offer in bold; 2-significant-figure rounding
rule; TAP-style English narrative conclusions; local deployment on DGX Spark; open
models only (Qwen3.6-35B-A3B, DeepSeek-V4-Flash, Qwen3-VL-32B/30B-A3B); Word export.

**Open — on the client decision list**: the Technical Marking Sheet sample (file
missing from delivered materials); bid folder delivery conventions; Stage III–V scope
for 1.0; turnaround expectations (drives batch design); more sanitized cases for a
regression set; DGX access window.

### 1.3 Technology stack

| Layer | Demo (now) | Production (client site) |
| --- | --- | --- |
| Language / runtime | Python 3.12 | same |
| LLM serving | GitHub Models free tier (OpenAI-compatible) | **vLLM** on DGX Spark (same client code, different base URL) |
| Text model | `gpt-4o-mini` → fallbacks `o3`, `gpt-4.1-mini` | Qwen3.6-35B-A3B / DeepSeek-V4-Flash |
| Vision/OCR model | `gpt-4.1` → same fallback chain | Qwen3-VL-30B-A3B (MoE, batched) |
| Backend | FastAPI + uvicorn, background jobs, X-API-Key auth | same |
| Frontend | Streamlit (pure HTTP client of the backend) | same (or thin React if client IT requires) |
| PDF handling | pypdf (text), pypdfium2 + Pillow (render for OCR) | same |
| Reports | python-docx | same + client template fidelity |
| Validation | pydantic v2 (LLM outputs schema-validated at the boundary) | same |
| Packaging | Docker Compose, 2 images (backend/frontend), arm64-ready | same stack on GB10 (arm64) |
| Testing | pytest — 30 offline tests, no network, no real data | + golden regression on real cases |

### 1.4 What the service delivers

For each procurement project: an auto-derived, **human-confirmed** evaluation rubric
with clause citations; per-bidder Stage I completeness and Stage II compliance
findings, each carrying page-level evidence; a deterministic price computation
(rounding, FX, arithmetic tally check, ranking, recommendation); and three editable
English Word deliverables (`price_summary.docx`, `summary_list.docx`,
`evaluation_record.docx`). Design principles: **LLMs extract and classify — code
calculates and ranks**; every negative finding is verifiable; the output is a draft
for the TAP, never an auto-final decision.

Demonstrated so far (synthetic data): full pipeline via UI/API/CLI; 30-bidder stress
run in 287 s with 100% agreement against seeded ground truth (4/4 Stage I failures,
3/3 Stage II failures, 3/3 arithmetic errors, incl. a scanned+missing-certificate
compound case); zero model fallbacks needed.

---

## 2. Deployment Plan — Milestones

| Phase | Timing | Content | Exit criteria |
| --- | --- | --- | --- |
| **P0 — Understanding & proposal** ✅ | Week 1 | Business analysis of the 3 sample cases, product design, service proposal | Proposal delivered |
| **P1 — Stage I/II demo** ✅ | Week 2 | Pipeline (ingest→rubric→extract→evaluate→Word), review UI, Docker service split, stress test, demo report (`docs/demo_presentation.md`) | Live demo runs end-to-end; feasibility evidenced |
| **P2 — Correctness hardening** | Week 3 | Targeted section retrieval (no silent truncation of long bids); adversarial second-pass verification of negative findings; deterministic FX table; audit trail (model, prompt hash, timestamps); CI + pinned dependencies | All P1 tests green + new correctness tests; audit log on every finding |
| **P3 — Local inference** | Week 4 | vLLM on DGX Spark (arm64 images); Qwen3-VL OCR batch path with resume; throughput measurement; model-choice evaluation under GB10 memory budget | 3 real client cases run fully on-prem; measured pages/hour |
| **P4 — Golden regression & fidelity** | Week 5 | Regression harness comparing pipeline output to the client's real historical reports; Word templates matched to client format (layout, note markers, bold conventions); extraction accuracy report | Regression pass on the 3 cases; client-format reports accepted by IT |
| **P5 — Production 1.0 delivery** | Week 6 | Batch queue for 60-bidder runs; multi-project management; operator documentation; handover to client IT (compose stack + runbook); UAT with client IT | 1.0 deployed on client hardware; UAT sign-off |

Standing risks tracked across phases: real-scan OCR quality (P3 measures it), missing
Technical Marking Sheet (blocks evaluation-record final format — client action),
Stage III–V scope decision (affects P5 packaging).

---

## 3. Detailed Specification

### 3.1 Code architecture

```
frontend/ui.py ──HTTP──► backend/api.py ──imports──► app/  (pipeline library)
                              │                        │
                              ▼                        ▼
                        data/projects/<id>/      LLM endpoint (OpenAI-compatible):
                        (uploads, checkpoints,   GitHub Models (demo) / vLLM (prod)
                         reports, OCR cache)
run_demo.py (CLI) ────imports──────────────────► app/
```

The `app/` package is the single source of pipeline logic; CLI and API are thin
orchestrators over it. All cross-stage data passes through pydantic contracts
(`schemas.py`) and is persisted as human-editable JSON checkpoints.

### 3.2 File inventory

49 tracked files; 27 Python files, 2,318 lines. Per package:

**`app/` — pipeline library (11 files, 1,041 lines)**

| File | Lines | Contents |
| --- | --- | --- |
| `schemas.py` | 125 | Pydantic contracts: `Rubric` (checklist / essential requirements / price scheme), `BidExtraction` (presence, compliance, price), `Stage1Result`, `Stage2Result`, `PriceRow`, `EvaluationResult`. Doubles as the JSON Schema sent to the LLM. |
| `config.py` | 66 | Env/.env loading, GitHub token resolution, model + fallback-chain configuration, OCR/prompt budget caps. The demo⇄production swap point. |
| `llm.py` | 102 | OpenAI-compatible client: fallback chains (rate limit/outage/403 → next model), o-series parameter handling, schema-validated JSON chat with retry-on-validation-error, page OCR. |
| `ingest.py` | 108 | PDF classification (text vs scanned, threshold-based), per-page text extraction, page rendering (pypdfium2) → VLM OCR with on-disk cache, page-cap for rate limits. |
| `rubric.py` | 71 | Tender understanding: prioritized document selection (Terms of Tender first), prompt assembly under budget, rubric derivation + load/save. |
| `bid_extract.py` | 50 | Per-bid extraction prompt (evidence-quoting rules, redaction handling, numeric-limit direction rules) → validated `BidExtraction`. |
| `evaluate.py` | 120 | Deterministic Stage I/II aggregation (missing-required→fail; "unclear"→clarification list, not disqualification), TAP-style English conclusion text. |
| `pricing.py` | 84 | Deterministic price engine: 2-sig-fig rounding (half-up at 3rd), FX conversion, both Price Summary schemes, arithmetic tally check, ranking incl. non-conforming rows, recommendation = best conforming. |
| `report.py` | 206 | python-docx renderers for the three deliverables; bold-recommended convention; auto-generated notes (incl. arithmetic-error notes). |
| `pipeline.py` | 109 | CLI orchestration with resumable JSON checkpoints; offline mode (fixtures→evaluation→reports, no network). |
| `__init__.py` | 0 | package marker |

**`backend/` — API service (4 files: 2 py = 327 lines, requirements, Dockerfile)**

| File | Contents |
| --- | --- |
| `api.py` (327) | FastAPI app: project CRUD, PDF uploads, background jobs (derive / evaluate) with one-job-per-project locking and status file, rubric GET/PUT (human checkpoint — evaluation refuses to run without it), extraction injection/correction endpoint, evaluation JSON, Word report downloads, X-API-Key auth (health open). |
| `requirements.txt` | FastAPI/uvicorn/multipart + pipeline deps only |
| `Dockerfile` | python:3.12-slim, `/data` volume, uvicorn :8000 |

**`frontend/` — review UI (3 files: 1 py = 176 lines, requirements, Dockerfile)**

| File | Contents |
| --- | --- |
| `ui.py` (176) | Streamlit app, 4 tabs = workflow steps: Documents (uploads), Rubric (derive + edit + save), Evaluation (job polling, Stage I matrix, Stage II evidence expanders, price table), Reports (downloads). HTTP-only; no documents or pipeline code in this container. |
| `requirements.txt` | streamlit + requests only |
| `Dockerfile` | python:3.12-slim, streamlit :8501 |

**`tools/` — generators & drivers (4 files, 360 lines)**

| File | Lines | Contents |
| --- | --- | --- |
| `pdfgen.py` | 47 | Dependency-free multi-page text-layer PDF writer (fixtures/demo cases). |
| `make_demo_case.py` | 205 | Synthetic case generator: fixed 3-bidder demo trio or `--bidders N` deterministic varied cases (seeded Stage I/II failures, arithmetic errors, scanned offers). |
| `stress_test.py` | 108 | Drives a case through a running backend with per-phase timings and outcome summary. |

**`test/` — 30 tests (9 py = 414 lines + 5 JSON fixtures)**

| File | Covers |
| --- | --- |
| `test_pricing.py` (98) | Rounding rule cases, CE ranking + non-conforming handling, FX, arithmetic tally (incl. the client sample's real numbers). |
| `test_evaluate.py` (43) | Stage gating, unclear-vs-fail semantics, conclusion phrasing. |
| `test_report.py` (43) | Word output reopened and asserted (values, bold-recommended, fail marks). |
| `test_ingest.py` (34) | Text/scan classification; scanned-without-LLM fails loudly. |
| `test_llm.py` (65) | Fallback order, all-fail error, OCR chain, o-series params (stubbed client). |
| `test_api.py` (86) | Full offline API flow via injected extractions; 404s; API-key enforcement. |
| `test_e2e_offline.py` (22) | Fixtures → evaluation → checkpoints → reports end-to-end. |
| `conftest.py` (23) | Fixture loading, path setup. |
| `data/synthetic_case/` | Rubric + 4 bid-extraction fixtures (the offline scenario). |

**Root & docs (10 files)**: `run_demo.py` (CLI entry), aggregate `requirements.txt`,
`docker-compose.yml`, `.env.example`, `.dockerignore`, `.gitignore`, `README.md`,
`docs/demo_presentation.md`, `docs/plan_report.md`, `demo_case/` (committed 3-bidder
sample: 5 PDFs).

### 3.3 Storage layout (per project, under `data/projects/<id>/`)

```
meta.json                      name, created
status.json                    job state: idle | running | done | error (+ detail)
tender/*.pdf                   uploaded tender documents
bids/<tenderer>/*.pdf          uploaded offers
work/rubric.json               derived rubric — human-editable checkpoint
work/bids/<tenderer>.json      per-bid extraction — editable; edited bids not re-run
work/cache/<sha>/page_N.md     OCR cache (per source file hash)
work/evaluation.json           full EvaluationResult
work/reports/*.docx            the three deliverables
```

### 3.4 Planned 1.0 additions (phases P2–P5)

| New module | Phase | Purpose |
| --- | --- | --- |
| `app/retrieval.py` | P2 | Keyword/heading section locator so long bids prompt only relevant schedules — replaces character-budget truncation. |
| `app/verify.py` | P2 | Adversarial second-pass check on every `present=false` / `complies=no` finding before it reaches a report. |
| `app/fx.py` | P2 | Deterministic exchange-rate table keyed to tender closing date. |
| `app/audit.py` | P2 | Per-finding audit record: model id, prompt hash, timestamps. |
| `.github/workflows/ci.yml` | P2 | Offline test suite on every push. |
| `deploy/vllm/` | P3 | vLLM launch configs for DGX Spark (arm64), model download/quantization notes. |
| `tools/regression.py` | P4 | Golden-set comparison against real historical reports. |
| Batch queue in `backend/` | P5 | Sequential multi-project queue with resume for 60-bidder overnight runs. |

### 3.5 Quality gates

Every phase keeps three invariants: (1) all numbers in reports reproducible by code
alone; (2) every negative finding carries evidence a reviewer can check in one
click/page-open; (3) the offline test suite runs with zero network and zero real
client data, so CI can never leak anything.
