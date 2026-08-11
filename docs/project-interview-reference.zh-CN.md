# Repo Agent 项目面试参考书

> 最近验证：2026-07-13
> 面向场景：简历深挖、技术面、系统设计面、项目答辩、开源项目讲解
> 一句话定位：Repo Agent 是一个“证据优先”的代码仓库调查与 Bug 定位系统。它不是急着替用户改代码，而是先解析仓库、构建代码图、检索证据、验证证据链，再把定位结果、置信度、证明对象、报告和可回放产物交给人或下游 Coding Agent。
>
> 零基础建议：先读 `docs/repo-agent-course-notes.zh-CN.md`，再读本文；面试前用 `docs/interview-defense-playbook.zh-CN.md` 做压力问答。本文第 30～32 章记录 2026-07-13 的真实代码审计、优化证据和新增刁难题。

## 0. 当前项目做到什么程度了

先给结论：这个项目已经不是原型 Demo，而是一个功能完整、可运行、可测试、可演示、可发布报告产物的 Python CLI + 本地 Web Studio + 代码检索/证明评测系统。它的核心产品形态已经打通，重点能力包括：

- 本地仓库解析：支持 Python、JavaScript、TypeScript、HTML、CSS 的轻量结构解析。
- 符号抽取：能抽取函数、类、路由、handler、imports、calls。
- 仓库索引：把源码切成文件级、符号级、chunk 级证据单元。
- 检索排序：结合词法匹配、文件角色、语义投影、图关系、路由锚点、重排规则。
- 图搜索：在 route、handler、import、call 等边上做 bounded MCTS-style graph search。
- 证明对象：输出 Proof-Carrying Retrieval，包括 route anchors、supporting paths、proof graph、decoy audit。
- 报告系统：能生成 HTML、Markdown、JSON、SARIF、release pack、scorecard。
- 证明回放：能把 JSON evidence bundle 放回当前仓库验证证据是否还成立。
- 证明突变测试：自动破坏证据 bundle，检查 proof replay 能否识别失效。
- 反事实/硬负例评测：用 admin、legacy、mock、documentation bait 等干扰项检验定位是否稳健。
- 对抗证明攻击：通过 JSON DSL 生成攻击变体，做 leaderboard、triage、policy synthesis、adaptive attack、repair、certificate。
- 时间维度回归：跨 git 历史检查 proof contract 何时失效，推断 successor symbol，生成迁移 patch plan。
- 多 Agent 证据法庭：把 retrieval、graph、proof、mutation、red-team、temporal 等证据变成 claim ledger 和 challenge ledger。
- 工程执行模式：可选 model tool-calling loop，在 workspace copy 中执行受限编辑、验证、review，再 apply 回源仓库。
- Web Studio：提供浏览器里的项目问答、证据查看、工具面板、报告预览、工程运行管理。
- CI 和测试：GitHub Actions 覆盖 Python 3.11/3.12、compileall、node syntax check、eval、counterfactual、ablation、proof replay、mutation、scorecard、release pack、PR guard、pytest。

### 0.1 当前工作区实际验证状态

我在当前工作区运行了以下命令：

```powershell
python -m compileall repo_agent tests examples
node --check web\app.js
python -m pytest
```

结果：

- `python -m compileall repo_agent tests examples`：通过。
- `node --check web\app.js`：通过。
- `python -m pytest -q --basetemp=<仓库内临时目录>`：160 项全部通过，耗时约 246 秒。

这意味着当前代码至少在语法层、Web JS 语法层、pytest 自动化测试层是可用的。

### 0.2 当前 Git 工作区状态

当前分支：

```text
main...origin/main
```

当前存在大量未提交改动和新增文件，项目处于“功能扩展已完成但尚未整理提交”的状态。`git diff --stat` 显示已有 tracked 文件改动约：

```text
24 个以上 tracked 文件存在改动，另有多项新增模块、测试、文档和演示资源
```

未跟踪新增内容包括：

- `repo_agent/contract.py`
- `repo_agent/court.py`
- `repo_agent/impact.py`
- `repo_agent/proof.py`
- `repo_agent/temporal.py`
- 多个 JSON spec/cases 文件
- 多个 tests 文件
- 多个报告和图片资源
- `docs/interview-case-study.md`
- `examples/counterfactual_agent_app/`

面试表达时要注意：可以说“当前本地工作区已经完成这些能力并通过测试”，但如果对方问“是否已经发布到远端”，要诚实说“当前还有大量未提交变更，需要做一次提交整理和 release gate 复核”。

### 0.3 已有报告指标

当前 `reports/` 下已有多类可展示报告。关键指标如下：

内置 eval：

```text
Cases: 11
Top-1 accuracy: 100.00%
Top-3 accuracy: 100.00%
MRR: 1.000
Average confidence: 0.95
```

反事实硬负例：

```text
graph_mcts: Top-1 100.00%, Top-3 100.00%, MRR 1.000, Distractor@1 0.00%
```

Portable benchmark adapter：

```text
Cases: 10
Top-1: 100.00%
Top-3: 100.00%
MRR: 1.000
Distractor@1: 0.00%
Average confidence: 0.96
```

Proof reliability scorecard：

```text
Grade: A
Score: 100/100
Status: pass
Proof status: proved
Strict replay status: valid
Mutation detection: 5/5
```

Temporal repair scorecard：

```text
Grade: A
Score: 100/100
Cases: 4
successor_top1: 100.00%
negative_control_abstention: 100.00%
causal_graph_delta: 100.00%
migration_ready: 100.00%
```

Multi-Agent Evidence Court：

```text
Verdict: accepted
Grade: A
Score: 100/100
Claims: 6/6 passed
Challenges: 5/5 discharged
```

这些指标不是大规模通用 benchmark 的胜利宣称，而是项目内置 fixtures 和 portable suite 上的可复现质量信号。面试时要把尺度说清楚：这是“自带基准、硬负例、对抗生成、证明验证”的完整可靠性闭环，不等于已经在 SWE-bench 全量任务上证明领先。

## 1. 用三种层次讲清这个项目

### 1.1 给非技术面试官的 30 秒版本

Repo Agent 是一个帮助开发者理解陌生代码库的工具。传统 AI 编程工具经常直接修改代码，但它们可能不知道真正相关的文件在哪里。Repo Agent 先做调查：它会扫描仓库、识别函数、接口、调用链，然后回答“这个功能在哪里实现”“这个 bug 可能在哪个 handler”“这个 route 最终写响应的是哪个函数”。它会给出证据链、置信度和可打开的报告，帮助人或后续 Coding Agent 更安全地改代码。

### 1.2 给技术面试官的 2 分钟版本

Repo Agent 的核心是一个 evidence-first repository investigation pipeline。系统先通过 parser 抽取文件事实、符号、路由和调用关系，然后构建 `RepositoryIndex`。用户提问后，它会：

1. 做 query planning，识别 intent、target roles、target languages、hop budget。
2. 对文件做 file scouting，先找可能相关的文件。
3. 对 chunk 做 lexical scoring 和 deterministic semantic projection。
4. 从 seed hits 出发，在 route、handler、call、import graph 上做 bounded MCTS-style graph search。
5. 对 query 中出现的精确 route literal 做 route-anchor boost。
6. 对候选结果做 multistep rerank，处理 public/admin/legacy/mock 等 route-family conflict。
7. 生成 answer、diagnostics、graph search audit、proof-carrying retrieval 和 decoy audit。
8. 可导出 HTML report、JSON evidence bundle、Markdown handoff。
9. 后续可 replay proof、mutate proof、生成 scorecard、impact analysis、regression contract、PR guard。

它有可选的 OpenAI-compatible model tool-calling loop，但 deterministic retrieval 路径不依赖 API key，因此项目不是单纯 LLM wrapper。

### 1.3 给资深系统设计面的 5 分钟版本

Repo Agent 把“代码仓库问答/定位”拆成四层：

- Representation layer：从源码抽取 `Symbol`、`CodeChunk`、`FileFact`、`GraphEdge`。
- Retrieval layer：用 query plan、词法特征、文件角色、局部语义投影、图扩展和重排规则找到 ranked evidence。
- Verification layer：把结果包装成 proof object，可 replay、可 strict edge verification、可 mutation lab、可 contract/PR guard。
- Product layer：CLI、Web Studio、HTML report、evidence bundle、release pack、agent court、engineering workspace mode。

设计上最重要的判断是：在代码修改之前，先证明“要看哪里”。所以它不像 IDE Agent 那样以 patch 为核心，而是以 localization、traceability、falsifiability 为核心。

## 2. 仓库结构总览

主要目录：

```text
repo_agent/
  __main__.py        CLI 总入口，包含 eval、benchmark、release-pack、proof-attack、temporal 等大量子命令
  agent.py           问答 Agent、模型工具调用、答案组合、证据诊断、证明对象构造
  indexer.py         仓库索引、检索、语义投影、图搜索、重排
  parsers.py         Python/JS/HTML/CSS 源码结构解析
  models.py          核心 dataclass 数据模型
  tools.py           Agent 可用的安全仓库工具
  runtime.py         CLI/Web 共享的运行时编排、缓存、报告、工程 run 管理
  engineering.py     可选工程执行 Agent，workspace edit、verify、review、timeline
  proof.py           proof replay、strict replay、mutation lab、proof scorecard
  impact.py          proof-guided impact analysis
  contract.py        proof regression contract、contract verify、PR guard、SARIF
  temporal.py        跨 git 历史的 proof regression、successor inference、migration plan
  court.py           multi-agent evidence court
  report.py          HTML report 渲染
  bundle.py          evidence bundle 生成
  server.py          本地 HTTP Web Studio 服务
  security.py        路径、问题长度、top-k、命令 allowlist 安全控制
  llm.py             OpenAI-compatible LLM adapter
  memory.py          repository brief / memory
  cache.py           索引缓存
  ignore.py          忽略生成目录、敏感文件、缓存目录
web/
  index.html         Web Studio 页面结构
  app.js             Web Studio 前端逻辑
  styles.css         Web Studio 样式
examples/
  simple_agent_app/
  simple_fastapi_app/
  simple_rag_app/
  counterfactual_agent_app/
tests/
  pytest 测试，包括 bundle、indexing、security、server assets、engineering、temporal、eval reporting、agent court
reports/
  已生成的评测、证明、对抗、时序、release pack、scorecard、SARIF 等产物
docs/
  文档、路线图、benchmarking、comparison、interview case study
```

项目依赖很克制：`pyproject.toml` 里 runtime dependency 只有 `numpy>=2.0`，dev dependency 是 `pytest>=8.0`。这能支撑一个面试亮点：核心检索能力尽量本地、轻量、可复现，而不是绑定大型外部服务。

## 3. 核心数据模型

文件：`repo_agent/models.py`

### 3.1 Symbol

`Symbol` 表示从源码里抽出的结构单元：

- `name`：函数名、类名、路由符号名。
- `kind`：`function`、`class`、`route` 等。
- `start_line` / `end_line`：源代码行范围。
- `calls`：该符号内部调用的函数名。
- `route_path`：如果是路由，保存 path。
- `handler_names`：路由绑定的 handler。

面试解释：Symbol 是从“源码文本”进入“代码图”的第一步。没有它，系统只能做全文搜索；有了它，才能知道某个 route 指向哪个 handler、某个 handler 调了哪些函数。

### 3.2 CodeChunk

`CodeChunk` 是检索时真正打分的证据单位。它既可以是整个文件，也可以是一个符号级片段。关键字段：

- `chunk_id`
- `repo_root`
- `relpath`
- `language`
- `text`
- `start_line` / `end_line`
- `symbol_name`
- `symbol_kind`
- `metadata_tokens`
- `imports`
- `calls`
- `route_path`
- `handler_names`

`source_label` 属性会把 chunk 展示为：

- `server.js:handlePublicChat`
- `app.py:post_api_chat`
- `web/app.js`

这个 label 很重要，因为报告、proof、bundle、contract、PR guard 都围绕它引用证据。

### 3.3 FileFact

`FileFact` 是文件级摘要：

- 文件路径
- 语言
- 行数
- imports
- symbol_names
- routes
- roles

它用于 file scouting，也就是在 chunk 级检索之前先判断哪些文件值得重点读。

### 3.4 QueryPlan

`QueryPlan` 表示对用户问题的结构化理解：

- `mode`
- `intent`
- `focus_terms`
- `target_roles`
- `target_languages`
- `hop_budget`

比如问题里有 `api`、`endpoint`、`接口`、`路由`，会倾向 `api_lookup`，目标角色是 backend/api/entrypoint，目标语言包含 JS/Python/TS。问题里有 `style`、`样式`，会倾向 CSS/front-end。

### 3.5 GraphEdge

`GraphEdge` 是仓库图的边：

- source chunk id
- target chunk id
- label
- weight

边的来源包括：

- route -> handler
- function -> called function
- file -> imported file
- route/function 等结构关系

### 3.6 RetrievalHit 和 InvestigationBundle

`RetrievalHit` 是一个候选答案：

- chunk
- score
- matched_terms
- reasons

`InvestigationBundle` 是一次检索调查的完整中间结果：

- mode
- focus_terms
- seed_hits
- final_hits
- graph_edges
- trace
- graph_search
- proof

面试里可以说：系统不是只返回 top-1，而是保留了整个 investigation trace，这给 explainability、debugging、评测、HTML 报告、proof replay 都提供了基础。

## 4. Parser 层：如何从源码抽结构

文件：`repo_agent/parsers.py`

### 4.1 支持语言

`detect_language` 根据后缀识别：

- Python
- JavaScript
- TypeScript
- HTML
- CSS

这不是完整编译器级 parser，而是面向仓库定位任务的轻量 parser。它的目标不是完全理解语义，而是抽出足够有用的结构：函数、类、路由、handler、调用、imports。

### 4.2 Python 解析

Python 解析走 AST：

- `ast.parse(text)` 失败时返回空 symbol，保证索引过程不因为坏文件崩溃。
- 遍历 top-level import/import-from。
- 遍历函数、异步函数、类。
- 对函数 decorator 做 route extraction。

可识别的 Python route 风格包括：

- FastAPI 风格：`@app.get("/path")`
- Flask 风格：`@app.route("/path", methods=["POST"])`
- 通过 `_expand_python_route_methods` 识别 `route` / `api_route` 的 methods。

Python route 会变成一个 `kind="route"` 的 Symbol，并且 `calls` 指向被 decorator 包裹的函数。这一步很关键：它把 decorator 路由变成了 graph edge 的起点。

### 4.3 JavaScript/TypeScript 解析

JS/TS 解析主要靠正则启发式：

- import/require 抽取。
- 函数声明、箭头函数、class 抽取。
- Express 路由抽取，如 `app.post("/api/chat", handler)`。
- chained router 抽取，如 `router.route("/x").post(handler)`。
- 从 route snippet 中抽 handler 名称。

它不是 Babel/TypeScript AST 级别，但优点是轻量、无额外依赖、适合 demo 和多语言 fixture。

面试风险点：如果对方问复杂 JS 语法、动态路由、装饰器、嵌套路由是否都支持，要承认目前是 lightweight parser，不是完整语言服务器。后续路线可以引入 Tree-sitter 或语言服务器协议。

### 4.4 HTML/CSS 解析

HTML/CSS 主要抽 imports/static references：

- HTML 里的 script/link/src/href。
- CSS 里的 import/url。

这样 Web Studio 或前端相关问题能从 `web/index.html` 关联到 `web/app.js`、`web/styles.css`。

## 5. Indexer 层：项目的技术心脏

文件：`repo_agent/indexer.py`

这是核心文件，约 1640 行。`RepositoryIndex` 承担：

- 保存 chunks、file facts、graph edges。
- query planning。
- file ranking。
- chunk scoring。
- semantic projection。
- graph search。
- route anchor boosting。
- multistep reranking。
- payload serialization。

### 5.1 build_index

`build_index` 的职责：

1. 遍历仓库文件。
2. 跳过 ignored/generated/protected 路径。
3. 控制文件数和单文件大小。
4. 读取文本。
5. 调用 `analyze_source` 得到 imports 和 symbols。
6. 生成文件级 chunk。
7. 生成符号级 chunk。
8. 生成 FileFact。
9. 构建 GraphEdge。
10. 返回 RepositoryIndex。

面试时可以把它类比成一个简化版本地代码搜索引擎的 indexing phase。

### 5.2 Query Planning

`RepositoryIndex.investigate` 的第一步是：

```text
mode = classify query
plan = _plan_query(query, mode)
```

`_plan_query` 会从用户问题里提取：

- 是否是前端查询。
- 是否是样式查询。
- 是否是交互逻辑查询。
- 是否是 API/route/endpoint 查询。
- 是否是 flow trace。
- 是否需要更大的 hop budget。
- 是否偏 Python/JS/CSS。

例子：

- “聊天接口的流式输出在哪里实现？”
  倾向 API lookup + flow trace + streaming。
- “网页样式在哪里？”
  倾向 style lookup + css。
- “public /api/chat endpoint 最终写 token 的函数是谁？”
  倾向 route-grounded flow trace + response writer。

### 5.3 File Scout

在 chunk 级检索之前，先用 `_rank_files` 对文件做粗排。

输入是 QueryPlan 和 FileFact。打分依据包括：

- 文件路径是否匹配关键词。
- 文件角色是否匹配 target roles。
- 文件语言是否匹配 target languages。
- 文件里的 symbol/routes/imports 是否覆盖 focus terms。
- 角色，如 backend/api/frontend/styles/tests/config。

这样做的意义是减少搜索噪声，并给后续 chunk rerank 提供 `file scout +x.x` 的 boost。

### 5.4 Primary Retrieval

`_retrieve_primary_hits` 会对 chunk 进行基础打分。核心来自 `_score_chunk`，特征包括：

- query token 和 chunk token overlap。
- symbol 名称匹配。
- route path 匹配。
- handler names 匹配。
- imports/calls 匹配。
- metadata tokens 匹配。
- semantic score。
- 文件角色。
- intent-specific boosts。

这一步生成 seed hits，是图搜索的起点。

### 5.5 Deterministic Semantic Projection

项目没有依赖外部 embedding API，而是用本地 deterministic semantic features。大体思路是：

- 对 chunk 和 query 做 tokenization。
- 构建 doc frequency / feature matrix。
- 使用 `numpy` 做轻量语义投影。
- 生成每个 chunk 的 semantic score。

它不是大型语义模型，但适合本地、低成本、可复现环境。面试说法：这是一种“在没有 API key 时仍然可运行的 semantic-ish baseline”，不是试图替代专业 embedding 模型。

### 5.6 MCTS-style Graph Search

`mcts_graph_boosts` 和 `_mcts_graph_boosts` 是项目亮点。

流程：

1. 从 seed hits 的 chunk id 出发。
2. 在 graph neighbors 中选择候选边。
3. 用 edge score 做选择。
4. 沿图走 max depth。
5. 到达节点后计算 node reward。
6. reward 反向传播到 path 上。
7. 根据 visits、average reward、search pressure 生成 boost。
8. 输出 top visited nodes 和 trace。

它不是严格学术版 MCTS，也没有完整 tree policy/value network，但保留了几个关键思想：

- bounded exploration
- visit count
- exploration/exploitation
- reward
- backpropagated boost
- traceable path

面试表达时可以说“MCTS-style”而不是过度宣称“完整 MCTS 规划器”。

### 5.7 Route Anchor Boosts

`_route_anchor_boosts` 是硬负例鲁棒性的关键。

当 query 中出现 `/api/chat` 这类 route literal 时，系统会：

1. 找到仓库图里 exact route match 的 route chunk。
2. 从这个 route chunk 出发做 BFS-like path expansion。
3. 对 route-path 上的 handler、writer、persistence function 加 boost。
4. 如果问题问 handler，就加强 depth 1 function。
5. 如果问题问 response writer，就加强写响应的深层函数。
6. 如果候选 chunk 被 query 排除，扣分。
7. 如果候选是其他 route，降低 boost。

这解释了为什么它能区分：

- public `/api/chat`
- admin `/api/admin/chat`
- legacy chat
- preview/mock/doc bait

面试核心句：路由定位问题不能只看文本相似度，因为 admin/legacy/mock 往往文本更像；必须用 exact route anchor 把检索约束到真实执行路径。

### 5.8 Multistep Rerank

`_rerank_multistep` 把 seed hits、file boosts、relation boosts、semantic scores 合在一起，进行任务特定重排。

典型规则：

- route-reachable chunks 加分。
- off-route writer decoy 扣分。
- route-family conflict 扣分，如 query 没提 admin 但候选含 admin。
- handler-function target 加分。
- response-writer target 加分。
- persistence target 加分。
- streaming handler disambiguation 加分。
- retrieval library boundary 加分。
- overview/file-level chunk 在 route query 中降权。

这是一种“可解释的 deterministic reranker”。每个加减分都有 reason，最后报告里能看到：

- `exact route path evidence`
- `response-writer target`
- `route-family conflict`
- `off-route writer decoy`
- `handler-function target`

这比黑盒 reranker 更容易做诊断和面试讲解。

### 5.9 为什么不是简单 grep

grep 可以找到关键词，但不能回答：

- 哪个 route 对应哪个 handler？
- public route 和 admin route 谁是真正相关？
- route handler 最终调用哪个 writer？
- top-1 为什么可信？
- 如果 handler 改名，之前证据是否失效？
- 这个证据能不能作为 PR contract？

Repo Agent 的价值就是把“文本命中”升级成“证据链”。

## 6. Agent 层：如何回答问题

文件：`repo_agent/agent.py`

`RepoAgent` 有两条路径：

- deterministic path：不用模型，直接用 `RepositoryIndex.investigate` 得到结果并组合答案。
- model path：如果配置了 OpenAI-compatible model，可以让模型调用安全工具进一步调查。

### 6.1 Deterministic Answer

`answer` 会：

1. 调用 `_investigate`。
2. 构建 diagnostics。
3. 构建 proof。
4. 根据问题是否包含 CJK 选择中文或英文回答。
5. 返回 `AgentResult`。

### 6.2 Evidence Diagnostics

`build_evidence_diagnostics` 会计算：

- top score
- second score
- score gap
- evidence count
- unique files
- graph edge count
- matched terms
- symbol hits
- route hits
- strengths
- warnings
- confidence
- label high/medium/low

置信度不是模型自信，而是基于检索质量的启发式评分。它考虑：

- 是否找到 ranked evidence。
- top score 是否足够高。
- top-1 和 top-2 是否有明显 gap。
- query terms 是否匹配代码词汇。
- 是否有 graph support。
- evidence 是否跨文件。
- 是否有 symbol-level/route-level evidence。

面试里要强调：这是 retrieval confidence，不是事实真值保证。真正的保证来自 proof replay、strict edge verification、tests 和人工 review。

### 6.3 Proof-Carrying Retrieval

`build_evidence_proof` 会把一次定位包装成 proof object。

关键字段：

- `schema_version`
- `strategy`
- `status`
- `claim`
- `top_hit`
- `route_literals`
- `checks`
- `supporting_paths`
- `proof_graph`
- `decoy_audit`
- `warnings`

Proof status：

- `proved`：有 route anchor，且 top hit 在 route path 上。
- `partial`：图搜索跑了，但 route anchoring 不完整。
- `unanchored`：没有 route anchor。

### 6.4 Proof Graph

Proof graph 是证据对象的图形化/机器可读结构，通常包含：

- route anchor node
- top hit node
- supporting path nodes
- graph-MCTS visited nodes
- decoy candidate nodes
- route/path/proof edges

它让下游工具不用解析自然语言，也能知道“证据为什么成立”。

### 6.5 Decoy Audit

`_build_decoy_audit` 会把高分但被拒绝的干扰项显式列出来。

一个 decoy audit entry 通常说明：

- 候选 label。
- 是否在 route path 上。
- 分数 gap。
- roles，如 admin/legacy/mock/notes。
- rejection reason。

面试亮点：很多系统只展示最终答案，Repo Agent 展示“为什么不是另一个看起来很像的答案”。这对调试、评审和对抗鲁棒性很关键。

### 6.6 Model Tool-calling 路径

如果 `--use-model` 打开，并配置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Agent 可以调用工具：

- `repo_brief`
- `find_relevant_code`
- `list_directory`
- `search_text`
- `read_file`
- `startup_hints`
- `verify_project`

但模型只是增强调查，不是核心依赖。没有模型时，deterministic path 仍然可用。

## 7. Runtime 层：CLI 和 Web 共享编排

文件：`repo_agent/runtime.py`

`RepoAgentRuntime` 是服务层/应用层，职责包括：

- 加载配置。
- 管理 reports、runs、cache。
- 加载或构建 index。
- 封装 ask/report/bundle/impact。
- 封装 engineer/resume/list/apply run。
- 提供 health 信息。
- 提供 workspace tools 给 Web Studio。

### 7.1 Cache

`IndexCache` 根据仓库 signature 缓存索引。Runtime 同时有内存缓存和磁盘缓存：

- 内存：避免同一进程重复构建。
- 磁盘：避免重启后重新索引。

如果 `force_rebuild` 为 true，则跳过缓存重建。

### 7.2 Ask / Report / Bundle

`ask`：

- validate repo path。
- validate question。
- load index。
- 创建 RepoAgent。
- 返回 AgentResult。
- 写 audit log。

`generate_report`：

- 先 ask。
- 调用 `write_html_report`。
- 写入 reports。

`generate_bundle`：

- 先 ask。
- 调用 `build_evidence_bundle`。
- 按 Markdown/JSON 输出 portable artifact。

### 7.3 Engineer

`engineer`：

- 验证 repo path 和 task。
- 默认 execution mode 是 `workspace`。
- 创建 `runs/<run_id>/workspace` 副本。
- 在副本上加载 index。
- 运行 EngineeringAgent。
- 持久化 run 记录。

这说明项目对自动改代码非常谨慎：默认不碰源仓库，而是在 workspace copy 中试运行，确认后才 apply。

## 8. Security 层：本地工具为什么相对安全

文件：`repo_agent/security.py`

### 8.1 路径安全

`validate_repo_path`：

- resolve path。
- 必须存在且是目录。
- 必须在 allowed roots 内。

`safe_join`：

- 防止 path traversal。
- 保证目标路径在 base dir 之内。

### 8.2 问题和 top-k 限制

`validate_question`：

- 去空。
- 不能为空。
- 不能超过 `max_question_chars`。

`clamp_top_k`：

- 把 top-k 限制在配置上限内。

这防止超长输入和过大结果导致资源滥用。

### 8.3 命令 allowlist

允许的验证命令包括：

```text
npm test
npm run test
npm run build
npm run lint
python -m pytest
python -m repo_agent eval
python -m compileall <paths>
node --check <file>
uv run pytest
```

`is_safe_verification_command` 会按 executable 分流：

- npm 只允许 test/build/lint。
- python 只允许 pytest、repo_agent eval、compileall relative paths。
- node 只允许 `node --check <js-like-file>`。
- uv 只允许 `uv run pytest`。

工具执行时使用 `subprocess.run(..., shell=False)`。面试要强调：这是为了避免把用户输入直接送 shell 执行。

### 8.4 保护目录和文件

忽略/保护范围包括：

- `.git`
- caches
- reports
- runs
- logs
- env/secrets
- build outputs

这样索引不会把生成物、敏感文件、历史运行副本混入 evidence，也降低误写风险。

## 9. Tools 层：Agent 可以操作什么

文件：`repo_agent/tools.py`

`RepoTools` 是模型和工程 Agent 的工具后端。

只读工具：

- `repo_brief`
- `plan`
- `semantic_scores`
- `scout_files`
- `read_candidates`
- `follow_neighbors`
- `mcts_graph_boosts`
- `rerank`
- `relevant_edges`
- `list_directory`
- `search_text`
- `read_file`
- `startup_hints`
- `infer_verification_command`

写工具：

- `replace_text`
- `write_file`

执行工具：

- `run_command`

写和执行都有保护：

- 只能访问 repo-relative path。
- ignored/protected path 不能读写。
- `write_file` 有大小限制。
- `run_command` 必须命中 allowlist。
- 执行时 `shell=False`。

## 10. Engineering Mode：从调查到受限修改

文件：`repo_agent/engineering.py`

这是“可选工程执行能力”，不是项目主轴。它适合演示 Repo Agent 在定位之后也能做小型受控修改。

### 10.1 EngineeringRun

`EngineeringRun` 保存：

- run id
- repo root
- source repo root
- execution mode
- task
- status
- model
- messages
- events
- changed files
- snapshots
- verifier result
- reviewer result
- timeline
- diff
- answer

它是 run persistence 的核心。

### 10.2 EngineeringAgent

`EngineeringAgent.run` 流程：

1. 创建或恢复 run。
2. 如果没有 LLM 配置，标记 model unavailable。
3. 生成 plan。
4. 进入 model/tool loop。
5. 每次 tool call 都记录 event 和 timeline。
6. 修改文件前保存 snapshot。
7. run 结束后生成 diff。
8. auto verify。
9. reviewer risk analysis。
10. persist run。

### 10.3 Multi-agent timeline

虽然代码里不是多个独立进程 Agent，但它把流程角色化为：

- Coordinator Agent
- Planner Agent
- Investigator Agent
- Patch Agent
- Verifier Agent
- Reviewer Agent

每个 timeline event 有：

- agent
- phase
- status
- title
- summary
- details
- timestamp

这能在 Web Studio 里展示“谁做了什么”，也方便面试讲 agent orchestration。

### 10.4 Verifier

Verifier 能：

- 根据改动自动选择安全验证命令。
- 执行 allow-listed command。
- 分类失败类型：
  - test failure
  - syntax error
  - missing dependency
  - timeout
  - environment issue

### 10.5 Reviewer

Reviewer 能：

- 给 run 风险评分。
- 识别 public surface 变化。
- 检查是否缺少测试。
- 做 file-level risk reason。
- 给 suggested follow-up actions。

面试表达：这不是追求“全自动大改”，而是把 autonomous edit 限制在可审计、可验证、可回滚的范围。

## 11. Proof 系统：从解释到可验证

文件：`repo_agent/proof.py`

### 11.1 Replay Proof

`replay_proof` 会读取 JSON evidence bundle，并重新在当前仓库 index 上检查：

- top hit 是否存在。
- route literals 是否仍存在。
- supporting paths 是否仍存在。
- proof graph endpoints 是否仍存在。
- strict 模式下 route/path edges 是否被当前 graph edges 支撑。
- decoy audit 是否仍能拒绝原 decoy。

这解决一个关键问题：报告不是一次性的截图，而是一个可复验 artifact。

### 11.2 Strict Replay

普通 replay 可能只检查节点存在。Strict replay 更强，会检查 proof graph route/path edge 是否真的存在于当前仓库 route/call/import graph 中。

面试说法：strict replay 是轻量 proof checker，它让“证据链”从文字解释变成可执行校验。

### 11.3 Drift Diagnosis

如果 replay 失败，系统会分类：

- top-hit drift
- route-anchor drift
- execution-path drift
- stale proof-graph endpoints
- decoy-audit drift

并给出 follow-up action。

这比简单报错好，因为它告诉用户“为什么旧证据不可信了”。

### 11.4 Mutation Lab

`run_proof_mutation_lab` 会自动生成坏 bundle：

- 改坏 top hit。
- 移除 route anchor。
- 改坏 supporting path。
- 改坏 proof graph edge。
- 改坏 decoy audit。

然后检查 replay 是否能抓住这些错误。

当前 proof scorecard 显示 mutation detection 是 `5/5`。

## 12. Impact / Contract / PR Guard

### 12.1 Impact Analysis

文件：`repo_agent/impact.py`

`analyze_impact` 会从一个 proof top hit 出发，沿图做 upstream/downstream walk，输出：

- impacted nodes
- exposed routes
- impacted files
- risk items
- verification plan

作用：如果某个 proved target 要改，系统能告诉你可能影响哪些 route、调用者、被调用者、验证命令。

### 12.2 Regression Contract

文件：`repo_agent/contract.py`

`build_regression_contract` 把 evidence bundle 冻结为 future PR 的 invariants。合同里可包含：

- repository
- query
- top hit
- route literals
- supporting paths
- proof graph edges
- protected surfaces
- impact-derived invariants

`verify_regression_contract` 会在后续代码变化后检查这些 invariants 是否仍成立。

### 12.3 PR Guard

`guard_pr_with_contract` 会把 changed files 和 protected surfaces 比对，输出：

- status
- touched surfaces
- required checks
- GitHub annotations
- SARIF

这让“代码定位证据”进入 CI/PR 流程。面试亮点：项目不是只做一次问答，而是把问答结果沉淀成持续回归检查。

## 13. Temporal 系统：跨时间的证明修复

文件：`repo_agent/temporal.py`

Temporal proof regression 解决的问题：一个 proof contract 今天有效，未来某个 commit 后失效了，系统能不能定位从哪个 commit 开始坏，并推断新 symbol？

### 13.1 跨 git 历史 replay

`run_temporal_proof_regression` 会：

1. 解析 git repo 和 repo subdir。
2. 生成 commit list。
3. 导出 commit snapshot，而不是直接污染当前工作区。
4. 在 snapshot 上 replay contract。
5. 找 first failing commit。
6. 找 last passing commit。
7. 构建 proof graph delta。
8. 推断 temporal repair。
9. 生成 migration plan。

### 13.2 Successor Inference

`infer_proof_successors` 会给候选 successor symbol 打分，依据包括：

- route reachability
- predecessor call relation
- proof-path continuity
- name similarity
- token Jaccard
- route/call graph evidence

当前 temporal repair scorecard 是 4 个 synthetic cases 全部 100%。

### 13.3 Migration Plan

系统能输出 JSON Patch-style operations，辅助把旧 contract 迁移到新 symbol。

面试说法：这让 proof artifact 有生命周期管理能力，不只是一次性报告。

## 14. Court 系统：多 Agent 证据法庭

文件：`repo_agent/court.py`

Multi-Agent Evidence Court 不是真的让多个聊天 Agent 互相辩论，而是把不同证据系统变成角色化 claim：

- retrieval_advocate：top hit claim。
- graph_navigator：route path claim。
- proof_verifier：strict replay claim。
- mutation_skeptic：mutation resistance claim。
- red_team_skeptic：generated attack claim。
- temporal_guardian：temporal repair claim。
- arbiter：根据 claims 和 challenges 给 verdict。

当前报告：

```text
Verdict: accepted
Grade: A
Score: 100/100
Claims: 6/6 passed
Challenges: 5/5 discharged
```

面试亮点：很多 multi-agent demo 是纯自然语言投票，Repo Agent 的 court 是 claim ledger + challenge ledger + evidence hash，更像可审计的工程机制。

## 15. CLI：项目操作面

文件：`repo_agent/__main__.py`

这个文件目前很大，约 9088 行，包含大量 CLI 子命令和报告/benchmark/release-pack 逻辑。

### 15.1 基础命令

```text
repo-agent index
repo-agent ask
repo-agent map
repo-agent report
repo-agent bundle
repo-agent serve
```

### 15.2 Proof 命令

```text
repo-agent replay-proof
repo-agent proof-mutate
repo-agent proof-scorecard
```

### 15.3 Impact / Contract / PR 命令

```text
repo-agent impact
repo-agent contract
repo-agent verify-contract
repo-agent pr-guard
```

### 15.4 Temporal 命令

```text
repo-agent temporal-proof-regression
repo-agent temporal-repair-benchmark
repo-agent temporal-repair-scorecard
```

### 15.5 Benchmark / Eval 命令

```text
repo-agent eval
repo-agent ablate
repo-agent counterfactual
repo-agent benchmark-adapter
repo-agent benchmark-diagnose
repo-agent benchmark-repair-card
repo-agent benchmark-repair-synthesize
repo-agent benchmark-repair-verify-implementation
repo-agent benchmark-repair-compile
```

### 15.6 Proof Attack 命令

```text
repo-agent proof-attack
repo-agent proof-attack-leaderboard
repo-agent proof-attack-triage
repo-agent proof-attack-policy
repo-agent proof-attack-adaptive
repo-agent proof-attack-repair
repo-agent proof-attack-certificate
repo-agent proof-attack-scorecard
repo-agent proof-attack-cegar
```

### 15.7 Release / Frontier / Artifact 命令

```text
repo-agent release-pack
repo-agent verify-release-pack
repo-agent agent-frontier
repo-agent agent-frontier-ablate
repo-agent agent-frontier-interactions
repo-agent agent-frontier-stability
repo-agent agent-artifact-review
repo-agent agent-court
```

### 15.8 Engineering 命令

```text
repo-agent engineer
repo-agent resume
repo-agent runs
repo-agent apply-run
repo-agent bench
```

### 15.9 对 __main__.py 的诚实评价

亮点：

- 功能非常完整。
- CLI 面覆盖了从检索、证明、报告到发布门禁的全流程。
- 很多高级评测功能已经实际落地。

风险：

- 文件过大，职责过多。
- 后续维护应该拆成：
  - `cli.py`
  - `evals.py`
  - `benchmarks.py`
  - `proof_attacks.py`
  - `release_pack.py`
  - `frontier.py`
  - `renderers.py`

面试时可以主动说：为了快速形成完整 artifact pipeline，早期把很多 CLI/report 逻辑集中在 `__main__.py`；下一步会按 bounded context 拆分，降低维护成本。

## 16. Web Studio

文件：

- `repo_agent/server.py`
- `web/index.html`
- `web/app.js`
- `web/styles.css`

### 16.1 Server

`server.py` 使用 Python 标准库 HTTP server 风格实现本地服务。它暴露：

- health
- index/map
- ask
- report
- bundle/impact
- workspace tools
- engineering run
- runs list/resume/apply
- static assets

同时通过 `_resolve_static_dir` 和 safe path 逻辑保护 static file serving。

### 16.2 Frontend

Web Studio 支持：

- 输入 repo path。
- 切换 use model。
- index/map。
- ask 问答。
- 查看 ranked evidence。
- 查看 trace。
- 查看 graph search audit。
- 查看 proof panel。
- 查看 decoy audit。
- 生成 report。
- 生成 impact。
- 使用 workspace tool panel。
- 启动 engineering run。
- 查看 run timeline、verifier、reviewer。

面试表达：Web Studio 是为了把证据链可视化，而不是只是给 CLI 包一层壳。

## 17. 评测体系

项目的评测层非常丰富。你面试时可以按“从简单到高级”的顺序讲。

### 17.1 Eval

`repo_agent/eval_cases.json` 覆盖：

- chat endpoint localization
- route-to-handler
- session reset
- RAG upload
- RAG retrieval
- FastAPI decorator route
- frontend code/style

当前结果：

```text
11 cases
Top-1 100.00%
Top-3 100.00%
MRR 1.000
Average confidence 0.95
```

解释方式：Top-3 100% 表示系统总能把正确位置放进前三；Top-1 还有改进空间，说明某些问题可能先返回 route entry 而不是 deep handler。

### 17.2 Ablation

`ablate` 用来比较：

- lexical
- semantic
- no_graph
- hybrid
- graph_mcts

意义：证明图搜索、路由锚点、rerank 不是装饰，而是对 hard-negative 有实际贡献。

### 17.3 Counterfactual

`counterfactual` 是硬负例 benchmark：

- public chat writer vs admin/legacy/mock/doc decoys
- public chat handler vs legacy/admin handlers
- session restore persistence vs chat stream noise

当前 graph_mcts：

```text
Top-1 100%
Top-3 100%
MRR 1.000
Distractor@1 0%
```

### 17.4 Portable Benchmark Adapter

`benchmark-adapter` 允许外部 reviewer 用 JSON 描述：

- repo
- question
- expected path
- expected symbol
- distractors
- tags

当前 bundled portable suite：

```text
10 cases
Top-1 100%
Top-3 100%
MRR 1.000
Distractor@1 0%
```

### 17.5 Benchmark Diagnostics / Repair

这部分把 benchmark failure 变成可行动诊断：

- weak-case taxonomy
- group-level action items
- projected Top-1 repair ceiling
- repair card
- repair rule synthesis
- implementation verification
- compiler intervention plan

面试说法：项目不仅跑 benchmark，还把 benchmark 结果反馈到 retrieval repair pipeline。

### 17.6 Proof Attack

Proof attack 系统通过 JSON spec 生成对抗 mutations：

- admin-shadow writers
- near-route preview writers
- documentation bait
- generated decoys

然后生成：

- benchmark
- leaderboard
- triage
- defense policy
- adaptive attack
- repair
- minimax certificate
- scorecard
- CEGAR report

这是面试里很能体现“工程深度”的部分，但不要讲得玄。它的核心就是：用自动生成的反例持续攻击证据链，再把失败/弱点转成规则和门禁。

## 18. Release Pack 和 Artifact Integrity

`release-pack` 会把一组关键报告整理到 `reports/release-pack`，并生成 manifest。

Manifest 记录：

- artifact path
- SHA-256
- byte size
- artifact type

`verify-release-pack` 会检查：

- 文件是否存在。
- hash 是否匹配。
- size 是否匹配。

意义：demo 或论文式 artifact 可以被复验，避免报告被篡改或缺失。

## 19. CI

文件：`.github/workflows/ci.yml`

CI matrix：

- Python 3.11
- Python 3.12

主要步骤：

1. checkout
2. setup-python
3. install `-e ".[dev]"`
4. compile Python sources
5. node check Web JS
6. run eval
7. run counterfactual benchmark
8. run retrieval ablation
9. build proof bundle
10. strict replay proof
11. run proof mutation lab
12. build proof reliability scorecard
13. build release pack
14. verify release pack integrity
15. run proof-backed PR guard demo
16. upload SARIF
17. run pytest

面试表达：CI 不只是跑单元测试，还跑了核心 evidence/proof/release pipeline。

## 20. 测试体系

当前 tests：

- `test_agent_court.py`
- `test_bundle.py`
- `test_engineering_modes.py`
- `test_eval_reporting.py`
- `test_indexing.py`
- `test_parsers.py`
- `test_security.py`
- `test_server_assets.py`
- `test_temporal_regression.py`

当前本地结果：

```text
160 tests passed in about 246s
```

测试覆盖方向：

- parser 能否抽路由/符号。
- indexer 能否定位关键 handler。
- security 能否拒绝危险路径/命令。
- bundle 是否包含 proof/graph/diagnostics。
- server static assets 是否安全。
- engineering workspace/local mode 行为。
- eval/report/benchmark 输出。
- temporal regression 和 migration。
- agent court verdict。

## 21. 一条完整数据流

以问题为例：

```text
Which function finally writes streamed tokens for the public /api/chat endpoint?
```

流程：

1. 用户通过 CLI 或 Web Studio 提问。
2. Runtime validate repo path 和 question。
3. Runtime 加载或构建 RepositoryIndex。
4. RepoAgent 调用 index.investigate。
5. `_plan_query` 识别这是 API/flow/response-writer 问题。
6. `_rank_files` 找到可能相关的 `server.js`。
7. `_retrieve_primary_hits` 找到 route、handler、writer 候选。
8. `_mcts_graph_boosts` 从 seed hits 在图上探索。
9. `_route_anchor_boosts` 锚定 public `/api/chat`。
10. `_rerank_multistep` 给 `writeChatDelta` 加 response-writer 和 exact route path evidence，给 admin/legacy/mock decoy 扣分。
11. 生成 final hits。
12. 生成 graph edges。
13. 生成 diagnostics，置信度 high。
14. 生成 proof，status `proved`。
15. 生成 decoy audit，解释 admin/legacy 为什么不是答案。
16. 输出自然语言答案。
17. 可导出 HTML report。
18. 可导出 JSON bundle。
19. 可 replay-proof strict。
20. 可 proof-mutate 检验证明检查器。
21. 可 proof-scorecard 汇总为 A/100。
22. 可 contract 化并进入 PR guard。

这条链就是项目的“主线故事”。

## 22. 项目亮点清单

### 22.1 技术亮点

- 本地 deterministic retrieval，不依赖 API key。
- route-aware repository graph。
- MCTS-style bounded graph exploration。
- route literal anchoring。
- hard-negative-aware reranking。
- proof-carrying retrieval。
- proof graph export。
- contrastive decoy audit。
- strict proof replay。
- proof mutation lab。
- proof-guided impact analysis。
- regression contract 和 PR guard。
- temporal proof regression。
- successor inference 和 migration plan。
- multi-agent evidence court。
- portable benchmark adapter。
- adversarial proof attack CEGAR loop。
- release pack integrity manifest。
- workspace-first engineering mode。
- safe tool execution with allowlist and `shell=False`。

### 22.2 工程亮点

- 代码模块边界大体清晰：parser/indexer/agent/runtime/tools/proof/contract/temporal/web。
- 测试数量可观，当前 160 项全量回归通过。
- CI 覆盖主流程。
- 报告 artifact 丰富。
- Web Studio 有实际产品界面。
- 支持 CLI 和浏览器两种入口。
- 支持 Markdown/JSON/HTML/SARIF 多种输出。
- 对安全边界有明确实现。

### 22.3 产品亮点

- 定位在“代码修改前的证据层”，不是又一个 IDE Agent。
- 对陌生仓库 onboarding 很有用。
- 对 Code Review 和 PR 风险管理很有用。
- 对下游 Coding Agent handoff 很有用。
- 报告可给人看，bundle 可给机器看。

## 23. 当前不足和下一步

面试时主动讲不足，反而更可信。

### 23.1 Parser 不够完整

当前 Python 用 AST，JS/TS 用正则启发式。复杂 JS/TS 语法、动态路由、框架特定元编程可能漏掉。

下一步：

- 引入 Tree-sitter。
- 为 Express、FastAPI、Flask、Next.js、Django、Spring 等建立更完整 parser adapter。

### 23.2 Semantic projection 是轻量 baseline

当前 semantic 不依赖外部 embedding，这有可复现优势，但召回能力不如专门 embedding model。

下一步：

- 增加 optional embeddings。
- 保留 deterministic fallback。
- 做 learned reranker ablation。

### 23.3 `__main__.py` 过大

当前 CLI/report/benchmark/release 逻辑大量集中在 `__main__.py`，维护成本偏高。

下一步：

- 按 domain 拆分模块。
- CLI 只保留 argument parsing 和 dispatch。
- 报告渲染和 benchmark logic 移到独立模块。

### 23.4 Benchmark 规模仍偏小

当前指标主要来自 bundled fixtures 和 portable suite，不代表真实世界所有仓库。

下一步：

- 增加第三方 repo localization cases。
- 增加 SWE-bench-style issue localization benchmark。
- 区分 file-level、symbol-level、path-level 指标。

### 23.5 Web Studio 还可以更产品化

当前 Web Studio 可用，但可以继续提升：

- 更好的 proof graph visualization。
- 更好的 run comparison。
- 更好的 report navigation。
- 更好的 onboarding wizard。

## 24. 面试高频问答

### Q1：这个项目解决什么问题？

回答：

它解决的是 AI 改代码前的上下文定位问题。很多 Coding Agent 直接尝试 patch，但真正困难的是先知道应该看哪个文件、哪个 route、哪个 handler、哪条调用链。Repo Agent 先解析仓库，构建代码图，检索证据，输出带置信度和证明链的定位结果。它可以帮人快速理解陌生仓库，也可以给下游 Coding Agent 提供可靠 handoff。

### Q2：它和 grep / ripgrep 有什么区别？

回答：

grep 只能告诉你哪些行包含关键词。Repo Agent 会把源码解析成符号和图：route 指向 handler，handler 调用 writer，文件之间有 import/call 关系。对于 `/api/chat` 这种问题，它不只是找 `chat` 字符串，而是锚定 public route，再沿执行路径找真正写响应的函数，并把 admin/legacy/mock decoy 显式拒绝。

### Q3：它和普通 RAG 有什么区别？

回答：

普通 RAG 多数是把文档 chunk embedding 后召回。Repo Agent 的 chunk 是代码结构感知的，包含 symbol、route、handler、calls、imports 等 metadata；检索后还会做 repository graph expansion、route anchor boosting、hard-negative rerank、proof generation 和 replay。它更像 codebase investigation engine，而不是文档问答 RAG。

### Q4：为什么不用模型直接读仓库？

回答：

成本高、上下文长、不可复现，而且很难解释为什么选某个文件。Repo Agent 先做本地 deterministic retrieval，能在没有 API key 时运行，还能输出 trace、confidence、proof 和 replay artifact。模型可以作为 optional investigator，但不是核心依赖。

### Q5：MCTS-style graph search 在这里怎么用？

回答：

系统先用词法/语义检索找到 seed hits，然后从这些节点出发在 repository graph 上探索。每次按 edge score 选择下一跳，走到一定深度后计算 node reward，再把 reward 回传给路径节点，最后根据 visits、average reward 和 search pressure 生成 boost。这样可以找到关键词不完全匹配但在执行路径上重要的 handler/writer。

### Q6：为什么 route anchor 重要？

回答：

因为代码库里常有多个相似 endpoint，比如 public `/api/chat`、admin chat replay、legacy chat、preview route。文本相似度可能把 admin 或 legacy 排很高。route anchor 会从 query 中提取 `/api/chat`，在仓库图里找到 exact route，然后只给这条执行路径上的 handler/writer 强 boost，对 off-route writer 和 route-family conflict 扣分。

### Q7：Proof-Carrying Retrieval 是什么？

回答：

它是对一次检索答案的机器可读证明包装。除了 top hit，还记录 route literals、graph search 是否运行、top hit 是否在 route path 上、supporting paths、proof graph、decoy audit 和 warnings。这样答案不是一句“我觉得在这里”，而是“这个 top hit 因为这些图路径和检查被证明支持”。

### Q8：Proof Replay 有什么价值？

回答：

代码会变。今天的报告明天可能失效。Proof Replay 会把 JSON evidence bundle 放回当前仓库重新检查 top hit、route anchor、supporting path、proof graph edge 和 decoy rejection 是否仍成立。Strict replay 还会检查 edge 是否真的存在于当前 graph。这样证据是可复验、可失效、可诊断的。

### Q9：Decoy Audit 解决什么问题？

回答：

它解决“为什么不是另一个相似答案”的问题。系统会把高分但错误的 admin/legacy/mock/doc bait 候选列出来，说明它们是否 route-anchored、分数差距、冲突角色、拒绝原因。这样报告不只展示正确答案，也展示对 hard negative 的防御。

### Q10：这个项目怎么保证安全？

回答：

第一，仓库路径必须在 allowed roots 内。第二，所有文件访问用 safe path，防止 traversal。第三，忽略 `.git`、`.env`、runs、reports、cache 等敏感或生成目录。第四，工程命令是 allowlist，执行时 `shell=False`。第五，默认工程模式在 `runs/<run_id>/workspace` 副本中编辑，不直接改源仓库。

### Q11：工程模式是不是会自动乱改代码？

回答：

不会。工程模式是实验能力，默认 workspace copy，所有工具调用、文件变更、验证输出、review 风险都会持久化。只有用户显式 `apply-run --confirm` 才会把变更应用回源仓库，而且 protected/generated paths 会被跳过。

### Q12：你怎么评测这个系统？

回答：

我做了多层评测。最基础是 eval cases，看 Top-1、Top-3、MRR、confidence。然后做 ablation，比较 lexical、semantic、no_graph、hybrid、graph_mcts。再做 counterfactual hard-negative，看 admin/legacy/mock decoys 下是否 distractor@1。再做 portable benchmark adapter，让外部 suite 能以 JSON 形式接入。最后做 proof replay、mutation lab、proof attack、temporal repair、agent court 等可靠性评测。

### Q13：当前指标如何？

回答：

当前工作区实际 pytest 是 160 项全量回归通过。内置 eval 是 11 cases，Top-1/Top-3 都是 100%，MRR 1.000。Portable benchmark adapter 是 10 cases Top-1/Top-3 都 100%。Proof reliability scorecard 是 A，100/100。Temporal repair scorecard 是 A，100/100。Multi-agent evidence court verdict 是 accepted，100/100。

### Q14：为什么 eval Top-1 不是 100%？

回答：

这是一个很真实的定位问题。有些问题问的是“接口最终调用哪个处理函数”，系统可能把 route entry 放在第一，把 deep handler 放在第二或第三。Top-3 100% 表明召回和候选排序足够可用，但 Top-1 还可以通过更细粒度 intent classification 和 handler-vs-route disambiguation 继续优化。

### Q15：这个项目最难的技术点是什么？

回答：

最难的是把代码检索从“关键词相似”提升到“执行路径证据”。具体包括：多语言轻量解析、构建 route/call/import graph、把用户 query 中的 route literal 转成图锚点、在图上做 bounded exploration、对 hard negative 做 rerank、最后把结果变成可 replay 的 proof artifact。

### Q16：如果仓库很大怎么办？

回答：

当前有 max files 和 max file bytes 限制，也有缓存和 ignored path 机制。大仓库下可以继续优化：增量索引、分目录索引、倒排索引、SQLite/FAISS/Annoy 等持久索引、按语言 server 做更精确解析、并行 build index、分层 retrieval。当前项目更像中小仓库和 demo benchmark 的完整闭环。

### Q17：为什么只依赖 numpy？

回答：

设计上希望基础功能本地可运行、可复现、安装简单。`numpy` 支撑轻量 semantic projection，其他能力尽量用标准库实现。未来可以 optional 加 embeddings、Tree-sitter、向量库，但不能让基础路径依赖外部服务。

### Q18：你会怎么继续优化？

回答：

优先级是：

1. 拆分 `__main__.py`。
2. 引入 Tree-sitter 提升 parser。
3. 增加真实外部仓库 benchmark。
4. 做增量索引和性能 profiling。
5. optional embedding/reranker。
6. 改进 Web Studio proof graph。
7. 把 proof contract 和 PR guard 接入更真实的 GitHub workflow。

### Q19：这个项目有没有过度工程？

回答：

功能面确实很宽，尤其 proof attack、frontier、court、temporal 等部分看起来研究味比较重。但主线是清晰的：仓库定位证据如何从检索结果变成可解释、可回放、可评测、可进入 CI 的 artifact。面试时我会承认 CLI/report 侧需要模块化，但也会强调这些高级产物不是装饰，它们服务于“证据可靠性”这一条主线。

### Q20：如果对方要求现场 Demo，你怎么演示？

建议流程：

1. 跑基础问答：

```powershell
python -m repo_agent ask --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?"
```

2. 生成 HTML 证明报告：

```powershell
python -m repo_agent report --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --output reports\demo-proof.html
```

3. 生成 JSON bundle：

```powershell
python -m repo_agent bundle --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --format json --output reports\demo-proof.bundle.json
```

4. Strict replay：

```powershell
python -m repo_agent replay-proof --bundle reports\demo-proof.bundle.json --strict --output reports\demo-replay.md
```

5. Mutation lab：

```powershell
python -m repo_agent proof-mutate --bundle reports\demo-proof.bundle.json --output reports\demo-mutation.md
```

6. 展示 scorecard：

```powershell
python -m repo_agent proof-scorecard --bundle reports\demo-proof.bundle.json --output reports\demo-scorecard.md
```

如果时间更短，只展示 `reports/proof-carrying-counterfactual.html`、`reports/proof-scorecard.md`、`reports/agent-court.md`。

## 25. 简历项目写法

### 25.1 一句话版本

设计并实现 Repo Agent，一个证据优先的本地代码仓库调查系统，通过源码解析、仓库图检索、路由锚点重排、证明回放和对抗评测，在 AI 改代码前提供可验证的文件/函数/执行路径定位证据。

### 25.2 三条 bullet 版本

- 构建 Python/JavaScript/FastAPI/Express 代码解析与检索管线，抽取函数、路由、handler、imports、calls，结合词法匹配、本地语义投影、MCTS-style 图搜索和 route-anchor rerank 输出 ranked evidence。
- 设计 Proof-Carrying Retrieval 机制，支持 proof graph、contrastive decoy audit、strict replay、mutation lab、impact analysis、regression contract、PR guard 和 SARIF 输出，把一次定位结果转成可回放的工程 artifact。
- 建立多层评测与可靠性门禁，包括 eval/ablation/counterfactual/portable benchmark/proof attack/temporal repair/agent court；当前本地 160 项 pytest 全量回归通过，内置 eval Top-1/Top-3 均为 100%，portable suite Top-1 100%，proof/temporal scorecard 均为 A/100。

### 25.3 系统设计版描述

Repo Agent 将代码仓库问答拆成 representation、retrieval、verification、product 四层。Representation 层从源码中抽取 Symbol、CodeChunk、FileFact 和 GraphEdge；Retrieval 层做 query planning、file scouting、semantic projection、graph MCTS、route anchor boosting 和 rerank；Verification 层把结果变成 proof bundle，支持 replay、mutation、contract 和 PR guard；Product 层提供 CLI、Web Studio、HTML report、release pack 和 workspace engineering mode。

## 26. 最适合展示的文件

优先看：

- `repo_agent/indexer.py`：核心检索和图搜索。
- `repo_agent/agent.py`：答案、diagnostics、proof、decoy audit。
- `repo_agent/proof.py`：proof replay 和 mutation lab。
- `repo_agent/contract.py`：proof contract 和 PR guard。
- `repo_agent/temporal.py`：temporal regression 和 successor inference。
- `repo_agent/engineering.py`：workspace engineering mode 和 verifier/reviewer。
- `repo_agent/security.py`：安全边界。
- `web/app.js`：Web Studio 交互。
- `tests/test_eval_reporting.py`：大量报告/评测行为测试。

如果面试官只给你 10 分钟讲代码，讲 `indexer.py`、`agent.py`、`proof.py`、`security.py` 四个就够。

## 27. 最适合展示的报告

- `reports/eval-report.md`
- `reports/counterfactual-report.md`
- `reports/benchmark-adapter.md`
- `reports/proof-scorecard.md`
- `reports/proof-replay-report.md`
- `reports/proof-mutation-report.md`
- `reports/proof-carrying-counterfactual.html`
- `reports/temporal-repair-scorecard.md`
- `reports/agent-court.md`
- `reports/release-pack/README.md`

展示顺序：

1. `eval-report`：说明基础定位能力。
2. `counterfactual-report`：说明 hard-negative 鲁棒性。
3. `proof-carrying-counterfactual.html`：说明可解释证据。
4. `proof-scorecard`：说明可验证可靠性。
5. `agent-court`：说明多证据仲裁。

## 28. 面试中的避坑话术

不要说：

- “这个系统能自动解决所有 bug。”
- “MCTS 一定比所有检索方法好。”
- “这些指标证明它超过 SWE-bench Agent。”
- “JS 解析完整支持所有语法。”
- “Proof 就是数学形式化证明。”

应该说：

- “它的定位是 AI 改代码前的 evidence layer。”
- “MCTS-style graph search 在 route/call graph 上提供 bounded exploration 和 traceable boosts。”
- “Proof 是工程意义上的可回放证据合同，不是定理证明。”
- “当前 benchmark 是 bundled fixtures 和 portable suite，下一步要扩大到第三方真实仓库。”
- “当前 parser 是 lightweight，未来可以用 Tree-sitter 提升覆盖。”

## 29. 用一句话收尾

Repo Agent 的核心价值不是“再做一个会聊天的编程助手”，而是把代码仓库定位这件事做成可索引、可追踪、可解释、可回放、可评测、可进入 CI 的证据工程。

---

## 30. 2026-07-13 真实代码审计与优化复盘

这一章可以直接当作面试中的“我如何发现并解决问题”案例。它不只列结果，还说明基线、根因、修复、测试和没有解决的部分。

### 30.1 审计顺序

本轮按下面顺序推进：

1. 查看目录、Git 状态和依赖，确认工作区已有大量未提交成果，不回退或覆盖现有修改。
2. 执行编译、JavaScript 语法、pytest 和关键 Flake8 检查，建立正确性基线。
3. 执行项目自带 `eval`、`ablate`、`counterfactual`，用真实排名指标寻找效果缺口。
4. 阅读 `security.py`、`agent.py`、`indexer.py` 的关键路径。
5. 每个修复都增加回归测试，最后跑完整测试套件。

一句话复述：

> 我分别用自动化测试验证功能、用静态检查验证代码质量、用产品 benchmark 验证检索效果，再用全量回归关闭修改风险。

### 30.2 先排除两种“假失败”

第一次运行时，系统 `py` 启动器没有关联解释器，报 `No installed Python found`；换到可用 Python 后，pytest 默认系统 Temp 又无权限，fixture 阶段报 `PermissionError`。二者都不是业务断言失败。

可靠命令是把临时目录放在仓库可写区域：

```powershell
python -m pytest -q --basetemp=.pytest_tmp\local-run
```

排障时要区分：

- 环境失败：解释器、依赖、权限、编码。
- 测试基础设施失败：fixture、临时目录、外部服务。
- 产品失败：断言错误、结果错误、异常未处理。

面试官会通过这个细节判断你是否只会“看到红色就改代码”。

### 30.3 修复一：阻止白名单可执行文件路径伪装

#### 现象

旧逻辑从第一个命令 token 提取文件名 stem，然后判断是不是 `npm`、`node`、`python`、`py`、`uv`。这会让下面的仓库内同名程序伪装成允许命令：

```text
.\tools\npm.cmd test
.\tools\node.exe --check web/app.js
./tools/uv run pytest
```

#### 根因

只验证“名称像谁”，没有验证“从哪里加载”。对于不会被替换为当前解释器的 npm/node/uv，`subprocess.run(shell=False)` 仍会执行用户给出的路径。

#### 修复

新增 `_is_bare_executable_name()`，要求可执行文件必须是无 `/`、无 `\`、无盘符、仅含安全文件名字符的裸命令名。路径伪装在进入原白名单分支前就被拒绝。

新增五个 Windows/Unix 路径伪装测试，并保留合法命令测试。

#### 安全边界必须诚实说明

Allowlist 不是 sandbox。`python -m pytest` 会导入测试代码，`npm test` 会运行 `package.json` 脚本。对不可信仓库仍需容器、低权限账户、网络隔离和资源限制。

面试标准回答：

> 我修复的是命令形状和可执行文件身份边界，减少 Agent 执行任意路径的风险；它不把仓库代码变成可信代码。

### 30.4 修复二：样式查询 Top-1 排名错误

#### 优化前证据

内置 eval 共 11 题，优化前：

```text
Top-1 accuracy: 90.91%
Top-3 accuracy: 100.00%
MRR: 0.955
```

“页面样式在哪？”返回：

```text
1. web/index.html
2. web/styles.css
```

具体分数显示 HTML 获得较强 semantic、web surface、file scout 和 graph hop boost；CSS 虽有 style boost，仍落后约 2 分。

#### 旧规则的问题

最终重排只对固定路径 `web/styles.css` 给很小的 boost：

- 强度不足，容易被其他信号覆盖。
- 假设目录固定，无法泛化到 `assets/theme.css`。

#### 优化方式

把路径特例提升为意图级规则：

```text
style_lookup + CSS language -> stylesheet intent boost
style_lookup + HTML language -> page-shell detour penalty
```

它不依赖 case ID、问题原文或固定路径。新增测试使用 `assets/theme.css`、`pages/dashboard.html`，验证非 `web/` 目录也能正确排序。

#### 优化后证据

```text
Top-1 accuracy: 100.00%
Top-3 accuracy: 100.00%
MRR: 1.000
```

如果被问“是不是手工规则过拟合”，要答：

> 这是 deterministic baseline 的领域先验，但抽象在 intent 和 language 层，并用不同目录结构做了回归。11 题仍是小样本，不能宣称通用领先，下一步必须在冻结的第三方 benchmark 上验证。

### 30.5 修复三：延迟类型注解存在未定义名

`agent.py` 使用 `from __future__ import annotations`，所以缺少 `RetrievalHit` 导入时，普通执行通常不立即报错；Flake8 报六处 `F821 undefined name`，而 `typing.get_type_hints()` 会在运行期触发 `NameError`。

修复：

- 正式从 `models.py` 导入 `RetrievalHit`。
- 对三个使用该类型的函数调用 `get_type_hints()` 做回归测试。
- 重新运行 Flake8 关键错误集合 `E9,F63,F7,F82`。

这个案例说明“测试通过”与“反射、文档生成、DI、Schema 工具能正确解析类型”是两个质量维度。

### 30.6 最终验证矩阵

| 检查 | 结果 | 证明范围 | 不证明什么 |
| --- | --- | --- | --- |
| Python `compileall` | 通过 | 语法可编译 | 不证明逻辑正确 |
| `node --check web/app.js` | 通过 | JS 语法有效 | 不证明浏览器交互正确 |
| Flake8 关键错误集 | 通过 | 无未定义名等高风险静态错误 | 不是完整风格检查 |
| pytest | 160 项全量通过，约 246 秒 | 当前测试无回归 | 不覆盖所有真实仓库 |
| 内置 eval | Top-1/Top-3 100%，MRR 1.000 | 11 个 smoke case 全对 | 样本小，不代表行业领先 |
| counterfactual | graph_mcts Top-1 100%，distractor@1 0% | 当前硬负例未骗过最终策略 | 干扰分布仍是自建 |
| tracked secret scan | 通过 | 当前正则未发现明显密钥 | 不替代专业扫描器 |

### 30.7 为什么没有直接拆分一万行的 `__main__.py`

它确实是当前最明显的可维护性技术债：CLI 参数、命令分发、benchmark、报告、release、proof attack 和 coordination 混在一个文件中。

但工作区已有约 1.5 万行未提交变更。此时做大规模机械搬迁会扩大冲突范围，也让行为回归更难归因。本轮先修安全、效果和静态正确性三个可独立验证的问题，把大重构列为下一阶段。

推荐拆分：

```text
repo_agent/cli/parser.py
repo_agent/cli/commands/core.py
repo_agent/cli/commands/proof.py
repo_agent/cli/commands/benchmark.py
repo_agent/cli/commands/release.py
```

顶层 `main()` 只 parse + dispatch；每条 command 使用明确 dataclass/TypedDict 输入输出。

### 30.8 其他仍存在的技术债

- Mypy 仍报告多处动态 dict、变量复用和类型收窄问题，不应靠大量 `type: ignore` 掩盖。
- JavaScript/TypeScript parser 主要是正则/启发式，不完整支持复杂 TSX、动态 import、元编程。
- 缓存签名主要依赖路径、mtime、size；极端情况下同大小且恢复 mtime 的修改可能漏失效。
- 简单 eval 中 `no_graph/hybrid/graph_mcts` 指标相同，不能用该集合证明 MCTS 独立增益。
- 默认允许 workspace 父目录是便利性取舍，产品化应改成显式最小 allowlist。
- 大量未提交/未跟踪成果需要按功能整理 commit，并在干净环境做 wheel 安装 smoke test。

---

## 31. 零基础到面试的最短执行路线

详细概念解释在 `docs/repo-agent-course-notes.zh-CN.md`。这里给出实践顺序。

### 第 1 阶段：会运行

记住五条命令：

```powershell
python -m repo_agent index --repo . --force
python -m repo_agent map --repo .
python -m repo_agent ask --repo . --question "Where is command validation implemented?"
python -m repo_agent eval
python -m pytest -q --basetemp=.pytest_tmp\learning
```

你必须能解释每条命令的输入、输出和失败位置。

### 第 2 阶段：看懂数据流

画出并背熟：

```text
source file
 -> SourceAnalysis/Symbol
 -> CodeChunk/FileFact
 -> GraphEdge
 -> QueryPlan
 -> RetrievalHit
 -> InvestigationBundle
 -> AgentResult/Proof
```

逐个回答：谁创建、谁消费、为什么存在。

### 第 3 阶段：按顺序读代码

1. `models.py`：先认识名词。
2. `parsers.py`：源码怎样变 Symbol。
3. `indexer.py:build_index()`：Symbol 怎样变 Chunk 和 Edge。
4. `RepositoryIndex._plan_query()`：问题怎样变计划。
5. `_rank_files()`、`_retrieve_primary_hits()`：粗排与初排。
6. `_mcts_graph_boosts()`、最终 rerank：图扩展与精排。
7. `agent.py`：怎样串成调查流程和 proof。
8. `runtime.py`：CLI/Web 如何复用用例。
9. `security.py`、`tools.py`：路径和命令边界。
10. `proof.py`、`contract.py`、`temporal.py`：证据怎样回放和跨时间验证。

### 第 4 阶段：能解释评分

不要背具体权重，背信号类别：

```text
final score
= lexical/semantic base
+ file scout boost
+ graph relation boost
+ route anchor / intent prior
- route-family conflict / decoy penalty
```

每个 boost/penalty 会记录 `reasons`，这是可解释性的核心。

### 第 5 阶段：能解释 Proof

Proof 回放检查：

- top hit 是否仍存在。
- evidence snippet 是否仍匹配。
- route literal 是否仍存在。
- supporting path 和 proof graph edge 是否仍可重建。
- decoy 是否仍被拒绝。

正确定位：工程可回放证据，不是数学形式化证明。

### 第 6 阶段：能做一个自己的改动

推荐：加一个新 query intent、一个通用 rerank feature、一个正例和一个反例测试，再跑 eval/ablation。只有亲手改过并解释副作用，面试时才不会停留在背稿。

### 第 7 阶段：10 分钟面试脚本

1. 30 秒：痛点与定位。
2. 1 分钟：四层架构。
3. 3 分钟：parser-index-retrieval-proof 数据流。
4. 2 分钟：本轮三个修复。
5. 1 分钟：测试和指标。
6. 1 分钟：局限。
7. 90 秒：Demo 与总结。

---

## 32. 新增刁难题与标准回答

### Q21：Top-1 100% 是不是过拟合？

可能。11 题只是 smoke suite。能做的是避免 case/path 硬编码、增加不同目录回归、使用冻结 challenge suite 和第三方仓库，并公开失败样本。不能把 100% 表述成通用领先。

### Q22：MCTS 在简单 eval 没增益，为什么保留？

简单问题可能已被词法和 intent prior 解决。保留的前提是跨文件长链和 hard-negative 场景有稳定增益；扩大 benchmark 后仍无增益就应降级或删除，不能因为算法名字高级而保留。

### Q23：为什么不用 BFS？

BFS 是重要 baseline。MCTS-style 的假设是在固定预算下把更多探索分配给高先验、高 reward 分支；是否值得要由相同预算下的消融实验决定。

### Q24：规则越来越多会不会失控？

会。控制方法是规则抽象到 intent/role/language，集中 feature 定义，每条规则绑定 benchmark 和 reason，做 ablation，并逐步转为可配置或学习权重。

### Q25：Proof 能彻底防幻觉吗？

不能。它约束 claim 绑定可回放证据，但 parser 漏检、召回错误、验证不完整仍会产生假安全感。需要 warnings、coverage、mutation 和 benchmark 共同约束。

### Q26：Allowlist 为什么不等于安全执行？

因为 pytest/npm test 本身会执行仓库代码。Allowlist 限制 Agent 能构造的命令形状；不可信代码隔离属于容器、OS 权限、网络和资源治理问题。

### Q27：没有 embedding 为什么叫 semantic？

它是当前仓库 token 空间上的 deterministic projection，只捕捉有限共现关系，不是预训练模型语义理解。必须带限定词介绍。

### Q28：如果正确文件根本没进索引怎么办？

重排无能为力，这是 recall ceiling。应监控 unsupported extension、parse failure、indexed coverage，增加纯文本 fallback 或更完整 parser，并把“未召回”和“排错”分开评测。

### Q29：如果让你删除一半功能，保留什么？

保留 parser/indexer、deterministic retrieval、evidence reasons、bundle/replay、核心 eval 和 CLI。复杂 frontier/court/attack 报告可以作为研究扩展，因为用户核心价值是可靠定位和可回放证据。

### Q30：如果面试官说“代码是 AI 写的，你做了什么”？

用工程判断回答：如何建立基线、识别环境假失败、读分数原因定位排序缺口、把路径特例泛化为 intent 规则、发现命令身份边界、设计反例测试、完成全量回归、诚实解释指标边界。能现场沿数据流读代码并回答反例，比争论代码来源更有说服力。

### 最终自检

面试前确保你能脱稿说出：

- 30 秒、2 分钟、5 分钟三套介绍。
- `Source -> Symbol -> Chunk -> Graph -> Hit -> Proof`。
- deterministic 与 LLM mode 的差异。
- Top-1、Top-3、MRR、distractor@1。
- 本轮三个修复的现象、根因、修复、测试。
- parser、benchmark、CLI monolith 三个局限。
- Allowlist 为什么不是 sandbox。

最后用一句话收尾：

> Repo Agent 是 AI coding 之前的证据层；它的核心不是回答得像人，而是让“为什么定位到这里”能够被检查、攻击、回放并进入工程流程。
