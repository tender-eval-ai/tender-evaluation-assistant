# Tender Evaluation Assistant — Interview Preparation

*How to present this project on a resume, in a 90-second pitch, and under questioning.
Everything here is true of the repo as of commit `7f9c1d8` (after the LangGraph +
agent upgrade, Docker images rebuilt and verified) — no embellishment needed; the
honest version is the strong version.*

---

## 1. Resume entry

### Project-section version (6 bullets — drop one or two to fit)

> **AI Tender Evaluation Assistant** — LLM document-review pipeline for public
> procurement (Python, FastAPI, Streamlit, Docker) · [github.com/tender-eval-ai/tender-evaluation-assistant]
>
> - Built an end-to-end pipeline that drafts procurement review reports from a tender
>   plus 20–60 scanned bid PDFs: vision-OCR ingestion, per-tender rubric derivation,
>   evidence-cited extraction, deterministic Stage I/II evaluation and price engine,
>   and editable Word deliverables — designed on the principle "**LLMs extract, code
>   calculates**", so no number in a report ever comes from a model.
> - Engineered hallucination defenses that survived measurement: schema-validated JSON
>   output with error-feedback retry, keyword-targeted page retrieval, an
>   **adversarial verification pass** that must refute every negative finding before
>   it reaches a report, and page-cited evidence rendered with the quoted sentence
>   highlighted — **100% agreement with seeded ground truth on a 30-bidder stress
>   test (now 116 s end-to-end)**.
> - Designed for strict confidentiality (NDA): OpenAI-compatible client with
>   cross-provider fallback chains (`model@endpoint`, per-hostname API keys); when the
>   original cloud provider was **retired mid-project**, the pipeline fell back to
>   local Ollama models with zero code change — the same one-line config swap targets
>   vLLM on the client's DGX workstation for fully local production.
> - Orchestrated the pipeline as a **LangGraph state graph** with durable per-project
>   checkpoints, human-in-the-loop `interrupt()`s at the two review points and
>   parallel per-bid fan-out; added a **bounded tool-using agent** (schema-validated
>   actions, read-only tools incl. on-demand OCR, step/OCR budgets, quotes verified on
>   the cited page) that runs only for unresolved findings — raised buried-evidence
>   recall from **0% to 100%** with **zero false restores** on a seeded benchmark.
> - Exposed the agent's read-only tools as an **MCP server** (official SDK, stdio +
>   API-keyed HTTP) with a **local-model MCP client** so the whole tool loop can stay
>   on-premises, and a confidentiality guard enforced in code — cloud-driven clients
>   (Claude Desktop) see synthetic projects only.
> - Shipped as a two-service Docker Compose stack (FastAPI backend with run/resume
>   jobs; Streamlit review UI with triaged review, evidence highlighting and one-click
>   folder upload) with **81 fully-offline tests** and CI on every push; 30 bidders
>   evaluated end to end in 116 s.

### One-line version (for a crowded resume)

> Built a LangGraph-orchestrated LLM pipeline with a bounded evidence-search agent
> that drafts public tender-evaluation reports from scanned bids (OCR → rubric
> derivation → cited extraction → deterministic scoring → Word); 100% ground-truth
> agreement on a 30-bidder case, 0→100% buried-evidence recall with zero false
> positives; tools also served over MCP with a local-model client; 81-test CI;
> Dockerized, runs fully local for confidentiality.

**Tailoring tips**: applying for an *AI/LLM/agent engineer* role → lead with bullets
2, 4 and 5 (verification, grounding, LangGraph, the bounded agent and its benchmark,
MCP). *Backend/platform* role → lead with bullet 6 (services, run/resume jobs,
parallelism, CI). *Product-minded* role → lead with bullet 1 and the human-checkpoint
design. If the posting names **MCP** (Quantiphi, Hexion, Avnet, Abacus did), keep
bullet 5 and be ready for the egress question below.

---

## 2. The 90-second introduction

*(~230 words ≈ 90 s. Bold = hit these words clearly.)*

> I built an AI assistant for public tender evaluation — the process where a
> procurement panel checks dozens of bids and writes a formal review report.
>
> Three things make it hard. The bids are **pure scans** — zero extractable text. The
> data is under **strict confidentiality**, so nothing can go to a cloud API in
> production. And there's **no fixed rubric** — every tender's own terms define what
> must be submitted and how price is assessed, so the rules must be read out of the
> documents each time.
>
> My core design principle: **LLMs extract, code calculates**. Models do OCR, derive
> that tender's rubric, and extract facts with page citations; every number — totals,
> rounding, rankings — is deterministic Python. The whole flow is a **LangGraph state
> graph** with durable checkpoints and two human-in-the-loop interrupts. On top of that
> I added trust mechanisms: schema-validated JSON with retry, an **adversarial
> verification pass** that tries to refute every negative finding, and code-level
> **citation grounding** — a claim that cites a page nobody read is not evidence.
>
> The one place I let a model choose its own actions is a **bounded evidence-search
> agent**: for findings still unresolved, it reads the contents page, OCRs the pages
> it points to on demand, and can only finish with a quote that's verified on that
> page. On a seeded benchmark it took buried-evidence recall from **zero to 100
> percent with zero false positives**. And the full 30-bidder case still matches its
> ground truth **100 percent**, now in under two minutes.

### 中文版（口语，约 90 秒）

> 我做了一个政府采购评标的 AI 助手——评标委员会要审几十份投标书、写正式的评审报告，
> 我的系统把这个报告的初稿自动生成出来。
>
> 这个问题有三个难点：投标文件是**纯扫描件**，一个字都提取不出来；数据有**严格保密
> 要求**，生产环境不能碰任何云端 API；而且**没有固定的评分标准**——每个标书自己的
> 条款定义要交什么材料、价格怎么算，规则必须每次从文档里"读"出来。
>
> 我的核心设计原则是"**模型负责读，代码负责算**"：LLM 做 OCR、推导本标书的评审
> 规则、带页码引用地提取事实；所有数字——合计、修约、排名——全部是确定性的 Python
> 代码。整个流程用 **LangGraph** 编排成状态图：持久化检查点，两处人工确认用 interrupt
> 实现。在这之上是可信机制：JSON 按 schema 校验失败自动重试；每条负面结论先经过一次
> **对抗性反驳**；还有代码层面的**引用落地校验**——引用了一页没读过的页面，不算证据。
>
> 唯一让模型自主决定动作的地方，是一个**受约束的证据搜索 agent**：针对仍未解决的
> 结论，它读目录页、按需 OCR 目录指向的页面，而且只能用在该页上核实过的原文来
> 结束。在预埋答案的基准测试上，被"埋"起来的证据召回率从 **0 提到 100%，零误报**；
> 30 家投标人的完整案例依然与预埋答案 **100% 一致**，现在不到两分钟。

---

## 3. Numbers to remember

| Number | What it is |
| --- | --- |
| **20–60** | Bidders per tender in production; hundreds of pages each |
| **30 / 116 s / 100%** | Stress test through the graph: bidders / end-to-end time / ground-truth agreement (287 s before parallel fan-out) |
| **4/4, 3/3, 3/3** | Missing certs (one inside a scan), shelf-life breaches, arithmetic errors — all caught |
| **81** | Fully-offline tests in CI (incl. graph, agent, grounding, MCP) |
| **9 / 3** | MCP tools exposed (all read-only) / policies the guard distinguishes (stdio default, on-premises client, HTTP) |
| **0/2 → 2/2, 0 false, 0/3 → 3/3** | Agent benchmark: buried certificate recall, false restores, buried prices |
| **6 s vs 133 s** | Rubric derivation, DeepSeek vs local qwen3:8b (same verdicts) |
| **55 s vs ~337 s** | 3-bid case with parallel extraction + cloud text vs sequential local |
| **~4,500 + 1,600** | Lines of Python (app, services, MCP, tools) + tests, across 69 files (16-module library + 2 services + MCP surface) |
| **2** | Human checkpoints (rubric confirm; extraction correction — corrections are final) |

---

## 4. Likely questions and answers

*(Answers written to be spoken in 20–40 seconds.)*

### Design decisions

**Q: Why not just send the whole PDF to GPT-4/a big model and ask for the report?**
A: Three reasons. Accountability — a public panel must verify every cell, so I
need page-cited facts and deterministic math, not free-form prose. Correctness — the
price rules are precise (2-significant-figure rounding, half-up, tally checks);
models get those subtly wrong, code never does. And confidentiality — production
can't use a frontier cloud model at all, so the design has to work on 8–30B local
models, which means narrow, validated extraction tasks rather than one giant prompt.

**Q: Why derive the rubric with an LLM instead of configuring it manually?**
A: Every tender defines its own checklist and price formula, so a static config is
wrong by design — it becomes stale the moment the next tender arrives. But I don't
trust the derivation blindly: the rubric is written to editable JSON with source
citations, and a human must confirm it before anything downstream runs. It's
LLM-drafted, human-approved configuration.

**Q: What does "LLMs extract, code calculates" mean concretely?**
A: The model returns only facts with citations — "unit price 11.80, page 3". The
price engine then does everything numeric in Python with Decimal: cost-effectiveness
D×M, 2-significant-figure rounding half-up, FX, the tally check comparing quoted
totals against computed ones, and ranking. If a report number is wrong, it's a bug I
can unit-test, not a hallucination I can only apologise for.

### LLM engineering

**Q: How do you handle hallucinations?**
A: Defense in depth. Schema-validated JSON with one error-feedback retry. Prompts
that require quoting the mentioning sentence before claiming a document is present.
Targeted retrieval so the model sees relevant pages instead of truncated noise. An
adversarial verification pass that tries to refute every negative finding — a refuted
"missing" is restored, a refuted "non-compliant" is only demoted to "unclear" for a
human, never auto-passed. And ultimately a human checkpoint with the cited page image,
evidence highlighted. Early on, a small model claimed a missing certificate was
present — that's precisely the failure the quote-required prompt and verification
pass now catch.

**Q: Why adversarial verification only for negative findings?**
A: Asymmetric consequences. A false "missing document" can wrongly disqualify a real
company — that's the expensive error, so it gets a second, hostile look. A false
"present" is caught later by the human review with evidence images. And note the
asymmetric resolution: refuted-missing is restored automatically because the evidence
is right there, but refuted-compliance only goes to a human — the system never
upgrades a bid to compliant on its own.

**Q: The bids are scans. How does OCR fit in, and what if OCR misreads a price?**
A: A vision model transcribes page images to Markdown, cached per page; the
text-vs-scan decision is per page, so a digital document with one scanned annex only
OCRs the annex. Misread prices are caught structurally: the tally check recomputes
the total from unit price × quantity, so a misread on either side surfaces as a
mismatch that's flagged in the report, and the reviewer sees the original page image
next to the extracted number.

**Q: How did you make it work with multiple/unreliable model providers?**
A: One OpenAI-compatible client with fallback chains where each entry is
`model@endpoint` and API keys are picked by hostname. That paid off dramatically:
the free cloud API I started with was retired mid-project — my pipeline logged the
failure and fell through to local Ollama with zero code change, same verdicts. It's
also the production story: point the same config at vLLM on the client's hardware.

### The agent

**Q: Is this an agent, or a pipeline with a fancy name?**
A: The top level is deliberately a *workflow* — a fixed graph — because a procurement
panel needs predictable, auditable steps. There is exactly one agentic component:
an evidence-search loop that runs only for findings still unresolved after
verification. There the model does choose its own actions — list pages, search, read,
OCR a page on demand, finish — and I bound it: read-only tools, step and OCR budgets,
a finish accepted only if the quote is verifiably on the cited page, and no power to
change a compliance verdict. I'd rather defend "bounded agency where search is the
problem" than a free-roaming agent I can't audit.

**Q: Why LangGraph?**
A: I had hand-rolled what it provides: status files, JSON checkpoints for
resumability, a thread pool for parallel bids, and two human checkpoints. LangGraph
gave me durable per-project checkpoints, `interrupt()` for the human-in-the-loop
pauses, `Send` for parallel fan-out and crash recovery that keeps finished work — and
its nodes are plain Python, so my existing functions and OpenAI-compatible client
stayed unchanged. I proved the wrapper first: byte-identical evaluation output versus
the previous orchestrator before I changed any behaviour.

**Q: How did you evaluate the agent, and what did you learn?**
A: I built a benchmark case where the schedules are buried on pages 9–12 of scan-only
offers behind a table of contents, with the first pass capped at 4 pages — so the
baseline provably cannot see them — and one bidder that genuinely lacks the
certificate. The agent took certificate recall from 0/2 to 2/2 and prices from 0/3 to
3/3 with zero false restores. The first run taught me two things I fixed: the
*first-pass* extractor was claiming "present on page 11" without ever reading page 11
— that became a deterministic grounding rule — and the agent was OCR-ing filler pages
sequentially because it hadn't seen the contents page — so its transcript now starts
with the page listing and the cover page.

**Q: What can the agent not do, and why?**
A: It cannot flip "unclear" to "compliant", cannot cite a page it hasn't read, cannot
exceed its OCR budget, and cannot invent a quote — every finish is checked against the
page text in code. Those limits are the design: the agent proposes evidence, the
deterministic evaluator and the human decide.

### MCP

**Q: You mention an MCP server — what does it expose, and why bother?**
A: The same read-only tools the agent uses — list pages, keyword search, read a page,
OCR a scanned page on demand within a budget — plus project navigation and the
confirmed rubric, over the official Python SDK on stdio and a guarded HTTP transport.
The point is that the tool layer becomes a product surface: a reviewer can ask any MCP
client "does Tenderer 3's offer include the certificate?" and get a page-cited answer
from the same bounded tools, without re-running the pipeline. It was cheap because the
tools were already pure functions over one tenderer's documents with an explicit
budget; the server is a thin adapter plus per-connection state on the SDK's lifespan
object.

**Q: Doesn't connecting Claude Desktop to confidential tender documents break the NDA?**
A: Yes, if you let it — an MCP server only moves *tool execution* on-premises; every
tool result is sent to the model driving the client, and Claude Desktop's model is in
the cloud. So I enforce it in code rather than in a README: a project is served only if
it was created with a *synthetic* flag; unflagged projects are not even listed. The
production-compatible path is my local-model client — the project's own OpenAI-
compatible class on Ollama or the DGX's vLLM driving the same tools over stdio — which
declares itself with an environment flag, and even then the HTTP transport stays
synthetic-only because an HTTP client could be anywhere. The tests cover all three
policies.

**Q: How does an 8B local model cope with driving tools?**
A: Worse than Claude, and the design assumes that. The client feeds it an initial
observation so it doesn't burn steps orienting itself, validates every action against
a schema with a correction retry, caps the steps, and only accepts a `found=true`
finish whose quote is on a page the client actually read. So a weak model degrades to
"not found in N steps" with a trace you can inspect — never to a fabricated citation.
On the buried-evidence case it followed the contents page to page 11 and quoted the
certificate, the same path the pipeline's agent takes.

### Engineering & quality

**Q: How do you test an LLM pipeline in CI?**
A: I separate the deterministic 80% from the model 20%. All 69 CI tests are fully
offline: the price engine, evaluation logic, grounding, report rendering, retrieval
scoring and per-page OCR routing are tested directly; the LLM client with stubbed
endpoints; the graph with stubbed model steps — byte-identical output versus the
fixture run, pause/resume with edits, crash recovery; the agent with scripted action
sequences — finds a buried document, rejects an unverifiable quote, respects budgets;
and the API end to end through run → resume → resume. Model *quality* is measured
separately, against synthetic cases with seeded ground truth.

**Q: Tell me about a bug you're glad you caught.**
A: A race condition. The stress driver polled job status right after POSTing an
evaluation and sometimes read the *previous* job's "done" — the new thread hadn't
written "running" yet. I fixed both sides: the endpoint now writes "running" before
returning, and the poller ignores terminal states older than its request. It was a
good lesson that job status is API contract, not just UI decoration.

**Q: How does parallelism work now?**
A: Bids are independent units of work, so the graph fans them out with LangGraph's
`Send` — one branch per bidder without a stored extraction — under a concurrency cap
(default 4) that matches what the model endpoint can take; results merge back through
a dict reducer keyed by bidder. Before the graph I had the same win with a thread pool
(a 3-bid case from ~337 s to 55 s); the graph version adds crash recovery for free:
finished bids survive a failure mid fan-out. 30 bidders now take 116 s end to end.

**Q: How would you scale this to 60 bidders / production?**
A: The units of work are naturally parallel — bids are independent. Production plan:
vLLM on the client's DGX serves batched requests, `MAX_PARALLEL_BIDS` scales the
fan-out, OCR is cached per file-hash so re-runs are cheap, and a batch queue handles
overnight runs. The stress test at 30 bidders was 287 s even *sequentially*, so the
throughput target is comfortable.

### The honest questions

**Q: What's the real accuracy on actual tender documents?**
A: Honestly: unproven, and I say so in the docs. The 100% figure is on clean
synthetic cases — it validates the workflow, decision logic and price math, not
real-scan OCR quality. That's exactly why the production plan starts with a golden
regression against three real historical cases on the client's hardware, where
confidentiality allows real data.

**Q: What was the hardest part?**
A: Reverse-engineering the business logic from masked sample reports — things like
non-conforming bids still being ranked but never recommended, or when an arithmetic
error becomes a formal note. Encoding domain rules precisely mattered more than any
model work; the LLM parts were straightforward by comparison once the contracts were
right.

**Q: What would you do differently?**
A: Start with the per-page OCR routing and parallel extraction from day one — both
were cheap and I added them late. And I'd introduce the golden-regression harness
earlier, even with only synthetic data, because every prompt change should be a
measured change. One thing I'd keep exactly: writing every stage's output as an
editable JSON checkpoint — it made the system debuggable, resumable and
human-correctable for free.

**Q: Where's the human in the loop, and could this auto-decide?**
A: Deliberately not. The system drafts; the panel decides. Two hard checkpoints —
rubric confirmation and extraction review — plus "unclear" findings explicitly routed
to human clarification. In public procurement the accountable party must stay
human; the product's value is turning days of clerical checking into minutes of
verification.

---

## 5. Good questions to ask the interviewer

- "Do you run LLMs on-prem or in-cloud, and how do you handle customers with data
  residency or confidentiality constraints?" *(shows you've lived this trade-off)*
- "How do you regression-test prompt or model changes today?" *(golden-regression
  experience transfers directly)*
- "Where do you draw the line between model output and deterministic code in your
  product?" *(your strongest design opinion, invited)*
