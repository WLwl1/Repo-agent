# Repo Agent 保研面试科研答辩主文档

> 版本：2026-08-10
>
> 项目性质：个人独立完成的开源项目；面试包装方向：代码智能、软件工程智能体、信息检索与可信 AI 系统。
>
> 事实边界：本文只使用仓库中已有代码、报告和评测产物。CORE-Bench 部分是由 Level-2 数据整理出的 repository-streaming 衍生子集，不等同于官方完整榜单；SWE-bench Verified 已完成数据准备和划分，但完整检索矩阵尚未结束。

## 使用说明

这份文档按照“先讲清主线，再经得起深挖”的顺序编排。面试中不需要一次性把所有功能都讲出来。最优策略是先用 3 分钟讲研究故事，再根据教授的问题进入方法、实验或个人贡献。

如果你看纯文字容易走神，请先打开同目录的 `interview-visual-teaching.zh-CN.md`。其中用三张项目图、玩具代码、生活类比和 Aider、Zoekt、SWE-bench、Agentless、LocAgent、OpenHands 等开源案例解释核心技术；该图解册也被放在总文档长篇附录的第一位。

当前代码的图扩散实现是 bounded Personalized PageRank（PPR）。旧报告中出现的 `graph_mcts` 是历史序列化标签，用于兼容旧 artifact。讲解时必须以 PPR 为当前算法口径。

# 第一部分：科研故事线

## 1.1 一句话项目定位

Repo Agent 是一个面向代码智能的证据优先代码仓库定位系统。它在 Coding Agent 修改代码之前，先回答三个问题：应该看哪里、为什么看那里、这条证据在仓库变化后是否仍然成立。

## 1.2 研究背景与动机

大模型写代码的瓶颈并不总是生成能力，而是仓库级上下文定位。真实仓库通常具有以下特点：

- 同一个业务词可能出现在 public、admin、legacy、mock 和 test 多个版本中；
- 目标行为可能由 route、handler、helper、writer 多级调用共同完成；
- 函数名称和自然语言问题不一定共享词面；
- 仓库不断变化，昨天生成的定位结论可能在今天失效。

关键词搜索能够告诉我们某个字符串出现在哪里，却不能说明哪个节点真正处于目标执行路径。普通代码 RAG 可以召回相似片段，但通常缺少 route、call、import 等结构信息，也不会为答案保留可验证的证据链。

因此，本项目的动机不是再做一个聊天机器人，而是建立一个 Coding Agent 的 evidence layer：在修改代码之前，把仓库中的结构事实、检索排序和验证结果组织成可审查的中间产物。

## 1.3 核心科学问题

> 如何融合代码内容、标识符、路径和程序结构，在存在相似干扰项的代码仓库中准确定位目标代码，并输出可解释、可回放的证据链？

## 1.4 现有方法的不足

### 表示不足

将代码块拼成一个长文本后做 BM25 或 embedding 检索，会让长文件因为重复出现查询词而获得不合理优势，精确的函数名和路径信号也容易被淹没。

### 结构不足

文本相似不等于执行相关。一个名为 `writeAdminChatDelta` 的函数可能比 `writeChatDelta` 包含更多相同关键词，但它并不属于 public `/api/chat` 路径。

### 可靠性不足

许多系统只返回一个答案或 Top-k 片段。用户无法知道它为什么被选中，也无法在仓库更新后快速验证旧答案是否仍然有效。

## 1.5 方法概述

本项目将代码定位拆成四层：

1. **结构化表示**：抽取文件、symbol、route、handler、call、import；
2. **多视图检索**：分别建立 content、identifier、path、structure 四个 BM25 视图，并用 weighted RRF 融合；
3. **图扩散与重排**：以初始候选为种子，在仓库图上进行有界 PPR，结合 route anchor、动作词和 contrastive exclusion；
4. **证据验证**：生成 Proof-Carrying Retrieval、supporting path、proof graph、decoy audit，并支持 replay、strict replay 和 mutation lab。

## 1.6 主要贡献

### 贡献一：多视图结构化代码检索

将代码正文、函数/类标识符、文件路径和结构关系独立建模，再通过加权倒数排名融合，避免单一文本视图无法区分不同类型证据。

### 贡献二：路由锚定的执行路径定位

对查询中的 `/api/chat` 等精确路径进行 route anchoring，再沿 route、handler、call 和 import 边扩散，使没有直接词面匹配的深层函数也能获得执行路径证据。

### 贡献三：可回放的证据对象

系统不只返回 Top-k，还保存支持路径、检索原因、干扰项、图边和指纹。后续可以把 JSON bundle 放回仓库 replay，检查证据是否漂移。

## 1.7 实验结论

### 内置 portable suite

10 个案例上，升级前后结果为：

| 方法 | Top-1 | Top-3 | MRR |
|---|---:|---:|---:|
| 升级前 | 40.0% | 50.0% | 0.492 |
| 升级后 | 100.0% | 100.0% | 1.000 |
| 绝对变化 | +60.0 pp | +50.0 pp | +0.508 |

### Challenge suite

32 个案例上：Top-1 为 84.375%，Top-3 为 93.750%，MRR 为 0.880，Distractor@1 为 0%。仍有 5 个 Top-1 gap，没有隐藏失败案例。

### CORE-Bench 衍生冻结测试集

该实验包含 200 条查询、22 个仓库，repository-disjoint 划分为 train/dev/test=122/28/50，冻结测试集包含 50 条查询。

| 方法 | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@10 | Recall@100 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 14% | 20% | 24% | 0.196 | 0.116 | 0.315 |
| Content+Identifier RRF | 24% | 26% | 32% | 0.289 | 0.146 | 0.321 |
| Content+Structure RRF | 14% | 24% | 30% | 0.222 | 0.128 | 0.394 |
| Full Multiview RRF | 16% | 32% | 36% | 0.254 | 0.147 | 0.370 |

推荐的谨慎结论是：Full Multiview 在冻结测试集上相对 BM25 将 Hit@3 和 Hit@5 都提高了 12 个百分点，MRR 从 0.196 提高到 0.254，说明结构化表示改善了候选排序；但 Hit@1 只提高 2 个百分点，200 条查询上的 paired bootstrap 置信区间仍跨 0，因此不能宣称统计显著或全面超过外部系统。

## 1.8 三分钟口述稿

我做的项目叫 Repo Agent，是一个面向代码智能和智能软件工程的证据优先代码仓库定位系统。这个项目的出发点是，大模型能不能正确解决一个仓库级问题，很大程度上取决于前置上下文是否找对。如果一开始定位到了错误文件，或者定位到了一个名字相似但实际不参与执行的函数，后面的推理和代码修改都会建立在错误基础上。

现有关键词搜索主要依赖词面匹配，容易受到同名函数、测试代码、旧版本和管理接口的干扰。普通代码 RAG 虽然能够召回语义相似片段，但通常把代码当作扁平文本处理，没有充分利用路由、调用和导入关系，而且仓库变化后很难重新验证旧结论。因此我的核心问题是：如何融合代码的文本信息和程序结构，在存在相似干扰项的仓库中准确定位目标代码，并生成可解释、可回放的证据链。

我的系统首先解析仓库，抽取文件、函数、路由、handler、调用和导入关系；然后从代码内容、标识符、文件路径和结构关系四个视图建立 BM25 索引，用加权倒数排名融合初始候选；接着以候选为种子，在仓库图上进行有界 Personalized PageRank，并结合查询意图、动作词、route anchor 和 contrastive reranking，区分真正的执行路径与 admin、legacy、mock 等干扰项。最后系统输出 Proof-Carrying Retrieval 对象，记录 Top Hit、支持路径、证明图和干扰项排除原因，之后还可以 replay 检查证据是否仍然成立。

项目的贡献主要有三点：第一，多视图结构化代码检索；第二，路由锚定的执行路径图扩散；第三，可回放、可失效诊断的证据 artifact。在 10 个内置案例上，Top-1 从 40% 提升到 100%，MRR 从 0.492 提升到 1.000。在 CORE-Bench 衍生的冻结测试集上，Full Multiview 的 Hit@3 和 Hit@5 比单视图 BM25 都高 12 个百分点，MRR 从 0.196 提升到 0.254。这个外部结果说明结构化表示有改善排序的趋势，但我不会把它包装成已经超过所有外部系统，因为当前测试集规模和显著性仍然有限。SWE-bench Verified 我完成了数据准备和划分，但完整矩阵还在继续运行。

# 第二部分：方法论深拆

## 2.1 Pipeline 文字图

```text
Repository
 -> parser：AST / Tree-sitter / regex fallback
 -> indexer：FileFact / Symbol / CodeChunk / GraphEdge
 -> query planner：intent / action / route / role / language
 -> multi-view BM25：content / identifier / path / structure
 -> weighted RRF：融合独立排名
 -> bounded PPR：沿 route / call / import 图扩散
 -> rerank：role / language / action / route / contrastive rules
 -> evidence：answer / trace / diagnostics / proof / decoy audit
 -> replay：验证证据是否仍然成立
```

## 2.2 解析与索引

Python 使用 AST 抽取函数、类、decorator route 和调用；JavaScript/TypeScript 优先使用 Tree-sitter，超过 20 KiB 的文件使用 fallback；HTML/CSS 主要抽取页面、脚本、样式和 import 关系。

这里的设计假设是：对于仓库定位，完整语法树不是必要条件；只要能够稳定抽取足够的 symbol 和关系，就可以为召回和重排提供有效结构信号。

## 2.3 BM25 与四视图

BM25 参数为 (k_1=1.5,b=0.75)。代码正文、标识符、路径和结构分别建立索引，避免长函数体重复词项压制短而精确的函数名或路径。

RRF 公式为：

\[
S(d)=\sum_{v\in V}\frac{w_v}{K+rank_v(d)}
\]

当前使用 (K=30)，权重为 content=1.0、identifier=1.8、path=1.1、structure=1.25。RRF 的好处是不同视图不需要共享可比的绝对分数尺度。

## 2.4 Query Planning

QueryPlan 包含：

- mode；
- intent；
- focus terms；
- target roles；
- target languages；
- route literals；
- hop budget；
- target symbol kind。

例如“FastAPI 聊天接口入口在哪里”应识别为 API/route lookup，而“最终调用哪个处理函数”更接近 function/caller relation lookup。两者不能使用完全相同的排序偏好。

## 2.5 PPR 图扩散

当前实现从种子检索结果构造 teleport 分布，在有限邻域中对有向或反向关系进行加权扩散：

\[
r_{t+1}=(1-\alpha)p+\alpha P^Tr_t,\qquad \alpha=0.85
\]

实现细节：

1. 种子权重来自初始检索分数；
2. 邻域扩展最多使用排名靠前的 24 条边；
3. PPR 迭代最多 80 次；
4. (L_1) 变化小于 (10^{-7}) 时提前收敛；
5. 对概率乘以轻量 relevance factor，再作为 rerank boost；
6. route anchor 作为独立验证信号，不被普通词面分数完全替代。

## 2.6 Route Anchor 与 Contrastive Reranking

如果查询包含精确路径，系统先定位 route 节点，然后扩展到 handler、writer 和 caller。对“不是 admin/legacy/mock”的表述，系统会显式读取 contrastive exclusion；即使一个 decoy 词面相似，只要 route-family 不一致，也会受到惩罚。

当前重排中可解释的代表性规则包括：

| 证据 | 作用 |
|---|---|
| role-aligned | 文件角色与 query intent 一致时加分 |
| language-aligned | 目标语言匹配时加分 |
| route-reachable | 节点在 route 可达路径上时加分 |
| function target | 问函数时优先 function symbol |
| action match | stream/write/retrieve 等动作匹配时加分 |
| contrastive exclusion | admin、legacy、mock、fake 等候选降权 |
| test/doc downrank | 非目标查询时测试和文档候选降权 |

## 2.7 Proof、Replay 与 Mutation

Proof bundle 记录：

- 查询和 query plan；
- seed hits 与 final hits；
- top hit；
- route anchor；
- supporting paths；
- proof graph nodes/edges；
- decoy audit；
- score gap 和 warnings。

Strict replay 不仅检查节点是否还存在，还会检查 proof graph 中的 route/path edge 是否仍然对应当前 route、call 或 import graph。Mutation lab 会故意修改 top hit、route、path、edge 或 decoy entry，检测 verifier 能否发现问题。

## 2.8 理论假设与适用条件

### BM25 假设

词项出现频率和稀有程度能够近似反映相关性。对于命名规范混乱、语义隐含在控制流中的代码，这一假设会变弱。

### RRF 假设

各视图的相对排名比绝对分数更可靠。它不能自动判断某个视图是否整体错误，所以需要 ablation 和 dev 调参。

### PPR 假设

仓库图中的局部边能够近似执行或依赖关系。反射、动态注册和 parser 漏边会破坏这一假设。

### Route Anchor 假设

用户问题中包含可识别的路由 literal，且 parser 能抽取对应 route。没有 literal 或存在动态路由时，route prior 会变弱。

### Proof 假设

当前 proof 只验证证据结构的一致性，不验证完整程序语义；它属于工程可靠性 artifact，不是形式化验证。

## 2.9 与最相关论文方法对比

| 方法 | 重点 | Repo Agent 的差异 |
|---|---|---|
| GraphCodeBERT | data flow 感知的预训练模型 | Repo Agent 不训练模型，使用轻量显式结构和可解释图扩散 |
| RepoCoder | 仓库级检索增强代码补全 | Repo Agent 关注 issue/行为定位及 evidence handoff |
| Agentless | localization-repair-validation 三阶段 | Repo Agent 聚焦 localization 的可验证证据层 |
| LocAgent | 异构代码图与 LLM 多跳定位 | Repo Agent 基础路径可脱离 LLM，增加 route proof、replay 和 decoy audit |

# 第三部分：实验设计与分析

## 3.1 数据集选择逻辑

内置 portable suite 用于回归，challenge suite 用于复杂失败模式，counterfactual suite 用于 hard-negative，CORE 衍生集用于外部 repository-disjoint 检验，SWE-bench Verified 用于未来的真实 issue 文件定位。

不要把所有集合混为一个数字。内置100%主要证明系统闭环，CORE 衍生测试集主要检验结构化表示的外部趋势，SWE-bench 才更接近最终软件工程任务，但当前还没有完整结果。

## 3.2 Baseline 选择

### Single-view BM25

检验单一内容词法检索的强度，是最基本、最可复现的 baseline。

### Content+Identifier

检验函数名、类名和标题等精确符号信号。

### Content+Structure

检验 route、imports、calls 和 metadata 是否提升候选覆盖。

### Full Multiview

四个视图全部参与 weighted RRF，代表当前主要检索方法。

### No-graph / Hybrid / PPR

用于项目内的流程消融，分析图扩散和其他重排模块是否真的带来额外价值。

## 3.3 主结果与解释

内置 portable suite 的大幅提升说明升级后的表示、意图路由和重排规则能够修复原先的明显失败。challenge suite 的84.375% Top-1 说明泛化并不完美，但失败案例被保留下来，便于进一步分析。

CORE 冻结测试集上，Full Multiview 的 Hit@3、Hit@5 和 MRR 优于 BM25，但 Hit@1 仅小幅改善。这个现象可以拆成两层：结构信息提高了正确候选进入前几名的概率，但最终第一名仍受到标签粒度、跨仓库命名差异和多个同样相关文件的影响。

## 3.4 统计与方差

核心检索路径是确定性的，同一环境和输入下没有神经网络随机种子方差。外部结果采用 paired bootstrap 估计查询采样不确定性。当前200条查询的 MRR、nDCG@10 和 Recall@100 区间都跨0，因此只能报告效应量和趋势。

## 3.5 失败案例分类

### Top-3 recoverable

正确文件进入前三，但没有排到第一。这说明召回没有失败，主要问题在 rerank 或证据权重。

### Library boundary ambiguity

入口函数和真正实现函数分属不同文件或库边界，query 没有明确要求“先看入口”还是“看核心实现”。

### Streaming handler ambiguity

多个函数都包含 stream、turn、handler 等词，需要利用 call path 和动作意图进一步区分。

### Route anchor weakness

查询没有精确 route literal，或动态 route 没被 parser 捕获，导致 route prior 失效。

### Parser recall gap

正确 symbol 或调用边没有进入索引，后续任何重排都无法挽救。

## 3.6 需要补做的实验

1. 在固定版本的 CORE/SWE 数据上跑完 full hybrid；
2. 加入 dense-only、BM25+dense、Zoekt 等匹配 baseline；
3. 按 repository 做 macro average；
4. 报告 Hit@1/3/5、MRR、MAP、nDCG、latency、RSS 和 index size；
5. 做 bootstrap CI、paired significance 和多次运行稳定性；
6. 评测 proof confidence、abstention 和 risk-coverage；
7. 在同一模型、同一 token budget 下比较有无 evidence layer 的 patch success。

# 第四部分：理论基础与 Related Work

## 4.1 发展脉络

### 代码搜索阶段

CodeSearchNet 将自然语言代码搜索规模化，GraphCodeBERT 进一步证明 data flow 等结构信号具有价值。

### 仓库级上下文阶段

RepoCoder 将检索引入仓库级代码补全，说明跨文件上下文能够提升生成。

### 真实软件工程评测阶段

SWE-bench 将 GitHub issue 和真实 patch 纳入评测，推动模型从函数生成走向 repository-level repair。

### Agent 简化与定位阶段

Agentless 说明复杂自主 Agent 不是唯一选择，LocAgent 则强调异构代码图和多跳定位。

### 可信证据阶段

Repo Agent 进一步把定位结果视为可回放 artifact，加入 proof、decoy、mutation 和 replay。

## 4.2 关键论文与局限

| 论文 | 核心贡献 | 局限 |
|---|---|---|
| CodeSearchNet | 建立大规模多语言代码搜索数据 | 不聚焦仓库执行路径 |
| GraphCodeBERT | data flow 感知预训练 | 需要模型训练和较高部署成本 |
| RepoCoder | 迭代检索增强仓库级补全 | 目标是 completion，不是 proof localization |
| SWE-bench | 真实 GitHub issue 评测 | 主要看最终 patch，不强调中间证据 |
| Agentless | localization-repair-validation 阶段化 | 不以 replayable evidence 为核心 |
| CORE-Bench | 强调 Agent 结果可复现 | 原始任务不是代码定位 |
| LocAgent | 图引导的 LLM 代码定位 | 对模型和 Agent 搜索策略依赖较强 |

## 4.3 项目位置

本项目不声称提出全新的 IR 或图算法，而是把成熟组件组织成一个研究型系统问题：

> 结构化代码检索能否让代码定位更准确？证据是否能够被 replay？哪些失败来自召回，哪些失败来自排序？

## 4.4 前沿问题

- 动态代码图和运行时 trace 融合；
- 代码定位的 confidence calibration；
- Agent 的 reliable abstention；
- 证据层对最终 patch success 的因果影响；
- 大型 monorepo 的增量图索引；
- 多语言、多框架和生成式代码的 parser 鲁棒性；
- 面向 CI/PR 的 proof contract；
- 证据冲突时的多 Agent arbitration。

# 第五部分：教授拷打模拟

## A. 基础理解型

### A1. 输入输出是什么？

**教授想考察：** 是否真正理解系统边界。

**参考答案：** 输入是仓库路径和自然语言问题，输出是排序后的代码证据、片段、支持路径、诊断信息、proof bundle 和 decoy audit，不只是一个文件名。

**可能追问：** 没有 API key 能不能运行？

**踩坑提醒：** 不要说输出是绝对正确答案。

### A2. 为什么不直接 grep？

**教授想考察：** 是否理解项目价值。

**参考答案：** grep 以文本行为单位，不能表达 route 到 handler 再到 writer 的关系。我的系统把仓库变成带结构的证据图，还能解释为什么排除相似候选。

**可能追问：** 简单字符串查找时 grep 是否更快？

**踩坑提醒：** 不要贬低 grep。

### A3. 四个检索视图是什么？

**教授想考察：** 是否掌握核心实现。

**参考答案：** content、identifier、path、structure，分别对应代码正文、符号、路径角色和程序关系。

**可能追问：** 为什么不拼成一个文本？

**踩坑提醒：** 应解释独立视图有利于可解释消融。

### A4. BM25 怎么实现？

**教授想考察：** 是否只会背算法名。

**参考答案：** 使用词频、IDF 和长度归一化，参数是 (k_1=1.5,b=0.75)，每个视图独立排序后做 RRF。

**可能追问：** BM25 与 TF-IDF 的区别？

**踩坑提醒：** 要说词频饱和和长度归一化。

### A5. 当前 MCTS 还是 PPR？

**教授想考察：** 是否存在概念包装。

**参考答案：** 当前实现是 bounded PPR。`graph_mcts` 只是旧 artifact 的兼容标签，历史实现才有 pseudo-MCTS/greedy walk。

**可能追问：** 为什么不统一重命名？

**踩坑提醒：** 不能把 PPR 说成严格 MCTS。

### A6. Route anchor 做什么？

**教授想考察：** 是否理解执行路径。

**参考答案：** 识别 `/api/chat` 等 literal，找到对应 route 节点，再沿 route-handler-call 边给执行路径上的节点加分。

**可能追问：** 动态路由怎么办？

**踩坑提醒：** 不要声称覆盖所有动态框架。

### A7. Proof 是形式化证明吗？

**教授想考察：** 是否过度包装。

**参考答案：** 不是。它验证当前索引中证据节点、支持路径、图边和 decoy audit 是否自洽、可 replay。

**可能追问：** 能不能保证程序语义正确？

**踩坑提醒：** 不能保证。

### A8. Parser 支持什么？

**教授想考察：** 是否知道边界。

**参考答案：** Python、JavaScript、TypeScript、HTML、CSS；Python 走 AST，JS/TS 优先 Tree-sitter，大文件 fallback。

**可能追问：** 为什么不是完整编译器 parser？

**踩坑提醒：** 主动承认轻量 parser 的定位。

### A9. 训练 epoch 多长、什么 GPU？

**教授想考察：** 是否把检索系统冒充训练模型。

**参考答案：** 核心路径没有训练 epoch，也不依赖 GPU。BM25、RRF、PPR 是确定性 CPU 检索；embedding 只是可选后端。

**可能追问：** 为什么 pyproject 里有 embedding 接口？

**踩坑提醒：** 不要编造训练过程。

### A10. 如何复现？

**教授想考察：** 是否有实验闭环。

**参考答案：** 通过固定 suite、固定 split seed、冻结 test hash 和 JSON 结果文件复现，并记录 commit、环境、数据版本和运行时间。

**可能追问：** 完整测试是否全部通过？

**踩坑提醒：** 要区分 focused regression 与完整测试时间限制。

## B. 科研思维型

### B1. 为什么不用纯 embedding？

**教授想考察：** 方法选择。

**参考答案：** 代码定位里函数名、路径和 route 是精确证据。先采用本地确定性 BM25 保证可复现，embedding 只能作为额外召回，不能替代结构图。

**可能追问：** 逻辑相似但词不同怎么办？

**踩坑提醒：** 不要否定 embedding。

### B2. 与普通 RAG 的区别？

**教授想考察：** 研究定位。

**参考答案：** 代码块带有 symbol、route、calls、imports 和角色元数据，召回后还有图扩散、对比排除和 replay，因此是 codebase investigation 而非普通文档问答。

**可能追问：** 是否证明提升 patch success？

**踩坑提醒：** 当前不能声称已证明。

### B3. 创新点是什么？

**教授想考察：** 是否区分工程和算法贡献。

**参考答案：** 不是发明 BM25 或 PPR，而是把多视图表示、route path、hard-negative audit 和 replayable evidence 组织成可评测闭环。

**可能追问：** 这更像工程还是论文？

**踩坑提醒：** 不要把成熟组件说成全新算法。

### B4. 为什么不用 BFS？

**教授想考察：** 图搜索取舍。

**参考答案：** BFS 对高连接度仓库图会扩展太多无关节点，PPR 用边权和种子相关性做有界扩散，延迟更可控。

**可能追问：** 是否做过严格优越性证明？

**踩坑提醒：** 没有就明确说没有。

### B5. 数据扩大十倍是否可用？

**教授想考察：** 规模意识。

**参考答案：** 思路可用，但当前内存索引不能直接保证大型 monorepo 性能，需要增量索引、磁盘倒排、图分区和缓存。

**可能追问：** 先改什么？

**踩坑提醒：** 不要只回答加机器。

### B6. parser 漏边怎么办？

**教授想考察：** 对系统假设的理解。

**参考答案：** 图扩散会失去证据，所以保留词法和符号召回，并在 proof 中报告 coverage；未来需要 parser recall 和 abstention。

**可能追问：** 如何检测？

**踩坑提醒：** 不要声称不会漏边。

### B7. 内置100%，外部不高，怎么解释？

**教授想考察：** 过拟合意识。

**参考答案：** 内置集证明机制闭环，外部集检验跨仓库泛化。外部结果更难，不能用内置100%证明广泛有效。

**可能追问：** 内置集还有价值吗？

**踩坑提醒：** 不要称其为 SOTA。

### B8. 为什么这些指标？

**教授想考察：** 实验逻辑。

**参考答案：** Hit@1 对应直接答案，Hit@3/5 对应可检查候选，MRR 反映排序位置，Recall@100 分析召回是否覆盖。

**可能追问：** 最重要哪个？

**踩坑提醒：** 不要只挑最高项。

### B9. baseline 公平吗？

**教授想考察：** 对照设计。

**参考答案：** 同一文档、查询、qrels、top-k，只改变表示或融合方式；尚未和所有外部系统完成匹配预算比较。

**可能追问：** 为什么没跑 Zoekt 或 LocAgent？

**踩坑提醒：** 不要编造对比成绩。

### B10. 假设什么时候失效？

**教授想考察：** 理论边界。

**参考答案：** 反射、动态 import、宏、运行时注册、极度模糊的问题描述和 parser 漏边都会削弱方法。

**可能追问：** 要不要 abstain？

**踩坑提醒：** 承认 abstention 是下一步。

## C. 压力追问型

### C1. 结果是不是过拟合？

**教授想考察：** 诚实度。

**参考答案：** 内置100%不能排除过拟合；外部 repository-disjoint frozen test 结果较低，且 paired bootstrap 区间跨0，因此我只说 preliminary evidence。

**可能追问：** 如何继续排除？

**踩坑提醒：** 不能只说有测试集。

### C2. 外部结果不高为什么讲？

**教授想考察：** 负面结果解释。

**参考答案：** Hit@3/5 分别提升12个百分点，说明结构信号改善候选排序；Hit@1提升有限，说明精确定位仍难。

**可能追问：** 是否挑指标？

**踩坑提醒：** 主动报告 Hit@1 只有小幅变化。

### C3. 做显著性了吗？

**教授想考察：** 统计严谨性。

**参考答案：** 做了200条查询的 paired bootstrap，MRR、nDCG@10、Recall@100 区间都跨0，当前不能声称显著。

**可能追问：** 为什么样本小？

**踩坑提醒：** 不要把12个百分点等同显著。

### C4. no_graph 也100%，PPR有用吗？

**教授想考察：** 是否维护结论。

**参考答案：** 当前小样本不能证明 PPR 独立贡献，主要证据指向结构重排和对比排除；需要专门的 held-out graph cases。

**可能追问：** 新实验也没增益怎么办？

**踩坑提醒：** 不能强行维护。

### C5. Proof 是否过度命名？

**教授想考察：** 概念边界。

**参考答案：** 它是工程 proof，不是形式化语义证明。若面向更严格论文，可以称 evidence contract。

**可能追问：** 你会改名吗？

**踩坑提醒：** 承认命名可以讨论。

### C6. 最大局限是什么？

**教授想考察：** 自我批判。

**参考答案：** parser 不完整、外部矩阵未完、confidence 未充分校准、尚未证明下游 patch success 提升。

**可能追问：** 只能先改一件事？

**踩坑提醒：** 不要说没有局限。

### C7. 最大困难？

**教授想考察：** 独立解决问题。

**参考答案：** 一方面解决 Tree-sitter 大文件崩溃，另一方面把评测从内置样例扩展到 repository-disjoint frozen test，保证结果可解释。

**可能追问：** parser 重新设计？

**踩坑提醒：** 不要夸大普通 bug 修复。

### C8. AI 写的代码，你做了什么？

**教授想考察：** 个人贡献。

**参考答案：** 架构、数据模型、检索、PPR、Proof、评测协议和失败分析由我设计并实现；工具可以辅助编码，但问题定义、实验、验证和取舍是我的工作。

**可能追问：** 现场讲一个函数。

**踩坑提醒：** 不要声称逐行手写所有代码。

### C9. 重新做一次怎么改？

**教授想考察：** 路线图。

**参考答案：** 先完成外部定位 benchmark，再做 tuning log、parser recall、confidence calibration 和 downstream utility，减少启发式规则耦合。

**可能追问：** 删除哪些功能？

**踩坑提醒：** 不要继续无边界堆功能。

### C10. 未来三年怎么发展？

**教授想考察：** 科研潜力。

**参考答案：** 方向会从生成 patch 转向 evidence-aware Agent，融合静态图、运行时 trace、测试反馈和版本历史，研究定位、校准、abstention 和可验证修改。

**可能追问：** 你研究哪一块？

**踩坑提醒：** 不要只说继续做大模型。

# 第六部分：个人贡献与科研潜力

## 6.1 个人贡献回答

这是我独立完成的个人开源项目。我从问题定义开始，将项目定位为 Coding Agent 修改前的 evidence layer。具体工作包括：设计数据模型；实现 Python/JS/TS/HTML/CSS 解析；构建多视图 BM25 与 weighted RRF；实现 query planning、route anchor、动作重排和 bounded PPR；实现 Proof-Carrying Retrieval、strict replay、mutation lab、decoy audit；设计 portable、challenge、counterfactual 和 CORE 衍生评测；补充 CLI、Web Studio、测试、报告和文档。

我认为最核心的个人工作，是把“找到一个相似文件”转化为“返回带路径、原因、干扰项和 replay 能力的证据对象”，并围绕这个核心建立实验闭环。

## 6.2 最大困难回答

最大的困难不是把功能拼起来，而是让结果具备可信的实验边界。Tree-sitter 在大型模板型 JavaScript 文件上出现过进程级崩溃，我增加了文件大小保护、parser 复用、单次遍历和 fallback。与此同时，我发现内置案例的100%不能说明泛化，于是补充 repository-disjoint split、frozen test 和 paired bootstrap。这个过程让我认识到，研究系统的关键不仅是性能，还包括失败可见、结果可复现和结论不夸大。

## 6.3 项目不足回答

当前 parser 仍然是定位任务导向的轻量 parser；外部 benchmark 还没有全部完成；启发式重排的规则交互需要更系统的消融；confidence 和 abstention 还没有充分校准；evidence layer 对最终 patch success 的提升尚未做固定预算实验。

## 6.4 未来方向回答

我希望继续研究结构化代码检索和可信软件工程 Agent。当前系统主要依赖静态仓库结构，下一步可以融合运行时 trace、测试执行结果和 git 历史，研究更可靠的定位、证据校准和自动 abstention。目标不是让 Agent 更会猜，而是让它在证据不足时知道不应该修改代码。

## 6.5 选择课题组回答模板

我关注到贵组在【程序分析/代码智能/软件工程 Agent/信息检索/大模型可靠性】方面有持续工作。我的项目涉及结构化代码表示、代码图检索、证据验证和真实仓库评测，希望在贵组进一步把偏工程化的系统问题收敛成更严格的研究问题，例如代码定位置信度校准、静态图与运行时证据融合、面向软件工程 Agent 的可验证检索。贵组在【具体论文1】和【具体论文2】上的工作，正好可以帮助我补足当前项目在理论分析和大规模评测上的不足。

# 第七部分：面试前速记卡

## 7.1 项目一句话

Repo Agent 是一个通过多视图结构化检索、路由执行路径图和可回放证据，帮助 Coding Agent 在修改代码前判断“应该看哪里、为什么是那里、证据是否仍然有效”的系统。

## 7.2 三个关键点

1. 不是 grep：有 symbol、route、call、import 和 graph edge；
2. 不是普通 RAG：有 route anchor、contrastive decoy audit 和执行路径；
3. 不是一次性答案：有 proof、replay、mutation 和证据报告。

## 7.3 两个应对句

- 外部结果：CORE 衍生冻结测试集上 Hit@3 和 Hit@5 相对 BM25 各提升12个百分点，但当前不能称为显著结论。
- PPR 贡献：当前小样本消融还不能证明 PPR 独立增益，下一步会专门构造图路径 held-out cases。

## 7.4 三个雷区

- 不把 CORE 衍生子集说成官方榜单成绩；
- 不把未完成的 SWE-bench 说成完整结果；
- 不把 `graph_mcts` 历史标签说成当前严格 MCTS。

## 7.5 卡壳话术

这个问题我分实现层和证据层回答。实现层面当前系统是这样做的；证据层面现有实验只支持到这个范围，我不想把尚未验证的部分说得过满。如果继续深入，我会优先补充对应的消融、统计检验或外部复现实验。

# 第八部分：代码走读脚本

## 8.1 models.py

先展示 Symbol、CodeChunk、FileFact、GraphEdge、RetrievalHit 和 InvestigationBundle。重点说明：系统先把仓库转换为稳定的数据结构，再让检索、报告、Web、Proof 和 Replay 共享同一种 artifact。

## 8.2 parsers.py

说明 AST、Tree-sitter 和 fallback 的职责边界。面试中可以打开一个 Python route 和一个 JS route，展示如何抽取 route path、handler 和 calls。

## 8.3 retrieval.py

展示 BM25Index、MultiViewBM25Index 和 weighted_reciprocal_rank_fusion。重点解释每个 view 为什么独立，以及 RRF 为什么不直接加绝对分数。

## 8.4 indexer.py

建议按以下顺序讲：build_index、query planning、file scout、primary retrieval、PPR、route anchor、rerank、investigate。不要一开始从 CLI 入口开始，因为教授更关心研究主线。

## 8.5 proof.py

展示 proof bundle、replay、strict edge verification、drift diagnosis 和 mutation lab。要主动说明 proof 的工程语义边界。

## 8.6 security.py 与 engineering.py

说明 path validation、allowed roots、command allowlist、protected/generated paths、workspace copy、explicit apply 和 verification/review timeline。

# 第九部分：系统设计白板讲法

## 9.1 白板图

```text
Repository
 -> Representation
   files / symbols / routes / calls / imports
 -> Retrieval
   BM25 / multi-view RRF / intent / PPR / rerank
 -> Verification
   proof / replay / mutation / decoy audit
 -> Product
   CLI / Web Studio / report / bundle
 -> Human or Coding Agent
```

## 9.2 白板讲解顺序

1. 先说输入和输出；
2. 再说为什么需要 parser；
3. 再说为什么需要 graph；
4. 再说为什么需要 proof；
5. 最后说 CLI 和 Web 是 artifact 的消费端。

# 第十部分：评测与复现协议

## 10.1 结果口径表

| 结果 | 可以怎样说 | 不能怎样说 |
|---|---|---|
| portable 10 cases | 内置回归集上升级有效 | 已证明广泛泛化 |
| challenge 32 cases | 更复杂 bundled cases 上仍有较好定位 | 已超过外部系统 |
| CORE 200 queries | CORE 衍生子集上的外部初步结果 | 官方 CORE 榜单成绩 |
| SWE preparation | 完成数据、标签、划分和防泄漏准备 | 已完整跑完并取得最终成绩 |
| proof scorecard | counterfactual bundle 上验证链闭环 | 证明程序语义绝对正确 |

## 10.2 复现实验检查单

- 固定代码 commit；
- 固定数据 revision；
- 固定 repository-disjoint split；
- 固定 frozen test hash；
- 记录 baseline、参数、硬件和缓存状态；
- 记录每个 query 的 rank 和 top hit；
- 保存失败案例和 warnings；
- 运行 paired bootstrap；
- 避免用 test case 设计新规则；
- 对外报告时明确“内部回归”与“外部有效性”。

# 第十一部分：未来研究计划

## 11.1 近期

完成 SWE-bench Verified 的完整定位矩阵；增加 dense-only、BM25+dense、Zoekt 和 graph baseline；补充按仓库 macro average、置信区间和失败 taxonomy。

## 11.2 中期

做 parser recall benchmark、confidence calibration、abstention 和 risk-coverage；将 proof replay 与 PR guard、regression contract 接入 CI。

## 11.3 长期

融合静态图、运行时 trace、测试反馈和 git 历史，建立 evidence-aware software engineering agent，并评测在固定模型与 token budget 下是否真正提升 patch success。

# 附录：常用回答模板

## 被问到不知道的数字

这个数字我不想凭记忆报错。当前我能确认的是【已确认数字】；更细的【方差/硬件/运行时间】我会以实验 artifact 为准。

## 被指出结果不显著

是的，当前统计检验还不能支持显著性结论。我把这个结果定位为效应趋势和实验假设验证，而不是最终论文级结论。

## 被问到为什么做这么多工程功能

这些功能不是互相独立的堆叠：retrieval 负责找到候选，proof 负责解释，replay 负责验证，report 和 CLI 负责交接。它们共同服务于“代码定位证据可审查”这一主线。

## 被问到是否要继续做模型

我会把模型作为可替换的召回或重排组件，而不会让核心系统依赖某个 API。当前更重要的是建立可解释、可复现、可校准的结构化证据层。
