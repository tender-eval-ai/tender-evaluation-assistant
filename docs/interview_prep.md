# Tender Evaluation Assistant — Interview Preparation

*How to present this project on a resume, in a 90-second pitch, and under questioning.
Everything here is true of the repo as of commit `4e96b4b` — no embellishment needed;
the honest version is the strong version.*

---

## 1. Resume entry

### Project-section version (4 bullets)

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
>   test (287 s end-to-end)**.
> - Designed for strict confidentiality (NDA): OpenAI-compatible client with
>   cross-provider fallback chains (`model@endpoint`, per-hostname API keys); when the
>   original cloud provider was **retired mid-project**, the pipeline fell back to
>   local Ollama models with zero code change — the same one-line config swap targets
>   vLLM on the client's DGX workstation for fully local production.
> - Shipped as a two-service Docker Compose stack (FastAPI backend with background
>   jobs and parallel bid extraction; Streamlit review UI with human checkpoints,
>   triaged review, and one-click folder upload) with **50 fully-offline tests** and
>   CI on every push; parallel extraction + cloud text cut a 3-bid case from ~337 s
>   to 55 s.

### One-line version (for a crowded resume)

> Built an LLM pipeline that drafts public tender-evaluation reports from scanned
> bids (OCR → rubric derivation → cited extraction → deterministic scoring → Word);
> 100% ground-truth agreement on a 30-bidder stress test; 50-test CI; Dockerized,
> runs fully local for confidentiality.

**Tailoring tips**: applying for an *AI/LLM engineer* role → lead with bullet 2
(verification, retrieval, schema validation). *Backend/platform* role → lead with
bullet 4 (services, jobs, parallelism, CI). *Product-minded* role → lead with bullet 1
and the human-checkpoint design.

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
> rounding, rankings — is deterministic Python. On top of that I added trust
> mechanisms: schema-validated JSON with retry, and an **adversarial verification
> pass** — every "document missing" or "non-compliant" finding gets an independent
> attempt to refute it before it can reach a report. Humans confirm the rubric and can
> correct any extraction, side-by-side with the cited page image, evidence highlighted.
>
> To prove it works I generated a **30-bidder** synthetic case with seeded defects —
> missing certificates, compliance breaches, arithmetic errors. The pipeline matched
> the ground truth **100 percent**, in under five minutes. And when the cloud API I
> started on was retired mid-project, the fallback chain switched to **local models
> with zero code change** — which is exactly the design production needs.

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
> 代码。在这之上我加了可信机制：JSON 按 schema 校验失败自动重试；每一条负面结论——
> "材料缺失"、"不合规"——都要先经过一次**对抗性反驳**才能进报告。人工确认评审规则，
> 也可以修正任何提取结果，界面上证据页图片就在旁边，原句高亮。
>
> 为了验证效果，我生成了一个 **30 家投标人**的合成案例，故意埋入缺证书、违规、总价
> 算错等缺陷——系统与预埋答案 **100% 一致**，全程不到五分钟。项目中途最初用的云端
> API 被停服，回退链**零代码改动**切到了本地模型——这恰好就是生产环境需要的架构。

---

## 3. Numbers to remember

| Number | What it is |
| --- | --- |
| **20–60** | Bidders per tender in production; hundreds of pages each |
| **30 / 287 s / 100%** | Stress test: bidders / end-to-end time / ground-truth agreement |
| **4/4, 3/3, 3/3** | Missing certs (one inside a scan), shelf-life breaches, arithmetic errors — all caught |
| **50** | Fully-offline tests in CI |
| **6 s vs 133 s** | Rubric derivation, DeepSeek vs local qwen3:8b (same verdicts) |
| **55 s vs ~337 s** | 3-bid case with parallel extraction + cloud text vs sequential local |
| **~3,800** | Lines of Python across 57 files (12-module library + 2 services) |
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

### Engineering & quality

**Q: How do you test an LLM pipeline in CI?**
A: I separate the deterministic 80% from the model 20%. All 50 CI tests are fully
offline: the price engine, evaluation logic, report rendering, retrieval scoring and
per-page OCR routing are tested directly; the LLM client is tested with stubbed
endpoints (including fallback behaviour); the API is tested end-to-end by injecting
fixture extractions through the human-correction path, and the parallel extractor
runs against a stubbed model through the real thread pool. Model *quality* is
measured separately, against synthetic cases with seeded ground truth.

**Q: Tell me about a bug you're glad you caught.**
A: A race condition. The stress driver polled job status right after POSTing an
evaluation and sometimes read the *previous* job's "done" — the new thread hadn't
written "running" yet. I fixed both sides: the endpoint now writes "running" before
returning, and the poller ignores terminal states older than its request. It was a
good lesson that job status is API contract, not just UI decoration.

**Q: Why threads and not asyncio for parallel extraction?**
A: The bottleneck is waiting on LLM HTTP calls, which threads handle fine through the
sync OpenAI client; a ThreadPoolExecutor with a small cap (default 4) got the win —
a 3-bid case went from ~337 s to 55 s — without converting the whole pipeline to
async. The shared state is tiny: results keyed by bidder, and a lock around progress
updates. If profiling ever shows thread overhead matters at 60 bidders, the seam to
swap is one function.

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
