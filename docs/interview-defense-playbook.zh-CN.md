# Repo Agent 面试答辩作战手册

> 生成时间：2026-07-07
> 用途：配合 `docs/project-interview-reference.zh-CN.md` 使用。主文档负责“系统性理解项目”，本手册负责“面试现场连续追问时如何防守、展开和反击”。
> 核心原则：不要把 Repo Agent 说成万能 Coding Agent。它最强的定位是 AI 改代码前的 evidence layer：先定位、证明、复验、交接，再进入修改。

## 0. 一页总纲

面试官真正想确认的不是“你堆了多少功能”，而是：

1. 你是否能把项目的主线讲清楚。
2. 你是否知道每个模块为什么存在。
3. 你是否能解释复杂设计的取舍。
4. 你是否诚实承认边界和不足。
5. 你是否能用测试、报告和 artifact 证明项目不是口头 Demo。

Repo Agent 的主线可以压缩成一句话：

> Repo Agent 把代码仓库问答从“模型凭感觉猜文件”变成“本地索引、图检索、证据排序、证明回放和报告交接”的工程闭环。

如果面试官要求再短：

> 它是给 Coding Agent 用的证据层，先回答“该看哪里、为什么是那里、证据还是否有效”，再让人或下游 Agent 去改代码。

如果面试官要求系统设计版：

> 系统由 representation、retrieval、verification、product 四层组成。Representation 从仓库抽取文件、符号、路由和调用边；retrieval 用 query plan、lexical/semantic scoring、route anchor 和 bounded graph search 找证据；verification 把结果变成 proof bundle、strict replay、mutation 和 contract；product 层提供 CLI、Web Studio、HTML report、release pack 和工程模式。

## 1. 30 秒、2 分钟、5 分钟三套答法

### 1.1 30 秒版

Repo Agent 是一个本地代码仓库调查系统。很多 AI 编程工具的问题不是不会改代码，而是不知道该改哪里。Repo Agent 先解析仓库，抽取函数、路由、调用关系和文件事实，再根据问题检索证据、沿代码图扩展、生成可回放的 proof bundle，最后输出报告或交给下游 Coding Agent。它的重点不是替代 IDE，而是让改代码前的定位过程可解释、可验证、可复现。

### 1.2 2 分钟版

我把项目设计成一个 evidence-first pipeline。第一步是 parser/indexer，把 Python、JavaScript、TypeScript、HTML、CSS 文件转换成 `FileFact`、`Symbol`、`CodeChunk` 和 `GraphEdge`。第二步是 retrieval，根据用户问题做 query planning，再结合 lexical scoring、轻量 semantic projection、文件角色、符号类型和 route literal 做候选召回。第三步是 graph-aware rerank，从 seed hits 出发沿 route、handler、call、import 边做 bounded MCTS-style graph search，让执行路径上的 handler/writer 能超过仅仅文本相似的 admin、legacy、mock decoy。第四步是 verification，把结果包装成 Proof-Carrying Retrieval，包括 route anchor、supporting path、proof graph、decoy audit 和 diagnostics，并支持 replay、strict replay、mutation lab、contract、PR guard 和 scorecard。最后有 CLI、Web Studio 和报告系统，让结果可以被人审查，也可以交给下游 Agent。

### 1.3 5 分钟版

Repo Agent 的技术核心不是“调用一个模型回答仓库问题”，而是把仓库定位拆成可测试的工程阶段。

第一层是表示层。系统遍历 allowed roots 内的源码，跳过 `.git`、`.env`、reports、runs、cache 等生成或敏感目录，抽取文件类型、行数、symbols、routes、imports、calls。这样后续检索对象不是普通文本块，而是带结构元数据的代码证据单元。

第二层是检索层。用户问题会被转成 `QueryPlan`，包含 intent、target roles、target languages、route literals、重要 terms 和 top-k budget。检索不是单纯 grep，而是先做 file scouting，再对 chunks 做多信号打分：词项匹配、路径/文件名匹配、symbol kind、route anchor、local semantic projection、graph expansion 和 hard-negative rerank。

第三层是证明层。系统不满足于“top hit 是某个文件”，而是输出 proof object：为什么这个 hit 被选中，它是否在 route path 上，哪些 graph paths 支持它，哪些 decoy 被排除，proof graph 当前有哪些节点和边。后续可以把 JSON bundle 拿回当前仓库 replay，检查证据是否漂移。

第四层是产品层。CLI 能 ask/report/bundle/replay/mutate/scorecard/contract/PR guard；Web Studio 能浏览答案、证据、仓库图、工具输出和报告；engineering mode 能在 workspace copy 里做受控修改、验证和 review，再显式 apply。

我的设计取舍是：先保证 deterministic local retrieval 和 artifact 可复验，再把模型作为可选增强。这样即使没有 API key，系统也能跑完核心定位、评测和报告闭环。

## 2. 面试官追问地图

面试官通常会沿这几条线追问：

1. 产品价值：为什么需要它？谁会用？和 IDE Agent 有什么区别？
2. 检索算法：为什么比 grep/RAG 强？MCTS-style graph search 是否真的必要？
3. 代码结构：indexer、agent、runtime、server、tools 怎么分工？
4. 可靠性：proof、replay、mutation、scorecard 是否真的证明了什么？
5. 安全性：本地命令、文件访问、工程模式会不会危险？
6. 评测：指标规模多大？是否过拟合 bundled fixtures？
7. 工程质量：测试、CI、release pack、artifact integrity 怎么做？
8. 不足：parser 不完整、benchmark 小、`__main__.py` 大，怎么继续演进？

回答策略：

- 先承认问题的核心，再把话题拉回 evidence layer 主线。
- 对算法问题，讲“为什么这个信号解决了哪种失败模式”。
- 对指标问题，主动说明数据规模和边界，不夸大。
- 对安全问题，强调默认 workspace copy、allowlist、path validation 和 explicit apply。
- 对不足问题，给出有优先级的 roadmap，不要说“后面都能做”。

## 3. 高频质疑与防守答案

### 3.1 “这不就是 grep 加一点 UI 吗？”

不是。grep 的基本单位是行，Repo Agent 的基本单位是带结构的证据：文件事实、符号、路由、调用边和代码 chunk。grep 只能说某个字符串在哪些行出现；Repo Agent 会回答“这个 public route 最终对应哪个 handler/writer，为什么 admin/legacy/mock 不是答案，当前证据能不能 replay”。

可以继续展开：

- grep 没有 route anchor，所以容易被相似 endpoint 干扰。
- grep 没有 call/import graph，所以不能沿执行路径找 writer。
- grep 没有 proof bundle，所以结果不能作为可回放 artifact。
- grep 没有 decoy audit，所以不能解释“为什么不是另一个相似候选”。

### 3.2 “这不就是 RAG 吗？”

它借鉴了 RAG 的召回思想，但面向代码仓库做了结构化增强。普通 RAG 多数是 chunk embedding + top-k；Repo Agent 的 chunk 带有 symbol、route、handler、calls、imports、file role 等元数据，召回后还会做 graph search、route-anchor rerank、hard-negative audit 和 proof replay。

更准确地说，它是 codebase investigation engine，而不是文档问答 RAG。

### 3.3 “MCTS-style graph search 是不是过度设计？”

要承认它不是通用搜索银弹：

> 我没有把它包装成理论最优算法。这里的 MCTS-style graph search 是 bounded exploration：从 seed hits 出发，在 repository graph 上用 visit/reward/backprop 的思想探索有限深度路径。它解决的是“关键函数不一定包含 query 关键词，但它在 route/call path 上”的问题。

再举例：

> 对 `/api/chat` 问题，真正写 stream delta 的函数可能叫 `writeChatDelta`，它不一定和用户问题完全词面匹配。图扩展能从 route handler 走到 writer，把执行路径证据拉上来。

### 3.4 “Proof 这个词会不会太大？”

要主动降温：

> 这里的 proof 是工程意义上的 proof-carrying artifact，不是数学定理证明。它证明的是：在当前仓库索引和当前规则下，top hit、route anchor、supporting path、proof graph edge 和 decoy audit 是否自洽、可回放、可失效诊断。

然后强调价值：

> 它让一次仓库定位不再只是自然语言结论，而是可存档、可 replay、可 mutation test、可进入 CI gate 的证据合同。

### 3.5 “你的 benchmark 很小，指标有什么意义？”

最佳答案是诚实且进攻性适中：

> 我不会说这些指标证明它已经超过通用软件工程 benchmark。当前指标主要证明项目内部闭环是可复现的：eval、counterfactual hard negatives、portable adapter、proof replay、mutation、temporal repair、agent court 都能自动跑出结果。它们的价值在于验证机制完整性和失败模式覆盖，而不是宣称大规模泛化已经完成。

然后补路线：

> 下一步我会优先接真实第三方仓库 benchmark，并把现有 proof/replay/scorecard 机制作为评测 harness，而不是只看 Top-1。

### 3.6 “为什么不直接上 Tree-sitter？”

回答：

> 这是一个阶段性取舍。当前 parser 是 lightweight parser，优点是安装简单、跨平台、无额外 native 依赖，可以快速跑通 retrieval/proof/report 的端到端闭环。Tree-sitter 是明确的下一步，它能提升语法覆盖和符号精度，但我不想在项目早期把系统成功依赖在复杂 parser 集成上。现在的架构已经把 parser 层隔离出来，未来可以替换为 Tree-sitter provider。

### 3.7 “为什么不用真实 embedding / vector DB？”

回答：

> 基础路径刻意保持 model-optional 和 dependency-light。当前 semantic projection 是 deterministic baseline，可以在没有 API key、没有向量数据库的环境里复现。真实 embedding 和 vector DB 是可选增强，适合大仓库和跨语言语义召回，但它们不能替代结构化 graph、route anchor 和 proof replay。

### 3.8 “工程模式会不会自动乱改代码？”

回答：

> 默认不会直接改源仓库。工程模式优先在 `runs/<run_id>/workspace` 副本里执行，记录 timeline、tool calls、diff、changed files、verification 和 review。只有用户显式执行 apply 并确认，才会把变更应用回源仓库。命令执行还有 allowlist，文件访问有 path validation，protected/generated paths 会跳过。

### 3.9 “这个项目最能体现你工程能力的地方是什么？”

回答可以分三层：

1. 抽象能力：把仓库问答拆成 representation、retrieval、verification、product 四层。
2. 可靠性意识：不仅追求 top-k，还做 proof replay、mutation、scorecard、contract 和 PR guard。
3. 产品闭环：CLI、Web Studio、HTML report、bundle、release pack 和 engineering mode 不是孤立功能，而是围绕 evidence handoff 组织。

### 3.10 “如果要上线给团队用，你最先补什么？”

优先级答案：

1. 拆分 `__main__.py`，把 CLI command handlers 模块化。
2. 接 Tree-sitter，提高 parser 精度。
3. 做增量索引和持久化倒排索引，支撑大仓库。
4. 接真实外部 benchmark，避免只在 bundled fixtures 上自嗨。
5. 增强 Web Studio 的 proof graph 可视化和报告对比。
6. 把 PR guard 更自然地接入 GitHub Actions 和 SARIF code scanning。

## 4. 系统设计白板讲法

白板从左到右画五块：

```text
Repository
  -> Parser / Indexer
  -> Retrieval / Graph Search
  -> Proof / Replay
  -> Reports / Web / CLI
  -> Downstream Human or Coding Agent
```

每块只写关键词：

```text
Parser / Indexer:
  FileFact, Symbol, CodeChunk, GraphEdge

Retrieval:
  QueryPlan, file scout, lexical, semantic projection,
  route anchor, graph MCTS, rerank

Proof:
  top hit, route path, proof graph, decoy audit,
  replay, mutation, scorecard

Product:
  ask, report, bundle, Web Studio, engineering workspace
```

白板讲解顺序：

1. 先说输入输出：输入是 repo path + question，输出是 ranked evidence + answer + proof artifacts。
2. 再说为什么需要 parser：让系统知道代码结构，而不只是文本。
3. 再说为什么需要 graph：让系统能沿执行路径找证据。
4. 再说为什么需要 proof：让结果能被复验，而不是一次性回答。
5. 最后说 UI/CLI：让 artifact 能被人和其他 Agent 消费。

## 5. 代码走读脚本

如果面试官让你现场打开代码，建议顺序如下。

### 5.1 `repo_agent/models.py`

讲数据模型：

- `Symbol`：函数、类、路由、handler 等结构。
- `CodeChunk`：检索和排序的基本证据单元。
- `FileFact`：文件级事实。
- `GraphEdge`：route/call/import/handler 等关系。
- `RetrievalHit`：一次命中的证据、分数、原因和片段。
- `InvestigationBundle`：最终回答、trace、diagnostics、proof、hits。

重点话术：

> 我先把仓库转成稳定的数据结构，再做检索和证明。这样后续 UI、report、replay 都消费同一种 artifact。

### 5.2 `repo_agent/parsers.py`

讲 parser 取舍：

- 当前是 lightweight parser。
- 目标不是完整编译，而是抽取对定位有价值的符号和关系。
- Python 用 AST 思路更稳。
- JS/TS/HTML/CSS 是启发式抽取，能覆盖 demo 和常见结构。

重点话术：

> parser 的任务不是替代语言服务器，而是为 evidence retrieval 提供足够结构信号。

### 5.3 `repo_agent/indexer.py`

讲核心检索：

- `build_index` 负责构建仓库索引。
- query planning 负责从问题中识别 route、intent、target role。
- file scout 先缩小候选空间。
- lexical + semantic projection 做基础召回。
- route anchor 和 graph search 提升执行路径证据。
- rerank 处理 hard negatives。

重点话术：

> 这里是项目的心脏。很多功能看起来很花，但主线都是为了让 top hit 更接近真正执行路径，而不是相似文本。

### 5.4 `repo_agent/agent.py`

讲回答层：

- 把检索 hits 转成用户可读答案。
- 生成 diagnostics。
- 生成 proof-carrying retrieval。
- 生成 decoy audit。
- 可选模型路径只作为增强。

重点话术：

> Agent 层不应该藏掉证据，而是把“为什么这样回答”暴露出来。

### 5.5 `repo_agent/proof.py`

讲可靠性：

- replay 检查旧 evidence bundle 是否仍成立。
- strict replay 检查 graph edge 是否仍存在。
- drift diagnosis 分类证据失效原因。
- mutation lab 故意破坏 bundle，测试系统是否能发现。

重点话术：

> 这部分让仓库定位从一次性答案变成可维护 artifact。

### 5.6 `repo_agent/security.py`

讲安全边界：

- allowed roots。
- safe path resolution。
- generated/protected paths。
- command allowlist。
- shell=False。

重点话术：

> 这是本地 Agent 类项目必须认真做的部分。否则检索工具和工程工具都会变成风险面。

### 5.7 `repo_agent/engineering.py`

讲工程模式：

- workspace copy。
- structured timeline。
- verifier/reviewer gates。
- persisted run state。
- explicit apply。

重点话术：

> 我没有把自动修改当成默认动作，而是把它放在受控 workspace 和可审查 timeline 里。

## 6. 指标解释模板

### 6.1 被问“Top-1 为什么不是 100%”

回答：

> 因为代码定位有时存在层级差异。比如用户问 route 最终写响应的函数，系统可能把 route entry 放第一，把 deep writer 放第二或第三。Top-3 100% 说明召回候选有效，Top-1 不满说明 intent disambiguation 和 handler-vs-writer rerank 还有提升空间。这是我保留诊断和 ablation 的原因。

### 6.2 被问“100/100 会不会不可信”

回答：

> 100/100 是在特定 scorecard 维度上的门禁结果，不代表真实世界所有任务满分。比如 proof scorecard 衡量的是 strict replay、mutation detection、decoy audit coverage 等机制是否通过阈值。它证明 reliability pipeline 在当前 fixtures 上闭环，不证明通用泛化已经完成。

### 6.3 被问“为什么需要这么多报告”

回答：

> 因为不同报告回答不同问题。eval report 看定位准确率，counterfactual 看 hard negative，proof replay 看旧证据是否还有效，mutation report 看失效检测能力，scorecard 给 CI 一个硬门禁，release pack 给外部 reviewer 一个 artifact 入口。它们不是为了堆数量，而是覆盖从检索到证明到发布的不同风险面。

## 7. Demo 流程和救场话术

### 7.1 标准 8 分钟 Demo

1. 打开项目，说明定位：evidence-first repository investigation。
2. 跑 ask：

```powershell
python -m repo_agent ask --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?"
```

3. 展示 top hit、confidence、reasons、route anchor。
4. 生成 HTML report：

```powershell
python -m repo_agent report --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --output reports\demo-proof.html
```

5. 生成 bundle 并 replay：

```powershell
python -m repo_agent bundle --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --format json --output reports\demo-proof.bundle.json
python -m repo_agent replay-proof --bundle reports\demo-proof.bundle.json --strict --output reports\demo-replay.md
```

6. 展示 mutation 或 scorecard：

```powershell
python -m repo_agent proof-mutate --bundle reports\demo-proof.bundle.json --output reports\demo-mutation.md
python -m repo_agent proof-scorecard --bundle reports\demo-proof.bundle.json --output reports\demo-scorecard.md
```

7. 收尾：

> 这展示的是从定位、解释、证据 bundle、strict replay 到可靠性报告的闭环。

### 7.2 Demo 命令失败时

如果路径问题：

> 这是本地路径问题，不影响系统设计。我先切到 repo root 或使用绝对路径重跑。

如果报告已存在：

> 报告是可覆盖 artifact，我换一个 output path，避免和已有文件冲突。

如果模型未配置：

> 核心路径不依赖模型。没有 API key 时 deterministic retrieval、proof、replay 和 report 仍然可用；模型只是可选增强。

如果时间不够：

> 我直接展示已有 `reports/` artifacts，再解释对应生成命令和验证含义。

## 8. 反问面试官的问题

当面试官问完后，可以反问：

1. “你们团队现在的 Coding Agent 最大痛点是误改、上下文找错，还是评测不可复现？”
2. “如果把这个系统接到你们仓库，最有价值的是本地问答、PR guard，还是 proof/report handoff？”
3. “你们更关心真实仓库 benchmark，还是安全边界和审计 artifact？”

这些反问能把项目从“我做了一个工具”拉到“我理解团队软件工程流程”。

## 9. 不要说的话

不要说：

- “它能自动解决所有 bug。”
- “MCTS 一定比传统检索好。”
- “Proof 是数学意义上的形式化证明。”
- “当前 benchmark 已经证明真实世界泛化。”
- “parser 已经完整支持 JavaScript/TypeScript 所有语法。”
- “工程模式可以放心自动改生产仓库。”

应该说：

- “它定位的是改代码前的 evidence layer。”
- “MCTS-style graph search 是有限图扩展，用来补足文本匹配不足。”
- “Proof 是工程意义上的可回放证据合同。”
- “当前 benchmark 证明机制闭环，下一步要扩展到更多真实仓库。”
- “parser 当前是 lightweight，Tree-sitter 是明确演进方向。”
- “工程模式默认 workspace copy，必须显式 apply。”

## 10. 面试收尾模板

强收尾：

> Repo Agent 的价值不是又做了一个能聊天的编程助手，而是把代码定位这件事工程化：先解析仓库，建立结构化证据；再用检索和图搜索定位执行路径；再把答案变成 proof bundle、report、scorecard 和 CI artifact。它解决的是 Coding Agent 改代码前最容易出错的一步：找错上下文。

稳健收尾：

> 这个项目目前已经有完整本地闭环和自动化测试，但我不会夸大它的泛化能力。它最成熟的是 evidence artifact 和 proof/replay 机制；最需要继续提升的是 parser 精度、大仓库性能和真实外部 benchmark。这个边界我很清楚，也正是下一阶段优化方向。

一句话收尾：

> Repo Agent 让“这个答案为什么可信”从口头解释变成可以保存、回放、攻击、评分和进入 CI 的工程证据。
