from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, UTC
from pathlib import Path

from .agent import RepoAgent
from .benchmarks import run_engineering_benchmark
from .contract import (
    build_regression_contract,
    guard_pr_with_contract,
    render_contract_markdown,
    render_contract_verification_markdown,
    render_pr_guard_markdown,
    verify_regression_contract,
    write_contract_output,
    write_contract_verification_output,
    write_pr_guard_output,
    write_pr_guard_sarif,
)
from .court import build_agent_court, render_agent_court_markdown, write_agent_court_output
from .impact import analyze_impact_bundle, render_impact_markdown, write_impact_output
from .models import RetrievalHit
from .proof import (
    build_proof_scorecard,
    render_mutation_markdown,
    render_replay_markdown,
    render_scorecard_markdown,
    replay_proof_bundle,
    run_proof_mutation_lab,
    write_mutation_output,
    write_replay_output,
    write_scorecard_output,
)
from .runtime import RepoAgentRuntime
from .security import clamp_top_k
from .server import serve
from .temporal import (
    build_temporal_demo_repo,
    render_temporal_markdown,
    run_temporal_proof_regression,
    write_temporal_output,
)


ABLATION_VARIANTS = ("lexical", "semantic", "no_graph", "hybrid", "graph_mcts")
PROOF_DEMO_QUESTION = "Which function finally writes streamed tokens for the public /api/chat endpoint?"
PROOF_ATTACK_EXPECTED_LABEL = "server.js:writeChatDelta"
PROOF_ATTACK_CASES = (
    {
        "id": "admin_shadow_writer",
        "description": "Injects an admin-only route and writer with public-chat-like naming.",
        "mutation": "admin_shadow",
        "distractors": ["writeChatDeltaForAdminShadow", "handleAdminChatShadow"],
    },
    {
        "id": "near_route_preview_writer",
        "description": "Injects a near-miss /api/chat-preview route with a plausible stream writer.",
        "mutation": "near_route_preview",
        "distractors": ["writeChatDeltaPreview", "handleChatPreview"],
    },
    {
        "id": "documentation_bait_writer",
        "description": "Injects documentation/onboarding bait functions with dense stream-writer vocabulary.",
        "mutation": "documentation_bait",
        "distractors": ["writeChatDeltaDocumentation", "writePublicChatDeltaNotes"],
    },
)


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    runtime = RepoAgentRuntime(project_root)

    parser = argparse.ArgumentParser(description="Repo Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Inspect a repository and print index stats.")
    index_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    index_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    ask_parser = subparsers.add_parser("ask", help="Ask a repository question.")
    ask_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    ask_parser.add_argument("--question", required=True, help="Question for the agent.")
    ask_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve.")
    ask_parser.add_argument("--use-model", action="store_true", help="Use an OpenAI-compatible model if configured.")
    ask_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    map_parser = subparsers.add_parser("map", help="Print a repository overview.")
    map_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    map_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    report_parser = subparsers.add_parser("report", help="Generate a visual HTML investigation report.")
    report_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    report_parser.add_argument("--question", required=True, help="Question for the agent.")
    report_parser.add_argument("--output", help="Optional output HTML path.")
    report_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve.")
    report_parser.add_argument("--use-model", action="store_true", help="Use an OpenAI-compatible model if configured.")
    report_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    bundle_parser = subparsers.add_parser("bundle", help="Export a portable evidence bundle for another coding agent.")
    bundle_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    bundle_parser.add_argument("--question", required=True, help="Question for the agent.")
    bundle_parser.add_argument(
        "--target",
        choices=("generic", "codex", "aider", "openhands"),
        default="generic",
        help="Downstream agent or handoff target.",
    )
    bundle_parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Evidence bundle output format.",
    )
    bundle_parser.add_argument("--output", help="Optional output path.")
    bundle_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve.")
    bundle_parser.add_argument("--use-model", action="store_true", help="Use an OpenAI-compatible model if configured.")
    bundle_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    replay_parser = subparsers.add_parser("replay-proof", help="Replay and validate a JSON evidence bundle proof.")
    replay_parser.add_argument("--bundle", required=True, help="Path to a JSON evidence bundle.")
    replay_parser.add_argument("--repo", help="Optional repository path override.")
    replay_parser.add_argument("--strict", action="store_true", help="Verify proof graph route/path edges against repository graph edges.")
    replay_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    replay_parser.add_argument("--json", action="store_true", help="Print machine-readable replay results.")

    mutation_parser = subparsers.add_parser("proof-mutate", help="Mutate a JSON evidence bundle and measure proof replay detection.")
    mutation_parser.add_argument("--bundle", required=True, help="Path to a JSON evidence bundle.")
    mutation_parser.add_argument("--repo", help="Optional repository path override.")
    mutation_parser.add_argument("--no-strict", action="store_true", help="Disable strict graph edge replay for mutation checks.")
    mutation_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    mutation_parser.add_argument("--json", action="store_true", help="Print machine-readable mutation results.")

    scorecard_parser = subparsers.add_parser("proof-scorecard", help="Build a proof reliability scorecard from a JSON evidence bundle.")
    scorecard_parser.add_argument("--bundle", required=True, help="Path to a JSON evidence bundle.")
    scorecard_parser.add_argument("--repo", help="Optional repository path override.")
    scorecard_parser.add_argument("--no-strict", action="store_true", help="Disable strict graph edge replay for scorecard checks.")
    scorecard_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    scorecard_parser.add_argument("--json", action="store_true", help="Print machine-readable scorecard results.")

    impact_parser = subparsers.add_parser("impact", help="Analyze proof-guided change impact from an evidence bundle.")
    impact_parser.add_argument("--bundle", required=True, help="Path to a JSON evidence bundle.")
    impact_parser.add_argument("--repo", help="Optional repository path override.")
    impact_parser.add_argument("--target", default="", help="Optional source label or symbol override. Defaults to proof.top_hit.")
    impact_parser.add_argument("--max-depth", type=int, default=3, help="Graph depth for upstream/downstream impact.")
    impact_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    impact_parser.add_argument("--json", action="store_true", help="Print machine-readable impact results.")

    contract_parser = subparsers.add_parser("contract", help="Generate a proof regression contract from an evidence bundle.")
    contract_parser.add_argument("--bundle", required=True, help="Path to a JSON evidence bundle.")
    contract_parser.add_argument("--repo", help="Optional repository path override.")
    contract_parser.add_argument("--max-depth", type=int, default=3, help="Graph depth for impact-derived invariants.")
    contract_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    contract_parser.add_argument("--json", action="store_true", help="Print machine-readable contract.")

    verify_contract_parser = subparsers.add_parser("verify-contract", help="Verify a proof regression contract.")
    verify_contract_parser.add_argument("--contract", required=True, help="Path to a proof regression contract JSON.")
    verify_contract_parser.add_argument("--repo", help="Optional repository path override.")
    verify_contract_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    verify_contract_parser.add_argument("--json", action="store_true", help="Print machine-readable verification results.")

    pr_guard_parser = subparsers.add_parser("pr-guard", help="Run a proof-backed PR guard against changed files.")
    pr_guard_parser.add_argument("--contract", required=True, help="Path to a proof regression contract JSON.")
    pr_guard_parser.add_argument("--repo", help="Optional repository path override.")
    pr_guard_parser.add_argument("--changed-files", nargs="*", default=[], help="Changed files to check against protected proof surfaces.")
    pr_guard_parser.add_argument("--changed-files-file", help="Optional newline-delimited file containing changed paths.")
    pr_guard_parser.add_argument("--fail-on", choices=("fail", "warn", "never"), default="fail", help="Exit non-zero on fail, warn/fail, or never.")
    pr_guard_parser.add_argument("--github-annotations", action="store_true", help="Print GitHub Actions annotations for touched proof surfaces.")
    pr_guard_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    pr_guard_parser.add_argument("--sarif-output", help="Optional SARIF output path for GitHub Code Scanning.")
    pr_guard_parser.add_argument("--json", action="store_true", help="Print machine-readable PR guard results.")

    temporal_parser = subparsers.add_parser(
        "temporal-proof-regression",
        help="Replay a proof regression contract across git history and locate the first failing commit.",
    )
    temporal_parser.add_argument("--contract", required=True, help="Path to a proof regression contract JSON.")
    temporal_parser.add_argument("--git-repo", help="Git repository to scan. Defaults to the contract repository.")
    temporal_parser.add_argument("--repo-subdir", help="Repository subdirectory protected by the contract.")
    temporal_parser.add_argument("--rev-range", default="HEAD", help="Git revision range or tip to scan with rev-list.")
    temporal_parser.add_argument("--max-commits", type=int, default=20, help="Maximum commits to check from the selected range.")
    temporal_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    temporal_parser.add_argument("--json", action="store_true", help="Print machine-readable temporal regression results.")

    temporal_bench_parser = subparsers.add_parser(
        "temporal-repair-benchmark",
        help="Run synthetic temporal repair benchmark cases and report successor/delta/migration accuracy.",
    )
    temporal_bench_parser.add_argument("--output-dir", default="reports/temporal-repair-benchmark", help="Directory for generated benchmark work and reports.")
    temporal_bench_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve when creating proof bundles.")
    temporal_bench_parser.add_argument("--output", help="Optional report path. Use .json for JSON, otherwise Markdown is written.")
    temporal_bench_parser.add_argument("--json", action="store_true", help="Print machine-readable benchmark results.")

    temporal_scorecard_parser = subparsers.add_parser(
        "temporal-repair-scorecard",
        help="Grade a temporal repair benchmark and enforce minimum quality thresholds.",
    )
    temporal_scorecard_parser.add_argument("--benchmark", required=True, help="Path to temporal repair benchmark JSON.")
    temporal_scorecard_parser.add_argument("--min-successor-top1", type=float, default=1.0, help="Minimum successor@1 accuracy.")
    temporal_scorecard_parser.add_argument("--min-abstention", type=float, default=1.0, help="Minimum abstention accuracy on negative controls.")
    temporal_scorecard_parser.add_argument("--min-delta-rate", type=float, default=1.0, help="Minimum causal graph delta rate.")
    temporal_scorecard_parser.add_argument("--min-migration-rate", type=float, default=1.0, help="Minimum migration ready rate.")
    temporal_scorecard_parser.add_argument("--fail-on-fail", action="store_true", help="Exit non-zero when the scorecard status is fail.")
    temporal_scorecard_parser.add_argument("--github-annotations", action="store_true", help="Print GitHub Actions annotations for failed thresholds and cases.")
    temporal_scorecard_parser.add_argument("--sarif-output", help="Optional SARIF output path for GitHub Code Scanning.")
    temporal_scorecard_parser.add_argument("--output", help="Optional report path. Use .json for JSON, otherwise Markdown is written.")
    temporal_scorecard_parser.add_argument("--json", action="store_true", help="Print machine-readable scorecard results.")

    release_parser = subparsers.add_parser("release-pack", help="Generate the release demo artifact pack.")
    release_parser.add_argument("--output-dir", default="reports/release-pack", help="Directory for release artifacts.")
    release_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for proof demos.")
    release_parser.add_argument("--json", action="store_true", help="Print machine-readable release pack manifest.")

    verify_release_parser = subparsers.add_parser("verify-release-pack", help="Verify release pack artifact integrity.")
    verify_release_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    verify_release_parser.add_argument("--json", action="store_true", help="Print machine-readable verification results.")

    agent_frontier_parser = subparsers.add_parser(
        "agent-frontier",
        help="Build a multi-objective reliability frontier from a release-pack manifest.",
    )
    agent_frontier_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    agent_frontier_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    agent_frontier_parser.add_argument("--json", action="store_true", help="Print machine-readable frontier results.")

    agent_frontier_ablation_parser = subparsers.add_parser(
        "agent-frontier-ablate",
        help="Run counterfactual evidence-family ablations over the agent reliability frontier.",
    )
    agent_frontier_ablation_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    agent_frontier_ablation_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    agent_frontier_ablation_parser.add_argument("--json", action="store_true", help="Print machine-readable frontier ablation results.")

    agent_frontier_interactions_parser = subparsers.add_parser(
        "agent-frontier-interactions",
        help="Map pairwise evidence-family interactions in the agent reliability frontier.",
    )
    agent_frontier_interactions_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    agent_frontier_interactions_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    agent_frontier_interactions_parser.add_argument("--json", action="store_true", help="Print machine-readable interaction results.")

    agent_frontier_stability_parser = subparsers.add_parser(
        "agent-frontier-stability",
        help="Bootstrap frontier, ablation, and interaction conclusions under metric uncertainty.",
    )
    agent_frontier_stability_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    agent_frontier_stability_parser.add_argument("--samples", type=int, default=64, help="Number of deterministic bootstrap perturbations.")
    agent_frontier_stability_parser.add_argument("--noise", type=float, default=0.04, help="Maximum absolute perturbation for normalized metrics.")
    agent_frontier_stability_parser.add_argument("--seed", type=int, default=7, help="Deterministic bootstrap seed.")
    agent_frontier_stability_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    agent_frontier_stability_parser.add_argument("--json", action="store_true", help="Print machine-readable stability results.")

    agent_artifact_review_parser = subparsers.add_parser(
        "agent-artifact-review",
        help="Generate a reviewer-facing artifact evaluation card from a release-pack manifest.",
    )
    agent_artifact_review_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    agent_artifact_review_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    agent_artifact_review_parser.add_argument("--json", action="store_true", help="Print machine-readable artifact review results.")

    artifact_provenance_parser = subparsers.add_parser(
        "artifact-provenance",
        help="Build a machine-readable claim-to-artifact provenance graph from a release-pack manifest.",
    )
    artifact_provenance_parser.add_argument("--manifest", required=True, help="Path to release-pack manifest.json.")
    artifact_provenance_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    artifact_provenance_parser.add_argument("--json", action="store_true", help="Print machine-readable provenance graph.")

    verify_artifact_provenance_parser = subparsers.add_parser(
        "verify-artifact-provenance",
        help="Verify a claim-to-artifact provenance graph and its artifact hashes.",
    )
    verify_artifact_provenance_parser.add_argument("--provenance", required=True, help="Path to artifact-provenance JSON.")
    verify_artifact_provenance_parser.add_argument("--manifest", help="Optional release-pack manifest path override.")
    verify_artifact_provenance_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    verify_artifact_provenance_parser.add_argument("--json", action="store_true", help="Print machine-readable verification results.")

    engineer_parser = subparsers.add_parser("engineer", help="Run an autonomous software engineering task.")
    engineer_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    engineer_parser.add_argument("--task", required=True, help="Engineering task for the autonomous agent.")
    engineer_parser.add_argument("--max-steps", type=int, default=6, help="Maximum autonomous model/tool turns.")
    engineer_parser.add_argument(
        "--execution-mode",
        choices=("local", "workspace"),
        default="workspace",
        help="Edit the source repo directly or an isolated runs/<id>/workspace copy.",
    )
    engineer_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")
    engineer_parser.add_argument("--json", action="store_true", help="Print machine-readable run data.")

    resume_parser = subparsers.add_parser("resume", help="Resume a persisted autonomous engineering run.")
    resume_parser.add_argument("--run-id", required=True, help="Run id from runs/<run_id>.")
    resume_parser.add_argument("--max-steps", type=int, default=6, help="Additional autonomous model/tool turns.")
    resume_parser.add_argument("--json", action="store_true", help="Print machine-readable run data.")

    runs_parser = subparsers.add_parser("runs", help="List recent autonomous engineering runs.")
    runs_parser.add_argument("--limit", type=int, default=20, help="Maximum runs to print.")
    runs_parser.add_argument("--json", action="store_true", help="Print machine-readable run data.")

    coordination_parser = subparsers.add_parser("coordination", help="Summarize multi-session coordination state.")
    coordination_parser.add_argument("--stale-minutes", type=int, default=120, help="Minutes before the coordination file is considered stale.")
    coordination_parser.add_argument("--json", action="store_true", help="Print machine-readable coordination state.")

    apply_parser = subparsers.add_parser("apply-run", help="Apply a workspace run's changed files to the source repo.")
    apply_parser.add_argument("--run-id", required=True, help="Run id from runs/<run_id>.")
    apply_parser.add_argument("--confirm", action="store_true", help="Required to apply files to the source repository.")
    apply_parser.add_argument("--json", action="store_true", help="Print machine-readable apply result.")

    bench_parser = subparsers.add_parser("bench", help="Run autonomous engineering benchmark cases.")
    bench_parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("engineering_cases.json")),
        help="Path to engineering benchmark case JSON.",
    )
    bench_parser.add_argument("--max-steps", type=int, default=6, help="Default maximum steps per case.")
    bench_parser.add_argument("--json", action="store_true", help="Print machine-readable benchmark data.")

    serve_parser = subparsers.add_parser("serve", help="Launch the local web studio.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host address.")
    serve_parser.add_argument("--port", type=int, default=8787, help="Server port.")

    eval_parser = subparsers.add_parser("eval", help="Run bundled evaluation cases.")
    eval_parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("eval_cases.json")),
        help="Path to evaluation case JSON.",
    )
    eval_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each case.")
    eval_parser.add_argument("--json", action="store_true", help="Print machine-readable evaluation metrics.")
    eval_parser.add_argument(
        "--output",
        help="Optional output path. Use .md for a Markdown report, otherwise JSON is written.",
    )

    ablate_parser = subparsers.add_parser("ablate", help="Run retrieval ablation cases across ranking strategies.")
    ablate_parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("eval_cases.json")),
        help="Path to evaluation case JSON.",
    )
    ablate_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each case.")
    ablate_parser.add_argument("--json", action="store_true", help="Print machine-readable ablation metrics.")
    ablate_parser.add_argument(
        "--output",
        help="Optional output path. Use .md for a Markdown report, otherwise JSON is written.",
    )

    counterfactual_parser = subparsers.add_parser(
        "counterfactual",
        help="Run hard-negative retrieval cases with intentionally confusing decoy symbols.",
    )
    counterfactual_parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("counterfactual_cases.json")),
        help="Path to counterfactual case JSON.",
    )
    counterfactual_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each case.")
    counterfactual_parser.add_argument("--json", action="store_true", help="Print machine-readable counterfactual metrics.")
    counterfactual_parser.add_argument(
        "--output",
        help="Optional output path. Use .md for a Markdown report, otherwise JSON is written.",
    )

    benchmark_adapter_parser = subparsers.add_parser(
        "benchmark-adapter",
        help="Run a portable external benchmark suite through Repo Agent's retrieval and evidence protocol.",
    )
    benchmark_adapter_parser.add_argument("--suite", required=True, help="Path to benchmark suite JSON.")
    benchmark_adapter_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each case.")
    benchmark_adapter_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_adapter_parser.add_argument("--emit-template", action="store_true", help="Write a template benchmark suite instead of running cases.")
    benchmark_adapter_parser.add_argument("--json", action="store_true", help="Print machine-readable benchmark adapter results.")

    benchmark_diagnose_parser = subparsers.add_parser(
        "benchmark-diagnose",
        help="Diagnose portable benchmark generalization gaps and counterfactual repair ceilings.",
    )
    benchmark_diagnose_parser.add_argument("--benchmark", required=True, help="Path to benchmark-adapter JSON output.")
    benchmark_diagnose_parser.add_argument("--min-top1", type=float, default=0.85, help="Top-1 threshold for group-level action items.")
    benchmark_diagnose_parser.add_argument("--min-top3", type=float, default=0.80, help="Top-3 threshold for blocker-level generalization gaps.")
    benchmark_diagnose_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_diagnose_parser.add_argument("--json", action="store_true", help="Print machine-readable diagnostics.")

    benchmark_experiment_parser = subparsers.add_parser(
        "benchmark-experiment-report",
        help="Build a paper-style experiment report from portable benchmark, diagnostics, and repair artifacts.",
    )
    benchmark_experiment_parser.add_argument("--benchmark", required=True, help="Path to benchmark-adapter JSON output.")
    benchmark_experiment_parser.add_argument("--diagnostics", help="Optional benchmark-diagnostics JSON output.")
    benchmark_experiment_parser.add_argument("--repair-card", help="Optional benchmark-repair-card JSON output.")
    benchmark_experiment_parser.add_argument("--repair-synthesis", help="Optional benchmark-repair-synthesis JSON output.")
    benchmark_experiment_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_experiment_parser.add_argument("--json", action="store_true", help="Print machine-readable experiment report.")

    benchmark_repair_parser = subparsers.add_parser(
        "benchmark-repair-card",
        help="Audit whether benchmark diagnostics were closed by concrete ranking repair evidence.",
    )
    benchmark_repair_parser.add_argument("--benchmark", required=True, help="Path to benchmark-adapter JSON output.")
    benchmark_repair_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_repair_parser.add_argument("--json", action="store_true", help="Print machine-readable repair card.")

    benchmark_repair_synth_parser = subparsers.add_parser(
        "benchmark-repair-synthesize",
        help="Synthesize auditable retrieval-repair rules from portable benchmark counterexamples and traces.",
    )
    benchmark_repair_synth_parser.add_argument("--benchmark", required=True, help="Path to benchmark-adapter JSON output.")
    benchmark_repair_synth_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_repair_synth_parser.add_argument("--json", action="store_true", help="Print machine-readable synthesized repair rules.")

    benchmark_repair_impl_parser = subparsers.add_parser(
        "benchmark-repair-verify-implementation",
        help="Verify synthesized retrieval-repair rules against concrete reranker implementation anchors.",
    )
    benchmark_repair_impl_parser.add_argument("--synthesis", required=True, help="Path to benchmark-repair-synthesis JSON output.")
    benchmark_repair_impl_parser.add_argument(
        "--source",
        default=str(Path(__file__).with_name("indexer.py")),
        help="Path to the reranker source file to verify.",
    )
    benchmark_repair_impl_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_repair_impl_parser.add_argument("--json", action="store_true", help="Print machine-readable implementation verification.")

    benchmark_repair_compile_parser = subparsers.add_parser(
        "benchmark-repair-compile",
        help="Compile synthesized retrieval-repair rules into auditable source intervention IR.",
    )
    benchmark_repair_compile_parser.add_argument("--synthesis", required=True, help="Path to benchmark-repair-synthesis JSON output.")
    benchmark_repair_compile_parser.add_argument("--implementation", help="Optional benchmark-repair-implementation JSON output.")
    benchmark_repair_compile_parser.add_argument(
        "--source",
        default=str(Path(__file__).with_name("indexer.py")),
        help="Path to the reranker source file to target.",
    )
    benchmark_repair_compile_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_repair_compile_parser.add_argument("--json", action="store_true", help="Print machine-readable repair compiler IR.")

    benchmark_repair_workbench_parser = subparsers.add_parser(
        "benchmark-repair-workbench",
        help="Build candidate patch and ablation experiments from compiled retrieval-repair interventions.",
    )
    benchmark_repair_workbench_parser.add_argument("--compiler", required=True, help="Path to benchmark-repair-compiler JSON output.")
    benchmark_repair_workbench_parser.add_argument(
        "--source",
        default=str(Path(__file__).with_name("indexer.py")),
        help="Path to the reranker source file to inspect for patch loci.",
    )
    benchmark_repair_workbench_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    benchmark_repair_workbench_parser.add_argument("--json", action="store_true", help="Print machine-readable repair workbench.")

    proof_attack_parser = subparsers.add_parser(
        "proof-attack",
        help="Run adversarial repository mutations that try to fool proof-carrying retrieval.",
    )
    proof_attack_parser.add_argument(
        "--spec",
        default=str(Path(__file__).with_name("proof_attack_specs.json")),
        help="Path to a declarative proof attack spec JSON.",
    )
    proof_attack_parser.add_argument("--output-dir", default="reports/proof-attack-benchmark", help="Directory for generated attack workspaces.")
    proof_attack_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each attack case.")
    proof_attack_parser.add_argument("--json", action="store_true", help="Print machine-readable proof attack metrics.")
    proof_attack_parser.add_argument(
        "--output",
        help="Optional output path. Use .md for a Markdown report, otherwise JSON is written.",
    )

    proof_attack_leaderboard_parser = subparsers.add_parser(
        "proof-attack-leaderboard",
        help="Rank adversarial proof attack cases by pressure, defense quality, and residual risk.",
    )
    proof_attack_leaderboard_parser.add_argument("--benchmark", required=True, help="Path to proof attack benchmark JSON.")
    proof_attack_leaderboard_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_leaderboard_parser.add_argument("--json", action="store_true", help="Print machine-readable leaderboard results.")

    proof_attack_triage_parser = subparsers.add_parser(
        "proof-attack-triage",
        help="Turn adversarial proof attack results into a prioritized defense hardening plan.",
    )
    proof_attack_triage_parser.add_argument("--benchmark", required=True, help="Path to proof attack benchmark JSON.")
    proof_attack_triage_parser.add_argument("--leaderboard", help="Optional proof attack leaderboard JSON.")
    proof_attack_triage_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_triage_parser.add_argument("--json", action="store_true", help="Print machine-readable triage results.")

    proof_attack_policy_parser = subparsers.add_parser(
        "proof-attack-policy",
        help="Synthesize a declarative defense policy from adversarial proof attack counterexamples.",
    )
    proof_attack_policy_parser.add_argument("--benchmark", required=True, help="Path to proof attack benchmark JSON.")
    proof_attack_policy_parser.add_argument("--leaderboard", help="Optional proof attack leaderboard JSON.")
    proof_attack_policy_parser.add_argument("--triage", help="Optional proof attack triage JSON.")
    proof_attack_policy_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_policy_parser.add_argument("--json", action="store_true", help="Print machine-readable synthesized policy results.")

    proof_attack_adaptive_parser = subparsers.add_parser(
        "proof-attack-adaptive",
        help="Generate and run adaptive proof attacks against a synthesized defense policy.",
    )
    proof_attack_adaptive_parser.add_argument("--benchmark", required=True, help="Path to the baseline proof attack benchmark JSON.")
    proof_attack_adaptive_parser.add_argument("--policy", required=True, help="Path to synthesized proof attack policy JSON.")
    proof_attack_adaptive_parser.add_argument("--output-dir", default="reports/proof-attack-adaptive", help="Directory for adaptive attack artifacts.")
    proof_attack_adaptive_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each adaptive attack case.")
    proof_attack_adaptive_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_adaptive_parser.add_argument("--json", action="store_true", help="Print machine-readable adaptive stress-test results.")

    proof_attack_repair_parser = subparsers.add_parser(
        "proof-attack-repair",
        help="Synthesize a policy repair from adaptive proof attack gaps.",
    )
    proof_attack_repair_parser.add_argument("--policy", required=True, help="Path to synthesized proof attack policy JSON.")
    proof_attack_repair_parser.add_argument("--adaptive", required=True, help="Path to adaptive proof attack curriculum JSON.")
    proof_attack_repair_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_repair_parser.add_argument("--json", action="store_true", help="Print machine-readable repaired policy results.")

    proof_attack_certificate_parser = subparsers.add_parser(
        "proof-attack-certificate",
        help="Build a machine-checkable certificate for the minimax proof attack loop.",
    )
    proof_attack_certificate_parser.add_argument("--benchmark", required=True, help="Path to baseline proof attack benchmark JSON.")
    proof_attack_certificate_parser.add_argument("--policy", required=True, help="Path to synthesized proof attack policy JSON.")
    proof_attack_certificate_parser.add_argument("--adaptive", required=True, help="Path to adaptive proof attack curriculum JSON.")
    proof_attack_certificate_parser.add_argument("--repair", required=True, help="Path to adaptive policy repair JSON.")
    proof_attack_certificate_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_certificate_parser.add_argument("--json", action="store_true", help="Print machine-readable certificate results.")

    proof_attack_scorecard_parser = subparsers.add_parser(
        "proof-attack-scorecard",
        help="Grade an adversarial proof attack benchmark and enforce self-red-team thresholds.",
    )
    proof_attack_scorecard_parser.add_argument("--benchmark", required=True, help="Path to proof attack benchmark JSON.")
    proof_attack_scorecard_parser.add_argument("--min-attack-resistance", type=float, default=1.0, help="Minimum attack resistance rate.")
    proof_attack_scorecard_parser.add_argument("--min-mitigated-decoys", type=float, default=1.0, help="Minimum generated decoy mitigation rate.")
    proof_attack_scorecard_parser.add_argument("--min-mitigation-signals", type=float, default=0.5, help="Minimum mitigation signal coverage.")
    proof_attack_scorecard_parser.add_argument("--min-proof-proved", type=float, default=1.0, help="Minimum proof proved rate.")
    proof_attack_scorecard_parser.add_argument("--fail-on-fail", action="store_true", help="Exit non-zero when the scorecard status is fail.")
    proof_attack_scorecard_parser.add_argument("--github-annotations", action="store_true", help="Print GitHub Actions annotations for failed red-team thresholds.")
    proof_attack_scorecard_parser.add_argument("--sarif-output", help="Optional SARIF output path for GitHub Code Scanning.")
    proof_attack_scorecard_parser.add_argument(
        "--output",
        help="Optional output path. Use .json for JSON, otherwise Markdown is written.",
    )
    proof_attack_scorecard_parser.add_argument("--json", action="store_true", help="Print machine-readable scorecard results.")

    proof_attack_cegar_parser = subparsers.add_parser(
        "proof-attack-cegar",
        help="Run a counterexample-guided proof attack reliability loop.",
    )
    proof_attack_cegar_parser.add_argument(
        "--spec",
        default=str(Path(__file__).with_name("proof_attack_specs.json")),
        help="Path to a declarative proof attack spec JSON.",
    )
    proof_attack_cegar_parser.add_argument("--output-dir", default="reports/proof-attack-cegar", help="Directory for CEGAR loop artifacts.")
    proof_attack_cegar_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each attack case.")
    proof_attack_cegar_parser.add_argument("--fail-on-blocker", action="store_true", help="Exit non-zero when the loop finds a blocking counterexample.")
    proof_attack_cegar_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    proof_attack_cegar_parser.add_argument("--json", action="store_true", help="Print machine-readable CEGAR loop results.")

    agent_court_parser = subparsers.add_parser(
        "agent-court",
        help="Run a multi-agent evidence court over proof, replay, mutation, red-team, and temporal scorecards.",
    )
    agent_court_parser.add_argument("--bundle", required=True, help="Path to a JSON evidence bundle.")
    agent_court_parser.add_argument("--repo", help="Optional repository path override.")
    agent_court_parser.add_argument("--proof-scorecard", help="Optional proof reliability scorecard JSON. Computed when omitted.")
    agent_court_parser.add_argument("--attack-scorecard", help="Optional adversarial proof attack scorecard JSON.")
    agent_court_parser.add_argument("--temporal-scorecard", help="Optional temporal repair scorecard JSON.")
    agent_court_parser.add_argument("--no-strict", action="store_true", help="Disable strict graph edge replay while computing missing proof scorecards.")
    agent_court_parser.add_argument("--output", help="Optional output path. Use .json for JSON, otherwise Markdown is written.")
    agent_court_parser.add_argument("--json", action="store_true", help="Print machine-readable court results.")

    args = parser.parse_args()

    if args.command == "index":
        repo_index = runtime.load_index(args.repo, force_rebuild=args.force_rebuild)
        print(json.dumps(repo_index.stats(), ensure_ascii=False, indent=2))
        return

    if args.command == "ask":
        result, _repo_index = runtime.ask(
            repo_path=args.repo,
            question=args.question,
            top_k=clamp_top_k(args.top_k, runtime.config),
            use_model=args.use_model,
            force_rebuild=args.force_rebuild,
        )
        print(result.answer)
        if result.diagnostics:
            print("\n[Confidence]")
            print(f"- {result.diagnostics.label} ({result.diagnostics.confidence:.2f})")
            for warning in result.diagnostics.warnings[:3]:
                print(f"- warning: {warning}")
        print("\n[Top Hits]")
        for hit in result.hits:
            print(
                f"- {hit.chunk.source_label} "
                f"({hit.chunk.start_line}-{hit.chunk.end_line}) "
                f"score={hit.score:.2f}"
            )
        if result.model_name:
            print(f"\n[Model]\n- {result.model_name}")
        return

    if args.command == "map":
        repo_index = runtime.load_index(args.repo, force_rebuild=args.force_rebuild)
        print(json.dumps(repo_index.repository_overview(), ensure_ascii=False, indent=2))
        return

    if args.command == "report":
        result, _repo_index, report_path = runtime.generate_report(
            repo_path=args.repo,
            question=args.question,
            top_k=clamp_top_k(args.top_k, runtime.config),
            use_model=args.use_model,
            force_rebuild=args.force_rebuild,
            output_path=args.output,
        )
        print(str(report_path))
        if result.model_name:
            print(f"model={result.model_name}")
        return

    if args.command == "bundle":
        bundle, bundle_path = runtime.generate_bundle(
            repo_path=args.repo,
            question=args.question,
            target=args.target,
            fmt=args.format,
            top_k=clamp_top_k(args.top_k, runtime.config),
            use_model=args.use_model,
            force_rebuild=args.force_rebuild,
            output_path=args.output,
        )
        print(str(bundle_path))
        print(f"target={bundle.get('target', '')}")
        print(f"evidence={len(bundle.get('evidence', []))}")
        return

    if args.command == "replay-proof":
        payload = replay_proof_bundle(
            bundle_path=Path(args.bundle),
            repo_path=Path(args.repo) if args.repo else None,
            strict=args.strict,
        )
        if args.output:
            written = write_replay_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_replay_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-mutate":
        payload = run_proof_mutation_lab(
            bundle_path=Path(args.bundle),
            repo_path=Path(args.repo) if args.repo else None,
            strict=not args.no_strict,
        )
        if args.output:
            written = write_mutation_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_mutation_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-scorecard":
        payload = build_proof_scorecard(
            bundle_path=Path(args.bundle),
            repo_path=Path(args.repo) if args.repo else None,
            strict=not args.no_strict,
        )
        if args.output:
            written = write_scorecard_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_scorecard_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "impact":
        payload = analyze_impact_bundle(
            Path(args.bundle),
            repo_path=Path(args.repo) if args.repo else None,
            target=args.target,
            max_depth=args.max_depth,
        )
        if args.output:
            written = write_impact_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_impact_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "contract":
        payload = build_regression_contract(
            Path(args.bundle),
            repo_path=Path(args.repo) if args.repo else None,
            max_depth=args.max_depth,
        )
        if args.output:
            written = write_contract_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_contract_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "verify-contract":
        payload = verify_regression_contract(
            Path(args.contract),
            repo_path=Path(args.repo) if args.repo else None,
        )
        if args.output:
            written = write_contract_verification_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_contract_verification_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "pr-guard":
        changed_files = _changed_files_from_args(args.changed_files, args.changed_files_file)
        payload = guard_pr_with_contract(
            Path(args.contract),
            changed_files=changed_files,
            repo_path=Path(args.repo) if args.repo else None,
            fail_on=args.fail_on,
        )
        if args.output:
            written = write_pr_guard_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.sarif_output:
            sarif_written = write_pr_guard_sarif(payload, Path(args.sarif_output))
            payload["sarif_output_path"] = str(sarif_written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_pr_guard_markdown(payload))
            if args.github_annotations:
                for annotation in payload.get("github_annotations", []):
                    print(annotation)
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        if payload.get("exit_code"):
            sys.exit(int(payload["exit_code"]))
        return

    if args.command == "temporal-proof-regression":
        payload = run_temporal_proof_regression(
            Path(args.contract),
            git_repo_path=Path(args.git_repo) if args.git_repo else None,
            repo_subdir=args.repo_subdir,
            rev_range=args.rev_range,
            max_commits=args.max_commits,
        )
        if args.output:
            written = write_temporal_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_temporal_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "temporal-repair-benchmark":
        payload = run_temporal_repair_benchmark(
            runtime,
            output_dir=Path(args.output_dir),
            top_k=clamp_top_k(args.top_k, runtime.config),
        )
        if args.output:
            written = write_temporal_benchmark_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_temporal_benchmark_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "temporal-repair-scorecard":
        payload = build_temporal_repair_scorecard(
            Path(args.benchmark),
            min_successor_top1=args.min_successor_top1,
            min_abstention=args.min_abstention,
            min_delta_rate=args.min_delta_rate,
            min_migration_rate=args.min_migration_rate,
        )
        if args.output:
            written = write_temporal_scorecard_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.sarif_output:
            sarif_written = write_temporal_scorecard_sarif(payload, Path(args.sarif_output))
            payload["sarif_output_path"] = str(sarif_written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_temporal_scorecard_markdown(payload))
            if args.github_annotations:
                for annotation in payload.get("github_annotations", []):
                    print(annotation)
            if args.output:
                print(f"\nReport: {payload['output_path']}")
            if args.sarif_output:
                print(f"SARIF: {payload['sarif_output_path']}")
        if args.fail_on_fail and payload.get("status") == "fail":
            sys.exit(1)
        return

    if args.command == "release-pack":
        payload = build_release_pack(
            runtime,
            output_dir=Path(args.output_dir),
            top_k=clamp_top_k(args.top_k, runtime.config),
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_release_pack_markdown(payload))
            print(f"\nManifest: {payload['manifest_path']}")
        return

    if args.command == "verify-release-pack":
        payload = verify_release_pack(Path(args.manifest))
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_release_pack_verification_markdown(payload))
        return

    if args.command == "agent-frontier":
        payload = build_agent_reliability_frontier(Path(args.manifest))
        if args.output:
            written = write_agent_frontier_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_agent_frontier_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "agent-frontier-ablate":
        payload = build_agent_frontier_ablation(Path(args.manifest))
        if args.output:
            written = write_agent_frontier_ablation_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_agent_frontier_ablation_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "agent-frontier-interactions":
        payload = build_agent_frontier_interactions(Path(args.manifest))
        if args.output:
            written = write_agent_frontier_interactions_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_agent_frontier_interactions_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "agent-frontier-stability":
        payload = build_agent_frontier_stability(
            Path(args.manifest),
            samples=args.samples,
            noise=args.noise,
            seed=args.seed,
        )
        if args.output:
            written = write_agent_frontier_stability_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_agent_frontier_stability_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "agent-artifact-review":
        payload = build_agent_artifact_review(Path(args.manifest))
        if args.output:
            written = write_agent_artifact_review_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_agent_artifact_review_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "artifact-provenance":
        payload = build_artifact_provenance(Path(args.manifest))
        if args.output:
            written = write_artifact_provenance_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_artifact_provenance_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "verify-artifact-provenance":
        payload = verify_artifact_provenance(
            Path(args.provenance),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        if args.output:
            written = write_artifact_provenance_verification_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_artifact_provenance_verification_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "engineer":
        result, _repo_index = runtime.engineer(
            repo_path=args.repo,
            task=args.task,
            max_steps=args.max_steps,
            execution_mode=args.execution_mode,
            force_rebuild=args.force_rebuild,
        )
        _print_engineering_result(result, json_output=args.json)
        return

    if args.command == "resume":
        result, _repo_index = runtime.resume_engineering_run(args.run_id, max_steps=args.max_steps)
        _print_engineering_result(result, json_output=args.json)
        return

    if args.command == "runs":
        runs = runtime.list_engineering_runs(limit=args.limit)
        if args.json:
            print(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
            return
        for item in runs:
            print(f"- {item.get('run_id')} | {item.get('status')} | {item.get('task')}")
        return

    if args.command == "coordination":
        payload = build_coordination_status(project_root, stale_minutes=args.stale_minutes)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_coordination_markdown(payload))
        return

    if args.command == "apply-run":
        result = runtime.apply_engineering_run(args.run_id, confirm=args.confirm)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        print(f"Applied run {result.get('run_id')} to {result.get('source_repo_root')}")
        for relpath in result.get("applied_files", []):
            print(f"- {relpath}")
        return

    if args.command == "bench":
        result = run_engineering_benchmark(runtime, Path(args.cases), max_steps=args.max_steps)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        runnable = result.get("runnable_count", result["case_count"])
        skipped = result.get("skipped_count", 0)
        print(
            f"Engineering benchmark: {result['case_count']} cases, "
            f"{runnable} runnable, {skipped} skipped, pass rate {result['pass_rate']:.2%}"
        )
        for item in result["cases"]:
            status = "SKIP" if item.get("skipped") else ("PASS" if item["passed"] else "FAIL")
            print(f"- [{status}] {item['name']} -> {item['status']} ({item['run_id']})")
        return

    if args.command == "serve":
        serve(project_root=project_root, host=args.host, port=args.port)
        return

    if args.command == "eval":
        run_eval(
            runtime,
            Path(args.cases),
            top_k=clamp_top_k(args.top_k, runtime.config),
            json_output=args.json,
            output_path=Path(args.output) if args.output else None,
        )
        return

    if args.command == "ablate":
        run_ablation(
            runtime,
            Path(args.cases),
            top_k=clamp_top_k(args.top_k, runtime.config),
            json_output=args.json,
            output_path=Path(args.output) if args.output else None,
        )
        return

    if args.command == "counterfactual":
        run_counterfactual(
            runtime,
            Path(args.cases),
            top_k=clamp_top_k(args.top_k, runtime.config),
            json_output=args.json,
            output_path=Path(args.output) if args.output else None,
        )
        return

    if args.command == "benchmark-adapter":
        suite_path = Path(args.suite)
        if args.emit_template:
            payload = build_benchmark_adapter_template()
            written = write_benchmark_adapter_output(payload, suite_path)
            payload["output_path"] = str(written)
        else:
            payload = run_benchmark_adapter(runtime, suite_path, top_k=clamp_top_k(args.top_k, runtime.config))
            if args.output:
                written = write_benchmark_adapter_output(payload, Path(args.output))
                payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_adapter_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-diagnose":
        payload = diagnose_benchmark_adapter(
            Path(args.benchmark),
            min_top1=args.min_top1,
            min_top3=args.min_top3,
        )
        if args.output:
            written = write_benchmark_diagnostics_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_diagnostics_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-experiment-report":
        payload = build_benchmark_experiment_report(
            Path(args.benchmark),
            diagnostics_path=Path(args.diagnostics) if args.diagnostics else None,
            repair_card_path=Path(args.repair_card) if args.repair_card else None,
            repair_synthesis_path=Path(args.repair_synthesis) if args.repair_synthesis else None,
        )
        if args.output:
            written = write_benchmark_experiment_report_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_experiment_report_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-repair-card":
        payload = build_benchmark_repair_card(Path(args.benchmark))
        if args.output:
            written = write_benchmark_repair_card_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_repair_card_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-repair-synthesize":
        payload = synthesize_benchmark_repair_rules(Path(args.benchmark))
        if args.output:
            written = write_benchmark_repair_synthesis_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_repair_synthesis_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-repair-verify-implementation":
        payload = verify_benchmark_repair_implementation(Path(args.synthesis), source_path=Path(args.source))
        if args.output:
            written = write_benchmark_repair_implementation_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_repair_implementation_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-repair-compile":
        payload = compile_benchmark_repair_interventions(
            Path(args.synthesis),
            implementation_path=Path(args.implementation) if args.implementation else None,
            source_path=Path(args.source),
        )
        if args.output:
            written = write_benchmark_repair_compiler_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_repair_compiler_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "benchmark-repair-workbench":
        payload = build_benchmark_repair_workbench(Path(args.compiler), source_path=Path(args.source))
        if args.output:
            written = write_benchmark_repair_workbench_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_benchmark_repair_workbench_markdown(payload))
            if payload.get("output_path"):
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack":
        payload = run_proof_attack_benchmark(
            runtime,
            output_dir=Path(args.output_dir),
            top_k=clamp_top_k(args.top_k, runtime.config),
            spec_path=Path(args.spec) if args.spec else None,
        )
        if args.output:
            written = write_proof_attack_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-leaderboard":
        payload = build_proof_attack_leaderboard(Path(args.benchmark))
        if args.output:
            written = write_proof_attack_leaderboard_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_leaderboard_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-triage":
        payload = build_proof_attack_triage(
            Path(args.benchmark),
            leaderboard_path=Path(args.leaderboard) if args.leaderboard else None,
        )
        if args.output:
            written = write_proof_attack_triage_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_triage_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-policy":
        payload = synthesize_proof_attack_policy(
            Path(args.benchmark),
            leaderboard_path=Path(args.leaderboard) if args.leaderboard else None,
            triage_path=Path(args.triage) if args.triage else None,
        )
        if args.output:
            written = write_proof_attack_policy_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_policy_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-adaptive":
        payload = run_adaptive_proof_attack_curriculum(
            runtime,
            baseline_benchmark_path=Path(args.benchmark),
            policy_path=Path(args.policy),
            output_dir=Path(args.output_dir),
            top_k=clamp_top_k(args.top_k, runtime.config),
        )
        if args.output:
            written = write_adaptive_proof_attack_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_adaptive_proof_attack_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-repair":
        payload = synthesize_adaptive_policy_repair(
            policy_path=Path(args.policy),
            adaptive_path=Path(args.adaptive),
        )
        if args.output:
            written = write_adaptive_policy_repair_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_adaptive_policy_repair_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-certificate":
        payload = build_proof_attack_minimax_certificate(
            benchmark_path=Path(args.benchmark),
            policy_path=Path(args.policy),
            adaptive_path=Path(args.adaptive),
            repair_path=Path(args.repair),
        )
        if args.output:
            written = write_proof_attack_minimax_certificate_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_minimax_certificate_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return

    if args.command == "proof-attack-scorecard":
        payload = build_proof_attack_scorecard(
            Path(args.benchmark),
            min_attack_resistance=args.min_attack_resistance,
            min_mitigated_decoys=args.min_mitigated_decoys,
            min_mitigation_signals=args.min_mitigation_signals,
            min_proof_proved=args.min_proof_proved,
        )
        if args.output:
            written = write_proof_attack_scorecard_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.sarif_output:
            sarif_written = write_proof_attack_scorecard_sarif(payload, Path(args.sarif_output))
            payload["sarif_output_path"] = str(sarif_written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_scorecard_markdown(payload))
            if args.github_annotations:
                for annotation in payload.get("github_annotations", []):
                    print(annotation)
            if args.output:
                print(f"\nReport: {payload['output_path']}")
            if args.sarif_output:
                print(f"SARIF: {payload['sarif_output_path']}")
        if args.fail_on_fail and payload.get("status") == "fail":
            sys.exit(1)
        return

    if args.command == "proof-attack-cegar":
        payload = run_proof_attack_cegar(
            runtime,
            output_dir=Path(args.output_dir),
            top_k=clamp_top_k(args.top_k, runtime.config),
            spec_path=Path(args.spec) if args.spec else None,
        )
        if args.output:
            written = write_proof_attack_cegar_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_proof_attack_cegar_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        if args.fail_on_blocker and payload.get("status") == "blocked":
            sys.exit(1)
        return

    if args.command == "agent-court":
        payload = build_agent_court(
            Path(args.bundle),
            repo_path=Path(args.repo) if args.repo else None,
            proof_scorecard_path=Path(args.proof_scorecard) if args.proof_scorecard else None,
            attack_scorecard_path=Path(args.attack_scorecard) if args.attack_scorecard else None,
            temporal_scorecard_path=Path(args.temporal_scorecard) if args.temporal_scorecard else None,
            strict=not args.no_strict,
        )
        if args.output:
            written = write_agent_court_output(payload, Path(args.output))
            payload["output_path"] = str(written)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_agent_court_markdown(payload))
            if args.output:
                print(f"\nReport: {payload['output_path']}")
        return


def run_eval(
    runtime: RepoAgentRuntime,
    cases_path: Path,
    top_k: int = 6,
    json_output: bool = False,
    output_path: Path | None = None,
) -> None:
    payload = evaluate_cases(runtime, cases_path, top_k=top_k)
    metrics = payload["metrics"]
    records = payload["cases"]

    if output_path is not None:
        written = write_eval_output(payload, output_path)
        payload["output_path"] = str(written)

    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    for record in records:
        ok = record["passed_top3"]
        rank_text = record["rank"] if record["rank"] is not None else "miss"
        confidence = record.get("confidence_label", "unknown")
        print(f"[{'PASS' if ok else 'FAIL'}] {record['question']}")
        print(f"  rank: {rank_text}")
        print(f"  hit: {record['top_hit'] or '<none>'}")
        print(f"  confidence: {confidence} ({record.get('confidence', 0):.2f})")
        if record["top_hits"]:
            print(f"  top3: {', '.join(record['top_hits'])}")

    passed_top3 = sum(1 for record in records if record["passed_top3"])
    print(f"\nSummary: {passed_top3}/{len(records)} passed @top3")
    print(f"Top-1 accuracy: {metrics['top1_accuracy']:.2%}")
    print(f"Top-3 accuracy: {metrics['top3_accuracy']:.2%}")
    print(f"MRR: {metrics['mrr']:.3f}")
    if output_path is not None:
        print(f"Report: {payload['output_path']}")


def evaluate_cases(runtime: RepoAgentRuntime, cases_path: Path, top_k: int = 6) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    records = []
    for case in cases:
        result, _repo_index = runtime.ask(
            repo_path=(cases_path.parent / case["repo"]).resolve(),
            question=case["question"],
            top_k=top_k,
            use_model=False,
            force_rebuild=True,
        )
        top_hit = result.hits[0] if result.hits else None
        rank = _case_match_rank(case, result.hits)
        diagnostics = result.diagnostics
        records.append(
            {
                "question": case["question"],
                "repo": str((cases_path.parent / case["repo"]).resolve()),
                "expected_path": case["expected_path"],
                "expected_symbol_contains": case.get("expected_symbol_contains", ""),
                "rank": rank,
                "top_hit": top_hit.chunk.source_label if top_hit else "",
                "top_hits": [hit.chunk.source_label for hit in result.hits[:top_k]],
                "passed_top1": rank == 1,
                "passed_top3": rank is not None and rank <= 3,
                "confidence": diagnostics.confidence if diagnostics else 0.0,
                "confidence_label": diagnostics.label if diagnostics else "unknown",
                "warnings": diagnostics.warnings if diagnostics else [],
            }
        )

    total = max(len(records), 1)
    metrics = {
        "case_count": len(records),
        "top_k": top_k,
        "top1_accuracy": sum(1 for record in records if record["passed_top1"]) / total,
        "top3_accuracy": sum(1 for record in records if record["passed_top3"]) / total,
        "mrr": sum((1 / record["rank"]) if record["rank"] else 0 for record in records) / total,
        "average_confidence": sum(record["confidence"] for record in records) / total,
    }
    return {"metrics": metrics, "cases": records}


TEMPORAL_REPAIR_CASES = [
    {
        "id": "same_file_experimental_rename",
        "description": "Target writer is renamed in place and the public stream caller is updated.",
        "expected_successor": "server.js:writeExperimentalChatDelta",
        "mutation": "rename_experimental",
    },
    {
        "id": "same_file_flush_rename",
        "description": "Target writer is renamed to a flush-style public writer in the same file.",
        "expected_successor": "server.js:flushPublicChatDelta",
        "mutation": "rename_flush",
    },
    {
        "id": "cross_file_writer_move",
        "description": "Target writer moves to a new file while the public route path relinks to it.",
        "expected_successor": "writer.js:writePublicChatDelta",
        "mutation": "move_writer_file",
    },
    {
        "id": "no_successor_writer_removed",
        "description": "Target writer is removed and the public route no longer relinks to a semantic successor.",
        "expected_successor": "",
        "expected_abstain": True,
        "mutation": "delete_writer_no_successor",
    },
]


def run_temporal_repair_benchmark(
    runtime: RepoAgentRuntime,
    *,
    output_dir: Path,
    top_k: int = 6,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    _allow_generated_root(runtime, output_dir)
    project_root = runtime.project_root
    source_repo = project_root / "examples" / "counterfactual_agent_app"
    workspace_key = hashlib.sha256(str(output_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    work_root = project_root / "test-workspaces" / f"_temporal-repair-benchmark-{workspace_key}"
    if work_root.exists():
        _remove_tree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    records = []
    for case in TEMPORAL_REPAIR_CASES:
        case_dir = output_dir / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        repo_dir = _prepare_temporal_benchmark_repo(source_repo, work_root / case["id"], case)
        _bundle, bundle_path = runtime.generate_bundle(
            repo_path=repo_dir,
            question=PROOF_DEMO_QUESTION,
            target="generic",
            fmt="json",
            top_k=top_k,
            use_model=False,
            force_rebuild=True,
            output_path=case_dir / "proof.bundle.json",
        )
        contract_payload = build_regression_contract(bundle_path, repo_path=repo_dir)
        contract_path = write_contract_output(contract_payload, case_dir / "proof-contract.json")
        _apply_temporal_benchmark_mutation(repo_dir, case)
        _git_commit_all(repo_dir, f"break proof via {case['id']}")
        temporal_payload = run_temporal_proof_regression(
            contract_path,
            git_repo_path=repo_dir,
            repo_subdir="",
            rev_range="HEAD",
            max_commits=10,
        )
        write_temporal_output(temporal_payload, case_dir / "temporal-proof-regression.md")
        write_temporal_output(temporal_payload, case_dir / "temporal-proof-regression.json")
        repair = temporal_payload.get("proof_repair") or {}
        top_candidate = (repair.get("top_candidate") or {}).get("label", "")
        expected_successor = str(case.get("expected_successor", ""))
        expected_abstain = bool(case.get("expected_abstain", False))
        abstained = not top_candidate
        graph_delta = repair.get("proof_graph_delta") or {}
        migration = repair.get("contract_migration_plan") or {}
        records.append(
            {
                "id": case["id"],
                "description": case["description"],
                "expected_successor": expected_successor,
                "expected_abstain": expected_abstain,
                "top_candidate": top_candidate,
                "successor_top1": (top_candidate == expected_successor) if expected_successor else False,
                "abstained": abstained,
                "abstention_correct": abstained if expected_abstain else True,
                "false_repair": bool(expected_abstain and top_candidate),
                "temporal_status": temporal_payload.get("status", ""),
                "graph_delta_status": graph_delta.get("status", ""),
                "migration_status": migration.get("status", ""),
                "patch_ops": len(migration.get("json_patch", [])),
                "report_path": str(case_dir / "temporal-proof-regression.md"),
            }
        )
    _remove_tree(work_root)

    positive_records = [item for item in records if item.get("expected_successor")]
    negative_records = [item for item in records if item.get("expected_abstain")]
    positive_total = max(len(positive_records), 1)
    negative_total = max(len(negative_records), 1)
    metrics = {
        "case_count": len(records),
        "positive_case_count": len(positive_records),
        "negative_control_count": len(negative_records),
        "successor_top1_accuracy": sum(1 for item in positive_records if item["successor_top1"]) / positive_total,
        "abstention_accuracy": sum(1 for item in negative_records if item["abstention_correct"]) / negative_total,
        "false_repair_rate": sum(1 for item in negative_records if item["false_repair"]) / negative_total,
        "causal_delta_rate": sum(1 for item in positive_records if item["graph_delta_status"] == "causal_relink_found") / positive_total,
        "migration_ready_rate": sum(1 for item in positive_records if item["migration_status"] == "ready_for_review") / positive_total,
        "average_patch_ops": sum(int(item["patch_ops"]) for item in positive_records) / positive_total,
    }
    return {
        "schema_version": "1.0",
        "strategy": "temporal_repair_benchmark",
        "output_dir": str(output_dir),
        "metrics": metrics,
        "cases": records,
    }


def render_temporal_benchmark_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Temporal Repair Benchmark",
        "",
        f"- Cases: `{int(metrics.get('case_count', 0))}`",
        f"- Positive cases: `{int(metrics.get('positive_case_count', 0))}`",
        f"- Negative controls: `{int(metrics.get('negative_control_count', 0))}`",
        f"- Successor@1: `{float(metrics.get('successor_top1_accuracy', 0.0)):.2%}`",
        f"- Abstention accuracy: `{float(metrics.get('abstention_accuracy', 0.0)):.2%}`",
        f"- False repair rate: `{float(metrics.get('false_repair_rate', 0.0)):.2%}`",
        f"- Causal graph delta rate: `{float(metrics.get('causal_delta_rate', 0.0)):.2%}`",
        f"- Migration ready rate: `{float(metrics.get('migration_ready_rate', 0.0)):.2%}`",
        f"- Average patch ops: `{float(metrics.get('average_patch_ops', 0.0)):.1f}`",
        "",
        "| Case | Expected | Top Candidate | Result | Delta | Migration |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in payload.get("cases", []):
        ok = "PASS" if (record.get("successor_top1") or record.get("abstention_correct")) else "FAIL"
        expected = record.get("expected_successor", "") or "ABSTAIN"
        top = record.get("top_candidate", "") or "ABSTAIN"
        lines.append(
            f"| `{record.get('id', '')}` | `{expected}` | "
            f"`{top}` | `{ok}` | "
            f"`{record.get('graph_delta_status', '')}` | `{record.get('migration_status', '')}` |"
        )
    lines.extend(["", "## Case Reports", ""])
    for record in payload.get("cases", []):
        lines.append(f"- `{record.get('id', '')}`: `{record.get('report_path', '')}`")
    lines.append("")
    return "\n".join(lines)


def write_temporal_benchmark_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_temporal_benchmark_markdown(payload), encoding="utf-8")
    return output_path


def build_temporal_repair_scorecard(
    benchmark_path: Path,
    *,
    min_successor_top1: float = 1.0,
    min_abstention: float = 1.0,
    min_delta_rate: float = 1.0,
    min_migration_rate: float = 1.0,
) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    metrics = dict(benchmark.get("metrics") or {})
    successor = float(metrics.get("successor_top1_accuracy", 0.0))
    abstention = float(metrics.get("abstention_accuracy", 0.0))
    delta = float(metrics.get("causal_delta_rate", 0.0))
    migration = float(metrics.get("migration_ready_rate", 0.0))
    items = [
        {
            "id": "successor_top1",
            "weight": 30,
            "value": successor,
            "threshold": min_successor_top1,
            "passed": successor >= min_successor_top1,
        },
        {
            "id": "negative_control_abstention",
            "weight": 25,
            "value": abstention,
            "threshold": min_abstention,
            "passed": abstention >= min_abstention,
        },
        {
            "id": "causal_graph_delta",
            "weight": 25,
            "value": delta,
            "threshold": min_delta_rate,
            "passed": delta >= min_delta_rate,
        },
        {
            "id": "migration_ready",
            "weight": 20,
            "value": migration,
            "threshold": min_migration_rate,
            "passed": migration >= min_migration_rate,
        },
    ]
    score = sum(item["weight"] for item in items if item["passed"])
    grade = _temporal_repair_grade(score)
    passed = all(item["passed"] for item in items)
    payload = {
        "schema_version": "1.0",
        "strategy": "temporal_repair_scorecard",
        "benchmark": str(benchmark_path),
        "status": "pass" if passed else "fail",
        "score": score,
        "grade": grade,
        "case_count": int(metrics.get("case_count", 0)),
        "items": items,
        "metrics": metrics,
        "failed_cases": [item for item in benchmark.get("cases", []) if _temporal_benchmark_case_failed(item)],
    }
    payload["github_annotations"] = _temporal_scorecard_github_annotations(payload)
    return payload


def render_temporal_scorecard_markdown(payload: dict) -> str:
    lines = [
        "# Repo Agent Temporal Repair Scorecard",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Benchmark: `{payload.get('benchmark', '')}`",
        f"- Cases: `{int(payload.get('case_count', 0))}`",
        "",
        "| Item | Value | Threshold | Result | Weight |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for item in payload.get("items", []):
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(
            f"| `{item.get('id', '')}` | `{float(item.get('value', 0.0)):.2%}` | "
            f"`{float(item.get('threshold', 0.0)):.2%}` | `{result}` | {int(item.get('weight', 0))} |"
        )
    failed_cases = list(payload.get("failed_cases") or [])
    if failed_cases:
        lines.extend(["", "## Failed Cases", "", "| Case | Top Candidate | Delta | Migration |", "| --- | --- | --- | --- |"])
        for case in failed_cases:
            lines.append(
                f"| `{case.get('id', '')}` | `{case.get('top_candidate', '')}` | "
                f"`{case.get('graph_delta_status', '')}` | `{case.get('migration_status', '')}` |"
            )
    lines.append("")
    return "\n".join(lines)


def write_temporal_scorecard_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_temporal_scorecard_markdown(payload), encoding="utf-8")
    return output_path


def render_temporal_scorecard_sarif(payload: dict) -> dict:
    benchmark_uri = _temporal_scorecard_sarif_uri(str(payload.get("benchmark", "")))
    results = []
    for item in payload.get("items", []):
        if item.get("passed"):
            continue
        item_id = str(item.get("id", "temporal_scorecard_item"))
        value = float(item.get("value", 0.0))
        threshold = float(item.get("threshold", 0.0))
        results.append(
            {
                "ruleId": "repo-agent/temporal-repair-threshold-failed",
                "level": "error",
                "message": {
                    "text": f"Temporal repair scorecard item {item_id} is {value:.2%}, below threshold {threshold:.2%}."
                },
                "locations": [_temporal_scorecard_sarif_location(benchmark_uri)],
                "properties": {
                    "scorecardItem": item_id,
                    "value": value,
                    "threshold": threshold,
                    "weight": int(item.get("weight", 0)),
                    "score": payload.get("score", 0),
                    "grade": payload.get("grade", ""),
                },
            }
        )
    for case in payload.get("failed_cases", []):
        results.append(
            {
                "ruleId": "repo-agent/temporal-repair-case-failed",
                "level": "error",
                "message": {"text": _temporal_scorecard_case_summary(case)},
                "locations": [_temporal_scorecard_sarif_location(benchmark_uri)],
                "properties": {
                    "caseId": case.get("id", ""),
                    "expectedAbstain": bool(case.get("expected_abstain")),
                    "topCandidate": case.get("top_candidate", ""),
                    "graphDeltaStatus": case.get("graph_delta_status", ""),
                    "migrationStatus": case.get("migration_status", ""),
                    "falseRepair": bool(case.get("false_repair")),
                },
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Repo Agent Temporal Repair Scorecard",
                        "informationUri": "https://github.com/",
                        "rules": [
                            {
                                "id": "repo-agent/temporal-repair-threshold-failed",
                                "name": "Temporal repair scorecard threshold failed",
                                "shortDescription": {"text": "A temporal repair scorecard metric is below its release threshold."},
                                "fullDescription": {
                                    "text": "Repo Agent evaluated temporal repair benchmark metrics and found a threshold miss that should block release."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                            {
                                "id": "repo-agent/temporal-repair-case-failed",
                                "name": "Temporal repair benchmark case failed",
                                "shortDescription": {"text": "A temporal repair benchmark case failed its expected behavior."},
                                "fullDescription": {
                                    "text": "Repo Agent found a benchmark case where successor inference, abstention, graph delta, or migration readiness did not meet expectations."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                        ],
                    }
                },
                "results": results,
                "properties": {
                    "status": payload.get("status", ""),
                    "score": payload.get("score", 0),
                    "grade": payload.get("grade", ""),
                    "benchmark": payload.get("benchmark", ""),
                },
            }
        ],
    }


def write_temporal_scorecard_sarif(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(render_temporal_scorecard_sarif(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _temporal_scorecard_github_annotations(payload: dict) -> list[str]:
    if payload.get("status") == "pass":
        score = int(payload.get("score", 0))
        grade = _escape_github_annotation(str(payload.get("grade", "")))
        return [f"::notice title=Repo Agent temporal repair scorecard::pass {score}/100 grade {grade}"]
    annotations = []
    for item in payload.get("items", []):
        if item.get("passed"):
            continue
        item_id = _escape_github_annotation(str(item.get("id", "")))
        value = float(item.get("value", 0.0))
        threshold = float(item.get("threshold", 0.0))
        annotations.append(
            f"::error title=Repo Agent temporal repair threshold failed::{item_id} is {value:.2%}, below {threshold:.2%}"
        )
    for case in payload.get("failed_cases", []):
        summary = _escape_github_annotation(_temporal_scorecard_case_summary(case))
        annotations.append(f"::error title=Repo Agent temporal repair case failed::{summary}")
    return annotations


def _temporal_scorecard_case_summary(case: dict) -> str:
    case_id = str(case.get("id", "unknown_case"))
    if case.get("expected_abstain"):
        candidate = str(case.get("top_candidate", "") or "no candidate")
        return f"{case_id}: expected abstention, got {candidate}"
    reasons = []
    if not bool(case.get("successor_top1")):
        reasons.append(f"successor@1 miss ({case.get('top_candidate', '')})")
    if case.get("graph_delta_status") != "causal_relink_found":
        reasons.append(f"delta {case.get('graph_delta_status', '')}")
    if case.get("migration_status") != "ready_for_review":
        reasons.append(f"migration {case.get('migration_status', '')}")
    return f"{case_id}: " + "; ".join(reason for reason in reasons if reason) if reasons else f"{case_id}: failed"


def _escape_github_annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")


def _temporal_scorecard_sarif_uri(uri: str) -> str:
    normalized = uri.replace("\\", "/")
    return normalized or "temporal-repair-benchmark.json"


def _temporal_scorecard_sarif_location(uri: str) -> dict:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": uri},
            "region": {"startLine": 1},
        }
    }


def _temporal_repair_grade(score: int) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    return "D"


def _temporal_benchmark_case_failed(case: dict) -> bool:
    if case.get("expected_abstain"):
        return not bool(case.get("abstention_correct"))
    return (
        not bool(case.get("successor_top1"))
        or case.get("graph_delta_status") != "causal_relink_found"
        or case.get("migration_status") != "ready_for_review"
    )


def _prepare_temporal_benchmark_repo(source_repo: Path, case_dir: Path, case: dict) -> Path:
    if case_dir.exists():
        _remove_tree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = case_dir / "repo"
    repo_dir.mkdir()
    (repo_dir / "server.js").write_text((source_repo / "server.js").read_text(encoding="utf-8"), encoding="utf-8")
    _git(repo_dir, ["init"])
    _git(repo_dir, ["config", "user.email", "repo-agent@example.local"])
    _git(repo_dir, ["config", "user.name", "Repo Agent"])
    _git(repo_dir, ["add", "server.js"])
    _git(repo_dir, ["commit", "-m", "preserve proved public chat writer"])
    return repo_dir


def _apply_temporal_benchmark_mutation(repo_dir: Path, case: dict) -> None:
    mutation = str(case.get("mutation", ""))
    server_path = repo_dir / "server.js"
    text = server_path.read_text(encoding="utf-8")
    original_text = text
    if mutation == "rename_experimental":
        text = text.replace("writeChatDelta", "writeExperimentalChatDelta")
    elif mutation == "rename_flush":
        text = text.replace("writeChatDelta", "flushPublicChatDelta")
    elif mutation == "move_writer_file":
        old_function = """function writeChatDelta(res, envelope) {
  res.setHeader('content-type', 'text/event-stream');
  res.write(`event: ${envelope.event}\\n`);
  res.write(`data: ${JSON.stringify(envelope.payload)}\\n\\n`);
  res.end();
}

"""
        new_function = """function writePublicChatDelta(res, envelope) {
  res.setHeader('content-type', 'text/event-stream');
  res.write(`event: ${envelope.event}\\n`);
  res.write(`data: ${JSON.stringify(envelope.payload)}\\n\\n`);
  res.end();
}
"""
        text = text.replace("writeChatDelta(res, prepared)", "writePublicChatDelta(res, prepared)")
        text = text.replace(old_function, "")
        text = text.replace("  writeChatDelta,\n", "")
        (repo_dir / "writer.js").write_text(new_function, encoding="utf-8")
    elif mutation == "delete_writer_no_successor":
        old_function = """function writeChatDelta(res, envelope) {
  res.setHeader('content-type', 'text/event-stream');
  res.write(`event: ${envelope.event}\\n`);
  res.write(`data: ${JSON.stringify(envelope.payload)}\\n\\n`);
  res.end();
}

"""
        text = text.replace("  const prepared = preparePublicStreamEnvelope(turn);\n  return writeChatDelta(res, prepared);", "  preparePublicStreamEnvelope(turn);\n  res.statusCode = 204;\n  return res.end();")
        text = text.replace(old_function, "")
        text = text.replace("  writeChatDelta,\n", "")
    else:
        raise ValueError(f"unknown temporal benchmark mutation: {mutation}")
    if text == original_text:
        raise ValueError(f"temporal benchmark mutation produced no change: {mutation}")
    server_path.write_text(text, encoding="utf-8")


def _git_commit_all(repo_dir: Path, message: str) -> None:
    _git(repo_dir, ["add", "."])
    if not _git_has_staged_changes(repo_dir):
        raise ValueError(f"cannot commit temporal benchmark case with no staged changes: {message}")
    _git(repo_dir, ["commit", "-m", message])


def _git_has_staged_changes(repo_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--cached", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode == 1


def _git(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _make_writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return
    writable_mode = mode | stat.S_IWRITE | stat.S_IREAD
    if path.is_dir():
        writable_mode |= stat.S_IEXEC
    try:
        path.chmod(writable_mode)
    except FileNotFoundError:
        return


def _make_tree_writable(path: Path) -> None:
    if not path.exists():
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            _make_writable(Path(root) / name)
        for name in dirs:
            _make_writable(Path(root) / name)
    _make_writable(path)


def _remove_tree(path: Path, *, attempts: int = 8, delay_seconds: float = 0.08) -> None:
    def _make_writable_and_retry(func, raw_path: str, _exc_info) -> None:
        target = Path(raw_path)
        _make_writable(target)
        last_error: OSError | None = None
        for attempt in range(max(1, attempts)):
            try:
                func(raw_path)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise
                time.sleep(delay_seconds * (attempt + 1))
        if last_error is not None:
            raise last_error

    if not path.exists():
        return
    last_error: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            _make_tree_writable(path)
            shutil.rmtree(path, onerror=_make_writable_and_retry)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            time.sleep(delay_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error


def _allow_generated_root(runtime: RepoAgentRuntime, root: Path) -> None:
    resolved = root.expanduser().resolve()
    for allowed in runtime.config.allowed_roots:
        allowed_root = allowed.resolve()
        if resolved == allowed_root or allowed_root in resolved.parents:
            return
    runtime.config.allowed_roots = (*runtime.config.allowed_roots, resolved)


def build_release_pack(runtime: RepoAgentRuntime, *, output_dir: Path, top_k: int = 6) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    _allow_generated_root(runtime, output_dir)
    project_root = runtime.project_root
    proof_repo = project_root / "examples" / "counterfactual_agent_app"
    proof_question = PROOF_DEMO_QUESTION
    artifacts: list[dict] = []

    ablation_payload = evaluate_ablation(runtime, project_root / "repo_agent" / "eval_cases.json", top_k=top_k)
    ablation_path = write_ablation_output(ablation_payload, output_dir / "ablation-report.md")
    artifacts.append(_artifact("ablation_report", ablation_path, "Retrieval ablation across lexical, semantic, hybrid, and graph-MCTS strategies."))

    counterfactual_payload = evaluate_counterfactual(runtime, project_root / "repo_agent" / "counterfactual_cases.json", top_k=top_k)
    counterfactual_path = write_counterfactual_output(counterfactual_payload, output_dir / "counterfactual-report.md")
    artifacts.append(_artifact("counterfactual_report", counterfactual_path, "Hard-negative benchmark with public/admin/legacy decoys."))

    benchmark_adapter_payload = run_benchmark_adapter(runtime, project_root / "repo_agent" / "benchmark_adapter_suite.json", top_k=top_k)
    benchmark_adapter_json_path = write_benchmark_adapter_output(benchmark_adapter_payload, output_dir / "benchmark-adapter.json")
    artifacts.append(_artifact("benchmark_adapter_json", benchmark_adapter_json_path, "Machine-readable portable benchmark adapter results."))
    benchmark_adapter_path = write_benchmark_adapter_output(benchmark_adapter_payload, output_dir / "benchmark-adapter.md")
    artifacts.append(_artifact("benchmark_adapter", benchmark_adapter_path, "Portable cross-repository benchmark adapter report."))
    benchmark_diagnostics_payload = diagnose_benchmark_adapter(benchmark_adapter_json_path)
    benchmark_diagnostics_json_path = write_benchmark_diagnostics_output(benchmark_diagnostics_payload, output_dir / "benchmark-diagnostics.json")
    artifacts.append(_artifact("benchmark_diagnostics_json", benchmark_diagnostics_json_path, "Machine-readable portable benchmark generalization diagnostics."))
    benchmark_diagnostics_path = write_benchmark_diagnostics_output(benchmark_diagnostics_payload, output_dir / "benchmark-diagnostics.md")
    artifacts.append(_artifact("benchmark_diagnostics", benchmark_diagnostics_path, "Counterfactual diagnosis of portable benchmark generalization gaps."))
    benchmark_repair_payload = build_benchmark_repair_card(benchmark_adapter_json_path)
    benchmark_repair_json_path = write_benchmark_repair_card_output(benchmark_repair_payload, output_dir / "benchmark-repair-card.json")
    artifacts.append(_artifact("benchmark_repair_json", benchmark_repair_json_path, "Machine-readable benchmark repair validation card."))
    benchmark_repair_path = write_benchmark_repair_card_output(benchmark_repair_payload, output_dir / "benchmark-repair-card.md")
    artifacts.append(_artifact("benchmark_repair", benchmark_repair_path, "Repair card proving portable benchmark weak cases were closed by explicit ranking guards."))
    benchmark_repair_synthesis_payload = synthesize_benchmark_repair_rules(benchmark_adapter_json_path)
    benchmark_repair_synthesis_json_path = write_benchmark_repair_synthesis_output(
        benchmark_repair_synthesis_payload,
        output_dir / "benchmark-repair-synthesis.json",
    )
    artifacts.append(_artifact("benchmark_repair_synthesis_json", benchmark_repair_synthesis_json_path, "Machine-readable counterexample-guided retrieval repair rule synthesis."))
    benchmark_repair_synthesis_path = write_benchmark_repair_synthesis_output(
        benchmark_repair_synthesis_payload,
        output_dir / "benchmark-repair-synthesis.md",
    )
    artifacts.append(_artifact("benchmark_repair_synthesis", benchmark_repair_synthesis_path, "Auditable synthesized retrieval-repair rules with projected and validated evidence."))
    benchmark_repair_implementation_payload = verify_benchmark_repair_implementation(
        benchmark_repair_synthesis_json_path,
        source_path=project_root / "repo_agent" / "indexer.py",
    )
    benchmark_repair_implementation_json_path = write_benchmark_repair_implementation_output(
        benchmark_repair_implementation_payload,
        output_dir / "benchmark-repair-implementation.json",
    )
    artifacts.append(_artifact("benchmark_repair_implementation_json", benchmark_repair_implementation_json_path, "Machine-readable verification that synthesized repair rules map to reranker code anchors."))
    benchmark_repair_implementation_path = write_benchmark_repair_implementation_output(
        benchmark_repair_implementation_payload,
        output_dir / "benchmark-repair-implementation.md",
    )
    artifacts.append(_artifact("benchmark_repair_implementation", benchmark_repair_implementation_path, "Reviewer-facing implementation certificate for synthesized retrieval-repair rules."))
    benchmark_repair_compiler_payload = compile_benchmark_repair_interventions(
        benchmark_repair_synthesis_json_path,
        implementation_path=benchmark_repair_implementation_json_path,
        source_path=project_root / "repo_agent" / "indexer.py",
    )
    benchmark_repair_compiler_json_path = write_benchmark_repair_compiler_output(
        benchmark_repair_compiler_payload,
        output_dir / "benchmark-repair-compiler.json",
    )
    artifacts.append(_artifact("benchmark_repair_compiler_json", benchmark_repair_compiler_json_path, "Machine-readable compiler IR for retrieval-repair interventions."))
    benchmark_repair_compiler_path = write_benchmark_repair_compiler_output(
        benchmark_repair_compiler_payload,
        output_dir / "benchmark-repair-compiler.md",
    )
    artifacts.append(_artifact("benchmark_repair_compiler", benchmark_repair_compiler_path, "Auditable source-level intervention and ablation plan for synthesized retrieval repairs."))
    benchmark_repair_workbench_payload = build_benchmark_repair_workbench(
        benchmark_repair_compiler_json_path,
        source_path=project_root / "repo_agent" / "indexer.py",
    )
    benchmark_repair_workbench_json_path = write_benchmark_repair_workbench_output(
        benchmark_repair_workbench_payload,
        output_dir / "benchmark-repair-workbench.json",
    )
    artifacts.append(_artifact("benchmark_repair_workbench_json", benchmark_repair_workbench_json_path, "Machine-readable patch and ablation workbench for compiled retrieval repairs."))
    benchmark_repair_workbench_path = write_benchmark_repair_workbench_output(
        benchmark_repair_workbench_payload,
        output_dir / "benchmark-repair-workbench.md",
    )
    artifacts.append(_artifact("benchmark_repair_workbench", benchmark_repair_workbench_path, "Reviewer-facing candidate patch, ablation, and validation matrix for retrieval repairs."))
    benchmark_experiment_payload = build_benchmark_experiment_report(
        benchmark_adapter_json_path,
        diagnostics_path=benchmark_diagnostics_json_path,
        repair_card_path=benchmark_repair_json_path,
        repair_synthesis_path=benchmark_repair_synthesis_json_path,
    )
    benchmark_experiment_json_path = write_benchmark_experiment_report_output(
        benchmark_experiment_payload,
        output_dir / "benchmark-experiment-report.json",
    )
    artifacts.append(_artifact("benchmark_experiment_json", benchmark_experiment_json_path, "Machine-readable paper-style benchmark experiment report."))
    benchmark_experiment_path = write_benchmark_experiment_report_output(
        benchmark_experiment_payload,
        output_dir / "benchmark-experiment-report.md",
    )
    artifacts.append(_artifact("benchmark_experiment", benchmark_experiment_path, "Paper-style external benchmark experiment report with metrics, taxonomy, claims, and falsifiers."))

    proof_attack_spec_source = project_root / "repo_agent" / "proof_attack_specs.json"
    proof_attack_spec_path = output_dir / "proof-attack-spec.json"
    shutil.copy2(proof_attack_spec_source, proof_attack_spec_path)
    artifacts.append(_artifact("proof_attack_spec", proof_attack_spec_path, "Declarative adversarial mutation spec for proof attack benchmark."))
    proof_attack_payload = run_proof_attack_benchmark(
        runtime,
        output_dir=output_dir / "proof-attack-benchmark",
        top_k=top_k,
        spec_path=proof_attack_spec_source,
    )
    proof_attack_json_path = write_proof_attack_output(proof_attack_payload, output_dir / "proof-attack-benchmark.json")
    artifacts.append(_artifact("proof_attack_benchmark_json", proof_attack_json_path, "Machine-readable adversarial proof attack benchmark results."))
    proof_attack_path = write_proof_attack_output(proof_attack_payload, output_dir / "proof-attack-benchmark.md")
    artifacts.append(_artifact("proof_attack_benchmark", proof_attack_path, "Adversarial repository mutation benchmark for proof-carrying retrieval."))
    proof_attack_leaderboard_payload = build_proof_attack_leaderboard(proof_attack_json_path)
    proof_attack_leaderboard_json_path = write_proof_attack_leaderboard_output(
        proof_attack_leaderboard_payload,
        output_dir / "proof-attack-leaderboard.json",
    )
    artifacts.append(_artifact("proof_attack_leaderboard_json", proof_attack_leaderboard_json_path, "Machine-readable adversarial proof attack leaderboard."))
    proof_attack_leaderboard_path = write_proof_attack_leaderboard_output(
        proof_attack_leaderboard_payload,
        output_dir / "proof-attack-leaderboard.md",
    )
    artifacts.append(_artifact("proof_attack_leaderboard", proof_attack_leaderboard_path, "Ranked attack pressure and residual-risk report."))
    proof_attack_triage_payload = build_proof_attack_triage(proof_attack_json_path)
    proof_attack_triage_json_path = write_proof_attack_triage_output(
        proof_attack_triage_payload,
        output_dir / "proof-attack-triage.json",
    )
    artifacts.append(_artifact("proof_attack_triage_json", proof_attack_triage_json_path, "Machine-readable proof attack defense triage plan."))
    proof_attack_triage_path = write_proof_attack_triage_output(
        proof_attack_triage_payload,
        output_dir / "proof-attack-triage.md",
    )
    artifacts.append(_artifact("proof_attack_triage", proof_attack_triage_path, "Counterexample-guided defense hardening plan."))
    proof_attack_policy_payload = synthesize_proof_attack_policy(
        proof_attack_json_path,
        leaderboard_payload=proof_attack_leaderboard_payload,
        triage_payload=proof_attack_triage_payload,
    )
    proof_attack_policy_json_path = write_proof_attack_policy_output(
        proof_attack_policy_payload,
        output_dir / "proof-attack-policy.json",
    )
    artifacts.append(_artifact("proof_attack_policy_json", proof_attack_policy_json_path, "Machine-readable counterexample-guided defense policy synthesis."))
    proof_attack_policy_path = write_proof_attack_policy_output(
        proof_attack_policy_payload,
        output_dir / "proof-attack-policy.md",
    )
    artifacts.append(_artifact("proof_attack_policy", proof_attack_policy_path, "Synthesized proof attack defense policy and simulation report."))
    proof_attack_adaptive_payload = run_adaptive_proof_attack_curriculum(
        runtime,
        baseline_benchmark_path=proof_attack_json_path,
        policy_path=proof_attack_policy_json_path,
        output_dir=output_dir / "proof-attack-adaptive",
        top_k=top_k,
    )
    for artifact in proof_attack_adaptive_payload.get("artifacts", []):
        artifacts.append(artifact)
    proof_attack_adaptive_json_path = write_adaptive_proof_attack_output(
        proof_attack_adaptive_payload,
        output_dir / "proof-attack-adaptive.json",
    )
    artifacts.append(_artifact("proof_attack_adaptive_json", proof_attack_adaptive_json_path, "Machine-readable adaptive proof attack curriculum report."))
    proof_attack_adaptive_path = write_adaptive_proof_attack_output(
        proof_attack_adaptive_payload,
        output_dir / "proof-attack-adaptive.md",
    )
    artifacts.append(_artifact("proof_attack_adaptive", proof_attack_adaptive_path, "Second-order policy stress-test report."))
    proof_attack_repair_payload = synthesize_adaptive_policy_repair(
        policy_path=proof_attack_policy_json_path,
        adaptive_path=proof_attack_adaptive_json_path,
    )
    proof_attack_repair_json_path = write_adaptive_policy_repair_output(
        proof_attack_repair_payload,
        output_dir / "proof-attack-repair.json",
    )
    artifacts.append(_artifact("proof_attack_repair_json", proof_attack_repair_json_path, "Machine-readable adaptive proof attack policy repair."))
    proof_attack_repair_path = write_adaptive_policy_repair_output(
        proof_attack_repair_payload,
        output_dir / "proof-attack-repair.md",
    )
    artifacts.append(_artifact("proof_attack_repair", proof_attack_repair_path, "Adaptive policy repair and re-evaluation report."))
    proof_attack_certificate_payload = build_proof_attack_minimax_certificate(
        benchmark_path=proof_attack_json_path,
        policy_path=proof_attack_policy_json_path,
        adaptive_path=proof_attack_adaptive_json_path,
        repair_path=proof_attack_repair_json_path,
    )
    proof_attack_certificate_json_path = write_proof_attack_minimax_certificate_output(
        proof_attack_certificate_payload,
        output_dir / "proof-attack-certificate.json",
    )
    artifacts.append(_artifact("proof_attack_certificate_json", proof_attack_certificate_json_path, "Machine-readable minimax proof attack certificate."))
    proof_attack_certificate_path = write_proof_attack_minimax_certificate_output(
        proof_attack_certificate_payload,
        output_dir / "proof-attack-certificate.md",
    )
    artifacts.append(_artifact("proof_attack_certificate", proof_attack_certificate_path, "Auditable minimax proof attack reliability certificate."))
    proof_attack_scorecard_payload = build_proof_attack_scorecard(proof_attack_json_path)
    proof_attack_scorecard_json_path = write_proof_attack_scorecard_output(
        proof_attack_scorecard_payload,
        output_dir / "proof-attack-scorecard.json",
    )
    artifacts.append(_artifact("proof_attack_scorecard_json", proof_attack_scorecard_json_path, "Machine-readable adversarial proof attack scorecard."))
    proof_attack_scorecard_path = write_proof_attack_scorecard_output(
        proof_attack_scorecard_payload,
        output_dir / "proof-attack-scorecard.md",
    )
    artifacts.append(_artifact("proof_attack_scorecard", proof_attack_scorecard_path, "Thresholded self-red-team quality gate."))
    proof_attack_scorecard_sarif_path = write_proof_attack_scorecard_sarif(
        proof_attack_scorecard_payload,
        output_dir / "proof-attack-scorecard.sarif",
    )
    artifacts.append(_artifact("proof_attack_scorecard_sarif", proof_attack_scorecard_sarif_path, "SARIF output for adversarial proof attack scorecard gate."))
    proof_attack_cegar_payload = build_proof_attack_cegar_summary(
        benchmark_path=proof_attack_json_path,
        leaderboard_payload=proof_attack_leaderboard_payload,
        triage_payload=proof_attack_triage_payload,
        scorecard_payload=proof_attack_scorecard_payload,
        policy_payload=proof_attack_policy_payload,
        artifact_paths={
            "proof_attack_benchmark_json": proof_attack_json_path,
            "proof_attack_benchmark": proof_attack_path,
            "proof_attack_leaderboard_json": proof_attack_leaderboard_json_path,
            "proof_attack_leaderboard": proof_attack_leaderboard_path,
            "proof_attack_triage_json": proof_attack_triage_json_path,
            "proof_attack_triage": proof_attack_triage_path,
            "proof_attack_policy_json": proof_attack_policy_json_path,
            "proof_attack_policy": proof_attack_policy_path,
            "proof_attack_scorecard_json": proof_attack_scorecard_json_path,
            "proof_attack_scorecard": proof_attack_scorecard_path,
            "proof_attack_scorecard_sarif": proof_attack_scorecard_sarif_path,
        },
    )
    proof_attack_cegar_json_path = write_proof_attack_cegar_output(
        proof_attack_cegar_payload,
        output_dir / "proof-attack-cegar.json",
    )
    artifacts.append(_artifact("proof_attack_cegar_json", proof_attack_cegar_json_path, "Machine-readable counterexample-guided proof attack reliability loop."))
    proof_attack_cegar_path = write_proof_attack_cegar_output(
        proof_attack_cegar_payload,
        output_dir / "proof-attack-cegar.md",
    )
    artifacts.append(_artifact("proof_attack_cegar", proof_attack_cegar_path, "Counterexample-guided proof attack convergence report."))

    _result, _repo_index, html_path = runtime.generate_report(
        repo_path=proof_repo,
        question=proof_question,
        top_k=top_k,
        use_model=False,
        force_rebuild=True,
        output_path=output_dir / "proof-carrying-counterfactual.html",
    )
    artifacts.append(_artifact("proof_html_report", html_path, "Proof-carrying HTML investigation report."))

    _bundle, bundle_path = runtime.generate_bundle(
        repo_path=proof_repo,
        question=proof_question,
        target="generic",
        fmt="json",
        top_k=top_k,
        use_model=False,
        force_rebuild=True,
        output_path=output_dir / "proof-carrying-counterfactual.bundle.json",
    )
    artifacts.append(_artifact("proof_bundle", bundle_path, "Portable JSON evidence bundle."))

    replay_payload = replay_proof_bundle(bundle_path, strict=True)
    replay_path = write_replay_output(replay_payload, output_dir / "proof-replay-report.md")
    artifacts.append(_artifact("proof_replay", replay_path, "Strict proof replay report."))

    mutation_payload = run_proof_mutation_lab(bundle_path)
    mutation_path = write_mutation_output(mutation_payload, output_dir / "proof-mutation-report.md")
    artifacts.append(_artifact("proof_mutation_lab", mutation_path, "Proof checker mutation-test report."))

    scorecard_payload = build_proof_scorecard(bundle_path)
    scorecard_path = write_scorecard_output(scorecard_payload, output_dir / "proof-scorecard.md")
    artifacts.append(_artifact("proof_scorecard", scorecard_path, "One-page proof reliability scorecard."))

    impact_payload = analyze_impact_bundle(bundle_path)
    impact_path = write_impact_output(impact_payload, output_dir / "proof-impact-report.md")
    artifacts.append(_artifact("proof_impact", impact_path, "Proof-guided change impact analysis."))

    contract_payload = build_regression_contract(bundle_path)
    contract_json_path = write_contract_output(contract_payload, output_dir / "proof-regression-contract.json")
    artifacts.append(_artifact("proof_regression_contract_json", contract_json_path, "Machine-readable proof regression contract."))
    contract_md_path = write_contract_output(contract_payload, output_dir / "proof-regression-contract.md")
    artifacts.append(_artifact("proof_regression_contract", contract_md_path, "Human-readable proof regression contract."))

    contract_verification_payload = verify_regression_contract(contract_json_path)
    contract_verification_path = write_contract_verification_output(
        contract_verification_payload,
        output_dir / "proof-regression-contract-verification.md",
    )
    artifacts.append(_artifact("proof_regression_contract_verification", contract_verification_path, "Proof regression contract verification report."))

    pr_guard_payload = guard_pr_with_contract(contract_json_path, changed_files=["server.js"], fail_on="never")
    pr_guard_path = write_pr_guard_output(pr_guard_payload, output_dir / "proof-pr-guard-report.md")
    artifacts.append(_artifact("proof_pr_guard", pr_guard_path, "Proof-backed PR guard report for protected-surface changes."))
    pr_guard_sarif_path = write_pr_guard_sarif(pr_guard_payload, output_dir / "proof-pr-guard.sarif")
    artifacts.append(_artifact("proof_pr_guard_sarif", pr_guard_sarif_path, "SARIF output for GitHub Code Scanning integration."))

    temporal_demo_repo = build_temporal_demo_repo(proof_repo, output_dir)
    temporal_payload = run_temporal_proof_regression(
        contract_json_path,
        git_repo_path=temporal_demo_repo,
        repo_subdir="",
        rev_range="HEAD",
        max_commits=10,
    )
    temporal_json_path = write_temporal_output(temporal_payload, output_dir / "temporal-proof-regression.json")
    artifacts.append(_artifact("temporal_proof_regression_json", temporal_json_path, "Machine-readable temporal proof regression audit."))
    temporal_md_path = write_temporal_output(temporal_payload, output_dir / "temporal-proof-regression.md")
    artifacts.append(_artifact("temporal_proof_regression", temporal_md_path, "Commit-history proof regression report with first failing commit attribution."))
    proof_repair = temporal_payload.get("proof_repair") or {}
    proof_graph_delta = proof_repair.get("proof_graph_delta") or {}
    migration_plan = proof_repair.get("contract_migration_plan") or {}

    temporal_benchmark_payload = run_temporal_repair_benchmark(
        runtime,
        output_dir=output_dir / "temporal-repair-benchmark",
        top_k=top_k,
    )
    temporal_benchmark_json_path = write_temporal_benchmark_output(
        temporal_benchmark_payload,
        output_dir / "temporal-repair-benchmark.json",
    )
    artifacts.append(_artifact("temporal_repair_benchmark_json", temporal_benchmark_json_path, "Machine-readable temporal repair benchmark results."))
    temporal_benchmark_path = write_temporal_benchmark_output(
        temporal_benchmark_payload,
        output_dir / "temporal-repair-benchmark.md",
    )
    artifacts.append(_artifact("temporal_repair_benchmark", temporal_benchmark_path, "Synthetic temporal repair benchmark report."))
    temporal_scorecard_payload = build_temporal_repair_scorecard(temporal_benchmark_json_path)
    temporal_scorecard_json_path = write_temporal_scorecard_output(
        temporal_scorecard_payload,
        output_dir / "temporal-repair-scorecard.json",
    )
    artifacts.append(_artifact("temporal_repair_scorecard_json", temporal_scorecard_json_path, "Machine-readable temporal repair scorecard."))
    temporal_scorecard_path = write_temporal_scorecard_output(
        temporal_scorecard_payload,
        output_dir / "temporal-repair-scorecard.md",
    )
    artifacts.append(_artifact("temporal_repair_scorecard", temporal_scorecard_path, "Thresholded temporal repair quality gate."))
    temporal_scorecard_sarif_path = write_temporal_scorecard_sarif(
        temporal_scorecard_payload,
        output_dir / "temporal-repair-scorecard.sarif",
    )
    artifacts.append(_artifact("temporal_repair_scorecard_sarif", temporal_scorecard_sarif_path, "SARIF output for temporal repair scorecard gate."))

    agent_court_payload = build_agent_court(
        bundle_path,
        proof_scorecard=scorecard_payload,
        attack_scorecard=proof_attack_scorecard_payload,
        temporal_scorecard=temporal_scorecard_payload,
    )
    agent_court_json_path = write_agent_court_output(agent_court_payload, output_dir / "agent-court.json")
    artifacts.append(_artifact("agent_court_json", agent_court_json_path, "Machine-readable multi-agent evidence court ledger."))
    agent_court_path = write_agent_court_output(agent_court_payload, output_dir / "agent-court.md")
    artifacts.append(_artifact("agent_court", agent_court_path, "Multi-agent verifier, skeptic, and arbiter report."))

    manifest = {
        "schema_version": "1.0",
        "strategy": "release_pack",
        "output_dir": str(output_dir),
        "proof_question": proof_question,
        "artifacts": artifacts,
        "metrics": {
            "ablation_graph_mcts_mrr": ablation_payload["metrics"]["graph_mcts"]["mrr"],
            "counterfactual_graph_mcts_top1": counterfactual_payload["metrics"]["graph_mcts"]["top1_accuracy"],
            "counterfactual_graph_mcts_mrr": counterfactual_payload["metrics"]["graph_mcts"]["mrr"],
            "counterfactual_graph_mcts_distractor_top1": counterfactual_payload["metrics"]["graph_mcts"]["distractor_top1_rate"],
            "benchmark_adapter_status": benchmark_adapter_payload["status"],
            "benchmark_adapter_cases": benchmark_adapter_payload["metrics"]["case_count"],
            "benchmark_adapter_top1": benchmark_adapter_payload["metrics"]["top1_accuracy"],
            "benchmark_adapter_top3": benchmark_adapter_payload["metrics"]["top3_accuracy"],
            "benchmark_adapter_mrr": benchmark_adapter_payload["metrics"]["mrr"],
            "benchmark_adapter_distractor_top1": benchmark_adapter_payload["metrics"]["distractor_top1_rate"],
            "benchmark_adapter_repo_groups": len(benchmark_adapter_payload["by_repo"]),
            "benchmark_adapter_tag_groups": len(benchmark_adapter_payload["by_tag"]),
            "benchmark_adapter_generalization_gaps": len(benchmark_adapter_payload["generalization_gaps"]),
            "benchmark_diagnostics_status": benchmark_diagnostics_payload["status"],
            "benchmark_diagnostics_score": benchmark_diagnostics_payload["score"],
            "benchmark_diagnostics_grade": benchmark_diagnostics_payload["grade"],
            "benchmark_diagnostics_weak_cases": benchmark_diagnostics_payload["summary"]["weak_case_count"],
            "benchmark_diagnostics_blockers": benchmark_diagnostics_payload["summary"]["blocker_count"],
            "benchmark_diagnostics_actions": benchmark_diagnostics_payload["summary"]["action_count"],
            "benchmark_diagnostics_taxonomy_count": benchmark_diagnostics_payload["summary"]["taxonomy_count"],
            "benchmark_diagnostics_recoverable_cases": benchmark_diagnostics_payload["summary"]["recoverable_case_count"],
            "benchmark_diagnostics_projected_top1": benchmark_diagnostics_payload["summary"]["projected_top1_accuracy"],
            "benchmark_repair_status": benchmark_repair_payload["status"],
            "benchmark_repair_score": benchmark_repair_payload["score"],
            "benchmark_repair_grade": benchmark_repair_payload["grade"],
            "benchmark_repair_guards": benchmark_repair_payload["summary"]["guard_count"],
            "benchmark_repair_passed_guards": benchmark_repair_payload["summary"]["passed_guards"],
            "benchmark_repair_reason_cases": benchmark_repair_payload["summary"]["repair_reason_case_count"],
            "benchmark_repair_synthesis_status": benchmark_repair_synthesis_payload["status"],
            "benchmark_repair_synthesis_score": benchmark_repair_synthesis_payload["score"],
            "benchmark_repair_synthesis_grade": benchmark_repair_synthesis_payload["grade"],
            "benchmark_repair_synthesis_candidates": benchmark_repair_synthesis_payload["summary"]["candidate_count"],
            "benchmark_repair_synthesis_proposed_rules": benchmark_repair_synthesis_payload["summary"]["proposed_rule_count"],
            "benchmark_repair_synthesis_validated_rules": benchmark_repair_synthesis_payload["summary"]["validated_rule_count"],
            "benchmark_repair_synthesis_coverage_cases": benchmark_repair_synthesis_payload["summary"]["coverage_case_count"],
            "benchmark_repair_synthesis_projected_top1": benchmark_repair_synthesis_payload["simulated_metrics"]["top1_accuracy"],
            "benchmark_repair_implementation_status": benchmark_repair_implementation_payload["status"],
            "benchmark_repair_implementation_score": benchmark_repair_implementation_payload["score"],
            "benchmark_repair_implementation_grade": benchmark_repair_implementation_payload["grade"],
            "benchmark_repair_implementation_validated_rules": benchmark_repair_implementation_payload["summary"]["validated_rule_count"],
            "benchmark_repair_implementation_implemented_rules": benchmark_repair_implementation_payload["summary"]["implemented_validated_rule_count"],
            "benchmark_repair_implementation_missing_rules": benchmark_repair_implementation_payload["summary"]["missing_validated_rule_count"],
            "benchmark_repair_implementation_found_anchors": benchmark_repair_implementation_payload["summary"]["found_anchor_count"],
            "benchmark_repair_implementation_anchor_count": benchmark_repair_implementation_payload["summary"]["anchor_count"],
            "benchmark_repair_implementation_found_reasons": benchmark_repair_implementation_payload["summary"]["found_reason_count"],
            "benchmark_repair_implementation_reason_count": benchmark_repair_implementation_payload["summary"]["reason_count"],
            "benchmark_repair_compiler_status": benchmark_repair_compiler_payload["status"],
            "benchmark_repair_compiler_score": benchmark_repair_compiler_payload["score"],
            "benchmark_repair_compiler_grade": benchmark_repair_compiler_payload["grade"],
            "benchmark_repair_compiler_patch_required": benchmark_repair_compiler_payload["summary"]["patch_required_count"],
            "benchmark_repair_compiler_regression_locks": benchmark_repair_compiler_payload["summary"]["regression_lock_count"],
            "benchmark_repair_compiler_ablation_toggles": benchmark_repair_compiler_payload["summary"]["ablation_toggle_count"],
            "benchmark_repair_compiler_validation_commands": benchmark_repair_compiler_payload["summary"]["validation_command_count"],
            "benchmark_repair_compiler_implemented_anchors": benchmark_repair_compiler_payload["summary"]["implemented_anchor_count"],
            "benchmark_repair_workbench_status": benchmark_repair_workbench_payload["status"],
            "benchmark_repair_workbench_score": benchmark_repair_workbench_payload["score"],
            "benchmark_repair_workbench_grade": benchmark_repair_workbench_payload["grade"],
            "benchmark_repair_workbench_patch_candidates": benchmark_repair_workbench_payload["summary"]["patch_candidate_count"],
            "benchmark_repair_workbench_review_apply_patches": benchmark_repair_workbench_payload["summary"]["review_apply_patch_count"],
            "benchmark_repair_workbench_counterfactual_patches": benchmark_repair_workbench_payload["summary"]["counterfactual_patch_count"],
            "benchmark_repair_workbench_experiments": benchmark_repair_workbench_payload["summary"]["experiment_count"],
            "benchmark_experiment_status": benchmark_experiment_payload["status"],
            "benchmark_experiment_score": benchmark_experiment_payload["score"],
            "benchmark_experiment_grade": benchmark_experiment_payload["grade"],
            "benchmark_experiment_claims": benchmark_experiment_payload["summary"]["claim_count"],
            "benchmark_experiment_supported_claims": benchmark_experiment_payload["summary"]["supported_claims"],
            "benchmark_experiment_weak_cases": benchmark_experiment_payload["summary"]["weak_case_count"],
            "benchmark_experiment_taxonomy_count": benchmark_experiment_payload["summary"]["taxonomy_count"],
            "benchmark_experiment_projected_top1": benchmark_experiment_payload["summary"]["projected_top1_accuracy"],
            "proof_attack_cases": proof_attack_payload["metrics"]["case_count"],
            "proof_attack_resistance_rate": proof_attack_payload["metrics"]["attack_resistance_rate"],
            "proof_attack_graph_mcts_top1": proof_attack_payload["metrics"]["graph_mcts_top1_accuracy"],
            "proof_attack_graph_mcts_distractor_top1": proof_attack_payload["metrics"]["graph_mcts_distractor_top1_rate"],
            "proof_attack_proof_proved_rate": proof_attack_payload["metrics"]["proof_proved_rate"],
            "proof_attack_generated_decoy_audit_rate": proof_attack_payload["metrics"]["generated_decoy_audit_rate"],
            "proof_attack_generated_decoy_count": proof_attack_payload["metrics"]["generated_decoy_count"],
            "proof_attack_mitigated_decoy_rate": proof_attack_payload["metrics"]["mitigated_decoy_rate"],
            "proof_attack_mitigation_signal_rate": proof_attack_payload["metrics"]["mitigation_signal_rate"],
            "proof_attack_suite": proof_attack_payload.get("spec", {}).get("suite", ""),
            "proof_attack_hardest_case": proof_attack_leaderboard_payload["hardest_case"],
            "proof_attack_max_pressure": proof_attack_leaderboard_payload["max_attack_pressure"],
            "proof_attack_max_residual_risk": proof_attack_leaderboard_payload["max_residual_risk"],
            "proof_attack_triage_status": proof_attack_triage_payload["status"],
            "proof_attack_triage_actions": proof_attack_triage_payload["action_count"],
            "proof_attack_triage_p0": proof_attack_triage_payload["priority_counts"]["P0"],
            "proof_attack_triage_p1": proof_attack_triage_payload["priority_counts"]["P1"],
            "proof_attack_triage_p2": proof_attack_triage_payload["priority_counts"]["P2"],
            "proof_attack_policy_status": proof_attack_policy_payload["status"],
            "proof_attack_policy_rules": proof_attack_policy_payload["rule_count"],
            "proof_attack_policy_coverage": proof_attack_policy_payload["simulation"]["coverage_rate"],
            "proof_attack_policy_residual_actions": proof_attack_policy_payload["simulation"]["after"]["uncovered_action_count"],
            "proof_attack_adaptive_status": proof_attack_adaptive_payload["status"],
            "proof_attack_adaptive_cases": proof_attack_adaptive_payload["case_count"],
            "proof_attack_adaptive_policy_coverage": proof_attack_adaptive_payload["metrics"]["policy_coverage_rate"],
            "proof_attack_adaptive_uncovered_actions": proof_attack_adaptive_payload["metrics"]["policy_uncovered_actions"],
            "proof_attack_repair_status": proof_attack_repair_payload["status"],
            "proof_attack_repair_patch_rules": proof_attack_repair_payload["patch_rule_count"],
            "proof_attack_repair_coverage": proof_attack_repair_payload["after"]["coverage_rate"],
            "proof_attack_repair_uncovered_actions": proof_attack_repair_payload["after"]["uncovered_action_count"],
            "proof_attack_certificate_status": proof_attack_certificate_payload["status"],
            "proof_attack_certificate_score": proof_attack_certificate_payload["score"],
            "proof_attack_certificate_claims": len(proof_attack_certificate_payload["claims"]),
            "proof_attack_certificate_passed_claims": sum(1 for claim in proof_attack_certificate_payload["claims"] if claim.get("passed")),
            "proof_attack_score": proof_attack_scorecard_payload["score"],
            "proof_attack_grade": proof_attack_scorecard_payload["grade"],
            "proof_attack_scorecard_status": proof_attack_scorecard_payload["status"],
            "proof_attack_cegar_status": proof_attack_cegar_payload["status"],
            "proof_attack_cegar_iterations": proof_attack_cegar_payload["iteration_count"],
            "proof_attack_cegar_next_actions": len(proof_attack_cegar_payload["next_actions"]),
            "proof_score": scorecard_payload["score"],
            "proof_grade": scorecard_payload["grade"],
            "mutation_detection_rate": scorecard_payload["metrics"]["mutation_detection_rate"],
            "impact_risk_level": impact_payload["impact_summary"]["risk_level"],
            "impact_exposed_routes": impact_payload["impact_summary"]["exposed_route_count"],
            "impact_impacted_files": impact_payload["impact_summary"]["impacted_file_count"],
            "contract_status": contract_verification_payload["status"],
            "contract_passed_checks": contract_verification_payload["summary"]["passed_count"],
            "contract_total_checks": contract_verification_payload["summary"]["check_count"],
            "pr_guard_status": pr_guard_payload["status"],
            "pr_guard_touched_files": pr_guard_payload["summary"]["touched_protected_file_count"],
            "temporal_status": temporal_payload["status"],
            "temporal_failed_commits": temporal_payload["summary"]["failed_count"],
            "temporal_first_failing_commit": (temporal_payload.get("first_failing_commit") or {}).get("short_sha", ""),
            "proof_repair_status": proof_repair.get("status", ""),
            "proof_repair_top_candidate": (proof_repair.get("top_candidate") or {}).get("label", ""),
            "proof_graph_delta_status": proof_graph_delta.get("status", ""),
            "proof_graph_delta_broken_edges": proof_graph_delta.get("broken_edge_count", 0),
            "proof_graph_delta_successor_relinks": proof_graph_delta.get("successor_relink_count", 0),
            "proof_contract_migration_status": migration_plan.get("status", ""),
            "proof_contract_migration_patch_ops": len(migration_plan.get("json_patch", [])),
            "temporal_repair_benchmark_cases": temporal_benchmark_payload["metrics"]["case_count"],
            "temporal_repair_successor_top1": temporal_benchmark_payload["metrics"]["successor_top1_accuracy"],
            "temporal_repair_abstention_accuracy": temporal_benchmark_payload["metrics"]["abstention_accuracy"],
            "temporal_repair_false_repair_rate": temporal_benchmark_payload["metrics"]["false_repair_rate"],
            "temporal_repair_causal_delta_rate": temporal_benchmark_payload["metrics"]["causal_delta_rate"],
            "temporal_repair_migration_ready_rate": temporal_benchmark_payload["metrics"]["migration_ready_rate"],
            "temporal_repair_score": temporal_scorecard_payload["score"],
            "temporal_repair_grade": temporal_scorecard_payload["grade"],
            "temporal_repair_scorecard_status": temporal_scorecard_payload["status"],
            "agent_court_status": agent_court_payload["verdict"]["status"],
            "agent_court_score": agent_court_payload["verdict"]["score"],
            "agent_court_grade": agent_court_payload["verdict"]["grade"],
            "agent_court_claims": agent_court_payload["metrics"]["claim_count"],
            "agent_court_challenges": agent_court_payload["metrics"]["challenge_count"],
            "agent_court_discharged_challenges": agent_court_payload["metrics"]["discharged_challenge_count"],
        },
    }
    manifest_path = output_dir / "manifest.json"
    readme_path = output_dir / "README.md"
    manifest["manifest_path"] = str(manifest_path)
    manifest["readme_path"] = str(readme_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    agent_frontier_payload = build_agent_reliability_frontier(manifest_path)
    agent_frontier_json_path = write_agent_frontier_output(
        agent_frontier_payload,
        output_dir / "agent-frontier.json",
    )
    artifacts.append(_artifact("agent_frontier_json", agent_frontier_json_path, "Machine-readable multi-objective agent reliability frontier."))
    agent_frontier_path = write_agent_frontier_output(
        agent_frontier_payload,
        output_dir / "agent-frontier.md",
    )
    artifacts.append(_artifact("agent_frontier", agent_frontier_path, "Pareto frontier over proof, attack, temporal, court, and integrity evidence."))
    manifest["metrics"].update(
        {
            "agent_frontier_status": agent_frontier_payload["status"],
            "agent_frontier_score": agent_frontier_payload["score"],
            "agent_frontier_grade": agent_frontier_payload["grade"],
            "agent_frontier_profiles": agent_frontier_payload["summary"]["profile_count"],
            "agent_frontier_pareto_profiles": agent_frontier_payload["summary"]["frontier_count"],
        }
    )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    agent_frontier_ablation_payload = build_agent_frontier_ablation(manifest_path)
    agent_frontier_ablation_json_path = write_agent_frontier_ablation_output(
        agent_frontier_ablation_payload,
        output_dir / "agent-frontier-ablation.json",
    )
    artifacts.append(_artifact("agent_frontier_ablation_json", agent_frontier_ablation_json_path, "Machine-readable causal ablation over agent reliability evidence families."))
    agent_frontier_ablation_path = write_agent_frontier_ablation_output(
        agent_frontier_ablation_payload,
        output_dir / "agent-frontier-ablation.md",
    )
    artifacts.append(_artifact("agent_frontier_ablation", agent_frontier_ablation_path, "Counterfactual evidence-family attribution for the agent reliability frontier."))
    manifest["metrics"].update(
        {
            "agent_frontier_ablation_status": agent_frontier_ablation_payload["status"],
            "agent_frontier_ablation_count": agent_frontier_ablation_payload["summary"]["ablation_count"],
            "agent_frontier_ablation_top_driver": agent_frontier_ablation_payload["summary"]["top_driver"],
            "agent_frontier_ablation_max_score_drop": agent_frontier_ablation_payload["summary"]["max_score_drop"],
            "agent_frontier_ablation_max_frontier_loss": agent_frontier_ablation_payload["summary"]["max_frontier_loss"],
        }
    )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    agent_frontier_interactions_payload = build_agent_frontier_interactions(manifest_path)
    agent_frontier_interactions_json_path = write_agent_frontier_interactions_output(
        agent_frontier_interactions_payload,
        output_dir / "agent-frontier-interactions.json",
    )
    artifacts.append(_artifact("agent_frontier_interactions_json", agent_frontier_interactions_json_path, "Machine-readable pairwise evidence interaction matrix."))
    agent_frontier_interactions_path = write_agent_frontier_interactions_output(
        agent_frontier_interactions_payload,
        output_dir / "agent-frontier-interactions.md",
    )
    artifacts.append(_artifact("agent_frontier_interactions", agent_frontier_interactions_path, "Pairwise counterfactual interaction matrix for reliability evidence families."))
    manifest["metrics"].update(
        {
            "agent_frontier_interactions_status": agent_frontier_interactions_payload["status"],
            "agent_frontier_interactions_pairs": agent_frontier_interactions_payload["summary"]["pair_count"],
            "agent_frontier_interactions_top_pair": agent_frontier_interactions_payload["summary"]["top_interaction"],
            "agent_frontier_interactions_max_synergy": agent_frontier_interactions_payload["summary"]["max_synergy"],
            "agent_frontier_interactions_fragile_pairs": agent_frontier_interactions_payload["summary"]["fragile_pair_count"],
        }
    )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    agent_frontier_stability_payload = build_agent_frontier_stability(manifest_path)
    agent_frontier_stability_json_path = write_agent_frontier_stability_output(
        agent_frontier_stability_payload,
        output_dir / "agent-frontier-stability.json",
    )
    artifacts.append(_artifact("agent_frontier_stability_json", agent_frontier_stability_json_path, "Machine-readable bootstrap stability analysis for the reliability frontier."))
    agent_frontier_stability_path = write_agent_frontier_stability_output(
        agent_frontier_stability_payload,
        output_dir / "agent-frontier-stability.md",
    )
    artifacts.append(_artifact("agent_frontier_stability", agent_frontier_stability_path, "Bootstrap uncertainty report for frontier membership and evidence interactions."))
    manifest["metrics"].update(
        {
            "agent_frontier_stability_status": agent_frontier_stability_payload["status"],
            "agent_frontier_stability_samples": agent_frontier_stability_payload["summary"]["sample_count"],
            "agent_frontier_stability_score_ci_low": agent_frontier_stability_payload["summary"]["score_ci_low"],
            "agent_frontier_stability_score_ci_high": agent_frontier_stability_payload["summary"]["score_ci_high"],
            "agent_frontier_stability_frontier_jaccard": agent_frontier_stability_payload["summary"]["frontier_jaccard_mean"],
            "agent_frontier_stability_top_interaction": agent_frontier_stability_payload["summary"]["top_interaction_mode"],
            "agent_frontier_stability_top_interaction_probability": agent_frontier_stability_payload["summary"]["top_interaction_probability"],
        }
    )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    agent_artifact_review_payload = build_agent_artifact_review(manifest_path)
    agent_artifact_review_json_path = write_agent_artifact_review_output(
        agent_artifact_review_payload,
        output_dir / "agent-artifact-review.json",
    )
    artifacts.append(_artifact("agent_artifact_review_json", agent_artifact_review_json_path, "Machine-readable reviewer-facing artifact evaluation card."))
    agent_artifact_review_path = write_agent_artifact_review_output(
        agent_artifact_review_payload,
        output_dir / "agent-artifact-review.md",
    )
    artifacts.append(_artifact("agent_artifact_review", agent_artifact_review_path, "Reviewer-facing claim card with evidence, commands, falsifiers, and limitations."))
    manifest["metrics"].update(
        {
            "agent_artifact_review_status": agent_artifact_review_payload["status"],
            "agent_artifact_review_score": agent_artifact_review_payload["score"],
            "agent_artifact_review_grade": agent_artifact_review_payload["grade"],
            "agent_artifact_review_claims": agent_artifact_review_payload["summary"]["claim_count"],
            "agent_artifact_review_supported_claims": agent_artifact_review_payload["summary"]["supported_count"],
            "agent_artifact_review_qualified_claims": agent_artifact_review_payload["summary"]["qualified_count"],
        }
    )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_provenance_payload = build_artifact_provenance(manifest_path)
    artifact_provenance_json_path = write_artifact_provenance_output(
        artifact_provenance_payload,
        output_dir / "artifact-provenance.json",
    )
    artifacts.append(_artifact("artifact_provenance_json", artifact_provenance_json_path, "Machine-readable claim-to-artifact provenance graph."))
    artifact_provenance_path = write_artifact_provenance_output(
        artifact_provenance_payload,
        output_dir / "artifact-provenance.md",
    )
    artifacts.append(_artifact("artifact_provenance", artifact_provenance_path, "Reviewer-facing claim provenance graph."))
    manifest["metrics"].update(
        {
            "artifact_provenance_status": artifact_provenance_payload["status"],
            "artifact_provenance_claims": artifact_provenance_payload["summary"]["claim_count"],
            "artifact_provenance_complete_claims": artifact_provenance_payload["summary"]["complete_claim_count"],
            "artifact_provenance_edges": artifact_provenance_payload["summary"]["edge_count"],
            "artifact_provenance_artifact_edges": artifact_provenance_payload["summary"]["artifact_edge_count"],
            "artifact_provenance_command_edges": artifact_provenance_payload["summary"]["command_edge_count"],
            "artifact_provenance_falsifier_edges": artifact_provenance_payload["summary"]["falsifier_edge_count"],
        }
    )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_provenance_verification_payload = verify_artifact_provenance(
        artifact_provenance_json_path,
        manifest_path=manifest_path,
    )
    artifact_provenance_verification_json_path = write_artifact_provenance_verification_output(
        artifact_provenance_verification_payload,
        output_dir / "artifact-provenance-verification.json",
    )
    artifacts.append(
        _artifact(
            "artifact_provenance_verification_json",
            artifact_provenance_verification_json_path,
            "Machine-readable verification of claim provenance edges and artifact hashes.",
        )
    )
    artifact_provenance_verification_path = write_artifact_provenance_verification_output(
        artifact_provenance_verification_payload,
        output_dir / "artifact-provenance-verification.md",
    )
    artifacts.append(
        _artifact(
            "artifact_provenance_verification",
            artifact_provenance_verification_path,
            "Reviewer-facing verification of claim provenance edges and artifact hashes.",
        )
    )
    manifest["metrics"].update(
        {
            "artifact_provenance_verification_status": artifact_provenance_verification_payload["status"],
            "artifact_provenance_verification_failures": artifact_provenance_verification_payload["summary"]["failure_count"],
            "artifact_provenance_verification_warnings": artifact_provenance_verification_payload["summary"]["warning_count"],
        }
    )

    readme_path.write_text(render_release_pack_markdown(manifest), encoding="utf-8")
    artifacts.append(_artifact("release_pack_readme", readme_path, "Release pack overview."))

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def render_release_pack_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Release Pack",
        "",
        f"- Output directory: `{payload.get('output_dir', '')}`",
        f"- Proof question: {payload.get('proof_question', '')}",
        f"- Proof score: `{metrics.get('proof_score', 0)}/100` (`{metrics.get('proof_grade', '')}`)",
        f"- Mutation detection: `{float(metrics.get('mutation_detection_rate', 0.0)):.1%}`",
        f"- Counterfactual graph-MCTS Top-1: `{float(metrics.get('counterfactual_graph_mcts_top1', 0.0)):.2%}`",
        f"- Counterfactual graph-MCTS MRR: `{float(metrics.get('counterfactual_graph_mcts_mrr', 0.0)):.3f}`",
        f"- Counterfactual distractor@1: `{float(metrics.get('counterfactual_graph_mcts_distractor_top1', 0.0)):.2%}`",
        f"- Portable benchmark adapter: `{metrics.get('benchmark_adapter_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_adapter_cases', 0))}` cases, "
        f"Top-3 `{float(metrics.get('benchmark_adapter_top3', 0.0)):.2%}`, "
        f"MRR `{float(metrics.get('benchmark_adapter_mrr', 0.0)):.3f}`, "
        f"gaps `{int(metrics.get('benchmark_adapter_generalization_gaps', 0))}`)",
        f"- Benchmark generalization diagnostics: `{metrics.get('benchmark_diagnostics_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_diagnostics_weak_cases', 0))}` weak cases, "
        f"blockers `{int(metrics.get('benchmark_diagnostics_blockers', 0))}`, "
        f"projected Top-1 `{float(metrics.get('benchmark_diagnostics_projected_top1', 0.0)):.2%}`)",
        f"- Benchmark repair card: `{metrics.get('benchmark_repair_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_repair_passed_guards', 0))}/"
        f"{int(metrics.get('benchmark_repair_guards', 0))}` guards, "
        f"repair-reason cases `{int(metrics.get('benchmark_repair_reason_cases', 0))}`)",
        f"- Benchmark repair synthesizer: `{metrics.get('benchmark_repair_synthesis_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_repair_synthesis_validated_rules', 0))}` validated, "
        f"`{int(metrics.get('benchmark_repair_synthesis_proposed_rules', 0))}` proposed, "
        f"projected Top-1 `{float(metrics.get('benchmark_repair_synthesis_projected_top1', 0.0)):.2%}`)",
        f"- Benchmark repair implementation: `{metrics.get('benchmark_repair_implementation_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_repair_implementation_implemented_rules', 0))}/"
        f"{int(metrics.get('benchmark_repair_implementation_validated_rules', 0))}` validated rules implemented, "
        f"anchors `{int(metrics.get('benchmark_repair_implementation_found_anchors', 0))}/"
        f"{int(metrics.get('benchmark_repair_implementation_anchor_count', 0))}`)",
        f"- Benchmark repair compiler: `{metrics.get('benchmark_repair_compiler_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_repair_compiler_regression_locks', 0))}` regression locks, "
        f"`{int(metrics.get('benchmark_repair_compiler_patch_required', 0))}` patch-required, "
        f"`{int(metrics.get('benchmark_repair_compiler_ablation_toggles', 0))}` ablation toggles)",
        f"- Benchmark repair workbench: `{metrics.get('benchmark_repair_workbench_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_repair_workbench_patch_candidates', 0))}` patch candidates, "
        f"`{int(metrics.get('benchmark_repair_workbench_review_apply_patches', 0))}` review-applicable, "
        f"`{int(metrics.get('benchmark_repair_workbench_experiments', 0))}` experiments)",
        f"- Benchmark experiment report: `{metrics.get('benchmark_experiment_status', 'unknown')}` "
        f"(`{int(metrics.get('benchmark_experiment_supported_claims', 0))}/"
        f"{int(metrics.get('benchmark_experiment_claims', 0))}` claims, "
        f"weak cases `{int(metrics.get('benchmark_experiment_weak_cases', 0))}`, "
        f"projected Top-1 `{float(metrics.get('benchmark_experiment_projected_top1', 0.0)):.2%}`)",
        f"- Adversarial proof attack resistance: `{float(metrics.get('proof_attack_resistance_rate', 0.0)):.2%}` "
        f"(`{int(metrics.get('proof_attack_cases', 0))}` cases, graph-MCTS distractor@1 "
        f"`{float(metrics.get('proof_attack_graph_mcts_distractor_top1', 0.0)):.2%}`, mitigated decoys "
        f"`{float(metrics.get('proof_attack_mitigated_decoy_rate', 0.0)):.2%}`)",
        f"- Adversarial attack leaderboard: `{metrics.get('proof_attack_hardest_case', '')}` "
        f"(pressure `{int(metrics.get('proof_attack_max_pressure', 0))}/100`, residual risk "
        f"`{int(metrics.get('proof_attack_max_residual_risk', 0))}/100`)",
        f"- Adversarial defense triage: `{metrics.get('proof_attack_triage_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_attack_triage_actions', 0))}` actions, "
        f"P0 `{int(metrics.get('proof_attack_triage_p0', 0))}`, "
        f"P1 `{int(metrics.get('proof_attack_triage_p1', 0))}`, "
        f"P2 `{int(metrics.get('proof_attack_triage_p2', 0))}`)",
        f"- Synthesized proof attack defense policy: `{metrics.get('proof_attack_policy_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_attack_policy_rules', 0))}` rules, "
        f"coverage `{float(metrics.get('proof_attack_policy_coverage', 0.0)):.2%}`, "
        f"residual `{int(metrics.get('proof_attack_policy_residual_actions', 0))}`)",
        f"- Adaptive proof attack curriculum: `{metrics.get('proof_attack_adaptive_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_attack_adaptive_cases', 0))}` cases, "
        f"policy coverage `{float(metrics.get('proof_attack_adaptive_policy_coverage', 0.0)):.2%}`, "
        f"uncovered `{int(metrics.get('proof_attack_adaptive_uncovered_actions', 0))}`)",
        f"- Adaptive policy repair: `{metrics.get('proof_attack_repair_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_attack_repair_patch_rules', 0))}` patch rules, "
        f"coverage `{float(metrics.get('proof_attack_repair_coverage', 0.0)):.2%}`, "
        f"uncovered `{int(metrics.get('proof_attack_repair_uncovered_actions', 0))}`)",
        f"- Proof attack minimax certificate: `{metrics.get('proof_attack_certificate_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_attack_certificate_score', 0))}/100`, "
        f"`{int(metrics.get('proof_attack_certificate_passed_claims', 0))}/"
        f"{int(metrics.get('proof_attack_certificate_claims', 0))}` claims)",
        f"- Adversarial proof attack scorecard: `{metrics.get('proof_attack_scorecard_status', 'unknown')}` "
        f"(`{metrics.get('proof_attack_score', 0)}/100`, `{metrics.get('proof_attack_grade', '')}`)",
        f"- Proof attack CEGAR loop: `{metrics.get('proof_attack_cegar_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_attack_cegar_iterations', 0))}` iteration, "
        f"`{int(metrics.get('proof_attack_cegar_next_actions', 0))}` next actions)",
        f"- Ablation graph-MCTS MRR: `{float(metrics.get('ablation_graph_mcts_mrr', 0.0)):.3f}`",
        f"- Impact risk level: `{metrics.get('impact_risk_level', 'unknown')}`",
        f"- Impacted files: `{int(metrics.get('impact_impacted_files', 0))}`",
        f"- Exposed routes: `{int(metrics.get('impact_exposed_routes', 0))}`",
        f"- Contract verification: `{metrics.get('contract_status', 'unknown')}` "
        f"(`{int(metrics.get('contract_passed_checks', 0))}/{int(metrics.get('contract_total_checks', 0))}`)",
        f"- PR guard: `{metrics.get('pr_guard_status', 'unknown')}` "
        f"(`{int(metrics.get('pr_guard_touched_files', 0))}` protected files touched)",
        f"- Temporal proof regression: `{metrics.get('temporal_status', 'unknown')}` "
        f"(`{int(metrics.get('temporal_failed_commits', 0))}` failing commits)",
        f"- Proof repair inference: `{metrics.get('proof_repair_status', 'unknown')}` "
        f"(`{metrics.get('proof_repair_top_candidate', '') or 'no candidate'}`)",
        f"- Proof graph delta: `{metrics.get('proof_graph_delta_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_graph_delta_broken_edges', 0))}` broken, "
        f"`{int(metrics.get('proof_graph_delta_successor_relinks', 0))}` relinked)",
        f"- Proof contract migration: `{metrics.get('proof_contract_migration_status', 'unknown')}` "
        f"(`{int(metrics.get('proof_contract_migration_patch_ops', 0))}` patch ops)",
        f"- Temporal repair benchmark: `{int(metrics.get('temporal_repair_benchmark_cases', 0))}` cases, "
        f"Successor@1 `{float(metrics.get('temporal_repair_successor_top1', 0.0)):.2%}`, "
        f"abstention `{float(metrics.get('temporal_repair_abstention_accuracy', 0.0)):.2%}`, "
        f"false repair `{float(metrics.get('temporal_repair_false_repair_rate', 0.0)):.2%}`, "
        f"delta `{float(metrics.get('temporal_repair_causal_delta_rate', 0.0)):.2%}`, "
        f"migration `{float(metrics.get('temporal_repair_migration_ready_rate', 0.0)):.2%}`",
        f"- Temporal repair scorecard: `{metrics.get('temporal_repair_scorecard_status', 'unknown')}` "
        f"(`{metrics.get('temporal_repair_score', 0)}/100`, `{metrics.get('temporal_repair_grade', '')}`)",
        f"- Multi-agent evidence court: `{metrics.get('agent_court_status', 'unknown')}` "
        f"(`{metrics.get('agent_court_score', 0)}/100`, `{metrics.get('agent_court_grade', '')}`, "
        f"`{int(metrics.get('agent_court_claims', 0))}` claims, "
        f"`{int(metrics.get('agent_court_discharged_challenges', 0))}/{int(metrics.get('agent_court_challenges', 0))}` challenges discharged)",
        f"- Agent reliability frontier: `{metrics.get('agent_frontier_status', 'unknown')}` "
        f"(`{metrics.get('agent_frontier_score', 0)}/100`, `{metrics.get('agent_frontier_grade', '')}`, "
        f"`{int(metrics.get('agent_frontier_pareto_profiles', 0))}/{int(metrics.get('agent_frontier_profiles', 0))}` Pareto profiles)",
        f"- Agent frontier causal ablation: `{metrics.get('agent_frontier_ablation_status', 'unknown')}` "
        f"(`{int(metrics.get('agent_frontier_ablation_count', 0))}` families, "
        f"top `{metrics.get('agent_frontier_ablation_top_driver', '')}`, "
        f"max drop `{int(metrics.get('agent_frontier_ablation_max_score_drop', 0))}`)",
        f"- Evidence interaction matrix: `{metrics.get('agent_frontier_interactions_status', 'unknown')}` "
        f"(`{int(metrics.get('agent_frontier_interactions_pairs', 0))}` pairs, "
        f"top `{metrics.get('agent_frontier_interactions_top_pair', '')}`, "
        f"synergy `{int(metrics.get('agent_frontier_interactions_max_synergy', 0))}`)",
        f"- Agent frontier stability: `{metrics.get('agent_frontier_stability_status', 'unknown')}` "
        f"(`{int(metrics.get('agent_frontier_stability_samples', 0))}` samples, score CI "
        f"`{int(metrics.get('agent_frontier_stability_score_ci_low', 0))}-"
        f"{int(metrics.get('agent_frontier_stability_score_ci_high', 0))}`, frontier Jaccard "
        f"`{float(metrics.get('agent_frontier_stability_frontier_jaccard', 0.0)):.2f}`, top interaction "
        f"`{metrics.get('agent_frontier_stability_top_interaction', '')}` @ "
        f"`{float(metrics.get('agent_frontier_stability_top_interaction_probability', 0.0)):.2%}`)",
        f"- Artifact evaluation card: `{metrics.get('agent_artifact_review_status', 'unknown')}` "
        f"(`{int(metrics.get('agent_artifact_review_score', 0))}/100`, "
        f"`{metrics.get('agent_artifact_review_grade', '')}`, "
        f"`{int(metrics.get('agent_artifact_review_supported_claims', 0))}/"
        f"{int(metrics.get('agent_artifact_review_claims', 0))}` supported claims)",
        f"- Artifact provenance graph: `{metrics.get('artifact_provenance_status', 'unknown')}` "
        f"(`{int(metrics.get('artifact_provenance_complete_claims', 0))}/"
        f"{int(metrics.get('artifact_provenance_claims', 0))}` complete claims, "
        f"`{int(metrics.get('artifact_provenance_edges', 0))}` edges)",
        f"- Artifact provenance verification: `{metrics.get('artifact_provenance_verification_status', 'unknown')}` "
        f"(`{int(metrics.get('artifact_provenance_verification_failures', 0))}` failures, "
        f"`{int(metrics.get('artifact_provenance_verification_warnings', 0))}` warnings)",
        "",
        "## Artifacts",
        "",
        "| Name | Path | Size | SHA-256 | Description |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in payload.get("artifacts", []):
        digest = str(item.get("sha256", ""))
        short_digest = digest[:12] if digest else ""
        lines.append(
            f"| `{item.get('name', '')}` | `{item.get('path', '')}` | "
            f"{int(item.get('size_bytes', 0))} | `{short_digest}` | {item.get('description', '')} |"
        )
    lines.append("")
    if payload.get("manifest_path"):
        lines.extend(
            [
                "## Integrity",
                "",
                "```powershell",
                f"python -m repo_agent verify-release-pack --manifest {payload['manifest_path']}",
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _artifact(name: str, path: Path, description: str) -> dict:
    return {
        "name": name,
        "path": str(path),
        "description": description,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def verify_release_pack(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    verified = []
    for item in manifest.get("artifacts", []):
        expected_size = item.get("size_bytes")
        expected_hash = item.get("sha256")
        artifact_path = _resolve_manifest_artifact_path(manifest_path, item.get("path", ""))
        checks = {
            "name": item.get("name", ""),
            "path": str(artifact_path),
            "exists": artifact_path.is_file(),
            "size_ok": False,
            "sha256_ok": False,
        }
        if not checks["exists"]:
            checks["reason"] = "missing"
            failures.append(checks)
            verified.append(checks)
            continue
        actual_size = artifact_path.stat().st_size
        actual_hash = _sha256_file(artifact_path)
        checks["actual_size_bytes"] = actual_size
        checks["actual_sha256"] = actual_hash
        checks["size_ok"] = actual_size == expected_size
        checks["sha256_ok"] = actual_hash == expected_hash
        if not checks["size_ok"]:
            checks["reason"] = "size_mismatch"
            failures.append(checks)
        elif not checks["sha256_ok"]:
            checks["reason"] = "sha256_mismatch"
            failures.append(checks)
        else:
            checks["reason"] = "ok"
        verified.append(checks)

    return {
        "schema_version": "1.0",
        "strategy": "release_pack_integrity_verification",
        "manifest_path": str(manifest_path),
        "valid": not failures,
        "artifact_count": len(manifest.get("artifacts", [])),
        "verified_count": sum(1 for item in verified if item.get("reason") == "ok"),
        "failures": failures,
        "artifacts": verified,
    }


def render_release_pack_verification_markdown(payload: dict) -> str:
    status = "PASS" if payload.get("valid") else "FAIL"
    lines = [
        "# Repo Agent Release Pack Integrity",
        "",
        f"- Status: `{status}`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Verified artifacts: `{payload.get('verified_count', 0)}/{payload.get('artifact_count', 0)}`",
        "",
        "| Result | Name | Size | SHA-256 | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("artifacts", []):
        ok = item.get("reason") == "ok"
        result = "PASS" if ok else f"FAIL:{item.get('reason', 'unknown')}"
        sha_status = "ok" if item.get("sha256_ok") else "bad"
        size_status = "ok" if item.get("size_ok") else "bad"
        lines.append(
            f"| {result} | `{item.get('name', '')}` | {size_status} | "
            f"{sha_status} | `{item.get('path', '')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def build_agent_reliability_frontier(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity = verify_release_pack(manifest_path)
    return _build_agent_reliability_frontier_payload(manifest, manifest_path=manifest_path, integrity=integrity)


def _build_agent_reliability_frontier_payload(manifest: dict, *, manifest_path: Path, integrity: dict) -> dict:
    metrics = dict(manifest.get("metrics") or {})
    artifact_count = len(manifest.get("artifacts") or [])
    profiles = [
        _agent_frontier_profile(
            "graph_mcts_retrieval",
            "Graph-MCTS Retrieval",
            "Route-anchored graph search and hard-negative retrieval.",
            {
                "reliability": _mean(
                    _metric(metrics, "counterfactual_graph_mcts_top1"),
                    _metric(metrics, "proof_attack_graph_mcts_top1"),
                ),
                "robustness": _mean(
                    1.0 - _metric(metrics, "counterfactual_graph_mcts_distractor_top1"),
                    1.0 - _metric(metrics, "proof_attack_graph_mcts_distractor_top1"),
                    _metric(metrics, "proof_attack_resistance_rate"),
                ),
                "evidence": _mean(_metric(metrics, "proof_attack_proof_proved_rate"), 0.72),
                "adaptivity": 0.38,
                "governance": 0.58,
                "efficiency": 0.86,
            },
            [
                "Counterfactual hard negatives",
                "Route-family graph priors",
                "Proof attack resistance",
            ],
            ["Static scoring can miss post-policy failures without the proof attack loop."],
        ),
        _agent_frontier_profile(
            "proof_contract_stack",
            "Proof Contract Stack",
            "Proof-carrying retrieval, strict replay, mutation lab, and PR contract governance.",
            {
                "reliability": _score_metric(metrics, "proof_score"),
                "robustness": _metric(metrics, "mutation_detection_rate"),
                "evidence": _mean(
                    _score_metric(metrics, "proof_score"),
                    _ratio_metric(metrics, "contract_passed_checks", "contract_total_checks"),
                ),
                "adaptivity": 0.56,
                "governance": _mean(
                    _status_metric(metrics, "contract_status", "valid"),
                    _status_metric(metrics, "pr_guard_status", "warn"),
                    _status_metric(metrics, "pr_guard_status", "pass"),
                ),
                "efficiency": 0.74,
            },
            [
                "Strict proof replay",
                "Mutation detection",
                "Executable proof regression contracts",
            ],
            ["Contract migration still requires human review after successor inference."],
        ),
        _agent_frontier_profile(
            "adversarial_minimax_loop",
            "Adversarial Minimax Loop",
            "Generated proof attacks, defense policy synthesis, adaptive attacks, repair, and certificate.",
            {
                "reliability": _score_metric(metrics, "proof_attack_certificate_score"),
                "robustness": _mean(
                    _metric(metrics, "proof_attack_resistance_rate"),
                    _metric(metrics, "proof_attack_mitigated_decoy_rate"),
                    _score_metric(metrics, "proof_attack_score"),
                ),
                "evidence": _ratio_metric(
                    metrics,
                    "proof_attack_certificate_passed_claims",
                    "proof_attack_certificate_claims",
                ),
                "adaptivity": _mean(
                    _status_metric(metrics, "proof_attack_adaptive_status", "adaptive_gap_found"),
                    _metric(metrics, "proof_attack_repair_coverage"),
                    1.0 - min(_metric(metrics, "proof_attack_adaptive_policy_coverage"), 1.0),
                ),
                "governance": _mean(
                    _status_metric(metrics, "proof_attack_scorecard_status", "pass"),
                    _status_metric(metrics, "proof_attack_certificate_status", "accepted"),
                    min(1.0, float(metrics.get("proof_attack_triage_actions", 0)) / 6.0),
                ),
                "efficiency": 0.61,
            },
            [
                "Spec-driven red-team mutations",
                "Counterexample-guided policy synthesis",
                "Adaptive repair certificate",
            ],
            ["The loop intentionally reports refinement pressure instead of hiding residual work."],
        ),
        _agent_frontier_profile(
            "temporal_repair_loop",
            "Temporal Repair Loop",
            "Replay proof contracts across git history and infer successor evidence after drift.",
            {
                "reliability": _score_metric(metrics, "temporal_repair_score"),
                "robustness": _mean(
                    _metric(metrics, "temporal_repair_abstention_accuracy"),
                    1.0 - _metric(metrics, "temporal_repair_false_repair_rate"),
                    _metric(metrics, "temporal_repair_causal_delta_rate"),
                ),
                "evidence": _mean(
                    _status_metric(metrics, "proof_graph_delta_status", "causal_relink_found"),
                    min(1.0, float(metrics.get("proof_graph_delta_successor_relinks", 0)) / max(float(metrics.get("proof_graph_delta_broken_edges", 1)), 1.0)),
                ),
                "adaptivity": _mean(
                    _metric(metrics, "temporal_repair_successor_top1"),
                    _metric(metrics, "temporal_repair_migration_ready_rate"),
                ),
                "governance": _status_metric(metrics, "temporal_repair_scorecard_status", "pass"),
                "efficiency": 0.57,
            },
            [
                "First failing commit attribution",
                "Causal proof graph delta",
                "Successor inference with abstention",
            ],
            ["Temporal repair is heavier than single-run replay because it evaluates history snapshots."],
        ),
        _agent_frontier_profile(
            "multi_agent_evidence_court",
            "Multi-Agent Evidence Court",
            "Specialized verifier and skeptic agents publish hashed claims before arbitration.",
            {
                "reliability": _score_metric(metrics, "agent_court_score"),
                "robustness": _ratio_metric(metrics, "agent_court_discharged_challenges", "agent_court_challenges"),
                "evidence": _mean(
                    _ratio_metric(metrics, "agent_court_claims", "agent_court_claims"),
                    _ratio_metric(metrics, "agent_court_discharged_challenges", "agent_court_challenges"),
                ),
                "adaptivity": 0.72,
                "governance": _status_metric(metrics, "agent_court_status", "accepted"),
                "efficiency": 0.52,
            },
            [
                "Role-specialized claim ledger",
                "Challenge discharge instead of consensus voting",
                "Arbiter verdict",
            ],
            ["Court quality depends on the strength of upstream proof, attack, and temporal scorecards."],
        ),
        _agent_frontier_profile(
            "release_integrity_mesh",
            "Release Integrity Mesh",
            "Tamper-evident artifact manifest and release-pack verification.",
            {
                "reliability": _ratio(integrity.get("verified_count", 0), integrity.get("artifact_count", 0)),
                "robustness": 1.0 if integrity.get("valid") else 0.0,
                "evidence": min(1.0, artifact_count / 50.0),
                "adaptivity": 0.24,
                "governance": 1.0 if integrity.get("valid") else 0.0,
                "efficiency": 0.69,
            },
            [
                "SHA-256 artifact ledger",
                "Byte-size verification",
                "Reproducible demo pack",
            ],
            ["Integrity proves artifact custody, not semantic correctness by itself."],
        ),
    ]
    frontier_ids = _agent_frontier_pareto_ids(profiles)
    frontier_profiles = [profile for profile in profiles if profile["id"] in frontier_ids]
    overall_score = int(round(100 * _mean(*(profile["score"] / 100.0 for profile in frontier_profiles)))) if frontier_profiles else 0
    dimension_means = {
        dimension: round(_mean(*(profile["dimensions"][dimension] for profile in profiles)), 4)
        for dimension in AGENT_FRONTIER_DIMENSIONS
    }
    weakest_dimensions = sorted(dimension_means.items(), key=lambda item: item[1])[:2]
    return {
        "schema_version": "1.0",
        "strategy": "agent_reliability_frontier",
        "manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256_file(manifest_path) if manifest_path.is_file() else "",
        "status": "accepted" if integrity.get("valid") and frontier_profiles else "needs_attention",
        "score": overall_score,
        "grade": _temporal_repair_grade(overall_score),
        "dimensions": list(AGENT_FRONTIER_DIMENSIONS),
        "summary": {
            "profile_count": len(profiles),
            "frontier_count": len(frontier_profiles),
            "frontier_ids": frontier_ids,
            "artifact_count": artifact_count,
            "integrity_valid": bool(integrity.get("valid")),
            "dimension_means": dimension_means,
            "weakest_dimensions": [{"dimension": name, "score": score} for name, score in weakest_dimensions],
        },
        "profiles": profiles,
        "frontier": frontier_profiles,
    }


AGENT_FRONTIER_DIMENSIONS = ("reliability", "robustness", "evidence", "adaptivity", "governance", "efficiency")


def render_agent_frontier_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Reliability Frontier",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Frontier profiles: `{summary.get('frontier_count', 0)}/{summary.get('profile_count', 0)}`",
        f"- Integrity valid: `{summary.get('integrity_valid', False)}`",
        "",
        "## Pareto Frontier",
        "",
        "| Profile | Score | Reliability | Robustness | Evidence | Adaptivity | Governance | Efficiency | Cost Proxy |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for profile in payload.get("frontier", []):
        dims = profile.get("dimensions") or {}
        lines.append(
            f"| `{profile.get('name', '')}` | {int(profile.get('score', 0))} | "
            f"{float(dims.get('reliability', 0.0)):.2f} | {float(dims.get('robustness', 0.0)):.2f} | "
            f"{float(dims.get('evidence', 0.0)):.2f} | {float(dims.get('adaptivity', 0.0)):.2f} | "
            f"{float(dims.get('governance', 0.0)):.2f} | {float(dims.get('efficiency', 0.0)):.2f} | "
            f"{float(profile.get('cost_proxy', 0.0)):.2f} |"
        )
    lines.extend(["", "## All Profiles", "", "| Profile | Dominated | Score | Evidence Hash | Bottlenecks |", "| --- | --- | ---: | --- | --- |"])
    for profile in payload.get("profiles", []):
        bottlenecks = ", ".join(item["dimension"] for item in profile.get("bottlenecks", [])) or "-"
        lines.append(
            f"| `{profile.get('name', '')}` | `{profile.get('dominated', False)}` | "
            f"{int(profile.get('score', 0))} | `{profile.get('evidence_hash', '')}` | {bottlenecks} |"
        )
    lines.extend(["", "## Weakest Dimensions", "", "| Dimension | Mean Score |", "| --- | ---: |"])
    for item in summary.get("weakest_dimensions", []):
        lines.append(f"| `{item.get('dimension', '')}` | {float(item.get('score', 0.0)):.2f} |")
    lines.append("")
    return "\n".join(lines)


def write_agent_frontier_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_agent_frontier_markdown(payload), encoding="utf-8")
    return output_path


def build_agent_frontier_ablation(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = build_agent_reliability_frontier(manifest_path)
    integrity = verify_release_pack(manifest_path)
    ablations = []
    for family in AGENT_FRONTIER_ABLATION_FAMILIES:
        ablations.append(_run_agent_frontier_ablation(manifest, manifest_path=manifest_path, baseline=baseline, family=family, integrity=integrity))
    ablations.sort(key=lambda item: (item["score_drop"], item["frontier_loss"], item["profile_score_drop"]), reverse=True)
    top_driver = ablations[0] if ablations else {}
    return {
        "schema_version": "1.0",
        "strategy": "agent_frontier_causal_ablation",
        "manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256_file(manifest_path) if manifest_path.is_file() else "",
        "status": "attributed" if baseline.get("status") == "accepted" and ablations else "needs_attention",
        "baseline": {
            "status": baseline.get("status", ""),
            "score": baseline.get("score", 0),
            "grade": baseline.get("grade", ""),
            "frontier_count": (baseline.get("summary") or {}).get("frontier_count", 0),
            "frontier_ids": (baseline.get("summary") or {}).get("frontier_ids", []),
            "weakest_dimensions": (baseline.get("summary") or {}).get("weakest_dimensions", []),
        },
        "summary": {
            "ablation_count": len(ablations),
            "top_driver": top_driver.get("id", ""),
            "max_score_drop": top_driver.get("score_drop", 0),
            "max_frontier_loss": max((item.get("frontier_loss", 0) for item in ablations), default=0),
            "protected_families": [item["id"] for item in ablations if item.get("score_drop", 0) >= 5 or item.get("frontier_loss", 0) > 0],
        },
        "ablations": ablations,
    }


def _run_agent_frontier_ablation(manifest: dict, *, manifest_path: Path, baseline: dict, family: dict, integrity: dict | None = None) -> dict:
    masked_manifest = json.loads(json.dumps(manifest))
    metrics = dict(masked_manifest.get("metrics") or {})
    for key, value in family.get("mask", {}).items():
        metrics[key] = value
    masked_manifest["metrics"] = metrics
    integrity = dict(integrity or verify_release_pack(manifest_path))
    if family.get("id") == "release_integrity_mesh":
        integrity = dict(integrity)
        integrity["valid"] = False
        integrity["verified_count"] = 0
    ablated = _build_agent_reliability_frontier_payload(masked_manifest, manifest_path=manifest_path, integrity=integrity)
    baseline_score = int(baseline.get("score", 0))
    ablated_score = int(ablated.get("score", 0))
    baseline_frontier = set((baseline.get("summary") or {}).get("frontier_ids", []))
    ablated_frontier = set((ablated.get("summary") or {}).get("frontier_ids", []))
    baseline_profile = _agent_frontier_profile_by_id(baseline, family["profile_id"])
    ablated_profile = _agent_frontier_profile_by_id(ablated, family["profile_id"])
    artifact_count = _agent_frontier_family_artifact_count(manifest, family.get("artifact_prefixes", ()))
    score_drop = max(0, baseline_score - ablated_score)
    profile_score_drop = max(0, int((baseline_profile or {}).get("score", 0)) - int((ablated_profile or {}).get("score", 0)))
    removed = sorted(baseline_frontier - ablated_frontier)
    added = sorted(ablated_frontier - baseline_frontier)
    return {
        "id": family["id"],
        "name": family["name"],
        "profile_id": family["profile_id"],
        "artifact_count": artifact_count,
        "masked_metrics": sorted(family.get("mask", {}).keys()),
        "baseline_score": baseline_score,
        "ablated_score": ablated_score,
        "score_drop": score_drop,
        "baseline_profile_score": int((baseline_profile or {}).get("score", 0)),
        "ablated_profile_score": int((ablated_profile or {}).get("score", 0)),
        "profile_score_drop": profile_score_drop,
        "baseline_frontier_count": len(baseline_frontier),
        "ablated_frontier_count": len(ablated_frontier),
        "frontier_loss": max(0, len(baseline_frontier) - len(ablated_frontier)),
        "frontier_removed": removed,
        "frontier_added": added,
        "dominance_changed": bool(removed or added),
        "primary_dimension": family["primary_dimension"],
        "recommendation": _agent_frontier_ablation_recommendation(family, score_drop, profile_score_drop, removed),
        "evidence_hash": _stable_short_hash(
            {
                "family": family["id"],
                "score_drop": score_drop,
                "profile_score_drop": profile_score_drop,
                "removed": removed,
                "added": added,
            }
        ),
    }


def render_agent_frontier_ablation_markdown(payload: dict) -> str:
    baseline = dict(payload.get("baseline") or {})
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Frontier Causal Ablation",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Baseline score: `{int(baseline.get('score', 0))}/100` (`{baseline.get('grade', '')}`)",
        f"- Baseline frontier: `{int(baseline.get('frontier_count', 0))}` profiles",
        f"- Ablations: `{int(summary.get('ablation_count', 0))}`",
        f"- Top evidence driver: `{summary.get('top_driver', '')}` (`-{int(summary.get('max_score_drop', 0))}` score)",
        "",
        "## Evidence-Family Ablations",
        "",
        "| Family | Score Drop | Profile Drop | Frontier Loss | Artifacts | Evidence | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in payload.get("ablations", []):
        lines.append(
            f"| `{item.get('name', '')}` | {int(item.get('score_drop', 0))} | "
            f"{int(item.get('profile_score_drop', 0))} | {int(item.get('frontier_loss', 0))} | "
            f"{int(item.get('artifact_count', 0))} | `{item.get('evidence_hash', '')}` | "
            f"{item.get('recommendation', '')} |"
        )
    lines.extend(["", "## Protected Families", ""])
    protected = summary.get("protected_families", [])
    if protected:
        for family_id in protected:
            lines.append(f"- `{family_id}`")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_agent_frontier_ablation_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_agent_frontier_ablation_markdown(payload), encoding="utf-8")
    return output_path


def build_agent_frontier_interactions(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = build_agent_reliability_frontier(manifest_path)
    single_ablation = build_agent_frontier_ablation(manifest_path)
    single_by_id = {item["id"]: item for item in single_ablation.get("ablations", [])}
    integrity = verify_release_pack(manifest_path)
    interactions = []
    families = list(AGENT_FRONTIER_ABLATION_FAMILIES)
    for left_index, left in enumerate(families):
        for right in families[left_index + 1 :]:
            interactions.append(
                _run_agent_frontier_pairwise_interaction(
                    manifest,
                    manifest_path=manifest_path,
                    baseline=baseline,
                    single_by_id=single_by_id,
                    left=left,
                    right=right,
                    integrity=integrity,
                )
            )
    interactions.sort(key=lambda item: (item["synergy"], item["observed_drop"], item["frontier_loss"]), reverse=True)
    top_interaction = interactions[0] if interactions else {}
    return {
        "schema_version": "1.0",
        "strategy": "agent_frontier_evidence_interaction_matrix",
        "manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256_file(manifest_path) if manifest_path.is_file() else "",
        "status": "mapped" if baseline.get("status") == "accepted" and interactions else "needs_attention",
        "baseline": {
            "score": baseline.get("score", 0),
            "grade": baseline.get("grade", ""),
            "frontier_count": (baseline.get("summary") or {}).get("frontier_count", 0),
            "frontier_ids": (baseline.get("summary") or {}).get("frontier_ids", []),
        },
        "summary": {
            "family_count": len(families),
            "pair_count": len(interactions),
            "top_interaction": top_interaction.get("id", ""),
            "max_synergy": top_interaction.get("synergy", 0),
            "max_observed_drop": max((item.get("observed_drop", 0) for item in interactions), default=0),
            "fragile_pair_count": sum(1 for item in interactions if item.get("fragile")),
            "fragile_pairs": [item["id"] for item in interactions if item.get("fragile")],
        },
        "interactions": interactions,
    }


def _run_agent_frontier_pairwise_interaction(
    manifest: dict,
    *,
    manifest_path: Path,
    baseline: dict,
    single_by_id: dict,
    left: dict,
    right: dict,
    integrity: dict | None = None,
) -> dict:
    masked_manifest = json.loads(json.dumps(manifest))
    metrics = dict(masked_manifest.get("metrics") or {})
    for family in (left, right):
        for key, value in family.get("mask", {}).items():
            metrics[key] = value
    masked_manifest["metrics"] = metrics
    integrity = dict(integrity or verify_release_pack(manifest_path))
    if left.get("id") == "release_integrity_mesh" or right.get("id") == "release_integrity_mesh":
        integrity = dict(integrity)
        integrity["valid"] = False
        integrity["verified_count"] = 0
    paired = _build_agent_reliability_frontier_payload(masked_manifest, manifest_path=manifest_path, integrity=integrity)
    baseline_score = int(baseline.get("score", 0))
    paired_score = int(paired.get("score", 0))
    observed_drop = max(0, baseline_score - paired_score)
    expected_drop = int(single_by_id.get(left["id"], {}).get("score_drop", 0)) + int(single_by_id.get(right["id"], {}).get("score_drop", 0))
    synergy = observed_drop - expected_drop
    baseline_frontier = set((baseline.get("summary") or {}).get("frontier_ids", []))
    paired_frontier = set((paired.get("summary") or {}).get("frontier_ids", []))
    removed = sorted(baseline_frontier - paired_frontier)
    added = sorted(paired_frontier - baseline_frontier)
    left_profile = _agent_frontier_profile_by_id(baseline, left["profile_id"]) or {}
    right_profile = _agent_frontier_profile_by_id(baseline, right["profile_id"]) or {}
    paired_left_profile = _agent_frontier_profile_by_id(paired, left["profile_id"]) or {}
    paired_right_profile = _agent_frontier_profile_by_id(paired, right["profile_id"]) or {}
    left_profile_drop = max(0, int(left_profile.get("score", 0)) - int(paired_left_profile.get("score", 0)))
    right_profile_drop = max(0, int(right_profile.get("score", 0)) - int(paired_right_profile.get("score", 0)))
    fragile = synergy > 0 or observed_drop >= 10 or bool(removed)
    interaction_id = f"{left['id']}__{right['id']}"
    return {
        "id": interaction_id,
        "left": left["id"],
        "right": right["id"],
        "left_name": left["name"],
        "right_name": right["name"],
        "baseline_score": baseline_score,
        "paired_score": paired_score,
        "observed_drop": observed_drop,
        "expected_additive_drop": expected_drop,
        "synergy": synergy,
        "interaction_type": _agent_frontier_interaction_type(synergy, removed, observed_drop),
        "frontier_loss": max(0, len(baseline_frontier) - len(paired_frontier)),
        "frontier_removed": removed,
        "frontier_added": added,
        "left_profile_drop": left_profile_drop,
        "right_profile_drop": right_profile_drop,
        "fragile": fragile,
        "recommendation": _agent_frontier_interaction_recommendation(left, right, synergy, observed_drop, removed),
        "evidence_hash": _stable_short_hash(
            {
                "id": interaction_id,
                "observed_drop": observed_drop,
                "expected": expected_drop,
                "synergy": synergy,
                "removed": removed,
            }
        ),
    }


def render_agent_frontier_interactions_markdown(payload: dict) -> str:
    baseline = dict(payload.get("baseline") or {})
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Evidence Interaction Matrix",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Baseline score: `{int(baseline.get('score', 0))}/100` (`{baseline.get('grade', '')}`)",
        f"- Evidence families: `{int(summary.get('family_count', 0))}`",
        f"- Pairwise counterfactuals: `{int(summary.get('pair_count', 0))}`",
        f"- Top interaction: `{summary.get('top_interaction', '')}` (synergy `{int(summary.get('max_synergy', 0))}`)",
        f"- Fragile pairs: `{int(summary.get('fragile_pair_count', 0))}`",
        "",
        "## Pairwise Interactions",
        "",
        "| Pair | Observed Drop | Expected Drop | Synergy | Type | Frontier Loss | Evidence | Recommendation |",
        "| --- | ---: | ---: | ---: | --- | ---: | --- | --- |",
    ]
    for item in payload.get("interactions", []):
        pair = f"{item.get('left', '')} + {item.get('right', '')}"
        lines.append(
            f"| `{pair}` | {int(item.get('observed_drop', 0))} | "
            f"{int(item.get('expected_additive_drop', 0))} | {int(item.get('synergy', 0))} | "
            f"`{item.get('interaction_type', '')}` | {int(item.get('frontier_loss', 0))} | "
            f"`{item.get('evidence_hash', '')}` | {item.get('recommendation', '')} |"
        )
    lines.extend(["", "## Fragile Pairs", ""])
    fragile = summary.get("fragile_pairs", [])
    if fragile:
        for pair_id in fragile:
            lines.append(f"- `{pair_id}`")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_agent_frontier_interactions_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_agent_frontier_interactions_markdown(payload), encoding="utf-8")
    return output_path


def build_agent_frontier_stability(manifest_path: Path, *, samples: int = 64, noise: float = 0.04, seed: int = 7) -> dict:
    sample_count = max(1, min(512, int(samples)))
    noise = max(0.0, min(0.25, float(noise)))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity = verify_release_pack(manifest_path)
    baseline = _build_agent_reliability_frontier_payload(manifest, manifest_path=manifest_path, integrity=integrity)
    baseline_interactions = _build_agent_frontier_interactions_from_manifest(
        manifest,
        manifest_path=manifest_path,
        baseline=baseline,
        integrity=integrity,
    )
    baseline_frontier_ids = set((baseline.get("summary") or {}).get("frontier_ids", []))
    rng = random.Random(seed)
    score_samples = []
    frontier_jaccards = []
    max_synergy_samples = []
    top_interaction_samples = []
    profile_stats = {
        profile["id"]: {
            "id": profile["id"],
            "name": profile["name"],
            "baseline_score": int(profile.get("score", 0)),
            "baseline_frontier": profile["id"] in baseline_frontier_ids,
            "scores": [],
            "frontier_hits": 0,
        }
        for profile in baseline.get("profiles", [])
    }
    interaction_stats = {
        item["id"]: {
            "id": item["id"],
            "left": item["left"],
            "right": item["right"],
            "baseline_synergy": int(item.get("synergy", 0)),
            "baseline_observed_drop": int(item.get("observed_drop", 0)),
            "baseline_type": item.get("interaction_type", ""),
            "synergies": [],
            "observed_drops": [],
            "fragile_hits": 0,
            "top_hits": 0,
        }
        for item in baseline_interactions.get("interactions", [])
    }

    families = list(AGENT_FRONTIER_ABLATION_FAMILIES)
    for _index in range(sample_count):
        sample_manifest = _agent_frontier_perturb_manifest(manifest, rng=rng, noise=noise)
        sample_frontier = _build_agent_reliability_frontier_payload(sample_manifest, manifest_path=manifest_path, integrity=integrity)
        sample_frontier_ids = set((sample_frontier.get("summary") or {}).get("frontier_ids", []))
        score_samples.append(int(sample_frontier.get("score", 0)))
        frontier_jaccards.append(_agent_frontier_jaccard(baseline_frontier_ids, sample_frontier_ids))

        for profile in sample_frontier.get("profiles", []):
            stats = profile_stats.get(profile.get("id"))
            if not stats:
                continue
            stats["scores"].append(int(profile.get("score", 0)))
            if profile.get("id") in sample_frontier_ids:
                stats["frontier_hits"] += 1

        sample_ablations = [
            _run_agent_frontier_ablation(
                sample_manifest,
                manifest_path=manifest_path,
                baseline=sample_frontier,
                family=family,
                integrity=integrity,
            )
            for family in families
        ]
        sample_single_by_id = {item["id"]: item for item in sample_ablations}
        sample_interactions = []
        for left_index, left in enumerate(families):
            for right in families[left_index + 1 :]:
                sample_interactions.append(
                    _run_agent_frontier_pairwise_interaction(
                        sample_manifest,
                        manifest_path=manifest_path,
                        baseline=sample_frontier,
                        single_by_id=sample_single_by_id,
                        left=left,
                        right=right,
                        integrity=integrity,
                    )
                )
        sample_interactions.sort(key=lambda item: (item["synergy"], item["observed_drop"], item["frontier_loss"]), reverse=True)
        if sample_interactions:
            top_interaction_samples.append(sample_interactions[0]["id"])
            max_synergy_samples.append(int(sample_interactions[0].get("synergy", 0)))
        for interaction in sample_interactions:
            stats = interaction_stats.get(interaction["id"])
            if not stats:
                continue
            stats["synergies"].append(int(interaction.get("synergy", 0)))
            stats["observed_drops"].append(int(interaction.get("observed_drop", 0)))
            if interaction.get("fragile"):
                stats["fragile_hits"] += 1
        if sample_interactions:
            interaction_stats[sample_interactions[0]["id"]]["top_hits"] += 1

    profile_stability = []
    for stats in profile_stats.values():
        score_summary = _agent_frontier_numeric_summary(stats["scores"], integer=True)
        frontier_probability = _safe_round(stats["frontier_hits"] / sample_count, 4)
        profile_stability.append(
            {
                "id": stats["id"],
                "name": stats["name"],
                "baseline_score": stats["baseline_score"],
                "baseline_frontier": stats["baseline_frontier"],
                "score_mean": score_summary["mean"],
                "score_ci_low": score_summary["ci_low"],
                "score_ci_high": score_summary["ci_high"],
                "frontier_probability": frontier_probability,
                "dominated_probability": _safe_round(1.0 - frontier_probability, 4),
                "stability": _agent_frontier_profile_stability_label(stats["baseline_frontier"], frontier_probability),
            }
        )
    profile_stability.sort(key=lambda item: (item["baseline_frontier"], item["frontier_probability"], item["score_mean"]), reverse=True)

    interaction_stability = []
    for stats in interaction_stats.values():
        synergy_summary = _agent_frontier_numeric_summary(stats["synergies"], integer=False)
        observed_summary = _agent_frontier_numeric_summary(stats["observed_drops"], integer=False)
        top_probability = _safe_round(stats["top_hits"] / sample_count, 4)
        fragile_probability = _safe_round(stats["fragile_hits"] / sample_count, 4)
        interaction_stability.append(
            {
                "id": stats["id"],
                "left": stats["left"],
                "right": stats["right"],
                "baseline_synergy": stats["baseline_synergy"],
                "baseline_observed_drop": stats["baseline_observed_drop"],
                "baseline_type": stats["baseline_type"],
                "synergy_mean": synergy_summary["mean"],
                "synergy_ci_low": synergy_summary["ci_low"],
                "synergy_ci_high": synergy_summary["ci_high"],
                "observed_drop_mean": observed_summary["mean"],
                "observed_drop_ci_low": observed_summary["ci_low"],
                "observed_drop_ci_high": observed_summary["ci_high"],
                "top_probability": top_probability,
                "fragile_probability": fragile_probability,
                "stability": _agent_frontier_interaction_stability_label(top_probability, fragile_probability, synergy_summary["ci_low"]),
            }
        )
    interaction_stability.sort(key=lambda item: (item["top_probability"], item["fragile_probability"], item["synergy_mean"]), reverse=True)

    score_summary = _agent_frontier_numeric_summary(score_samples, integer=True)
    max_synergy_summary = _agent_frontier_numeric_summary(max_synergy_samples, integer=False)
    top_mode, top_mode_count = _agent_frontier_mode(top_interaction_samples)
    top_probability = _safe_round(top_mode_count / sample_count, 4) if sample_count else 0.0
    frontier_jaccard_mean = _safe_round(_mean(*frontier_jaccards), 4)
    stable_frontier = [item["id"] for item in profile_stability if item["baseline_frontier"] and item["frontier_probability"] >= 0.9]
    unstable_frontier = [item["id"] for item in profile_stability if item["baseline_frontier"] and item["frontier_probability"] < 0.75]
    status = _agent_frontier_stability_status(
        baseline_status=baseline.get("status", ""),
        score_ci_low=score_summary["ci_low"],
        score_ci_high=score_summary["ci_high"],
        frontier_jaccard_mean=frontier_jaccard_mean,
        top_probability=top_probability,
        unstable_frontier_count=len(unstable_frontier),
    )
    return {
        "schema_version": "1.0",
        "strategy": "agent_frontier_uncertainty_bootstrap",
        "manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256_file(manifest_path) if manifest_path.is_file() else "",
        "status": status,
        "baseline": {
            "score": baseline.get("score", 0),
            "grade": baseline.get("grade", ""),
            "frontier_count": (baseline.get("summary") or {}).get("frontier_count", 0),
            "frontier_ids": (baseline.get("summary") or {}).get("frontier_ids", []),
            "top_interaction": (baseline_interactions.get("summary") or {}).get("top_interaction", ""),
            "max_synergy": (baseline_interactions.get("summary") or {}).get("max_synergy", 0),
        },
        "bootstrap": {
            "sample_count": sample_count,
            "noise": noise,
            "seed": seed,
            "perturbation": "uniform bounded noise over normalized metrics and score metrics",
        },
        "summary": {
            "sample_count": sample_count,
            "score_mean": score_summary["mean"],
            "score_ci_low": score_summary["ci_low"],
            "score_ci_high": score_summary["ci_high"],
            "score_ci_width": int(score_summary["ci_high"] - score_summary["ci_low"]),
            "frontier_jaccard_mean": frontier_jaccard_mean,
            "stable_frontier_count": len(stable_frontier),
            "stable_frontier_profiles": stable_frontier,
            "unstable_frontier_count": len(unstable_frontier),
            "unstable_frontier_profiles": unstable_frontier,
            "top_interaction_mode": top_mode,
            "top_interaction_probability": top_probability,
            "max_synergy_mean": max_synergy_summary["mean"],
            "max_synergy_ci_low": max_synergy_summary["ci_low"],
            "max_synergy_ci_high": max_synergy_summary["ci_high"],
            "evidence_hash": _stable_short_hash(
                {
                    "score": score_summary,
                    "frontier_jaccard": frontier_jaccard_mean,
                    "top": top_mode,
                    "top_probability": top_probability,
                    "seed": seed,
                    "noise": noise,
                }
            ),
        },
        "profiles": profile_stability,
        "interactions": interaction_stability,
    }


def _build_agent_frontier_interactions_from_manifest(manifest: dict, *, manifest_path: Path, baseline: dict, integrity: dict) -> dict:
    ablations = [
        _run_agent_frontier_ablation(
            manifest,
            manifest_path=manifest_path,
            baseline=baseline,
            family=family,
            integrity=integrity,
        )
        for family in AGENT_FRONTIER_ABLATION_FAMILIES
    ]
    single_by_id = {item["id"]: item for item in ablations}
    interactions = []
    families = list(AGENT_FRONTIER_ABLATION_FAMILIES)
    for left_index, left in enumerate(families):
        for right in families[left_index + 1 :]:
            interactions.append(
                _run_agent_frontier_pairwise_interaction(
                    manifest,
                    manifest_path=manifest_path,
                    baseline=baseline,
                    single_by_id=single_by_id,
                    left=left,
                    right=right,
                    integrity=integrity,
                )
            )
    interactions.sort(key=lambda item: (item["synergy"], item["observed_drop"], item["frontier_loss"]), reverse=True)
    top_interaction = interactions[0] if interactions else {}
    return {
        "summary": {
            "top_interaction": top_interaction.get("id", ""),
            "max_synergy": top_interaction.get("synergy", 0),
        },
        "interactions": interactions,
    }


def render_agent_frontier_stability_markdown(payload: dict) -> str:
    baseline = dict(payload.get("baseline") or {})
    summary = dict(payload.get("summary") or {})
    bootstrap = dict(payload.get("bootstrap") or {})
    lines = [
        "# Repo Agent Frontier Stability Lab",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Baseline score: `{int(baseline.get('score', 0))}/100` (`{baseline.get('grade', '')}`)",
        f"- Samples: `{int(bootstrap.get('sample_count', 0))}`",
        f"- Noise: `{float(bootstrap.get('noise', 0.0)):.2%}`",
        f"- Seed: `{int(bootstrap.get('seed', 0))}`",
        f"- Score mean: `{float(summary.get('score_mean', 0.0)):.1f}`",
        f"- Score 95% CI: `{int(summary.get('score_ci_low', 0))}-{int(summary.get('score_ci_high', 0))}`",
        f"- Frontier Jaccard mean: `{float(summary.get('frontier_jaccard_mean', 0.0)):.2f}`",
        f"- Top interaction mode: `{summary.get('top_interaction_mode', '')}` @ `{float(summary.get('top_interaction_probability', 0.0)):.2%}`",
        f"- Max synergy 95% CI: `{float(summary.get('max_synergy_ci_low', 0.0)):.1f}-{float(summary.get('max_synergy_ci_high', 0.0)):.1f}`",
        f"- Evidence hash: `{summary.get('evidence_hash', '')}`",
        "",
        "## Profile Stability",
        "",
        "| Profile | Baseline Frontier | Frontier Probability | Score Mean | Score CI | Stability |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in payload.get("profiles", []):
        lines.append(
            f"| `{item.get('name', '')}` | `{item.get('baseline_frontier', False)}` | "
            f"{float(item.get('frontier_probability', 0.0)):.2%} | "
            f"{float(item.get('score_mean', 0.0)):.1f} | "
            f"`{int(item.get('score_ci_low', 0))}-{int(item.get('score_ci_high', 0))}` | "
            f"`{item.get('stability', '')}` |"
        )
    lines.extend(
        [
            "",
            "## Interaction Stability",
            "",
            "| Pair | Top Probability | Fragile Probability | Synergy Mean | Synergy CI | Observed Drop Mean | Stability |",
            "| --- | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for item in payload.get("interactions", []):
        pair = f"{item.get('left', '')} + {item.get('right', '')}"
        lines.append(
            f"| `{pair}` | {float(item.get('top_probability', 0.0)):.2%} | "
            f"{float(item.get('fragile_probability', 0.0)):.2%} | "
            f"{float(item.get('synergy_mean', 0.0)):.1f} | "
            f"`{float(item.get('synergy_ci_low', 0.0)):.1f}-{float(item.get('synergy_ci_high', 0.0)):.1f}` | "
            f"{float(item.get('observed_drop_mean', 0.0)):.1f} | "
            f"`{item.get('stability', '')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def write_agent_frontier_stability_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_agent_frontier_stability_markdown(payload), encoding="utf-8")
    return output_path


def build_agent_artifact_review(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics = dict(manifest.get("metrics") or {})
    integrity = verify_release_pack(manifest_path)
    claims = [
        _agent_artifact_claim(
            "route_grounded_retrieval",
            "Route-grounded Graph-MCTS retrieval resists hard-negative route and writer decoys.",
            "retrieval",
            metrics,
            checks=[
                _claim_check("counterfactual_graph_mcts_top1", metrics.get("counterfactual_graph_mcts_top1"), ">=", 1.0, "counterfactual Top-1"),
                _claim_check("counterfactual_graph_mcts_distractor_top1", metrics.get("counterfactual_graph_mcts_distractor_top1"), "<=", 0.0, "counterfactual distractor@1"),
                _claim_check("proof_attack_graph_mcts_top1", metrics.get("proof_attack_graph_mcts_top1"), ">=", 1.0, "generated attack Top-1"),
                _claim_check("proof_attack_graph_mcts_distractor_top1", metrics.get("proof_attack_graph_mcts_distractor_top1"), "<=", 0.0, "generated attack distractor@1"),
            ],
            artifacts=("ablation_report", "counterfactual_report", "proof_attack_benchmark_json", "proof_attack_benchmark"),
            validation_commands=(
                "python -m repo_agent ablate --output reports/ablation-report.md",
                "python -m repo_agent counterfactual --output reports/counterfactual-report.md",
                "python -m repo_agent proof-attack --output-dir reports/proof-attack-benchmark --output reports/proof-attack-benchmark.md",
            ),
            falsifiers=(
                "Graph-MCTS Top-1 drops below 100% on bundled hard-negative cases.",
                "Any generated decoy becomes rank-1 for the public /api/chat writer query.",
                "A new same-route-family decoy is not represented in the proof decoy audit.",
            ),
            limitations=("Bundled cases are adversarial but small; external multi-repository benchmarks are still needed.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "portable_generalization_adapter",
            "The evaluation protocol can ingest portable benchmark suites and report cross-repository generalization gaps.",
            "external_validity",
            metrics,
            checks=[
                _claim_check("benchmark_adapter_status", metrics.get("benchmark_adapter_status"), "in", ("pass", "needs_attention"), "adapter status"),
                _claim_check("benchmark_adapter_cases", metrics.get("benchmark_adapter_cases"), ">=", 10, "portable case count"),
                _claim_check("benchmark_adapter_repo_groups", metrics.get("benchmark_adapter_repo_groups"), ">=", 4, "repository coverage"),
                _claim_check("benchmark_adapter_tag_groups", metrics.get("benchmark_adapter_tag_groups"), ">=", 8, "tag coverage"),
                _claim_check("benchmark_adapter_top3", metrics.get("benchmark_adapter_top3"), ">=", 0.75, "challenge-suite Top-3 floor"),
                _claim_check("benchmark_adapter_top1", metrics.get("benchmark_adapter_top1"), ">=", 0.40, "challenge-suite Top-1 floor"),
                _claim_check("benchmark_adapter_distractor_top1", metrics.get("benchmark_adapter_distractor_top1"), "<=", 0.07, "challenge-suite distractor@1 ceiling"),
                _claim_check("benchmark_diagnostics_status", metrics.get("benchmark_diagnostics_status"), "in", ("clean", "actionable", "blocked"), "diagnostics status"),
                _claim_check("benchmark_diagnostics_taxonomy_count", metrics.get("benchmark_diagnostics_taxonomy_count"), ">=", 0, "diagnostic taxonomy"),
                _claim_check("benchmark_diagnostics_projected_top1", metrics.get("benchmark_diagnostics_projected_top1"), ">=", metrics.get("benchmark_adapter_top1", 0.0), "recoverable Top-1 ceiling"),
                _claim_check("benchmark_repair_status", metrics.get("benchmark_repair_status"), "in", ("validated", "needs_repair"), "repair card"),
                _claim_check("benchmark_repair_passed_guards", metrics.get("benchmark_repair_passed_guards"), "==", metrics.get("benchmark_repair_guards"), "repair guards"),
            ],
            artifacts=("benchmark_adapter_json", "benchmark_adapter", "benchmark_diagnostics_json", "benchmark_diagnostics", "benchmark_repair_json", "benchmark_repair"),
            validation_commands=(
                "python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.md",
                "python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json --json",
                "python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-adapter.json --output reports/benchmark-diagnostics.md",
                "python -m repo_agent benchmark-repair-card --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-card.md",
            ),
            falsifiers=(
                "A third-party suite cannot be represented as repo/question/expected symbol cases.",
                "A repository or tag group falls below the Top-3 threshold without being surfaced as a generalization gap.",
                "Rank-1 distractors exceed the challenge-suite ceiling without creating a repair action.",
                "The diagnostics report cannot explain weak Top-1 cases or projects an unrealizable repair ceiling.",
            ),
            limitations=(
                "The bundled portable suite is intentionally challenging; nonzero gaps are preserved as repair evidence rather than hidden as pass/fail noise.",
            ),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "counterexample_guided_retrieval_repair",
            "Portable benchmark traces can be converted into auditable retrieval-repair rules, implementation anchors, compiled interventions, and patch/ablation experiments.",
            "self_improvement",
            metrics,
            checks=[
                _claim_check("benchmark_repair_synthesis_status", metrics.get("benchmark_repair_synthesis_status"), "in", ("validated", "repair_plan"), "repair synthesis status"),
                _claim_check("benchmark_repair_synthesis_score", metrics.get("benchmark_repair_synthesis_score"), ">=", 40, "repair synthesis score"),
                _claim_check("benchmark_repair_synthesis_candidates", metrics.get("benchmark_repair_synthesis_candidates"), ">=", 5, "repair candidates"),
                _claim_check("benchmark_repair_synthesis_active_rules", int(metrics.get("benchmark_repair_synthesis_validated_rules", 0)) + int(metrics.get("benchmark_repair_synthesis_proposed_rules", 0)), ">=", 2, "validated or proposed rules"),
                _claim_check("benchmark_repair_synthesis_projected_top1", metrics.get("benchmark_repair_synthesis_projected_top1"), ">=", metrics.get("benchmark_adapter_top1", 0.0), "projected Top-1 replay"),
                _claim_check("benchmark_repair_implementation_status", metrics.get("benchmark_repair_implementation_status"), "in", ("verified", "implementation_plan"), "implementation verification"),
                _claim_check("benchmark_repair_implementation_implemented_rules", metrics.get("benchmark_repair_implementation_implemented_rules"), "<=", metrics.get("benchmark_repair_synthesis_validated_rules"), "implemented validated rules"),
                _claim_check("benchmark_repair_implementation_missing_rules", metrics.get("benchmark_repair_implementation_missing_rules"), "==", 0, "missing validated implementations"),
                _claim_check("benchmark_repair_compiler_status", metrics.get("benchmark_repair_compiler_status"), "in", ("compiled_noop_verified", "patch_plan_ready"), "compiled repair IR"),
                _claim_check("benchmark_repair_compiler_patch_required", metrics.get("benchmark_repair_compiler_patch_required"), ">=", 0, "open compiled patches"),
                _claim_check("benchmark_repair_compiler_regression_locks", metrics.get("benchmark_repair_compiler_regression_locks"), "==", metrics.get("benchmark_repair_synthesis_validated_rules"), "compiled regression locks"),
                _claim_check("benchmark_repair_compiler_ablation_toggles", metrics.get("benchmark_repair_compiler_ablation_toggles"), ">=", int(metrics.get("benchmark_repair_synthesis_validated_rules", 0)) + int(metrics.get("benchmark_repair_synthesis_proposed_rules", 0)), "compiled ablation toggles"),
                _claim_check("benchmark_repair_workbench_status", metrics.get("benchmark_repair_workbench_status"), "==", "patch_workbench_ready", "patch workbench"),
                _claim_check("benchmark_repair_workbench_patch_candidates", metrics.get("benchmark_repair_workbench_patch_candidates"), ">=", metrics.get("benchmark_repair_compiler_ablation_toggles", 0), "patch candidates"),
                _claim_check("benchmark_repair_workbench_experiments", metrics.get("benchmark_repair_workbench_experiments"), ">=", metrics.get("benchmark_repair_compiler_ablation_toggles", 0), "ablation experiments"),
            ],
            artifacts=(
                "benchmark_repair_synthesis_json",
                "benchmark_repair_synthesis",
                "benchmark_repair_implementation_json",
                "benchmark_repair_implementation",
                "benchmark_repair_compiler_json",
                "benchmark_repair_compiler",
                "benchmark_repair_workbench_json",
                "benchmark_repair_workbench",
                "benchmark_adapter_json",
                "benchmark_repair_json",
            ),
            validation_commands=(
                "python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.md",
                "python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.md",
                "python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.md",
                "python -m repo_agent benchmark-repair-workbench --compiler reports/benchmark-repair-compiler.json --output reports/benchmark-repair-workbench.md",
                "python -m repo_agent benchmark-repair-card --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-card.md",
            ),
            falsifiers=(
                "A failed portable benchmark case yields no proposed rule despite the expected answer being present in Top-k.",
                "A synthesized rule cannot name affected cases, validation cases, and a concrete rule DSL.",
                "A rule is marked validated without an explicit top-hit reason in the benchmark trace.",
                "A validated rule cannot be mapped to concrete reranker helpers or emitted reason literals.",
                "A validated implementation cannot be compiled into a deterministic intervention, regression lock, and ablation toggle.",
                "A compiled intervention cannot generate a reviewable patch candidate or single-rule ablation experiment.",
            ),
            limitations=("The compiler and workbench emit auditable source-level intervention IR, patch candidates, and validation commands; applying code patches still requires reviewer approval.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "proof_carrying_retrieval",
            "The selected answer is backed by replayable proof, mutation checks, and executable regression contracts.",
            "verification",
            metrics,
            checks=[
                _claim_check("proof_score", metrics.get("proof_score"), ">=", 95, "proof score"),
                _claim_check("mutation_detection_rate", metrics.get("mutation_detection_rate"), ">=", 1.0, "mutation detection"),
                _claim_check("contract_status", metrics.get("contract_status"), "==", "valid", "contract verification"),
                _claim_check("contract_passed_checks", metrics.get("contract_passed_checks"), "==", metrics.get("contract_total_checks"), "contract checks"),
            ],
            artifacts=("proof_bundle", "proof_replay", "proof_mutation_lab", "proof_scorecard", "proof_regression_contract_json", "proof_regression_contract_verification", "proof_pr_guard"),
            validation_commands=(
                "python -m repo_agent replay-proof --bundle reports/proof-carrying-counterfactual.bundle.json --strict --output reports/proof-replay-report.md",
                "python -m repo_agent proof-mutate --bundle reports/proof-carrying-counterfactual.bundle.json --output reports/proof-mutation-report.md",
                "python -m repo_agent verify-contract --contract reports/proof-regression-contract.json --output reports/proof-regression-contract-verification.md",
            ),
            falsifiers=(
                "Strict proof replay fails after rebuilding the repository index.",
                "A seeded proof mutation is not detected.",
                "The proof regression contract passes while the route-to-target proof path is broken.",
            ),
            limitations=("Proof contracts verify current evidence chains; they do not prove full functional correctness of the application.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "adaptive_minimax_reliability_loop",
            "Generated attacks, defense policy synthesis, adaptive counterexamples, repair, and certificate form a closed reliability loop.",
            "red_team",
            metrics,
            checks=[
                _claim_check("proof_attack_resistance_rate", metrics.get("proof_attack_resistance_rate"), ">=", 1.0, "attack resistance"),
                _claim_check("proof_attack_policy_coverage", metrics.get("proof_attack_policy_coverage"), ">=", 1.0, "policy coverage"),
                _claim_check("proof_attack_adaptive_status", metrics.get("proof_attack_adaptive_status"), "==", "adaptive_gap_found", "adaptive gap surfaced"),
                _claim_check("proof_attack_repair_status", metrics.get("proof_attack_repair_status"), "==", "repair_converges", "adaptive repair"),
                _claim_check("proof_attack_certificate_status", metrics.get("proof_attack_certificate_status"), "==", "accepted", "minimax certificate"),
            ],
            artifacts=("proof_attack_benchmark_json", "proof_attack_policy_json", "proof_attack_adaptive_json", "proof_attack_repair_json", "proof_attack_certificate_json", "proof_attack_cegar_json"),
            validation_commands=(
                "python -m repo_agent proof-attack-cegar --output-dir reports/proof-attack-cegar --output reports/proof-attack-cegar.md",
                "python -m repo_agent proof-attack-certificate --benchmark reports/proof-attack-benchmark.json --policy reports/proof-attack-policy.json --adaptive reports/proof-attack-adaptive.json --repair reports/proof-attack-repair.json --output reports/proof-attack-certificate.md",
            ),
            falsifiers=(
                "A generated attack leaves a rank-1 decoy or unproved top answer.",
                "The synthesized policy no longer covers open triage actions.",
                "Adaptive repair leaves uncovered second-order actions.",
            ),
            limitations=("The loop is deterministic and inspectable; broader attack grammars would strengthen external validity.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "temporal_repair_and_abstention",
            "Proof regressions across git history can be localized, explained with graph deltas, repaired, and abstained when no successor exists.",
            "temporal",
            metrics,
            checks=[
                _claim_check("temporal_repair_successor_top1", metrics.get("temporal_repair_successor_top1"), ">=", 1.0, "successor@1"),
                _claim_check("temporal_repair_abstention_accuracy", metrics.get("temporal_repair_abstention_accuracy"), ">=", 1.0, "negative-control abstention"),
                _claim_check("temporal_repair_false_repair_rate", metrics.get("temporal_repair_false_repair_rate"), "<=", 0.0, "false repair"),
                _claim_check("temporal_repair_causal_delta_rate", metrics.get("temporal_repair_causal_delta_rate"), ">=", 1.0, "causal graph delta"),
                _claim_check("temporal_repair_scorecard_status", metrics.get("temporal_repair_scorecard_status"), "==", "pass", "temporal scorecard"),
            ],
            artifacts=("temporal_proof_regression_json", "temporal_proof_regression", "temporal_repair_benchmark_json", "temporal_repair_scorecard_json", "temporal_repair_scorecard_sarif"),
            validation_commands=(
                "python -m repo_agent temporal-repair-benchmark --output-dir reports/temporal-repair-benchmark --output reports/temporal-repair-benchmark.json",
                "python -m repo_agent temporal-repair-scorecard --benchmark reports/temporal-repair-benchmark.json --output reports/temporal-repair-scorecard.md --fail-on-fail",
            ),
            falsifiers=(
                "A rename or move case fails to rank the expected successor first.",
                "The no-successor negative control invents a repair.",
                "The graph delta cannot identify a broken proof-path edge.",
            ),
            limitations=("Synthetic histories cover representative proof drift patterns, not arbitrary long-lived project evolution.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "multi_agent_evidence_court",
            "Multi-agent arbitration is based on role-specialized hashed claims and discharged challenges, not prose-only voting.",
            "multi_agent",
            metrics,
            checks=[
                _claim_check("agent_court_status", metrics.get("agent_court_status"), "==", "accepted", "court verdict"),
                _claim_check("agent_court_score", metrics.get("agent_court_score"), ">=", 95, "court score"),
                _claim_check("agent_court_claims", metrics.get("agent_court_claims"), ">=", 6, "claim count"),
                _claim_check("agent_court_discharged_challenges", metrics.get("agent_court_discharged_challenges"), "==", metrics.get("agent_court_challenges"), "challenge discharge"),
            ],
            artifacts=("agent_court_json", "agent_court"),
            validation_commands=("python -m repo_agent agent-court --bundle reports/proof-carrying-counterfactual.bundle.json --attack-scorecard reports/proof-attack-scorecard.json --temporal-scorecard reports/temporal-repair-scorecard.json --output reports/agent-court.md",),
            falsifiers=(
                "Any required verifier claim fails.",
                "An error-level challenge remains open.",
                "The arbiter accepts an answer without proof replay or red-team evidence.",
            ),
            limitations=("Current agents are deterministic role evaluators; adding independent model-based judges would test robustness of arbitration.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "frontier_causal_uncertainty_analysis",
            "Agent reliability is evaluated as a Pareto frontier with causal ablation, pairwise interaction mapping, and bootstrap stability.",
            "evaluation",
            metrics,
            checks=[
                _claim_check("agent_frontier_status", metrics.get("agent_frontier_status"), "==", "accepted", "frontier status"),
                _claim_check("agent_frontier_ablation_status", metrics.get("agent_frontier_ablation_status"), "==", "attributed", "causal ablation"),
                _claim_check("agent_frontier_interactions_status", metrics.get("agent_frontier_interactions_status"), "==", "mapped", "pairwise interactions"),
                _claim_check("agent_frontier_stability_samples", metrics.get("agent_frontier_stability_samples"), ">=", 64, "bootstrap samples"),
                _claim_check("agent_frontier_stability_frontier_jaccard", metrics.get("agent_frontier_stability_frontier_jaccard"), ">=", 0.80, "frontier Jaccard"),
                _claim_check("agent_frontier_stability_score_ci_high", metrics.get("agent_frontier_stability_score_ci_high"), "<=", metrics.get("agent_frontier_stability_score_ci_low", 0) + 8, "score CI width"),
            ],
            artifacts=("agent_frontier_json", "agent_frontier_ablation_json", "agent_frontier_interactions_json", "agent_frontier_stability_json"),
            validation_commands=(
                "python -m repo_agent agent-frontier --manifest reports/release-pack/manifest.json --output reports/agent-frontier.md",
                "python -m repo_agent agent-frontier-ablate --manifest reports/release-pack/manifest.json --output reports/agent-frontier-ablation.md",
                "python -m repo_agent agent-frontier-interactions --manifest reports/release-pack/manifest.json --output reports/agent-frontier-interactions.md",
                "python -m repo_agent agent-frontier-stability --manifest reports/release-pack/manifest.json --output reports/agent-frontier-stability.md",
            ),
            falsifiers=(
                "A masked evidence family does not change any frontier-relevant score or profile.",
                "The top pairwise dependency is unstable under metric perturbation.",
                "A single scalar ranking contradicts Pareto membership conclusions.",
            ),
            limitations=("The frontier dimensions are engineered from release-pack metrics; external benchmarks should calibrate their weights.",),
            manifest=manifest,
        ),
        _agent_artifact_claim(
            "tamper_evident_reproducibility_pack",
            "The release pack is tamper-evident and self-verifying across generated reports, JSON artifacts, SARIF outputs, and demos.",
            "reproducibility",
            metrics,
            checks=[
                _claim_check("integrity_valid", integrity.get("valid"), "==", True, "manifest integrity"),
                _claim_check("verified_count", integrity.get("verified_count"), "==", integrity.get("artifact_count"), "verified artifacts"),
                _claim_check("artifact_count", integrity.get("artifact_count"), ">=", 50, "artifact coverage"),
            ],
            artifacts=(),
            validation_commands=("python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json",),
            falsifiers=(
                "Any artifact is missing, has a byte-size mismatch, or has a SHA-256 mismatch.",
                "A generated report used in a claim is absent from the manifest.",
                "The release gate cannot rebuild and verify the release pack.",
            ),
            limitations=("Integrity verifies artifact custody and reproducibility, not semantic correctness by itself.",),
            manifest=manifest,
        ),
    ]
    supported_count = sum(1 for claim in claims if claim["verdict"] == "supported")
    qualified_count = sum(1 for claim in claims if claim["verdict"] == "qualified")
    unsupported_count = sum(1 for claim in claims if claim["verdict"] == "unsupported")
    score = int(round(_mean(*(claim["confidence"] / 100.0 for claim in claims)) * 100)) if claims else 0
    status = "accepted" if unsupported_count == 0 and supported_count == len(claims) else "accepted_with_limitations" if unsupported_count == 0 else "needs_revision"
    return {
        "schema_version": "1.0",
        "strategy": "agent_artifact_evaluation_card",
        "manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256_file(manifest_path) if manifest_path.is_file() else "",
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "summary": {
            "claim_count": len(claims),
            "supported_count": supported_count,
            "qualified_count": qualified_count,
            "unsupported_count": unsupported_count,
            "artifact_count": integrity.get("artifact_count", 0),
            "verified_artifact_count": integrity.get("verified_count", 0),
            "integrity_valid": bool(integrity.get("valid")),
            "review_hash": _stable_short_hash(
                {
                    "claims": [(claim["id"], claim["verdict"], claim["confidence"]) for claim in claims],
                    "integrity": integrity.get("verified_count", 0),
                    "manifest": _sha256_file(manifest_path) if manifest_path.is_file() else "",
                }
            ),
        },
        "claims": claims,
        "reviewer_protocol": [
            {
                "step": "rebuild_release_pack",
                "command": "python -m repo_agent release-pack --output-dir reports/release-pack",
                "passes_if": "manifest, claim card, and release README regenerate without missing artifacts",
            },
            {
                "step": "verify_artifact_integrity",
                "command": "python -m repo_agent verify-release-pack --manifest reports/release-pack/manifest.json",
                "passes_if": "verified artifacts equals artifact count and every hash matches",
            },
            {
                "step": "run_release_gate",
                "command": "powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\release_gate.ps1",
                "passes_if": "compile, tests, generated benchmarks, frontier analyses, artifact review, integrity, and secret scan all pass",
            },
        ],
    }


def _agent_artifact_claim(
    claim_id: str,
    claim: str,
    category: str,
    metrics: dict,
    *,
    checks: list[dict],
    artifacts: tuple[str, ...],
    validation_commands: tuple[str, ...],
    falsifiers: tuple[str, ...],
    limitations: tuple[str, ...],
    manifest: dict,
) -> dict:
    passed = sum(1 for item in checks if item["passed"])
    artifact_checks = _agent_artifact_presence(manifest, artifacts)
    artifact_passed = sum(1 for item in artifact_checks if item["present"])
    total = len(checks) + len(artifact_checks)
    confidence = int(round(100 * (passed + artifact_passed) / max(1, total)))
    if confidence >= 90:
        verdict = "supported"
    elif confidence >= 70:
        verdict = "qualified"
    else:
        verdict = "unsupported"
    failed_checks = [item for item in checks if not item["passed"]]
    missing_artifacts = [item for item in artifact_checks if not item["present"]]
    risk_level = "low" if verdict == "supported" else "medium" if verdict == "qualified" else "high"
    return {
        "id": claim_id,
        "category": category,
        "claim": claim,
        "verdict": verdict,
        "confidence": confidence,
        "grade": _temporal_repair_grade(confidence),
        "risk_level": risk_level,
        "checks_passed": passed,
        "checks_total": len(checks),
        "artifacts_present": artifact_passed,
        "artifacts_total": len(artifact_checks),
        "checks": checks,
        "required_artifacts": artifact_checks,
        "validation_commands": list(validation_commands),
        "falsifiers": list(falsifiers),
        "limitations": list(limitations),
        "failed_checks": failed_checks,
        "missing_artifacts": missing_artifacts,
        "evidence_hash": _stable_short_hash(
            {
                "id": claim_id,
                "checks": [(item["metric"], item["value"], item["passed"]) for item in checks],
                "artifacts": [(item["name"], item["present"]) for item in artifact_checks],
            }
        ),
    }


def _claim_check(metric: str, value: object, op: str, threshold: object, label: str) -> dict:
    passed = False
    try:
        if op == "==":
            passed = value == threshold
        elif op == ">=":
            passed = float(value) >= float(threshold)
        elif op == "<=":
            passed = float(value) <= float(threshold)
        elif op == ">":
            passed = float(value) > float(threshold)
        elif op == "<":
            passed = float(value) < float(threshold)
        elif op == "in":
            passed = value in set(threshold if isinstance(threshold, list | tuple | set) else [threshold])
    except (TypeError, ValueError):
        passed = False
    return {
        "metric": metric,
        "label": label,
        "value": value,
        "operator": op,
        "threshold": threshold,
        "passed": bool(passed),
    }


def _agent_artifact_presence(manifest: dict, names: tuple[str, ...]) -> list[dict]:
    by_name = {item.get("name"): item for item in manifest.get("artifacts", [])}
    checks = []
    for name in names:
        artifact = by_name.get(name) or {}
        checks.append(
            {
                "name": name,
                "present": bool(artifact),
                "path": artifact.get("path", ""),
                "sha256": artifact.get("sha256", ""),
                "size_bytes": artifact.get("size_bytes", 0),
            }
        )
    return checks


def render_agent_artifact_review_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Artifact Evaluation Card",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Claims: `{int(summary.get('supported_count', 0))}/{int(summary.get('claim_count', 0))}` supported, "
        f"`{int(summary.get('qualified_count', 0))}` qualified, `{int(summary.get('unsupported_count', 0))}` unsupported",
        f"- Artifact integrity: `{int(summary.get('verified_artifact_count', 0))}/{int(summary.get('artifact_count', 0))}` verified",
        f"- Review hash: `{summary.get('review_hash', '')}`",
        "",
        "## Claim Ledger",
        "",
        "| Claim | Category | Verdict | Confidence | Checks | Artifacts | Evidence |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for claim in payload.get("claims", []):
        lines.append(
            f"| `{claim.get('id', '')}` | `{claim.get('category', '')}` | `{claim.get('verdict', '')}` | "
            f"{int(claim.get('confidence', 0))} | "
            f"{int(claim.get('checks_passed', 0))}/{int(claim.get('checks_total', 0))} | "
            f"{int(claim.get('artifacts_present', 0))}/{int(claim.get('artifacts_total', 0))} | "
            f"`{claim.get('evidence_hash', '')}` |"
        )
    lines.append("")
    for claim in payload.get("claims", []):
        lines.extend(
            [
                f"## {claim.get('id', '')}",
                "",
                f"**Claim:** {claim.get('claim', '')}",
                "",
                f"- Verdict: `{claim.get('verdict', '')}`",
                f"- Confidence: `{int(claim.get('confidence', 0))}/100`",
                f"- Risk: `{claim.get('risk_level', '')}`",
                "",
                "| Metric | Value | Threshold | Result |",
                "| --- | ---: | --- | --- |",
            ]
        )
        for item in claim.get("checks", []):
            result = "PASS" if item.get("passed") else "FAIL"
            lines.append(
                f"| `{item.get('label', item.get('metric', ''))}` | `{item.get('value', '')}` | "
                f"`{item.get('operator', '')} {item.get('threshold', '')}` | {result} |"
            )
        lines.extend(["", "Required artifacts:"])
        for artifact in claim.get("required_artifacts", []):
            status = "present" if artifact.get("present") else "missing"
            lines.append(f"- `{artifact.get('name', '')}`: `{status}` `{artifact.get('sha256', '')[:12]}`")
        lines.extend(["", "Validation commands:"])
        for command in claim.get("validation_commands", []):
            lines.append(f"- `{command}`")
        lines.extend(["", "Falsifiers:"])
        for falsifier in claim.get("falsifiers", []):
            lines.append(f"- {falsifier}")
        lines.extend(["", "Limitations:"])
        for limitation in claim.get("limitations", []):
            lines.append(f"- {limitation}")
        lines.append("")
    lines.extend(["## Reviewer Protocol", "", "| Step | Command | Passes If |", "| --- | --- | --- |"])
    for item in payload.get("reviewer_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | `{item.get('command', '')}` | {item.get('passes_if', '')} |")
    lines.append("")
    return "\n".join(lines)


def write_agent_artifact_review_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_agent_artifact_review_markdown(payload), encoding="utf-8")
    return output_path


def build_artifact_provenance(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review = build_agent_artifact_review(manifest_path)
    integrity = verify_release_pack(manifest_path)
    claims = []
    edges = []
    for claim in review.get("claims", []):
        claim_id = str(claim.get("id", ""))
        claim_node = f"claim:{claim_id}"
        metric_edges = []
        artifact_edges = []
        command_edges = []
        falsifier_edges = []
        for check in claim.get("checks", []):
            edge = _provenance_edge(
                claim_node,
                f"metric:{check.get('metric', '')}",
                "checked_by_metric",
                {
                    "metric": check.get("metric", ""),
                    "value": check.get("value"),
                    "operator": check.get("operator", ""),
                    "threshold": check.get("threshold"),
                    "passed": bool(check.get("passed")),
                },
            )
            metric_edges.append(edge)
            edges.append(edge)
        for artifact in claim.get("required_artifacts", []):
            edge = _provenance_edge(
                claim_node,
                f"artifact:{artifact.get('name', '')}",
                "supported_by_artifact",
                {
                    "name": artifact.get("name", ""),
                    "path": artifact.get("path", ""),
                    "sha256": artifact.get("sha256", ""),
                    "size_bytes": artifact.get("size_bytes", 0),
                    "present": bool(artifact.get("present")),
                },
            )
            artifact_edges.append(edge)
            edges.append(edge)
        for index, command in enumerate(claim.get("validation_commands", []), start=1):
            edge = _provenance_edge(
                claim_node,
                f"command:{claim_id}:{index}",
                "validated_by_command",
                {"command": command},
            )
            command_edges.append(edge)
            edges.append(edge)
        for index, falsifier in enumerate(claim.get("falsifiers", []), start=1):
            edge = _provenance_edge(
                claim_node,
                f"falsifier:{claim_id}:{index}",
                "falsified_by_condition",
                {"falsifier": falsifier},
            )
            falsifier_edges.append(edge)
            edges.append(edge)
        complete = bool(metric_edges and command_edges and falsifier_edges)
        complete = complete and (bool(artifact_edges) or claim.get("category") == "reproducibility")
        claims.append(
            {
                "id": claim_id,
                "node": claim_node,
                "category": claim.get("category", ""),
                "verdict": claim.get("verdict", ""),
                "confidence": int(claim.get("confidence", 0)),
                "evidence_hash": claim.get("evidence_hash", ""),
                "provenance_hash": _stable_short_hash(
                    {
                        "claim": claim_id,
                        "evidence": claim.get("evidence_hash", ""),
                        "metrics": [edge["hash"] for edge in metric_edges],
                        "artifacts": [edge["hash"] for edge in artifact_edges],
                        "commands": [edge["hash"] for edge in command_edges],
                        "falsifiers": [edge["hash"] for edge in falsifier_edges],
                    }
                ),
                "complete": complete,
                "edge_counts": {
                    "metric": len(metric_edges),
                    "artifact": len(artifact_edges),
                    "command": len(command_edges),
                    "falsifier": len(falsifier_edges),
                },
                "artifacts": [edge["target"].removeprefix("artifact:") for edge in artifact_edges],
                "validation_commands": list(claim.get("validation_commands", [])),
                "falsifiers": list(claim.get("falsifiers", [])),
            }
        )
    relation_counts = Counter(edge["relation"] for edge in edges)
    complete_count = sum(1 for claim in claims if claim["complete"])
    summary = {
        "claim_count": len(claims),
        "supported_claim_count": sum(1 for claim in claims if claim["verdict"] == "supported"),
        "complete_claim_count": complete_count,
        "complete_claim_rate": complete_count / max(1, len(claims)),
        "edge_count": len(edges),
        "metric_edge_count": relation_counts.get("checked_by_metric", 0),
        "artifact_edge_count": relation_counts.get("supported_by_artifact", 0),
        "command_edge_count": relation_counts.get("validated_by_command", 0),
        "falsifier_edge_count": relation_counts.get("falsified_by_condition", 0),
        "integrity_valid": bool(integrity.get("valid")),
    }
    summary["provenance_hash"] = _stable_short_hash(
        {
            "manifest": _sha256_file(manifest_path) if manifest_path.is_file() else "",
            "claims": [(claim["id"], claim["provenance_hash"], claim["complete"]) for claim in claims],
            "edges": [(edge["source"], edge["target"], edge["relation"], edge["hash"]) for edge in edges],
            "integrity": integrity.get("verified_count", 0),
        }
    )
    status = (
        "complete"
        if summary["integrity_valid"] and summary["complete_claim_count"] == summary["claim_count"]
        else "incomplete"
    )
    return {
        "schema_version": "1.0",
        "strategy": "artifact_provenance_schema",
        "manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256_file(manifest_path) if manifest_path.is_file() else "",
        "source_review_hash": (review.get("summary") or {}).get("review_hash", ""),
        "status": status,
        "summary": summary,
        "claims": claims,
        "edges": edges,
        "reviewer_protocol": list(review.get("reviewer_protocol") or []),
        "artifact_count": len(manifest.get("artifacts", [])),
    }


def _provenance_edge(source: str, target: str, relation: str, evidence: dict) -> dict:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "evidence": evidence,
        "hash": _stable_short_hash(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "evidence": evidence,
            }
        ),
    }


def render_artifact_provenance_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Artifact Provenance Graph",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Claims: `{int(summary.get('complete_claim_count', 0))}/{int(summary.get('claim_count', 0))}` complete",
        f"- Edges: `{int(summary.get('edge_count', 0))}`",
        f"- Metric edges: `{int(summary.get('metric_edge_count', 0))}`",
        f"- Artifact edges: `{int(summary.get('artifact_edge_count', 0))}`",
        f"- Command edges: `{int(summary.get('command_edge_count', 0))}`",
        f"- Falsifier edges: `{int(summary.get('falsifier_edge_count', 0))}`",
        f"- Integrity valid: `{bool(summary.get('integrity_valid', False))}`",
        f"- Provenance hash: `{summary.get('provenance_hash', '')}`",
        "",
        "## Claim Coverage",
        "",
        "| Claim | Category | Verdict | Complete | Metrics | Artifacts | Commands | Falsifiers | Hash |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for claim in payload.get("claims", []):
        counts = dict(claim.get("edge_counts") or {})
        lines.append(
            f"| `{claim.get('id', '')}` | `{claim.get('category', '')}` | `{claim.get('verdict', '')}` | "
            f"`{bool(claim.get('complete'))}` | "
            f"{int(counts.get('metric', 0))} | {int(counts.get('artifact', 0))} | "
            f"{int(counts.get('command', 0))} | {int(counts.get('falsifier', 0))} | "
            f"`{claim.get('provenance_hash', '')}` |"
        )
    lines.extend(
        [
            "",
            "## Edge Summary",
            "",
            "| Relation | Count |",
            "| --- | ---: |",
            f"| `checked_by_metric` | {int(summary.get('metric_edge_count', 0))} |",
            f"| `supported_by_artifact` | {int(summary.get('artifact_edge_count', 0))} |",
            f"| `validated_by_command` | {int(summary.get('command_edge_count', 0))} |",
            f"| `falsified_by_condition` | {int(summary.get('falsifier_edge_count', 0))} |",
            "",
        ]
    )
    return "\n".join(lines)


def write_artifact_provenance_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_artifact_provenance_markdown(payload), encoding="utf-8")
    return output_path


def verify_artifact_provenance(provenance_path: Path, *, manifest_path: Path | None = None) -> dict:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    selected_manifest = manifest_path or Path(str(provenance.get("manifest_path", "")))
    failures: list[dict] = []
    warnings: list[dict] = []
    edges = list(provenance.get("edges") or [])
    claims = list(provenance.get("claims") or [])
    summary = dict(provenance.get("summary") or {})

    for index, edge in enumerate(edges, start=1):
        expected_edge = _provenance_edge(
            str(edge.get("source", "")),
            str(edge.get("target", "")),
            str(edge.get("relation", "")),
            dict(edge.get("evidence") or {}),
        )
        if edge.get("hash") != expected_edge["hash"]:
            failures.append(
                {
                    "type": "edge_hash_mismatch",
                    "edge_index": index,
                    "source": edge.get("source", ""),
                    "target": edge.get("target", ""),
                    "expected_hash": expected_edge["hash"],
                    "actual_hash": edge.get("hash", ""),
                }
            )
        if edge.get("relation") == "supported_by_artifact":
            _verify_provenance_artifact_edge(edge, failures)

    for claim in claims:
        if not claim.get("complete"):
            failures.append(
                {
                    "type": "claim_incomplete",
                    "claim": claim.get("id", ""),
                    "edge_counts": dict(claim.get("edge_counts") or {}),
                }
            )

    actual_relation_counts = Counter(str(edge.get("relation", "")) for edge in edges)
    expected_counts = {
        "edge_count": len(edges),
        "metric_edge_count": actual_relation_counts.get("checked_by_metric", 0),
        "artifact_edge_count": actual_relation_counts.get("supported_by_artifact", 0),
        "command_edge_count": actual_relation_counts.get("validated_by_command", 0),
        "falsifier_edge_count": actual_relation_counts.get("falsified_by_condition", 0),
        "claim_count": len(claims),
        "complete_claim_count": sum(1 for claim in claims if claim.get("complete")),
    }
    for key, expected in expected_counts.items():
        if int(summary.get(key, -1)) != expected:
            failures.append(
                {
                    "type": "summary_count_mismatch",
                    "field": key,
                    "expected": expected,
                    "actual": summary.get(key),
                }
            )

    manifest_sha = ""
    if str(selected_manifest):
        selected_manifest = selected_manifest.expanduser().resolve()
        if selected_manifest.is_file():
            manifest_sha = _sha256_file(selected_manifest)
            if provenance.get("source_manifest_sha256") and provenance.get("source_manifest_sha256") != manifest_sha:
                warnings.append(
                    {
                        "type": "manifest_hash_drift",
                        "manifest": str(selected_manifest),
                        "source_manifest_sha256": provenance.get("source_manifest_sha256", ""),
                        "current_manifest_sha256": manifest_sha,
                        "detail": "The final release manifest may append provenance artifacts after the graph snapshot was built.",
                    }
                )
        else:
            warnings.append(
                {
                    "type": "manifest_missing",
                    "manifest": str(selected_manifest),
                }
            )

    valid = not failures
    return {
        "schema_version": "1.0",
        "strategy": "artifact_provenance_verification",
        "provenance_path": str(provenance_path),
        "manifest_path": str(selected_manifest) if str(selected_manifest) else "",
        "source_provenance_sha256": _sha256_file(provenance_path) if provenance_path.is_file() else "",
        "current_manifest_sha256": manifest_sha,
        "status": "pass" if valid else "fail",
        "valid": valid,
        "summary": {
            "claim_count": len(claims),
            "edge_count": len(edges),
            "artifact_edge_count": actual_relation_counts.get("supported_by_artifact", 0),
            "failure_count": len(failures),
            "warning_count": len(warnings),
            "complete_claim_count": expected_counts["complete_claim_count"],
        },
        "failures": failures,
        "warnings": warnings,
    }


def _verify_provenance_artifact_edge(edge: dict, failures: list[dict]) -> None:
    evidence = dict(edge.get("evidence") or {})
    name = str(evidence.get("name", ""))
    if not evidence.get("present"):
        failures.append(
            {
                "type": "artifact_not_present_in_claim",
                "artifact": name,
                "edge": edge.get("hash", ""),
            }
        )
        return
    path = Path(str(evidence.get("path", ""))).expanduser()
    if not path.is_file():
        failures.append(
            {
                "type": "artifact_file_missing",
                "artifact": name,
                "path": str(path),
                "edge": edge.get("hash", ""),
            }
        )
        return
    expected_sha = str(evidence.get("sha256", ""))
    actual_sha = _sha256_file(path)
    if expected_sha and expected_sha != actual_sha:
        failures.append(
            {
                "type": "artifact_sha256_mismatch",
                "artifact": name,
                "path": str(path),
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "edge": edge.get("hash", ""),
            }
        )
    expected_size = int(evidence.get("size_bytes", 0) or 0)
    actual_size = path.stat().st_size
    if expected_size and expected_size != actual_size:
        failures.append(
            {
                "type": "artifact_size_mismatch",
                "artifact": name,
                "path": str(path),
                "expected_size_bytes": expected_size,
                "actual_size_bytes": actual_size,
                "edge": edge.get("hash", ""),
            }
        )


def render_artifact_provenance_verification_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Artifact Provenance Verification",
        "",
        f"- Status: `{str(payload.get('status', 'unknown')).upper()}`",
        f"- Provenance: `{payload.get('provenance_path', '')}`",
        f"- Manifest: `{payload.get('manifest_path', '')}`",
        f"- Claims: `{int(summary.get('complete_claim_count', 0))}/{int(summary.get('claim_count', 0))}` complete",
        f"- Edges: `{int(summary.get('edge_count', 0))}`",
        f"- Artifact edges: `{int(summary.get('artifact_edge_count', 0))}`",
        f"- Failures: `{int(summary.get('failure_count', 0))}`",
        f"- Warnings: `{int(summary.get('warning_count', 0))}`",
        "",
        "## Failures",
        "",
    ]
    failures = list(payload.get("failures") or [])
    if failures:
        lines.extend(["| Type | Detail |", "| --- | --- |"])
        for item in failures:
            lines.append(f"| `{item.get('type', '')}` | `{_markdown_cell(json.dumps(item, ensure_ascii=False, sort_keys=True))}` |")
    else:
        lines.append("No provenance verification failures.")
    warnings = list(payload.get("warnings") or [])
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(["| Type | Detail |", "| --- | --- |"])
        for item in warnings:
            lines.append(f"| `{item.get('type', '')}` | `{_markdown_cell(json.dumps(item, ensure_ascii=False, sort_keys=True))}` |")
    else:
        lines.append("No warnings.")
    lines.append("")
    return "\n".join(lines)


def write_artifact_provenance_verification_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_artifact_provenance_verification_markdown(payload), encoding="utf-8")
    return output_path


def _agent_frontier_perturb_manifest(manifest: dict, *, rng: random.Random, noise: float) -> dict:
    perturbed = json.loads(json.dumps(manifest))
    metrics = dict(perturbed.get("metrics") or {})
    for key, value in list(metrics.items()):
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        numeric = float(value)
        if 0.0 <= numeric <= 1.0:
            metrics[key] = round(_clamp01(numeric + rng.uniform(-noise, noise)), 4)
        elif "score" in key and 0.0 <= numeric <= 100.0:
            metrics[key] = int(round(max(0.0, min(100.0, numeric + rng.uniform(-100.0 * noise, 100.0 * noise)))))
    perturbed["metrics"] = metrics
    return perturbed


def _agent_frontier_numeric_summary(values: list[int | float], *, integer: bool) -> dict:
    if not values:
        return {"mean": 0, "ci_low": 0, "ci_high": 0, "min": 0, "max": 0}
    mean_value = sum(float(value) for value in values) / len(values)
    low = _agent_frontier_quantile(values, 0.025)
    high = _agent_frontier_quantile(values, 0.975)
    if integer:
        return {
            "mean": round(mean_value, 1),
            "ci_low": int(round(low)),
            "ci_high": int(round(high)),
            "min": int(round(min(values))),
            "max": int(round(max(values))),
        }
    return {
        "mean": round(mean_value, 2),
        "ci_low": round(low, 2),
        "ci_high": round(high, 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def _agent_frontier_quantile(values: list[int | float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _agent_frontier_mode(values: list[str]) -> tuple[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return "", 0
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def _agent_frontier_jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / max(1, len(left | right))


def _agent_frontier_profile_stability_label(baseline_frontier: bool, frontier_probability: float) -> str:
    if baseline_frontier and frontier_probability >= 0.9:
        return "stable_frontier"
    if baseline_frontier and frontier_probability < 0.75:
        return "fragile_frontier"
    if not baseline_frontier and frontier_probability <= 0.1:
        return "stable_dominated"
    return "boundary_case"


def _agent_frontier_interaction_stability_label(top_probability: float, fragile_probability: float, synergy_ci_low: float) -> str:
    if top_probability >= 0.5 and synergy_ci_low > 0:
        return "stable_top_synergy"
    if fragile_probability >= 0.9:
        return "stable_fragility"
    if top_probability >= 0.25:
        return "contested_top_interaction"
    return "supporting_interaction"


def _agent_frontier_stability_status(
    *,
    baseline_status: str,
    score_ci_low: int,
    score_ci_high: int,
    frontier_jaccard_mean: float,
    top_probability: float,
    unstable_frontier_count: int,
) -> str:
    if baseline_status != "accepted":
        return "needs_attention"
    if (score_ci_high - score_ci_low) <= 8 and frontier_jaccard_mean >= 0.85 and top_probability >= 0.35 and unstable_frontier_count == 0:
        return "stable"
    return "uncertain"


def _safe_round(value: float, digits: int) -> float:
    return round(float(value), digits)


def _agent_frontier_interaction_type(synergy: int, removed: list[str], observed_drop: int) -> str:
    if synergy > 0:
        return "synergistic_fragility"
    if removed:
        return "frontier_membership_dependency"
    if observed_drop >= 10:
        return "additive_fragility"
    if synergy < 0:
        return "redundant_evidence"
    return "independent"


def _agent_frontier_interaction_recommendation(left: dict, right: dict, synergy: int, observed_drop: int, removed: list[str]) -> str:
    if synergy > 0:
        return "Add a paired release gate; these evidence families fail worse together than their single drops predict."
    if removed:
        return f"Keep both families in the demo pack; paired masking removes Pareto profiles {', '.join(removed)}."
    if observed_drop >= 10:
        return "Treat the pair as an additive reliability dependency in regression review."
    if synergy < 0:
        return "Evidence is partly redundant; useful for defense in depth but not a nonlinear failure mode."
    return f"No strong interaction; monitor {left['primary_dimension']} and {right['primary_dimension']} independently."


def _agent_frontier_profile_by_id(payload: dict, profile_id: str) -> dict | None:
    for profile in payload.get("profiles", []):
        if profile.get("id") == profile_id:
            return profile
    return None


def _agent_frontier_family_artifact_count(manifest: dict, prefixes: tuple[str, ...]) -> int:
    count = 0
    for artifact in manifest.get("artifacts", []):
        name = str(artifact.get("name", ""))
        if any(name.startswith(prefix) for prefix in prefixes):
            count += 1
    return count


def _agent_frontier_ablation_recommendation(family: dict, score_drop: int, profile_score_drop: int, removed: list[str]) -> str:
    if removed:
        return f"Protect this family in release gates; removing it changes Pareto membership for {', '.join(removed)}."
    if score_drop >= 5 or profile_score_drop >= 20:
        return f"Treat as a critical evidence driver for {family['primary_dimension']}."
    if profile_score_drop > 0:
        return f"Keep as supporting evidence for {family['primary_dimension']}."
    return "Low causal impact on the current frontier; keep for defense in depth."


AGENT_FRONTIER_ABLATION_FAMILIES = (
    {
        "id": "graph_mcts_retrieval",
        "name": "Graph-MCTS Retrieval Evidence",
        "profile_id": "graph_mcts_retrieval",
        "primary_dimension": "robustness",
        "artifact_prefixes": ("ablation", "counterfactual", "proof_attack_benchmark"),
        "mask": {
            "counterfactual_graph_mcts_top1": 0.0,
            "counterfactual_graph_mcts_distractor_top1": 1.0,
            "proof_attack_graph_mcts_top1": 0.0,
            "proof_attack_graph_mcts_distractor_top1": 1.0,
            "proof_attack_resistance_rate": 0.0,
            "proof_attack_proof_proved_rate": 0.0,
        },
    },
    {
        "id": "proof_contract_stack",
        "name": "Proof Contract Evidence",
        "profile_id": "proof_contract_stack",
        "primary_dimension": "evidence",
        "artifact_prefixes": ("proof_replay", "proof_mutation", "proof_scorecard", "proof_regression", "proof_pr_guard", "proof_impact"),
        "mask": {
            "proof_score": 0,
            "mutation_detection_rate": 0.0,
            "contract_passed_checks": 0,
            "contract_total_checks": 6,
            "contract_status": "invalid",
            "pr_guard_status": "fail",
        },
    },
    {
        "id": "adversarial_minimax_loop",
        "name": "Adversarial Minimax Evidence",
        "profile_id": "adversarial_minimax_loop",
        "primary_dimension": "adaptivity",
        "artifact_prefixes": ("proof_attack_policy", "proof_attack_adaptive", "proof_attack_repair", "proof_attack_certificate", "proof_attack_scorecard", "proof_attack_cegar"),
        "mask": {
            "proof_attack_certificate_score": 0,
            "proof_attack_mitigated_decoy_rate": 0.0,
            "proof_attack_score": 0,
            "proof_attack_certificate_passed_claims": 0,
            "proof_attack_certificate_claims": 5,
            "proof_attack_adaptive_status": "missing",
            "proof_attack_repair_coverage": 0.0,
            "proof_attack_adaptive_policy_coverage": 1.0,
            "proof_attack_scorecard_status": "fail",
            "proof_attack_certificate_status": "rejected",
            "proof_attack_triage_actions": 0,
        },
    },
    {
        "id": "temporal_repair_loop",
        "name": "Temporal Repair Evidence",
        "profile_id": "temporal_repair_loop",
        "primary_dimension": "adaptivity",
        "artifact_prefixes": ("temporal", "proof_graph_delta"),
        "mask": {
            "temporal_repair_score": 0,
            "temporal_repair_abstention_accuracy": 0.0,
            "temporal_repair_false_repair_rate": 1.0,
            "temporal_repair_causal_delta_rate": 0.0,
            "proof_graph_delta_status": "missing",
            "proof_graph_delta_successor_relinks": 0,
            "proof_graph_delta_broken_edges": 1,
            "temporal_repair_successor_top1": 0.0,
            "temporal_repair_migration_ready_rate": 0.0,
            "temporal_repair_scorecard_status": "fail",
        },
    },
    {
        "id": "multi_agent_evidence_court",
        "name": "Multi-Agent Court Evidence",
        "profile_id": "multi_agent_evidence_court",
        "primary_dimension": "governance",
        "artifact_prefixes": ("agent_court",),
        "mask": {
            "agent_court_score": 0,
            "agent_court_discharged_challenges": 0,
            "agent_court_challenges": 5,
            "agent_court_claims": 0,
            "agent_court_status": "contested",
        },
    },
    {
        "id": "release_integrity_mesh",
        "name": "Release Integrity Evidence",
        "profile_id": "release_integrity_mesh",
        "primary_dimension": "governance",
        "artifact_prefixes": ("release_pack", "agent_frontier"),
        "mask": {},
    },
)


def _agent_frontier_profile(profile_id: str, name: str, description: str, dimensions: dict, signals: list[str], caveats: list[str]) -> dict:
    normalized = {dimension: _clamp01(float(dimensions.get(dimension, 0.0))) for dimension in AGENT_FRONTIER_DIMENSIONS}
    score = int(
        round(
            100
            * (
                0.24 * normalized["reliability"]
                + 0.20 * normalized["robustness"]
                + 0.19 * normalized["evidence"]
                + 0.15 * normalized["adaptivity"]
                + 0.15 * normalized["governance"]
                + 0.07 * normalized["efficiency"]
            )
        )
    )
    bottlenecks = [
        {"dimension": dimension, "score": value}
        for dimension, value in normalized.items()
        if value < 0.7
    ]
    evidence = {"id": profile_id, "dimensions": normalized, "signals": signals, "caveats": caveats}
    return {
        "id": profile_id,
        "name": name,
        "description": description,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "dimensions": normalized,
        "cost_proxy": round(1.0 - normalized["efficiency"], 4),
        "signals": signals,
        "caveats": caveats,
        "bottlenecks": bottlenecks,
        "dominated": False,
        "evidence_hash": _stable_short_hash(evidence),
    }


def _agent_frontier_pareto_ids(profiles: list[dict]) -> list[str]:
    frontier = []
    for candidate in profiles:
        candidate_dims = candidate.get("dimensions") or {}
        dominated = False
        for challenger in profiles:
            if challenger is candidate:
                continue
            challenger_dims = challenger.get("dimensions") or {}
            if all(challenger_dims.get(dim, 0.0) >= candidate_dims.get(dim, 0.0) for dim in AGENT_FRONTIER_DIMENSIONS) and any(
                challenger_dims.get(dim, 0.0) > candidate_dims.get(dim, 0.0) for dim in AGENT_FRONTIER_DIMENSIONS
            ):
                dominated = True
                break
        candidate["dominated"] = dominated
        if not dominated:
            frontier.append(str(candidate.get("id", "")))
    return frontier


def _metric(metrics: dict, key: str, default: float = 0.0) -> float:
    return _clamp01(float(metrics.get(key, default) or 0.0))


def _score_metric(metrics: dict, key: str) -> float:
    return _clamp01(float(metrics.get(key, 0) or 0) / 100.0)


def _status_metric(metrics: dict, key: str, expected: str) -> float:
    return 1.0 if str(metrics.get(key, "")) == expected else 0.0


def _ratio_metric(metrics: dict, numerator_key: str, denominator_key: str) -> float:
    return _ratio(metrics.get(numerator_key, 0), metrics.get(denominator_key, 0))


def _ratio(numerator: object, denominator: object) -> float:
    try:
        denom = float(denominator)
        if denom <= 0:
            return 0.0
        return _clamp01(float(numerator) / denom)
    except (TypeError, ValueError):
        return 0.0


def _mean(*values: float) -> float:
    clean = [float(value) for value in values]
    if not clean:
        return 0.0
    return _clamp01(sum(clean) / len(clean))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _resolve_manifest_artifact_path(manifest_path: Path, raw_path: str) -> Path:
    artifact_path = Path(raw_path)
    if artifact_path.is_absolute() or artifact_path.exists():
        return artifact_path
    sibling_path = manifest_path.parent / artifact_path.name
    if sibling_path.exists():
        return sibling_path
    return artifact_path


def _changed_files_from_args(values: list[str], file_path: str | None) -> list[str]:
    changed = list(values or [])
    if file_path:
        changed.extend(
            line.strip()
            for line in Path(file_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return changed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_eval_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".md":
        output_path.write_text(render_eval_markdown(payload), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_benchmark_adapter_template() -> dict:
    return {
        "schema_version": "1.0",
        "suite_id": "my-external-agent-benchmark",
        "name": "My External Agent Benchmark",
        "description": "Portable benchmark suite for repository-localization and proof-carrying retrieval tasks.",
        "source": "local-or-third-party",
        "cases": [
            {
                "id": "case_001",
                "repo": "path/to/repository",
                "question": "Which function handles the public API route?",
                "expected_path": "server.py",
                "expected_symbol_contains": "handle_public_route",
                "distractor_symbol_contains": ["handle_admin_route", "legacy_handler"],
                "tags": ["api", "route-grounded", "hard-negative"],
                "source": "issue-or-paper-reference",
            }
        ],
    }


def run_benchmark_adapter(runtime: RepoAgentRuntime, suite_path: Path, *, top_k: int = 6) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = list(suite.get("cases") or [])
    records = []
    for case in cases:
        repo_path = _resolve_benchmark_repo_path(suite_path, case.get("repo", ""))
        result, _repo_index = runtime.ask(
            repo_path=repo_path,
            question=str(case.get("question", "")),
            top_k=top_k,
            use_model=False,
            force_rebuild=True,
        )
        hits = result.hits[:top_k]
        top_hit = hits[0] if hits else None
        rank = _case_match_rank(case, hits)
        distractor_rank = _case_distractor_rank(case, hits)
        diagnostics = result.diagnostics
        tags = [str(tag) for tag in case.get("tags", [])]
        records.append(
            {
                "id": str(case.get("id") or case.get("name") or f"case_{len(records) + 1}"),
                "name": str(case.get("name") or case.get("id") or ""),
                "source": str(case.get("source") or suite.get("source") or ""),
                "repo": str(repo_path),
                "repo_key": _benchmark_repo_key(suite_path, repo_path),
                "question": str(case.get("question", "")),
                "expected_path": str(case.get("expected_path", "")),
                "expected_symbol_contains": str(case.get("expected_symbol_contains", "")),
                "distractor_symbol_contains": [str(item) for item in case.get("distractor_symbol_contains", [])],
                "tags": tags,
                "rank": rank,
                "distractor_rank": distractor_rank,
                "top_hit": top_hit.chunk.source_label if top_hit else "",
                "top_hits": [hit.chunk.source_label for hit in hits],
                "top_hit_reasons": list(top_hit.reasons) if top_hit else [],
                "top_hits_detail": [
                    {
                        "rank": index,
                        "source_label": hit.chunk.source_label,
                        "score": round(hit.score, 3),
                        "reasons": list(hit.reasons),
                    }
                    for index, hit in enumerate(hits, start=1)
                ],
                "passed_top1": rank == 1,
                "passed_top3": rank is not None and rank <= 3,
                "distractor_top1": distractor_rank == 1,
                "confidence": diagnostics.confidence if diagnostics else 0.0,
                "confidence_label": diagnostics.label if diagnostics else "unknown",
                "warnings": diagnostics.warnings if diagnostics else [],
                "evidence_hash": _stable_short_hash(
                    {
                        "id": case.get("id", ""),
                        "repo": str(repo_path),
                        "rank": rank,
                        "distractor_rank": distractor_rank,
                        "top_hits": [hit.chunk.source_label for hit in hits],
                    }
                ),
            }
        )
    metrics = _benchmark_metrics(records, top_k=top_k)
    by_repo = [
        {"repo": repo, **_benchmark_metrics(items, top_k=top_k)}
        for repo, items in sorted(_group_records(records, key="repo_key").items())
    ]
    tag_groups: dict[str, list[dict]] = {}
    for record in records:
        for tag in record.get("tags", []) or ["untagged"]:
            tag_groups.setdefault(tag, []).append(record)
    by_tag = [
        {"tag": tag, **_benchmark_metrics(items, top_k=top_k)}
        for tag, items in sorted(tag_groups.items())
    ]
    generalization_gaps = _benchmark_generalization_gaps(by_repo=by_repo, by_tag=by_tag)
    status = "pass" if metrics["top3_accuracy"] >= 0.8 and metrics["distractor_top1_rate"] == 0 else "needs_attention"
    return {
        "schema_version": "1.0",
        "strategy": "portable_benchmark_adapter",
        "suite_path": str(suite_path),
        "suite_id": str(suite.get("suite_id") or suite.get("name") or suite_path.stem),
        "name": str(suite.get("name") or suite_path.stem),
        "description": str(suite.get("description") or ""),
        "source": str(suite.get("source") or ""),
        "status": status,
        "metrics": metrics,
        "by_repo": by_repo,
        "by_tag": by_tag,
        "generalization_gaps": generalization_gaps,
        "cases": records,
        "review_protocol": [
            {
                "step": "add_external_cases",
                "detail": "Convert each third-party task into repo/question/expected_path/expected_symbol_contains plus optional distractors and tags.",
            },
            {
                "step": "run_adapter",
                "detail": f"python -m repo_agent benchmark-adapter --suite {suite_path} --output reports/benchmark-adapter.md",
            },
            {
                "step": "inspect_gaps",
                "detail": "Review per-repo and per-tag groups whose Top-3 accuracy is below 80% or whose distractor@1 is nonzero.",
            },
        ],
    }


def write_benchmark_adapter_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_adapter_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_adapter_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Benchmark Adapter Report",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Name: {payload.get('name', '')}",
        f"- Source: `{payload.get('source', '')}`",
        f"- Cases: `{int(metrics.get('case_count', 0))}`",
        f"- Top-1: `{float(metrics.get('top1_accuracy', 0.0)):.2%}`",
        f"- Top-3: `{float(metrics.get('top3_accuracy', 0.0)):.2%}`",
        f"- MRR: `{float(metrics.get('mrr', 0.0)):.3f}`",
        f"- Distractor@1: `{float(metrics.get('distractor_top1_rate', 0.0)):.2%}`",
        f"- Average confidence: `{float(metrics.get('average_confidence', 0.0)):.2f}`",
        "",
        "## Generalization Gaps",
        "",
    ]
    gaps = payload.get("generalization_gaps", [])
    if gaps:
        lines.extend(["| Scope | Id | Top-3 | Distractor@1 | Reason |", "| --- | --- | ---: | ---: | --- |"])
        for gap in gaps:
            lines.append(
                f"| `{gap.get('scope', '')}` | `{_markdown_cell(gap.get('id', ''))}` | "
                f"{float(gap.get('top3_accuracy', 0.0)):.2%} | "
                f"{float(gap.get('distractor_top1_rate', 0.0)):.2%} | {gap.get('reason', '')} |"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## By Repository", "", "| Repository | Cases | Top-1 | Top-3 | MRR | Distractor@1 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for item in payload.get("by_repo", []):
        lines.append(
            f"| `{_markdown_cell(item.get('repo', ''))}` | {int(item.get('case_count', 0))} | "
            f"{float(item.get('top1_accuracy', 0.0)):.2%} | {float(item.get('top3_accuracy', 0.0)):.2%} | "
            f"{float(item.get('mrr', 0.0)):.3f} | {float(item.get('distractor_top1_rate', 0.0)):.2%} |"
        )
    lines.extend(["", "## By Tag", "", "| Tag | Cases | Top-1 | Top-3 | MRR | Distractor@1 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for item in payload.get("by_tag", []):
        lines.append(
            f"| `{_markdown_cell(item.get('tag', ''))}` | {int(item.get('case_count', 0))} | "
            f"{float(item.get('top1_accuracy', 0.0)):.2%} | {float(item.get('top3_accuracy', 0.0)):.2%} | "
            f"{float(item.get('mrr', 0.0)):.3f} | {float(item.get('distractor_top1_rate', 0.0)):.2%} |"
        )
    lines.extend(["", "## Cases", "", "| Case | Repo | Tags | Rank | Decoy Rank | Top Hit | Evidence |", "| --- | --- | --- | ---: | ---: | --- | --- |"])
    for record in payload.get("cases", []):
        rank = record.get("rank") if record.get("rank") is not None else "miss"
        decoy = record.get("distractor_rank") if record.get("distractor_rank") is not None else "none"
        lines.append(
            f"| `{_markdown_cell(record.get('id', ''))}` | `{_markdown_cell(record.get('repo_key', ''))}` | "
            f"{_markdown_cell(', '.join(record.get('tags', [])))} | {rank} | {decoy} | "
            f"`{_markdown_cell(record.get('top_hit', ''))}` | `{record.get('evidence_hash', '')}` |"
        )
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def _resolve_benchmark_repo_path(suite_path: Path, raw_repo: str) -> Path:
    repo_path = Path(raw_repo)
    if repo_path.is_absolute():
        return repo_path.resolve()
    return (suite_path.parent / repo_path).resolve()


def _benchmark_repo_key(suite_path: Path, repo_path: Path) -> str:
    try:
        return str(repo_path.relative_to(suite_path.parent.resolve()))
    except ValueError:
        return str(repo_path)


def _benchmark_metrics(records: list[dict], *, top_k: int) -> dict:
    total = max(len(records), 1)
    return {
        "case_count": len(records),
        "top_k": top_k,
        "top1_accuracy": sum(1 for record in records if record.get("passed_top1")) / total,
        "top3_accuracy": sum(1 for record in records if record.get("passed_top3")) / total,
        "mrr": sum((1 / record["rank"]) if record.get("rank") else 0.0 for record in records) / total,
        "distractor_top1_rate": sum(1 for record in records if record.get("distractor_top1")) / total,
        "average_confidence": sum(float(record.get("confidence", 0.0)) for record in records) / total,
    }


def _group_records(records: list[dict], *, key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(str(record.get(key, "")), []).append(record)
    return groups


def _benchmark_generalization_gaps(*, by_repo: list[dict], by_tag: list[dict]) -> list[dict]:
    gaps = []
    for scope, items, key in (("repo", by_repo, "repo"), ("tag", by_tag, "tag")):
        for item in items:
            top3 = float(item.get("top3_accuracy", 0.0))
            distractor = float(item.get("distractor_top1_rate", 0.0))
            if top3 < 0.8 or distractor > 0.0:
                reason = "low Top-3" if top3 < 0.8 else "rank-1 distractor"
                gaps.append(
                    {
                        "scope": scope,
                        "id": item.get(key, ""),
                        "top3_accuracy": top3,
                        "distractor_top1_rate": distractor,
                        "reason": reason,
                    }
                )
    gaps.sort(key=lambda item: (item["top3_accuracy"], -item["distractor_top1_rate"], item["scope"], item["id"]))
    return gaps


def diagnose_benchmark_adapter(benchmark_path: Path, *, min_top1: float = 0.85, min_top3: float = 0.80) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    cases = list(benchmark.get("cases") or [])
    metrics = dict(benchmark.get("metrics") or {})
    case_diagnostics = [_benchmark_case_diagnosis(record) for record in cases]
    weak_cases = [item for item in case_diagnostics if item["severity"] != "pass"]
    group_diagnostics = _benchmark_group_diagnostics(benchmark, min_top1=min_top1, min_top3=min_top3)
    interventions = _benchmark_counterfactual_interventions(cases, metrics)
    taxonomy_counts: dict[str, int] = {}
    for item in case_diagnostics:
        for label in item.get("taxonomy", []):
            taxonomy_counts[label] = taxonomy_counts.get(label, 0) + 1
    taxonomy = [
        {
            "label": label,
            "count": count,
            "severity": _benchmark_taxonomy_severity(label),
            "recommendation": _benchmark_taxonomy_recommendation(label),
        }
        for label, count in sorted(taxonomy_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    blockers = [item for item in weak_cases if item["severity"] == "blocker"] + [
        item for item in group_diagnostics if item.get("severity") == "blocker"
    ]
    action_items = [item for item in weak_cases if item["severity"] in {"action", "blocker"}] + group_diagnostics
    projected_top1 = max(float(metrics.get("top1_accuracy", 0.0)), *(float(item.get("projected_top1_accuracy", 0.0)) for item in interventions))
    score = max(0, min(100, int(round(100 - 25 * len(blockers) - 4 * max(0, len(weak_cases) - len(blockers)) - min(5, len(group_diagnostics))))))
    status = "blocked" if blockers else "actionable" if action_items else "clean"
    return {
        "schema_version": "1.0",
        "strategy": "portable_benchmark_generalization_diagnostics",
        "benchmark_path": str(benchmark_path),
        "source_benchmark_sha256": _sha256_file(benchmark_path) if benchmark_path.is_file() else "",
        "suite_id": benchmark.get("suite_id", ""),
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "thresholds": {"min_top1": min_top1, "min_top3": min_top3},
        "summary": {
            "case_count": int(metrics.get("case_count", len(cases))),
            "weak_case_count": len(weak_cases),
            "blocker_count": len(blockers),
            "action_count": len(action_items),
            "taxonomy_count": len(taxonomy),
            "recoverable_case_count": sum(1 for item in case_diagnostics if "top3_recoverable" in item.get("taxonomy", [])),
            "current_top1_accuracy": float(metrics.get("top1_accuracy", 0.0)),
            "current_top3_accuracy": float(metrics.get("top3_accuracy", 0.0)),
            "projected_top1_accuracy": projected_top1,
            "distractor_top1_rate": float(metrics.get("distractor_top1_rate", 0.0)),
        },
        "taxonomy": taxonomy,
        "case_diagnostics": case_diagnostics,
        "group_diagnostics": group_diagnostics,
        "counterfactual_interventions": interventions,
        "review_protocol": [
            {
                "step": "inspect_weak_cases",
                "detail": "Start with blocker cases, then action cases whose expected answer is inside Top-3 but not rank-1.",
            },
            {
                "step": "apply_targeted_guards",
                "detail": "Use the taxonomy recommendations instead of broad reranker tuning.",
            },
            {
                "step": "rerun_adapter",
                "detail": "Rerun benchmark-adapter and benchmark-diagnose; projected Top-1 is only a ceiling until verified by a fresh run.",
            },
        ],
        "evidence_hash": _stable_short_hash(
            {
                "suite": benchmark.get("suite_id", ""),
                "status": status,
                "score": score,
                "weak_cases": [(item["id"], item["severity"], item["taxonomy"]) for item in weak_cases],
                "groups": [(item["scope"], item["id"], item["severity"]) for item in group_diagnostics],
            }
        ),
    }


def write_benchmark_diagnostics_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_diagnostics_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_diagnostics_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Benchmark Generalization Diagnostics",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Cases: `{int(summary.get('case_count', 0))}`",
        f"- Weak cases: `{int(summary.get('weak_case_count', 0))}`",
        f"- Blockers: `{int(summary.get('blocker_count', 0))}`",
        f"- Current Top-1: `{float(summary.get('current_top1_accuracy', 0.0)):.2%}`",
        f"- Projected Top-1 ceiling: `{float(summary.get('projected_top1_accuracy', 0.0)):.2%}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Diagnostic Taxonomy",
        "",
    ]
    taxonomy = payload.get("taxonomy", [])
    if taxonomy:
        lines.extend(["| Label | Count | Severity | Recommendation |", "| --- | ---: | --- | --- |"])
        for item in taxonomy:
            lines.append(
                f"| `{item.get('label', '')}` | {int(item.get('count', 0))} | `{item.get('severity', '')}` | "
                f"{item.get('recommendation', '')} |"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Counterfactual Interventions", "", "| Intervention | Affected | Projected Top-1 | Rationale |", "| --- | ---: | ---: | --- |"])
    for item in payload.get("counterfactual_interventions", []):
        lines.append(
            f"| `{item.get('id', '')}` | {int(item.get('affected_cases', 0))} | "
            f"{float(item.get('projected_top1_accuracy', 0.0)):.2%} | {item.get('rationale', '')} |"
        )
    lines.extend(["", "## Case Diagnostics", "", "| Case | Severity | Rank | Tags | Taxonomy | Recommendation | Evidence |", "| --- | --- | ---: | --- | --- | --- | --- |"])
    for item in payload.get("case_diagnostics", []):
        rank = item.get("rank") if item.get("rank") is not None else "miss"
        lines.append(
            f"| `{_markdown_cell(item.get('id', ''))}` | `{item.get('severity', '')}` | {rank} | "
            f"{_markdown_cell(', '.join(item.get('tags', [])))} | {_markdown_cell(', '.join(item.get('taxonomy', [])))} | "
            f"{_markdown_cell(item.get('recommendation', ''))} | `{item.get('evidence_hash', '')}` |"
        )
    lines.extend(["", "## Group Diagnostics", "", "| Scope | Id | Severity | Top-1 | Top-3 | Cases | Recommendation |", "| --- | --- | --- | ---: | ---: | ---: | --- |"])
    for item in payload.get("group_diagnostics", []):
        lines.append(
            f"| `{item.get('scope', '')}` | `{_markdown_cell(item.get('id', ''))}` | `{item.get('severity', '')}` | "
            f"{float(item.get('top1_accuracy', 0.0)):.2%} | {float(item.get('top3_accuracy', 0.0)):.2%} | "
            f"{int(item.get('case_count', 0))} | {item.get('recommendation', '')} |"
        )
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def build_benchmark_experiment_report(
    benchmark_path: Path,
    *,
    diagnostics_path: Path | None = None,
    repair_card_path: Path | None = None,
    repair_synthesis_path: Path | None = None,
) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    diagnostics = (
        json.loads(diagnostics_path.read_text(encoding="utf-8"))
        if diagnostics_path and diagnostics_path.is_file()
        else diagnose_benchmark_adapter(benchmark_path)
    )
    repair_card = (
        json.loads(repair_card_path.read_text(encoding="utf-8"))
        if repair_card_path and repair_card_path.is_file()
        else build_benchmark_repair_card(benchmark_path)
    )
    repair_synthesis = (
        json.loads(repair_synthesis_path.read_text(encoding="utf-8"))
        if repair_synthesis_path and repair_synthesis_path.is_file()
        else synthesize_benchmark_repair_rules(benchmark_path)
    )
    metrics = dict(benchmark.get("metrics") or {})
    diag_summary = dict(diagnostics.get("summary") or {})
    repair_summary = dict(repair_card.get("summary") or {})
    synthesis_summary = dict(repair_synthesis.get("summary") or {})
    dataset = {
        "suite_id": benchmark.get("suite_id", ""),
        "name": benchmark.get("name", ""),
        "source": benchmark.get("source", ""),
        "case_count": int(metrics.get("case_count", len(benchmark.get("cases", [])))),
        "repo_group_count": len(benchmark.get("by_repo", [])),
        "tag_group_count": len(benchmark.get("by_tag", [])),
        "hard_negative_case_count": sum(
            1
            for record in benchmark.get("cases", [])
            if record.get("distractor_symbol_contains") or "hard-negative" in {str(tag).lower() for tag in record.get("tags", [])}
        ),
    }
    metrics_table = [
        _experiment_metric("Top-1", metrics.get("top1_accuracy", 0.0), "higher", "Rank-1 localization accuracy."),
        _experiment_metric("Top-3", metrics.get("top3_accuracy", 0.0), "higher", "Expected target appears in the first three hits."),
        _experiment_metric("MRR", metrics.get("mrr", 0.0), "higher", "Mean reciprocal rank over expected targets."),
        _experiment_metric("Distractor@1", metrics.get("distractor_top1_rate", 0.0), "lower", "Known hard-negative distractor reaches rank 1."),
        _experiment_metric("Projected Top-1", diag_summary.get("projected_top1_accuracy", metrics.get("top1_accuracy", 0.0)), "higher", "Counterfactual ceiling after targeted repairs."),
    ]
    taxonomy = list(diagnostics.get("taxonomy") or [])
    case_failures = [
        item
        for item in diagnostics.get("case_diagnostics", [])
        if item.get("severity") != "pass"
    ]
    repair_readiness = {
        "repair_card_status": repair_card.get("status", ""),
        "repair_card_score": int(repair_card.get("score", 0)),
        "passed_guards": int(repair_summary.get("passed_guards", 0)),
        "guard_count": int(repair_summary.get("guard_count", 0)),
        "synthesis_status": repair_synthesis.get("status", ""),
        "validated_rules": int(synthesis_summary.get("validated_rule_count", 0)),
        "proposed_rules": int(synthesis_summary.get("proposed_rule_count", 0)),
        "projected_top1_delta": float(synthesis_summary.get("projected_top1_delta", 0.0)),
    }
    claims = [
        {
            "id": "portable_external_validity",
            "claim": "Third-party localization suites can be represented as portable repo/question/expected-target JSON.",
            "supported": dataset["case_count"] > 0 and dataset["repo_group_count"] > 0,
            "evidence": [str(benchmark_path), "benchmark adapter metrics"],
        },
        {
            "id": "hard_negative_accounting",
            "claim": "Hard-negative distractors are measured explicitly instead of hidden inside Top-k accuracy.",
            "supported": "distractor_top1_rate" in metrics,
            "evidence": ["Distractor@1 metric", f"{dataset['hard_negative_case_count']} hard-negative cases"],
        },
        {
            "id": "repairable_failure_taxonomy",
            "claim": "Benchmark failures are converted into taxonomy labels and counterfactual repair ceilings.",
            "supported": diagnostics.get("status") in {"clean", "actionable", "blocked"} and "projected_top1_accuracy" in diag_summary,
            "evidence": [str(diagnostics_path or "generated diagnostics"), f"{len(taxonomy)} taxonomy labels"],
        },
        {
            "id": "repair_evidence_closure",
            "claim": "Repair claims are only accepted when ranking guards or synthesized rules expose explicit evidence.",
            "supported": repair_card.get("status") in {"validated", "partial", "needs_repair"} and repair_synthesis.get("status") in {"validated", "repair_plan", "needs_more_evidence", "no_counterexamples"},
            "evidence": [str(repair_card_path or "generated repair card"), str(repair_synthesis_path or "generated repair synthesis")],
        },
    ]
    supported_claims = sum(1 for claim in claims if claim["supported"])
    status = "accepted" if supported_claims == len(claims) and diagnostics.get("status") != "blocked" else "accepted_with_limitations"
    score = int(
        round(
            100
            * _mean(
                float(metrics.get("top3_accuracy", 0.0)),
                1.0 - float(metrics.get("distractor_top1_rate", 0.0)),
                supported_claims / max(1, len(claims)),
                max(0.0, min(1.0, int(repair_card.get("score", 0)) / 100.0)),
            )
        )
    )
    return {
        "schema_version": "1.0",
        "strategy": "portable_benchmark_experiment_report",
        "benchmark_path": str(benchmark_path),
        "diagnostics_path": str(diagnostics_path) if diagnostics_path else "",
        "repair_card_path": str(repair_card_path) if repair_card_path else "",
        "repair_synthesis_path": str(repair_synthesis_path) if repair_synthesis_path else "",
        "source_benchmark_sha256": _sha256_file(benchmark_path) if benchmark_path.is_file() else "",
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "dataset": dataset,
        "metrics_table": metrics_table,
        "taxonomy": taxonomy,
        "case_failures": case_failures,
        "repair_readiness": repair_readiness,
        "claims": claims,
        "summary": {
            "supported_claims": supported_claims,
            "claim_count": len(claims),
            "weak_case_count": int(diag_summary.get("weak_case_count", 0)),
            "blocker_count": int(diag_summary.get("blocker_count", 0)),
            "taxonomy_count": len(taxonomy),
            "generalization_gap_count": len(benchmark.get("generalization_gaps", [])),
            "projected_top1_accuracy": float(diag_summary.get("projected_top1_accuracy", metrics.get("top1_accuracy", 0.0))),
        },
        "reproducibility": [
            f"python -m repo_agent benchmark-adapter --suite {benchmark.get('suite_path', '<suite.json>')} --output reports/benchmark-adapter.json --json",
            "python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-adapter.json --output reports/benchmark-diagnostics.json --json",
            "python -m repo_agent benchmark-repair-card --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-card.json --json",
            "python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.json --json",
            "python -m repo_agent benchmark-experiment-report --benchmark reports/benchmark-adapter.json --diagnostics reports/benchmark-diagnostics.json --repair-card reports/benchmark-repair-card.json --repair-synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-experiment-report.md",
        ],
        "falsifiers": [
            "A third-party suite cannot be represented without code changes.",
            "Distractor@1 is omitted or cannot identify hard-negative rank-1 failures.",
            "Diagnostics report a clean suite while weak cases or generalization gaps remain.",
            "Repair synthesis claims validation without explicit top-hit reason evidence or implementation anchors.",
        ],
        "evidence_hash": _stable_short_hash(
            {
                "benchmark": _sha256_file(benchmark_path) if benchmark_path.is_file() else "",
                "metrics": metrics_table,
                "taxonomy": [(item.get("label"), item.get("count")) for item in taxonomy],
                "claims": [(item["id"], item["supported"]) for item in claims],
                "repair": repair_readiness,
            }
        ),
    }


def _experiment_metric(name: str, value: object, direction: str, interpretation: str) -> dict:
    return {
        "name": name,
        "value": float(value or 0.0),
        "direction": direction,
        "interpretation": interpretation,
    }


def render_benchmark_experiment_report_markdown(payload: dict) -> str:
    dataset = dict(payload.get("dataset") or {})
    repair = dict(payload.get("repair_readiness") or {})
    lines = [
        "# Repo Agent Benchmark Experiment Report",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{dataset.get('suite_id', '')}`",
        f"- Cases: `{int(dataset.get('case_count', 0))}`",
        f"- Repositories: `{int(dataset.get('repo_group_count', 0))}`",
        f"- Tags: `{int(dataset.get('tag_group_count', 0))}`",
        f"- Hard-negative cases: `{int(dataset.get('hard_negative_case_count', 0))}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Direction | Interpretation |",
        "| --- | ---: | --- | --- |",
    ]
    for item in payload.get("metrics_table", []):
        lines.append(
            f"| `{item.get('name', '')}` | {float(item.get('value', 0.0)):.2%} | `{item.get('direction', '')}` | "
            f"{_markdown_cell(item.get('interpretation', ''))} |"
        )
    lines.extend(
        [
            "",
            "## Failure Taxonomy",
            "",
            "| Label | Count | Severity | Recommendation |",
            "| --- | ---: | --- | --- |",
        ]
    )
    taxonomy = payload.get("taxonomy", [])
    if taxonomy:
        for item in taxonomy:
            lines.append(
                f"| `{item.get('label', '')}` | {int(item.get('count', 0))} | `{item.get('severity', '')}` | "
                f"{_markdown_cell(item.get('recommendation', ''))} |"
            )
    else:
        lines.append("| `none` | 0 | `pass` | No failure taxonomy labels were emitted. |")
    lines.extend(
        [
            "",
            "## Repair Readiness",
            "",
            f"- Repair card: `{repair.get('repair_card_status', '')}` (`{int(repair.get('passed_guards', 0))}/{int(repair.get('guard_count', 0))}` guards)",
            f"- Repair synthesis: `{repair.get('synthesis_status', '')}` (`{int(repair.get('validated_rules', 0))}` validated, `{int(repair.get('proposed_rules', 0))}` proposed)",
            f"- Projected Top-1 delta: `{float(repair.get('projected_top1_delta', 0.0)):.2%}`",
            "",
            "## Claims",
            "",
            "| Claim | Supported | Evidence |",
            "| --- | --- | --- |",
        ]
    )
    for claim in payload.get("claims", []):
        evidence = "; ".join(str(item) for item in claim.get("evidence", []))
        lines.append(
            f"| `{claim.get('id', '')}` | `{bool(claim.get('supported'))}` | {_markdown_cell(evidence)} |"
        )
    lines.extend(
        [
            "",
            "## Weak Cases",
            "",
            "| Case | Severity | Rank | Taxonomy | Recommendation |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    failures = payload.get("case_failures", [])
    if failures:
        for item in failures:
            rank = item.get("rank") if item.get("rank") is not None else "miss"
            lines.append(
                f"| `{_markdown_cell(item.get('id', ''))}` | `{item.get('severity', '')}` | {rank} | "
                f"{_markdown_cell(', '.join(item.get('taxonomy', [])))} | {_markdown_cell(item.get('recommendation', ''))} |"
            )
    else:
        lines.append("| `none` | `pass` | 1 | `none` | No weak cases remain. |")
    lines.extend(["", "## Reproducibility", "", "| Step | Command |", "| ---: | --- |"])
    for index, command in enumerate(payload.get("reproducibility", []), start=1):
        lines.append(f"| {index} | `{_markdown_cell(command)}` |")
    lines.extend(["", "## Falsifiers", ""])
    for item in payload.get("falsifiers", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_benchmark_experiment_report_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_experiment_report_markdown(payload), encoding="utf-8")
    return output_path


def _benchmark_case_diagnosis(record: dict) -> dict:
    rank = record.get("rank")
    distractor_rank = record.get("distractor_rank")
    tags = [str(tag) for tag in record.get("tags", [])]
    tag_set = {tag.lower() for tag in tags}
    taxonomy = []
    if rank is None:
        taxonomy.append("expected_missing_from_topk")
    elif rank > 3:
        taxonomy.append("top3_miss")
    elif rank > 1:
        taxonomy.append("top3_recoverable")
    if distractor_rank == 1:
        taxonomy.append("rank1_distractor")
    elif isinstance(distractor_rank, int) and distractor_rank <= 3:
        taxonomy.append("near_rank_distractor")
    if float(record.get("confidence", 0.0)) < 0.75:
        taxonomy.append("low_confidence")
    if "route-grounded" in tag_set and rank != 1:
        taxonomy.append("route_anchor_weakness")
    if ({"library", "retrieval"} & tag_set) and rank != 1:
        taxonomy.append("library_boundary_ambiguity")
    if "streaming" in tag_set and rank != 1:
        taxonomy.append("streaming_handler_ambiguity")
    expected_symbol = str(record.get("expected_symbol_contains", "")).lower()
    question = str(record.get("question", "")).lower()
    if expected_symbol and expected_symbol not in question and rank != 1:
        taxonomy.append("hidden_symbol_query")
    taxonomy = sorted(set(taxonomy))
    severity = "pass"
    if {"expected_missing_from_topk", "top3_miss", "rank1_distractor"} & set(taxonomy):
        severity = "blocker"
    elif taxonomy:
        severity = "action"
    return {
        "id": record.get("id", ""),
        "repo_key": record.get("repo_key", ""),
        "rank": rank,
        "top_hit": record.get("top_hit", ""),
        "expected_path": record.get("expected_path", ""),
        "expected_symbol_contains": record.get("expected_symbol_contains", ""),
        "tags": tags,
        "severity": severity,
        "taxonomy": taxonomy,
        "recommendation": _benchmark_case_recommendation(taxonomy),
        "evidence_hash": record.get("evidence_hash", ""),
    }


def _benchmark_group_diagnostics(benchmark: dict, *, min_top1: float, min_top3: float) -> list[dict]:
    diagnostics = []
    for scope, items, key in (("repo", benchmark.get("by_repo", []), "repo"), ("tag", benchmark.get("by_tag", []), "tag")):
        for item in items:
            top1 = float(item.get("top1_accuracy", 0.0))
            top3 = float(item.get("top3_accuracy", 0.0))
            distractor = float(item.get("distractor_top1_rate", 0.0))
            if top3 < min_top3 or distractor > 0.0:
                severity = "blocker"
            elif top1 < min_top1:
                severity = "action"
            else:
                continue
            diagnostics.append(
                {
                    "scope": scope,
                    "id": item.get(key, ""),
                    "severity": severity,
                    "case_count": int(item.get("case_count", 0)),
                    "top1_accuracy": top1,
                    "top3_accuracy": top3,
                    "mrr": float(item.get("mrr", 0.0)),
                    "distractor_top1_rate": distractor,
                    "recommendation": _benchmark_group_recommendation(scope, item, severity),
                    "evidence_hash": _stable_short_hash({"scope": scope, "id": item.get(key, ""), "top1": top1, "top3": top3, "distractor": distractor}),
                }
            )
    diagnostics.sort(key=lambda item: (item["severity"] != "blocker", item["top3_accuracy"], item["top1_accuracy"], item["scope"], str(item["id"])))
    return diagnostics


def _benchmark_counterfactual_interventions(cases: list[dict], metrics: dict) -> list[dict]:
    total = max(len(cases), 1)
    current_top1 = sum(1 for record in cases if record.get("rank") == 1)
    interventions = []
    specs = [
        (
            "promote_top3_expected_to_rank1",
            [record for record in cases if isinstance(record.get("rank"), int) and 1 < record.get("rank") <= 3],
            "If Top-3 recoverable cases are disambiguated with targeted route/library/streaming guards, they become rank-1.",
        ),
        (
            "eliminate_rank1_distractors",
            [record for record in cases if record.get("distractor_rank") == 1],
            "If known distractors are demoted from rank-1, hard-negative failures stop blocking the suite.",
        ),
        (
            "route_anchor_backfill",
            [record for record in cases if "route-grounded" in {str(tag).lower() for tag in record.get("tags", [])} and record.get("rank") != 1],
            "If route-grounded misses receive explicit route-anchor evidence, endpoint-localization Top-1 should improve.",
        ),
        (
            "library_boundary_guard",
            [record for record in cases if {"library", "retrieval"} & {str(tag).lower() for tag in record.get("tags", [])} and record.get("rank") != 1],
            "If library/retrieval cases get module-boundary priors, helper implementations can outrank nearby handlers.",
        ),
    ]
    for intervention_id, affected, rationale in specs:
        affected_ids = [str(record.get("id", "")) for record in affected]
        projected_top1 = (current_top1 + len([record for record in affected if record.get("rank") != 1])) / total
        interventions.append(
            {
                "id": intervention_id,
                "affected_cases": len(affected),
                "affected_case_ids": affected_ids,
                "projected_top1_accuracy": min(1.0, projected_top1),
                "rationale": rationale,
                "evidence_hash": _stable_short_hash({"id": intervention_id, "affected": affected_ids, "current": metrics.get("top1_accuracy", 0.0)}),
            }
        )
    return interventions


def _benchmark_case_recommendation(taxonomy: list[str]) -> str:
    if not taxonomy:
        return "Keep as regression coverage; no action needed."
    if "rank1_distractor" in taxonomy:
        return "Add or strengthen hard-negative demotion before trusting this suite."
    if "top3_recoverable" in taxonomy:
        if "library_boundary_ambiguity" in taxonomy:
            return "Add module-boundary and helper-symbol priors, then verify the expected helper moves from Top-3 to rank-1."
        if "streaming_handler_ambiguity" in taxonomy:
            return "Separate stream entrypoint and stream writer evidence so adjacent handlers do not steal rank-1."
        if "route_anchor_weakness" in taxonomy:
            return "Require explicit route-anchor proof for this query family."
        return "Inspect the Top-3 set and add a narrow rerank guard for the ambiguous evidence family."
    if "top3_miss" in taxonomy or "expected_missing_from_topk" in taxonomy:
        return "Treat as a benchmark blocker; collect missing graph, symbol, or file-scout evidence before tuning."
    return "Review taxonomy labels and add a targeted benchmark guard."


def _benchmark_group_recommendation(scope: str, item: dict, severity: str) -> str:
    if severity == "blocker":
        return "Block release or mark the suite as externally weak until Top-3 and distractor thresholds recover."
    return f"Add focused cases or rerank guards for this {scope}; Top-3 is healthy but rank-1 evidence is under-specified."


def _benchmark_taxonomy_severity(label: str) -> str:
    if label in {"expected_missing_from_topk", "top3_miss", "rank1_distractor"}:
        return "blocker"
    return "action"


def _benchmark_taxonomy_recommendation(label: str) -> str:
    recommendations = {
        "top3_recoverable": "Use Top-3 as a counterfactual ceiling and add a narrow disambiguation guard.",
        "near_rank_distractor": "Keep distractor labels in the suite and audit whether they move toward rank-1.",
        "low_confidence": "Require proof replay or abstention before accepting this answer family.",
        "route_anchor_weakness": "Bind evidence to explicit route literals and route-to-symbol paths.",
        "library_boundary_ambiguity": "Add module-boundary priors so helper libraries can outrank callers.",
        "streaming_handler_ambiguity": "Separate streaming entrypoints, stream turn orchestration, and token writers.",
        "hidden_symbol_query": "Evaluate whether natural-language queries need symbol-free semantic coverage.",
        "expected_missing_from_topk": "Expand indexing or graph scouting before using this suite as a release claim.",
        "top3_miss": "Treat as a blocking generalization gap and collect new evidence signals.",
        "rank1_distractor": "Strengthen hard-negative demotion and require distractor@1 to return to zero.",
    }
    return recommendations.get(label, "Review the affected cases and add a targeted guard.")


def build_benchmark_repair_card(benchmark_path: Path) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    cases = list(benchmark.get("cases") or [])
    metrics = dict(benchmark.get("metrics") or {})
    guard_specs = [
        {
            "id": "streaming_handler_disambiguation",
            "reason": "streaming handler disambiguation",
            "tags": ("streaming",),
            "description": "Stream-specific handler names should outrank adjacent sync handlers when the query asks for streaming.",
        },
        {
            "id": "retrieval_library_boundary_prior",
            "reason": "retrieval helper target",
            "secondary_reason": "library boundary prior",
            "tags": ("retrieval", "library"),
            "description": "Retrieval/read-first questions should prefer library helpers over upload/text entry handlers.",
        },
    ]
    guard_results = []
    for spec in guard_specs:
        related_cases = [
            record
            for record in cases
            if set(str(tag).lower() for tag in record.get("tags", [])).intersection(set(spec["tags"]))
        ]
        evidence_cases = []
        for record in related_cases:
            reasons = [str(reason) for reason in record.get("top_hit_reasons", [])]
            reason_text = " | ".join(reasons).lower()
            primary = str(spec["reason"]).lower() in reason_text
            secondary = not spec.get("secondary_reason") or str(spec["secondary_reason"]).lower() in reason_text
            if record.get("rank") == 1 and primary and secondary:
                evidence_cases.append(record.get("id", ""))
        guard_results.append(
            {
                "id": spec["id"],
                "description": spec["description"],
                "related_case_count": len(related_cases),
                "evidence_case_count": len(evidence_cases),
                "evidence_cases": evidence_cases,
                "passed": bool(evidence_cases) if related_cases else True,
                "required_reason": spec["reason"],
                "secondary_reason": spec.get("secondary_reason", ""),
                "evidence_hash": _stable_short_hash({"id": spec["id"], "cases": evidence_cases}),
            }
        )
    case_results = [
        {
            "id": record.get("id", ""),
            "rank": record.get("rank"),
            "top_hit": record.get("top_hit", ""),
            "passed": record.get("rank") == 1,
            "repair_reasons": [
                reason
                for reason in record.get("top_hit_reasons", [])
                if str(reason).lower() in {"streaming handler disambiguation", "retrieval helper target", "library boundary prior"}
            ],
            "evidence_hash": record.get("evidence_hash", ""),
        }
        for record in cases
    ]
    top1 = float(metrics.get("top1_accuracy", 0.0))
    guard_passed = sum(1 for item in guard_results if item["passed"])
    all_cases_top1 = all(item["passed"] for item in case_results)
    status = "validated" if all_cases_top1 and guard_passed == len(guard_results) else "needs_repair" if not all_cases_top1 else "partial"
    score = int(round(100 * _mean(top1, guard_passed / max(1, len(guard_results)))))
    return {
        "schema_version": "1.0",
        "strategy": "portable_benchmark_repair_card",
        "benchmark_path": str(benchmark_path),
        "source_benchmark_sha256": _sha256_file(benchmark_path) if benchmark_path.is_file() else "",
        "suite_id": benchmark.get("suite_id", ""),
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "summary": {
            "case_count": len(case_results),
            "top1_accuracy": top1,
            "mrr": float(metrics.get("mrr", 0.0)),
            "guard_count": len(guard_results),
            "passed_guards": guard_passed,
            "top1_case_count": sum(1 for item in case_results if item["passed"]),
            "repair_reason_case_count": sum(1 for item in case_results if item["repair_reasons"]),
        },
        "guards": guard_results,
        "cases": case_results,
        "review_protocol": [
            {
                "step": "verify_adapter_top1",
                "detail": "All portable benchmark cases must rank the expected code at position 1 after repair.",
            },
            {
                "step": "audit_repair_reasons",
                "detail": "Previously weak families must carry explicit repair reasons in the top-hit evidence.",
            },
            {
                "step": "rerun_diagnostics",
                "detail": "benchmark-diagnose should report clean or zero blockers after the repair card is validated.",
            },
        ],
        "evidence_hash": _stable_short_hash(
            {
                "suite": benchmark.get("suite_id", ""),
                "status": status,
                "top1": top1,
                "guards": [(item["id"], item["passed"], item["evidence_cases"]) for item in guard_results],
            }
        ),
    }


def write_benchmark_repair_card_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_repair_card_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_repair_card_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Benchmark Repair Card",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Top-1: `{float(summary.get('top1_accuracy', 0.0)):.2%}`",
        f"- Guards: `{int(summary.get('passed_guards', 0))}/{int(summary.get('guard_count', 0))}`",
        f"- Repair-reason cases: `{int(summary.get('repair_reason_case_count', 0))}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Repair Guards",
        "",
        "| Guard | Result | Cases | Required Evidence | Description |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in payload.get("guards", []):
        result = "PASS" if item.get("passed") else "FAIL"
        required = item.get("required_reason", "")
        if item.get("secondary_reason"):
            required = f"{required}; {item.get('secondary_reason')}"
        lines.append(
            f"| `{item.get('id', '')}` | `{result}` | {int(item.get('evidence_case_count', 0))}/"
            f"{int(item.get('related_case_count', 0))} | `{_markdown_cell(required)}` | "
            f"{_markdown_cell(item.get('description', ''))} |"
        )
    lines.extend(["", "## Case Repair Evidence", "", "| Case | Rank | Top Hit | Repair Reasons | Evidence |", "| --- | ---: | --- | --- | --- |"])
    for item in payload.get("cases", []):
        rank = item.get("rank") if item.get("rank") is not None else "miss"
        lines.append(
            f"| `{_markdown_cell(item.get('id', ''))}` | {rank} | `{_markdown_cell(item.get('top_hit', ''))}` | "
            f"{_markdown_cell(', '.join(item.get('repair_reasons', [])))} | `{item.get('evidence_hash', '')}` |"
        )
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def synthesize_benchmark_repair_rules(benchmark_path: Path) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    cases = list(benchmark.get("cases") or [])
    baseline_metrics = dict(benchmark.get("metrics") or {})
    total = max(len(cases), 1)
    candidate_specs = [
        {
            "id": "promote_streaming_handler_intent",
            "family": "intent_disambiguation",
            "tags": {"streaming"},
            "query_terms": {"stream", "streaming", "streamed", "sse"},
            "reason_terms": {"streaming handler disambiguation"},
            "description": "When the query asks for streaming, promote the handler whose name/body carries stream-specific evidence.",
            "rule_dsl": {
                "if": ["query_mentions_streaming", "candidate_has_streaming_symbol_or_body"],
                "then": "boost_candidate",
                "because": "stream handlers are often adjacent to sync handlers and writers with overlapping vocabulary",
            },
        },
        {
            "id": "prefer_retrieval_library_boundary",
            "family": "module_boundary_prior",
            "tags": {"retrieval", "library", "rag"},
            "query_terms": {"retrieve", "retrieval", "rag", "read first", "understand"},
            "reason_terms": {"retrieval helper target", "library boundary prior"},
            "description": "For retrieval/read-first questions, prefer library helpers over route/upload entry handlers.",
            "rule_dsl": {
                "if": ["query_mentions_retrieval_or_read_first", "candidate_is_library_helper"],
                "then": "boost_candidate_and_demote_entrypoint_detours",
                "because": "repository readers need the implementation boundary, not just the HTTP entrypoint",
            },
        },
        {
            "id": "route_anchor_backfill",
            "family": "graph_anchor",
            "tags": {"route-grounded"},
            "query_terms": {"/api/", "route", "endpoint"},
            "reason_terms": {"route literal match", "route function target", "route path evidence"},
            "description": "When a query names an endpoint, require route-literal or route-to-symbol graph evidence before accepting rank-1.",
            "rule_dsl": {
                "if": ["query_mentions_route_or_endpoint", "candidate_has_route_literal_or_route_graph_path"],
                "then": "boost_candidate",
                "because": "route-localization failures are often caused by nearby admin or legacy handlers",
            },
        },
        {
            "id": "demote_rank1_hard_negative",
            "family": "counterexample_guard",
            "tags": {"hard-negative"},
            "query_terms": {"public", "admin", "legacy", "mock", "fake"},
            "reason_terms": {"distractor demotion", "hard-negative guard", "public route disambiguation"},
            "description": "If a labeled distractor reaches rank-1, synthesize a narrow demotion guard tied to the counterexample label.",
            "rule_dsl": {
                "if": ["candidate_matches_labeled_distractor", "expected_candidate_is_in_topk"],
                "then": "demote_distractor_and_promote_expected",
                "because": "hard-negative labels should become regression guards rather than post-hoc explanations",
            },
        },
        {
            "id": "symbol_free_semantic_bridge",
            "family": "semantic_bridge",
            "tags": {"hidden-symbol"},
            "query_terms": {"which", "where", "understand", "flow"},
            "reason_terms": {"semantic symbol bridge", "hidden symbol query"},
            "description": "When the expected symbol is absent from the natural-language query, mine surrounding tokens to bridge query intent to symbol names.",
            "rule_dsl": {
                "if": ["expected_symbol_not_mentioned", "expected_candidate_is_in_topk"],
                "then": "derive_intent_terms_from_expected_context",
                "because": "external benchmarks often ask behavioral questions without naming implementation symbols",
            },
        },
    ]
    candidates = [_synthesize_repair_candidate(spec, cases, total) for spec in candidate_specs]
    proposed_candidates = [item for item in candidates if item["status"] == "proposed"]
    validated_candidates = [item for item in candidates if item["status"] == "validated"]
    simulated_metrics = _simulate_synthesized_repair_metrics(cases, proposed_candidates)
    baseline_top1 = float(baseline_metrics.get("top1_accuracy", 0.0))
    projected_top1 = float(simulated_metrics.get("top1_accuracy", baseline_top1))
    if proposed_candidates:
        status = "repair_plan"
    elif validated_candidates and baseline_top1 >= 1.0:
        status = "validated"
    elif baseline_top1 >= 1.0:
        status = "no_counterexamples"
    else:
        status = "needs_more_evidence"
    coverage_case_ids = sorted(
        {
            str(case_id)
            for candidate in candidates
            for case_id in candidate.get("affected_case_ids", []) + candidate.get("validated_case_ids", [])
        }
    )
    score = int(
        round(
            100
            * _mean(
                baseline_top1,
                projected_top1,
                len(validated_candidates) / max(1, len([item for item in candidates if item["status"] != "dormant"])),
            )
        )
    )
    return {
        "schema_version": "1.0",
        "strategy": "counterexample_guided_retrieval_repair_synthesis",
        "benchmark_path": str(benchmark_path),
        "source_benchmark_sha256": _sha256_file(benchmark_path) if benchmark_path.is_file() else "",
        "suite_id": benchmark.get("suite_id", ""),
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "baseline_metrics": {
            "case_count": int(baseline_metrics.get("case_count", len(cases))),
            "top1_accuracy": baseline_top1,
            "top3_accuracy": float(baseline_metrics.get("top3_accuracy", 0.0)),
            "mrr": float(baseline_metrics.get("mrr", 0.0)),
            "distractor_top1_rate": float(baseline_metrics.get("distractor_top1_rate", 0.0)),
        },
        "simulated_metrics": simulated_metrics,
        "summary": {
            "candidate_count": len(candidates),
            "proposed_rule_count": len(proposed_candidates),
            "validated_rule_count": len(validated_candidates),
            "dormant_rule_count": sum(1 for item in candidates if item["status"] == "dormant"),
            "coverage_case_count": len(coverage_case_ids),
            "closed_gap_count": sum(len(item.get("affected_case_ids", [])) for item in proposed_candidates),
            "projected_top1_delta": projected_top1 - baseline_top1,
        },
        "rules": candidates,
        "review_protocol": [
            {
                "step": "inspect_counterexamples",
                "detail": "Review proposed rules first; each proposal names the exact cases whose expected answer is inside Top-k but not rank-1.",
            },
            {
                "step": "implement_narrow_guard",
                "detail": "Translate only one rule family at a time into reranker logic and emit an explicit top-hit reason.",
            },
            {
                "step": "rerun_replay",
                "detail": "Rerun benchmark-adapter, benchmark-diagnose, benchmark-repair-card, and benchmark-repair-synthesize to prove the rule became validated.",
            },
        ],
        "evidence_hash": _stable_short_hash(
            {
                "suite": benchmark.get("suite_id", ""),
                "status": status,
                "rules": [
                    (item["id"], item["status"], item["affected_case_ids"], item["validated_case_ids"])
                    for item in candidates
                ],
                "projection": simulated_metrics,
            }
        ),
    }


def _synthesize_repair_candidate(spec: dict, cases: list[dict], total: int) -> dict:
    affected_cases = []
    validated_cases = []
    risk_cases = []
    for record in cases:
        tags = {str(tag).lower() for tag in record.get("tags", [])}
        question = str(record.get("question", "")).lower()
        expected_symbol = str(record.get("expected_symbol_contains", "")).lower()
        rank = record.get("rank")
        expected_in_topk = _benchmark_record_expected_in_topk(record)
        reason_text = _benchmark_record_reason_text(record)
        tag_match = bool(tags & set(spec.get("tags", set())))
        query_match = any(term in question for term in spec.get("query_terms", set()))
        reason_match = any(term in reason_text for term in spec.get("reason_terms", set()))
        hidden_symbol_match = spec["id"] == "symbol_free_semantic_bridge" and expected_symbol and expected_symbol not in question
        hard_negative_match = spec["id"] == "demote_rank1_hard_negative" and record.get("distractor_rank") == 1
        if record.get("rank") == 1 and reason_match:
            validated_cases.append(str(record.get("id", "")))
        if hard_negative_match or ((tag_match or query_match or hidden_symbol_match) and rank != 1 and expected_in_topk):
            affected_cases.append(str(record.get("id", "")))
        if (tag_match or query_match) and rank == 1 and not reason_match and spec["id"] in {"route_anchor_backfill", "symbol_free_semantic_bridge"}:
            risk_cases.append(str(record.get("id", "")))
    affected_cases = sorted(set(affected_cases))
    validated_cases = sorted(set(validated_cases))
    risk_cases = sorted(set(risk_cases) - set(validated_cases))
    if affected_cases:
        status = "proposed"
    elif validated_cases:
        status = "validated"
    else:
        status = "dormant"
    projected = _project_candidate_metrics(cases, affected_cases, total)
    confidence = _synthesis_rule_confidence(status, affected_cases, validated_cases, risk_cases)
    return {
        "id": spec["id"],
        "family": spec["family"],
        "status": status,
        "confidence": confidence,
        "description": spec["description"],
        "rule_dsl": spec["rule_dsl"],
        "affected_case_ids": affected_cases,
        "validated_case_ids": validated_cases,
        "risk_case_ids": risk_cases,
        "support": {
            "affected_cases": len(affected_cases),
            "validated_cases": len(validated_cases),
            "risk_cases": len(risk_cases),
            "trigger_tags": sorted(spec.get("tags", set())),
            "reason_terms": sorted(spec.get("reason_terms", set())),
        },
        "projected_metrics": projected,
        "evidence_hash": _stable_short_hash(
            {
                "id": spec["id"],
                "status": status,
                "affected": affected_cases,
                "validated": validated_cases,
                "risk": risk_cases,
                "confidence": confidence,
            }
        ),
    }


def _benchmark_record_reason_text(record: dict) -> str:
    reasons = [str(reason) for reason in record.get("top_hit_reasons", [])]
    for hit in record.get("top_hits_detail", []) or []:
        reasons.extend(str(reason) for reason in hit.get("reasons", []))
    return " | ".join(reasons).lower()


def _benchmark_record_expected_in_topk(record: dict) -> bool:
    expected_path = str(record.get("expected_path", "")).replace("\\", "/").lower()
    expected_symbol = str(record.get("expected_symbol_contains", "")).lower()
    labels = [str(label) for label in record.get("top_hits", [])]
    labels.extend(str(hit.get("source_label", "")) for hit in record.get("top_hits_detail", []) or [])
    for label in labels:
        normalized = label.replace("\\", "/").lower()
        path_match = not expected_path or expected_path in normalized
        symbol_match = not expected_symbol or expected_symbol in normalized
        if path_match and symbol_match:
            return True
    return False


def _project_candidate_metrics(cases: list[dict], affected_case_ids: list[str], total: int) -> dict:
    affected = set(affected_case_ids)
    projected_ranks = []
    for record in cases:
        rank = record.get("rank")
        if str(record.get("id", "")) in affected:
            projected_ranks.append(1)
        else:
            projected_ranks.append(rank if isinstance(rank, int) else None)
    return {
        "top1_accuracy": sum(1 for rank in projected_ranks if rank == 1) / total,
        "top3_accuracy": sum(1 for rank in projected_ranks if isinstance(rank, int) and rank <= 3) / total,
        "mrr": sum((1 / rank) if isinstance(rank, int) and rank > 0 else 0.0 for rank in projected_ranks) / total,
    }


def _simulate_synthesized_repair_metrics(cases: list[dict], proposed_candidates: list[dict]) -> dict:
    total = max(len(cases), 1)
    affected = {
        str(case_id)
        for candidate in proposed_candidates
        for case_id in candidate.get("affected_case_ids", [])
    }
    projected_ranks = []
    projected_distractor_top1 = 0
    for record in cases:
        case_id = str(record.get("id", ""))
        rank = record.get("rank")
        if case_id in affected:
            projected_ranks.append(1)
        else:
            projected_ranks.append(rank if isinstance(rank, int) else None)
            if record.get("distractor_rank") == 1:
                projected_distractor_top1 += 1
    return {
        "case_count": len(cases),
        "top1_accuracy": sum(1 for rank in projected_ranks if rank == 1) / total,
        "top3_accuracy": sum(1 for rank in projected_ranks if isinstance(rank, int) and rank <= 3) / total,
        "mrr": sum((1 / rank) if isinstance(rank, int) and rank > 0 else 0.0 for rank in projected_ranks) / total,
        "distractor_top1_rate": projected_distractor_top1 / total,
    }


def _synthesis_rule_confidence(status: str, affected_cases: list[str], validated_cases: list[str], risk_cases: list[str]) -> int:
    if status == "validated":
        return max(80, min(100, 86 + 7 * len(validated_cases) - 5 * len(risk_cases)))
    if status == "proposed":
        return max(45, min(88, 58 + 8 * len(affected_cases) + 4 * len(validated_cases) - 6 * len(risk_cases)))
    return 30


def write_benchmark_repair_synthesis_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_repair_synthesis_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_repair_synthesis_markdown(payload: dict) -> str:
    baseline = dict(payload.get("baseline_metrics") or {})
    simulated = dict(payload.get("simulated_metrics") or {})
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Benchmark Repair Synthesizer",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Baseline Top-1: `{float(baseline.get('top1_accuracy', 0.0)):.2%}`",
        f"- Projected Top-1: `{float(simulated.get('top1_accuracy', 0.0)):.2%}`",
        f"- Proposed rules: `{int(summary.get('proposed_rule_count', 0))}`",
        f"- Validated rules: `{int(summary.get('validated_rule_count', 0))}`",
        f"- Coverage cases: `{int(summary.get('coverage_case_count', 0))}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Synthesized Rules",
        "",
        "| Rule | Status | Confidence | Affected | Validated | Risk | Projected Top-1 | Description |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in payload.get("rules", []):
        projected = dict(item.get("projected_metrics") or {})
        support = dict(item.get("support") or {})
        lines.append(
            f"| `{item.get('id', '')}` | `{item.get('status', '')}` | {int(item.get('confidence', 0))} | "
            f"{int(support.get('affected_cases', 0))} | {int(support.get('validated_cases', 0))} | "
            f"{int(support.get('risk_cases', 0))} | {float(projected.get('top1_accuracy', 0.0)):.2%} | "
            f"{_markdown_cell(item.get('description', ''))} |"
        )
    lines.extend(["", "## Rule DSL", "", "| Rule | If | Then | Because | Evidence |", "| --- | --- | --- | --- | --- |"])
    for item in payload.get("rules", []):
        rule = dict(item.get("rule_dsl") or {})
        lines.append(
            f"| `{item.get('id', '')}` | {_markdown_cell(', '.join(rule.get('if', [])))} | "
            f"`{_markdown_cell(rule.get('then', ''))}` | {_markdown_cell(rule.get('because', ''))} | "
            f"`{item.get('evidence_hash', '')}` |"
        )
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def verify_benchmark_repair_implementation(synthesis_path: Path, *, source_path: Path) -> dict:
    synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
    source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
    rules = []
    for rule in synthesis.get("rules", []):
        rules.append(_verify_repair_rule_implementation(rule, source_path=source_path, source_text=source_text))
    validated_rules = [item for item in rules if item["synthesis_status"] == "validated"]
    proposed_rules = [item for item in rules if item["synthesis_status"] == "proposed"]
    missing_validated = [item for item in validated_rules if item["implementation_status"] != "implemented"]
    implemented_validated = [item for item in validated_rules if item["implementation_status"] == "implemented"]
    if missing_validated:
        status = "needs_implementation"
    elif proposed_rules:
        status = "implementation_plan"
    elif implemented_validated:
        status = "verified"
    else:
        status = "no_validated_rules"
    score = int(
        round(
            100
            * _mean(
                len(implemented_validated) / max(1, len(validated_rules)),
                1.0 if not missing_validated else 0.0,
                1.0 if source_path.is_file() else 0.0,
            )
        )
    )
    return {
        "schema_version": "1.0",
        "strategy": "counterexample_guided_retrieval_repair_implementation_verification",
        "synthesis_path": str(synthesis_path),
        "source_synthesis_sha256": _sha256_file(synthesis_path) if synthesis_path.is_file() else "",
        "source_path": str(source_path),
        "source_sha256": _sha256_file(source_path) if source_path.is_file() else "",
        "suite_id": synthesis.get("suite_id", ""),
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "summary": {
            "rule_count": len(rules),
            "validated_rule_count": len(validated_rules),
            "implemented_validated_rule_count": len(implemented_validated),
            "missing_validated_rule_count": len(missing_validated),
            "proposed_rule_count": len(proposed_rules),
            "source_available": source_path.is_file(),
            "anchor_count": sum(len(item.get("anchors", [])) for item in rules),
            "found_anchor_count": sum(1 for item in rules for anchor in item.get("anchors", []) if anchor.get("found")),
            "reason_count": sum(len(item.get("reasons", [])) for item in rules),
            "found_reason_count": sum(1 for item in rules for reason in item.get("reasons", []) if reason.get("found")),
        },
        "rules": rules,
        "review_protocol": [
            {
                "step": "verify_validated_rules",
                "detail": "Every validated synthesis rule must map to concrete helper/function anchors and emitted top-hit reason literals.",
            },
            {
                "step": "inspect_proposed_rules",
                "detail": "Proposed rules are implementation work items; do not mark them validated until a reranker reason appears in benchmark traces.",
            },
            {
                "step": "rerun_release_gate",
                "detail": "Run the release gate after implementation verification so manifest metrics, repair synthesis, and artifact review agree.",
            },
        ],
        "evidence_hash": _stable_short_hash(
            {
                "suite": synthesis.get("suite_id", ""),
                "status": status,
                "source": str(source_path),
                "rules": [
                    (
                        item["id"],
                        item["synthesis_status"],
                        item["implementation_status"],
                        [anchor["found"] for anchor in item["anchors"]],
                        [reason["found"] for reason in item["reasons"]],
                    )
                    for item in rules
                ],
            }
        ),
    }


def _verify_repair_rule_implementation(rule: dict, *, source_path: Path, source_text: str) -> dict:
    spec = _repair_rule_implementation_spec(str(rule.get("id", "")))
    anchors = [_source_term_evidence(source_text, term, kind="anchor") for term in spec["anchors"]]
    reasons = [_source_term_evidence(source_text, term, kind="reason") for term in spec["reasons"]]
    synthesis_status = str(rule.get("status", "unknown"))
    required = synthesis_status == "validated"
    anchors_ok = all(anchor["found"] for anchor in anchors) if anchors else False
    reasons_ok = all(reason["found"] for reason in reasons) if reasons else False
    if synthesis_status == "validated" and anchors_ok and reasons_ok:
        implementation_status = "implemented"
    elif synthesis_status == "validated":
        implementation_status = "missing_implementation"
    elif synthesis_status == "proposed":
        implementation_status = "patch_required"
    else:
        implementation_status = "advisory"
    return {
        "id": rule.get("id", ""),
        "family": rule.get("family", ""),
        "synthesis_status": synthesis_status,
        "implementation_status": implementation_status,
        "required": required,
        "source_path": str(source_path),
        "anchors": anchors,
        "reasons": reasons,
        "patch_hint": spec["patch_hint"],
        "evidence_hash": _stable_short_hash(
            {
                "id": rule.get("id", ""),
                "synthesis": synthesis_status,
                "status": implementation_status,
                "anchors": [(item["term"], item["found"], item.get("line")) for item in anchors],
                "reasons": [(item["term"], item["found"], item.get("line")) for item in reasons],
            }
        ),
    }


def _repair_rule_implementation_spec(rule_id: str) -> dict:
    specs = {
        "promote_streaming_handler_intent": {
            "anchors": ["STREAM_QUERY_TERMS", "_asks_for_streaming", "_chunk_matches_streaming_intent"],
            "reasons": ["streaming handler disambiguation"],
            "patch_hint": "Add stream-query detection, stream-candidate matching, and an emitted top-hit reason in the reranker.",
        },
        "prefer_retrieval_library_boundary": {
            "anchors": ["RETRIEVAL_QUERY_TERMS", "READ_FIRST_QUERY_TERMS", "_asks_for_retrieval_boundary", "_chunk_is_library_boundary"],
            "reasons": ["retrieval helper target", "library boundary prior", "entry handler boundary detour"],
            "patch_hint": "Add retrieval/read-first detection, library-boundary priors, and entry-handler detour demotion.",
        },
        "route_anchor_backfill": {
            "anchors": ["_query_route_literals", "_route_reachable_chunk_ids", "route_reachable_ids"],
            "reasons": ["exact route path evidence"],
            "patch_hint": "Bind route-mentioned queries to route literals and route-reachable graph paths before accepting rank-1.",
        },
        "demote_rank1_hard_negative": {
            "anchors": ["distractor", "excluded_symbols", "_chunk_writes_response"],
            "reasons": ["off-route writer decoy", "explicitly excluded by query"],
            "patch_hint": "Map labeled rank-1 distractors to narrow demotion rules and require a visible rejection reason.",
        },
        "symbol_free_semantic_bridge": {
            "anchors": ["latent", "semantic", "symbol"],
            "reasons": ["semantic"],
            "patch_hint": "Bridge behavior-only questions to symbol terms using surrounding implementation context.",
        },
    }
    return specs.get(
        rule_id,
        {
            "anchors": [rule_id],
            "reasons": [],
            "patch_hint": "No built-in implementation spec exists for this rule; add anchors before treating it as implemented.",
        },
    )


def _source_term_evidence(source_text: str, term: str, *, kind: str) -> dict:
    if not source_text:
        return {"term": term, "kind": kind, "found": False, "line": None, "snippet": ""}
    index = source_text.find(term)
    if index < 0:
        return {"term": term, "kind": kind, "found": False, "line": None, "snippet": ""}
    line = source_text.count("\n", 0, index) + 1
    lines = source_text.splitlines()
    snippet = lines[line - 1].strip() if 0 <= line - 1 < len(lines) else ""
    return {"term": term, "kind": kind, "found": True, "line": line, "snippet": snippet}


def write_benchmark_repair_implementation_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_repair_implementation_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_repair_implementation_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Benchmark Repair Implementation Verification",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Source: `{payload.get('source_path', '')}`",
        f"- Validated rules implemented: `{int(summary.get('implemented_validated_rule_count', 0))}/"
        f"{int(summary.get('validated_rule_count', 0))}`",
        f"- Anchors found: `{int(summary.get('found_anchor_count', 0))}/{int(summary.get('anchor_count', 0))}`",
        f"- Reasons found: `{int(summary.get('found_reason_count', 0))}/{int(summary.get('reason_count', 0))}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Rule Implementation Map",
        "",
        "| Rule | Synthesis | Implementation | Anchors | Reasons | Patch Hint |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for item in payload.get("rules", []):
        anchors = list(item.get("anchors", []))
        reasons = list(item.get("reasons", []))
        lines.append(
            f"| `{item.get('id', '')}` | `{item.get('synthesis_status', '')}` | `{item.get('implementation_status', '')}` | "
            f"{sum(1 for anchor in anchors if anchor.get('found'))}/{len(anchors)} | "
            f"{sum(1 for reason in reasons if reason.get('found'))}/{len(reasons)} | "
            f"{_markdown_cell(item.get('patch_hint', ''))} |"
        )
    lines.extend(["", "## Source Evidence", "", "| Rule | Kind | Term | Found | Line | Snippet |", "| --- | --- | --- | --- | ---: | --- |"])
    for item in payload.get("rules", []):
        for evidence in list(item.get("anchors", [])) + list(item.get("reasons", [])):
            found = "yes" if evidence.get("found") else "no"
            line = evidence.get("line") if evidence.get("line") is not None else ""
            lines.append(
                f"| `{item.get('id', '')}` | `{evidence.get('kind', '')}` | `{_markdown_cell(evidence.get('term', ''))}` | "
                f"`{found}` | {line} | `{_markdown_cell(evidence.get('snippet', ''))}` |"
            )
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def compile_benchmark_repair_interventions(
    synthesis_path: Path,
    *,
    implementation_path: Path | None = None,
    source_path: Path,
) -> dict:
    synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
    implementation = (
        json.loads(implementation_path.read_text(encoding="utf-8"))
        if implementation_path is not None and implementation_path.is_file()
        else verify_benchmark_repair_implementation(synthesis_path, source_path=source_path)
    )
    implementation_by_id = {str(rule.get("id", "")): rule for rule in implementation.get("rules", [])}
    interventions = [
        _compile_repair_rule_intervention(
            rule,
            implementation_by_id.get(str(rule.get("id", "")), {}),
            source_path=source_path,
        )
        for rule in synthesis.get("rules", [])
    ]
    patch_required = [item for item in interventions if item["action"] == "apply_patch"]
    regression_locks = [item for item in interventions if item["action"] == "lock_regression"]
    ablation_toggles = [toggle for item in interventions for toggle in item.get("ablation_toggles", [])]
    validation_commands = sorted({command for item in interventions for command in item.get("validation_commands", [])})
    if not source_path.is_file():
        status = "needs_source"
    elif patch_required:
        status = "patch_plan_ready"
    elif regression_locks:
        status = "compiled_noop_verified"
    else:
        status = "no_actionable_rules"
    score = int(
        round(
            100
            * _mean(
                1.0 if source_path.is_file() else 0.0,
                len(regression_locks) / max(1, sum(1 for rule in synthesis.get("rules", []) if rule.get("status") == "validated")),
                1.0 if validation_commands else 0.0,
                1.0 if ablation_toggles else 0.0,
            )
        )
    )
    return {
        "schema_version": "1.0",
        "strategy": "benchmark_repair_rule_compiler",
        "synthesis_path": str(synthesis_path),
        "source_synthesis_sha256": _sha256_file(synthesis_path) if synthesis_path.is_file() else "",
        "implementation_path": str(implementation_path) if implementation_path is not None else "",
        "source_implementation_sha256": _sha256_file(implementation_path) if implementation_path is not None and implementation_path.is_file() else "",
        "source_path": str(source_path),
        "source_sha256": _sha256_file(source_path) if source_path.is_file() else "",
        "suite_id": synthesis.get("suite_id", ""),
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "summary": {
            "rule_count": len(interventions),
            "patch_required_count": len(patch_required),
            "regression_lock_count": len(regression_locks),
            "ablation_toggle_count": len(ablation_toggles),
            "validation_command_count": len(validation_commands),
            "source_available": source_path.is_file(),
            "implemented_anchor_count": sum(item.get("implemented_anchor_count", 0) for item in interventions),
            "reason_literal_count": sum(len(item.get("reason_literals", [])) for item in interventions),
        },
        "interventions": interventions,
        "validation_commands": validation_commands,
        "review_protocol": [
            {
                "step": "inspect_compiled_ir",
                "detail": "Confirm every non-dormant rule has a deterministic action, source target, reason literal, and validation command.",
            },
            {
                "step": "apply_one_rule_family",
                "detail": "Apply only one patch-required rule family at a time, then rerun benchmark adapter, synthesis, implementation verification, and compiler.",
            },
            {
                "step": "run_ablation_toggle",
                "detail": "Use the toggle plan to remove one reason/anchor family and confirm the benchmark or claim card observes the expected regression.",
            },
        ],
        "evidence_hash": _stable_short_hash(
            {
                "suite": synthesis.get("suite_id", ""),
                "status": status,
                "interventions": [
                    (
                        item["rule_id"],
                        item["action"],
                        item["implementation_status"],
                        item["patch_required"],
                        item["implemented_anchor_count"],
                    )
                    for item in interventions
                ],
            }
        ),
    }


def _compile_repair_rule_intervention(rule: dict, implementation_rule: dict, *, source_path: Path) -> dict:
    rule_id = str(rule.get("id", ""))
    synthesis_status = str(rule.get("status", "unknown"))
    implementation_status = str(implementation_rule.get("implementation_status", "unknown"))
    patch_spec = _repair_rule_patch_spec(rule_id)
    anchors = list(implementation_rule.get("anchors", []))
    reasons = list(implementation_rule.get("reasons", []))
    found_anchors = [anchor for anchor in anchors if anchor.get("found")]
    found_reasons = [reason for reason in reasons if reason.get("found")]
    if synthesis_status == "validated" and implementation_status == "implemented":
        action = "lock_regression"
    elif synthesis_status in {"validated", "proposed"}:
        action = "apply_patch"
    else:
        action = "observe"
    patch_required = action == "apply_patch"
    reason_literals = [str(reason.get("term", "")) for reason in reasons if reason.get("term")]
    if not reason_literals:
        reason_literals = list(patch_spec["reason_literals"])
    validation_commands = [
        "python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json --json",
        "python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.json --json",
        "python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.json --json",
        "python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.json --json",
    ]
    return {
        "rule_id": rule_id,
        "family": rule.get("family", ""),
        "synthesis_status": synthesis_status,
        "implementation_status": implementation_status,
        "action": action,
        "patch_required": patch_required,
        "source_path": str(source_path),
        "target_functions": patch_spec["target_functions"],
        "insertion_points": patch_spec["insertion_points"],
        "guard_conditions": patch_spec["guard_conditions"],
        "score_effects": patch_spec["score_effects"],
        "reason_literals": reason_literals,
        "implemented_anchor_count": len(found_anchors),
        "implemented_reason_count": len(found_reasons),
        "case_links": {
            "affected_case_ids": list(rule.get("affected_case_ids", [])),
            "validated_case_ids": list(rule.get("validated_case_ids", [])),
            "risk_case_ids": list(rule.get("risk_case_ids", [])),
        },
        "patch_plan": _repair_rule_patch_plan(rule_id, patch_spec, action=action),
        "ablation_toggles": _repair_rule_ablation_toggles(rule_id, patch_spec, reason_literals, action=action),
        "validation_commands": validation_commands if action in {"apply_patch", "lock_regression"} else validation_commands[:2],
        "rollback_condition": patch_spec["rollback_condition"],
        "evidence_hash": _stable_short_hash(
            {
                "rule": rule_id,
                "synthesis": synthesis_status,
                "implementation": implementation_status,
                "action": action,
                "anchors": [(item.get("term"), item.get("line")) for item in found_anchors],
                "reasons": [(item.get("term"), item.get("line")) for item in found_reasons],
            }
        ),
    }


def _repair_rule_patch_spec(rule_id: str) -> dict:
    specs = {
        "promote_streaming_handler_intent": {
            "target_functions": ["_asks_for_streaming", "_chunk_matches_streaming_intent", "_rerank_multistep"],
            "insertion_points": ["stream query predicate", "candidate streaming matcher", "handler rerank boost"],
            "guard_conditions": ["query contains stream/sse/delta intent", "candidate symbol/body/calls contain stream evidence"],
            "score_effects": ["boost matching handler", "emit streaming handler disambiguation reason"],
            "reason_literals": ["streaming handler disambiguation"],
            "rollback_condition": "Any non-streaming query loses Top-1 or a streaming decoy becomes rank-1.",
        },
        "prefer_retrieval_library_boundary": {
            "target_functions": ["_asks_for_retrieval_boundary", "_chunk_is_library_boundary", "_rerank_multistep"],
            "insertion_points": ["retrieval/read-first predicate", "library boundary classifier", "entry-handler detour demotion"],
            "guard_conditions": ["query asks for retrieve/search/rag plus read-first or flow intent", "candidate is a library/helper boundary"],
            "score_effects": ["boost retrieval helper", "boost library boundary", "demote generic entry handler detours"],
            "reason_literals": ["retrieval helper target", "library boundary prior", "entry handler boundary detour"],
            "rollback_condition": "Upload/route entrypoint questions start preferring helper libraries over the explicit endpoint.",
        },
        "route_anchor_backfill": {
            "target_functions": ["_query_route_literals", "_route_reachable_chunk_ids", "_rerank_multistep"],
            "insertion_points": ["route literal extraction", "route-reachable graph expansion", "route path rerank boost"],
            "guard_conditions": ["query names a route or endpoint literal", "candidate is route-reachable from the literal"],
            "score_effects": ["boost route-reachable candidate", "demote off-route response writer decoys"],
            "reason_literals": ["exact route path evidence"],
            "rollback_condition": "A same-file off-route writer outranks the endpoint-reachable handler.",
        },
        "demote_rank1_hard_negative": {
            "target_functions": ["_rerank_multistep", "_chunk_writes_response"],
            "insertion_points": ["distractor label matcher", "writer-family conflict check", "rerank demotion"],
            "guard_conditions": ["candidate matches labeled distractor", "expected candidate remains inside Top-k"],
            "score_effects": ["demote labeled hard negative", "emit explicit rejection reason"],
            "reason_literals": ["off-route writer decoy", "explicitly excluded by query"],
            "rollback_condition": "A labeled distractor can still become rank-1 after the patch.",
        },
        "symbol_free_semantic_bridge": {
            "target_functions": ["_semantic_scores", "_build_semantic_features", "_rerank_multistep"],
            "insertion_points": ["expected-context term miner", "latent semantic bridge", "symbol-free intent boost"],
            "guard_conditions": ["expected symbol is absent from natural language query", "semantic context links behavior to symbol"],
            "score_effects": ["boost behavior-matching implementation chunk", "emit semantic bridge reason"],
            "reason_literals": ["semantic symbol bridge", "hidden symbol query"],
            "rollback_condition": "Symbol-free behavioral questions regress while symbol-named questions remain unchanged.",
        },
    }
    return specs.get(
        rule_id,
        {
            "target_functions": ["_rerank_multistep"],
            "insertion_points": ["custom rule hook"],
            "guard_conditions": ["custom rule predicate"],
            "score_effects": ["custom score adjustment"],
            "reason_literals": [f"{rule_id} applied"],
            "rollback_condition": "The custom rule changes unrelated benchmark cases.",
        },
    )


def _repair_rule_patch_plan(rule_id: str, patch_spec: dict, *, action: str) -> list[dict]:
    if action == "lock_regression":
        verb = "lock"
        detail = "Keep the existing implementation anchors and reason literals under regression tests."
    elif action == "apply_patch":
        verb = "patch"
        detail = "Apply the compiled intervention at the named reranker insertion points."
    else:
        verb = "observe"
        detail = "Track this dormant rule until a benchmark counterexample activates it."
    return [
        {
            "op": verb,
            "target": target,
            "detail": detail,
            "guard": "; ".join(patch_spec["guard_conditions"]),
            "score_effect": "; ".join(patch_spec["score_effects"]),
            "reason": ", ".join(patch_spec["reason_literals"]),
        }
        for target in patch_spec["target_functions"]
    ]


def _repair_rule_ablation_toggles(rule_id: str, patch_spec: dict, reason_literals: list[str], *, action: str) -> list[dict]:
    if action == "observe":
        return []
    toggles = []
    for reason in reason_literals or patch_spec["reason_literals"]:
        toggles.append(
            {
                "id": f"ablate_{rule_id}_{_slugify(reason)}",
                "rule_id": rule_id,
                "disable_reason_literal": reason,
                "expected_effect": "Top-1 should not improve; any regression localizes this rule's benchmark contribution.",
                "validation": "Rerun benchmark-adapter, repair synthesis, implementation verification, and artifact review.",
            }
        )
    return toggles


def write_benchmark_repair_compiler_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_repair_compiler_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_repair_compiler_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Benchmark Repair Compiler",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Source: `{payload.get('source_path', '')}`",
        f"- Patch-required rules: `{int(summary.get('patch_required_count', 0))}`",
        f"- Regression locks: `{int(summary.get('regression_lock_count', 0))}`",
        f"- Ablation toggles: `{int(summary.get('ablation_toggle_count', 0))}`",
        f"- Validation commands: `{int(summary.get('validation_command_count', 0))}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Intervention IR",
        "",
        "| Rule | Synthesis | Implementation | Action | Targets | Reasons | Cases | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("interventions", []):
        cases = dict(item.get("case_links") or {})
        case_count = len(cases.get("affected_case_ids", [])) + len(cases.get("validated_case_ids", []))
        lines.append(
            f"| `{item.get('rule_id', '')}` | `{item.get('synthesis_status', '')}` | "
            f"`{item.get('implementation_status', '')}` | `{item.get('action', '')}` | "
            f"{_markdown_cell(', '.join(item.get('target_functions', [])))} | "
            f"{_markdown_cell(', '.join(item.get('reason_literals', [])))} | {case_count} | "
            f"`{item.get('evidence_hash', '')}` |"
        )
    lines.extend(["", "## Patch Plan", "", "| Rule | Op | Target | Guard | Score Effect | Reason |", "| --- | --- | --- | --- | --- | --- |"])
    for item in payload.get("interventions", []):
        for op in item.get("patch_plan", []):
            lines.append(
                f"| `{item.get('rule_id', '')}` | `{op.get('op', '')}` | `{op.get('target', '')}` | "
                f"{_markdown_cell(op.get('guard', ''))} | {_markdown_cell(op.get('score_effect', ''))} | "
                f"{_markdown_cell(op.get('reason', ''))} |"
            )
    lines.extend(["", "## Ablation Toggles", "", "| Toggle | Rule | Disabled Reason | Expected Effect |", "| --- | --- | --- | --- |"])
    for item in payload.get("interventions", []):
        for toggle in item.get("ablation_toggles", []):
            lines.append(
                f"| `{toggle.get('id', '')}` | `{toggle.get('rule_id', '')}` | "
                f"`{_markdown_cell(toggle.get('disable_reason_literal', ''))}` | "
                f"{_markdown_cell(toggle.get('expected_effect', ''))} |"
            )
    lines.extend(["", "## Validation Commands", ""])
    for command in payload.get("validation_commands", []):
        lines.append(f"- `{command}`")
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def build_benchmark_repair_workbench(compiler_path: Path, *, source_path: Path) -> dict:
    compiler = json.loads(compiler_path.read_text(encoding="utf-8"))
    source_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
    interventions = list(compiler.get("interventions", []))
    patch_candidates = []
    experiments = []
    for intervention in interventions:
        patch_candidates.extend(_repair_workbench_patch_candidates(intervention, source_path=source_path, source_text=source_text))
        experiments.extend(_repair_workbench_experiments(intervention))
    executable_patches = [item for item in patch_candidates if item.get("patch_applicability") == "review_apply"]
    counterfactual_patches = [item for item in patch_candidates if item.get("candidate_type") == "ablation_counterfactual"]
    regression_locks = [item for item in interventions if item.get("action") == "lock_regression"]
    patch_required = [item for item in interventions if item.get("action") == "apply_patch"]
    status = "patch_workbench_ready" if patch_candidates and source_path.is_file() else "needs_source"
    score = int(
        round(
            100
            * _mean(
                1.0 if source_path.is_file() else 0.0,
                1.0 if patch_candidates else 0.0,
                1.0 if experiments else 0.0,
                len(counterfactual_patches) / max(1, int((compiler.get("summary") or {}).get("ablation_toggle_count", 0))),
            )
        )
    )
    return {
        "schema_version": "1.0",
        "strategy": "benchmark_repair_patch_workbench",
        "compiler_path": str(compiler_path),
        "source_compiler_sha256": _sha256_file(compiler_path) if compiler_path.is_file() else "",
        "source_path": str(source_path),
        "source_sha256": _sha256_file(source_path) if source_path.is_file() else "",
        "suite_id": compiler.get("suite_id", ""),
        "status": status,
        "score": score,
        "grade": _temporal_repair_grade(score),
        "summary": {
            "intervention_count": len(interventions),
            "patch_candidate_count": len(patch_candidates),
            "review_apply_patch_count": len(executable_patches),
            "counterfactual_patch_count": len(counterfactual_patches),
            "experiment_count": len(experiments),
            "regression_lock_count": len(regression_locks),
            "patch_required_count": len(patch_required),
            "source_available": source_path.is_file(),
        },
        "patch_candidates": patch_candidates,
        "experiments": experiments,
        "review_protocol": [
            {
                "step": "review_patch_candidates",
                "detail": "Inspect generated diff candidates before applying them; counterfactual patches are for ablation experiments only.",
            },
            {
                "step": "run_one_ablation_at_a_time",
                "detail": "Apply at most one ablation patch, rerun the benchmark adapter and artifact review, then revert the patch.",
            },
            {
                "step": "promote_patch_after_evidence",
                "detail": "A patch-required candidate can be promoted only after synthesis, implementation verification, compiler, workbench, and release gate all pass.",
            },
        ],
        "validation_matrix": _repair_workbench_validation_matrix(),
        "evidence_hash": _stable_short_hash(
            {
                "compiler": compiler.get("evidence_hash", ""),
                "status": status,
                "patches": [
                    (
                        item.get("id"),
                        item.get("candidate_type"),
                        item.get("rule_id"),
                        item.get("patch_applicability"),
                        item.get("source_line"),
                    )
                    for item in patch_candidates
                ],
                "experiments": [(item.get("id"), item.get("rule_id")) for item in experiments],
            }
        ),
    }


def _repair_workbench_patch_candidates(intervention: dict, *, source_path: Path, source_text: str) -> list[dict]:
    rule_id = str(intervention.get("rule_id", ""))
    candidates = []
    if intervention.get("action") == "apply_patch":
        candidates.append(_repair_workbench_apply_patch_candidate(intervention, source_path=source_path, source_text=source_text))
    for toggle in intervention.get("ablation_toggles", []):
        reason = str(toggle.get("disable_reason_literal", ""))
        candidates.append(
            _repair_workbench_ablation_patch_candidate(
                intervention,
                toggle,
                source_path=source_path,
                source_text=source_text,
                reason=reason,
            )
        )
    if intervention.get("action") == "lock_regression" and not intervention.get("ablation_toggles"):
        candidates.append(
            {
                "id": f"lock_{rule_id}",
                "rule_id": rule_id,
                "candidate_type": "regression_lock",
                "patch_applicability": "no_source_change",
                "source_path": str(source_path),
                "source_line": None,
                "summary": "Existing implementation is locked by benchmark, implementation verification, and compiler checks.",
                "diff": "",
                "validation_commands": list(intervention.get("validation_commands", [])),
                "rollback": intervention.get("rollback_condition", ""),
                "evidence_hash": _stable_short_hash({"rule": rule_id, "type": "regression_lock"}),
            }
        )
    return candidates


def _repair_workbench_apply_patch_candidate(intervention: dict, *, source_path: Path, source_text: str) -> dict:
    rule_id = str(intervention.get("rule_id", ""))
    target = next(iter(intervention.get("target_functions", []) or ["_rerank_multistep"]), "_rerank_multistep")
    locus = _source_term_evidence(source_text, f"def {target}", kind="patch_locus")
    line = locus.get("line")
    reason = ", ".join(intervention.get("reason_literals", []))
    guard = "; ".join(intervention.get("guard_conditions", []))
    score_effect = "; ".join(intervention.get("score_effects", []))
    old_line = _source_raw_line(source_text, line) if locus.get("found") else f"# target function {target} not found"
    diff = _review_only_patch_hunk(
        source_path,
        line,
        old_line=old_line,
        new_line=f"{_line_indent(old_line)}# REVIEW PATCH {rule_id}: guard=({guard}); effect=({score_effect}); reason=({reason})",
    )
    return {
        "id": f"candidate_{rule_id}",
        "rule_id": rule_id,
        "candidate_type": "patch_required",
        "patch_applicability": "review_skeleton",
        "source_path": str(source_path),
        "source_line": line,
        "summary": "Patch-required rule compiled into a review skeleton near the target function.",
        "diff": diff,
        "validation_commands": list(intervention.get("validation_commands", [])),
        "rollback": intervention.get("rollback_condition", ""),
        "evidence_hash": _stable_short_hash({"rule": rule_id, "type": "patch_required", "line": line, "reason": reason}),
    }


def _repair_workbench_ablation_patch_candidate(
    intervention: dict,
    toggle: dict,
    *,
    source_path: Path,
    source_text: str,
    reason: str,
) -> dict:
    rule_id = str(intervention.get("rule_id", ""))
    locus = _source_term_evidence(source_text, reason, kind="ablation_locus")
    old_line = _source_raw_line(source_text, locus.get("line")) if locus.get("found") else f"# reason literal not found: {reason}"
    new_line = old_line.replace(reason, f"ABLATION_DISABLED_{_slugify(reason)}") if locus.get("found") else old_line
    diff = _review_only_patch_hunk(source_path, locus.get("line"), old_line=old_line, new_line=new_line)
    return {
        "id": str(toggle.get("id") or f"ablate_{rule_id}_{_slugify(reason)}"),
        "rule_id": rule_id,
        "candidate_type": "ablation_counterfactual",
        "patch_applicability": "review_apply" if locus.get("found") else "missing_locus",
        "source_path": str(source_path),
        "source_line": locus.get("line"),
        "summary": f"Disable `{reason}` to test whether the benchmark or artifact claim observes this rule's contribution.",
        "diff": diff,
        "validation_commands": list(intervention.get("validation_commands", [])),
        "rollback": "Revert the one-line ablation patch immediately after collecting benchmark evidence.",
        "expected_effect": toggle.get("expected_effect", ""),
        "evidence_hash": _stable_short_hash({"rule": rule_id, "type": "ablation", "reason": reason, "line": locus.get("line")}),
    }


def _repair_workbench_experiments(intervention: dict) -> list[dict]:
    experiments = []
    rule_id = str(intervention.get("rule_id", ""))
    for toggle in intervention.get("ablation_toggles", []):
        experiments.append(
            {
                "id": f"experiment_{toggle.get('id', '')}",
                "rule_id": rule_id,
                "type": "single_rule_ablation",
                "disabled_reason": toggle.get("disable_reason_literal", ""),
                "hypothesis": toggle.get("expected_effect", ""),
                "success_criteria": [
                    "benchmark adapter still runs to completion",
                    "repair synthesis and implementation verification report the changed evidence path",
                    "artifact review either remains supported or explains the weakened claim",
                ],
                "commands": [
                    "python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json --json",
                    "python -m repo_agent benchmark-repair-synthesize --benchmark reports/benchmark-adapter.json --output reports/benchmark-repair-synthesis.json --json",
                    "python -m repo_agent benchmark-repair-verify-implementation --synthesis reports/benchmark-repair-synthesis.json --output reports/benchmark-repair-implementation.json --json",
                    "python -m repo_agent benchmark-repair-compile --synthesis reports/benchmark-repair-synthesis.json --implementation reports/benchmark-repair-implementation.json --output reports/benchmark-repair-compiler.json --json",
                    "python -m repo_agent benchmark-repair-workbench --compiler reports/benchmark-repair-compiler.json --output reports/benchmark-repair-workbench.json --json",
                ],
            }
        )
    return experiments


def _repair_workbench_validation_matrix() -> list[dict]:
    return [
        {
            "stage": "candidate_generation",
            "command": "python -m repo_agent benchmark-repair-workbench --compiler reports/benchmark-repair-compiler.json --output reports/benchmark-repair-workbench.md",
            "passes_if": "patch candidates and experiments are generated with source loci or explicit missing-locus status",
        },
        {
            "stage": "ablation_replay",
            "command": "python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json --json",
            "passes_if": "the ablated run completes and records any Top-1, reason, or claim-card delta",
        },
        {
            "stage": "release_gate",
            "command": "powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\release_gate.ps1",
            "passes_if": "no candidate patch is promoted unless the full gate passes",
        },
    ]


def _review_only_patch_hunk(source_path: Path, line: object, *, old_line: str, new_line: str) -> str:
    line_number = int(line) if isinstance(line, int) else 1
    return "\n".join(
        [
            f"--- a/{source_path.as_posix()}",
            f"+++ b/{source_path.as_posix()}",
            f"@@ -{line_number},1 +{line_number},1 @@",
            f"-{old_line}",
            f"+{new_line}",
        ]
    )


def _source_raw_line(source_text: str, line: object) -> str:
    if not isinstance(line, int):
        return ""
    lines = source_text.splitlines()
    return lines[line - 1] if 0 <= line - 1 < len(lines) else ""


def _line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def write_benchmark_repair_workbench_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_benchmark_repair_workbench_markdown(payload), encoding="utf-8")
    return output_path


def render_benchmark_repair_workbench_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Benchmark Repair Workbench",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Suite: `{payload.get('suite_id', '')}`",
        f"- Source: `{payload.get('source_path', '')}`",
        f"- Patch candidates: `{int(summary.get('patch_candidate_count', 0))}`",
        f"- Review-applicable patches: `{int(summary.get('review_apply_patch_count', 0))}`",
        f"- Counterfactual patches: `{int(summary.get('counterfactual_patch_count', 0))}`",
        f"- Experiments: `{int(summary.get('experiment_count', 0))}`",
        f"- Evidence hash: `{payload.get('evidence_hash', '')}`",
        "",
        "## Patch Candidates",
        "",
        "| Candidate | Rule | Type | Applicability | Line | Summary | Evidence |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for item in payload.get("patch_candidates", []):
        line = item.get("source_line") if item.get("source_line") is not None else ""
        lines.append(
            f"| `{item.get('id', '')}` | `{item.get('rule_id', '')}` | `{item.get('candidate_type', '')}` | "
            f"`{item.get('patch_applicability', '')}` | {line} | {_markdown_cell(item.get('summary', ''))} | "
            f"`{item.get('evidence_hash', '')}` |"
        )
    lines.extend(["", "## Experiments", "", "| Experiment | Rule | Disabled Reason | Hypothesis |", "| --- | --- | --- | --- |"])
    for item in payload.get("experiments", []):
        lines.append(
            f"| `{item.get('id', '')}` | `{item.get('rule_id', '')}` | "
            f"`{_markdown_cell(item.get('disabled_reason', ''))}` | {_markdown_cell(item.get('hypothesis', ''))} |"
        )
    lines.extend(["", "## Validation Matrix", "", "| Stage | Command | Passes If |", "| --- | --- | --- |"])
    for item in payload.get("validation_matrix", []):
        lines.append(f"| `{item.get('stage', '')}` | `{item.get('command', '')}` | {item.get('passes_if', '')} |")
    lines.extend(["", "## Review Protocol", "", "| Step | Detail |", "| --- | --- |"])
    for item in payload.get("review_protocol", []):
        lines.append(f"| `{item.get('step', '')}` | {item.get('detail', '')} |")
    lines.extend(["", "## Candidate Diffs", ""])
    for item in payload.get("patch_candidates", []):
        diff = str(item.get("diff", ""))
        if not diff:
            continue
        lines.extend([f"### `{item.get('id', '')}`", "", "```diff", diff, "```", ""])
    return "\n".join(lines)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "rule"


def render_eval_markdown(payload: dict) -> str:
    metrics = payload["metrics"]
    lines = [
        "# Repo Agent Evaluation Report",
        "",
        "## Summary",
        "",
        f"- Cases: {metrics['case_count']}",
        f"- Top-k: {metrics['top_k']}",
        f"- Top-1 accuracy: {metrics['top1_accuracy']:.2%}",
        f"- Top-3 accuracy: {metrics['top3_accuracy']:.2%}",
        f"- MRR: {metrics['mrr']:.3f}",
        f"- Average confidence: {metrics['average_confidence']:.2f}",
        "",
        "## Cases",
        "",
        "| Result | Rank | Confidence | Expected | Top hit | Question |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for record in payload["cases"]:
        result = "PASS" if record["passed_top3"] else "FAIL"
        rank = str(record["rank"]) if record["rank"] is not None else "miss"
        confidence = f"{record['confidence_label']} {record['confidence']:.2f}"
        expected = _markdown_cell(record["expected_path"])
        top_hit = _markdown_cell(record["top_hit"] or "<none>")
        question = _markdown_cell(record["question"])
        lines.append(f"| {result} | {rank} | {confidence} | `{expected}` | `{top_hit}` | {question} |")
    lines.append("")
    return "\n".join(lines)


def run_ablation(
    runtime: RepoAgentRuntime,
    cases_path: Path,
    top_k: int = 6,
    json_output: bool = False,
    output_path: Path | None = None,
) -> None:
    payload = evaluate_ablation(runtime, cases_path, top_k=top_k)
    if output_path is not None:
        written = write_ablation_output(payload, output_path)
        payload["output_path"] = str(written)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("Retrieval ablation")
    for variant, metrics in payload["metrics"].items():
        print(
            f"- {variant}: Top-1 {metrics['top1_accuracy']:.2%}, "
            f"Top-3 {metrics['top3_accuracy']:.2%}, MRR {metrics['mrr']:.3f}"
        )
    if output_path is not None:
        print(f"Report: {payload['output_path']}")


def evaluate_ablation(runtime: RepoAgentRuntime, cases_path: Path, top_k: int = 6) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    records = []
    metric_buckets = {
        variant: {"top1": 0, "top3": 0, "rr": 0.0}
        for variant in ABLATION_VARIANTS
    }
    for case in cases:
        repo_path = (cases_path.parent / case["repo"]).resolve()
        repo_index = runtime.load_index(repo_path, force_rebuild=True)
        variants: dict[str, dict] = {}
        for variant in ABLATION_VARIANTS:
            hits = _ablation_hits(repo_index, str(case["question"]), variant=variant, top_k=top_k)
            rank = _case_match_rank(case, hits)
            variants[variant] = {
                "rank": rank,
                "top_hit": hits[0].chunk.source_label if hits else "",
                "top_hits": [hit.chunk.source_label for hit in hits[:top_k]],
                "passed_top1": rank == 1,
                "passed_top3": rank is not None and rank <= 3,
            }
            metric_buckets[variant]["top1"] += 1 if rank == 1 else 0
            metric_buckets[variant]["top3"] += 1 if rank is not None and rank <= 3 else 0
            metric_buckets[variant]["rr"] += (1 / rank) if rank else 0.0
        records.append(
            {
                "question": case["question"],
                "repo": str(repo_path),
                "expected_path": case["expected_path"],
                "expected_symbol_contains": case.get("expected_symbol_contains", ""),
                "variants": variants,
            }
        )

    total = max(len(records), 1)
    metrics = {
        variant: {
            "case_count": len(records),
            "top_k": top_k,
            "top1_accuracy": bucket["top1"] / total,
            "top3_accuracy": bucket["top3"] / total,
            "mrr": bucket["rr"] / total,
        }
        for variant, bucket in metric_buckets.items()
    }
    return {"variants": list(ABLATION_VARIANTS), "metrics": metrics, "cases": records}


def _ablation_hits(repo_index, question: str, *, variant: str, top_k: int) -> list[RetrievalHit]:
    if variant == "lexical":
        return repo_index._score_all_chunks(question, {})[:top_k]
    if variant == "semantic":
        semantic_scores = repo_index.semantic_scores_for(question)
        hits = [
            RetrievalHit(
                chunk=repo_index.chunk_by_id[chunk_id],
                score=score,
                matched_terms=["semantic_projection"],
                reasons=["semantic-only score"],
            )
            for chunk_id, score in semantic_scores.items()
            if chunk_id in repo_index.chunk_by_id
        ]
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]
    if variant == "graph_mcts":
        hits, _diagnostics = repo_index.mcts_graph_search(question, top_k=top_k)
        return hits
    plan = repo_index.plan_query(question)
    semantic_scores = repo_index.semantic_scores_for(question)
    file_hits = repo_index.scout_files(plan, limit=max(6, top_k + 2))
    seed_hits, file_boosts = repo_index.read_candidates(
        question,
        plan,
        file_hits,
        semantic_scores,
        top_k=top_k,
    )
    if variant == "no_graph":
        relation_boosts = {}
    elif variant == "hybrid":
        relation_boosts, _hop_trace = repo_index.follow_neighbors(seed_hits[: max(2, min(4, top_k))], plan)
    else:
        raise ValueError(f"unknown ablation variant: {variant}")
    return repo_index.rerank_candidates(
        question,
        plan,
        seed_hits,
        file_boosts,
        relation_boosts,
        semantic_scores,
        top_k=top_k,
    )


def write_ablation_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".md":
        output_path.write_text(render_ablation_markdown(payload), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def render_ablation_markdown(payload: dict) -> str:
    lines = [
        "# Repo Agent Retrieval Ablation Report",
        "",
        "## Strategy Summary",
        "",
        "| Strategy | Top-1 | Top-3 | MRR |",
        "| --- | ---: | ---: | ---: |",
    ]
    for variant in payload["variants"]:
        metrics = payload["metrics"][variant]
        lines.append(
            f"| {variant} | {metrics['top1_accuracy']:.2%} | "
            f"{metrics['top3_accuracy']:.2%} | {metrics['mrr']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Case Matrix",
            "",
            "| " + " | ".join(["Question", "Expected", *payload["variants"]]) + " |",
            "| " + " | ".join(["---", "---", *(["---"] * len(payload["variants"]))]) + " |",
        ]
    )
    for record in payload["cases"]:
        cells = []
        for variant in payload["variants"]:
            item = record["variants"][variant]
            rank = item["rank"] if item["rank"] is not None else "miss"
            cells.append(f"rank {rank}: `{_markdown_cell(item['top_hit'] or '<none>')}`")
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(record["question"]),
                    f"`{_markdown_cell(record['expected_path'])}`",
                    *cells,
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def run_proof_attack_benchmark(runtime: RepoAgentRuntime, *, output_dir: Path, top_k: int = 6, spec_path: Path | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_repo = runtime.project_root / "examples" / "counterfactual_agent_app"
    work_root = _proof_attack_work_root(runtime, output_dir)
    if work_root.exists():
        _remove_tree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    spec_payload = _load_proof_attack_spec(spec_path)
    attack_cases = list(spec_payload.get("cases") or [])

    records = []
    for case in attack_cases:
        repo_dir = work_root / case["id"] / "repo"
        if repo_dir.exists():
            _remove_tree(repo_dir)
        shutil.copytree(source_repo, repo_dir)
        _apply_proof_attack_mutation(repo_dir, case["mutation"])
        repo_index = runtime.load_index(repo_dir, force_rebuild=True)
        variants = _evaluate_attack_variants(repo_index, list(case.get("distractors") or []), top_k=top_k)
        proof_record = _evaluate_attack_proof(repo_index, list(case.get("distractors") or []), top_k=top_k)
        defense_audit = _evaluate_attack_defense_audit(repo_index, list(case.get("distractors") or []), top_k=top_k)
        graph_record = variants["graph_mcts"]
        passed = (
            graph_record["rank"] == 1
            and graph_record["distractor_rank"] != 1
            and proof_record["proof_status"] == "proved"
            and proof_record["top_hit"] == PROOF_ATTACK_EXPECTED_LABEL
            and proof_record["route_anchor_preserved"]
            and proof_record["supporting_path_preserved"]
        )
        records.append(
            {
                "id": case["id"],
                "description": case["description"],
                "threat_model": case.get("threat_model", ""),
                "severity": case.get("severity", "medium"),
                "tags": list(case.get("tags") or []),
                "mutation": case.get("mutation", {}),
                "repo": str(repo_dir),
                "expected": PROOF_ATTACK_EXPECTED_LABEL,
                "distractors": list(case.get("distractors") or []),
                "passed": passed,
                "variants": variants,
                "proof": proof_record,
                "defense_audit": defense_audit,
            }
        )

    total = max(len(records), 1)
    graph_records = [item["variants"]["graph_mcts"] for item in records]
    proof_records = [item["proof"] for item in records]
    decoy_audits = [
        decoy
        for item in records
        for decoy in item.get("defense_audit", {}).get("decoys", [])
    ]
    decoy_total = max(len(decoy_audits), 1)
    metrics = {
        "case_count": len(records),
        "top_k": top_k,
        "graph_mcts_top1_accuracy": sum(1 for item in graph_records if item["rank"] == 1) / total,
        "graph_mcts_distractor_top1_rate": sum(1 for item in graph_records if item["distractor_rank"] == 1) / total,
        "proof_proved_rate": sum(1 for item in proof_records if item["proof_status"] == "proved") / total,
        "route_anchor_rate": sum(1 for item in proof_records if item["route_anchor_preserved"]) / total,
        "supporting_path_rate": sum(1 for item in proof_records if item["supporting_path_preserved"]) / total,
        "generated_decoy_audit_rate": sum(1 for item in proof_records if item["generated_decoy_audited"]) / total,
        "generated_decoy_count": len(decoy_audits),
        "mitigated_decoy_rate": sum(1 for item in decoy_audits if item.get("mitigated")) / decoy_total,
        "mitigation_signal_rate": sum(1 for item in decoy_audits if item.get("mitigation_signals")) / decoy_total,
        "route_family_conflict_rate": sum(1 for item in decoy_audits if "route-family conflict" in item.get("mitigation_signals", [])) / decoy_total,
        "off_route_writer_decoy_rate": sum(1 for item in decoy_audits if "off-route writer decoy" in item.get("mitigation_signals", [])) / decoy_total,
        "attack_resistance_rate": sum(1 for item in records if item["passed"]) / total,
    }
    return {
        "schema_version": "1.0",
        "strategy": "adversarial_proof_attack_benchmark",
        "question": PROOF_DEMO_QUESTION,
        "spec": {
            "path": str(spec_path) if spec_path else "",
            "suite": spec_payload.get("suite", "builtin"),
            "description": spec_payload.get("description", ""),
            "case_count": len(attack_cases),
        },
        "source_repo": str(source_repo),
        "output_dir": str(output_dir),
        "work_root": str(work_root),
        "expected": PROOF_ATTACK_EXPECTED_LABEL,
        "variants": list(ABLATION_VARIANTS),
        "metrics": metrics,
        "cases": records,
    }


def _proof_attack_work_root(runtime: RepoAgentRuntime, output_dir: Path) -> Path:
    workspace_key = _stable_short_hash({"output_dir": str(output_dir.resolve())})
    return runtime.project_root / "test-workspaces" / f"_proof-attack-benchmark-{workspace_key}"


def write_proof_attack_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".md":
        output_path.write_text(render_proof_attack_markdown(payload), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_proof_attack_leaderboard(benchmark_path: Path) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    rows = []
    for case in benchmark.get("cases", []):
        graph = dict((case.get("variants") or {}).get("graph_mcts") or {})
        proof = dict(case.get("proof") or {})
        decoys = list((case.get("defense_audit") or {}).get("decoys") or [])
        unmitigated = [item for item in decoys if not bool(item.get("mitigated"))]
        weak_signals = [item for item in decoys if bool(item.get("mitigated")) and not list(item.get("mitigation_signals") or [])]
        pressure = _proof_attack_pressure_score(case)
        defense = _proof_attack_defense_score(case)
        rows.append(
            {
                "case_id": case.get("id", ""),
                "description": case.get("description", ""),
                "threat_model": case.get("threat_model", ""),
                "severity": case.get("severity", "medium"),
                "tags": list(case.get("tags") or []),
                "passed": bool(case.get("passed")),
                "attack_pressure": pressure,
                "defense_score": defense,
                "residual_risk": max(0, pressure - defense),
                "graph_mcts_rank": graph.get("rank"),
                "graph_mcts_distractor_rank": graph.get("distractor_rank"),
                "proof_status": proof.get("proof_status", "unknown"),
                "generated_decoy_audited": bool(proof.get("generated_decoy_audited")),
                "decoy_count": len(decoys),
                "unmitigated_decoy_count": len(unmitigated),
                "weak_signal_decoy_count": len(weak_signals),
            }
        )
    rows.sort(key=lambda item: (int(item["residual_risk"]), int(item["attack_pressure"]), -int(item["defense_score"])), reverse=True)
    hardest = rows[0] if rows else {}
    return {
        "schema_version": "1.0",
        "strategy": "adversarial_proof_attack_leaderboard",
        "benchmark": str(benchmark_path),
        "suite": (benchmark.get("spec") or {}).get("suite", ""),
        "case_count": len(rows),
        "hardest_case": hardest.get("case_id", ""),
        "max_attack_pressure": hardest.get("attack_pressure", 0),
        "max_residual_risk": hardest.get("residual_risk", 0),
        "rows": rows,
    }


def render_proof_attack_leaderboard_markdown(payload: dict) -> str:
    lines = [
        "# Repo Agent Adversarial Proof Attack Leaderboard",
        "",
        f"- Suite: `{payload.get('suite', '')}`",
        f"- Benchmark: `{payload.get('benchmark', '')}`",
        f"- Cases: `{int(payload.get('case_count', 0))}`",
        f"- Hardest case: `{payload.get('hardest_case', '')}`",
        f"- Max attack pressure: `{int(payload.get('max_attack_pressure', 0))}/100`",
        f"- Max residual risk: `{int(payload.get('max_residual_risk', 0))}/100`",
        "",
        "| Rank | Case | Severity | Pressure | Defense | Residual Risk | Graph Decoy Rank | Weak Signals | Tags |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for rank, row in enumerate(payload.get("rows", []), start=1):
        distractor_rank = row.get("graph_mcts_distractor_rank")
        tags = ", ".join(f"`{_markdown_cell(str(item))}`" for item in row.get("tags", [])) or "`none`"
        lines.append(
            f"| {rank} | `{row.get('case_id', '')}` | `{row.get('severity', '')}` | "
            f"{int(row.get('attack_pressure', 0))} | {int(row.get('defense_score', 0))} | "
            f"{int(row.get('residual_risk', 0))} | {distractor_rank if distractor_rank is not None else 'none'} | "
            f"{int(row.get('weak_signal_decoy_count', 0))} | {tags} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_proof_attack_leaderboard_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_proof_attack_leaderboard_markdown(payload), encoding="utf-8")
    return output_path


def build_proof_attack_triage(benchmark_path: Path, *, leaderboard_path: Path | None = None) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    leaderboard = (
        json.loads(leaderboard_path.read_text(encoding="utf-8"))
        if leaderboard_path is not None
        else build_proof_attack_leaderboard(benchmark_path)
    )
    rows_by_case = {str(row.get("case_id", "")): row for row in leaderboard.get("rows", [])}
    actions = []
    for case in benchmark.get("cases", []):
        case_id = str(case.get("id", ""))
        row = dict(rows_by_case.get(case_id) or {})
        proof = dict(case.get("proof") or {})
        decoys = list((case.get("defense_audit") or {}).get("decoys") or [])
        if not bool(proof.get("generated_decoy_audited")):
            actions.append(
                _proof_attack_triage_action(
                    case,
                    "generated_decoy_audit_gap",
                    "P1",
                    "Expand proof decoy-audit candidate selection so generated distractors are preserved in the proof ledger.",
                    "Add the generated decoy labels to proof.decoy_audit coverage checks or increase audit diversity for same-route-family symbols.",
                    {"generated_decoys": proof.get("generated_decoys", []), "audited": proof.get("audited_generated_decoys", [])},
                )
            )
        if int(row.get("attack_pressure", 0)) >= 75:
            priority = "P0" if int(row.get("residual_risk", 0)) > 0 else "P1"
            actions.append(
                _proof_attack_triage_action(
                    case,
                    "high_pressure_attack",
                    priority,
                    "Keep this case as a release-blocking regression because it exerts high retrieval pressure.",
                    "Pin the attack spec in the release pack and require proof-attack-scorecard plus leaderboard review before changing rerank logic.",
                    {
                        "attack_pressure": row.get("attack_pressure", 0),
                        "defense_score": row.get("defense_score", 0),
                        "residual_risk": row.get("residual_risk", 0),
                    },
                )
            )
        for decoy in decoys:
            signals = list(decoy.get("mitigation_signals") or [])
            if not bool(decoy.get("mitigated")):
                actions.append(
                    _proof_attack_triage_action(
                        case,
                        "unmitigated_rank1_decoy",
                        "P0",
                        "A generated decoy reached rank 1 and must become a hard negative regression.",
                        "Add a route-family/off-route-writer penalty or proof-path requirement that demotes this label below the true route target.",
                        decoy,
                    )
                )
            elif not signals:
                priority = "P2" if decoy.get("status") == "ranked_below_audit_window" else "P1"
                actions.append(
                    _proof_attack_triage_action(
                        case,
                        "weak_signal_decoy",
                        priority,
                        "The decoy was mitigated by rank but lacks an explicit causal mitigation signal.",
                        "Add an auditable mitigation reason such as route-family conflict, off-route writer decoy, or documentation-only bait.",
                        decoy,
                    )
                )
    actions.sort(key=lambda item: (_triage_priority_rank(item.get("priority", "")), -int(item.get("attack_pressure", 0)), item.get("case_id", "")))
    counts = {priority: sum(1 for item in actions if item.get("priority") == priority) for priority in ("P0", "P1", "P2")}
    return {
        "schema_version": "1.0",
        "strategy": "adversarial_proof_attack_triage",
        "benchmark": str(benchmark_path),
        "leaderboard": str(leaderboard_path) if leaderboard_path else "",
        "suite": (benchmark.get("spec") or {}).get("suite", ""),
        "status": "blocker" if counts["P0"] else "needs_hardening" if counts["P1"] else "monitor",
        "action_count": len(actions),
        "priority_counts": counts,
        "metrics": {
            "case_count": int((benchmark.get("metrics") or {}).get("case_count", 0)),
            "attack_resistance_rate": float((benchmark.get("metrics") or {}).get("attack_resistance_rate", 0.0)),
            "mitigated_decoy_rate": float((benchmark.get("metrics") or {}).get("mitigated_decoy_rate", 0.0)),
            "mitigation_signal_rate": float((benchmark.get("metrics") or {}).get("mitigation_signal_rate", 0.0)),
            "hardest_case": leaderboard.get("hardest_case", ""),
            "max_attack_pressure": int(leaderboard.get("max_attack_pressure", 0)),
            "max_residual_risk": int(leaderboard.get("max_residual_risk", 0)),
        },
        "actions": actions,
    }


def render_proof_attack_triage_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    priorities = dict(payload.get("priority_counts") or {})
    lines = [
        "# Repo Agent Adversarial Proof Attack Triage",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Suite: `{payload.get('suite', '')}`",
        f"- Benchmark: `{payload.get('benchmark', '')}`",
        f"- Actions: `{int(payload.get('action_count', 0))}`",
        f"- Priorities: `P0={int(priorities.get('P0', 0))}`, `P1={int(priorities.get('P1', 0))}`, `P2={int(priorities.get('P2', 0))}`",
        f"- Hardest case: `{metrics.get('hardest_case', '')}`",
        f"- Max attack pressure: `{int(metrics.get('max_attack_pressure', 0))}/100`",
        f"- Max residual risk: `{int(metrics.get('max_residual_risk', 0))}/100`",
        "",
        "| Priority | Case | Category | Attack Pressure | Suggested Guard |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for action in payload.get("actions", []):
        lines.append(
            f"| `{action.get('priority', '')}` | `{action.get('case_id', '')}` | `{action.get('category', '')}` | "
            f"{int(action.get('attack_pressure', 0))} | {_markdown_cell(action.get('suggested_guard', ''))} |"
        )
    lines.extend(["", "## Action Details", ""])
    for action in payload.get("actions", []):
        lines.extend(
            [
                f"### {action.get('priority', '')} `{action.get('case_id', '')}` / `{action.get('category', '')}`",
                "",
                f"- Threat model: {action.get('threat_model', '') or 'n/a'}",
                f"- Diagnosis: {action.get('diagnosis', '')}",
                f"- Suggested guard: {action.get('suggested_guard', '')}",
                f"- Evidence hash: `{action.get('evidence_hash', '')}`",
                "",
            ]
        )
    return "\n".join(lines)


def write_proof_attack_triage_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_proof_attack_triage_markdown(payload), encoding="utf-8")
    return output_path


def synthesize_proof_attack_policy(
    benchmark_path: Path,
    *,
    leaderboard_path: Path | None = None,
    triage_path: Path | None = None,
    leaderboard_payload: dict | None = None,
    triage_payload: dict | None = None,
) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    leaderboard = leaderboard_payload or (
        json.loads(leaderboard_path.read_text(encoding="utf-8"))
        if leaderboard_path is not None
        else build_proof_attack_leaderboard(benchmark_path)
    )
    triage = triage_payload or (
        json.loads(triage_path.read_text(encoding="utf-8"))
        if triage_path is not None
        else build_proof_attack_triage(benchmark_path, leaderboard_path=leaderboard_path)
    )
    actions = list(triage.get("actions") or [])
    rules = _synthesize_proof_attack_policy_rules(actions)
    coverage = _simulate_proof_attack_policy(actions, rules, benchmark=benchmark, leaderboard=leaderboard, triage=triage)
    policy_id = _stable_short_hash(
        {
            "suite": (benchmark.get("spec") or {}).get("suite", ""),
            "benchmark": str(benchmark_path),
            "rules": [rule["id"] for rule in rules],
            "covered": coverage["covered_action_count"],
        }
    )
    return {
        "schema_version": "1.0",
        "strategy": "adversarial_proof_attack_policy_synthesis",
        "policy_id": f"proof-attack-policy-{policy_id}",
        "benchmark": str(benchmark_path),
        "leaderboard": str(leaderboard_path) if leaderboard_path else "",
        "triage": str(triage_path) if triage_path else "",
        "suite": (benchmark.get("spec") or {}).get("suite", ""),
        "status": coverage["status"],
        "rule_count": len(rules),
        "rules": rules,
        "simulation": coverage,
        "counterexamples": _proof_attack_policy_counterexamples(actions, rules),
    }


def render_proof_attack_policy_markdown(payload: dict) -> str:
    simulation = dict(payload.get("simulation") or {})
    before = dict(simulation.get("before") or {})
    after = dict(simulation.get("after") or {})
    lines = [
        "# Repo Agent Proof Attack Defense Policy Synthesis",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Policy: `{payload.get('policy_id', '')}`",
        f"- Suite: `{payload.get('suite', '')}`",
        f"- Benchmark: `{payload.get('benchmark', '')}`",
        f"- Rules: `{int(payload.get('rule_count', 0))}`",
        f"- Counterexample coverage: `{float(simulation.get('coverage_rate', 0.0)):.2%}`",
        f"- Residual actions: `{int(after.get('uncovered_action_count', 0))}` "
        f"(`P0={int(after.get('P0', 0))}`, `P1={int(after.get('P1', 0))}`, `P2={int(after.get('P2', 0))}`)",
        f"- Expected mitigation-signal coverage: `{float(after.get('expected_mitigation_signal_rate', 0.0)):.2%}` "
        f"(before `{float(before.get('mitigation_signal_rate', 0.0)):.2%}`)",
        "",
        "## Synthesized Rules",
        "",
        "| Rule | Type | Covers | Effect | Confidence |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for rule in payload.get("rules", []):
        effect = "; ".join(str(item) for item in rule.get("effect", {}).get("signals", [])) or str(rule.get("effect", {}).get("action", ""))
        lines.append(
            f"| `{rule.get('id', '')}` | `{rule.get('type', '')}` | {len(rule.get('covers', []))} | "
            f"{_markdown_cell(effect)} | {float(rule.get('confidence', 0.0)):.2f} |"
        )
    lines.extend(
        [
            "",
            "## Before / After Simulation",
            "",
            "| Metric | Before | After Policy |",
            "| --- | ---: | ---: |",
            f"| Open actions | {int(before.get('action_count', 0))} | {int(after.get('uncovered_action_count', 0))} |",
            f"| P0 actions | {int(before.get('P0', 0))} | {int(after.get('P0', 0))} |",
            f"| P1 actions | {int(before.get('P1', 0))} | {int(after.get('P1', 0))} |",
            f"| P2 actions | {int(before.get('P2', 0))} | {int(after.get('P2', 0))} |",
            f"| Mitigation signal coverage | {float(before.get('mitigation_signal_rate', 0.0)):.2%} | {float(after.get('expected_mitigation_signal_rate', 0.0)):.2%} |",
            "",
            "## Counterexample Coverage",
            "",
            "| Priority | Case | Category | Covered By | Evidence |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("counterexamples", []):
        covered_by = ", ".join(f"`{rule_id}`" for rule_id in item.get("covered_by", [])) or "`uncovered`"
        lines.append(
            f"| `{item.get('priority', '')}` | `{item.get('case_id', '')}` | `{item.get('category', '')}` | "
            f"{covered_by} | `{item.get('evidence_hash', '')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def write_proof_attack_policy_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_proof_attack_policy_markdown(payload), encoding="utf-8")
    return output_path


def run_adaptive_proof_attack_curriculum(
    runtime: RepoAgentRuntime,
    *,
    baseline_benchmark_path: Path,
    policy_path: Path,
    output_dir: Path,
    top_k: int = 6,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_benchmark_path.read_text(encoding="utf-8"))
    adaptive_spec = build_adaptive_proof_attack_spec(baseline, policy)
    adaptive_spec_path = output_dir / "proof-attack-adaptive-spec.json"
    adaptive_spec_path.write_text(json.dumps(adaptive_spec, ensure_ascii=False, indent=2), encoding="utf-8")

    benchmark_payload = run_proof_attack_benchmark(
        runtime,
        output_dir=output_dir / "adaptive-workspaces",
        top_k=top_k,
        spec_path=adaptive_spec_path,
    )
    benchmark_json_path = write_proof_attack_output(benchmark_payload, output_dir / "proof-attack-adaptive-benchmark.json")
    benchmark_path = write_proof_attack_output(benchmark_payload, output_dir / "proof-attack-adaptive-benchmark.md")
    leaderboard_payload = build_proof_attack_leaderboard(benchmark_json_path)
    leaderboard_json_path = write_proof_attack_leaderboard_output(leaderboard_payload, output_dir / "proof-attack-adaptive-leaderboard.json")
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard_payload, output_dir / "proof-attack-adaptive-leaderboard.md")
    triage_payload = build_proof_attack_triage(benchmark_json_path, leaderboard_path=leaderboard_json_path)
    triage_json_path = write_proof_attack_triage_output(triage_payload, output_dir / "proof-attack-adaptive-triage.json")
    triage_path = write_proof_attack_triage_output(triage_payload, output_dir / "proof-attack-adaptive-triage.md")

    policy_eval = evaluate_proof_attack_policy_on_triage(policy, triage_payload)
    uncovered = list(policy_eval.get("uncovered_actions") or [])
    status = "adaptive_gap_found" if uncovered else "adaptive_policy_holds"
    artifacts = [
        _artifact("proof_attack_adaptive_spec", adaptive_spec_path, "Generated second-order attack spec targeting synthesized policy rules."),
        _artifact("proof_attack_adaptive_benchmark_json", benchmark_json_path, "Machine-readable adaptive proof attack benchmark results."),
        _artifact("proof_attack_adaptive_benchmark", benchmark_path, "Human-readable adaptive proof attack benchmark."),
        _artifact("proof_attack_adaptive_leaderboard_json", leaderboard_json_path, "Machine-readable adaptive attack leaderboard."),
        _artifact("proof_attack_adaptive_leaderboard", leaderboard_path, "Adaptive attack pressure and residual-risk leaderboard."),
        _artifact("proof_attack_adaptive_triage_json", triage_json_path, "Machine-readable triage for adaptive policy stress test."),
        _artifact("proof_attack_adaptive_triage", triage_path, "Adaptive counterexample triage report."),
    ]
    return {
        "schema_version": "1.0",
        "strategy": "adaptive_proof_attack_curriculum",
        "status": status,
        "baseline_benchmark": str(baseline_benchmark_path),
        "policy": str(policy_path),
        "policy_id": policy.get("policy_id", ""),
        "output_dir": str(output_dir),
        "adaptive_spec": str(adaptive_spec_path),
        "adaptive_suite": adaptive_spec.get("suite", ""),
        "case_count": len(adaptive_spec.get("cases", [])),
        "benchmark": str(benchmark_json_path),
        "metrics": {
            "attack_resistance_rate": float((benchmark_payload.get("metrics") or {}).get("attack_resistance_rate", 0.0)),
            "max_attack_pressure": int(leaderboard_payload.get("max_attack_pressure", 0)),
            "max_residual_risk": int(leaderboard_payload.get("max_residual_risk", 0)),
            "triage_actions": int(triage_payload.get("action_count", 0)),
            "policy_coverage_rate": float(policy_eval.get("coverage_rate", 0.0)),
            "policy_uncovered_actions": int(policy_eval.get("uncovered_action_count", 0)),
        },
        "adaptive_cases": [
            {
                "id": case.get("id", ""),
                "targets_rule": case.get("targets_rule", ""),
                "adaptation": case.get("adaptation", ""),
                "threat_model": case.get("threat_model", ""),
            }
            for case in adaptive_spec.get("cases", [])
        ],
        "policy_evaluation": policy_eval,
        "artifacts": artifacts,
    }


def build_adaptive_proof_attack_spec(baseline_benchmark: dict, policy: dict) -> dict:
    suite = (baseline_benchmark.get("spec") or {}).get("suite", "proof-attacks")
    rules = {str(rule.get("id", "")) for rule in policy.get("rules", [])}
    cases = []
    if "documentation_bait_signal" in rules:
        cases.append(
            {
                "id": "adaptive_semantic_bait_writer",
                "description": "Semantic writer bait avoids the documentation/notes lexical trigger used by the synthesized policy.",
                "threat_model": "non-executed semantic bait that resembles the public stream writer without documentation naming",
                "severity": "high",
                "tags": ["semantic-decoy", "policy-adaptive"],
                "targets_rule": "documentation_bait_signal",
                "adaptation": "rename documentation bait to guide/reference terms and remove the documentation-bait tag",
                "mutation": {
                    "template": "documentation_bait",
                    "functions": [
                        {
                            "name": "writePublicChatDeltaGuide",
                            "return_text": "public api chat stream token writer final response event data route handler",
                        },
                        {
                            "name": "writeChatDeltaReference",
                            "return_text": "chat delta streamed token writer for api chat endpoint proof path response",
                        },
                    ],
                },
                "distractors": ["writePublicChatDeltaGuide", "writeChatDeltaReference"],
            }
        )
    if "ranked_below_audit_window_signal" in rules:
        cases.append(
            {
                "id": "adaptive_near_route_draft_writer",
                "description": "Near-route draft writer keeps the decoy executable but outside the requested route path.",
                "threat_model": "near-route public-looking writer attempts to hide behind rank-window demotion policy",
                "severity": "medium",
                "tags": ["near-route", "writer-decoy", "policy-adaptive"],
                "targets_rule": "ranked_below_audit_window_signal",
                "adaptation": "use a draft sibling route with public chat vocabulary and a plausible stream writer",
                "mutation": {
                    "template": "route_writer_decoy",
                    "route": "/api/chat-draft",
                    "handler": "handlePublicChatDraft",
                    "writer": "writeChatDeltaDraft",
                    "event": "chat.delta",
                    "token": "draft-only",
                    "payload_name": "draft",
                },
                "distractors": ["writeChatDeltaDraft", "handlePublicChatDraft"],
            }
        )
    if "audit_generated_decoys" in rules or "pin_high_pressure_counterexamples" in rules:
        cases.append(
            {
                "id": "adaptive_shadow_stream_writer",
                "description": "Privileged shadow writer changes route vocabulary while preserving public stream semantics.",
                "threat_model": "off-route privileged writer probes whether audit expansion and regression pins generalize",
                "severity": "high",
                "tags": ["route-family", "writer-decoy", "policy-adaptive"],
                "targets_rule": "audit_generated_decoys,pin_high_pressure_counterexamples",
                "adaptation": "combine privileged route with public stream naming but avoid the original admin-shadow identifiers",
                "mutation": {
                    "template": "route_writer_decoy",
                    "route": "/api/internal/chat/stream",
                    "handler": "handleInternalChatStream",
                    "writer": "writePublicChatDeltaMirror",
                    "event": "chat.delta",
                    "token": "internal-mirror",
                    "payload_name": "mirror",
                },
                "distractors": ["writePublicChatDeltaMirror", "handleInternalChatStream"],
            }
        )
    case_ids = {str(case.get("id", "")) for case in cases}
    if len(cases) < 3 and "documentation_bait_signal" in rules and "adaptive_procedural_reference_writer" not in case_ids:
        cases.append(
            {
                "id": "adaptive_procedural_reference_writer",
                "description": "Procedural reference bait swaps documentation labels for guide/reference language while preserving stream-writer semantics.",
                "threat_model": "non-executed reference prose that should be treated as a semantic decoy even without documentation labels",
                "severity": "medium",
                "tags": ["semantic-decoy", "reference-bait", "policy-adaptive"],
                "targets_rule": "documentation_bait_signal",
                "adaptation": "replace documentation/notes lexical hooks with guide/reference wording and public stream writer tokens",
                "mutation": {
                    "template": "documentation_bait",
                    "functions": [
                        {
                            "name": "writeChatDeltaProcedureGuide",
                            "return_text": "public chat stream writer procedure guide final token response event route",
                        },
                        {
                            "name": "writeChatDeltaReferencePlan",
                            "return_text": "api chat endpoint reference plan streams token payload to response writer",
                        },
                    ],
                },
                "distractors": ["writeChatDeltaProcedureGuide", "writeChatDeltaReferencePlan"],
            }
        )
        case_ids.add("adaptive_procedural_reference_writer")
    if len(cases) < 3 and "adaptive_protocol_mirror_writer" not in case_ids:
        cases.append(
            {
                "id": "adaptive_protocol_mirror_writer",
                "description": "Protocol mirror writer keeps public chat stream semantics under an internal protocol route.",
                "threat_model": "off-route protocol mirror probes route-family generalization beyond first-round decoys",
                "severity": "high",
                "tags": ["route-family", "writer-decoy", "protocol-mirror", "policy-adaptive"],
                "targets_rule": "audit_generated_decoys,pin_high_pressure_counterexamples",
                "adaptation": "move stream-writer behavior into an internal protocol path while preserving public payload vocabulary",
                "mutation": {
                    "template": "route_writer_decoy",
                    "route": "/api/protocol/chat/mirror",
                    "handler": "handleProtocolChatMirror",
                    "writer": "writeProtocolChatDeltaMirror",
                    "event": "chat.delta",
                    "token": "protocol-mirror",
                    "payload_name": "protocol",
                },
                "distractors": ["writeProtocolChatDeltaMirror", "handleProtocolChatMirror"],
            }
        )
        case_ids.add("adaptive_protocol_mirror_writer")
    if not cases:
        cases.append(
            {
                "id": "adaptive_generic_semantic_bait",
                "description": "Fallback semantic bait generated when the policy has no recognized proof attack rules.",
                "threat_model": "generic second-order semantic bait",
                "severity": "medium",
                "tags": ["semantic-decoy", "policy-adaptive"],
                "targets_rule": "unknown",
                "adaptation": "probe unknown policy surface with a non-executed public-stream-like function",
                "mutation": {
                    "template": "documentation_bait",
                    "functions": [
                        {
                            "name": "writeChatDeltaGuide",
                            "return_text": "public chat endpoint stream writer token event data proof route",
                        }
                    ],
                },
                "distractors": ["writeChatDeltaGuide"],
            }
        )
    return {
        "schema_version": "1.0",
        "suite": f"{suite}-adaptive-policy-curriculum",
        "description": "Second-order proof attack curriculum generated from synthesized defense policy rules.",
        "cases": cases,
    }


def evaluate_proof_attack_policy_on_triage(policy: dict, triage_payload: dict) -> dict:
    actions = list(triage_payload.get("actions") or [])
    rules = list(policy.get("rules") or [])
    matched = []
    uncovered = []
    for action in actions:
        matching_rules = [
            str(rule.get("id", ""))
            for rule in rules
            if _proof_attack_policy_rule_matches_action(rule, action)
        ]
        item = {
            "case_id": action.get("case_id", ""),
            "category": action.get("category", ""),
            "priority": action.get("priority", ""),
            "attack_pressure": int(action.get("attack_pressure", 0)),
            "evidence_hash": action.get("evidence_hash", ""),
            "matched_rules": matching_rules,
        }
        if matching_rules:
            matched.append(item)
        else:
            uncovered.append(item)
    total = max(len(actions), 1)
    priority_counts = {priority: sum(1 for action in uncovered if action.get("priority") == priority) for priority in ("P0", "P1", "P2")}
    return {
        "status": "covered" if not uncovered else "gap",
        "action_count": len(actions),
        "matched_action_count": len(matched),
        "uncovered_action_count": len(uncovered),
        "coverage_rate": (len(actions) - len(uncovered)) / total,
        "uncovered_priority_counts": priority_counts,
        "matched_actions": matched,
        "uncovered_actions": uncovered,
    }


def render_adaptive_proof_attack_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    evaluation = dict(payload.get("policy_evaluation") or {})
    lines = [
        "# Repo Agent Adaptive Proof Attack Curriculum",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Policy: `{payload.get('policy_id', '')}`",
        f"- Adaptive suite: `{payload.get('adaptive_suite', '')}`",
        f"- Cases: `{int(payload.get('case_count', 0))}`",
        f"- Adaptive attack resistance: `{float(metrics.get('attack_resistance_rate', 0.0)):.2%}`",
        f"- Max adaptive attack pressure: `{int(metrics.get('max_attack_pressure', 0))}/100`",
        f"- Policy coverage on adaptive triage: `{float(metrics.get('policy_coverage_rate', 0.0)):.2%}`",
        f"- Uncovered adaptive actions: `{int(metrics.get('policy_uncovered_actions', 0))}`",
        f"- Generated spec: `{payload.get('adaptive_spec', '')}`",
        "",
        "## Adaptive Cases",
        "",
        "| Case | Targets Rule | Adaptation | Threat Model |",
        "| --- | --- | --- | --- |",
    ]
    for case in payload.get("adaptive_cases", []):
        lines.append(
            f"| `{case.get('id', '')}` | `{case.get('targets_rule', '')}` | "
            f"{_markdown_cell(str(case.get('adaptation', '')))} | {_markdown_cell(str(case.get('threat_model', '')))} |"
        )
    lines.extend(["", "## Original Policy Evaluation", "", "| Result | Case | Category | Priority | Matched Rules | Evidence |", "| --- | --- | --- | --- | --- | --- |"])
    for item in evaluation.get("matched_actions", []):
        rules = ", ".join(f"`{rule}`" for rule in item.get("matched_rules", []))
        lines.append(f"| `covered` | `{item.get('case_id', '')}` | `{item.get('category', '')}` | `{item.get('priority', '')}` | {rules} | `{item.get('evidence_hash', '')}` |")
    for item in evaluation.get("uncovered_actions", []):
        lines.append(f"| `gap` | `{item.get('case_id', '')}` | `{item.get('category', '')}` | `{item.get('priority', '')}` | `none` | `{item.get('evidence_hash', '')}` |")
    if payload.get("artifacts"):
        lines.extend(["", "## Artifacts", "", "| Name | Path | SHA-256 |", "| --- | --- | --- |"])
        for artifact in payload.get("artifacts", []):
            digest = str(artifact.get("sha256", ""))
            lines.append(f"| `{artifact.get('name', '')}` | `{artifact.get('path', '')}` | `{digest[:12]}` |")
    lines.append("")
    return "\n".join(lines)


def write_adaptive_proof_attack_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_adaptive_proof_attack_markdown(payload), encoding="utf-8")
    return output_path


def synthesize_adaptive_policy_repair(*, policy_path: Path, adaptive_path: Path) -> dict:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    adaptive = json.loads(adaptive_path.read_text(encoding="utf-8"))
    triage_path = _adaptive_artifact_path(adaptive, "proof_attack_adaptive_triage_json", base_path=adaptive_path)
    triage_payload = json.loads(triage_path.read_text(encoding="utf-8"))
    before = evaluate_proof_attack_policy_on_triage(policy, triage_payload)
    patch_rules = _synthesize_adaptive_policy_repair_rules(policy, triage_payload, before)
    repaired_policy = json.loads(json.dumps(policy, ensure_ascii=False))
    existing_rule_ids = {str(rule.get("id", "")) for rule in repaired_policy.get("rules", [])}
    repaired_policy.setdefault("rules", [])
    for rule in patch_rules:
        if rule.get("id") not in existing_rule_ids:
            repaired_policy["rules"].append(rule)
    repair_hash = _stable_short_hash(
        {
            "base_policy": policy.get("policy_id", ""),
            "adaptive": adaptive.get("adaptive_suite", ""),
            "rules": [rule.get("id", "") for rule in patch_rules],
        }
    )
    repaired_policy["policy_id"] = f"{policy.get('policy_id', 'proof-attack-policy')}-repair-{repair_hash}"
    repaired_policy["status"] = "policy_repaired"
    repaired_policy["rule_count"] = len(repaired_policy.get("rules", []))
    repaired_policy["repair"] = {
        "source_policy": policy.get("policy_id", ""),
        "adaptive_report": str(adaptive_path),
        "patch_rule_count": len(patch_rules),
        "patch_rule_ids": [rule.get("id", "") for rule in patch_rules],
    }
    after = evaluate_proof_attack_policy_on_triage(repaired_policy, triage_payload)
    status = "repair_converges" if int(after.get("uncovered_action_count", 0)) == 0 else "repair_incomplete"
    return {
        "schema_version": "1.0",
        "strategy": "adaptive_proof_attack_policy_repair",
        "status": status,
        "policy": str(policy_path),
        "adaptive": str(adaptive_path),
        "adaptive_triage": str(triage_path),
        "source_policy_id": policy.get("policy_id", ""),
        "repaired_policy_id": repaired_policy.get("policy_id", ""),
        "patch_rule_count": len(patch_rules),
        "patch_rules": patch_rules,
        "before": before,
        "after": after,
        "coverage_delta": float(after.get("coverage_rate", 0.0)) - float(before.get("coverage_rate", 0.0)),
        "residual_delta": int(after.get("uncovered_action_count", 0)) - int(before.get("uncovered_action_count", 0)),
        "repaired_policy": repaired_policy,
    }


def render_adaptive_policy_repair_markdown(payload: dict) -> str:
    before = dict(payload.get("before") or {})
    after = dict(payload.get("after") or {})
    lines = [
        "# Repo Agent Adaptive Policy Repair",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Source policy: `{payload.get('source_policy_id', '')}`",
        f"- Repaired policy: `{payload.get('repaired_policy_id', '')}`",
        f"- Patch rules: `{int(payload.get('patch_rule_count', 0))}`",
        f"- Coverage: `{float(before.get('coverage_rate', 0.0)):.2%}` -> `{float(after.get('coverage_rate', 0.0)):.2%}`",
        f"- Uncovered actions: `{int(before.get('uncovered_action_count', 0))}` -> `{int(after.get('uncovered_action_count', 0))}`",
        "",
        "## Patch Rules",
        "",
        "| Rule | Type | Covers | Effect | Confidence |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for rule in payload.get("patch_rules", []):
        effect = "; ".join(str(item) for item in (rule.get("effect") or {}).get("signals", [])) or str((rule.get("effect") or {}).get("action", ""))
        lines.append(
            f"| `{rule.get('id', '')}` | `{rule.get('type', '')}` | {len(rule.get('covers', []))} | "
            f"{_markdown_cell(effect)} | {float(rule.get('confidence', 0.0)):.2f} |"
        )
    lines.extend(
        [
            "",
            "## Before / After Adaptive Coverage",
            "",
            "| Result | Case | Category | Priority | Matched Rules | Evidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in after.get("matched_actions", []):
        rules = ", ".join(f"`{rule}`" for rule in item.get("matched_rules", [])) or "`none`"
        lines.append(f"| `covered` | `{item.get('case_id', '')}` | `{item.get('category', '')}` | `{item.get('priority', '')}` | {rules} | `{item.get('evidence_hash', '')}` |")
    for item in after.get("uncovered_actions", []):
        lines.append(f"| `gap` | `{item.get('case_id', '')}` | `{item.get('category', '')}` | `{item.get('priority', '')}` | `none` | `{item.get('evidence_hash', '')}` |")
    lines.append("")
    return "\n".join(lines)


def write_adaptive_policy_repair_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_adaptive_policy_repair_markdown(payload), encoding="utf-8")
    return output_path


def build_proof_attack_minimax_certificate(
    *,
    benchmark_path: Path,
    policy_path: Path,
    adaptive_path: Path,
    repair_path: Path,
) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    adaptive = json.loads(adaptive_path.read_text(encoding="utf-8"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    claims = [
        _certificate_claim(
            "baseline_attacks_resisted",
            "Baseline generated proof attacks preserve the proved public route target.",
            float((benchmark.get("metrics") or {}).get("attack_resistance_rate", 0.0)) >= 1.0,
            {"attack_resistance_rate": (benchmark.get("metrics") or {}).get("attack_resistance_rate", 0.0), "cases": (benchmark.get("metrics") or {}).get("case_count", 0)},
        ),
        _certificate_claim(
            "policy_covers_first_order_triage",
            "Synthesized policy covers all first-order triage counterexamples.",
            policy.get("status") == "policy_converges"
            and float((policy.get("simulation") or {}).get("coverage_rate", 0.0)) >= 1.0
            and int(((policy.get("simulation") or {}).get("after") or {}).get("uncovered_action_count", 1)) == 0,
            {"policy_id": policy.get("policy_id", ""), "coverage": (policy.get("simulation") or {}).get("coverage_rate", 0.0)},
        ),
        _certificate_claim(
            "adaptive_curriculum_finds_policy_gap",
            "Second-order adaptive attacks expose at least one policy generalization gap.",
            adaptive.get("status") == "adaptive_gap_found"
            and float((adaptive.get("metrics") or {}).get("policy_coverage_rate", 1.0)) < 1.0
            and int((adaptive.get("metrics") or {}).get("policy_uncovered_actions", 0)) > 0,
            {
                "adaptive_suite": adaptive.get("adaptive_suite", ""),
                "coverage": (adaptive.get("metrics") or {}).get("policy_coverage_rate", 0.0),
                "uncovered": (adaptive.get("metrics") or {}).get("policy_uncovered_actions", 0),
            },
        ),
        _certificate_claim(
            "repair_closes_adaptive_gap",
            "Adaptive policy repair covers all second-order adaptive triage actions.",
            repair.get("status") == "repair_converges"
            and float((repair.get("after") or {}).get("coverage_rate", 0.0)) >= 1.0
            and int((repair.get("after") or {}).get("uncovered_action_count", 1)) == 0,
            {
                "patch_rules": repair.get("patch_rule_count", 0),
                "before": (repair.get("before") or {}).get("coverage_rate", 0.0),
                "after": (repair.get("after") or {}).get("coverage_rate", 0.0),
            },
        ),
        _certificate_claim(
            "policy_lineage_consistent",
            "Policy, adaptive curriculum, and repair reports reference the same policy lineage.",
            str(policy.get("policy_id", "")) == str(adaptive.get("policy_id", ""))
            and str(policy.get("policy_id", "")) == str(repair.get("source_policy_id", "")),
            {
                "policy_id": policy.get("policy_id", ""),
                "adaptive_policy_id": adaptive.get("policy_id", ""),
                "repair_source_policy_id": repair.get("source_policy_id", ""),
            },
        ),
    ]
    passed = sum(1 for claim in claims if claim.get("passed"))
    score = int(round(100 * passed / max(len(claims), 1)))
    return {
        "schema_version": "1.0",
        "strategy": "proof_attack_minimax_certificate",
        "status": "accepted" if passed == len(claims) else "rejected",
        "score": score,
        "grade": _temporal_repair_grade(score),
        "inputs": [
            _certificate_input("benchmark", benchmark_path),
            _certificate_input("policy", policy_path),
            _certificate_input("adaptive", adaptive_path),
            _certificate_input("repair", repair_path),
        ],
        "lineage": {
            "suite": (benchmark.get("spec") or {}).get("suite", ""),
            "policy_id": policy.get("policy_id", ""),
            "adaptive_suite": adaptive.get("adaptive_suite", ""),
            "repaired_policy_id": repair.get("repaired_policy_id", ""),
        },
        "metrics": {
            "baseline_attack_resistance": float((benchmark.get("metrics") or {}).get("attack_resistance_rate", 0.0)),
            "policy_coverage": float((policy.get("simulation") or {}).get("coverage_rate", 0.0)),
            "adaptive_policy_coverage": float((adaptive.get("metrics") or {}).get("policy_coverage_rate", 0.0)),
            "adaptive_uncovered_actions": int((adaptive.get("metrics") or {}).get("policy_uncovered_actions", 0)),
            "repair_coverage": float((repair.get("after") or {}).get("coverage_rate", 0.0)),
            "repair_uncovered_actions": int((repair.get("after") or {}).get("uncovered_action_count", 0)),
            "patch_rule_count": int(repair.get("patch_rule_count", 0)),
        },
        "claims": claims,
    }


def render_proof_attack_minimax_certificate_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Proof Attack Minimax Certificate",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Policy: `{(payload.get('lineage') or {}).get('policy_id', '')}`",
        f"- Repaired policy: `{(payload.get('lineage') or {}).get('repaired_policy_id', '')}`",
        f"- Baseline attack resistance: `{float(metrics.get('baseline_attack_resistance', 0.0)):.2%}`",
        f"- First-order policy coverage: `{float(metrics.get('policy_coverage', 0.0)):.2%}`",
        f"- Adaptive policy coverage: `{float(metrics.get('adaptive_policy_coverage', 0.0)):.2%}`",
        f"- Repair coverage: `{float(metrics.get('repair_coverage', 0.0)):.2%}`",
        "",
        "## Claims",
        "",
        "| Result | Claim | Evidence |",
        "| --- | --- | --- |",
    ]
    for claim in payload.get("claims", []):
        result = "PASS" if claim.get("passed") else "FAIL"
        lines.append(f"| `{result}` | `{claim.get('id', '')}` | `{claim.get('evidence_hash', '')}` |")
    lines.extend(["", "## Inputs", "", "| Name | Path | SHA-256 |", "| --- | --- | --- |"])
    for item in payload.get("inputs", []):
        lines.append(f"| `{item.get('name', '')}` | `{item.get('path', '')}` | `{str(item.get('sha256', ''))[:12]}` |")
    lines.append("")
    return "\n".join(lines)


def write_proof_attack_minimax_certificate_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_proof_attack_minimax_certificate_markdown(payload), encoding="utf-8")
    return output_path


def build_proof_attack_scorecard(
    benchmark_path: Path,
    *,
    min_attack_resistance: float = 1.0,
    min_mitigated_decoys: float = 1.0,
    min_mitigation_signals: float = 0.5,
    min_proof_proved: float = 1.0,
) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    metrics = dict(benchmark.get("metrics") or {})
    attack_resistance = float(metrics.get("attack_resistance_rate", 0.0))
    mitigated_decoys = float(metrics.get("mitigated_decoy_rate", 0.0))
    mitigation_signals = float(metrics.get("mitigation_signal_rate", 0.0))
    proof_proved = float(metrics.get("proof_proved_rate", 0.0))
    items = [
        {
            "id": "attack_resistance",
            "weight": 35,
            "value": attack_resistance,
            "threshold": min_attack_resistance,
            "passed": attack_resistance >= min_attack_resistance,
        },
        {
            "id": "generated_decoy_mitigation",
            "weight": 25,
            "value": mitigated_decoys,
            "threshold": min_mitigated_decoys,
            "passed": mitigated_decoys >= min_mitigated_decoys,
        },
        {
            "id": "mitigation_signal_coverage",
            "weight": 20,
            "value": mitigation_signals,
            "threshold": min_mitigation_signals,
            "passed": mitigation_signals >= min_mitigation_signals,
        },
        {
            "id": "proof_proved_rate",
            "weight": 20,
            "value": proof_proved,
            "threshold": min_proof_proved,
            "passed": proof_proved >= min_proof_proved,
        },
    ]
    score = sum(item["weight"] for item in items if item["passed"])
    passed = all(item["passed"] for item in items)
    payload = {
        "schema_version": "1.0",
        "strategy": "adversarial_proof_attack_scorecard",
        "benchmark": str(benchmark_path),
        "status": "pass" if passed else "fail",
        "score": score,
        "grade": _temporal_repair_grade(score),
        "case_count": int(metrics.get("case_count", 0)),
        "generated_decoy_count": int(metrics.get("generated_decoy_count", 0)),
        "items": items,
        "metrics": metrics,
        "failed_cases": [case for case in benchmark.get("cases", []) if not bool(case.get("passed"))],
        "unmitigated_decoys": _proof_attack_unmitigated_decoys(benchmark),
        "weak_signal_decoys": _proof_attack_weak_signal_decoys(benchmark),
    }
    payload["github_annotations"] = _proof_attack_scorecard_github_annotations(payload)
    return payload


def render_proof_attack_scorecard_markdown(payload: dict) -> str:
    lines = [
        "# Repo Agent Adversarial Proof Attack Scorecard",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Benchmark: `{payload.get('benchmark', '')}`",
        f"- Cases: `{int(payload.get('case_count', 0))}`",
        f"- Generated decoys: `{int(payload.get('generated_decoy_count', 0))}`",
        "",
        "| Item | Value | Threshold | Result | Weight |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for item in payload.get("items", []):
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(
            f"| `{item.get('id', '')}` | `{float(item.get('value', 0.0)):.2%}` | "
            f"`{float(item.get('threshold', 0.0)):.2%}` | `{result}` | {int(item.get('weight', 0))} |"
        )
    failed_cases = list(payload.get("failed_cases") or [])
    if failed_cases:
        lines.extend(["", "## Failed Attack Cases", "", "| Case | Graph-MCTS Top Hit | Proof |", "| --- | --- | --- |"])
        for case in failed_cases:
            graph = dict((case.get("variants") or {}).get("graph_mcts") or {})
            proof = dict(case.get("proof") or {})
            lines.append(
                f"| `{case.get('id', '')}` | `{graph.get('top_hit', '')}` | "
                f"`{proof.get('proof_status', '')}` / `{proof.get('top_hit', '')}` |"
            )
    unmitigated = list(payload.get("unmitigated_decoys") or [])
    if unmitigated:
        lines.extend(["", "## Unmitigated Decoys", "", "| Case | Decoy | Rank |", "| --- | --- | ---: |"])
        for item in unmitigated:
            lines.append(f"| `{item.get('case_id', '')}` | `{item.get('label', '')}` | {item.get('rank', '')} |")
    weak = list(payload.get("weak_signal_decoys") or [])
    if weak:
        lines.extend(["", "## Weak-Signal Decoys", "", "| Case | Decoy | Rank | Status |", "| --- | --- | ---: | --- |"])
        for item in weak:
            rank = item.get("rank") if item.get("rank") is not None else f">{item.get('audit_top_k', 0)}"
            lines.append(f"| `{item.get('case_id', '')}` | `{item.get('label', '')}` | {rank} | `{item.get('status', '')}` |")
    lines.append("")
    return "\n".join(lines)


def write_proof_attack_scorecard_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_proof_attack_scorecard_markdown(payload), encoding="utf-8")
    return output_path


def render_proof_attack_scorecard_sarif(payload: dict) -> dict:
    benchmark_uri = _temporal_scorecard_sarif_uri(str(payload.get("benchmark", "")))
    results = []
    for item in payload.get("items", []):
        if item.get("passed"):
            continue
        item_id = str(item.get("id", "proof_attack_scorecard_item"))
        value = float(item.get("value", 0.0))
        threshold = float(item.get("threshold", 0.0))
        results.append(
            {
                "ruleId": "repo-agent/proof-attack-threshold-failed",
                "level": "error",
                "message": {"text": f"Proof attack scorecard item {item_id} is {value:.2%}, below threshold {threshold:.2%}."},
                "locations": [_temporal_scorecard_sarif_location(benchmark_uri)],
                "properties": {
                    "scorecardItem": item_id,
                    "value": value,
                    "threshold": threshold,
                    "weight": int(item.get("weight", 0)),
                    "score": payload.get("score", 0),
                    "grade": payload.get("grade", ""),
                },
            }
        )
    for case in payload.get("failed_cases", []):
        results.append(
            {
                "ruleId": "repo-agent/proof-attack-case-failed",
                "level": "error",
                "message": {"text": _proof_attack_case_summary(case)},
                "locations": [_temporal_scorecard_sarif_location(benchmark_uri)],
                "properties": {
                    "caseId": case.get("id", ""),
                    "expected": case.get("expected", ""),
                },
            }
        )
    for decoy in payload.get("unmitigated_decoys", []):
        results.append(
            {
                "ruleId": "repo-agent/proof-attack-decoy-unmitigated",
                "level": "error",
                "message": {"text": f"{decoy.get('case_id', '')}: generated decoy reached rank 1 ({decoy.get('label', '')})."},
                "locations": [_temporal_scorecard_sarif_location(benchmark_uri)],
                "properties": decoy,
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Repo Agent Adversarial Proof Attack Scorecard",
                        "informationUri": "https://github.com/",
                        "rules": [
                            {
                                "id": "repo-agent/proof-attack-threshold-failed",
                                "name": "Proof attack scorecard threshold failed",
                                "shortDescription": {"text": "A self-red-team proof attack metric is below its release threshold."},
                                "fullDescription": {
                                    "text": "Repo Agent generated adversarial repository mutations and found that attack resistance or causal defense coverage missed a required threshold."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                            {
                                "id": "repo-agent/proof-attack-case-failed",
                                "name": "Proof attack case failed",
                                "shortDescription": {"text": "A generated proof attack case bypassed the expected defense."},
                                "fullDescription": {
                                    "text": "Repo Agent found an adversarial repository mutation where graph-MCTS or proof-carrying retrieval did not preserve the expected route-anchored proof."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                            {
                                "id": "repo-agent/proof-attack-decoy-unmitigated",
                                "name": "Generated proof attack decoy reached rank 1",
                                "shortDescription": {"text": "A generated adversarial decoy was not mitigated."},
                                "fullDescription": {
                                    "text": "Repo Agent found that a generated decoy reached the top rank in the proof attack benchmark."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                        ],
                    }
                },
                "results": results,
                "properties": {
                    "status": payload.get("status", ""),
                    "score": payload.get("score", 0),
                    "grade": payload.get("grade", ""),
                    "benchmark": payload.get("benchmark", ""),
                },
            }
        ],
    }


def write_proof_attack_scorecard_sarif(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(render_proof_attack_scorecard_sarif(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def run_proof_attack_cegar(
    runtime: RepoAgentRuntime,
    *,
    output_dir: Path,
    top_k: int = 6,
    spec_path: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_payload = run_proof_attack_benchmark(
        runtime,
        output_dir=output_dir / "benchmark-workspaces",
        top_k=top_k,
        spec_path=spec_path,
    )
    benchmark_json_path = write_proof_attack_output(benchmark_payload, output_dir / "proof-attack-benchmark.json")
    benchmark_path = write_proof_attack_output(benchmark_payload, output_dir / "proof-attack-benchmark.md")

    leaderboard_payload = build_proof_attack_leaderboard(benchmark_json_path)
    leaderboard_json_path = write_proof_attack_leaderboard_output(leaderboard_payload, output_dir / "proof-attack-leaderboard.json")
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard_payload, output_dir / "proof-attack-leaderboard.md")

    triage_payload = build_proof_attack_triage(benchmark_json_path, leaderboard_path=leaderboard_json_path)
    triage_json_path = write_proof_attack_triage_output(triage_payload, output_dir / "proof-attack-triage.json")
    triage_path = write_proof_attack_triage_output(triage_payload, output_dir / "proof-attack-triage.md")

    policy_payload = synthesize_proof_attack_policy(
        benchmark_json_path,
        leaderboard_payload=leaderboard_payload,
        triage_payload=triage_payload,
    )
    policy_json_path = write_proof_attack_policy_output(policy_payload, output_dir / "proof-attack-policy.json")
    policy_path = write_proof_attack_policy_output(policy_payload, output_dir / "proof-attack-policy.md")

    scorecard_payload = build_proof_attack_scorecard(benchmark_json_path)
    scorecard_json_path = write_proof_attack_scorecard_output(scorecard_payload, output_dir / "proof-attack-scorecard.json")
    scorecard_path = write_proof_attack_scorecard_output(scorecard_payload, output_dir / "proof-attack-scorecard.md")
    scorecard_sarif_path = write_proof_attack_scorecard_sarif(scorecard_payload, output_dir / "proof-attack-scorecard.sarif")

    return build_proof_attack_cegar_summary(
        benchmark_path=benchmark_json_path,
        leaderboard_payload=leaderboard_payload,
        triage_payload=triage_payload,
        scorecard_payload=scorecard_payload,
        policy_payload=policy_payload,
        artifact_paths={
            "proof_attack_benchmark_json": benchmark_json_path,
            "proof_attack_benchmark": benchmark_path,
            "proof_attack_leaderboard_json": leaderboard_json_path,
            "proof_attack_leaderboard": leaderboard_path,
            "proof_attack_triage_json": triage_json_path,
            "proof_attack_triage": triage_path,
            "proof_attack_policy_json": policy_json_path,
            "proof_attack_policy": policy_path,
            "proof_attack_scorecard_json": scorecard_json_path,
            "proof_attack_scorecard": scorecard_path,
            "proof_attack_scorecard_sarif": scorecard_sarif_path,
        },
    )


def build_proof_attack_cegar_summary(
    *,
    benchmark_path: Path,
    leaderboard_payload: dict,
    triage_payload: dict,
    scorecard_payload: dict,
    policy_payload: dict | None = None,
    artifact_paths: dict[str, Path] | None = None,
) -> dict:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark_metrics = dict(benchmark.get("metrics") or {})
    priority_counts = dict(triage_payload.get("priority_counts") or {})
    scorecard_items = list(scorecard_payload.get("items") or [])
    p0_count = int(priority_counts.get("P0", 0))
    p1_count = int(priority_counts.get("P1", 0))
    residual_risk = int(leaderboard_payload.get("max_residual_risk", 0))
    status = _proof_attack_cegar_status(
        p0_count=p0_count,
        p1_count=p1_count,
        residual_risk=residual_risk,
        scorecard_status=str(scorecard_payload.get("status", "unknown")),
    )
    next_actions = [
        {
            "priority": action.get("priority", ""),
            "case_id": action.get("case_id", ""),
            "category": action.get("category", ""),
            "suggested_guard": action.get("suggested_guard", ""),
            "evidence_hash": action.get("evidence_hash", ""),
        }
        for action in list(triage_payload.get("actions") or [])[:5]
    ]
    criteria = [
        {
            "id": "scorecard_passes",
            "passed": scorecard_payload.get("status") == "pass",
            "detail": f"{int(scorecard_payload.get('score', 0))}/100 grade {scorecard_payload.get('grade', '')}",
        },
        {
            "id": "no_blocking_counterexamples",
            "passed": p0_count == 0,
            "detail": f"P0={p0_count}",
        },
        {
            "id": "no_residual_risk",
            "passed": residual_risk == 0,
            "detail": f"max residual risk {residual_risk}/100",
        },
        {
            "id": "no_refinement_actions",
            "passed": p1_count == 0,
            "detail": f"P1={p1_count}",
        },
    ]
    if policy_payload:
        policy_simulation = dict(policy_payload.get("simulation") or {})
        policy_after = dict(policy_simulation.get("after") or {})
        criteria.append(
            {
                "id": "policy_covers_refinement_actions",
                "passed": int(policy_after.get("P0", 0)) == 0 and int(policy_after.get("P1", 0)) == 0,
                "detail": (
                    f"{float(policy_simulation.get('coverage_rate', 0.0)):.2%} coverage, "
                    f"{int(policy_after.get('uncovered_action_count', 0))} residual actions"
                ),
            }
        )
    artifacts = []
    for name, path in (artifact_paths or {}).items():
        if path.exists():
            artifacts.append(_artifact(name, path, _proof_attack_cegar_artifact_description(name)))
    iteration = {
        "id": 1,
        "suite": (benchmark.get("spec") or {}).get("suite", ""),
        "case_count": int(benchmark_metrics.get("case_count", 0)),
        "attack_resistance_rate": float(benchmark_metrics.get("attack_resistance_rate", 0.0)),
        "mitigated_decoy_rate": float(benchmark_metrics.get("mitigated_decoy_rate", 0.0)),
        "mitigation_signal_rate": float(benchmark_metrics.get("mitigation_signal_rate", 0.0)),
        "hardest_case": leaderboard_payload.get("hardest_case", ""),
        "max_attack_pressure": int(leaderboard_payload.get("max_attack_pressure", 0)),
        "max_residual_risk": residual_risk,
        "triage_status": triage_payload.get("status", "unknown"),
        "triage_actions": int(triage_payload.get("action_count", 0)),
        "priority_counts": priority_counts,
        "scorecard_status": scorecard_payload.get("status", "unknown"),
        "score": int(scorecard_payload.get("score", 0)),
        "grade": scorecard_payload.get("grade", ""),
    }
    return {
        "schema_version": "1.0",
        "strategy": "adversarial_proof_attack_cegar",
        "status": status,
        "benchmark": str(benchmark_path),
        "iteration_count": 1,
        "iterations": [iteration],
        "convergence_criteria": criteria,
        "next_actions": next_actions,
        "artifacts": artifacts,
        "scorecard_items": scorecard_items,
        "policy": {
            "status": (policy_payload or {}).get("status", ""),
            "policy_id": (policy_payload or {}).get("policy_id", ""),
            "rule_count": int((policy_payload or {}).get("rule_count", 0)),
            "coverage_rate": float(((policy_payload or {}).get("simulation") or {}).get("coverage_rate", 0.0)),
            "residual_actions": int((((policy_payload or {}).get("simulation") or {}).get("after") or {}).get("uncovered_action_count", 0)),
        },
        "summary": {
            "status": status,
            "hardest_case": iteration["hardest_case"],
            "max_attack_pressure": iteration["max_attack_pressure"],
            "max_residual_risk": iteration["max_residual_risk"],
            "action_count": iteration["triage_actions"],
            "p0": p0_count,
            "p1": p1_count,
            "score": iteration["score"],
            "grade": iteration["grade"],
        },
    }


def render_proof_attack_cegar_markdown(payload: dict) -> str:
    summary = dict(payload.get("summary") or {})
    policy = dict(payload.get("policy") or {})
    iterations = list(payload.get("iterations") or [])
    iteration = dict(iterations[-1] if iterations else {})
    lines = [
        "# Repo Agent Proof Attack CEGAR Loop",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Iterations: `{int(payload.get('iteration_count', 0))}`",
        f"- Benchmark: `{payload.get('benchmark', '')}`",
        f"- Hardest case: `{summary.get('hardest_case', '')}`",
        f"- Max attack pressure: `{int(summary.get('max_attack_pressure', 0))}/100`",
        f"- Max residual risk: `{int(summary.get('max_residual_risk', 0))}/100`",
        f"- Scorecard: `{int(summary.get('score', 0))}/100` (`{summary.get('grade', '')}`)",
        f"- Open actions: `{int(summary.get('action_count', 0))}` (`P0={int(summary.get('p0', 0))}`, `P1={int(summary.get('p1', 0))}`)",
        f"- Synthesized policy: `{policy.get('status', 'not_run') or 'not_run'}` "
        f"(`{int(policy.get('rule_count', 0))}` rules, `{float(policy.get('coverage_rate', 0.0)):.2%}` coverage)",
        "",
        "## Convergence Criteria",
        "",
        "| Criterion | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("convergence_criteria", []):
        result = "PASS" if item.get("passed") else "REFINE"
        lines.append(f"| `{item.get('id', '')}` | `{result}` | {_markdown_cell(str(item.get('detail', '')))} |")
    lines.extend(
        [
            "",
            "## Iteration 1",
            "",
            f"- Suite: `{iteration.get('suite', '')}`",
            f"- Cases: `{int(iteration.get('case_count', 0))}`",
            f"- Attack resistance: `{float(iteration.get('attack_resistance_rate', 0.0)):.2%}`",
            f"- Mitigated decoys: `{float(iteration.get('mitigated_decoy_rate', 0.0)):.2%}`",
            f"- Mitigation signal coverage: `{float(iteration.get('mitigation_signal_rate', 0.0)):.2%}`",
            "",
            "## Next Hardening Actions",
            "",
            "| Priority | Case | Category | Suggested Guard | Evidence |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    actions = list(payload.get("next_actions") or [])
    if actions:
        for action in actions:
            lines.append(
                f"| `{action.get('priority', '')}` | `{action.get('case_id', '')}` | `{action.get('category', '')}` | "
                f"{_markdown_cell(str(action.get('suggested_guard', '')))} | `{action.get('evidence_hash', '')}` |"
            )
    else:
        lines.append("| `none` | `n/a` | `converged` | No refinement action required. | `n/a` |")
    if payload.get("artifacts"):
        lines.extend(["", "## Loop Artifacts", "", "| Name | Path | SHA-256 |", "| --- | --- | --- |"])
        for artifact in payload.get("artifacts", []):
            digest = str(artifact.get("sha256", ""))
            lines.append(f"| `{artifact.get('name', '')}` | `{artifact.get('path', '')}` | `{digest[:12]}` |")
    lines.append("")
    return "\n".join(lines)


def write_proof_attack_cegar_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_proof_attack_cegar_markdown(payload), encoding="utf-8")
    return output_path


def _proof_attack_cegar_status(*, p0_count: int, p1_count: int, residual_risk: int, scorecard_status: str) -> str:
    if scorecard_status == "fail" or p0_count > 0:
        return "blocked"
    if p1_count > 0 or residual_risk > 0:
        return "needs_refinement"
    return "converged"


def _proof_attack_cegar_artifact_description(name: str) -> str:
    descriptions = {
        "proof_attack_benchmark_json": "Machine-readable generated counterexamples.",
        "proof_attack_benchmark": "Human-readable generated counterexample benchmark.",
        "proof_attack_leaderboard_json": "Machine-readable counterexample ranking.",
        "proof_attack_leaderboard": "Attack pressure and residual-risk leaderboard.",
        "proof_attack_triage_json": "Machine-readable defense hardening plan.",
        "proof_attack_triage": "Counterexample-guided refinement actions.",
        "proof_attack_policy_json": "Machine-readable synthesized defense policy.",
        "proof_attack_policy": "Counterexample-guided defense policy simulation.",
        "proof_attack_scorecard_json": "Machine-readable CEGAR quality gate.",
        "proof_attack_scorecard": "Thresholded self-red-team scorecard.",
        "proof_attack_scorecard_sarif": "SARIF output for CI and code scanning.",
    }
    return descriptions.get(name, "CEGAR loop artifact.")


def _synthesize_proof_attack_policy_rules(actions: list[dict]) -> list[dict]:
    rules: list[dict] = []

    def add_rule(
        rule_id: str,
        rule_type: str,
        predicate,
        *,
        condition: dict,
        effect: dict,
        rationale: str,
        confidence: float,
    ) -> set[str]:
        covered_actions = [_proof_attack_policy_action_ref(action) for action in actions if predicate(action)]
        if not covered_actions:
            return set()
        rules.append(
            {
                "id": rule_id,
                "type": rule_type,
                "condition": condition,
                "effect": effect,
                "rationale": rationale,
                "confidence": confidence,
                "covers": covered_actions,
            }
        )
        return {item["evidence_hash"] for item in covered_actions}

    covered: set[str] = set()
    covered |= add_rule(
        "audit_generated_decoys",
        "proof_audit_expansion",
        lambda action: action.get("category") == "generated_decoy_audit_gap",
        condition={"triage_category": "generated_decoy_audit_gap"},
        effect={
            "action": "include generated distractor labels in proof.decoy_audit candidate selection",
            "signals": ["generated-decoy-audited"],
        },
        rationale="Counterexamples showed generated distractors that were mitigated by ranking but absent from the proof ledger.",
        confidence=0.88,
    )
    covered |= add_rule(
        "pin_high_pressure_counterexamples",
        "release_regression_pin",
        lambda action: action.get("category") == "high_pressure_attack",
        condition={"triage_category": "high_pressure_attack", "attack_pressure_gte": 75},
        effect={
            "action": "require benchmark, leaderboard, scorecard, and policy review before reranker changes",
            "signals": ["high-pressure-regression-pinned"],
        },
        rationale="High-pressure attacks should remain release-blocking regressions even when the current scorecard passes.",
        confidence=0.91,
    )
    covered |= add_rule(
        "documentation_bait_signal",
        "causal_mitigation_signal",
        lambda action: action.get("category") == "weak_signal_decoy"
        and (
            "documentation-bait" in set(action.get("tags") or [])
            or _proof_attack_policy_evidence_contains(action, ("Documentation", "Notes", "documentation", "notes"))
        ),
        condition={"triage_category": "weak_signal_decoy", "label_contains": ["Documentation", "Notes"], "tag": "documentation-bait"},
        effect={
            "action": "mark documentation-like non-executed writers as documentation-only bait",
            "signals": ["documentation-only bait"],
        },
        rationale="Documentation bait can be semantically close to a true writer while remaining outside the executable proof path.",
        confidence=0.84,
    )
    covered |= add_rule(
        "ranked_below_audit_window_signal",
        "audit_window_signal",
        lambda action: action.get("category") == "weak_signal_decoy"
        and (action.get("evidence") or {}).get("status") == "ranked_below_audit_window",
        condition={"triage_category": "weak_signal_decoy", "decoy_status": "ranked_below_audit_window"},
        effect={
            "action": "preserve below-window generated decoys as explicitly mitigated by rank window",
            "signals": ["rank-window demotion"],
        },
        rationale="A decoy outside the defense audit window is mitigated by rank but still needs an explicit causal reason.",
        confidence=0.78,
    )
    covered |= add_rule(
        "rank1_decoy_hard_negative",
        "hard_negative_guard",
        lambda action: action.get("category") == "unmitigated_rank1_decoy",
        condition={"triage_category": "unmitigated_rank1_decoy"},
        effect={
            "action": "promote rank-1 generated decoys into hard negative regression fixtures",
            "signals": ["rank-1-decoy-blocked"],
        },
        rationale="A generated decoy at rank 1 is a blocking counterexample and should become a regression fixture.",
        confidence=0.95,
    )

    remaining_weak = [
        action
        for action in actions
        if action.get("category") == "weak_signal_decoy" and action.get("evidence_hash", "") not in covered
    ]
    if remaining_weak:
        add_rule(
            "explicit_weak_signal_backfill",
            "causal_mitigation_signal",
            lambda action: action in remaining_weak,
            condition={"triage_category": "weak_signal_decoy", "fallback": "unclassified mitigated decoy"},
            effect={
                "action": "require every mitigated generated decoy to carry at least one named causal signal",
                "signals": ["explicit-weak-signal-backfill"],
            },
            rationale="No mitigated generated decoy should remain silent; unclassified cases receive a fallback signal pending a narrower rule.",
            confidence=0.62,
        )

    rules.sort(key=lambda rule: (-len(rule.get("covers", [])), rule.get("id", "")))
    return rules


def _simulate_proof_attack_policy(actions: list[dict], rules: list[dict], *, benchmark: dict, leaderboard: dict, triage: dict) -> dict:
    covered_by: dict[str, list[str]] = {}
    for rule in rules:
        for action in rule.get("covers", []):
            covered_by.setdefault(action.get("evidence_hash", ""), []).append(rule.get("id", ""))
    uncovered = [action for action in actions if action.get("evidence_hash", "") not in covered_by]
    priority_before = dict(triage.get("priority_counts") or {})
    priority_after = {priority: sum(1 for action in uncovered if action.get("priority") == priority) for priority in ("P0", "P1", "P2")}
    decoys = [
        decoy
        for case in benchmark.get("cases", [])
        for decoy in (case.get("defense_audit") or {}).get("decoys", [])
    ]
    decoy_total = max(len(decoys), 1)
    current_signal_count = sum(1 for decoy in decoys if decoy.get("mitigation_signals"))
    covered_weak_labels = {
        str((action.get("evidence") or {}).get("label", ""))
        for action in actions
        if action.get("category") == "weak_signal_decoy" and action.get("evidence_hash", "") in covered_by
    }
    expected_signal_rate = min(1.0, (current_signal_count + len([item for item in covered_weak_labels if item])) / decoy_total)
    total_actions = max(len(actions), 1)
    coverage_rate = (len(actions) - len(uncovered)) / total_actions
    status = (
        "policy_blocked"
        if priority_after["P0"] > 0
        else "policy_converges"
        if not uncovered
        else "policy_reduces_risk"
    )
    return {
        "status": status,
        "covered_action_count": len(actions) - len(uncovered),
        "uncovered_action_count": len(uncovered),
        "coverage_rate": coverage_rate,
        "covered_by": covered_by,
        "before": {
            "action_count": len(actions),
            "P0": int(priority_before.get("P0", 0)),
            "P1": int(priority_before.get("P1", 0)),
            "P2": int(priority_before.get("P2", 0)),
            "mitigation_signal_rate": float((benchmark.get("metrics") or {}).get("mitigation_signal_rate", 0.0)),
            "max_residual_risk": int(leaderboard.get("max_residual_risk", 0)),
        },
        "after": {
            "uncovered_action_count": len(uncovered),
            "P0": priority_after["P0"],
            "P1": priority_after["P1"],
            "P2": priority_after["P2"],
            "expected_mitigation_signal_rate": expected_signal_rate,
            "max_residual_risk": 0 if priority_after["P0"] == 0 else int(leaderboard.get("max_residual_risk", 0)),
        },
    }


def _proof_attack_policy_counterexamples(actions: list[dict], rules: list[dict]) -> list[dict]:
    covered_by: dict[str, list[str]] = {}
    for rule in rules:
        for action in rule.get("covers", []):
            covered_by.setdefault(action.get("evidence_hash", ""), []).append(rule.get("id", ""))
    return [
        {
            "case_id": action.get("case_id", ""),
            "category": action.get("category", ""),
            "priority": action.get("priority", ""),
            "attack_pressure": action.get("attack_pressure", 0),
            "evidence_hash": action.get("evidence_hash", ""),
            "covered_by": covered_by.get(action.get("evidence_hash", ""), []),
        }
        for action in actions
    ]


def _proof_attack_policy_action_ref(action: dict) -> dict:
    return {
        "case_id": action.get("case_id", ""),
        "category": action.get("category", ""),
        "priority": action.get("priority", ""),
        "evidence_hash": action.get("evidence_hash", ""),
    }


def _proof_attack_policy_evidence_contains(action: dict, needles: tuple[str, ...]) -> bool:
    evidence = action.get("evidence") or {}
    haystacks = [str(evidence.get("label", "")), str(evidence.get("status", "")), " ".join(str(item) for item in evidence.get("reasons", []))]
    return any(needle in haystack for haystack in haystacks for needle in needles)


def _proof_attack_policy_rule_matches_action(rule: dict, action: dict) -> bool:
    condition = dict(rule.get("condition") or {})
    category = str(condition.get("triage_category", ""))
    if category and action.get("category") != category:
        return False
    case_prefix = str(condition.get("case_id_prefix", ""))
    if case_prefix and not str(action.get("case_id", "")).startswith(case_prefix):
        return False
    if "attack_pressure_gte" in condition and int(action.get("attack_pressure", 0)) < int(condition.get("attack_pressure_gte", 0)):
        return False
    if condition.get("tag") and str(condition.get("tag")) not in set(action.get("tags") or []):
        return False
    if condition.get("decoy_status") and (action.get("evidence") or {}).get("status") != condition.get("decoy_status"):
        return False
    label_needles = tuple(str(item) for item in condition.get("label_contains", []) if str(item))
    if label_needles:
        return _proof_attack_policy_evidence_contains(action, label_needles)
    if condition.get("fallback"):
        return not category or action.get("category") == category
    return True


def _adaptive_artifact_path(payload: dict, name: str, *, base_path: Path) -> Path:
    for artifact in payload.get("artifacts", []):
        if artifact.get("name") != name:
            continue
        candidate = Path(str(artifact.get("path", "")))
        if candidate.is_absolute() or candidate.exists():
            return candidate
        joined = base_path.parent / candidate
        if joined.exists():
            return joined
        return candidate
    raise ValueError(f"adaptive proof attack artifact not found: {name}")


def _synthesize_adaptive_policy_repair_rules(policy: dict, triage_payload: dict, before_eval: dict) -> list[dict]:
    actions_by_hash = {str(action.get("evidence_hash", "")): action for action in triage_payload.get("actions", [])}
    uncovered = [actions_by_hash.get(str(item.get("evidence_hash", "")), item) for item in before_eval.get("uncovered_actions", [])]
    uncovered = [action for action in uncovered if action]
    rules: list[dict] = []
    weak_actions = [action for action in uncovered if action.get("category") == "weak_signal_decoy"]
    if weak_actions:
        label_tokens = _adaptive_repair_label_tokens(weak_actions)
        rule_id = "adaptive_weak_signal_generalization"
        rules.append(
            {
                "id": rule_id,
                "type": "adaptive_causal_mitigation_signal",
                "condition": {
                    "triage_category": "weak_signal_decoy",
                    "case_id_prefix": "adaptive_",
                    "label_contains": label_tokens,
                },
                "effect": {
                    "action": "generalize weak-signal mitigation to adaptive semantic, mirror, guide, reference, and draft decoys",
                    "signals": ["adaptive-policy-generalized-signal"],
                },
                "rationale": "Second-order attacks changed naming while preserving stream-writer semantics; the original policy overfit the first benchmark labels.",
                "confidence": 0.81,
                "covers": [_proof_attack_policy_action_ref(action) for action in weak_actions],
                "source": {
                    "from_policy": policy.get("policy_id", ""),
                    "adaptive_uncovered_actions": len(weak_actions),
                },
            }
        )
    p0_actions = [action for action in uncovered if action.get("priority") == "P0"]
    if p0_actions:
        rules.append(
            {
                "id": "adaptive_p0_regression_pin",
                "type": "adaptive_release_regression_pin",
                "condition": {
                    "case_id_prefix": "adaptive_",
                    "attack_pressure_gte": min(int(action.get("attack_pressure", 100)) for action in p0_actions),
                },
                "effect": {
                    "action": "promote adaptive P0 attacks into the release-blocking regression curriculum",
                    "signals": ["adaptive-p0-regression-pinned"],
                },
                "rationale": "Adaptive attacks can expose high-pressure regressions that the first-round policy did not explicitly pin.",
                "confidence": 0.9,
                "covers": [_proof_attack_policy_action_ref(action) for action in p0_actions],
                "source": {
                    "from_policy": policy.get("policy_id", ""),
                    "adaptive_uncovered_actions": len(p0_actions),
                },
            }
        )
    repaired = json.loads(json.dumps(policy, ensure_ascii=False))
    repaired.setdefault("rules", [])
    repaired["rules"].extend(rules)
    after = evaluate_proof_attack_policy_on_triage(repaired, triage_payload)
    if int(after.get("uncovered_action_count", 0)) > 0:
        remaining = [
            actions_by_hash.get(str(item.get("evidence_hash", "")), item)
            for item in after.get("uncovered_actions", [])
        ]
        remaining_categories = {str(action.get("category", "")) for action in remaining if action}
        condition = {
            "case_id_prefix": "adaptive_",
            "fallback": "residual adaptive counterexample",
        }
        if len(remaining_categories) == 1:
            condition["triage_category"] = next(iter(remaining_categories))
        rules.append(
            {
                "id": "adaptive_residual_action_backstop",
                "type": "adaptive_policy_backstop",
                "condition": condition,
                "effect": {
                    "action": "require every residual adaptive counterexample to carry an explicit mitigation signal or become a release blocker",
                    "signals": ["adaptive-residual-backstop"],
                },
                "rationale": "The targeted adaptive patch did not cover all second-order actions, so residual adaptive cases are kept visible.",
                "confidence": 0.58,
                "covers": [_proof_attack_policy_action_ref(action) for action in remaining if action],
                "source": {
                    "from_policy": policy.get("policy_id", ""),
                    "adaptive_uncovered_actions": len(remaining),
                },
            }
        )
    return rules


def _adaptive_repair_label_tokens(actions: list[dict]) -> list[str]:
    tokens = []
    for action in actions:
        evidence = action.get("evidence") or {}
        label = str(evidence.get("label", ""))
        for token in ("Guide", "Reference", "Mirror", "Draft", "Semantic", "Bait"):
            if token in label and token not in tokens:
                tokens.append(token)
    return tokens or ["Guide", "Reference", "Mirror", "Draft"]


def _certificate_input(name: str, path: Path) -> dict:
    return {
        "name": name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _certificate_claim(claim_id: str, description: str, passed: bool, evidence: dict) -> dict:
    return {
        "id": claim_id,
        "description": description,
        "passed": bool(passed),
        "evidence": evidence,
        "evidence_hash": _stable_short_hash(evidence),
    }


def _proof_attack_scorecard_github_annotations(payload: dict) -> list[str]:
    if payload.get("status") == "pass":
        return [
            f"::notice title=Repo Agent adversarial proof attack scorecard::pass {int(payload.get('score', 0))}/100 grade {_escape_github_annotation(str(payload.get('grade', '')))}"
        ]
    annotations = []
    for item in payload.get("items", []):
        if item.get("passed"):
            continue
        item_id = _escape_github_annotation(str(item.get("id", "")))
        annotations.append(
            f"::error title=Repo Agent proof attack threshold failed::{item_id} is {float(item.get('value', 0.0)):.2%}, below {float(item.get('threshold', 0.0)):.2%}"
        )
    for case in payload.get("failed_cases", []):
        annotations.append(f"::error title=Repo Agent proof attack case failed::{_escape_github_annotation(_proof_attack_case_summary(case))}")
    for decoy in payload.get("unmitigated_decoys", []):
        annotations.append(
            f"::error title=Repo Agent proof attack decoy unmitigated::{_escape_github_annotation(str(decoy.get('case_id', '')))}: {_escape_github_annotation(str(decoy.get('label', '')))} reached rank 1"
        )
    return annotations


def _proof_attack_unmitigated_decoys(benchmark: dict) -> list[dict]:
    return [
        {"case_id": case.get("id", ""), **decoy}
        for case in benchmark.get("cases", [])
        for decoy in (case.get("defense_audit") or {}).get("decoys", [])
        if not bool(decoy.get("mitigated"))
    ]


def _proof_attack_weak_signal_decoys(benchmark: dict) -> list[dict]:
    return [
        {"case_id": case.get("id", ""), **decoy}
        for case in benchmark.get("cases", [])
        for decoy in (case.get("defense_audit") or {}).get("decoys", [])
        if bool(decoy.get("mitigated")) and not list(decoy.get("mitigation_signals") or [])
    ]


def _proof_attack_case_summary(case: dict) -> str:
    graph = dict((case.get("variants") or {}).get("graph_mcts") or {})
    proof = dict(case.get("proof") or {})
    return (
        f"{case.get('id', 'unknown_case')}: top={graph.get('top_hit', '')}, "
        f"proof={proof.get('proof_status', '')}/{proof.get('top_hit', '')}"
    )


def render_proof_attack_markdown(payload: dict) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Adversarial Proof Attack Benchmark",
        "",
        f"- Strategy: `{payload.get('strategy', '')}`",
        f"- Spec suite: `{(payload.get('spec') or {}).get('suite', '')}`",
        f"- Question: {payload.get('question', '')}",
        f"- Expected target: `{payload.get('expected', '')}`",
        f"- Cases: `{int(metrics.get('case_count', 0))}`",
        f"- Attack resistance: `{float(metrics.get('attack_resistance_rate', 0.0)):.2%}`",
        f"- Graph-MCTS Top-1: `{float(metrics.get('graph_mcts_top1_accuracy', 0.0)):.2%}`",
        f"- Graph-MCTS distractor@1: `{float(metrics.get('graph_mcts_distractor_top1_rate', 0.0)):.2%}`",
        f"- Proof proved rate: `{float(metrics.get('proof_proved_rate', 0.0)):.2%}`",
        f"- Route anchor rate: `{float(metrics.get('route_anchor_rate', 0.0)):.2%}`",
        f"- Generated decoy audit rate: `{float(metrics.get('generated_decoy_audit_rate', 0.0)):.2%}`",
        f"- Mitigated generated decoys: `{float(metrics.get('mitigated_decoy_rate', 0.0)):.2%}`",
        f"- Mitigation signal rate: `{float(metrics.get('mitigation_signal_rate', 0.0)):.2%}`",
        "",
        "| Case | Result | Graph-MCTS Top Hit | Distractor Rank | Proof | Audited Generated Decoy |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for case in payload.get("cases", []):
        graph = dict((case.get("variants") or {}).get("graph_mcts") or {})
        proof = dict(case.get("proof") or {})
        result = "PASS" if case.get("passed") else "FAIL"
        distractor_rank = graph.get("distractor_rank")
        lines.append(
            f"| `{case.get('id', '')}` | `{result}` | `{graph.get('top_hit', '')}` | "
            f"{distractor_rank if distractor_rank is not None else 'none'} | "
            f"`{proof.get('proof_status', '')}` / `{proof.get('top_hit', '')}` | "
            f"{bool(proof.get('generated_decoy_audited'))} |"
        )
    lines.extend(["", "## Variant Matrix", "", "| Case | " + " | ".join(payload.get("variants", [])) + " |"])
    lines.append("| --- | " + " | ".join(["---"] * len(payload.get("variants", []))) + " |")
    for case in payload.get("cases", []):
        cells = []
        for variant in payload.get("variants", []):
            item = dict((case.get("variants") or {}).get(variant) or {})
            rank = item.get("rank") if item.get("rank") is not None else "miss"
            distractor = item.get("distractor_rank") if item.get("distractor_rank") is not None else "none"
            cells.append(f"rank {rank}, decoy {distractor}: `{_markdown_cell(item.get('top_hit', '') or '<none>')}`")
        lines.append("| " + " | ".join([f"`{case.get('id', '')}`", *cells]) + " |")
    lines.extend(
        [
            "",
            "## Causal Defense Audit",
            "",
            "| Case | Decoy | Rank | Mitigated | Signals | Reasons |",
            "| --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for case in payload.get("cases", []):
        for decoy in (case.get("defense_audit") or {}).get("decoys", []):
            rank = decoy.get("rank")
            signals = ", ".join(f"`{item}`" for item in decoy.get("mitigation_signals", [])) or "`none`"
            reasons = _markdown_cell("; ".join(decoy.get("reasons", [])[:5]) or decoy.get("status", ""))
            lines.append(
                f"| `{case.get('id', '')}` | `{decoy.get('label', '')}` | "
                f"{rank if rank is not None else '>{}'.format(decoy.get('audit_top_k', 0))} | "
                f"{bool(decoy.get('mitigated'))} | {signals} | {reasons} |"
            )
    lines.append("")
    return "\n".join(lines)


def _evaluate_attack_variants(repo_index, distractors: list[str], *, top_k: int) -> dict[str, dict]:
    variants = {}
    for variant in ABLATION_VARIANTS:
        hits = _ablation_hits(repo_index, PROOF_DEMO_QUESTION, variant=variant, top_k=max(top_k, 18))
        variants[variant] = {
            "rank": _exact_label_rank(PROOF_ATTACK_EXPECTED_LABEL, hits),
            "distractor_rank": _attack_distractor_rank(distractors, hits),
            "top_hit": hits[0].chunk.source_label if hits else "",
            "top_hits": [hit.chunk.source_label for hit in hits[:top_k]],
        }
    return variants


def _evaluate_attack_defense_audit(repo_index, distractors: list[str], *, top_k: int) -> dict:
    audit_top_k = max(top_k, 18)
    hits = _ablation_hits(repo_index, PROOF_DEMO_QUESTION, variant="graph_mcts", top_k=audit_top_k)
    by_label = {hit.chunk.source_label: (rank, hit) for rank, hit in enumerate(hits, start=1)}
    decoys = []
    for name in distractors:
        label = f"server.js:{name}"
        item = by_label.get(label)
        rank = item[0] if item else None
        hit = item[1] if item else None
        reasons = list(hit.reasons) if hit else []
        signals = [
            reason
            for reason in reasons
            if reason in {"route-family conflict", "off-route writer decoy", "explicitly excluded by query"}
        ]
        decoys.append(
            {
                "label": label,
                "rank": rank,
                "score": round(hit.score, 2) if hit else 0.0,
                "audit_top_k": audit_top_k,
                "mitigated": rank != 1,
                "mitigation_signals": signals,
                "reasons": reasons,
                "status": "ranked_below_audit_window" if rank is None else "ranked",
            }
        )
    return {
        "strategy": "causal_defense_audit",
        "variant": "graph_mcts",
        "audit_top_k": audit_top_k,
        "decoys": decoys,
    }


def _evaluate_attack_proof(repo_index, distractors: list[str], *, top_k: int) -> dict:
    result = RepoAgent(repo_index).answer(PROOF_DEMO_QUESTION, top_k=top_k)
    proof = dict(result.proof or {})
    supporting_paths = list(proof.get("supporting_paths") or [])
    decoy_audit = list(proof.get("decoy_audit") or [])
    audited_candidates = {str(item.get("candidate", "")) for item in decoy_audit}
    generated_labels = {f"server.js:{name}" for name in distractors}
    return {
        "proof_status": proof.get("status", "unknown"),
        "top_hit": proof.get("top_hit", ""),
        "route_anchor_preserved": "/api/chat" in set(proof.get("route_literals") or []),
        "supporting_path_preserved": any(PROOF_ATTACK_EXPECTED_LABEL in list(item.get("path") or []) for item in supporting_paths),
        "decoy_audit_count": len(decoy_audit),
        "generated_decoy_audited": bool(generated_labels & audited_candidates),
        "generated_decoys": sorted(generated_labels),
        "audited_generated_decoys": sorted(generated_labels & audited_candidates),
    }


def _load_proof_attack_spec(spec_path: Path | None = None) -> dict:
    if spec_path is None:
        return {
            "schema_version": "1.0",
            "suite": "builtin-proof-attacks",
            "description": "Built-in adversarial proof attack cases.",
            "cases": [dict(item) for item in PROOF_ATTACK_CASES],
        }
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("proof attack spec must be a JSON object")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("proof attack spec must contain a non-empty cases list")
    normalized = []
    for raw_case in cases:
        if not isinstance(raw_case, dict):
            raise ValueError("proof attack spec cases must be JSON objects")
        case_id = _safe_slug(str(raw_case.get("id", "")))
        if not case_id:
            raise ValueError("proof attack spec case id is required")
        mutation = raw_case.get("mutation")
        if not isinstance(mutation, dict | str):
            raise ValueError(f"proof attack case {case_id} must define a mutation object")
        distractors = [str(item) for item in raw_case.get("distractors", [])]
        if not distractors:
            distractors = _distractors_from_mutation(mutation)
        normalized.append(
            {
                "id": case_id,
                "description": str(raw_case.get("description", "")),
                "threat_model": str(raw_case.get("threat_model", "")),
                "severity": str(raw_case.get("severity", "medium")),
                "tags": [str(item) for item in raw_case.get("tags", [])],
                "mutation": mutation,
                "distractors": distractors,
            }
        )
    return {
        "schema_version": str(payload.get("schema_version", "1.0")),
        "suite": str(payload.get("suite", spec_path.stem)),
        "description": str(payload.get("description", "")),
        "cases": normalized,
    }


def _apply_proof_attack_mutation(repo_dir: Path, mutation: str | dict) -> None:
    server_path = repo_dir / "server.js"
    source = server_path.read_text(encoding="utf-8")
    if isinstance(mutation, dict):
        injection = _render_proof_attack_mutation(mutation)
    elif mutation == "admin_shadow":
        injection = """

app.post('/api/admin/chat/shadow', handleAdminChatShadow);

function handleAdminChatShadow(req, res) {
  const replay = {
    event: 'chat.delta',
    payload: { token: 'public-looking-admin-shadow' },
  };
  return writeChatDeltaForAdminShadow(res, replay);
}

function writeChatDeltaForAdminShadow(res, replay) {
  res.write(`event: ${replay.event}\\n`);
  res.write(`data: ${JSON.stringify(replay.payload)}\\n\\n`);
  res.end();
}
"""
    elif mutation == "near_route_preview":
        injection = """

app.post('/api/chat-preview', handleChatPreview);

function handleChatPreview(req, res) {
  const frame = {
    event: 'chat.delta',
    payload: { token: 'preview-only' },
  };
  return writeChatDeltaPreview(res, frame);
}

function writeChatDeltaPreview(res, frame) {
  res.write(`event: ${frame.event}\\n`);
  res.write(`data: ${JSON.stringify(frame.payload)}\\n\\n`);
  res.end();
}
"""
    elif mutation == "documentation_bait":
        injection = """

function writeChatDeltaDocumentation() {
  return 'public /api/chat streamed token writer proof route handler final output';
}

function writePublicChatDeltaNotes() {
  return 'write chat delta stream response token event data for the public chat endpoint';
}
"""
    else:
        raise ValueError(f"unknown proof attack mutation: {mutation}")
    marker = "\nmodule.exports = {"
    if marker not in source:
        raise ValueError("server.js does not contain module.exports marker")
    server_path.write_text(source.replace(marker, injection + marker), encoding="utf-8")


def _render_proof_attack_mutation(mutation: dict) -> str:
    template = str(mutation.get("template", ""))
    if template == "route_writer_decoy":
        route = _safe_js_string(str(mutation.get("route", "")))
        handler = _safe_js_identifier(str(mutation.get("handler", "")))
        writer = _safe_js_identifier(str(mutation.get("writer", "")))
        event = _safe_js_string(str(mutation.get("event", "chat.delta")))
        token = _safe_js_string(str(mutation.get("token", "decoy")))
        payload_name = _safe_js_identifier(str(mutation.get("payload_name", "frame")))
        return f"""

app.post({json.dumps(route)}, {handler});

function {handler}(req, res) {{
  const {payload_name} = {{
    event: {json.dumps(event)},
    payload: {{ token: {json.dumps(token)} }},
  }};
  return {writer}(res, {payload_name});
}}

function {writer}(res, {payload_name}) {{
  res.write(`event: ${{{payload_name}.event}}\\n`);
  res.write(`data: ${{JSON.stringify({payload_name}.payload)}}\\n\\n`);
  res.end();
}}
"""
    if template == "documentation_bait":
        functions = mutation.get("functions")
        if not isinstance(functions, list) or not functions:
            raise ValueError("documentation_bait mutation requires functions")
        blocks = []
        for item in functions:
            if not isinstance(item, dict):
                raise ValueError("documentation_bait functions must be objects")
            name = _safe_js_identifier(str(item.get("name", "")))
            return_text = _safe_js_string(str(item.get("return_text", "")))
            blocks.append(
                f"""
function {name}() {{
  return {json.dumps(return_text)};
}}
"""
            )
        return "\n".join(blocks)
    raise ValueError(f"unknown proof attack mutation template: {template}")


def _distractors_from_mutation(mutation: str | dict) -> list[str]:
    if isinstance(mutation, str):
        for item in PROOF_ATTACK_CASES:
            if item.get("mutation") == mutation:
                return list(item.get("distractors") or [])
        return []
    template = str(mutation.get("template", ""))
    if template == "route_writer_decoy":
        return [str(mutation.get("writer", "")), str(mutation.get("handler", ""))]
    if template == "documentation_bait":
        return [str(item.get("name", "")) for item in mutation.get("functions", []) if isinstance(item, dict)]
    return []


def _safe_slug(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError(f"unsafe proof attack case id: {value}")
    return value


def _safe_js_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value):
        raise ValueError(f"unsafe JavaScript identifier in proof attack spec: {value}")
    return value


def _safe_js_string(value: str) -> str:
    if "\n" in value or "\r" in value or "`" in value:
        raise ValueError("proof attack spec strings must be single-line and must not contain backticks")
    return value


def _proof_attack_pressure_score(case: dict) -> int:
    variants = dict(case.get("variants") or {})
    ranks = [
        int(item.get("distractor_rank"))
        for item in variants.values()
        if isinstance(item, dict) and item.get("distractor_rank") is not None
    ]
    best_decoy_rank = min(ranks) if ranks else 99
    decoys = list((case.get("defense_audit") or {}).get("decoys") or [])
    proof = dict(case.get("proof") or {})
    score = 15
    score += max(0, 45 - (best_decoy_rank - 1) * 5)
    score += min(len(decoys) * 8, 20)
    score += sum(1 for item in decoys if not list(item.get("mitigation_signals") or [])) * 6
    if not proof.get("generated_decoy_audited"):
        score += 8
    if str(case.get("severity", "")).lower() == "high":
        score += 6
    return min(100, int(score))


def _proof_attack_defense_score(case: dict) -> int:
    decoys = list((case.get("defense_audit") or {}).get("decoys") or [])
    proof = dict(case.get("proof") or {})
    score = 0
    if case.get("passed"):
        score += 35
    if proof.get("proof_status") == "proved" and proof.get("top_hit") == PROOF_ATTACK_EXPECTED_LABEL:
        score += 25
    if proof.get("route_anchor_preserved") and proof.get("supporting_path_preserved"):
        score += 20
    if decoys and all(item.get("mitigated") for item in decoys):
        score += 10
    if decoys and any(item.get("mitigation_signals") for item in decoys):
        score += 10
    return min(100, int(score))


def _proof_attack_triage_action(
    case: dict,
    category: str,
    priority: str,
    diagnosis: str,
    suggested_guard: str,
    evidence: dict,
) -> dict:
    return {
        "case_id": case.get("id", ""),
        "category": category,
        "priority": priority,
        "severity": case.get("severity", "medium"),
        "tags": list(case.get("tags") or []),
        "threat_model": case.get("threat_model", ""),
        "attack_pressure": _proof_attack_pressure_score(case),
        "diagnosis": diagnosis,
        "suggested_guard": suggested_guard,
        "evidence": evidence,
        "evidence_hash": _stable_short_hash(evidence),
    }


def _triage_priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


def _stable_short_hash(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _exact_label_rank(expected_label: str, hits: list) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if hit.chunk.source_label == expected_label:
            return rank
    return None


def _attack_distractor_rank(distractors: list[str], hits: list) -> int | None:
    labels = {f"server.js:{item}".lower() for item in distractors}
    names = {item.lower() for item in distractors}
    for rank, hit in enumerate(hits, start=1):
        label = hit.chunk.source_label.lower()
        name = hit.chunk.symbol_name.lower()
        if label in labels or name in names:
            return rank
    return None


def run_counterfactual(
    runtime: RepoAgentRuntime,
    cases_path: Path,
    top_k: int = 6,
    json_output: bool = False,
    output_path: Path | None = None,
) -> None:
    payload = evaluate_counterfactual(runtime, cases_path, top_k=top_k)
    if output_path is not None:
        written = write_counterfactual_output(payload, output_path)
        payload["output_path"] = str(written)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("Counterfactual hard-negative benchmark")
    for variant, metrics in payload["metrics"].items():
        print(
            f"- {variant}: Top-1 {metrics['top1_accuracy']:.2%}, "
            f"Top-3 {metrics['top3_accuracy']:.2%}, "
            f"MRR {metrics['mrr']:.3f}, "
            f"distractor@1 {metrics['distractor_top1_rate']:.2%}"
        )
    if output_path is not None:
        print(f"Report: {payload['output_path']}")


def evaluate_counterfactual(runtime: RepoAgentRuntime, cases_path: Path, top_k: int = 6) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    records = []
    metric_buckets = {
        variant: {"top1": 0, "top3": 0, "rr": 0.0, "distractor_top1": 0}
        for variant in ABLATION_VARIANTS
    }
    for case in cases:
        repo_path = (cases_path.parent / case["repo"]).resolve()
        repo_index = runtime.load_index(repo_path, force_rebuild=True)
        variants: dict[str, dict] = {}
        for variant in ABLATION_VARIANTS:
            hits = _ablation_hits(repo_index, str(case["question"]), variant=variant, top_k=top_k)
            rank = _case_match_rank(case, hits)
            distractor_rank = _case_distractor_rank(case, hits)
            top_hit = hits[0].chunk.source_label if hits else ""
            variants[variant] = {
                "rank": rank,
                "distractor_rank": distractor_rank,
                "top_hit": top_hit,
                "top_hits": [hit.chunk.source_label for hit in hits[:top_k]],
                "passed_top1": rank == 1,
                "passed_top3": rank is not None and rank <= 3,
                "distractor_top1": distractor_rank == 1,
            }
            metric_buckets[variant]["top1"] += 1 if rank == 1 else 0
            metric_buckets[variant]["top3"] += 1 if rank is not None and rank <= 3 else 0
            metric_buckets[variant]["rr"] += (1 / rank) if rank else 0.0
            metric_buckets[variant]["distractor_top1"] += 1 if distractor_rank == 1 else 0
        records.append(
            {
                "name": case.get("name", ""),
                "question": case["question"],
                "repo": str(repo_path),
                "expected_path": case["expected_path"],
                "expected_symbol_contains": case.get("expected_symbol_contains", ""),
                "distractor_symbol_contains": case.get("distractor_symbol_contains", []),
                "variants": variants,
            }
        )

    total = max(len(records), 1)
    metrics = {
        variant: {
            "case_count": len(records),
            "top_k": top_k,
            "top1_accuracy": bucket["top1"] / total,
            "top3_accuracy": bucket["top3"] / total,
            "mrr": bucket["rr"] / total,
            "distractor_top1_rate": bucket["distractor_top1"] / total,
        }
        for variant, bucket in metric_buckets.items()
    }
    return {"variants": list(ABLATION_VARIANTS), "metrics": metrics, "cases": records}


def write_counterfactual_output(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".md":
        output_path.write_text(render_counterfactual_markdown(payload), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def render_counterfactual_markdown(payload: dict) -> str:
    lines = [
        "# Repo Agent Counterfactual Hard-Negative Report",
        "",
        "## Strategy Summary",
        "",
        "| Strategy | Top-1 | Top-3 | MRR | Distractor@1 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for variant in payload["variants"]:
        metrics = payload["metrics"][variant]
        lines.append(
            f"| {variant} | {metrics['top1_accuracy']:.2%} | "
            f"{metrics['top3_accuracy']:.2%} | {metrics['mrr']:.3f} | "
            f"{metrics['distractor_top1_rate']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Case Matrix",
            "",
            "| Case | Expected | Distractors | " + " | ".join(payload["variants"]) + " |",
            "| --- | --- | --- | " + " | ".join(["---"] * len(payload["variants"])) + " |",
        ]
    )
    for record in payload["cases"]:
        cells = []
        for variant in payload["variants"]:
            item = record["variants"][variant]
            rank = item["rank"] if item["rank"] is not None else "miss"
            distractor = item["distractor_rank"] if item["distractor_rank"] is not None else "none"
            cells.append(
                f"rank {rank}, decoy {distractor}: `{_markdown_cell(item['top_hit'] or '<none>')}`"
            )
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(record.get("name") or record["question"]),
                    f"`{_markdown_cell(record['expected_symbol_contains'] or record['expected_path'])}`",
                    _markdown_cell(", ".join(record.get("distractor_symbol_contains", []))),
                    *cells,
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def build_coordination_status(project_root: Path, *, stale_minutes: int = 120) -> dict:
    coordination_path = project_root / ".agents" / "coordination.md"
    text = coordination_path.read_text(encoding="utf-8") if coordination_path.is_file() else ""
    claims = _parse_coordination_claims(text)
    active_claims = [claim for claim in claims if str(claim.get("status", "")).lower() in {"active", "in_progress"}]
    git_status = _coordination_git_status(project_root)
    dirty_files = git_status.get("dirty_files", [])
    touched_claims = _claims_touching_dirty_files(active_claims, dirty_files)

    age_minutes = None
    updated_at = ""
    if coordination_path.exists():
        modified_at = datetime.fromtimestamp(coordination_path.stat().st_mtime, tz=UTC)
        age_minutes = round((datetime.now(UTC) - modified_at).total_seconds() / 60, 1)
        updated_at = modified_at.isoformat()

    warnings = []
    if not coordination_path.exists():
        warnings.append("coordination file missing")
    elif age_minutes is not None and age_minutes > max(1, stale_minutes):
        warnings.append(f"coordination file stale for {age_minutes:.1f} minutes")
    if not active_claims:
        warnings.append("no active claims recorded")
    if git_status.get("error"):
        warnings.append(f"git status unavailable: {git_status['error']}")
    conflicts = _coordination_claim_conflicts(active_claims)
    if conflicts:
        warnings.append(f"{len(conflicts)} active claim file overlap(s)")

    return {
        "schema_version": "1.0",
        "strategy": "multi_session_coordination_status",
        "coordination_file": str(coordination_path),
        "exists": coordination_path.exists(),
        "updated_at": updated_at,
        "age_minutes": age_minutes,
        "stale_minutes": stale_minutes,
        "is_stale": bool(age_minutes is not None and age_minutes > max(1, stale_minutes)),
        "branch": git_status.get("branch", ""),
        "dirty_file_count": len(dirty_files),
        "dirty_files": dirty_files,
        "claims": claims,
        "active_claims": active_claims,
        "claim_conflicts": conflicts,
        "claims_touching_dirty_files": touched_claims,
        "warnings": warnings,
        "recommended_next_steps": _coordination_next_steps(warnings, conflicts, touched_claims),
    }


def render_coordination_markdown(payload: dict) -> str:
    lines = [
        "# Repo Agent Coordination Status",
        "",
        f"- File: `{payload.get('coordination_file', '')}`",
        f"- Updated: `{payload.get('updated_at', '') or 'unknown'}`",
        f"- Age minutes: `{payload.get('age_minutes')}`",
        f"- Branch: `{payload.get('branch', '') or 'unknown'}`",
        f"- Dirty files: `{int(payload.get('dirty_file_count', 0))}`",
        f"- Active claims: `{len(payload.get('active_claims', []))}`",
    ]
    warnings = list(payload.get("warnings") or [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    active_claims = list(payload.get("active_claims") or [])
    if active_claims:
        lines.extend(["", "## Active Claims", "", "| Session | Focus | Files | Status |", "| --- | --- | --- | --- |"])
        for claim in active_claims:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(claim.get("session", "")),
                        _markdown_cell(claim.get("focus", "")),
                        _markdown_cell(", ".join(claim.get("claimed_files", []))),
                        _markdown_cell(claim.get("status", "")),
                    ]
                )
                + " |"
            )
    conflicts = list(payload.get("claim_conflicts") or [])
    if conflicts:
        lines.extend(["", "## Claim Overlaps", ""])
        for conflict in conflicts:
            lines.append(
                f"- `{conflict.get('file', '')}` claimed by "
                f"{', '.join('`' + item + '`' for item in conflict.get('sessions', []))}"
            )
    touched = list(payload.get("claims_touching_dirty_files") or [])
    if touched:
        lines.extend(["", "## Dirty Claimed Files", ""])
        for item in touched:
            lines.append(f"- `{item.get('file', '')}` touches `{item.get('claim_file', '')}` ({item.get('session', '')})")
    next_steps = list(payload.get("recommended_next_steps") or [])
    if next_steps:
        lines.extend(["", "## Next Steps", ""])
        for step in next_steps:
            lines.append(f"- {step}")
    lines.append("")
    return "\n".join(lines)


def _parse_coordination_claims(text: str) -> list[dict]:
    lines = text.splitlines()
    claims: list[dict] = []
    for index, line in enumerate(lines):
        cells = _split_markdown_row(line)
        if [cell.lower() for cell in cells[:4]] != ["session", "focus", "files claimed", "status"]:
            continue
        for row in lines[index + 2 :]:
            row_cells = _split_markdown_row(row)
            if len(row_cells) < 4:
                break
            claimed_files = [
                item.strip().strip("`")
                for item in re.split(r",|<br\s*/?>", row_cells[2])
                if item.strip().strip("`")
            ]
            claims.append(
                {
                    "session": row_cells[0],
                    "focus": row_cells[1],
                    "claimed_files": claimed_files,
                    "status": row_cells[3],
                }
            )
        break
    return claims


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if cells and all(set(cell) <= {"-", ":"} for cell in cells):
        return []
    return cells


def _coordination_git_status(project_root: Path) -> dict:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "status", "--short", "--branch"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"branch": "", "dirty_files": [], "error": str(exc)}
    if result.returncode != 0:
        return {"branch": "", "dirty_files": [], "error": (result.stderr or result.stdout).strip()}
    branch = ""
    dirty_files = []
    for line in result.stdout.splitlines():
        if line.startswith("## "):
            branch = line[3:].strip()
            continue
        if not line.strip():
            continue
        relpath = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in relpath:
            relpath = relpath.split(" -> ", 1)[1].strip()
        dirty_files.append(relpath.replace("\\", "/"))
    return {"branch": branch, "dirty_files": dirty_files, "error": ""}


def _coordination_claim_conflicts(active_claims: list[dict]) -> list[dict]:
    owners: dict[str, set[str]] = {}
    for claim in active_claims:
        session = str(claim.get("session", ""))
        for claimed_file in claim.get("claimed_files", []):
            normalized = _normalize_claim_path(claimed_file)
            if not normalized or normalized == "pending after baseline":
                continue
            owners.setdefault(normalized, set()).add(session)
    return [
        {"file": claimed_file, "sessions": sorted(sessions)}
        for claimed_file, sessions in sorted(owners.items())
        if len(sessions) > 1
    ]


def _claims_touching_dirty_files(active_claims: list[dict], dirty_files: list[str]) -> list[dict]:
    touched = []
    for dirty_file in dirty_files:
        normalized_dirty = _normalize_claim_path(dirty_file)
        for claim in active_claims:
            for claimed_file in claim.get("claimed_files", []):
                normalized_claim = _normalize_claim_path(claimed_file)
                if not normalized_claim or normalized_claim == "pending after baseline":
                    continue
                if normalized_dirty == normalized_claim or normalized_dirty.startswith(normalized_claim.rstrip("/") + "/"):
                    touched.append(
                        {
                            "file": dirty_file,
                            "session": claim.get("session", ""),
                            "claim_file": claimed_file,
                        }
                    )
    return touched


def _normalize_claim_path(value: str) -> str:
    return value.strip().strip("`").replace("\\", "/").lstrip("./")


def _coordination_next_steps(warnings: list[str], conflicts: list[dict], touched_claims: list[dict]) -> list[str]:
    if conflicts:
        return ["Resolve overlapping active claims before editing shared files."]
    if touched_claims:
        return ["Review dirty files that intersect active claims before starting a parallel workstream."]
    if warnings:
        return ["Refresh .agents/coordination.md with current claims and recent validation results."]
    return ["Coordination state is healthy; choose a narrow unclaimed workstream and record it before editing."]


def _print_engineering_result(result: dict, *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(result.get("answer", ""))
    print(f"\n[Run]\n- {result.get('run_id')}")
    print(f"- status={result.get('status')}")
    print(f"- execution_mode={result.get('execution_mode')}")
    print(f"- path={result.get('run_path')}")
    if result.get("workspace_root"):
        print(f"- workspace={result.get('workspace_root')}")
    verifier = result.get("verifier_result") or {}
    reviewer = result.get("reviewer_result") or {}
    if verifier:
        print(f"- verifier={verifier.get('status')} ({verifier.get('summary', '')})")
    if reviewer:
        print(f"- reviewer={reviewer.get('status')} risk={reviewer.get('risk_score')}")
    if result.get("changed_files"):
        print("\n[Changed Files]")
        for relpath in result["changed_files"]:
            print(f"- {relpath}")
    if result.get("verification"):
        print("\n[Verification]")
        for item in result["verification"][-4:]:
            print(f"- {item.get('command')} -> exit {item.get('exit_code')}")
    if result.get("review"):
        print(f"\n[Review]\n{result.get('review')}")
    if result.get("timeline"):
        print("\n[Timeline]")
        for item in result["timeline"][-8:]:
            print(
                f"- {item.get('step')}. {item.get('agent')} | "
                f"{item.get('phase')} | {item.get('status')} | {item.get('title')}"
            )


def _case_match_rank(case: dict, hits: list) -> int | None:
    expected_path = str(case["expected_path"]).replace("\\", "/")
    expected_symbol = str(case.get("expected_symbol_contains", "")).lower()
    for rank, hit in enumerate(hits, start=1):
        relpath = hit.chunk.relpath.replace("\\", "/")
        path_ok = expected_path in relpath
        symbol_ok = not expected_symbol or expected_symbol in hit.chunk.symbol_name.lower()
        if path_ok and symbol_ok:
            return rank
    return None


def _case_distractor_rank(case: dict, hits: list) -> int | None:
    distractors = [str(item).lower() for item in case.get("distractor_symbol_contains", []) if str(item)]
    if not distractors:
        return None
    for rank, hit in enumerate(hits, start=1):
        symbol = hit.chunk.symbol_name.lower()
        label = hit.chunk.source_label.lower()
        if any(distractor in symbol or distractor in label for distractor in distractors):
            return rank
    return None


def _markdown_cell(value: object) -> str:
    return str(value).replace("\\", "/").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
