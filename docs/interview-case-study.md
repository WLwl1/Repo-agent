# Repo Agent Interview Case Study

Repo Agent is an evidence-first codebase investigation system. It answers the question a coding agent should answer before editing files: where is the relevant code, why is it relevant, and how confident should we be?

## Interview Pitch

Modern coding agents are impressive at applying patches, but they are only as good as the repository context they operate on. Repo Agent focuses on the context layer: it builds a local repository index, extracts symbols and route-like edges, retrieves candidate code with hybrid lexical and semantic signals, expands through a lightweight graph, and produces a reviewable evidence trail before any edit is attempted.

The project is intentionally model-optional. Without an API key it runs deterministic retrieval, diagnostics, reports, and bundled evals. With an OpenAI-compatible model configured, it adds a tool-calling investigation loop and a constrained engineering loop.

## Research Positioning

The project is positioned against current agent evaluation and retrieval-repair work rather than older chatbot demos. [RaFe](https://arxiv.org/html/2405.14431v1) shows that ranking feedback can drive retrieval/query improvement without hand labels; [CORE-Bench](https://arxiv.org/abs/2409.11363) emphasizes agent artifact credibility and reproducibility; [SWE-bench](https://arxiv.org/abs/2310.06770) made real repository tasks the standard evaluation setting for software agents. Repo Agent's contribution is a code-repository version of that idea: benchmark traces become proof-carrying evidence, counterexamples, and auditable repair rules instead of opaque prompt tweaks.

## Technical Highlights

- Hybrid retrieval: token/BM25-style scoring, local TF-IDF/latent semantic projection, file-role priors, symbol metadata, and graph-aware reranking.
- MCTS-style graph exploration: bounded repository-graph search uses seed nodes, visit counts, exploration/exploitation scoring, node reward, and backpropagated boosts to find high-value execution-path evidence.
- Route-anchored graph priors: exact route literals such as `/api/chat` seed execution-path propagation so public endpoint evidence can outrank admin, legacy, mock, and documentation decoys.
- Repository graph: route, handler, import, and call relationships are extracted into weighted edges so answers can follow execution paths instead of relying on flat text search.
- Evidence diagnostics: each answer includes confidence, score gap, coverage, graph support, matched terms, strengths, and warnings.
- Graph Search Audit: answers, Web Studio, HTML reports, and handoff bundles expose inspected nodes, visits, average reward, boost, and best path so the retrieval process can be reviewed instead of trusted blindly.
- Proof-Carrying Retrieval: each answer can carry a proof object with graph-search checks, route anchors, top-hit validation, supporting execution paths, and warnings. This turns "the retriever ranked X first" into "X is first and is connected to the requested route/path under explicit checks."
- Proof Graph export: the proof object contains nodes and edges for route anchors, top hits, supporting route paths, graph-MCTS visited nodes, and decoy candidates, so a downstream agent or report can reason over the evidence instead of parsing prose.
- Contrastive Decoy Audit: hard negatives are surfaced with rejection reasons, route-anchor status, score gap, and conflicting route-family roles instead of disappearing behind the final ranking.
- Proof Replay: JSON evidence bundles can be replayed against the current repository index to verify that top hits, route literals, supporting paths, proof graph edges, and decoy audit entries still resolve.
- Strict Proof Replay: `replay-proof --strict` verifies proof graph route/path edges against current repository route, call, and import graph edges.
- Proof Drift Diagnosis: failed replays are classified as top-hit drift, route-anchor drift, execution-path drift, stale proof-graph endpoints, or decoy-audit drift, with suggested follow-up actions.
- Proof Mutation Lab: evidence bundles can be automatically corrupted to test whether strict replay detects stale top hits, missing routes, broken paths, bad proof edges, and stale decoy audits.
- Adversarial Proof Attack Benchmark: generated repository mutations inject admin-shadow writers, near-route preview writers, and documentation bait to red-team route-family-aware proof retrieval, with a causal defense audit for each generated decoy.
- Adversarial Mutation Spec and Leaderboard: red-team cases live in a safe JSON DSL, and results are ranked by attack pressure, defense score, residual risk, severity, tags, and weak-signal decoys.
- Adversarial Defense Triage: attack outputs become prioritized hardening actions, so weak mitigation signals and audit gaps are preserved even when the benchmark passes.
- Counterexample-Guided Defense Policy Synthesis: triage actions are converted into declarative rules, then simulated against open counterexamples to measure coverage, residual actions, and expected mitigation-signal improvement.
- Adaptive Proof Attack Curriculum: synthesized defense policies are treated as attack surfaces, producing second-order mutation specs that probe whether policy rules generalize to unseen counterexamples.
- Adaptive Policy Repair: second-order policy gaps are converted into patch rules, then re-evaluated against adaptive triage to prove whether the minimax loop closes.
- Proof Attack Minimax Certificate: the baseline attack, policy synthesis, adaptive attack, and repair artifacts are hashed into a claim ledger with an accepted/rejected verdict.
- Adversarial Proof Attack Scorecard: generated attack resistance, decoy mitigation, mitigation-signal coverage, and proof-proved rate become a hard CI gate with GitHub annotations and SARIF output.
- Proof Attack CEGAR Loop: generated counterexamples, leaderboard pressure, defense triage, scorecard gates, SARIF, and next hardening actions are composed into one counterexample-guided reliability report.
- Proof Reliability Scorecard: proof status, strict replay, verified proof edges, decoy audit coverage, and mutation detection are summarized into one reliability grade.
- Proof-Guided Impact Analysis: a proved target can be expanded into upstream/downstream impact, exposed routes, impacted files, risk items, and verification checks.
- Proof Regression Contracts: a proof bundle can be frozen into executable invariants that future PRs must satisfy.
- Proof-Backed PR Guard: changed files are compared against protected proof surfaces and mapped to required verification gates, GitHub annotations, and SARIF Code Scanning output.
- Temporal Proof Regression, Proof Graph Delta, Repair Inference, and Migration Planning: proof contracts can be replayed across archived git commit snapshots to locate the first commit where an evidence chain stopped holding, explain the causal proof-path diff, rank likely successor symbols, then emit reviewable JSON Patch operations for proof regeneration.
- Temporal Repair Benchmark: synthetic git histories measure successor@1, negative-control abstention, false-repair rate, causal delta detection, and migration-plan readiness across multiple proof-breaking changes.
- Temporal Repair Scorecard: benchmark metrics become a thresholded CI gate with grade, score, failed-case reporting, hard-fail exit codes, GitHub annotations, and SARIF Code Scanning output.
- Multi-Agent Evidence Court: retrieval, graph, proof-verifier, mutation-skeptic, red-team, and temporal agents publish hashed claims and challenges, then an arbiter accepts or contests the answer from machine-checkable evidence instead of chat-style agreement.
- Agent Reliability Frontier: release-pack evidence is projected into reliability, robustness, evidence, adaptivity, governance, and efficiency dimensions, then Pareto-ranked to avoid one-number agent evaluation.
- Agent Frontier Causal Ablation: evidence families are counterfactually masked and the frontier is recomputed to attribute score drops and Pareto membership changes.
- Evidence Interaction Matrix: pairwise evidence-family counterfactuals expose nonlinear reliability dependencies that first-order ablations miss.
- Frontier Stability Lab: deterministic bootstrap perturbations estimate score confidence intervals, Pareto membership survival, and whether the top evidence interaction is robust under metric uncertainty.
- Portable Benchmark Adapter: external suites can be supplied as JSON repo/question/expected-symbol cases, then scored by repository, tag, Top-1, Top-3, MRR, distractor@1, and generalization gaps.
- Benchmark Generalization Diagnostics: adapter outputs are transformed into weak-case taxonomies, group-level action items, and counterfactual Top-1 repair ceilings.
- Benchmark Repair Card: repaired ranking guards are audited through top-hit reasons, proving the portable suite reaches Top-1 100% with explicit streaming and retrieval-boundary evidence.
- Benchmark Repair Synthesizer: benchmark traces are converted into proposed or validated retrieval-repair rule DSLs, with affected cases, risk cases, projected Top-1/MRR, and evidence hashes.
- Benchmark Repair Implementation Verification: validated repair rules are mapped back to concrete reranker helpers, source anchors, and emitted reason literals.
- Benchmark Repair Compiler: rule DSLs are compiled into source-level intervention IR, regression locks, ablation toggles, validation commands, and rollback conditions.
- Benchmark Repair Workbench: compiled interventions generate reviewable patch candidates, one-rule ablation diffs, experiment hypotheses, and validation matrices.
- Artifact Evaluation Card: each headline claim is tied to required artifacts, validation commands, falsifiers, limitations, confidence, and a reviewer protocol.
- Artifact Integrity Manifest: every release-pack artifact carries SHA-256 and byte-size metadata, and a verifier catches missing or tampered reports.
- Safe local tooling: file access is path-validated, generated directories are ignored, verification commands are allow-listed, and execution uses `shell=False`.
- Multi-agent engineering gates: Coordinator, Planner, Investigator, Patch, Verifier, and Reviewer events are persisted as a structured run timeline.
- Verifier Agent: changed-file runs can auto-select an allow-listed command, execute it, count pass/fail signals, and classify failure output.
- Reviewer Agent: runs receive a risk score, file-level risk reasons, missing-test warnings, and suggested follow-up actions.
- Workspace engineering mode: autonomous edits happen in `runs/<run_id>/workspace` by default, with persisted traces, timeline events, diffs, changed files, and explicit apply-back.
- Handoff artifacts: HTML reports and Markdown/JSON evidence bundles can be passed to Codex, Aider, OpenHands, or a human reviewer.
- Reproducible evals: bundled localization cases report Top-1 accuracy, Top-3 accuracy, MRR, average confidence, per-case ranks, retrieval ablations, counterfactual hard-negative metrics, adversarial proof-attack resistance, and mitigation-signal coverage.

## Architecture

```text
Repository
  -> parser layer
     -> files, chunks, symbols, routes, imports, calls
  -> repository index
     -> lexical statistics, latent semantic matrix, graph edges, file facts
  -> investigation pipeline
     -> query plan -> file scout -> code read -> MCTS graph search -> rerank
  -> answer layer
     -> evidence, snippets, graph support, diagnostics, trace
  -> optional agent layer
     -> safe tools, verification, review gates, workspace edits, persisted runs
  -> multi-agent evidence court
     -> Retrieval Advocate -> Graph Navigator -> Proof Verifier -> Mutation Skeptic -> Red-Team Skeptic -> Temporal Guardian -> Arbiter
  -> multi-agent run timeline
     -> Coordinator -> Planner -> Investigator -> Patch -> Verifier -> Reviewer
```

## What Makes It More Than A Wrapper

Repo Agent does not simply send the whole repository to a model. The core retrieval path works locally and deterministically:

1. It classifies the query into repository QA or bug localization.
2. It expands query terms with code-oriented synonyms.
3. It ranks likely files using token overlap, file roles, routes, and language priors.
4. It scores chunks with lexical and semantic features.
5. It runs a bounded MCTS-style search over route, handler, import, and call edges.
6. It detects exact route literals in the query and propagates route-anchored path priors through the execution graph.
7. It converts visits and rewards into traceable graph boosts, then reranks candidates.
8. It builds a proof-carrying retrieval object that records route literals, graph-search checks, top-hit validation, and supporting paths.
9. It computes confidence diagnostics from ranking quality and graph support.
10. It exports the graph-search audit trail and proof object into the answer, API response, HTML report, and evidence bundle.

This design gives the project a defensible systems story: indexing, ranking, graph search, safety boundaries, observability, and evaluation.

## Proof-Carrying Retrieval

The proof object is a compact, machine-readable contract around an answer. For route or execution-path questions, it records:

- whether graph-MCTS ran
- which route literals were anchored from the query
- whether the top-ranked chunk is on a route-anchored path
- the supporting path, for example `/api/chat -> handlePublicChat -> streamPublicChatTurn -> writeChatDelta`
- warnings when evidence is partial or unanchored

The Proof Graph is the visual and machine-readable form of that contract. It separates route anchors, supporting path nodes, the top hit, graph-MCTS visited nodes, and decoy candidates. This is a strong interview differentiator because it gives the project a verification story beyond scoring. A demo report can show `status: proved` for the public `/api/chat` writer while admin, legacy, and mock writers remain visible decoys but fail the route-path proof.

The Contrastive Decoy Audit is the negative half of the proof. For each high-scoring hard negative, it records whether the candidate is route-anchored, the score gap against the top hit, conflicting roles such as `admin` or `legacy`, and a natural-language rejection reason. This makes the benchmark easier to trust: the project can show not only that it avoided the wrong answer, but why the wrong answer was tempting and why it was rejected.

Proof Replay closes the loop. A JSON evidence bundle can be reloaded later and checked against the current repository graph. If a handler was renamed, a route was removed, or a proof graph edge no longer resolves, replay marks the proof invalid. That gives the project a stronger claim than explainability: the evidence is portable and falsifiable.

Strict Proof Replay adds edge-level checking. It does not merely verify that proof graph nodes still exist; it checks that route/path proof edges are backed by current route, call, or import graph edges. That turns proof replay into a lightweight proof checker for codebase evidence.

Proof Drift Diagnosis makes invalid replay results actionable. Instead of a generic failure, replay explains whether the proof broke because the answer symbol disappeared, the requested route changed, the route-to-writer path no longer resolves, proof graph endpoints went stale, or a previously rejected decoy changed state.

Proof Mutation Lab is the self-test for the proof checker. It starts from a valid evidence bundle, injects controlled corruptions, reruns strict replay, and reports detection rate by mutation type. This gives the project a benchmark for the verifier itself, not only for retrieval quality.

Adversarial Proof Attack Benchmark is the red-team loop for retrieval and proof together. It copies the counterfactual demo repository, reads a safe JSON mutation spec, injects generated decoys such as admin-shadow writers, near-route preview writers, and documentation bait, then measures whether graph-MCTS and Proof-Carrying Retrieval still anchor the exact public `/api/chat` path. This is different from static counterfactual cases: the benchmark mutates the repository under test and records attack resistance, graph-MCTS distractor@1, proof proved rate, route-anchor preservation, generated-decoy audit coverage, mitigated-decoy rate, and mitigation-signal coverage. The Causal Defense Audit explains the defense, not only the outcome, by listing each generated decoy's rank, rerank reasons, and signals such as `route-family conflict` or `off-route writer decoy`.

The Adversarial Mutation Spec and Leaderboard make the red-team system extensible. New attacks can be added as JSON templates for route-writer decoys or documentation bait without touching Python code, and `proof-attack-leaderboard` ranks the hardest cases by attack pressure, defense score, residual risk, severity, tags, and weak-signal decoys. This turns the benchmark from a fixed demo into something closer to a community-extensible evaluation harness.

Adversarial Defense Triage closes the CEGAR-style loop. It inspects the benchmark, leaderboard, proof decoy audit, and causal defense audit, then emits P0/P1/P2 hardening actions for unmitigated rank-1 decoys, generated-decoy audit gaps, weak mitigation signals, and high-pressure attacks. Passing a benchmark is no longer the end of the workflow; the system preserves the remaining counterexamples as concrete guard recommendations with evidence hashes.

Counterexample-Guided Defense Policy Synthesis turns triage from advice into an executable design artifact. `proof-attack-policy` synthesizes declarative rules such as generated-decoy audit expansion, documentation-bait mitigation signals, high-pressure regression pins, and rank-window demotion signals, then simulates the policy against the current counterexample set. The report shows rule coverage, residual P0/P1/P2 actions, and before/after mitigation-signal coverage.

Adaptive Proof Attack Curriculum adds the minimax step. `proof-attack-adaptive` reads the synthesized policy, generates a second-order JSON mutation spec that targets individual rules, runs the generated attacks, and evaluates whether the original policy covers the new triage actions. This creates a strong interview story: the project does not just patch yesterday's benchmark; it uses the patch itself as tomorrow's attack surface.

Adaptive Policy Repair closes that minimax loop. `proof-attack-repair` reads the adaptive report, synthesizes new patch rules for uncovered second-order actions, then re-evaluates the repaired policy against the same adaptive triage. The resulting before/after report makes the improvement explicit: coverage delta, residual-action delta, patch rules, and the repaired policy payload.

Proof Attack Minimax Certificate makes the loop auditable as a release artifact. `proof-attack-certificate` reads the baseline benchmark, synthesized policy, adaptive curriculum, and repair report; records SHA-256 inputs; evaluates the claims that must hold for the loop to be trusted; and emits an accepted/rejected verdict. This gives the project a stronger interview claim than "we ran red-team tests": it can show exactly which evidence artifacts support the minimax reliability story.

Adversarial Proof Attack Scorecard turns that red-team loop into CI governance. It weights attack resistance, generated-decoy mitigation, mitigation-signal coverage, and proof-proved rate into a 100-point grade, preserves failed attack cases and unmitigated decoys, exits non-zero when thresholds fail, and emits GitHub annotations plus SARIF for Code Scanning.

The Proof Attack CEGAR Loop is the senior-engineering story. `proof-attack-cegar` runs the generated counterexamples, ranks the hardest cases, turns weak defenses into P0/P1/P2 refinement actions, writes scorecard/SARIF artifacts, then emits a single convergence status: `blocked`, `needs_refinement`, or `converged`. That makes the project look less like a benchmark collection and more like a reliability loop for agentic retrieval systems.

The Proof Reliability Scorecard is the executive summary for GitHub and interviews. It rolls the proof status, strict replay result, verified proof edges, decoy audit coverage, and mutation detection rate into a compact score and grade.

Proof-Guided Impact Analysis turns a proof bundle into a change-risk artifact. It starts from `proof.top_hit`, walks reverse and forward repository graph edges, identifies route exposure, lists impacted files, and produces a verification plan. This is the bridge from "the agent found the right code" to "the agent can reason about what a change would endanger."

Proof Regression Contracts turn the same proof and impact result into PR-time governance. The contract freezes the proved target, route literals, supporting paths, decoy rejection, and route exposure as executable invariants, then `verify-contract` checks them against the current repository state.

Proof-Backed PR Guard is the next step in that governance chain. Given a contract and changed files, it detects whether the PR touched a protected proof surface, then returns a pass/warn/fail decision and the verification commands required before merge. It can also emit GitHub Actions annotations and SARIF, so the finding appears in normal CI and Code Scanning workflows.

Temporal Proof Regression adds the time dimension. Given a proof regression contract and a git revision range, it exports each commit with `git archive`, replays the contract against the snapshot, and reports the pass-to-fail transition. This avoids mutating the active worktree while answering a more senior engineering question: not just "is the proof broken now?", but "which commit first broke it?"

Proof Graph Delta is the causal explanation layer. It compares the proof path in the last passing snapshot against the first failing snapshot and reports which route/call edges were preserved, removed, or unresolved. If a successor candidate exists, it also checks whether the old proof-path predecessor now points to the successor and whether the successor remains reachable from the original route.

Proof Repair Inference is the recovery layer after temporal regression. It compares the last passing snapshot with the first failing snapshot and ranks likely successor symbols using route reachability, proof-path predecessor continuity, body-token overlap, call overlap, and name similarity. The output is intentionally a reviewable repair candidate, not an automatic contract rewrite: a developer can inspect the successor, regenerate the proof bundle, rerun strict replay, and then mint a new proof regression contract.

Contract Migration Planning turns the reviewed successor into concrete operations. The report emits JSON Patch-style replacements for the contract target, proof context, and supporting proof path, plus simulation checks that confirm the successor exists, the proof-path predecessor relinks, and the broken edge is explained. This gives the project a practical repair workflow while preserving human review before changing the proof contract.

Temporal Repair Benchmark keeps the repair story honest. It builds synthetic git histories, creates a proof contract from the passing commit, breaks the proof in the next commit, and then scores whether temporal repair recovers the expected successor, abstains on no-successor negative controls, explains a causal graph delta, and emits a ready-for-review migration plan. The bundled cases include same-file writer renames, a cross-file writer move, and a deletion case where inventing a successor would be wrong.

Temporal Repair Scorecard turns those benchmark metrics into a release gate. It weights Successor@1, negative-control abstention, causal graph-delta rate, and migration-ready rate into a 100-point grade, preserves failed-case details when a threshold is missed, exits non-zero in CI, and emits GitHub annotations plus SARIF for Code Scanning.

Multi-Agent Evidence Court is the reliability protocol on top of the proof system. Instead of asking several agents to debate in prose, it assigns specialized roles: retrieval advocate, graph navigator, proof verifier, mutation skeptic, red-team skeptic, temporal guardian, and arbiter. Each role emits a structured claim with a stable evidence hash; decoys, failed replay checks, unmitigated generated attacks, and failed temporal thresholds become challenges. The arbiter accepts the answer only when required claims pass and error-level challenges are discharged. This is the project's multi-agent story: role specialization plus machine-checkable evidence, not consensus theater.

Agent Reliability Frontier is the evaluation layer over the whole release pack. `agent-frontier` reads the manifest, verifies artifact integrity, then scores graph-MCTS retrieval, proof contracts, adversarial minimax repair, temporal repair, multi-agent arbitration, and release integrity across reliability, robustness, evidence, adaptivity, governance, and efficiency. It reports the Pareto frontier and bottleneck dimensions, which gives the project a more research-shaped claim than a single leaderboard number.

Agent Frontier Causal Ablation answers the follow-up question: which evidence actually caused the frontier score? `agent-frontier-ablate` counterfactually masks graph retrieval, proof contracts, adversarial minimax repair, temporal repair, multi-agent court, and release integrity signals, recomputes the frontier, and reports score drops, profile drops, Pareto membership changes, and protected evidence families. This makes the reliability story harder to dismiss as a dashboard, because it includes causal attribution over its own evidence.

Evidence Interaction Matrix adds the second-order view. `agent-frontier-interactions` masks every pair of evidence families, recomputes the frontier, and compares the observed score drop with the additive expectation from single-family ablations. Positive synergy means two evidence families fail worse together than either one predicts alone; frontier loss means a pair is required to keep a reliability profile on the Pareto frontier. This is the kind of analysis that helps answer a paper-reviewer-style question: are the components independently useful, redundant, or coupled?

Frontier Stability Lab adds the uncertainty view. `agent-frontier-stability` perturbs normalized release-pack metrics with a deterministic bootstrap, recomputes frontier membership and pairwise interactions, then reports score confidence intervals, Pareto survival probabilities, frontier Jaccard stability, and the probability that the same interaction remains the top nonlinear dependency. This answers a tougher reviewer question: are the conclusions stable under measurement noise, or did one threshold happen to make the demo look good?

Portable Benchmark Adapter is the external-validity layer. `benchmark-adapter` accepts a JSON suite where each case points at a repository, natural-language question, expected path/symbol, optional hard-negative distractors, and tags. It reruns Repo Agent's retrieval protocol over those cases, then reports per-repo and per-tag Top-1, Top-3, MRR, distractor@1, evidence hashes, and generalization gaps. This directly answers the skeptical question "does this only work on your own demo?" because reviewers can add new suites without changing Python code.

Benchmark Generalization Diagnostics is the reviewer-facing error analysis for that adapter. `benchmark-diagnose` reads the adapter JSON and labels weak cases with causes such as `top3_recoverable`, `library_boundary_ambiguity`, `streaming_handler_ambiguity`, `hidden_symbol_query`, and `route_anchor_weakness`. It then aggregates group action items and computes counterfactual repair ceilings. This is useful in an interview because it shows scientific restraint: a pass is not treated as the end of the story; the system explains where rank-1 evidence is still under-specified and how much targeted fixes could theoretically recover.

Benchmark Repair Card closes that loop. After the diagnostics exposed streaming-handler ambiguity and retrieval-library ambiguity, the repaired reranker emits explicit reasons such as `streaming handler disambiguation`, `retrieval helper target`, and `library boundary prior`. `benchmark-repair-card` audits those reasons and verifies that all portable benchmark cases are now rank-1. This is the strongest version of the external-validity story: diagnosis, targeted repair, and reproducible repair evidence are all separate artifacts.

Benchmark Repair Synthesizer is the self-improvement layer on top of that loop. `benchmark-repair-synthesize` reads the adapter trace and turns counterexamples into auditable rule candidates such as `prefer_retrieval_library_boundary`, `promote_streaming_handler_intent`, and `demote_rank1_hard_negative`. A rule can be `proposed` when it would move an expected Top-k answer to rank-1, `validated` when the top-hit trace already carries the repair reason, or `dormant` when the suite has no evidence for that family. This gives a stronger research story than manual tuning: failures become a structured rule DSL, projected metrics, coverage cases, risk cases, and stable evidence hashes.

Benchmark Repair Implementation Verification prevents a subtle failure mode: the project could synthesize a convincing rule but never prove that the reranker actually implements it. `benchmark-repair-verify-implementation` reads the synthesis JSON and `repo_agent/indexer.py`, then checks helper anchors such as `_asks_for_streaming`, `_chunk_matches_streaming_intent`, `_asks_for_retrieval_boundary`, and `_chunk_is_library_boundary`, plus emitted reason literals such as `streaming handler disambiguation`, `retrieval helper target`, and `library boundary prior`. This turns the repair loop into rule-to-code evidence rather than report-only self-improvement.

Benchmark Repair Compiler is the next step from verification to controlled change. `benchmark-repair-compile` reads the synthesis and implementation certificates, then emits a source-level intervention IR: target functions, insertion points, guard predicates, score effects, reason literals, validation commands, rollback conditions, and ablation toggles. If a rule is already implemented, it becomes a regression lock; if a rule is proposed or missing, it becomes a patch-required intervention plan. This is useful as a research contribution because the system is no longer just saying "I found a failure"; it is compiling failures into auditable, ablation-ready repair actions.

Benchmark Repair Workbench turns compiled repair intent into experiment-ready artifacts. `benchmark-repair-workbench` reads the compiler JSON and source file, locates emitted reason literals, and generates reviewable candidate diffs for single-rule ablations. This gives each repair rule a concrete falsification path: disable one reason, rerun the adapter/synthesis/implementation/compiler/workbench chain, and check whether the benchmark or claim card observes the expected regression. It is the bridge from "we synthesized a repair" to "we can experimentally measure whether the repair is carrying value."

Artifact Evaluation Card turns the whole project into a falsifiable artifact, not just a demo. `agent-artifact-review` reads the release-pack manifest and emits a claim ledger for route-grounded retrieval, portable generalization diagnostics and repair, counterexample-guided repair synthesis, implementation verification, repair compilation, patch/ablation workbench, proof-carrying retrieval, adaptive minimax reliability, temporal repair, multi-agent court, frontier uncertainty analysis, and tamper-evident reproducibility. Each claim has required artifacts, metric checks, validation commands, falsifiers, limitations, confidence, and a reviewer protocol. In an interview, this is the strongest framing: "I designed the project so a skeptical reviewer can rerun or falsify every headline claim."

The Artifact Integrity Manifest makes the demo pack reproducible as a deliverable. `release-pack` writes hashes and byte sizes for every generated artifact, and `verify-release-pack` re-checks them so a reviewer can detect missing or modified evidence before trusting the package.

## Retrieval Ablation Lab

Repo Agent includes a deterministic ablation command that compares ranking strategies on the same localization cases:

```text
lexical   -> direct chunk scoring without semantic projection or graph expansion
semantic  -> latent semantic projection only
no_graph  -> query planning + file scout + semantic scoring, but no graph-hop boost
hybrid    -> full pipeline with file scout, semantic scoring, graph expansion, and reranking
graph_mcts -> budgeted graph search with visits, reward backpropagation, and traceable boosts
```

This is the technical-depth proof point: the project can explain not only what it returns, but which retrieval component helped or failed on each case.

Current bundled smoke result:

```text
lexical:  Top-1 72.73%, Top-3 90.91%,  MRR 0.826
semantic: Top-1 63.64%, Top-3 72.73%,  MRR 0.705
no_graph: Top-1 81.82%, Top-3 100.00%, MRR 0.894
hybrid:   Top-1 81.82%, Top-3 100.00%, MRR 0.894
graph_mcts: Top-1 81.82%, Top-3 100.00%, MRR 0.909
```

## Counterfactual Hard-Negative Lab

The hard-negative benchmark constructs cases where many symbols share the same surface words. The fixture includes a public `/api/chat` route, admin replay route, legacy chat route, fake stream writer, and documentation-like notes. A weak retriever can match "chat stream writer" but still pick the wrong route family.

```text
lexical   -> direct chunk scoring
semantic  -> latent semantic projection only
no_graph  -> planned retrieval without graph-MCTS route anchoring
hybrid    -> fixed graph expansion
graph_mcts -> route-anchored MCTS graph search
```

Current bundled hard-negative result:

```text
lexical:    Top-1 0.00%,   Top-3 0.00%,   MRR 0.139, distractor@1 0.00%
semantic:   Top-1 0.00%,   Top-3 33.33%,  MRR 0.111, distractor@1 0.00%
no_graph:   Top-1 66.67%,  Top-3 100.00%, MRR 0.833, distractor@1 33.33%
hybrid:     Top-1 66.67%,  Top-3 100.00%, MRR 0.833, distractor@1 33.33%
graph_mcts: Top-1 100.00%, Top-3 100.00%, MRR 1.000, distractor@1 0.00%
```

## Multi-Agent Engineering Gates

The engineering mode records a structured timeline rather than a flat transcript. Each event includes the responsible agent, phase, status, summary, details, and timestamp.

```text
Coordinator Agent
  -> starts or resumes the run, controls finish/apply state
Planner Agent
  -> creates the implementation and verification strategy
Investigator Agent
  -> finds files, reads code, searches text, and retrieves graph evidence
Patch Agent
  -> performs exact replacements or controlled writes
Verifier Agent
  -> runs or auto-selects allow-listed verification commands and classifies failures
Reviewer Agent
  -> scores risk, flags missing tests, reviews public-surface changes, and suggests next actions
```

This lets the project demonstrate agent orchestration with concrete gates: a patch is not just "done"; it has verifier status, reviewer status, file-level risks, and an auditable timeline.

## Demo Script

Run the release gate to regenerate the main artifacts and verify the project end to end:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release_gate.ps1
```

The generated proof artifacts to show first are `reports/proof-scorecard.md`, `reports/proof-replay-report.md`, `reports/proof-mutation-report.md`, and `reports/proof-carrying-counterfactual.html`.

For a cross-platform demo bundle, generate the release pack:

```powershell
python -m repo_agent release-pack --output-dir reports/release-pack
```

Start with `reports/release-pack/README.md`, then open the scorecard, `agent-court.md`, and proof-carrying HTML report.

Verify the generated package before sharing it:

```powershell
python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json
```

Build the reliability frontier from the release pack:

```powershell
python -m repo_agent agent-frontier --manifest reports/release-pack/manifest.json --output reports/agent-frontier.md
python -m repo_agent agent-frontier-ablate --manifest reports/release-pack/manifest.json --output reports/agent-frontier-ablation.md
python -m repo_agent agent-frontier-interactions --manifest reports/release-pack/manifest.json --output reports/agent-frontier-interactions.md
python -m repo_agent agent-frontier-stability --manifest reports/release-pack/manifest.json --output reports/agent-frontier-stability.md
python -m repo_agent agent-artifact-review --manifest reports/release-pack/manifest.json --output reports/agent-artifact-review.md
```

Run the deterministic localization benchmark:

```powershell
python -m repo_agent eval --output reports/eval-report.md
```

Run the retrieval ablation:

```powershell
python -m repo_agent ablate --output reports/ablation-report.md
```

Run the hard-negative benchmark:

```powershell
python -m repo_agent counterfactual --output reports/counterfactual-report.md
```

Run the portable benchmark adapter:

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

Run generated proof attacks:

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

Grade generated proof attacks as a CI gate:

```powershell
python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.json --sarif-output reports/proof-attack-scorecard.sarif --github-annotations --fail-on-fail
python -m repo_agent proof-attack-scorecard --benchmark reports/proof-attack-benchmark.json --output reports/proof-attack-scorecard.md
```

Run the counterexample-guided reliability loop:

```powershell
python -m repo_agent proof-attack-cegar --spec repo_agent/proof_attack_specs.json --output-dir reports/proof-attack-cegar --output reports/proof-attack-cegar.md
```

Generate a proof-carrying hard-negative report:

```powershell
python -m repo_agent report --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --output reports/proof-carrying-counterfactual.html
```

Replay the same proof as a portable JSON evidence artifact:

```powershell
python -m repo_agent bundle --repo ".\examples\counterfactual_agent_app" --question "Which function finally writes streamed tokens for the public /api/chat endpoint?" --format json --output reports/proof-carrying-counterfactual.bundle.json
python -m repo_agent replay-proof --bundle reports/proof-carrying-counterfactual.bundle.json --strict --output reports/proof-replay-report.md
```

Stress-test the proof checker:

```powershell
python -m repo_agent proof-mutate --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-mutation-report.md
```

Generate the reliability scorecard:

```powershell
python -m repo_agent proof-scorecard --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-scorecard.md
```

Generate a proof-guided impact report:

```powershell
python -m repo_agent impact --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-impact-report.md
```

Generate and verify a proof regression contract:

```powershell
python -m repo_agent contract --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-regression-contract.json
python -m repo_agent verify-contract --contract reports/proof-regression-contract.json --output reports/proof-regression-contract-verification.md
```

Run the PR guard for a protected-surface change:

```powershell
python -m repo_agent pr-guard --contract reports/proof-regression-contract.json --changed-files server.js --fail-on never --output reports/proof-pr-guard-report.md --sarif-output reports/proof-pr-guard.sarif
```

In CI, use a stricter policy and emit GitHub annotations:

```powershell
python -m repo_agent pr-guard --contract reports/proof-regression-contract.json --changed-files-file changed-files.txt --fail-on warn --github-annotations --sarif-output proof-pr-guard.sarif
```

Locate the first commit that broke a proof contract:

```powershell
python -m repo_agent temporal-proof-regression --contract reports/proof-regression-contract.json --git-repo . --repo-subdir examples/counterfactual_agent_app --rev-range HEAD --output reports/temporal-proof-regression.md
```

Run the temporal repair benchmark:

```powershell
python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.json
python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.md
```

Grade the temporal repair benchmark:

```powershell
python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.json --sarif-output reports/temporal-repair-scorecard.sarif --github-annotations --fail-on-fail
python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.md
```

Run the multi-agent evidence court:

```powershell
python -m repo_agent agent-court --bundle reports/proof-carrying-counterfactual.bundle.json --attack-scorecard reports/proof-attack-scorecard.json --temporal-scorecard reports/temporal-repair-scorecard.json --output reports/agent-court.md
```

Ask a repository question:

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?"
```

Generate a handoff bundle for a downstream coding agent:

```powershell
python -m repo_agent bundle --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --target codex
```

Run a constrained engineering task in a workspace copy:

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint" --execution-mode workspace
```

Then inspect the run timeline in Web Studio or read `runs/<run_id>/run.json` to see `timeline`, `verifier_result`, and `reviewer_result`.

## Interview Talking Points

- Retrieval quality: explain why route-anchored graph search is more useful than plain grep when the user asks about a route, handler, execution path, or bug surface.
- Counterfactual robustness: show `reports/counterfactual-report.md`; explain `distractor@1` and why graph_mcts avoids admin/legacy decoys.
- Portable generalization: show `reports/benchmark-adapter.md` or `reports/release-pack/benchmark-adapter.md`; explain how a reviewer can add external repo/question/expected-symbol cases, then inspect per-repo/per-tag Top-3 and generalization gaps.
- Generalization diagnostics: show `reports/benchmark-diagnostics.md` or `reports/release-pack/benchmark-diagnostics.md`; explain weak-case taxonomy, projected Top-1 ceiling, and why recoverable Top-3 cases should drive targeted evidence guards instead of broad tuning.
- Generalization repair: show `reports/benchmark-repair-card.md` or `reports/release-pack/benchmark-repair-card.md`; explain that the previous weak families now carry explicit repair reasons and the portable suite reaches Top-1 100%.
- Repair synthesis: show `reports/benchmark-repair-synthesis.md` or `reports/release-pack/benchmark-repair-synthesis.md`; explain proposed versus validated rule states and how the rule DSL turns benchmark failures into reviewable reranker patches.
- Repair implementation verification: show `reports/benchmark-repair-implementation.md` or `reports/release-pack/benchmark-repair-implementation.md`; explain how validated rules are mapped back to concrete source anchors and emitted reason literals.
- Repair compiler: show `reports/benchmark-repair-compiler.md` or `reports/release-pack/benchmark-repair-compiler.md`; explain how validated rules become regression locks and proposed rules become source-level patch plans with ablation toggles.
- Repair workbench: show `reports/benchmark-repair-workbench.md` or `reports/release-pack/benchmark-repair-workbench.md`; explain how the compiler emits reviewable ablation diffs and experiments for each repair reason.
- Adversarial proof attacks: show `reports/proof-attack-benchmark.md`; explain that the system generates new decoy routes/writers, then measures attack resistance and shows the causal defense audit instead of only passing hand-written cases.
- Adversarial mutation DSL and leaderboard: show `repo_agent/proof_attack_specs.json` and `reports/proof-attack-leaderboard.md`; explain that new red-team cases can be added without changing Python code and ranked by residual risk.
- Adversarial defense triage: show `reports/proof-attack-triage.md`; explain that even passing attacks produce prioritized hardening actions for weak signals and audit gaps.
- Defense policy synthesis: show `reports/proof-attack-policy.md`; explain that the system synthesizes auditable defense rules from counterexamples and simulates whether they close the refinement gap.
- Adaptive policy attacks: show `reports/proof-attack-adaptive.md`; explain that the synthesized policy is itself red-teamed by generated second-order attacks, exposing whether rules overfit the first benchmark.
- Adaptive policy repair: show `reports/proof-attack-repair.md`; explain that uncovered second-order gaps become patch rules and are re-evaluated until coverage closes.
- Minimax certificate: show `reports/proof-attack-certificate.md`; explain that baseline attack, policy, adaptive attack, and repair artifacts are hashed into a claim ledger with an accepted/rejected verdict.
- Self-red-team gate: show `reports/proof-attack-scorecard.md` and `reports/proof-attack-scorecard.sarif`; explain that generated attacks now become CI-blocking quality gates.
- CEGAR reliability loop: show `reports/proof-attack-cegar.md`; explain that generated counterexamples are ranked, triaged, gated, and converted into next hardening actions until the loop converges.
- Proof-carrying retrieval: show `reports/proof-carrying-counterfactual.html`; explain why the top hit is marked `proved` only when it is connected to the requested public route path, then use the Proof Graph and Contrastive Decoy Audit to contrast it with admin/legacy decoys.
- Proof replay: show the `replay-proof` command; explain that the evidence bundle is not just a static report but a falsifiable artifact that can be checked after code changes, with drift diagnosis when it fails.
- Proof mutation lab: show `proof-mutate`; explain that the proof checker is evaluated by injecting stale top-hit, route, path, edge, and decoy mutations.
- Reliability scorecard: show `reports/proof-scorecard.md`; use it as the one-page summary before drilling into replay and mutation details.
- Proof-guided impact: show `reports/proof-impact-report.md`; explain that proof artifacts now drive change-impact and verification planning.
- Regression contract: show `reports/proof-regression-contract-verification.md`; explain that investigation evidence becomes executable PR invariants.
- PR guard: show `reports/proof-pr-guard-report.md` and `reports/proof-pr-guard.sarif`; explain that changed files are mapped to proof-protected surfaces, required checks, GitHub annotations, and Code Scanning findings.
- Temporal regression, graph delta, and migration planning: show `reports/temporal-proof-regression.md` or `reports/release-pack/temporal-proof-regression.md`; explain that Repo Agent can replay a proof contract across commit snapshots, identify the first commit that broke the evidence chain without checking out the worktree, show the exact proof-path edge that disappeared, rank the likely successor symbol, and emit reviewable JSON Patch operations for proof regeneration.
- Temporal repair benchmark: show `reports/temporal-repair-benchmark.md` or `reports/release-pack/temporal-repair-benchmark.md`; explain Successor@1, negative-control abstention, false-repair rate, causal graph-delta rate, and migration-ready rate across synthetic proof-breaking histories.
- Temporal repair scorecard: show `reports/temporal-repair-scorecard.md`, `reports/temporal-repair-scorecard.sarif`, or `reports/release-pack/temporal-repair-scorecard.sarif`; explain how benchmark metrics become a hard CI gate instead of remaining a passive report.
- Multi-agent evidence court: show `reports/agent-court.md` or `reports/release-pack/agent-court.md`; explain that the project uses agents as specialized verifiers and skeptics with hashed claims, not as a prose-only debate.
- Agent reliability frontier: show `reports/agent-frontier.md` or `reports/release-pack/agent-frontier.md`; explain why agent reliability is treated as a Pareto frontier across reliability, robustness, evidence, adaptivity, governance, and efficiency instead of one scalar score.
- Frontier causal ablation: show `reports/agent-frontier-ablation.md` or `reports/release-pack/agent-frontier-ablation.md`; explain that evidence families are masked and the frontier is recomputed to prove which artifacts actually drive the score.
- Evidence interaction matrix: show `reports/agent-frontier-interactions.md` or `reports/release-pack/agent-frontier-interactions.md`; explain observed-vs-additive drops and why nonlinear evidence coupling matters for agent reliability.
- Frontier stability lab: show `reports/agent-frontier-stability.md` or `reports/release-pack/agent-frontier-stability.md`; explain score confidence intervals, Pareto survival probability, and whether the top nonlinear dependency survives metric perturbation.
- Artifact evaluation card: show `reports/agent-artifact-review.md` or `reports/release-pack/agent-artifact-review.md`; explain that every headline claim, including portable generalization diagnostics and repair, has required artifacts, validation commands, falsifiers, limitations, and confidence.
- Artifact integrity: show `verify-release-pack`; explain that the generated demo pack is hash-checked and tamper-evident.
- Observability: show the trace steps and confidence diagnostics so the answer is not a black box.
- Multi-agent orchestration: show how Coordinator, Planner, Investigator, Patch, Verifier, and Reviewer produce a structured run timeline.
- Engineering quality gates: explain auto-verification, failure classification, reviewer risk score, file-level risk, and suggested actions.
- Safety: describe ignored generated paths, path validation, allow-listed verification commands, workspace edits, and explicit apply-back.
- Evaluation: show `reports/eval-report.md`, `reports/ablation-report.md`, and `reports/counterfactual-report.md`; explain Top-1, Top-3, MRR, average confidence, and distractor@1.
- Product judgment: position Repo Agent as the evidence layer before full coding agents, not as a vague clone of an IDE assistant.

## Roadmap For Deeper Follow-Up

- Add AST-backed parsers for more languages through Tree-sitter.
- Add a learned reranker behind the deterministic baseline.
- Add SWE-bench-style issue localization cases that evaluate file/symbol ranking before patch generation.
- Add repository-scale profiling for indexing time, memory, and retrieval latency.
