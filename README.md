# Repo Agent

Evidence-first codebase investigation, proof-carrying retrieval, adversarial self-red-teaming, and benchmark-driven repair before an AI edits code.

[GitHub showcase](docs/github-showcase.md) | [Artifact map](docs/artifact-map.md) | [超级详细技术白皮书与项目拷打大全](docs/repo-agent-complete-deep-dive.zh-CN.md) | [Interview case study](docs/interview-case-study.md) | [零基础讲义](docs/repo-agent-course-notes.zh-CN.md) | [面试参考书](docs/project-interview-reference.zh-CN.md) | [答辩手册](docs/interview-defense-playbook.zh-CN.md) | [Launch checklist](docs/github-launch-checklist.md)

> 需要按当前工作区复核实现、实验和测试状态时，以 [超级详细技术白皮书与项目拷打大全](docs/repo-agent-complete-deep-dive.zh-CN.md) 为准；下方 Verified Release Snapshot 保留的是历史 release artifact 快照，不替代本次审计。

![Repo Agent Method](assets/repo-agent-paper-method-figure-v4.png)

## Verified Release Snapshot

- `178` tests passed in the latest release gate
- `80/80` release-pack artifacts verified by SHA-256 manifest
- `9/9` reviewer claims supported by the artifact evaluation card
- portable benchmark Top-1 / Top-3 / MRR: `100% / 100% / 1.000`
- intent-guard subset: `6/6` Top-1 with `0%` distractor@1; 32-case challenge suite: `93.75% / 100% / 0.964` Top-1 / Top-3 / MRR with `0%` distractor@1
- benchmark repair loop: `3` validated rules -> `3/3` implemented -> `5` ablation experiments

## 2-Minute Showcase

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_showcase.ps1
```

Open `reports/showcase/benchmark-repair-workbench.md` to see benchmark repair rules compiled into source-level ablation diffs and validation experiments. See [docs/artifact-map.md](docs/artifact-map.md) for the reviewer reading order.

For the full research artifact pack:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release_gate.ps1
```

<!-- Legacy localized README links are hidden until their encodings are repaired.

- zh_CN [简体中文](readme/README.zh_CN.md)
- ja [日本語](readme/README.ja.md)

-->

## Why Repo Agent

Most coding agents optimize for changing files. That is useful after you trust the context, but it is often too heavy, too expensive, and too opaque when the real first question is:

> Where should I look, and what is the evidence?

Repo Agent is a local codebase investigator. It focuses on proving the location of a bug, feature, route, handler, or execution path before asking a model to edit anything:

- parse real source code into symbols and file chunks
- build a lightweight repository graph from routes, handlers, decorators, imports, and calls
- retrieve grounded evidence with multi-view BM25 recall, optional dense embeddings, and graph expansion
- inspect the real workspace with directory listing, text search, file reads, and optional verification commands
- answer repository questions and bug-localization prompts with ranked evidence, line references, and trace output
- score each answer with evidence diagnostics: confidence, coverage, score gap, graph support, strengths, and warnings
- export a shareable HTML report for debugging, onboarding, and review
- export a portable evidence bundle for handoff to Codex, Aider, OpenHands, or another coding agent
- optionally hand the evidence to an OpenAI-compatible tool-calling loop when a model is configured

Repo Agent is not trying to be a clone of a full IDE coding agent. Its sharp edge is the step before coding: cheap local triage, inspectable evidence, and a report you can review with a human.

## Trust Signals

- Runs without an API key for deterministic, graph-aware retrieval
- Ships fixture repositories and CI-backed ranking metrics
- Ignores generated caches, logs, reports, and run workspaces during indexing
- Uses path validation for repository access and report/static-file serving
- Runs verification commands with `shell=False` and an allow-listed command shape
- Includes pytest coverage for parser, indexing, cache, security, and web-asset behavior

## Research Questions

Repo Agent now has one research program with three falsifiable questions:

1. **RQ1 — localization:** does multi-view structural retrieval improve file/function localization on real issues?
2. **RQ2 — calibrated evidence:** does replayable evidence reduce high-confidence errors and support reliable abstention?
3. **RQ3 — downstream utility:** does the evidence layer improve final repair success under the same model and token budget?

The primary external-validity gate requires at least 20 repositories and 200
cases, repository-disjoint train/dev/test splits, a SHA-256-frozen test set,
and a tuning log that contains no test-derived rules. The complete protocol is
in [docs/retrieval-research-2026.md](docs/retrieval-research-2026.md). Bundled
fixture scores are regression signals, not external research results.

## Appendix Capability Inventory

The following systems features support the three questions or remain appendix/future-work experiments. They are not independent research claims:

- retrieval pipeline: query planning -> file scouting -> code reading -> budgeted graph search -> reranking
- local retrieval: deterministic multi-view BM25 with weighted reciprocal-rank fusion; optional provider-backed dense embeddings add semantic recall without changing the ranking contract
- repository graph: route, handler, import, and call edges support execution-path localization
- bounded graph diffusion: typed repository-graph expansion with normalized Personalized PageRank boosts and traceable paths; the serialized `graph_mcts` label is retained for compatibility with older reports
- route-anchored graph priors: exact route literals in a query seed execution-path search, separating public endpoints from admin, legacy, mock, and documentation decoys
- proof-carrying retrieval: each investigation can attach a machine-readable proof object with route anchors, graph-search checks, top-hit validation, supporting paths, and warnings
- proof graph: the proof object also exports nodes and edges for route anchors, top hits, supporting execution paths, graph-MCTS visits, and decoy candidates
- contrastive decoy audit: hard-negative candidates are not just hidden by ranking; they are surfaced with rejection reasons, route-anchor status, score gap, and conflicting route-family roles
- proof replay: JSON evidence bundles can be replayed against the current repository index to verify that top hits, route anchors, supporting paths, proof graph endpoints, and decoy rejections still resolve
- strict proof replay: `replay-proof --strict` verifies proof graph route/path edges against current repository graph edges instead of only checking that nodes still exist
- proof drift diagnosis: failed replays are classified as top-hit drift, route-anchor drift, execution-path drift, stale proof-graph endpoints, or decoy-audit drift, with suggested follow-up actions
- proof mutation lab: JSON evidence bundles can be automatically mutated to test whether strict replay catches stale top hits, missing routes, broken paths, bad proof edges, and stale decoy audits
- adversarial proof attack benchmark: synthetic repository mutations inject admin-shadow writers, near-route preview writers, and documentation bait to red-team proof-carrying retrieval, then emit a causal defense audit showing which generated decoys were mitigated by route-family and off-route-writer signals
- adversarial mutation spec and leaderboard: proof attacks can be defined in a safe JSON DSL and ranked by attack pressure, defense score, residual risk, severity, tags, and weak-signal decoys
- adversarial defense triage: proof attack outputs are converted into prioritized P0/P1/P2 hardening actions for unmitigated decoys, weak mitigation signals, audit gaps, and high-pressure attacks
- counterexample-guided defense policy synthesis: triage actions are converted into declarative defense rules, then simulated against the open counterexamples to report coverage, residual actions, and expected mitigation-signal improvement
- adaptive proof attack curriculum: synthesized defense policies are treated as the next attack surface, generating second-order attack specs that probe whether the policy generalizes beyond the counterexamples it was trained on
- adaptive policy repair: uncovered second-order counterexamples are converted into patch rules, then re-evaluated to prove whether repaired policy coverage closes the adaptive gap
- proof attack minimax certificate: the baseline attack, synthesized policy, adaptive attack, and repair artifacts are hashed into a claim ledger with an accepted/rejected verdict for the full reliability loop
- adversarial proof attack scorecard: self-red-team metrics become a thresholded CI gate with hard-fail thresholds, GitHub annotations, and SARIF output
- proof attack CEGAR loop: generated counterexamples, attack-pressure ranking, defense triage, scorecard gates, SARIF, and next hardening actions are composed into one counterexample-guided reliability report
- proof reliability scorecard: strict replay, mutation detection, proof status, verified proof edges, and decoy audit coverage are summarized into a GitHub-friendly reliability grade
- proof-guided impact analysis: evidence bundles can be turned into upstream/downstream change-impact reports with exposed routes, impacted files, risk items, and verification plans
- proof regression contracts: proved evidence and impact analysis can be frozen into machine-readable PR contracts and re-verified after code changes
- proof-backed PR guard: changed files can be checked against protected proof surfaces to decide whether replay, contract verification, and route checks are required, with GitHub annotations and SARIF output
- temporal proof regression, graph delta, repair inference, and migration planning: proof contracts can be replayed across git history from archived commit snapshots to identify the first commit that broke an evidence chain, explain which proof-path edges disappeared or relinked, rank likely successor symbols from route reachability/proof-path continuity/code similarity, and emit reviewable JSON Patch operations for contract migration
- temporal repair benchmark: synthetic git histories evaluate successor@1, negative-control abstention, false-repair rate, causal graph-delta detection, and migration-plan readiness across same-file renames, cross-file writer moves, and no-successor deletions
- temporal repair scorecard: benchmark metrics are turned into a thresholded release/CI quality gate with fail-on-threshold behavior, GitHub annotations, and SARIF output for Code Scanning
- multi-agent evidence court: retrieval, graph, proof-verifier, mutation-skeptic, red-team, and temporal agents publish hashed claims into a ledger, then an arbiter accepts or contests the answer from discharged challenges rather than chat-style consensus
- agent reliability frontier: release-pack evidence is projected into reliability, robustness, evidence, adaptivity, governance, and efficiency dimensions, then Pareto-ranked instead of collapsed into one success metric
- agent frontier causal ablation: proof, attack, temporal, court, and integrity evidence families are counterfactually masked to attribute which artifacts actually support the reliability frontier
- evidence interaction matrix: pairwise evidence-family counterfactuals detect nonlinear reliability collapses that single-family ablations cannot see
- frontier stability lab: deterministic bootstrap perturbations estimate score confidence intervals, Pareto membership survival, and top-interaction stability under metric uncertainty
- portable benchmark adapter: third-party localization suites can be expressed as repo/question/expected-symbol JSON and scored with per-repo/per-tag Top-1, Top-3, MRR, distractor@1, and generalization-gap reports
- benchmark generalization diagnostics: portable benchmark outputs are converted into case-level taxonomies, group-level action items, and counterfactual repair ceilings for weak Top-1 behavior
- benchmark repair card: diagnostics-driven ranking guards are verified by explicit top-hit reasons, proving streaming handler and retrieval-library ambiguity fixes closed the portable suite
- benchmark intent guards: authorization middleware, synchronous JSON handlers, clear-state helpers, package-data config files, verification-policy files, and run-apply actions are covered by a focused challenge suite with explicit rerank reason literals
- benchmark repair synthesizer: counterexample traces are converted into auditable retrieval-repair rule DSLs with affected cases, validated cases, risk cases, projected Top-1, and evidence hashes
- benchmark repair implementation verification: synthesized rules are checked against concrete reranker helpers, source anchors, and emitted reason literals before they count as implemented
- benchmark repair compiler: validated or proposed repair rules are compiled into source-level intervention IR, regression locks, ablation toggles, validation commands, and rollback conditions
- benchmark repair workbench: compiled interventions become reviewable patch candidates, single-rule ablation diffs, experiment hypotheses, and validation matrices
- artifact evaluation card: every major project claim is tied to required artifacts, validation commands, falsifiers, limitations, confidence, and a reviewer protocol
- artifact integrity manifest: release packs include SHA-256 hashes and byte sizes for every generated artifact, plus a verifier that detects missing or tampered reports
- observability: trace output, ranked evidence, snippets, graph edges, confidence diagnostics, warnings, and HTML reports
- explainability artifacts: answers, HTML reports, API responses, and evidence bundles include Graph Search Audit, Proof-Carrying Retrieval, Proof Graph, Contrastive Decoy Audit, and Proof Replay data for inspected chunks, visits, rewards, boosts, paths, validation checks, and decoy comparisons
- multi-agent engineering gates: Coordinator, Planner, Investigator, Patch, Verifier, and Reviewer events are persisted as a structured run timeline
- verifier intelligence: changed-file runs can auto-select an allow-listed verification command, execute it, and classify failures from stdout/stderr
- reviewer intelligence: each run gets a risk score, file-level risk reasons, missing-test warnings, and suggested follow-up actions
- safety: path validation, ignored generated paths, protected files, allow-listed verification commands, workspace-first edits, and explicit apply-back
- evaluation: bundled cases report Top-1, Top-3, MRR, average confidence, per-case ranks, retrieval ablations, counterfactual hard-negative results, adversarial proof-attack resistance, and mitigation-signal coverage

For the interview narrative, see [docs/interview-case-study.md](docs/interview-case-study.md).

## Positioning

Repo Agent is the evidence layer before code changes. It pairs well with tools such as Aider, OpenHands, SWE-agent, or Codex: use Repo Agent to find the files, handlers, routes, traces, and confidence signals; then hand the evidence to a coding agent when you actually want edits.

It should be judged on localization quality, traceability, and reviewability rather than on how aggressively it changes files. See [docs/comparison.md](docs/comparison.md) for a more explicit comparison.

## Key Capabilities

- Evidence-first repository QA and bug triage
- Ranked file, symbol, and line-level evidence
- Evidence confidence diagnostics that make retrieval quality and risk visible
- Express/FastAPI/Flask-style route and handler linking
- Multi-step repository investigation: broad lexical/embedding recall -> symbol graph expansion -> model-directed search -> verification
- Trace output that shows how the result was found
- Graph Search Audit cards that expose bounded graph expansion and path evidence
- Proof-Carrying Retrieval panels that validate whether the top answer is anchored to the route or execution path asked about
- Proof Graph export for downstream agents and static reports, including route anchors, top-hit evidence, route-path edges, and decoy candidates
- Contrastive Decoy Audit that explains why admin, legacy, fake, mock, or notes-like candidates were rejected
- Proof Replay command that reloads a JSON evidence bundle and verifies whether its proof still holds on the current repository
- Strict proof-edge verification for route/path proof graph edges against current route/call/import graph edges
- Proof Drift Diagnosis that explains why a replay failed and what to regenerate or inspect next
- Proof Mutation Lab that stress-tests proof replay by injecting controlled evidence corruptions and reporting detection rate
- Adversarial Proof Attack Benchmark that mutates a demo repository with generated decoy routes/writers and measures whether graph-MCTS plus proof-carrying retrieval still anchors the exact public route path, with a causal defense audit for each generated decoy
- Adversarial Mutation Spec and Leaderboard that make red-team cases extensible through JSON templates and rank the hardest attacks instead of keeping the benchmark as fixed code
- Adversarial Defense Triage that turns generated counterexamples into CEGAR-style hardening actions with priorities, evidence hashes, and suggested guards
- Adversarial Proof Attack Scorecard that turns generated attack resistance, decoy mitigation, mitigation-signal coverage, and proof-proved rate into a CI quality gate
- Proof Attack Minimax Certificate that hashes the baseline attack, synthesized policy, adaptive attack, and repair inputs into a machine-checkable claim ledger
- Proof Reliability Scorecard that rolls proof status, strict replay, proof-edge verification, decoy audit coverage, and mutation detection into one report
- Proof-Guided Impact Analysis that explains which callers, callees, routes, files, and checks are affected if a proved evidence target changes
- Proof Regression Contracts that convert a proof bundle into executable invariants for future PRs
- Proof-Backed PR Guard that detects when changed files touch protected proof surfaces and emits required verification gates, GitHub annotations, and SARIF for Code Scanning
- Temporal Proof Regression, Proof Graph Delta, Repair Inference, and Contract Migration Planning that replay the proof contract across git commits, use exported snapshots instead of mutating the active worktree, report the first failing commit, explain the causal proof-path diff, rank likely successor symbols, and emit reviewable JSON Patch operations for proof regeneration
- Temporal Repair Benchmark that quantifies successor inference and migration planning across multiple synthetic proof-breaking histories
- Temporal Repair Scorecard that converts benchmark metrics into a release-ready CI gate with hard-fail thresholds, GitHub annotations, and SARIF output
- Multi-Agent Evidence Court that converts proof replay, mutation testing, adversarial scorecards, and temporal repair scorecards into a claim ledger, challenge ledger, and arbiter verdict
- Agent Reliability Frontier that turns the release pack into a multi-objective Pareto analysis across reliability, robustness, evidence, adaptivity, governance, and efficiency
- Agent Frontier Causal Ablation that masks evidence families and recomputes the frontier to expose causal score drops, Pareto membership changes, and protected evidence drivers
- Evidence Interaction Matrix that masks pairs of evidence families to measure observed drop, expected additive drop, synergy, and Pareto membership loss
- Frontier Stability Lab that bootstraps metric perturbations to report score confidence intervals, frontier survival probabilities, and whether the top nonlinear evidence dependency is stable or contested
- Portable Benchmark Adapter that lets reviewers plug in external cross-repository suites without changing Python code, then reports per-repo/per-tag generalization gaps and distractor@1
- Benchmark Generalization Diagnostics that explains weak cases with labels such as `top3_recoverable`, `library_boundary_ambiguity`, `streaming_handler_ambiguity`, and `route_anchor_weakness`, then reports projected Top-1 repair ceilings
- Benchmark Repair Card that audits the repaired ranking reasons and proves the portable suite reaches Top-1 100% without rank-1 distractors
- Benchmark Repair Synthesizer that turns weak or repaired benchmark traces into concrete rule candidates such as `prefer_retrieval_library_boundary` and `promote_streaming_handler_intent`, including whether each rule is proposed, validated, or dormant
- Benchmark Repair Implementation Verification that maps validated rules back to `repo_agent/indexer.py` anchors and reason literals, preventing rule reports from drifting away from real code
- Benchmark Repair Compiler that turns repair-rule DSLs into deterministic source-level intervention plans, regression locks, ablation toggles, validation commands, and rollback conditions
- Benchmark Repair Workbench that generates reviewable candidate diffs, counterfactual ablation patches, experiment hypotheses, and validation matrices from compiled interventions
- Artifact Evaluation Card that turns project claims into reviewer-facing evidence cards with required artifacts, validation commands, falsifiers, limitations, confidence scores, and a reproducibility protocol
- Artifact Integrity Manifest that hashes every release-pack artifact and can be re-verified before publishing or during a demo
- Counterfactual hard-negative benchmark with admin/legacy/mock decoys and `distractor@1` tracking
- Shareable HTML reports for review and debugging
- Portable Markdown/JSON evidence bundles for downstream coding agents
- Model-optional workflow: lexical/structural retrieval works without an API key; configured providers add dense embedding recall
- Real agent mode with model-selected tools: `repo_brief`, `find_relevant_code`, `list_directory`, `search_text`, `search_symbols`, `find_symbol_relations`, `read_file`, `startup_hints`, and `verify_project`
- Local web studio for interactive analysis
- Workspace tool panel for directory listing, file reads, text search, startup hints, and allow-listed verification commands
- Experimental multi-agent engineering mode with inspect -> edit -> verify -> review -> finish loops
- Workspace sandbox mode that edits `runs/<run_id>/workspace` instead of the source repository
- Persistent run records under `runs/<run_id>/run.json`, including tool calls, changed files, verification output, reviewer risk, timeline events, and diff snapshots
- Built-in example repositories for reproducible demos
- CI-backed evals with Top-1, Top-3, MRR, lexical/semantic/no-graph/hybrid/graph-MCTS-compatible ablations, and hard-negative distractor metrics
- Safety controls for path validation, input limits, and index limits
- Centralized verification command policy that blocks arbitrary `python -c`, `node -e`, package-install, and traversal-shaped commands
- Audit logs for indexing, ask, map, report, and request failures

## When To Use It

Use Repo Agent when you need to:

- onboard into an unfamiliar repository
- find the route, handler, or execution path behind a behavior
- localize a likely bug before opening an editor
- produce a reviewable evidence trail for a teammate
- run cheap deterministic codebase search before spending model tokens

Use a full coding agent after you have enough evidence and want autonomous edits.

## Architecture

![Repo Agent Architecture](assets/architecture-diagram.png)

## Demo Questions

Try Repo Agent on the included fixture repos:

- `Where is the chat endpoint implemented?`
- `What should I inspect first for a streaming bug?`
- `Where does the RAG upload flow enter the codebase?`
- `What is the main execution path for this service?`
- `Can you quickly verify whether this project still runs?`

## Quick Start

### Install

```powershell
cd repo-agent
python -m pip install -e ".[dev]"
```

Once published, the target install shape is:

```powershell
pipx install repo-agent
```

### Run the built-in eval

```powershell
python -m repo_agent eval --output reports/eval-report.md
```

### Run the retrieval ablation

```powershell
python -m repo_agent ablate --output reports/ablation-report.md
```

The ablation compares lexical, semantic-only, no-graph, fixed graph expansion, and the `graph_mcts` compatibility label (currently backed by bounded Personalized PageRank) retrieval.

### Run the counterfactual hard-negative benchmark

```powershell
python -m repo_agent counterfactual --output reports/counterfactual-report.md
```

The counterfactual benchmark uses deliberately confusing public/admin/legacy/mock decoys and reports `distractor@1`.

### Run a portable cross-repository benchmark

```powershell
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.md
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json
python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-adapter.json --output reports/benchmark-diagnostics.md
python -m repo_agent benchmark-repair-card --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-card.md
python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.json
python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.md
python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.json
python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.json
python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.md
python -m repo_agent benchmark-repair-workbench --compiler reports/benchmark-repair-compiler.json --output reports/benchmark-repair-workbench.md
python -m repo_agent benchmark-adapter --suite my-suite.json --emit-template
```

The benchmark adapter is the external-validity layer. A suite is plain JSON with `repo`, `question`, `expected_path`, `expected_symbol_contains`, optional distractors, and tags. The report scores Top-1, Top-3, MRR, distractor@1, per-repository groups, per-tag groups, and explicit generalization gaps, so a reviewer can add third-party cases without editing Repo Agent internals. The diagnostics pass then explains weak Top-1 behavior with a taxonomy, group action items, and counterfactual repair ceilings. The repair card closes the loop by auditing explicit top-hit reasons such as `streaming handler disambiguation`, `retrieval helper target`, and `library boundary prior`, proving that targeted evidence guards moved the portable suite to Top-1 100%. The repair synthesizer adds the self-improvement layer: it reads the same benchmark trace, proposes or validates declarative retrieval-repair rules, estimates projected Top-1/MRR, and records affected, validated, and risk cases before any rule is trusted. The implementation verifier then checks those validated rules against source anchors and emitted reason literals, so a rule is not considered implemented merely because a report says it exists. The compiler turns the same rule DSL into source-level intervention IR: patch-required rules become target functions, guard conditions, score effects, validation commands, and rollback conditions; already implemented rules become regression locks with ablation toggles. The workbench then turns compiled interventions into reviewable patch candidates and one-rule ablation diffs so a reviewer can test whether each repair reason actually carries benchmark value.

### Run the adversarial proof attack benchmark

```powershell
python -m repo_agent proof-attack --spec repo_agent/proof_attack_specs.json --output-dir reports/proof-attack-benchmark --output reports/proof-attack-benchmark.json
python -m repo_agent proof-attack --spec repo_agent/proof_attack_specs.json --output-dir reports/proof-attack-benchmark --output reports/proof-attack-benchmark.md
python -m repo_agent proof-attack-leaderboard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-leaderboard.md
python -m repo_agent proof-attack-triage --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-triage.md
python -m repo_agent proof-attack-policy --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-policy.json
python -m repo_agent proof-attack-policy --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-policy.md
python -m repo_agent proof-attack-adaptive --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --output-dir reports/proof-attack-adaptive --output reports/proof-attack-adaptive.json
python -m repo_agent proof-attack-adaptive --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --output-dir reports/proof-attack-adaptive --output reports/proof-attack-adaptive.md
python -m repo_agent proof-attack-repair --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --output reports/proof-attack-repair.md
python -m repo_agent proof-attack-certificate --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --repair reports/proof-attack-repair.json --output reports/proof-attack-certificate.md
```

The attack benchmark copies the counterfactual demo repo, reads a safe JSON mutation spec, injects generated decoy code such as admin-shadow writers, near-route preview writers, and documentation bait, then scores whether route-family-aware graph search and Proof-Carrying Retrieval still return the exact public `/api/chat` writer with a proved route path. The Causal Defense Audit section records each generated decoy's rank, rerank reasons, and mitigation signals such as `route-family conflict` and `off-route writer decoy`. The leaderboard ranks cases by attack pressure, defense score, residual risk, severity, tags, and weak-signal decoys. The triage report turns the same counterexamples into prioritized defense actions, so passing attacks can still reveal weak or missing mitigation signals. The policy synthesizer turns those actions into declarative defense rules, then simulates whether the rules cover all open counterexamples and improve mitigation-signal coverage. The adaptive curriculum then treats that policy as the next attack surface and generates second-order attack specs to find policy generalization gaps. The repair step synthesizes patch rules from those adaptive gaps and re-runs policy coverage to prove whether the minimax loop closes. The minimax certificate hashes every input artifact and records the claims that make the loop acceptable or rejected.

Grade the generated attacks as a self-red-team CI gate:

```powershell
python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.json --sarif-output reports/proof-attack-scorecard.sarif --github-annotations --fail-on-fail
python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.md
```

The scorecard checks attack resistance, generated-decoy mitigation, mitigation-signal coverage, and proof-proved rate. Failed red-team thresholds can block CI and appear in GitHub Actions logs or Code Scanning.

Run the whole counterexample-guided reliability loop in one command:

```powershell
python -m repo_agent proof-attack-cegar --spec repo_agent/proof_attack_specs.json --output-dir reports/proof-attack-cegar --output reports/proof-attack-cegar.md
```

The CEGAR loop turns generated attacks into a single convergence report: it records the hardest counterexample, scorecard grade, residual risk, P0/P1/P2 refinement load, synthesized policy coverage, supporting artifacts, and the next hardening actions needed before the loop can be considered converged.

### Generate a proof-carrying report

```powershell
python -m repo_agent report --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --output reports/proof-carrying-counterfactual.html
```

The report includes a Proof-Carrying Retrieval panel, Proof Graph, and Contrastive Decoy Audit. The answer is marked as `proved` only when graph search ran, a route anchor was found, and the top hit is on the route-anchored execution path; admin, legacy, mock, and notes-like candidates can still appear with explicit rejection reasons.

### Replay a proof bundle

```powershell
python -m repo_agent bundle --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --format json --output reports/proof-carrying-counterfactual.bundle.json
python -m repo_agent replay-proof --bundle reports/proof-carrying-counterfactual.bundle.json --strict --output reports/proof-replay-report.md
```

Proof replay reloads the JSON evidence bundle, rebuilds the current repository index, and verifies that the top hit, route literals, supporting paths, proof graph edges, and decoy audit entries still resolve. With `--strict`, route/path proof graph edges must also be backed by current route, call, or import graph edges. If replay fails, Proof Drift Diagnosis classifies the failure and suggests whether to rerun localization, inspect changed routes, rebuild the execution path, regenerate the proof graph, or rerun the decoy audit.

### Run the multi-agent evidence court

```powershell
python -m repo_agent agent-court --bundle reports/proof-carrying-counterfactual.bundle.json --attack-scorecard reports/proof-attack-scorecard.json --temporal-scorecard reports/temporal-repair-scorecard.json --output reports/agent-court.md
```

The evidence court is a deterministic multi-agent arbitration protocol. A retrieval advocate, graph navigator, proof verifier, mutation skeptic, red-team skeptic, and temporal guardian each publish a claim with a stable evidence hash. The arbiter accepts the answer only when required claims pass and error-level challenges are discharged; otherwise the report preserves the contested claims and open challenges for review.

The attack and temporal scorecard inputs are optional, but including them turns the court into a stronger release artifact because the red-team and code-evolution agents can participate in the verdict.

### Build the agent reliability frontier

```powershell
python -m repo_agent agent-frontier --manifest reports/release-pack/manifest.json --output reports/agent-frontier.md
python -m repo_agent agent-frontier-ablate --manifest reports/release-pack/manifest.json --output reports/agent-frontier-ablation.md
python -m repo_agent agent-frontier-interactions --manifest reports/release-pack/manifest.json --output reports/agent-frontier-interactions.md
python -m repo_agent agent-frontier-stability --manifest reports/release-pack/manifest.json --output reports/agent-frontier-stability.md
python -m repo_agent agent-artifact-review --manifest reports/release-pack/manifest.json --output reports/agent-artifact-review.md
```

The frontier report treats the release pack as an evaluation corpus. It compares graph-aware retrieval (serialized as `graph_mcts` for compatibility), proof contracts, adversarial minimax repair, temporal repair, multi-agent arbitration, and artifact integrity across six dimensions, then reports the Pareto frontier and bottleneck dimensions. The ablation report then counterfactually masks evidence families and recomputes the frontier to show which artifacts cause the largest score drops or Pareto membership changes. The interaction matrix masks pairs of evidence families and compares observed drop with the additive expectation, surfacing nonlinear reliability dependencies. The stability lab adds deterministic bootstrap perturbations over the manifest metrics, reporting score confidence intervals, Pareto membership survival probabilities, and whether the top evidence interaction is stable or merely a boundary effect. The artifact review card then turns the project narrative into a reviewer-facing claim ledger: each claim lists required artifacts, validation commands, falsifiers, limitations, confidence, and a reproducibility protocol. This is useful in interviews because it avoids pretending that agent quality is one scalar metric or that a GitHub README claim should be trusted without falsifiable evidence.

### Run the proof mutation lab

```powershell
python -m repo_agent proof-mutate --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-mutation-report.md
```

The mutation lab corrupts a valid evidence bundle in controlled ways and measures whether strict replay detects each mutation. Current seeded mutations cover stale top hit, missing route anchor, broken supporting path, unverified proof graph edge, and stale decoy audit.

### Generate a proof reliability scorecard

```powershell
python -m repo_agent proof-scorecard --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-scorecard.md
```

The scorecard gives a compact reliability grade across proof status, strict replay validity, proof-edge verification, decoy audit coverage, and mutation detection.

### Analyze proof-guided change impact

```powershell
python -m repo_agent impact --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-impact-report.md
```

The impact report starts from `proof.top_hit`, walks upstream and downstream graph edges, identifies exposed routes and impacted files, assigns risk items, and suggests verification checks such as strict proof replay and route-level tests.

### Generate and verify a proof regression contract

```powershell
python -m repo_agent contract --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-regression-contract.json
python -m repo_agent verify-contract --contract reports/proof-regression-contract.json --output reports/proof-regression-contract-verification.md
```

The contract freezes the proved target, route literals, route-to-target supporting paths, decoy rejection, and impact route exposure into executable invariants that can be checked after future code changes.

### Run a proof-backed PR guard

```powershell
python -m repo_agent pr-guard --contract reports/proof-regression-contract.json --changed-files server.js --fail-on never --output reports/proof-pr-guard-report.md --sarif-output reports/proof-pr-guard.sarif
```

The PR guard compares changed files against protected proof surfaces. If a PR touches the proved target file, supporting path, or route-exposed surface, it emits required verification commands such as strict proof replay and contract verification.

For CI, make protected-surface warnings fail the job and emit GitHub Actions annotations:

```powershell
python -m repo_agent pr-guard --contract reports/proof-regression-contract.json --changed-files-file changed-files.txt --fail-on warn --github-annotations
```

To publish findings to GitHub Code Scanning, also pass `--sarif-output proof-pr-guard.sarif` and upload the SARIF file with `github/codeql-action/upload-sarif`.

### Locate a proof regression in git history

```powershell
python -m repo_agent temporal-proof-regression --contract reports/proof-regression-contract.json --git-repo . --repo-subdir examples/counterfactual_agent_app --rev-range HEAD --output reports/temporal-proof-regression.md
```

Temporal proof regression exports each selected commit with `git archive`, replays the proof regression contract against the snapshot, and reports the pass-to-fail transition. It never checks out commits in the active worktree, so it can run even when the developer has local changes. When a pass-to-fail transition is found, Proof Graph Delta compares the last passing and first failing proof paths to show which route/call edges disappeared and whether the top successor relinks through the same predecessor. Repair inference then ranks likely successor symbols using route reachability, proof-path predecessor continuity, body-token overlap, call overlap, and name similarity. Contract migration planning turns the reviewed successor into JSON Patch-style operations for the proof contract and lists the artifacts that must be regenerated.

### Run the temporal repair benchmark

```powershell
python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.json
python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.md
```

The benchmark constructs synthetic git histories, generates a proof contract from the passing commit, breaks the proof in the next commit, then measures whether temporal repair finds the expected successor, explains the graph delta, and produces a review-ready migration plan. Current bundled cases cover same-file renames, a cross-file writer move, and a no-successor deletion that should abstain instead of inventing a repair.

Grade the benchmark as a release gate:

```powershell
python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.json --sarif-output reports/temporal-repair-scorecard.sarif --github-annotations --fail-on-fail
python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.md
```

The scorecard checks successor@1, negative-control abstention, causal graph-delta rate, and migration-ready rate against thresholds. With `--fail-on-fail`, it exits non-zero when a threshold is missed; with `--github-annotations` and `--sarif-output`, failed metrics and benchmark cases can appear directly in GitHub Actions logs and Code Scanning.

### Generate the full release pack

```powershell
python -m repo_agent release-pack --output-dir reports/release-pack
```

The release pack is the cross-platform demo bundle for GitHub: ablation report, counterfactual report, portable benchmark adapter report, benchmark generalization diagnostics, benchmark repair card, benchmark repair synthesis, benchmark repair implementation verification, benchmark repair compiler, benchmark repair workbench, adversarial mutation spec, adversarial proof attack benchmark, attack leaderboard, defense triage plan, synthesized defense policy, adaptive proof attack curriculum, adaptive policy repair, minimax certificate, adversarial proof attack scorecard/SARIF, CEGAR reliability loop, proof-carrying HTML report, JSON evidence bundle, strict replay report, mutation lab report, proof reliability scorecard, proof-guided impact report, proof regression contract, contract verification report, PR guard report, PR guard SARIF, temporal proof regression report, temporal repair benchmark, temporal repair scorecard SARIF, multi-agent evidence court ledger/report, agent reliability frontier, frontier causal ablation, evidence interaction matrix, frontier stability lab, artifact evaluation card, and a manifest.

Verify that every release-pack artifact still matches the generated manifest:

```powershell
python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json
```

The manifest records SHA-256 and byte-size metadata for each artifact, so missing or tampered reports fail verification.

### Ask a question from the CLI

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?"
```

### Launch the web studio

```powershell
python -m repo_agent serve
```

Then open `http://127.0.0.1:8787`.

## Real AI Agent Mode

Repo Agent works without a model by default.

If you want the real agent loop, copy `.env.example` to `.env` and set:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `REPO_AGENT_EMBEDDING_MODEL` (optional; defaults to `text-embedding-3-small`)

Then run:

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --use-model
```

With `--use-model`, Repo Agent gives the model a safe tool belt and records every tool call in the trace. If an embedding model is configured, the index also performs dense semantic recall; the model can then inspect files, search symbols/text, follow callers/callees, and run allow-listed verification commands before producing the final answer.

Without `--use-model`, Repo Agent falls back to deterministic graph-aware retrieval and evidence ranking.

## Experimental Engineering Mode

Repo Agent includes an experimental engineering loop for small, controlled changes after investigation. It can inspect files, edit in a workspace copy, run allow-listed verification commands, and persist a full run record.

Workspace mode is the default for both the CLI and Web Studio. In this mode edits happen under `runs/<run_id>/workspace` first:

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint" --execution-mode workspace
```

Run directly against the source repository only when you have reviewed the task and trust the edit surface:

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint and verify the project still compiles" --execution-mode local
```

Resume a saved run:

```powershell
python -m repo_agent resume --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx
```

Apply a reviewed workspace run back to the source repository:

```powershell
python -m repo_agent apply-run --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx --confirm
```

When applying a workspace run, Repo Agent only copies changed repository files back to the source tree. Protected and generated paths such as `.env`, `.git`, `runs`, `reports`, caches, and build outputs are skipped.

Run engineering benchmark cases:

```powershell
python -m repo_agent bench --json
```

The experimental engineering loop can:

- inspect files and search the codebase
- retrieve relevant code with the repository graph
- edit files with exact replacements or controlled file writes
- run allow-listed verification commands such as compile checks, tests, builds, and `node --check`
- auto-select a safe verification command when files changed but no test/build command was observed
- classify failed verification output into test failure, syntax error, missing dependency, timeout, or environment categories
- inspect status/diff, revert a bad file edit, and finish with reviewer feedback
- score file-level review risk and suggest concrete follow-up actions before apply-back
- render a structured multi-agent run timeline for Coordinator, Planner, Investigator, Patch, Verifier, and Reviewer events
- apply reviewed workspace changes back to the source repo with explicit confirmation
- persist the full run trace and final diff in `runs/<run_id>/run.json`

This mode is deliberately constrained. The main product promise remains investigation first: make the evidence clear before code changes happen.

## Web Studio

The web studio supports:

- repository path input
- AI agent mode toggle
- autonomous engineering button
- local or workspace-sandbox execution mode selector
- Runs view with open, resume, and apply actions
- multi-agent timeline cards for engineering runs
- verifier and reviewer gate summaries with risk score, failed verification details, and file-level risk
- proof-guided impact generation with route exposure, risk summary, impacted files, and verification plan
- one-click indexing
- repository QA and bug-localization runs
- startup hints and quick verification
- directory listing, file reading, and text search inside the repo
- ranked evidence inspection
- trace inspection
- HTML report generation and preview
- Impact report generation and preview

## CLI Commands

```text
repo-agent index  --repo <path> [--force-rebuild]
repo-agent ask    --repo <path> --question "<query>" [--use-model] [--top-k <n>]
repo-agent engineer --repo <path> --task "<task>" [--execution-mode local|workspace] [--max-steps <n>] [--json]
repo-agent resume --run-id <run_id> [--max-steps <n>] [--json]
repo-agent runs [--limit <n>] [--json]
repo-agent apply-run --run-id <run_id> --confirm [--json]
repo-agent bench [--cases <path>] [--max-steps <n>] [--json]
repo-agent map    --repo <path> [--force-rebuild]
repo-agent report --repo <path> --question "<query>" [--use-model]
repo-agent bundle --repo <path> --question "<query>" [--target generic|codex|aider|openhands] [--format markdown|json]
repo-agent replay-proof --bundle <path.json> [--repo <path>] [--strict] [--json] [--output <path.json|path.md>]
repo-agent proof-mutate --bundle <path.json> [--repo <path>] [--no-strict] [--json] [--output <path.json|path.md>]
repo-agent proof-scorecard --bundle <path.json> [--repo <path>] [--no-strict] [--json] [--output <path.json|path.md>]
repo-agent impact --bundle <path.json> [--repo <path>] [--target <source-label>] [--max-depth <n>] [--json] [--output <path.json|path.md>]
repo-agent contract --bundle <path.json> [--repo <path>] [--max-depth <n>] [--json] [--output <path.json|path.md>]
repo-agent verify-contract --contract <contract.json> [--repo <path>] [--json] [--output <path.json|path.md>]
repo-agent pr-guard --contract <contract.json> [--repo <path>] [--changed-files <path> ...] [--changed-files-file <path>] [--fail-on fail|warn|never] [--github-annotations] [--sarif-output <path.sarif>] [--json] [--output <path.json|path.md>]
repo-agent temporal-repair-scorecard --benchmark <benchmark.json> [--min-successor-top1 <n>] [--min-abstention <n>] [--min-delta-rate <n>] [--min-migration-rate <n>] [--fail-on-fail] [--github-annotations] [--sarif-output <path.sarif>] [--json] [--output <path.json|path.md>]
repo-agent agent-court --bundle <path.json> [--repo <path>] [--proof-scorecard <scorecard.json>] [--attack-scorecard <scorecard.json>] [--temporal-scorecard <scorecard.json>] [--no-strict] [--json] [--output <path.json|path.md>]
repo-agent release-pack [--output-dir <dir>] [--top-k <n>] [--json]
repo-agent verify-release-pack --manifest <manifest.json> [--json]
repo-agent agent-frontier --manifest <manifest.json> [--json] [--output <path.json|path.md>]
repo-agent agent-frontier-ablate --manifest <manifest.json> [--json] [--output <path.json|path.md>]
repo-agent agent-frontier-interactions --manifest <manifest.json> [--json] [--output <path.json|path.md>]
repo-agent agent-frontier-stability --manifest <manifest.json> [--samples <n>] [--noise <n>] [--seed <n>] [--json] [--output <path.json|path.md>]
repo-agent agent-artifact-review --manifest <manifest.json> [--json] [--output <path.json|path.md>]
repo-agent serve  [--host 127.0.0.1] [--port 8787]
repo-agent eval   [--top-k <n>] [--json] [--output <path.json|path.md>]
repo-agent ablate [--top-k <n>] [--json] [--output <path.json|path.md>]
repo-agent counterfactual [--top-k <n>] [--json] [--output <path.json|path.md>]
repo-agent benchmark-adapter --suite <suite.json> [--top-k <n>] [--emit-template] [--json] [--output <path.json|path.md>]
repo-agent benchmark-diagnose --benchmark <benchmark-adapter.json> [--min-top1 <n>] [--min-top3 <n>] [--json] [--output <path.json|path.md>]
repo-agent benchmark-repair-card --benchmark <benchmark-adapter.json> [--json] [--output <path.json|path.md>]
repo-agent benchmark-repair-synthesize --benchmark <benchmark-adapter.json> [--json] [--output <path.json|path.md>]
repo-agent benchmark-repair-verify-implementation --synthesis <benchmark-repair-synthesis.json> [--source <indexer.py>] [--json] [--output <path.json|path.md>]
repo-agent benchmark-repair-compile --synthesis <benchmark-repair-synthesis.json> [--implementation <benchmark-repair-implementation.json>] [--source <indexer.py>] [--json] [--output <path.json|path.md>]
repo-agent benchmark-repair-workbench --compiler <benchmark-repair-compiler.json> [--source <indexer.py>] [--json] [--output <path.json|path.md>]
repo-agent proof-attack [--spec <spec.json>] [--output-dir <dir>] [--top-k <n>] [--json] [--output <path.json|path.md>]
repo-agent proof-attack-leaderboard --benchmark <benchmark.json> [--json] [--output <path.json|path.md>]
repo-agent proof-attack-triage --benchmark <benchmark.json> [--leaderboard <leaderboard.json>] [--json] [--output <path.json|path.md>]
repo-agent proof-attack-policy --benchmark <benchmark.json> [--leaderboard <leaderboard.json>] [--triage <triage.json>] [--json] [--output <path.json|path.md>]
repo-agent proof-attack-adaptive --benchmark <benchmark.json> --policy <policy.json> [--output-dir <dir>] [--top-k <n>] [--json] [--output <path.json|path.md>]
repo-agent proof-attack-repair --policy <policy.json> --adaptive <adaptive.json> [--json] [--output <path.json|path.md>]
repo-agent proof-attack-certificate --benchmark <benchmark.json> --policy <policy.json> --adaptive <adaptive.json> --repair <repair.json> [--json] [--output <path.json|path.md>]
repo-agent proof-attack-scorecard --benchmark <benchmark.json> [--min-attack-resistance <n>] [--min-mitigated-decoys <n>] [--min-mitigation-signals <n>] [--min-proof-proved <n>] [--fail-on-fail] [--github-annotations] [--sarif-output <path.sarif>] [--json] [--output <path.json|path.md>]
repo-agent proof-attack-cegar [--spec <spec.json>] [--output-dir <dir>] [--top-k <n>] [--fail-on-blocker] [--json] [--output <path.json|path.md>]
```

## Evidence Bundles

Use `repo-agent bundle` when you want Repo Agent to do the investigation phase, then hand the grounded evidence to a coding agent for edits:

```powershell
python -m repo_agent bundle --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --target codex
```

The bundle includes the repository brief, ranked evidence, snippets, graph edges, trace steps, evidence diagnostics, and a handoff prompt tailored to the selected target.

## Repository Layout

```text
repo_agent/
  agent.py        answer composition
  indexer.py      graph building + multi-view retrieval + reranking
  memory.py       repository brief and role memory
  parsers.py      symbol extraction
  runtime.py      cache + safety + orchestration
  tools.py        repo tool runtime for multi-step investigation
  server.py       local HTTP server
  llm.py          OpenAI-compatible model adapter
web/
  index.html      web studio shell
  app.js          UI logic
  styles.css      UI styling
examples/
  simple_agent_app/
  simple_fastapi_app/
  simple_rag_app/
```

## Evaluation

Repo Agent ships with reproducible fixture repositories under `examples/`, so `repo-agent eval` works out of the box on a fresh clone and in CI.

Current eval scenarios cover:

- chat endpoint localization
- route-to-handler localization
- session reset localization
- RAG upload entry localization
- RAG main-flow inspection
- FastAPI/Flask-style decorator route localization
- counterfactual public/admin/legacy route disambiguation with hard negatives

The default eval prints per-case rank plus aggregate retrieval metrics:

```text
Summary: 11/11 passed @top3
Top-1 accuracy: 100.00%
Top-3 accuracy: 100.00%
MRR: 1.000
```

The counterfactual benchmark is intentionally adversarial. Current bundled hard-negative result:

```text
graph_mcts: Top-1 100.00%, Top-3 100.00%, MRR 1.000, distractor@1 0.00%
lexical:    Top-1 0.00%,   Top-3 0.00%,   MRR 0.139, distractor@1 0.00%
```

The built-in eval is a smoke suite, not a claim of broad benchmark dominance. The public benchmark plan is tracked in [docs/benchmarking.md](docs/benchmarking.md).

## Quality Gate

Run the release gate before publishing or opening a pull request:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release_gate.ps1
```

The release gate compiles sources, checks Web Studio JavaScript, runs pytest, regenerates ablation/counterfactual reports, runs the portable benchmark adapter, generalization diagnostics, repair card, repair synthesizer, repair implementation verification, repair compiler, and repair workbench, runs spec-driven adversarial proof attacks, generates an attack leaderboard, defense triage plan, synthesized defense policy, adaptive policy curriculum, adaptive policy repair, and minimax certificate, grades the benchmark as a hard self-red-team CI gate with SARIF/annotations, runs the CEGAR reliability loop, builds the proof-carrying report and evidence bundle, runs strict proof replay, runs the proof mutation lab, generates the reliability scorecard, builds proof-guided impact analysis, generates and verifies the proof regression contract, runs the proof-backed PR guard, builds the release pack, generates the agent reliability frontier, frontier causal ablation, evidence interaction matrix, frontier stability lab, and artifact evaluation card, runs the temporal repair scorecard as a hard CI gate with SARIF/annotations, runs the multi-agent evidence court, verifies the integrity manifest, and scans tracked files for obvious secrets.

The core checks are:

```powershell
python -m compileall repo_agent tests examples
node --check web/app.js
python -m pytest
python -m repo_agent ablate --output reports/ablation-report.md
python -m repo_agent counterfactual --output reports/counterfactual-report.md
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.md
python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-adapter.json --output reports/benchmark-diagnostics.md
python -m repo_agent benchmark-repair-card --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-card.md
python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.json
python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.md
python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.json
python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.json
python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.md
python -m repo_agent benchmark-repair-workbench --compiler reports/benchmark-repair-compiler.json --output reports/benchmark-repair-workbench.md
python -m repo_agent proof-attack --spec repo_agent/proof_attack_specs.json --output-dir reports/proof-attack-benchmark --output reports/proof-attack-benchmark.json
python -m repo_agent proof-attack-leaderboard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-leaderboard.md
python -m repo_agent proof-attack-triage --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-triage.md
python -m repo_agent proof-attack-policy --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-policy.json
python -m repo_agent proof-attack-policy --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-policy.md
python -m repo_agent proof-attack-adaptive --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --output-dir reports/proof-attack-adaptive --output reports/proof-attack-adaptive.json
python -m repo_agent proof-attack-adaptive --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --output-dir reports/proof-attack-adaptive --output reports/proof-attack-adaptive.md
python -m repo_agent proof-attack-repair --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --output reports/proof-attack-repair.md
python -m repo_agent proof-attack-certificate --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --repair reports/proof-attack-repair.json --output reports/proof-attack-certificate.md
python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.json --sarif-output reports/proof-attack-scorecard.sarif --github-annotations --fail-on-fail
python -m repo_agent proof-attack-cegar --spec repo_agent/proof_attack_specs.json --output-dir reports/proof-attack-cegar --output reports/proof-attack-cegar.md
python -m repo_agent proof-scorecard --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-scorecard.md
python -m repo_agent impact --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-impact-report.md
python -m repo_agent contract --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-regression-contract.json
python -m repo_agent verify-contract --contract reports/proof-regression-contract.json --output reports/proof-regression-contract-verification.md
python -m repo_agent pr-guard --contract reports/proof-regression-contract.json --changed-files server.js --fail-on never --output reports/proof-pr-guard-report.md --sarif-output reports/proof-pr-guard.sarif
python -m repo_agent release-pack --output-dir reports/release-pack
python -m repo_agent agent-frontier --manifest reports/release-pack/manifest.json --output reports/agent-frontier.md
python -m repo_agent agent-frontier-ablate --manifest reports/release-pack/manifest.json --output reports/agent-frontier-ablation.md
python -m repo_agent agent-frontier-interactions --manifest reports/release-pack/manifest.json --output reports/agent-frontier-interactions.md
python -m repo_agent agent-frontier-stability --manifest reports/release-pack/manifest.json --output reports/agent-frontier-stability.md
python -m repo_agent agent-artifact-review --manifest reports/release-pack/manifest.json --output reports/agent-artifact-review.md
python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.json
python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.json --sarif-output reports/temporal-repair-scorecard.sarif --github-annotations --fail-on-fail
python -m repo_agent agent-court --bundle reports/proof-carrying-counterfactual.bundle.json --attack-scorecard reports/proof-attack-scorecard.json --temporal-scorecard reports/temporal-repair-scorecard.json --output reports/agent-court.md
python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json
```

## Configuration

See `.env.example` for:

- optional model settings
- allowed repository roots
- question length limit
- top-k limit
- index file count and file size limits

## Before Publishing

Clean generated local artifacts before pushing:

```powershell
pwsh .\scripts\clean_generated.ps1
```

For repository metadata, topics, and social preview suggestions, see:

- [docs/github-launch-checklist.md](docs/github-launch-checklist.md)
- [docs/repository-metadata.md](docs/repository-metadata.md)
- [docs/benchmarking.md](docs/benchmarking.md)
- [docs/roadmap.md](docs/roadmap.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

For security-sensitive issues, see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
