# 采购审查助手 — 开发与部署计划

*状态日期：2026-08-01 · 仓库：`tender-evaluation-assistant`（私有）· Demo 阶段已完成*

---

## 1. 高层开发计划

### 1.1 用户需求

| 维度 | 需求 |
| --- | --- |
| 用户 | 支撑评标小组（TAP）的采购助理；只能通过客户 IT 部门对接（无法直接接触用户） |
| 任务 | 每次采购：按该招标自身的规则审查 20–60 家投标单位的投标文件，产出采购审查报告 |
| 输入 | 一套招标文件（多为可提取文本的 PDF）+ 每家投标单位一份投标文件（**扫描件**，60–400 页） |
| 输出 | 价格汇总表（2 种格式）、Stage I 与 Stage II 结论、详细评估记录表 —— **可编辑 Word、英文** |
| 约束 | 严格保密协议：真实文件只能**本地处理**（客户 DGX Spark GB10），数据不出内网 |

从客户样例案例中得出的三个决定产品形态的发现：

1. **每个招标定义自己的规则**——完整性清单、基本要求、价格公式
   （cost-effectiveness `D×M` 或单价×数量）都写在各自的 Terms of Tender 里。
   评审 rubric 必须按项目动态推导，不能写死。
2. **投标文件全部是扫描件**（实测 62 页 0 字符可提取）——视觉模型 OCR
   是核心能力，不是可选项。
3. **TAP 会人工复核算术**——样例价格汇总表中标注了某投标人报价总额与
   单价×数量不符。产品必须复现这类确定性检查。

### 1.2 已确认需求与待定事项

**已确认**（依据客户资料）：TAP 五阶段流程，1.0 范围为 Stage I/II；两种价格
汇总表格式，含 "cannot be calculated / not applicable" 处理与推荐标加粗；
2 位有效数字舍入规则；TAP 风格英文结论叙述；DGX Spark 本地部署；仅用开源
模型（Qwen3.6-35B-A3B、DeepSeek-V4-Flash、Qwen3-VL-32B/30B-A3B）；Word 导出。

**待定——列入客户决策清单**：Technical Marking Sheet 样例（交付资料中缺失）；
投标文件目录交付规范；Stage III–V 是否纳入 1.0；时效预期（决定批处理设计）；
更多脱敏案例作为回归集；DGX 环境访问窗口。

### 1.3 技术栈

| 层 | Demo（当前） | 生产（客户本地） |
| --- | --- | --- |
| 语言 / 运行时 | Python 3.12 | 同 |
| LLM 服务 | GitHub Models 免费额度（OpenAI 兼容） | **vLLM** on DGX Spark（客户端代码不变，仅换 base URL） |
| 文本模型 | `gpt-4o-mini` → 降级 `o3`、`gpt-4.1-mini` | Qwen3.6-35B-A3B / DeepSeek-V4-Flash |
| 视觉/OCR 模型 | `gpt-4.1` → 同降级链 | Qwen3-VL-30B-A3B（MoE，批处理） |
| 后端 | FastAPI + uvicorn，后台任务，X-API-Key 鉴权 | 同 |
| 前端 | Streamlit（仅通过 HTTP 调后端） | 同（如客户 IT 要求可换轻量 React） |
| PDF 处理 | pypdf（文本层）、pypdfium2 + Pillow（渲染供 OCR） | 同 |
| 报告 | python-docx | 同 + 客户模板逐项对齐 |
| 校验 | pydantic v2（LLM 输出在边界处按 schema 校验） | 同 |
| 打包 | Docker Compose，2 个镜像（前端/后端），支持 arm64 | 同一套部署到 GB10（arm64） |
| 测试 | pytest —— 30 项离线测试，无网络、无真实数据 | + 真实案例黄金回归集 |

### 1.4 服务交付内容

每个采购项目交付：自动推导、**人工确认**的评审 rubric（附条款出处）；逐标的
Stage I 完整性与 Stage II 符合性结论，每条附页码级证据；确定性价格计算
（舍入、汇率、算术复核、排名、推荐）；三份可编辑英文 Word 报告
（`price_summary.docx`、`summary_list.docx`、`evaluation_record.docx`）。
设计原则：**LLM 只做提取与判断——数字全部由代码计算**；每条否定性结论可核查；
产出是给 TAP 的**草稿**，绝不自动终审。

已验证（合成数据）：UI/API/CLI 三种方式全流程走通；30 家投标压力测试 287 秒
完成，与预埋事实 100% 一致（Stage I 缺件 4/4、Stage II 不符 3/3、算术错误
3/3，含"扫描件+缺证书"复合用例）；全程 0 次模型降级。

---

## 2. 部署计划 — 里程碑

| 阶段 | 时间 | 内容 | 出口标准 |
| --- | --- | --- | --- |
| **P0 — 需求理解与方案** ✅ | 第 1 周 | 3 个样例案例业务分析、产品设计、项目服务方案 | 方案交付 |
| **P1 — Stage I/II Demo** ✅ | 第 2 周 | 管线（摄取→rubric→提取→评审→Word）、审阅 UI、前后端 Docker 化、压力测试、演示汇报（`docs/demo_presentation.md`） | 现场演示全流程走通；可行性有据 |
| **P2 — 正确性加固** | 第 3 周 | 长文档定向检索（杜绝静默截断）；否定性结论对抗式二次校验；确定性汇率表；审计日志（模型、提示词哈希、时间戳）；CI + 依赖锁定 | P1 测试全绿 + 新增正确性测试；每条结论有审计记录 |
| **P3 — 本地推理** | 第 4 周 | DGX Spark 上部署 vLLM（arm64 镜像）；Qwen3-VL OCR 批处理（可断点续跑）；吞吐量实测；GB10 显存预算下的模型选型评估 | 3 个真实案例全程内网跑通；产出 页数/小时 实测值 |
| **P4 — 黄金回归与版式对齐** | 第 5 周 | 回归工具：管线输出对照客户真实历史报告；Word 模板对齐客户版式（布局、注释符号、加粗惯例）；提取准确率报告 | 3 个案例回归通过；报告版式获客户 IT 认可 |
| **P5 — 生产 1.0 交付** | 第 6 周 | 60 家投标批量任务队列；多项目管理；操作文档；向客户 IT 移交（compose 部署 + 运维手册）；UAT | 1.0 部署在客户硬件；UAT 签收 |

跨阶段持续跟踪的风险：真实扫描件 OCR 质量（P3 实测）；Technical Marking Sheet
缺失（阻塞评估记录表最终版式——需客户提供）；Stage III–V 范围决策（影响 P5 打包）。

---

## 3. 详细规格

### 3.1 代码架构

```
frontend/ui.py ──HTTP──► backend/api.py ──import──► app/（管线库）
                              │                       │
                              ▼                       ▼
                        data/projects/<id>/     LLM 端点（OpenAI 兼容）：
                        （上传件、检查点、        GitHub Models（demo）/ vLLM（生产）
                          报告、OCR 缓存）
run_demo.py（CLI）────import──────────────────► app/
```

`app/` 包是管线逻辑的唯一来源；CLI 与 API 只是其上的薄编排层。跨阶段数据一律
经 pydantic 契约（`schemas.py`）流转，并落盘为人工可编辑的 JSON 检查点。

### 3.2 文件清单

版本库共 49 个文件；其中 Python 27 个、2,318 行。按包列出：

**`app/` — 管线库（11 个文件，1,041 行）**

| 文件 | 行数 | 内容 |
| --- | --- | --- |
| `schemas.py` | 125 | pydantic 契约：`Rubric`（清单/基本要求/价格方案）、`BidExtraction`（齐备性、符合性、价格）、`Stage1Result`、`Stage2Result`、`PriceRow`、`EvaluationResult`。同时作为发给 LLM 的 JSON Schema。 |
| `config.py` | 66 | 环境/.env 加载、GitHub token 解析、模型与降级链配置、OCR/提示词预算上限。demo⇄生产的切换点。 |
| `llm.py` | 102 | OpenAI 兼容客户端：模型降级链（限流/故障/403 → 下一个）、o 系列参数适配、schema 校验的 JSON 会话（校验失败自动重试）、页面 OCR。 |
| `ingest.py` | 108 | PDF 分类（文本/扫描，阈值法）、逐页文本抽取、页面渲染（pypdfium2）→ VLM OCR 带磁盘缓存、限流页数上限。 |
| `rubric.py` | 71 | 招标理解：文档优先级排序（Terms of Tender 优先）、预算内提示词组装、rubric 推导与读写。 |
| `bid_extract.py` | 50 | 逐标提取提示词（证据引用规则、遮盖件处理、数值比较方向规则）→ 校验后的 `BidExtraction`。 |
| `evaluate.py` | 120 | 确定性 Stage I/II 聚合（必备项缺失→不通过；"unclear"→待澄清清单而非否决）、TAP 风格英文结论文本。 |
| `pricing.py` | 84 | 确定性价格引擎：2 位有效数字舍入（第 3 位半进位）、汇率换算、两种价格汇总方案、报价算术复核、排名（含不合规标）、推荐 = 最优合规标。 |
| `report.py` | 206 | 三份交付物的 python-docx 渲染；推荐标加粗惯例；注释自动生成（含算术错误注）。 |
| `pipeline.py` | 109 | CLI 编排，JSON 检查点可续跑；离线模式（fixtures→评审→报告，无网络）。 |
| `__init__.py` | 0 | 包标记 |

**`backend/` — API 服务（4 个文件：2 个 py 共 327 行、requirements、Dockerfile）**

| 文件 | 内容 |
| --- | --- |
| `api.py`（327） | FastAPI 应用：项目 CRUD、PDF 上传、后台任务（推导/评审，单项目单任务锁 + 状态文件）、rubric GET/PUT（人工确认点——未确认不允许评审）、提取结果注入/人工修正接口、评审结果 JSON、Word 报告下载、X-API-Key 鉴权（health 开放）。 |
| `requirements.txt` | 仅 FastAPI/uvicorn/multipart + 管线依赖 |
| `Dockerfile` | python:3.12-slim，`/data` 卷，uvicorn :8000 |

**`frontend/` — 审阅 UI（3 个文件：1 个 py 共 176 行、requirements、Dockerfile）**

| 文件 | 内容 |
| --- | --- |
| `ui.py`（176） | Streamlit 应用，4 个页签 = 业务流程四步：Documents（上传）、Rubric（推导+编辑+保存）、Evaluation（任务轮询、Stage I 矩阵、Stage II 证据、价格表）、Reports（下载）。纯 HTTP；该容器内无文件、无管线代码。 |
| `requirements.txt` | 仅 streamlit + requests |
| `Dockerfile` | python:3.12-slim，streamlit :8501 |

**`tools/` — 生成器与驱动（4 个文件，360 行）**

| 文件 | 行数 | 内容 |
| --- | --- | --- |
| `pdfgen.py` | 47 | 零依赖多页文本层 PDF 生成器（测试与演示用例）。 |
| `make_demo_case.py` | 205 | 合成案例生成器：固定 3 家演示组合，或 `--bidders N` 生成确定性变化案例（预埋 Stage I/II 失败、算术错误、扫描件）。 |
| `stress_test.py` | 108 | 驱动案例经由运行中的后端全流程执行，输出分阶段耗时与结果摘要。 |

**`test/` — 30 项测试（9 个 py 共 414 行 + 5 个 JSON fixture）**

| 文件 | 覆盖 |
| --- | --- |
| `test_pricing.py`（98） | 舍入规则用例、CE 排名与不合规处理、汇率、算术复核（含客户样例真实数字）。 |
| `test_evaluate.py`（43） | 阶段门控、unclear 与 fail 语义、结论措辞。 |
| `test_report.py`（43） | Word 产物重新打开并断言（数值、推荐加粗、缺件标记）。 |
| `test_ingest.py`（34） | 文本/扫描分类；扫描件无 LLM 时显式报错。 |
| `test_llm.py`（65） | 降级顺序、全部失败报错、OCR 链、o 系列参数（stub 客户端）。 |
| `test_api.py`（86） | 注入提取结果的全离线 API 流程；404；API-Key 强制。 |
| `test_e2e_offline.py`（22） | fixtures → 评审 → 检查点 → 报告端到端。 |
| `conftest.py`（23） | fixture 加载、路径设置。 |
| `data/synthetic_case/` | rubric + 4 份投标提取 fixture（离线场景）。 |

**根目录与文档（10 个文件）**：`run_demo.py`（CLI 入口）、聚合 `requirements.txt`、
`docker-compose.yml`、`.env.example`、`.dockerignore`、`.gitignore`、`README.md`、
`docs/demo_presentation.md`、`docs/plan_report.md`（英文版）、`demo_case/`
（随库提交的 3 家样例：5 个 PDF）。

### 3.3 存储布局（每个项目，位于 `data/projects/<id>/`）

```
meta.json                      名称、创建时间
status.json                    任务状态：idle | running | done | error（+ 详情）
tender/*.pdf                   上传的招标文件
bids/<tenderer>/*.pdf          上传的投标文件
work/rubric.json               推导出的 rubric —— 人工可编辑检查点
work/bids/<tenderer>.json      逐标提取结果 —— 可编辑；已修正的不再重跑
work/cache/<sha>/page_N.md     OCR 缓存（按源文件哈希）
work/evaluation.json           完整评审结果
work/reports/*.docx            三份交付物
```

### 3.4 1.0 计划新增模块（P2–P5）

| 新模块 | 阶段 | 用途 |
| --- | --- | --- |
| `app/retrieval.py` | P2 | 关键词/标题定位章节，长投标文件只送相关表格进提示词——取代字符预算截断。 |
| `app/verify.py` | P2 | 对每条 `present=false` / `complies=no` 结论做对抗式二次校验后才入报告。 |
| `app/fx.py` | P2 | 按招标截标日取值的确定性汇率表。 |
| `app/audit.py` | P2 | 每条结论的审计记录：模型 id、提示词哈希、时间戳。 |
| `.github/workflows/ci.yml` | P2 | 每次 push 跑离线测试套件。 |
| `deploy/vllm/` | P3 | DGX Spark（arm64）的 vLLM 启动配置、模型下载/量化说明。 |
| `tools/regression.py` | P4 | 对照真实历史报告的黄金集比对。 |
| `backend/` 批量队列 | P5 | 多项目串行队列、可断点续跑，支撑 60 家投标的夜间批处理。 |

### 3.5 质量门

每个阶段保持三条不变式：（1）报告中所有数字仅凭代码即可复算；（2）每条否定性
结论附带评审员一步可核查的证据；（3）离线测试套件零网络、零真实客户数据运行，
CI 永远不可能泄露任何资料。
