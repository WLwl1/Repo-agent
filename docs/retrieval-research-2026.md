# Repository Retrieval Research Baseline (2026-08-02)

## Research questions and claim boundary

This project has three primary research questions. Everything else is an
implementation or an appendix experiment and must not be presented as a
separate contribution.

| ID | Falsifiable question | Primary outcome | Required comparison |
| --- | --- | --- | --- |
| RQ1 | Does multi-view structural retrieval improve real-issue file/function localization? | Hit@1/3/5, MRR, per-repository macro average | BM25, multi-view without graph, full hybrid |
| RQ2 | Does replayable evidence reduce high-confidence errors and support reliable abstention? | ECE, Brier, risk-coverage, proof detection rate | ranking-only, replay, replay + abstention |
| RQ3 | Does the evidence layer improve repair success at the same model and token budget? | patch-resolved rate, test pass rate, tokens, cost, wall time | agent without evidence vs. with evidence |

The machine-readable protocol, repository-disjoint split algorithm, frozen-test
fingerprint, and leakage audit live in
[`repo_agent/research_protocol.py`](../repo_agent/research_protocol.py).
The current implementation does **not** claim to have answered RQ2 or RQ3;
those require calibration and downstream agent experiments.

## External-validity gate

The publishable external suite must satisfy all of the following before a
result is reported as a research result:

- at least 20 repositories and 200 issue/query cases;
- repository-disjoint train/dev/test partitions, generated with a recorded seed;
- a frozen test partition with a SHA-256 fingerprint;
- no tuning log may cite a test case or test split;
- the source dataset, repository commit, query version, environment, and all
  skipped records are recorded.

The importer enforces this gate when invoked with `--strict-research-audit`:

```powershell
repo-agent-import-benchmark `
  --input data/swebench-verified.jsonl `
  --repo-root data/repos `
  --dataset-name "SWE-bench Verified" `
  --output .tmp/external/swebench-verified-suite.json `
  --freeze-test `
  --audit-output .tmp/external/swebench-verified-audit.json `
  --strict-research-audit
```

The repository also ships deterministic preparation scripts for the two
external components. They verify the upstream dataset revision before writing
any manifest:

```powershell
$env:PYTHONPATH = "."
python scripts/prepare_core_bench_subset.py `
  --output-dir .tmp/core-bench-level2-20x200 `
  --manifest-output docs/core-bench-level2-external-manifest.json
python scripts/prepare_swebench_verified_subset.py `
  --output-dir .tmp/swebench-verified `
  --manifest-output docs/swebench-verified-external-manifest.json
```

For CORE-Bench, use the JSONL evaluator after exporting the official dataset:

```powershell
python -m repo_agent.core_bench `
  --corpus data/core-bench/corpus.jsonl `
  --queries data/core-bench/level2-queries.jsonl `
  --qrels data/core-bench/level2-qrels.jsonl `
  --methods bm25,multiview_rrf,bm25_rrf_multiview `
  --output .tmp/external/core-bench-level2.json
```

CORE-Bench is an appropriate external target because its paper defines an
issue-to-edit localization level over 632 repositories and 5,061 queries, in
addition to a broader-context level; it is materially different from this
repository's 10-case fixture suite. See the [official paper](https://arxiv.org/abs/2606.11864)
and [dataset page](https://huggingface.co/datasets/zhangfw123/CORE-Bench).

This note defines the research basis, implementation choices, and evidence required before Repo Agent can claim an improvement over existing repository-search systems. Frontend and serving work are intentionally out of scope.

## Why this project should exist

Agentic software engineering is not the same task as docstring-to-function search. An engineering agent must localize an issue in a concrete repository revision, distinguish near-duplicate in-repository distractors, recover supporting callers/callees and configuration, and hand the next stage evidence that can be verified against source. A high similarity score alone does not establish that the retrieved symbol is on the relevant execution path.

The strongest motivation is therefore not “another code search engine.” It is a reproducible evidence layer between an issue/task and an engineering agent:

1. retrieve the likely edit surface with high recall;
2. recover structural context under a bounded budget;
3. reject plausible but causally unrelated candidates;
4. expose enough provenance to replay the result after the repository changes.

## Research and project baseline

The following sources were inspected on 2026-08-02. Preprints are treated as design evidence, not as independently reproduced results.

| Work | Relevant finding | Repo Agent implication |
| --- | --- | --- |
| [GraphCodeBERT](https://arxiv.org/abs/2009.08366) | Data-flow structure improves code representation over token-only input. | Keep typed structure separate from raw content; do not flatten all signals into one bag of tokens. |
| [RepoCoder](https://arxiv.org/abs/2303.12570) | Iterative retrieval-generation improves repository-level completion by more than 10% over in-file baselines in its reported settings. | Retrieval should be iterative and repository-aware, but generation results are not localization evidence. |
| [SWE-bench](https://arxiv.org/abs/2310.06770) | Real issues require coordinated reasoning across files and executable environments. | Evaluation must ultimately use real repository revisions and issue-to-edit labels. |
| [SWE-agent](https://arxiv.org/abs/2405.15793) | Agent-computer interface design materially affects engineering performance. | Retrieval output must be usable as an agent tool, not only as an offline leaderboard score. |
| [Agentless](https://arxiv.org/abs/2407.01489) | A simple localization/repair/validation pipeline can outperform more complex agents at lower reported cost. | Deterministic localization is a serious baseline; complexity must earn measurable value. |
| [RANGER](https://arxiv.org/abs/2509.25257) | Repository graphs, entity lookup, natural-language retrieval, and graph exploration are complementary. | Route entity-like and natural-language queries differently, then combine lexical and graph evidence. |
| [ReflectCode / RepoAlign-Bench](https://arxiv.org/abs/2510.24749) | The paper reports +12.2% Top-5 accuracy and +7.1% recall for repository-aware change-request retrieval. | Add change-intent and adversarial verification benchmarks; do not rely on function-level search data. |
| [CORE-Bench](https://arxiv.org/abs/2606.11864) | Agentic retrieval needs code understanding, issue-to-edit localization, broader context, and in-repository distractors; the benchmark contains over 180K queries. | CORE-Bench or an auditable subset is the target external validity gate. |
| [Retrieval-Oriented Code Representations](https://arxiv.org/abs/2607.11046) | The paper reports role-aware summaries up to +40% Hit@5 over paths, multi-representation fusion up to +31.9%, and reranking up to +42%. | Treat representation as a first-class component and measure accuracy against representation footprint. |

Engineering baselines to compare or integrate include [Zoekt](https://github.com/sourcegraph/zoekt) for fast trigram search, [SCIP](https://github.com/sourcegraph/scip) for code-intelligence interchange, [Aider](https://github.com/Aider-AI/aider) for repository maps, [SWE-agent](https://github.com/princeton-nlp/SWE-agent), and [Agentless](https://github.com/OpenAutoCoder/Agentless). GitHub popularity is not used as an accuracy metric.

## Implemented retrieval architecture

### 1. Multi-view code representation

Each chunk is indexed through four independent BM25 views:

- `content`: implementation text;
- `identifier`: symbol, qualified name, handlers, and calls;
- `path`: repository path, language, and symbol kind;
- `structure`: route, imports, calls, references, inheritance, and file roles.

The rankings are combined with weighted reciprocal-rank fusion (RRF). Identifier and structure channels receive higher weights than raw content. This prevents a long file overview from winning merely because it repeats every query word. Dense embeddings, when configured, are fused as another ranking rather than added as an uncalibrated score.

### 2. Intent and entity routing

The deterministic query planner identifies general task surfaces such as API/flow, function action, test, configuration, frontend logic, and stylesheet lookup. Exact route literals and action verbs are preserved. This is deliberately a small, inspectable router rather than a benchmark-case lookup table.

### 3. Graph diffusion

The previous active implementation was a bounded greedy expansion while public artifacts called it MCTS. It is replaced internally by bounded Personalized PageRank (PPR):

- retrieval scores form the restart distribution;
- typed edge weights define normalized transitions;
- diffusion is restricted to a bounded seed neighborhood;
- convergence and damping are emitted in diagnostics;
- exact route anchors remain an independent verification signal.

The historical `graph_mcts` trace/ablation label remains temporarily for serialized-artifact compatibility. New diagnostics declare `strategy=personalized_pagerank`; future schema migration should rename the public variant.

### 4. Contrastive and action-aware reranking

Reranking uses general evidence features: requested symbol kind, primary action verb, call-site overlap, role/language alignment, exact route-family consistency, and explicit contrastive exclusions. Test and documentation surfaces are downranked unless requested. These features must be evaluated with held-out cases to detect rule overfitting.

### 5. Parser stability gate

The Python Tree-sitter 0.26 environment produced process-level access violations on template-heavy JavaScript. Traversal was changed to a single reusable node table. Until segmented parsing is implemented, JavaScript/TypeScript files above 20 KiB use the deterministic regex fallback. This is a known recall trade-off, but the indexer must not crash the benchmark process.

## Current measured result

Commands:

```powershell
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output .tmp/retrieval-upgrade/final-portable.json
python -m pytest tests/test_retrieval.py tests/test_parsers.py tests/test_ranking_regressions.py tests/test_indexing.py -q
```

Portable suite results on the same 10 bundled cases and `top_k=6`:

| Variant | Top-1 | Top-3 | MRR | Distractor@1 |
| --- | ---: | ---: | ---: | ---: |
| Pre-upgrade workspace baseline | 40.0% | 50.0% | 0.492 | 0.0% |
| Multi-view RRF + intent routing + bounded PPR | 100.0% | 100.0% | 1.000 | 0.0% |
| Absolute change | +60.0 pp | +50.0 pp | +0.508 | 0.0 pp |

The focused parser/retrieval/indexing regression set currently passes 27/27 tests. These numbers prove a regression improvement on the bundled suite only. They do **not** prove superiority over RANGER, ReflectCode, CORE-Bench systems, Zoekt, or commercial code search.

The separate 32-case challenge suite currently reports Top-1 `84.375%`, Top-3 `93.750%`, MRR `0.880`, and distractor@1 `0.0%`. Five Top-1 gaps remain and are listed in `reports/retrieval-upgrade-2026-08-02.md`; they are not hidden by the 10-case perfect score.

## Required evaluation before a strong claim

The next report must contain all of the following on versioned data:

1. **External localization:** CORE-Bench issue-to-edit subset and a SWE-bench Verified file/function localization subset.
2. **Baselines:** concatenated single-view BM25, multi-view without graph, dense-only, BM25+dense RRF, Zoekt, and full hybrid PPR; model reranking is reported separately.
3. **Metrics:** Hit@1/3/5, MRR, MAP/nDCG where graded labels exist, broader-context recall, distractor@1, abstention calibration, index/query latency, peak RSS, index size, and representation footprint.
4. **Ablations:** identifier, path, structure, intent router, route anchors, PPR, contrastive exclusion, and LLM reranker.
5. **Statistics:** per-repository macro average, bootstrap confidence intervals, paired significance tests, and failure categories.
6. **Leakage controls:** immutable train/dev/test repository split, no reason literals derived from held-out questions, and all tuning decisions logged before test evaluation.
7. **Downstream utility:** compare issue resolution or patch-validation success with and without Repo Agent evidence under the same model/token budget.

## Definition of an Agent-engineer-grade retrieval layer

The retrieval portion is ready for that label only when a clean clone can reproduce external benchmark reports; every result records commit, dataset version, environment, cost, latency, and failures; no bundled-only metric is described as state of the art; and downstream engineering success improves under a fixed budget. The project narrative is then closed: real issue localization is the motivation, multi-view structural retrieval and replayable evidence are the method, and external/downstream deltas are the result.
