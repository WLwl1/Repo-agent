from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import repo_agent.__main__ as main_module
from repo_agent.__main__ import (
    build_agent_frontier_ablation,
    build_agent_frontier_interactions,
    build_agent_frontier_stability,
    build_agent_artifact_review,
    build_artifact_provenance,
    build_agent_reliability_frontier,
    build_benchmark_adapter_template,
    build_benchmark_repair_card,
    build_release_pack,
    build_proof_attack_leaderboard,
    build_proof_attack_minimax_certificate,
    build_proof_attack_scorecard,
    build_proof_attack_triage,
    build_temporal_repair_scorecard,
    diagnose_benchmark_adapter,
    evaluate_counterfactual,
    _proof_attack_work_root,
    _remove_tree,
    render_benchmark_adapter_markdown,
    render_benchmark_diagnostics_markdown,
    render_benchmark_repair_card_markdown,
    render_benchmark_repair_compiler_markdown,
    render_benchmark_repair_implementation_markdown,
    render_benchmark_repair_synthesis_markdown,
    render_benchmark_repair_workbench_markdown,
    render_proof_attack_policy_markdown,
    render_adaptive_proof_attack_markdown,
    render_adaptive_policy_repair_markdown,
    render_agent_frontier_ablation_markdown,
    render_agent_frontier_interactions_markdown,
    render_agent_frontier_markdown,
    render_agent_frontier_stability_markdown,
    render_agent_artifact_review_markdown,
    render_artifact_provenance_markdown,
    render_proof_attack_cegar_markdown,
    render_proof_attack_minimax_certificate_markdown,
    render_proof_attack_scorecard_markdown,
    render_proof_attack_scorecard_sarif,
    render_proof_attack_leaderboard_markdown,
    render_proof_attack_triage_markdown,
    render_proof_attack_markdown,
    render_ablation_markdown,
    render_counterfactual_markdown,
    render_eval_markdown,
    render_release_pack_markdown,
    render_release_pack_verification_markdown,
    render_temporal_scorecard_markdown,
    render_temporal_scorecard_sarif,
    run_adaptive_proof_attack_curriculum,
    run_benchmark_adapter,
    run_proof_attack_cegar,
    run_proof_attack_benchmark,
    build_benchmark_repair_workbench,
    compile_benchmark_repair_interventions,
    synthesize_adaptive_policy_repair,
    synthesize_benchmark_repair_rules,
    synthesize_proof_attack_policy,
    verify_artifact_provenance,
    verify_benchmark_repair_implementation,
    verify_release_pack,
    write_ablation_output,
    write_counterfactual_output,
    write_eval_output,
    write_adaptive_proof_attack_output,
    write_adaptive_policy_repair_output,
    write_agent_frontier_ablation_output,
    write_agent_frontier_interactions_output,
    write_agent_frontier_output,
    write_agent_frontier_stability_output,
    write_agent_artifact_review_output,
    write_artifact_provenance_output,
    write_artifact_provenance_verification_output,
    write_benchmark_adapter_output,
    write_benchmark_diagnostics_output,
    write_benchmark_repair_card_output,
    write_benchmark_repair_compiler_output,
    write_benchmark_repair_implementation_output,
    write_benchmark_repair_synthesis_output,
    write_benchmark_repair_workbench_output,
    write_proof_attack_policy_output,
    write_proof_attack_cegar_output,
    write_proof_attack_minimax_certificate_output,
    write_proof_attack_output,
    write_proof_attack_leaderboard_output,
    write_proof_attack_scorecard_output,
    write_proof_attack_scorecard_sarif,
    write_proof_attack_triage_output,
    write_temporal_scorecard_output,
    write_temporal_scorecard_sarif,
)
from repo_agent.agent import RepoAgent
from repo_agent.indexer import build_index
from repo_agent.runtime import RepoAgentRuntime


def _payload() -> dict:
    return {
        "metrics": {
            "case_count": 1,
            "top_k": 6,
            "top1_accuracy": 1.0,
            "top3_accuracy": 1.0,
            "mrr": 1.0,
            "average_confidence": 0.82,
        },
        "cases": [
            {
                "question": "Where is the chat endpoint implemented?",
                "expected_path": "server.js",
                "rank": 1,
                "top_hit": "server.js:handleChat",
                "top_hits": ["server.js:handleChat"],
                "passed_top1": True,
                "passed_top3": True,
                "confidence": 0.82,
                "confidence_label": "high",
                "warnings": [],
            }
        ],
    }


def test_render_eval_markdown_includes_metrics_and_cases() -> None:
    text = render_eval_markdown(_payload())

    assert "# Repo Agent Evaluation Report" in text
    assert "Top-1 accuracy: 100.00%" in text
    assert "MRR: 1.000" in text
    assert "| PASS | 1 | high 0.82 | `server.js` | `server.js:handleChat` |" in text


def test_write_eval_output_uses_suffix_to_choose_format(tmp_path: Path) -> None:
    payload = _payload()
    json_path = write_eval_output(payload, tmp_path / "eval.json")
    md_path = write_eval_output(payload, tmp_path / "eval.md")

    assert json.loads(json_path.read_text(encoding="utf-8"))["metrics"]["case_count"] == 1
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Evaluation Report")


def test_render_ablation_markdown_includes_strategy_table() -> None:
    payload = {
        "variants": ["lexical", "semantic", "no_graph", "hybrid", "graph_mcts"],
        "metrics": {
            "lexical": {"top1_accuracy": 0.5, "top3_accuracy": 1.0, "mrr": 0.75},
            "semantic": {"top1_accuracy": 0.25, "top3_accuracy": 0.5, "mrr": 0.4},
            "no_graph": {"top1_accuracy": 0.75, "top3_accuracy": 1.0, "mrr": 0.85},
            "hybrid": {"top1_accuracy": 1.0, "top3_accuracy": 1.0, "mrr": 1.0},
            "graph_mcts": {"top1_accuracy": 1.0, "top3_accuracy": 1.0, "mrr": 1.0},
        },
        "cases": [
            {
                "question": "Where is the chat endpoint implemented?",
                "expected_path": "server.js",
                "variants": {
                    "lexical": {"rank": 2, "top_hit": "server.js:helper"},
                    "semantic": {"rank": None, "top_hit": ""},
                    "no_graph": {"rank": 1, "top_hit": "server.js:route"},
                    "hybrid": {"rank": 1, "top_hit": "server.js:route"},
                    "graph_mcts": {"rank": 1, "top_hit": "server.js:route"},
                },
            }
        ],
    }

    text = render_ablation_markdown(payload)

    assert "# Repo Agent Retrieval Ablation Report" in text
    assert "| hybrid | 100.00% | 100.00% | 1.000 |" in text
    assert "| Question | Expected | lexical | semantic | no_graph | hybrid | graph_mcts |" in text
    assert "rank miss: `<none>`" in text


def test_write_ablation_output_uses_suffix_to_choose_format(tmp_path: Path) -> None:
    payload = {
        "variants": ["hybrid"],
        "metrics": {"hybrid": {"top1_accuracy": 1.0, "top3_accuracy": 1.0, "mrr": 1.0}},
        "cases": [
            {
                "question": "Where?",
                "expected_path": "app.py",
                "variants": {"hybrid": {"rank": 1, "top_hit": "app.py:main"}},
            }
        ],
    }

    json_path = write_ablation_output(payload, tmp_path / "ablation.json")
    md_path = write_ablation_output(payload, tmp_path / "ablation.md")

    assert json.loads(json_path.read_text(encoding="utf-8"))["variants"] == ["hybrid"]
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Retrieval Ablation Report")


def test_render_counterfactual_markdown_includes_distractor_rate() -> None:
    payload = {
        "variants": ["lexical", "graph_mcts"],
        "metrics": {
            "lexical": {
                "top1_accuracy": 0.0,
                "top3_accuracy": 0.0,
                "mrr": 0.0,
                "distractor_top1_rate": 1.0,
            },
            "graph_mcts": {
                "top1_accuracy": 1.0,
                "top3_accuracy": 1.0,
                "mrr": 1.0,
                "distractor_top1_rate": 0.0,
            },
        },
        "cases": [
            {
                "name": "hard_case",
                "question": "Where?",
                "expected_path": "server.js",
                "expected_symbol_contains": "writeChatDelta",
                "distractor_symbol_contains": ["writeLegacyChatDelta"],
                "variants": {
                    "lexical": {"rank": None, "distractor_rank": 1, "top_hit": "server.js:writeLegacyChatDelta"},
                    "graph_mcts": {"rank": 1, "distractor_rank": None, "top_hit": "server.js:writeChatDelta"},
                },
            }
        ],
    }

    text = render_counterfactual_markdown(payload)

    assert "# Repo Agent Counterfactual Hard-Negative Report" in text
    assert "Distractor@1" in text
    assert "| graph_mcts | 100.00% | 100.00% | 1.000 | 0.00% |" in text
    assert "decoy 1" in text


def test_write_counterfactual_output_uses_suffix_to_choose_format(tmp_path: Path) -> None:
    payload = {
        "variants": ["graph_mcts"],
        "metrics": {
            "graph_mcts": {
                "top1_accuracy": 1.0,
                "top3_accuracy": 1.0,
                "mrr": 1.0,
                "distractor_top1_rate": 0.0,
            }
        },
        "cases": [],
    }

    json_path = write_counterfactual_output(payload, tmp_path / "counterfactual.json")
    md_path = write_counterfactual_output(payload, tmp_path / "counterfactual.md")

    assert json.loads(json_path.read_text(encoding="utf-8"))["variants"] == ["graph_mcts"]
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Counterfactual Hard-Negative Report")


def test_counterfactual_eval_proves_graph_mcts_resists_decoys() -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    payload = evaluate_counterfactual(runtime, Path("repo_agent/counterfactual_cases.json"), top_k=6)

    graph_metrics = payload["metrics"]["graph_mcts"]
    lexical_metrics = payload["metrics"]["lexical"]

    assert graph_metrics["top1_accuracy"] == 1.0
    assert graph_metrics["distractor_top1_rate"] == 0.0
    assert graph_metrics["mrr"] > lexical_metrics["mrr"]


def test_counterfactual_answer_carries_route_proof() -> None:
    repo_index = build_index(Path("examples/counterfactual_agent_app"))
    result = RepoAgent(repo_index).answer(
        "Which function finally writes streamed tokens for the public /api/chat endpoint?",
        top_k=6,
    )

    assert result.hits[0].chunk.source_label == "server.js:writeChatDelta"
    assert result.proof["status"] == "proved"
    assert "/api/chat" in result.proof["route_literals"]
    assert any("writeChatDelta" in " -> ".join(item["path"]) for item in result.proof["supporting_paths"])
    proof_graph = result.proof["proof_graph"]
    graph_node_roles = {
        node["id"]: set(node["roles"])
        for node in proof_graph["nodes"]
    }
    graph_edge_labels = {edge["label"] for edge in proof_graph["edges"]}

    assert "top_hit" in graph_node_roles["server.js:writeChatDelta"]
    assert "route_anchor" in graph_node_roles["/api/chat"]
    assert any("decoy" in roles for node_id, roles in graph_node_roles.items() if "admin" in node_id.lower() or "legacy" in node_id.lower())
    assert "route_path" in graph_edge_labels
    decoy_audit = result.proof["decoy_audit"]

    assert any("admin" in item["candidate"].lower() for item in decoy_audit)
    assert any("legacy" in item["candidate"].lower() for item in decoy_audit)
    assert all(item["rejected"] for item in decoy_audit)
    assert any("admin" in item["conflicting_roles"] for item in decoy_audit)
    assert any("/api/chat" in item["requested_routes"] for item in decoy_audit)


def test_benchmark_adapter_runs_portable_cross_repo_suite(tmp_path: Path) -> None:
    suite = {
        "schema_version": "1.0",
        "suite_id": "test-portable-suite",
        "name": "Test Portable Suite",
        "source": "unit-test",
        "description": "Small cross-repository suite for the benchmark adapter.",
        "cases": [
            {
                "id": "counterfactual_public_writer",
                "repo": str(Path.cwd() / "examples" / "counterfactual_agent_app"),
                "question": "Which function finally writes streamed tokens for the public /api/chat endpoint?",
                "expected_path": "server.js",
                "expected_symbol_contains": "writeChatDelta",
                "distractor_symbol_contains": ["writeAdminAuditEvent", "writeLegacyChatDelta"],
                "tags": ["express", "route-grounded", "writer"],
            },
            {
                "id": "fastapi_chat_route",
                "repo": str(Path.cwd() / "examples" / "simple_fastapi_app"),
                "question": "Where is the chat route implemented?",
                "expected_path": "app.py",
                "expected_symbol_contains": "post_api_chat",
                "tags": ["fastapi", "route-grounded", "handler"],
            },
        ],
    }
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")

    runtime = RepoAgentRuntime(Path.cwd())
    payload = run_benchmark_adapter(runtime, suite_path, top_k=6)
    markdown = render_benchmark_adapter_markdown(payload)
    json_path = write_benchmark_adapter_output(payload, tmp_path / "benchmark-adapter.json")
    md_path = write_benchmark_adapter_output(payload, tmp_path / "benchmark-adapter.md")
    template_path = write_benchmark_adapter_output(build_benchmark_adapter_template(), tmp_path / "template.json")
    cli_path = tmp_path / "cli-benchmark-adapter.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-adapter",
            "--suite",
            str(suite_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "portable_benchmark_adapter"
    assert payload["status"] == "pass"
    assert payload["metrics"]["case_count"] == 2
    assert payload["metrics"]["top3_accuracy"] == 1.0
    assert payload["metrics"]["distractor_top1_rate"] == 0.0
    assert len(payload["by_repo"]) == 2
    assert any(record["evidence_hash"] for record in payload["cases"])
    assert all("top_hit_reasons" in record for record in payload["cases"])
    assert "# Repo Agent Benchmark Adapter Report" in markdown
    assert "Generalization Gaps" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "pass"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Adapter Report")
    assert json.loads(template_path.read_text(encoding="utf-8"))["suite_id"] == "my-external-agent-benchmark"
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["strategy"] == "portable_benchmark_adapter"


def test_benchmark_adapter_passes_intent_guard_challenge_suite(tmp_path: Path) -> None:
    root = Path.cwd()
    suite = {
        "schema_version": "1.0",
        "suite_id": "intent-guard-challenge-suite",
        "source": "repo-agent-intent-guard-regression",
        "cases": [
            {
                "id": "authorization_middleware",
                "repo": str(root / "examples" / "counterfactual_agent_app"),
                "question": "Which middleware authorizes the public /api/chat route before the handler runs?",
                "expected_path": "server.js",
                "expected_symbol_contains": "authorizePublicChat",
                "distractor_symbol_contains": ["handlePublicChat"],
            },
            {
                "id": "sync_json_handler",
                "repo": str(root / "examples" / "simple_agent_app"),
                "question": "Which handler serves the synchronous JSON assistant route rather than the streaming chat route?",
                "expected_path": "server.js",
                "expected_symbol_contains": "handleAgentRequest",
                "distractor_symbol_contains": ["handleAgentStreamRequest"],
            },
            {
                "id": "clear_state_helper",
                "repo": str(root / "examples" / "simple_fastapi_app"),
                "question": "Which helper clears state for the FastAPI admin reset route?",
                "expected_path": "app.py",
                "expected_symbol_contains": "clear_state",
                "distractor_symbol_contains": ["run_chat", "load_session"],
            },
            {
                "id": "package_config",
                "repo": str(root),
                "question": "Where is package data configured so benchmark_adapter_suite.json ships with the Python package?",
                "expected_path": "pyproject.toml",
                "distractor_symbol_contains": ["README.md", "MANIFEST.in"],
            },
            {
                "id": "security_verification_policy",
                "repo": str(root),
                "question": "Which Python file defines the allow-list policy for safe verification commands?",
                "expected_path": "repo_agent/security.py",
                "distractor_symbol_contains": ["EngineeringAgent", "RepoTools", "workspace_tool"],
            },
            {
                "id": "apply_run_action",
                "repo": str(root),
                "question": "Which Web Studio function applies a persisted run workspace back to the source repository from the run history action?",
                "expected_path": "web/app.js",
                "expected_symbol_contains": "applyRun",
                "distractor_symbol_contains": ["refreshRuns", "renderRuns", "runEngineering"],
            },
        ],
    }
    suite_path = tmp_path / "intent-guard-suite.json"
    suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = run_benchmark_adapter(RepoAgentRuntime(root), suite_path, top_k=6)
    reasons_by_id = {case["id"]: case["top_hit_reasons"] for case in payload["cases"]}

    assert payload["status"] == "pass"
    assert payload["metrics"]["case_count"] == 6
    assert payload["metrics"]["top1_accuracy"] == 1.0
    assert payload["metrics"]["distractor_top1_rate"] == 0.0
    assert "authorization middleware target" in reasons_by_id["authorization_middleware"]
    assert "sync-json handler target" in reasons_by_id["sync_json_handler"]
    assert "clear-state helper target" in reasons_by_id["clear_state_helper"]
    assert "package data config target" in reasons_by_id["package_config"]
    assert "verification policy target" in reasons_by_id["security_verification_policy"]
    assert "apply-run action target" in reasons_by_id["apply_run_action"]


def test_benchmark_diagnostics_explain_recoverable_generalization_gaps(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark-adapter.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "portable_benchmark_adapter",
                "suite_id": "diagnostic-suite",
                "metrics": {
                    "case_count": 2,
                    "top_k": 6,
                    "top1_accuracy": 0.5,
                    "top3_accuracy": 1.0,
                    "mrr": 0.75,
                    "distractor_top1_rate": 0.0,
                    "average_confidence": 0.9,
                },
                "by_repo": [
                    {"repo": "repo-a", "case_count": 2, "top_k": 6, "top1_accuracy": 0.5, "top3_accuracy": 1.0, "mrr": 0.75, "distractor_top1_rate": 0.0, "average_confidence": 0.9}
                ],
                "by_tag": [
                    {"tag": "retrieval", "case_count": 1, "top_k": 6, "top1_accuracy": 0.0, "top3_accuracy": 1.0, "mrr": 0.5, "distractor_top1_rate": 0.0, "average_confidence": 0.88}
                ],
                "cases": [
                    {
                        "id": "library_retrieval_gap",
                        "repo_key": "repo-a",
                        "question": "Which function should be read first to understand retrieval?",
                        "expected_path": "lib/rag-store.js",
                        "expected_symbol_contains": "retrieve",
                        "tags": ["retrieval", "library"],
                        "rank": 2,
                        "distractor_rank": None,
                        "top_hit": "server.js:handleRagUpload",
                        "top_hits": ["server.js:handleRagUpload", "lib/rag-store.js:retrieve"],
                        "passed_top1": False,
                        "passed_top3": True,
                        "distractor_top1": False,
                        "confidence": 0.88,
                        "confidence_label": "high",
                        "warnings": [],
                        "evidence_hash": "abc123",
                    },
                    {
                        "id": "route_pass",
                        "repo_key": "repo-a",
                        "question": "Where is the route implemented?",
                        "expected_path": "app.py",
                        "expected_symbol_contains": "post_api_chat",
                        "tags": ["route-grounded"],
                        "rank": 1,
                        "distractor_rank": None,
                        "top_hit": "app.py:post_api_chat",
                        "top_hits": ["app.py:post_api_chat"],
                        "passed_top1": True,
                        "passed_top3": True,
                        "distractor_top1": False,
                        "confidence": 0.92,
                        "confidence_label": "high",
                        "warnings": [],
                        "evidence_hash": "def456",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = diagnose_benchmark_adapter(benchmark_path)
    markdown = render_benchmark_diagnostics_markdown(payload)
    json_path = write_benchmark_diagnostics_output(payload, tmp_path / "benchmark-diagnostics.json")
    md_path = write_benchmark_diagnostics_output(payload, tmp_path / "benchmark-diagnostics.md")
    cli_path = tmp_path / "cli-benchmark-diagnostics.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-diagnose",
            "--benchmark",
            str(benchmark_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "portable_benchmark_generalization_diagnostics"
    assert payload["status"] == "actionable"
    assert payload["summary"]["weak_case_count"] == 1
    assert payload["summary"]["blocker_count"] == 0
    assert payload["summary"]["projected_top1_accuracy"] == 1.0
    assert payload["case_diagnostics"][0]["taxonomy"] == ["hidden_symbol_query", "library_boundary_ambiguity", "top3_recoverable"]
    assert any(item["id"] == "promote_top3_expected_to_rank1" and item["affected_cases"] == 1 for item in payload["counterfactual_interventions"])
    assert "# Repo Agent Benchmark Generalization Diagnostics" in markdown
    assert "library_boundary_ambiguity" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "actionable"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Generalization Diagnostics")
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["blocker_count"] == 0


def test_benchmark_repair_card_validates_ranking_guards(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark-adapter.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "portable_benchmark_adapter",
                "suite_id": "repair-suite",
                "metrics": {
                    "case_count": 2,
                    "top_k": 6,
                    "top1_accuracy": 1.0,
                    "top3_accuracy": 1.0,
                    "mrr": 1.0,
                    "distractor_top1_rate": 0.0,
                    "average_confidence": 0.95,
                },
                "cases": [
                    {
                        "id": "streaming_fixed",
                        "tags": ["streaming", "handler"],
                        "rank": 1,
                        "top_hit": "server.js:handleAgentStreamRequest",
                        "top_hit_reasons": ["handler-function target", "streaming handler disambiguation"],
                        "evidence_hash": "stream123",
                    },
                    {
                        "id": "retrieval_fixed",
                        "tags": ["retrieval", "library"],
                        "rank": 1,
                        "top_hit": "lib/rag-store.js:retrieve",
                        "top_hit_reasons": ["retrieval helper target", "library boundary prior"],
                        "evidence_hash": "retrieve123",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_benchmark_repair_card(benchmark_path)
    markdown = render_benchmark_repair_card_markdown(payload)
    json_path = write_benchmark_repair_card_output(payload, tmp_path / "benchmark-repair-card.json")
    md_path = write_benchmark_repair_card_output(payload, tmp_path / "benchmark-repair-card.md")
    cli_path = tmp_path / "cli-benchmark-repair-card.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-repair-card",
            "--benchmark",
            str(benchmark_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "portable_benchmark_repair_card"
    assert payload["status"] == "validated"
    assert payload["summary"]["passed_guards"] == payload["summary"]["guard_count"] == 2
    assert payload["summary"]["repair_reason_case_count"] == 2
    assert "# Repo Agent Benchmark Repair Card" in markdown
    assert "streaming_handler_disambiguation" in markdown
    assert "retrieval_library_boundary_prior" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "validated"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Repair Card")
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["passed_guards"] == 2


def test_benchmark_repair_synthesizer_proposes_and_validates_rules(tmp_path: Path) -> None:
    weak_benchmark_path = tmp_path / "weak-benchmark-adapter.json"
    weak_benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "portable_benchmark_adapter",
                "suite_id": "weak-repair-suite",
                "metrics": {
                    "case_count": 2,
                    "top_k": 6,
                    "top1_accuracy": 0.5,
                    "top3_accuracy": 1.0,
                    "mrr": 0.75,
                    "distractor_top1_rate": 0.0,
                },
                "cases": [
                    {
                        "id": "rag_retrieval_weak",
                        "question": "Which function should be read first to understand the RAG retrieval flow?",
                        "expected_path": "lib/rag-store.js",
                        "expected_symbol_contains": "retrieve",
                        "tags": ["rag", "retrieval", "library"],
                        "rank": 2,
                        "top_hit": "server.js:handleRagUpload",
                        "top_hits": ["server.js:handleRagUpload", "lib/rag-store.js:retrieve"],
                        "top_hits_detail": [
                            {"rank": 1, "source_label": "server.js:handleRagUpload", "reasons": ["handler-function target"]},
                            {"rank": 2, "source_label": "lib/rag-store.js:retrieve", "reasons": ["semantic overlap"]},
                        ],
                        "evidence_hash": "weak123",
                    },
                    {
                        "id": "streaming_validated",
                        "question": "Which function handles the chat streaming request?",
                        "expected_path": "server.js",
                        "expected_symbol_contains": "handleAgentStreamRequest",
                        "tags": ["streaming", "handler"],
                        "rank": 1,
                        "top_hit": "server.js:handleAgentStreamRequest",
                        "top_hits": ["server.js:handleAgentStreamRequest"],
                        "top_hit_reasons": ["streaming handler disambiguation"],
                        "top_hits_detail": [
                            {"rank": 1, "source_label": "server.js:handleAgentStreamRequest", "reasons": ["streaming handler disambiguation"]},
                        ],
                        "evidence_hash": "stream123",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    validated_benchmark_path = tmp_path / "validated-benchmark-adapter.json"
    validated_benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "portable_benchmark_adapter",
                "suite_id": "validated-repair-suite",
                "metrics": {
                    "case_count": 2,
                    "top_k": 6,
                    "top1_accuracy": 1.0,
                    "top3_accuracy": 1.0,
                    "mrr": 1.0,
                    "distractor_top1_rate": 0.0,
                },
                "cases": [
                    {
                        "id": "streaming_validated",
                        "question": "Which function handles the chat streaming request?",
                        "expected_path": "server.js",
                        "expected_symbol_contains": "handleAgentStreamRequest",
                        "tags": ["streaming", "handler"],
                        "rank": 1,
                        "top_hit": "server.js:handleAgentStreamRequest",
                        "top_hit_reasons": ["streaming handler disambiguation"],
                        "top_hits_detail": [
                            {"rank": 1, "source_label": "server.js:handleAgentStreamRequest", "reasons": ["streaming handler disambiguation"]},
                        ],
                        "evidence_hash": "stream123",
                    },
                    {
                        "id": "retrieval_validated",
                        "question": "Which function should be read first to understand the RAG retrieval flow?",
                        "expected_path": "lib/rag-store.js",
                        "expected_symbol_contains": "retrieve",
                        "tags": ["rag", "retrieval", "library"],
                        "rank": 1,
                        "top_hit": "lib/rag-store.js:retrieve",
                        "top_hit_reasons": ["retrieval helper target", "library boundary prior"],
                        "top_hits_detail": [
                            {"rank": 1, "source_label": "lib/rag-store.js:retrieve", "reasons": ["retrieval helper target", "library boundary prior"]},
                        ],
                        "evidence_hash": "retrieve123",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    weak_payload = synthesize_benchmark_repair_rules(weak_benchmark_path)
    validated_payload = synthesize_benchmark_repair_rules(validated_benchmark_path)
    markdown = render_benchmark_repair_synthesis_markdown(weak_payload)
    json_path = write_benchmark_repair_synthesis_output(weak_payload, tmp_path / "benchmark-repair-synthesis.json")
    md_path = write_benchmark_repair_synthesis_output(weak_payload, tmp_path / "benchmark-repair-synthesis.md")
    cli_path = tmp_path / "cli-benchmark-repair-synthesis.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-repair-synthesize",
            "--benchmark",
            str(weak_benchmark_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert weak_payload["strategy"] == "counterexample_guided_retrieval_repair_synthesis"
    assert weak_payload["status"] == "repair_plan"
    assert weak_payload["summary"]["proposed_rule_count"] >= 1
    assert weak_payload["simulated_metrics"]["top1_accuracy"] == 1.0
    assert any(item["id"] == "prefer_retrieval_library_boundary" and item["status"] == "proposed" for item in weak_payload["rules"])
    assert validated_payload["status"] == "validated"
    assert validated_payload["summary"]["validated_rule_count"] >= 2
    assert "# Repo Agent Benchmark Repair Synthesizer" in markdown
    assert "prefer_retrieval_library_boundary" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "repair_plan"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Repair Synthesizer")
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["simulated_metrics"]["top1_accuracy"] == 1.0


def test_benchmark_repair_implementation_verifier_maps_rules_to_source(tmp_path: Path) -> None:
    synthesis_path = tmp_path / "benchmark-repair-synthesis.json"
    synthesis_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "counterexample_guided_retrieval_repair_synthesis",
                "suite_id": "implementation-suite",
                "rules": [
                    {
                        "id": "promote_streaming_handler_intent",
                        "family": "intent_disambiguation",
                        "status": "validated",
                    },
                    {
                        "id": "prefer_retrieval_library_boundary",
                        "family": "module_boundary_prior",
                        "status": "validated",
                    },
                    {
                        "id": "demote_rank1_hard_negative",
                        "family": "counterexample_guard",
                        "status": "dormant",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "indexer.py"
    source_path.write_text(
        "\n".join(
            [
                "STREAM_QUERY_TERMS = ('stream',)",
                "RETRIEVAL_QUERY_TERMS = ('retrieval',)",
                "READ_FIRST_QUERY_TERMS = ('read first',)",
                "def _asks_for_streaming(query): pass",
                "def _chunk_matches_streaming_intent(chunk): pass",
                "def _asks_for_retrieval_boundary(query): pass",
                "def _chunk_is_library_boundary(chunk): pass",
                "reasons = reasons + ['streaming handler disambiguation']",
                "reasons = reasons + ['retrieval helper target']",
                "reasons = reasons + ['library boundary prior']",
                "reasons = reasons + ['entry handler boundary detour']",
            ]
        ),
        encoding="utf-8",
    )

    payload = verify_benchmark_repair_implementation(synthesis_path, source_path=source_path)
    markdown = render_benchmark_repair_implementation_markdown(payload)
    json_path = write_benchmark_repair_implementation_output(payload, tmp_path / "benchmark-repair-implementation.json")
    md_path = write_benchmark_repair_implementation_output(payload, tmp_path / "benchmark-repair-implementation.md")
    cli_path = tmp_path / "cli-benchmark-repair-implementation.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-repair-verify-implementation",
            "--synthesis",
            str(synthesis_path),
            "--source",
            str(source_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "counterexample_guided_retrieval_repair_implementation_verification"
    assert payload["status"] == "verified"
    assert payload["summary"]["implemented_validated_rule_count"] == 2
    assert payload["summary"]["missing_validated_rule_count"] == 0
    assert "# Repo Agent Benchmark Repair Implementation Verification" in markdown
    assert "promote_streaming_handler_intent" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "verified"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Repair Implementation Verification")
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["implemented_validated_rule_count"] == 2


def test_benchmark_repair_compiler_emits_intervention_ir(tmp_path: Path) -> None:
    synthesis_path = tmp_path / "benchmark-repair-synthesis.json"
    synthesis_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "counterexample_guided_retrieval_repair_synthesis",
                "suite_id": "compiler-suite",
                "rules": [
                    {
                        "id": "promote_streaming_handler_intent",
                        "family": "intent_disambiguation",
                        "status": "validated",
                        "validated_case_ids": ["stream_case"],
                    },
                    {
                        "id": "prefer_retrieval_library_boundary",
                        "family": "module_boundary_prior",
                        "status": "proposed",
                        "affected_case_ids": ["retrieval_case"],
                    },
                    {
                        "id": "demote_rank1_hard_negative",
                        "family": "counterexample_guard",
                        "status": "dormant",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    implementation_path = tmp_path / "benchmark-repair-implementation.json"
    implementation_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "counterexample_guided_retrieval_repair_implementation_verification",
                "rules": [
                    {
                        "id": "promote_streaming_handler_intent",
                        "implementation_status": "implemented",
                        "anchors": [{"term": "_asks_for_streaming", "found": True, "line": 10}],
                        "reasons": [{"term": "streaming handler disambiguation", "found": True, "line": 20}],
                    },
                    {
                        "id": "prefer_retrieval_library_boundary",
                        "implementation_status": "patch_required",
                        "anchors": [],
                        "reasons": [],
                    },
                    {
                        "id": "demote_rank1_hard_negative",
                        "implementation_status": "advisory",
                        "anchors": [],
                        "reasons": [],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "indexer.py"
    source_path.write_text("def _rerank_multistep():\n    pass\n", encoding="utf-8")

    payload = compile_benchmark_repair_interventions(
        synthesis_path,
        implementation_path=implementation_path,
        source_path=source_path,
    )
    markdown = render_benchmark_repair_compiler_markdown(payload)
    json_path = write_benchmark_repair_compiler_output(payload, tmp_path / "benchmark-repair-compiler.json")
    md_path = write_benchmark_repair_compiler_output(payload, tmp_path / "benchmark-repair-compiler.md")
    cli_path = tmp_path / "cli-benchmark-repair-compiler.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-repair-compile",
            "--synthesis",
            str(synthesis_path),
            "--implementation",
            str(implementation_path),
            "--source",
            str(source_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    actions = {item["rule_id"]: item["action"] for item in payload["interventions"]}
    assert payload["strategy"] == "benchmark_repair_rule_compiler"
    assert payload["status"] == "patch_plan_ready"
    assert payload["summary"]["regression_lock_count"] == 1
    assert payload["summary"]["patch_required_count"] == 1
    assert payload["summary"]["ablation_toggle_count"] >= 2
    assert actions["promote_streaming_handler_intent"] == "lock_regression"
    assert actions["prefer_retrieval_library_boundary"] == "apply_patch"
    assert "# Repo Agent Benchmark Repair Compiler" in markdown
    assert "Ablation Toggles" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "patch_plan_ready"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Repair Compiler")
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["patch_required_count"] == 1


def test_benchmark_repair_workbench_generates_patch_candidates(tmp_path: Path) -> None:
    compiler_path = tmp_path / "benchmark-repair-compiler.json"
    compiler_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "benchmark_repair_rule_compiler",
                "suite_id": "workbench-suite",
                "summary": {"ablation_toggle_count": 1},
                "interventions": [
                    {
                        "rule_id": "promote_streaming_handler_intent",
                        "family": "intent_disambiguation",
                        "action": "lock_regression",
                        "implementation_status": "implemented",
                        "target_functions": ["_rerank_multistep"],
                        "guard_conditions": ["query contains stream intent"],
                        "score_effects": ["boost matching handler"],
                        "reason_literals": ["streaming handler disambiguation"],
                        "ablation_toggles": [
                            {
                                "id": "ablate_promote_streaming_handler_intent_streaming_handler_disambiguation",
                                "rule_id": "promote_streaming_handler_intent",
                                "disable_reason_literal": "streaming handler disambiguation",
                                "expected_effect": "Top-1 should not improve.",
                            }
                        ],
                        "validation_commands": ["python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json"],
                        "rollback_condition": "Revert the ablation.",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    source_path = tmp_path / "indexer.py"
    source_path.write_text(
        "\n".join(
            [
                "def _rerank_multistep():",
                "    reasons = reasons + ['streaming handler disambiguation']",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_benchmark_repair_workbench(compiler_path, source_path=source_path)
    markdown = render_benchmark_repair_workbench_markdown(payload)
    json_path = write_benchmark_repair_workbench_output(payload, tmp_path / "benchmark-repair-workbench.json")
    md_path = write_benchmark_repair_workbench_output(payload, tmp_path / "benchmark-repair-workbench.md")
    cli_path = tmp_path / "cli-benchmark-repair-workbench.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-repair-workbench",
            "--compiler",
            str(compiler_path),
            "--source",
            str(source_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "benchmark_repair_patch_workbench"
    assert payload["status"] == "patch_workbench_ready"
    assert payload["summary"]["patch_candidate_count"] == 1
    assert payload["summary"]["review_apply_patch_count"] == 1
    assert payload["summary"]["experiment_count"] == 1
    assert payload["patch_candidates"][0]["source_line"] == 2
    assert "ABLATION_DISABLED_streaming_handler_disambiguation" in payload["patch_candidates"][0]["diff"]
    assert "# Repo Agent Benchmark Repair Workbench" in markdown
    assert "Candidate Diffs" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "patch_workbench_ready"
    assert md_path.read_text(encoding="utf-8").startswith("# Repo Agent Benchmark Repair Workbench")
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["review_apply_patch_count"] == 1


def test_render_proof_attack_markdown_includes_resistance_metrics() -> None:
    payload = {
        "strategy": "adversarial_proof_attack_benchmark",
        "question": "Where?",
        "expected": "server.js:writeChatDelta",
        "variants": ["lexical", "graph_mcts"],
        "metrics": {
            "case_count": 1,
            "attack_resistance_rate": 1.0,
            "graph_mcts_top1_accuracy": 1.0,
            "graph_mcts_distractor_top1_rate": 0.0,
            "proof_proved_rate": 1.0,
            "route_anchor_rate": 1.0,
            "generated_decoy_audit_rate": 1.0,
            "mitigated_decoy_rate": 1.0,
            "mitigation_signal_rate": 1.0,
        },
        "cases": [
            {
                "id": "attack",
                "passed": True,
                "variants": {
                    "lexical": {"rank": 2, "distractor_rank": 1, "top_hit": "server.js:decoy"},
                    "graph_mcts": {"rank": 1, "distractor_rank": None, "top_hit": "server.js:writeChatDelta"},
                },
                "proof": {
                    "proof_status": "proved",
                    "top_hit": "server.js:writeChatDelta",
                    "generated_decoy_audited": True,
                },
                "defense_audit": {
                    "decoys": [
                        {
                            "label": "server.js:decoy",
                            "rank": 2,
                            "audit_top_k": 18,
                            "mitigated": True,
                            "mitigation_signals": ["route-family conflict"],
                            "reasons": ["route-family conflict"],
                        }
                    ]
                },
            }
        ],
    }

    text = render_proof_attack_markdown(payload)

    assert "# Repo Agent Adversarial Proof Attack Benchmark" in text
    assert "Attack resistance: `100.00%`" in text
    assert "## Causal Defense Audit" in text
    assert "`route-family conflict`" in text
    assert "rank 2, decoy 1" in text


def test_proof_attack_benchmark_resists_generated_decoys(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    output_path = write_proof_attack_output(payload, tmp_path / "proof-attack.md")

    assert payload["strategy"] == "adversarial_proof_attack_benchmark"
    assert payload["metrics"]["case_count"] == 3
    assert payload["metrics"]["graph_mcts_top1_accuracy"] == 1.0
    assert payload["metrics"]["graph_mcts_distractor_top1_rate"] == 0.0
    assert payload["metrics"]["proof_proved_rate"] == 1.0
    assert payload["metrics"]["route_anchor_rate"] == 1.0
    assert payload["metrics"]["supporting_path_rate"] == 1.0
    assert payload["metrics"]["attack_resistance_rate"] == 1.0
    assert payload["metrics"]["generated_decoy_count"] == 6
    assert payload["metrics"]["mitigated_decoy_rate"] == 1.0
    assert payload["metrics"]["mitigation_signal_rate"] > 0.0
    assert any(
        decoy["mitigation_signals"]
        for case in payload["cases"]
        for decoy in case["defense_audit"]["decoys"]
    )
    assert all(case["proof"]["top_hit"] == "server.js:writeChatDelta" for case in payload["cases"])
    assert output_path.is_file()


def test_proof_attack_work_root_is_isolated_by_output_dir(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    first = _proof_attack_work_root(runtime, tmp_path / "release-a" / "proof-attack")
    second = _proof_attack_work_root(runtime, tmp_path / "release-b" / "proof-attack")
    first_again = _proof_attack_work_root(runtime, tmp_path / "release-a" / "proof-attack")

    assert first == first_again
    assert first != second
    assert first.parent == Path.cwd() / "test-workspaces"
    assert first.name.startswith("_proof-attack-benchmark-")


def test_proof_attack_spec_drives_custom_mutations_and_leaderboard(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    spec_path = tmp_path / "proof-attack-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "suite": "custom-red-team-suite",
                "cases": [
                    {
                        "id": "tenant_shadow_writer",
                        "description": "Tenant-scoped route decoy with public chat vocabulary.",
                        "threat_model": "tenant route with misleading stream writer name",
                        "severity": "high",
                        "tags": ["tenant", "route-family"],
                        "mutation": {
                            "template": "route_writer_decoy",
                            "route": "/api/tenant/chat/shadow",
                            "handler": "handleTenantChatShadow",
                            "writer": "writeTenantChatDeltaShadow",
                            "event": "chat.delta",
                            "token": "tenant-shadow",
                            "payload_name": "shadow",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6, spec_path=spec_path)
    benchmark_path = write_proof_attack_output(payload, tmp_path / "proof-attack.json")
    leaderboard = build_proof_attack_leaderboard(benchmark_path)
    markdown = render_proof_attack_leaderboard_markdown(leaderboard)
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard, tmp_path / "proof-attack-leaderboard.md")
    cli_path = tmp_path / "proof-attack-leaderboard.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-leaderboard",
            "--benchmark",
            str(benchmark_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["spec"]["suite"] == "custom-red-team-suite"
    assert payload["metrics"]["case_count"] == 1
    assert payload["cases"][0]["id"] == "tenant_shadow_writer"
    assert payload["cases"][0]["distractors"] == ["writeTenantChatDeltaShadow", "handleTenantChatShadow"]
    assert payload["cases"][0]["passed"] is True
    assert leaderboard["case_count"] == 1
    assert leaderboard["hardest_case"] == "tenant_shadow_writer"
    assert leaderboard["rows"][0]["attack_pressure"] > 0
    assert "# Repo Agent Adversarial Proof Attack Leaderboard" in markdown
    assert leaderboard_path.is_file()
    assert result.returncode == 0
    assert cli_path.is_file()


def test_proof_attack_triage_turns_weak_signals_into_hardening_actions(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    benchmark_payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    benchmark_path = write_proof_attack_output(benchmark_payload, tmp_path / "proof-attack.json")
    leaderboard = build_proof_attack_leaderboard(benchmark_path)
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard, tmp_path / "proof-attack-leaderboard.json")

    payload = build_proof_attack_triage(benchmark_path, leaderboard_path=leaderboard_path)
    markdown = render_proof_attack_triage_markdown(payload)
    output_path = write_proof_attack_triage_output(payload, tmp_path / "proof-attack-triage.md")
    cli_path = tmp_path / "proof-attack-triage.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-triage",
            "--benchmark",
            str(benchmark_path),
            "--leaderboard",
            str(leaderboard_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["status"] == "needs_hardening"
    assert payload["action_count"] >= 3
    assert payload["priority_counts"]["P0"] == 0
    assert payload["priority_counts"]["P1"] >= 1
    assert any(action["category"] == "weak_signal_decoy" for action in payload["actions"])
    assert any(action["category"] == "high_pressure_attack" for action in payload["actions"])
    assert all(len(action["evidence_hash"]) == 12 for action in payload["actions"])
    assert "# Repo Agent Adversarial Proof Attack Triage" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert cli_path.is_file()


def test_proof_attack_policy_synthesizes_rules_from_counterexamples(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    benchmark_payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    benchmark_path = write_proof_attack_output(benchmark_payload, tmp_path / "proof-attack.json")
    leaderboard = build_proof_attack_leaderboard(benchmark_path)
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard, tmp_path / "proof-attack-leaderboard.json")
    triage = build_proof_attack_triage(benchmark_path, leaderboard_path=leaderboard_path)
    triage_path = write_proof_attack_triage_output(triage, tmp_path / "proof-attack-triage.json")

    payload = synthesize_proof_attack_policy(benchmark_path, leaderboard_path=leaderboard_path, triage_path=triage_path)
    markdown = render_proof_attack_policy_markdown(payload)
    output_path = write_proof_attack_policy_output(payload, tmp_path / "proof-attack-policy.md")
    cli_path = tmp_path / "proof-attack-policy.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-policy",
            "--benchmark",
            str(benchmark_path),
            "--leaderboard",
            str(leaderboard_path),
            "--triage",
            str(triage_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "adversarial_proof_attack_policy_synthesis"
    assert payload["status"] == "policy_converges"
    assert payload["rule_count"] >= 3
    assert payload["simulation"]["coverage_rate"] == 1.0
    assert payload["simulation"]["after"]["uncovered_action_count"] == 0
    assert payload["simulation"]["after"]["expected_mitigation_signal_rate"] == 1.0
    assert {rule["id"] for rule in payload["rules"]}.issuperset(
        {"audit_generated_decoys", "documentation_bait_signal", "pin_high_pressure_counterexamples"}
    )
    assert all(item["covered_by"] for item in payload["counterexamples"])
    assert "# Repo Agent Proof Attack Defense Policy Synthesis" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["status"] == payload["status"]


def test_adaptive_proof_attack_curriculum_stresses_synthesized_policy(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    benchmark_payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    benchmark_path = write_proof_attack_output(benchmark_payload, tmp_path / "proof-attack.json")
    leaderboard = build_proof_attack_leaderboard(benchmark_path)
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard, tmp_path / "proof-attack-leaderboard.json")
    triage = build_proof_attack_triage(benchmark_path, leaderboard_path=leaderboard_path)
    triage_path = write_proof_attack_triage_output(triage, tmp_path / "proof-attack-triage.json")
    policy = synthesize_proof_attack_policy(benchmark_path, leaderboard_path=leaderboard_path, triage_path=triage_path)
    policy_path = write_proof_attack_policy_output(policy, tmp_path / "proof-attack-policy.json")

    payload = run_adaptive_proof_attack_curriculum(
        runtime,
        baseline_benchmark_path=benchmark_path,
        policy_path=policy_path,
        output_dir=tmp_path / "proof-attack-adaptive",
        top_k=6,
    )
    markdown = render_adaptive_proof_attack_markdown(payload)
    output_path = write_adaptive_proof_attack_output(payload, tmp_path / "proof-attack-adaptive.md")
    artifact_names = {item["name"] for item in payload["artifacts"]}
    cli_path = tmp_path / "proof-attack-adaptive.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-adaptive",
            "--benchmark",
            str(benchmark_path),
            "--policy",
            str(policy_path),
            "--output-dir",
            str(tmp_path / "proof-attack-adaptive-cli"),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "adaptive_proof_attack_curriculum"
    assert payload["status"] == "adaptive_gap_found"
    assert payload["case_count"] >= 3
    assert payload["metrics"]["policy_coverage_rate"] < 1.0
    assert payload["metrics"]["policy_uncovered_actions"] >= 1
    assert any(case["targets_rule"] == "documentation_bait_signal" for case in payload["adaptive_cases"])
    assert any(action["case_id"] == "adaptive_semantic_bait_writer" for action in payload["policy_evaluation"]["uncovered_actions"])
    assert {
        "proof_attack_adaptive_spec",
        "proof_attack_adaptive_benchmark_json",
        "proof_attack_adaptive_triage",
    }.issubset(artifact_names)
    assert "# Repo Agent Adaptive Proof Attack Curriculum" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["status"] == payload["status"]


def test_adaptive_policy_repair_closes_second_order_gaps(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    benchmark_payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    benchmark_path = write_proof_attack_output(benchmark_payload, tmp_path / "proof-attack.json")
    leaderboard = build_proof_attack_leaderboard(benchmark_path)
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard, tmp_path / "proof-attack-leaderboard.json")
    triage = build_proof_attack_triage(benchmark_path, leaderboard_path=leaderboard_path)
    triage_path = write_proof_attack_triage_output(triage, tmp_path / "proof-attack-triage.json")
    policy = synthesize_proof_attack_policy(benchmark_path, leaderboard_path=leaderboard_path, triage_path=triage_path)
    policy_path = write_proof_attack_policy_output(policy, tmp_path / "proof-attack-policy.json")
    adaptive = run_adaptive_proof_attack_curriculum(
        runtime,
        baseline_benchmark_path=benchmark_path,
        policy_path=policy_path,
        output_dir=tmp_path / "proof-attack-adaptive",
        top_k=6,
    )
    adaptive_path = write_adaptive_proof_attack_output(adaptive, tmp_path / "proof-attack-adaptive.json")

    payload = synthesize_adaptive_policy_repair(policy_path=policy_path, adaptive_path=adaptive_path)
    markdown = render_adaptive_policy_repair_markdown(payload)
    output_path = write_adaptive_policy_repair_output(payload, tmp_path / "proof-attack-repair.md")
    cli_path = tmp_path / "proof-attack-repair.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-repair",
            "--policy",
            str(policy_path),
            "--adaptive",
            str(adaptive_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "adaptive_proof_attack_policy_repair"
    assert payload["status"] == "repair_converges"
    assert payload["patch_rule_count"] >= 1
    assert payload["before"]["coverage_rate"] < 1.0
    assert payload["after"]["coverage_rate"] == 1.0
    assert payload["after"]["uncovered_action_count"] == 0
    assert payload["coverage_delta"] > 0
    assert payload["residual_delta"] < 0
    assert any(rule["id"] == "adaptive_weak_signal_generalization" for rule in payload["patch_rules"])
    assert "# Repo Agent Adaptive Policy Repair" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["status"] == payload["status"]


def test_proof_attack_minimax_certificate_audits_repair_loop(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    benchmark_payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    benchmark_path = write_proof_attack_output(benchmark_payload, tmp_path / "proof-attack.json")
    leaderboard = build_proof_attack_leaderboard(benchmark_path)
    leaderboard_path = write_proof_attack_leaderboard_output(leaderboard, tmp_path / "proof-attack-leaderboard.json")
    triage = build_proof_attack_triage(benchmark_path, leaderboard_path=leaderboard_path)
    triage_path = write_proof_attack_triage_output(triage, tmp_path / "proof-attack-triage.json")
    policy = synthesize_proof_attack_policy(benchmark_path, leaderboard_path=leaderboard_path, triage_path=triage_path)
    policy_path = write_proof_attack_policy_output(policy, tmp_path / "proof-attack-policy.json")
    adaptive = run_adaptive_proof_attack_curriculum(
        runtime,
        baseline_benchmark_path=benchmark_path,
        policy_path=policy_path,
        output_dir=tmp_path / "proof-attack-adaptive",
        top_k=6,
    )
    adaptive_path = write_adaptive_proof_attack_output(adaptive, tmp_path / "proof-attack-adaptive.json")
    repair = synthesize_adaptive_policy_repair(policy_path=policy_path, adaptive_path=adaptive_path)
    repair_path = write_adaptive_policy_repair_output(repair, tmp_path / "proof-attack-repair.json")

    payload = build_proof_attack_minimax_certificate(
        benchmark_path=benchmark_path,
        policy_path=policy_path,
        adaptive_path=adaptive_path,
        repair_path=repair_path,
    )
    markdown = render_proof_attack_minimax_certificate_markdown(payload)
    output_path = write_proof_attack_minimax_certificate_output(payload, tmp_path / "proof-attack-certificate.md")
    cli_path = tmp_path / "proof-attack-certificate.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-certificate",
            "--benchmark",
            str(benchmark_path),
            "--policy",
            str(policy_path),
            "--adaptive",
            str(adaptive_path),
            "--repair",
            str(repair_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "proof_attack_minimax_certificate"
    assert payload["status"] == "accepted"
    assert payload["score"] == 100
    assert payload["grade"] == "A"
    assert len(payload["claims"]) == 5
    assert all(claim["passed"] for claim in payload["claims"])
    assert len(payload["inputs"]) == 4
    assert all(len(item["sha256"]) == 64 for item in payload["inputs"])
    assert payload["metrics"]["baseline_attack_resistance"] == 1.0
    assert payload["metrics"]["policy_coverage"] == 1.0
    assert payload["metrics"]["adaptive_policy_coverage"] < 1.0
    assert payload["metrics"]["repair_coverage"] == 1.0
    assert "# Repo Agent Proof Attack Minimax Certificate" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["status"] == payload["status"]


def test_proof_attack_scorecard_grades_generated_attacks(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    benchmark_payload = run_proof_attack_benchmark(runtime, output_dir=tmp_path / "proof-attack", top_k=6)
    benchmark_path = write_proof_attack_output(benchmark_payload, tmp_path / "proof-attack.json")

    payload = build_proof_attack_scorecard(benchmark_path)
    markdown = render_proof_attack_scorecard_markdown(payload)
    sarif = render_proof_attack_scorecard_sarif(payload)
    output_path = write_proof_attack_scorecard_output(payload, tmp_path / "proof-attack-scorecard.md")
    sarif_path = write_proof_attack_scorecard_sarif(payload, tmp_path / "proof-attack-scorecard.sarif")

    assert payload["status"] == "pass"
    assert payload["score"] == 100
    assert payload["grade"] == "A"
    assert payload["generated_decoy_count"] == 6
    assert all(item["passed"] for item in payload["items"])
    assert not payload["failed_cases"]
    assert not payload["unmitigated_decoys"]
    assert payload["weak_signal_decoys"]
    assert payload["github_annotations"][0].startswith("::notice")
    assert sarif["runs"][0]["results"] == []
    assert "# Repo Agent Adversarial Proof Attack Scorecard" in markdown
    assert output_path.is_file()
    assert sarif_path.is_file()


def test_remove_tree_retries_transient_file_lock(tmp_path: Path, monkeypatch) -> None:
    worktree = tmp_path / "locked-worktree"
    worktree.mkdir()
    (worktree / "server.js").write_text("console.log('temporary');\n", encoding="utf-8")
    real_rmtree = shutil.rmtree
    calls = 0

    def flaky_rmtree(path: Path, onerror=None) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("transient Windows file lock")
        real_rmtree(path, onerror=onerror)

    monkeypatch.setattr(main_module.shutil, "rmtree", flaky_rmtree)

    _remove_tree(worktree, attempts=3, delay_seconds=0)

    assert calls == 2
    assert not worktree.exists()


def test_temporal_benchmark_mutation_rejects_noop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "server.js").write_text("function unrelated() {}\n", encoding="utf-8")

    try:
        main_module._apply_temporal_benchmark_mutation(repo, {"mutation": "rename_flush"})
    except ValueError as exc:
        assert "produced no change" in str(exc)
    else:
        raise AssertionError("expected no-op temporal mutation to fail")


def test_proof_attack_scorecard_fails_thresholds_and_emits_ci_artifacts(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "proof-attack.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "case_count": 1,
                    "generated_decoy_count": 1,
                    "attack_resistance_rate": 0.0,
                    "mitigated_decoy_rate": 0.0,
                    "mitigation_signal_rate": 0.0,
                    "proof_proved_rate": 0.0,
                },
                "cases": [
                    {
                        "id": "attack",
                        "expected": "server.js:writeChatDelta",
                        "passed": False,
                        "variants": {
                            "graph_mcts": {
                                "top_hit": "server.js:writeChatDeltaForAdminShadow",
                                "rank": 2,
                                "distractor_rank": 1,
                            }
                        },
                        "proof": {
                            "proof_status": "partial",
                            "top_hit": "server.js:writeChatDeltaForAdminShadow",
                        },
                        "defense_audit": {
                            "decoys": [
                                {
                                    "label": "server.js:writeChatDeltaForAdminShadow",
                                    "rank": 1,
                                    "audit_top_k": 18,
                                    "mitigated": False,
                                    "mitigation_signals": [],
                                    "reasons": ["response writer"],
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_proof_attack_scorecard(benchmark_path)
    sarif = render_proof_attack_scorecard_sarif(payload)
    sarif_path = tmp_path / "proof-attack-scorecard.sarif"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-attack-scorecard",
            "--benchmark",
            str(benchmark_path),
            "--sarif-output",
            str(sarif_path),
            "--github-annotations",
            "--fail-on-fail",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["status"] == "fail"
    assert payload["score"] == 0
    assert {item["id"] for item in payload["items"] if not item["passed"]} == {
        "attack_resistance",
        "generated_decoy_mitigation",
        "mitigation_signal_coverage",
        "proof_proved_rate",
    }
    assert len(payload["failed_cases"]) == 1
    assert len(payload["unmitigated_decoys"]) == 1
    assert any(annotation.startswith("::error") for annotation in payload["github_annotations"])
    assert {
        "repo-agent/proof-attack-threshold-failed",
        "repo-agent/proof-attack-case-failed",
        "repo-agent/proof-attack-decoy-unmitigated",
    }.issubset({item["ruleId"] for item in sarif["runs"][0]["results"]})
    assert result.returncode == 1
    assert "::error title=Repo Agent proof attack threshold failed" in result.stdout
    assert sarif_path.is_file()


def test_proof_attack_cegar_runs_counterexample_guided_loop(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    payload = run_proof_attack_cegar(
        runtime,
        output_dir=tmp_path / "proof-attack-cegar",
        top_k=6,
        spec_path=Path("repo_agent/proof_attack_specs.json"),
    )
    markdown = render_proof_attack_cegar_markdown(payload)
    output_path = write_proof_attack_cegar_output(payload, tmp_path / "proof-attack-cegar.md")

    artifact_names = {item["name"] for item in payload["artifacts"]}
    assert payload["strategy"] == "adversarial_proof_attack_cegar"
    assert payload["status"] == "needs_refinement"
    assert payload["iteration_count"] == 1
    assert payload["iterations"][0]["scorecard_status"] == "pass"
    assert payload["iterations"][0]["score"] == 100
    assert payload["iterations"][0]["max_attack_pressure"] > 0
    assert payload["iterations"][0]["max_residual_risk"] == 0
    assert payload["summary"]["p0"] == 0
    assert payload["summary"]["p1"] >= 1
    assert payload["policy"]["status"] == "policy_converges"
    assert payload["policy"]["coverage_rate"] == 1.0
    assert payload["policy"]["residual_actions"] == 0
    assert payload["next_actions"]
    assert {
        "proof_attack_benchmark_json",
        "proof_attack_leaderboard",
        "proof_attack_triage",
        "proof_attack_policy",
        "proof_attack_scorecard_sarif",
    }.issubset(artifact_names)
    assert "# Repo Agent Proof Attack CEGAR Loop" in markdown
    assert "no_refinement_actions" in markdown
    assert "policy_covers_refinement_actions" in markdown
    assert output_path.is_file()


def test_agent_reliability_frontier_builds_pareto_profiles(tmp_path: Path) -> None:
    artifact_paths = []
    for index in range(3):
        artifact_path = tmp_path / f"artifact-{index}.txt"
        artifact_path.write_text(f"artifact {index}\n", encoding="utf-8")
        artifact_paths.append(artifact_path)
    artifacts = [
        {
            "name": path.stem,
            "path": str(path),
            "description": "Synthetic frontier artifact.",
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in artifact_paths
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "release_pack",
                "artifacts": artifacts,
                "metrics": {
                    "counterfactual_graph_mcts_top1": 1.0,
                    "counterfactual_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_graph_mcts_top1": 1.0,
                    "proof_attack_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_resistance_rate": 1.0,
                    "proof_attack_proof_proved_rate": 1.0,
                    "proof_score": 100,
                    "mutation_detection_rate": 1.0,
                    "contract_passed_checks": 4,
                    "contract_total_checks": 4,
                    "contract_status": "valid",
                    "pr_guard_status": "warn",
                    "proof_attack_certificate_score": 100,
                    "proof_attack_mitigated_decoy_rate": 1.0,
                    "proof_attack_score": 100,
                    "proof_attack_certificate_passed_claims": 5,
                    "proof_attack_certificate_claims": 5,
                    "proof_attack_adaptive_status": "adaptive_gap_found",
                    "proof_attack_repair_coverage": 1.0,
                    "proof_attack_adaptive_policy_coverage": 0.55,
                    "proof_attack_scorecard_status": "pass",
                    "proof_attack_certificate_status": "accepted",
                    "proof_attack_triage_actions": 7,
                    "temporal_repair_score": 100,
                    "temporal_repair_abstention_accuracy": 1.0,
                    "temporal_repair_false_repair_rate": 0.0,
                    "temporal_repair_causal_delta_rate": 1.0,
                    "proof_graph_delta_status": "causal_relink_found",
                    "proof_graph_delta_successor_relinks": 1,
                    "proof_graph_delta_broken_edges": 1,
                    "temporal_repair_successor_top1": 1.0,
                    "temporal_repair_migration_ready_rate": 1.0,
                    "temporal_repair_scorecard_status": "pass",
                    "agent_court_score": 100,
                    "agent_court_discharged_challenges": 5,
                    "agent_court_challenges": 5,
                    "agent_court_claims": 6,
                    "agent_court_status": "accepted",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_agent_reliability_frontier(manifest_path)
    markdown = render_agent_frontier_markdown(payload)
    output_path = write_agent_frontier_output(payload, tmp_path / "agent-frontier.md")
    cli_path = tmp_path / "agent-frontier.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "agent-frontier",
            "--manifest",
            str(manifest_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "agent_reliability_frontier"
    assert payload["status"] == "accepted"
    assert payload["summary"]["profile_count"] == 6
    assert payload["summary"]["frontier_count"] >= 2
    assert "adversarial_minimax_loop" in payload["summary"]["frontier_ids"]
    assert all(0 <= profile["score"] <= 100 for profile in payload["profiles"])
    assert all(profile["evidence_hash"] for profile in payload["profiles"])
    assert "# Repo Agent Reliability Frontier" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["profile_count"] == 6


def test_agent_frontier_ablation_attributes_evidence_families(tmp_path: Path) -> None:
    artifact_paths = []
    for name in ("proof_attack_certificate.md", "temporal_repair_scorecard.md", "agent_court.md"):
        artifact_path = tmp_path / name
        artifact_path.write_text(f"{name}\n", encoding="utf-8")
        artifact_paths.append(artifact_path)
    artifacts = [
        {
            "name": path.stem.replace("-", "_"),
            "path": str(path),
            "description": "Synthetic frontier ablation artifact.",
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in artifact_paths
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "release_pack",
                "artifacts": artifacts,
                "metrics": {
                    "counterfactual_graph_mcts_top1": 1.0,
                    "counterfactual_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_graph_mcts_top1": 1.0,
                    "proof_attack_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_resistance_rate": 1.0,
                    "proof_attack_proof_proved_rate": 1.0,
                    "proof_score": 100,
                    "mutation_detection_rate": 1.0,
                    "contract_passed_checks": 4,
                    "contract_total_checks": 4,
                    "contract_status": "valid",
                    "pr_guard_status": "warn",
                    "proof_attack_certificate_score": 100,
                    "proof_attack_mitigated_decoy_rate": 1.0,
                    "proof_attack_score": 100,
                    "proof_attack_certificate_passed_claims": 5,
                    "proof_attack_certificate_claims": 5,
                    "proof_attack_adaptive_status": "adaptive_gap_found",
                    "proof_attack_repair_coverage": 1.0,
                    "proof_attack_adaptive_policy_coverage": 0.55,
                    "proof_attack_scorecard_status": "pass",
                    "proof_attack_certificate_status": "accepted",
                    "proof_attack_triage_actions": 7,
                    "temporal_repair_score": 100,
                    "temporal_repair_abstention_accuracy": 1.0,
                    "temporal_repair_false_repair_rate": 0.0,
                    "temporal_repair_causal_delta_rate": 1.0,
                    "proof_graph_delta_status": "causal_relink_found",
                    "proof_graph_delta_successor_relinks": 1,
                    "proof_graph_delta_broken_edges": 1,
                    "temporal_repair_successor_top1": 1.0,
                    "temporal_repair_migration_ready_rate": 1.0,
                    "temporal_repair_scorecard_status": "pass",
                    "agent_court_score": 100,
                    "agent_court_discharged_challenges": 5,
                    "agent_court_challenges": 5,
                    "agent_court_claims": 6,
                    "agent_court_status": "accepted",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_agent_frontier_ablation(manifest_path)
    markdown = render_agent_frontier_ablation_markdown(payload)
    output_path = write_agent_frontier_ablation_output(payload, tmp_path / "agent-frontier-ablation.md")
    cli_path = tmp_path / "agent-frontier-ablation.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "agent-frontier-ablate",
            "--manifest",
            str(manifest_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "agent_frontier_causal_ablation"
    assert payload["status"] == "attributed"
    assert payload["summary"]["ablation_count"] == 6
    assert payload["summary"]["max_score_drop"] > 0
    assert payload["summary"]["top_driver"]
    assert any(item["id"] == "temporal_repair_loop" and item["profile_score_drop"] > 0 for item in payload["ablations"])
    assert any(item["dominance_changed"] for item in payload["ablations"])
    assert "# Repo Agent Frontier Causal Ablation" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["ablation_count"] == 6


def test_agent_frontier_interactions_maps_pairwise_counterfactuals(tmp_path: Path) -> None:
    artifact_paths = []
    for name in ("proof_contract.md", "proof_attack_certificate.md", "temporal_repair_scorecard.md", "agent_court.md"):
        artifact_path = tmp_path / name
        artifact_path.write_text(f"{name}\n", encoding="utf-8")
        artifact_paths.append(artifact_path)
    artifacts = [
        {
            "name": path.stem.replace("-", "_"),
            "path": str(path),
            "description": "Synthetic frontier interaction artifact.",
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in artifact_paths
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "release_pack",
                "artifacts": artifacts,
                "metrics": {
                    "counterfactual_graph_mcts_top1": 1.0,
                    "counterfactual_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_graph_mcts_top1": 1.0,
                    "proof_attack_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_resistance_rate": 1.0,
                    "proof_attack_proof_proved_rate": 1.0,
                    "proof_score": 100,
                    "mutation_detection_rate": 1.0,
                    "contract_passed_checks": 4,
                    "contract_total_checks": 4,
                    "contract_status": "valid",
                    "pr_guard_status": "warn",
                    "proof_attack_certificate_score": 100,
                    "proof_attack_mitigated_decoy_rate": 1.0,
                    "proof_attack_score": 100,
                    "proof_attack_certificate_passed_claims": 5,
                    "proof_attack_certificate_claims": 5,
                    "proof_attack_adaptive_status": "adaptive_gap_found",
                    "proof_attack_repair_coverage": 1.0,
                    "proof_attack_adaptive_policy_coverage": 0.55,
                    "proof_attack_scorecard_status": "pass",
                    "proof_attack_certificate_status": "accepted",
                    "proof_attack_triage_actions": 7,
                    "temporal_repair_score": 100,
                    "temporal_repair_abstention_accuracy": 1.0,
                    "temporal_repair_false_repair_rate": 0.0,
                    "temporal_repair_causal_delta_rate": 1.0,
                    "proof_graph_delta_status": "causal_relink_found",
                    "proof_graph_delta_successor_relinks": 1,
                    "proof_graph_delta_broken_edges": 1,
                    "temporal_repair_successor_top1": 1.0,
                    "temporal_repair_migration_ready_rate": 1.0,
                    "temporal_repair_scorecard_status": "pass",
                    "agent_court_score": 100,
                    "agent_court_discharged_challenges": 5,
                    "agent_court_challenges": 5,
                    "agent_court_claims": 6,
                    "agent_court_status": "accepted",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_agent_frontier_interactions(manifest_path)
    markdown = render_agent_frontier_interactions_markdown(payload)
    output_path = write_agent_frontier_interactions_output(payload, tmp_path / "agent-frontier-interactions.md")
    cli_path = tmp_path / "agent-frontier-interactions.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "agent-frontier-interactions",
            "--manifest",
            str(manifest_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "agent_frontier_evidence_interaction_matrix"
    assert payload["status"] == "mapped"
    assert payload["summary"]["family_count"] == 6
    assert payload["summary"]["pair_count"] == 15
    assert payload["summary"]["top_interaction"]
    assert payload["summary"]["fragile_pair_count"] >= 1
    assert all("synergy" in item for item in payload["interactions"])
    assert any(item["frontier_loss"] > 0 for item in payload["interactions"])
    assert "# Repo Agent Evidence Interaction Matrix" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["pair_count"] == 15


def test_agent_frontier_stability_bootstraps_uncertainty(tmp_path: Path) -> None:
    artifact_paths = []
    for name in ("proof_contract.md", "proof_attack_certificate.md", "temporal_repair_scorecard.md", "agent_court.md"):
        artifact_path = tmp_path / name
        artifact_path.write_text(f"{name}\n", encoding="utf-8")
        artifact_paths.append(artifact_path)
    artifacts = [
        {
            "name": path.stem.replace("-", "_"),
            "path": str(path),
            "description": "Synthetic frontier stability artifact.",
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in artifact_paths
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "release_pack",
                "artifacts": artifacts,
                "metrics": {
                    "counterfactual_graph_mcts_top1": 1.0,
                    "counterfactual_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_graph_mcts_top1": 1.0,
                    "proof_attack_graph_mcts_distractor_top1": 0.0,
                    "proof_attack_resistance_rate": 1.0,
                    "proof_attack_proof_proved_rate": 1.0,
                    "proof_score": 100,
                    "mutation_detection_rate": 1.0,
                    "contract_passed_checks": 4,
                    "contract_total_checks": 4,
                    "contract_status": "valid",
                    "pr_guard_status": "warn",
                    "proof_attack_certificate_score": 100,
                    "proof_attack_mitigated_decoy_rate": 1.0,
                    "proof_attack_score": 100,
                    "proof_attack_certificate_passed_claims": 5,
                    "proof_attack_certificate_claims": 5,
                    "proof_attack_adaptive_status": "adaptive_gap_found",
                    "proof_attack_repair_coverage": 1.0,
                    "proof_attack_adaptive_policy_coverage": 0.55,
                    "proof_attack_scorecard_status": "pass",
                    "proof_attack_certificate_status": "accepted",
                    "proof_attack_triage_actions": 7,
                    "temporal_repair_score": 100,
                    "temporal_repair_abstention_accuracy": 1.0,
                    "temporal_repair_false_repair_rate": 0.0,
                    "temporal_repair_causal_delta_rate": 1.0,
                    "proof_graph_delta_status": "causal_relink_found",
                    "proof_graph_delta_successor_relinks": 1,
                    "proof_graph_delta_broken_edges": 1,
                    "temporal_repair_successor_top1": 1.0,
                    "temporal_repair_migration_ready_rate": 1.0,
                    "temporal_repair_scorecard_status": "pass",
                    "agent_court_score": 100,
                    "agent_court_discharged_challenges": 5,
                    "agent_court_challenges": 5,
                    "agent_court_claims": 6,
                    "agent_court_status": "accepted",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_agent_frontier_stability(manifest_path, samples=12, noise=0.03, seed=11)
    markdown = render_agent_frontier_stability_markdown(payload)
    output_path = write_agent_frontier_stability_output(payload, tmp_path / "agent-frontier-stability.md")
    cli_path = tmp_path / "agent-frontier-stability.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "agent-frontier-stability",
            "--manifest",
            str(manifest_path),
            "--samples",
            "12",
            "--noise",
            "0.03",
            "--seed",
            "11",
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "agent_frontier_uncertainty_bootstrap"
    assert payload["status"] in {"stable", "uncertain"}
    assert payload["summary"]["sample_count"] == 12
    assert payload["summary"]["score_ci_low"] <= payload["summary"]["score_ci_high"]
    assert 0.0 <= payload["summary"]["frontier_jaccard_mean"] <= 1.0
    assert payload["summary"]["top_interaction_mode"]
    assert payload["summary"]["top_interaction_probability"] > 0.0
    assert len(payload["profiles"]) == 6
    assert len(payload["interactions"]) == 15
    assert all("frontier_probability" in item for item in payload["profiles"])
    assert all("fragile_probability" in item for item in payload["interactions"])
    assert "# Repo Agent Frontier Stability Lab" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["sample_count"] == 12


def test_agent_artifact_review_generates_reviewer_claim_card(tmp_path: Path) -> None:
    artifact_names = [
        "ablation_report",
        "counterfactual_report",
        "benchmark_adapter_json",
        "benchmark_adapter",
        "benchmark_diagnostics_json",
        "benchmark_diagnostics",
        "benchmark_repair_json",
        "benchmark_repair",
        "benchmark_repair_synthesis_json",
        "benchmark_repair_synthesis",
        "benchmark_repair_implementation_json",
        "benchmark_repair_implementation",
        "benchmark_repair_compiler_json",
        "benchmark_repair_compiler",
        "benchmark_repair_workbench_json",
        "benchmark_repair_workbench",
        "proof_attack_benchmark_json",
        "proof_attack_benchmark",
        "proof_bundle",
        "proof_replay",
        "proof_mutation_lab",
        "proof_scorecard",
        "proof_regression_contract_json",
        "proof_regression_contract_verification",
        "proof_pr_guard",
        "proof_attack_policy_json",
        "proof_attack_adaptive_json",
        "proof_attack_repair_json",
        "proof_attack_certificate_json",
        "proof_attack_cegar_json",
        "temporal_proof_regression_json",
        "temporal_proof_regression",
        "temporal_repair_benchmark_json",
        "temporal_repair_scorecard_json",
        "temporal_repair_scorecard_sarif",
        "agent_court_json",
        "agent_court",
        "agent_frontier_json",
        "agent_frontier_ablation_json",
        "agent_frontier_interactions_json",
        "agent_frontier_stability_json",
        "release_pack_readme",
    ]
    artifacts = []
    for name in artifact_names:
        artifact_path = tmp_path / f"{name}.txt"
        artifact_path.write_text(f"{name}\n", encoding="utf-8")
        artifacts.append(
            {
                "name": name,
                "path": str(artifact_path),
                "description": "Synthetic artifact review evidence.",
                "size_bytes": artifact_path.stat().st_size,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            }
        )
    for index in range(25):
        artifact_path = tmp_path / f"extra_artifact_{index}.txt"
        artifact_path.write_text(f"extra {index}\n", encoding="utf-8")
        artifacts.append(
            {
                "name": f"extra_artifact_{index}",
                "path": str(artifact_path),
                "description": "Synthetic extra artifact for reproducibility coverage.",
                "size_bytes": artifact_path.stat().st_size,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            }
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "strategy": "release_pack",
                "artifacts": artifacts,
                "metrics": {
                    "counterfactual_graph_mcts_top1": 1.0,
                    "counterfactual_graph_mcts_distractor_top1": 0.0,
                    "benchmark_adapter_status": "pass",
                    "benchmark_adapter_cases": 10,
                    "benchmark_adapter_repo_groups": 5,
                    "benchmark_adapter_tag_groups": 12,
                    "benchmark_adapter_top3": 1.0,
                    "benchmark_adapter_top1": 1.0,
                    "benchmark_adapter_distractor_top1": 0.0,
                    "benchmark_diagnostics_status": "clean",
                    "benchmark_diagnostics_score": 100,
                    "benchmark_diagnostics_blockers": 0,
                    "benchmark_diagnostics_taxonomy_count": 0,
                    "benchmark_diagnostics_projected_top1": 1.0,
                    "benchmark_repair_status": "validated",
                    "benchmark_repair_guards": 2,
                    "benchmark_repair_passed_guards": 2,
                    "benchmark_repair_synthesis_status": "validated",
                    "benchmark_repair_synthesis_score": 100,
                    "benchmark_repair_synthesis_validated_rules": 2,
                    "benchmark_repair_synthesis_proposed_rules": 0,
                    "benchmark_repair_synthesis_projected_top1": 1.0,
                    "benchmark_repair_implementation_status": "verified",
                    "benchmark_repair_implementation_score": 100,
                    "benchmark_repair_implementation_validated_rules": 2,
                    "benchmark_repair_implementation_implemented_rules": 2,
                    "benchmark_repair_implementation_missing_rules": 0,
                    "benchmark_repair_compiler_status": "compiled_noop_verified",
                    "benchmark_repair_compiler_score": 100,
                    "benchmark_repair_compiler_patch_required": 0,
                    "benchmark_repair_compiler_regression_locks": 2,
                    "benchmark_repair_compiler_ablation_toggles": 3,
                    "benchmark_repair_workbench_status": "patch_workbench_ready",
                    "benchmark_repair_workbench_score": 100,
                    "benchmark_repair_workbench_patch_candidates": 3,
                    "benchmark_repair_workbench_review_apply_patches": 3,
                    "benchmark_repair_workbench_counterfactual_patches": 3,
                    "benchmark_repair_workbench_experiments": 3,
                    "proof_attack_graph_mcts_top1": 1.0,
                    "proof_attack_graph_mcts_distractor_top1": 0.0,
                    "proof_score": 100,
                    "mutation_detection_rate": 1.0,
                    "contract_status": "valid",
                    "contract_passed_checks": 6,
                    "contract_total_checks": 6,
                    "proof_attack_resistance_rate": 1.0,
                    "proof_attack_policy_coverage": 1.0,
                    "proof_attack_adaptive_status": "adaptive_gap_found",
                    "proof_attack_repair_status": "repair_converges",
                    "proof_attack_certificate_status": "accepted",
                    "temporal_repair_successor_top1": 1.0,
                    "temporal_repair_abstention_accuracy": 1.0,
                    "temporal_repair_false_repair_rate": 0.0,
                    "temporal_repair_causal_delta_rate": 1.0,
                    "temporal_repair_scorecard_status": "pass",
                    "agent_court_status": "accepted",
                    "agent_court_score": 100,
                    "agent_court_claims": 6,
                    "agent_court_discharged_challenges": 5,
                    "agent_court_challenges": 5,
                    "agent_frontier_status": "accepted",
                    "agent_frontier_ablation_status": "attributed",
                    "agent_frontier_interactions_status": "mapped",
                    "agent_frontier_stability_status": "stable",
                    "agent_frontier_stability_samples": 64,
                    "agent_frontier_stability_frontier_jaccard": 0.86,
                    "agent_frontier_stability_score_ci_low": 89,
                    "agent_frontier_stability_score_ci_high": 89,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_agent_artifact_review(manifest_path)
    markdown = render_agent_artifact_review_markdown(payload)
    output_path = write_agent_artifact_review_output(payload, tmp_path / "agent-artifact-review.md")
    cli_path = tmp_path / "agent-artifact-review.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "agent-artifact-review",
            "--manifest",
            str(manifest_path),
            "--output",
            str(cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["strategy"] == "agent_artifact_evaluation_card"
    assert payload["status"] == "accepted"
    assert payload["summary"]["claim_count"] == 9
    assert payload["summary"]["supported_count"] == 9
    assert payload["summary"]["unsupported_count"] == 0
    assert payload["score"] == 100
    assert all(claim["validation_commands"] for claim in payload["claims"])
    assert all(claim["falsifiers"] for claim in payload["claims"])
    assert "# Repo Agent Artifact Evaluation Card" in markdown
    assert "## Reviewer Protocol" in markdown
    assert output_path.is_file()
    assert result.returncode == 0
    assert json.loads(cli_path.read_text(encoding="utf-8"))["summary"]["claim_count"] == 9

    provenance = build_artifact_provenance(manifest_path)
    provenance_markdown = render_artifact_provenance_markdown(provenance)
    provenance_output = write_artifact_provenance_output(provenance, tmp_path / "artifact-provenance.md")
    provenance_cli_path = tmp_path / "artifact-provenance.json"
    provenance_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "artifact-provenance",
            "--manifest",
            str(manifest_path),
            "--output",
            str(provenance_cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert provenance["strategy"] == "artifact_provenance_schema"
    assert provenance["status"] == "complete"
    assert provenance["summary"]["claim_count"] == payload["summary"]["claim_count"]
    assert provenance["summary"]["complete_claim_count"] == provenance["summary"]["claim_count"]
    assert provenance["summary"]["metric_edge_count"] >= payload["summary"]["claim_count"]
    assert provenance["summary"]["artifact_edge_count"] >= payload["summary"]["claim_count"] - 1
    assert provenance["summary"]["command_edge_count"] >= payload["summary"]["claim_count"]
    assert provenance["summary"]["falsifier_edge_count"] >= payload["summary"]["claim_count"]
    assert all(claim["complete"] for claim in provenance["claims"])
    assert all(edge["hash"] for edge in provenance["edges"])
    assert "# Repo Agent Artifact Provenance Graph" in provenance_markdown
    assert provenance_output.is_file()
    assert provenance_result.returncode == 0
    assert json.loads(provenance_cli_path.read_text(encoding="utf-8"))["status"] == "complete"

    provenance_json_path = write_artifact_provenance_output(provenance, tmp_path / "artifact-provenance.json")
    verification = verify_artifact_provenance(provenance_json_path, manifest_path=manifest_path)
    verification_output = write_artifact_provenance_verification_output(
        verification,
        tmp_path / "artifact-provenance-verification.md",
    )
    verification_cli_path = tmp_path / "artifact-provenance-verification.json"
    verification_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "verify-artifact-provenance",
            "--provenance",
            str(provenance_json_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(verification_cli_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert verification["strategy"] == "artifact_provenance_verification"
    assert verification["status"] == "pass"
    assert verification["summary"]["failure_count"] == 0
    assert verification_output.is_file()
    assert verification_result.returncode == 0
    assert json.loads(verification_cli_path.read_text(encoding="utf-8"))["status"] == "pass"

    tampered_artifact = Path(provenance["claims"][0]["artifacts"][0])
    tampered_path = next(
        Path(edge["evidence"]["path"])
        for edge in provenance["edges"]
        if edge["relation"] == "supported_by_artifact" and edge["target"] == f"artifact:{tampered_artifact.name}"
    )
    tampered_path.write_text(tampered_path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    tampered = verify_artifact_provenance(provenance_json_path, manifest_path=manifest_path)

    assert tampered["status"] == "fail"
    assert any(item["type"] == "artifact_sha256_mismatch" for item in tampered["failures"])


def test_release_pack_generates_manifest_and_artifacts(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    payload = build_release_pack(runtime, output_dir=tmp_path / "release-pack", top_k=6)
    markdown = render_release_pack_markdown(payload)
    manifest_payload = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
    verification = verify_release_pack(Path(payload["manifest_path"]))
    verification_markdown = render_release_pack_verification_markdown(verification)

    artifact_names = {item["name"] for item in payload["artifacts"]}
    manifest_names = {item["name"] for item in manifest_payload["artifacts"]}
    assert payload["strategy"] == "release_pack"
    assert payload["metrics"]["proof_grade"] == "A"
    assert payload["metrics"]["mutation_detection_rate"] == 1.0
    assert {
        "ablation_report",
        "counterfactual_report",
        "benchmark_adapter_json",
        "benchmark_adapter",
        "benchmark_diagnostics_json",
        "benchmark_diagnostics",
        "benchmark_repair_json",
        "benchmark_repair",
        "benchmark_repair_synthesis_json",
        "benchmark_repair_synthesis",
        "benchmark_repair_implementation_json",
        "benchmark_repair_implementation",
        "benchmark_repair_compiler_json",
        "benchmark_repair_compiler",
        "benchmark_repair_workbench_json",
        "benchmark_repair_workbench",
        "proof_attack_spec",
        "proof_attack_benchmark_json",
        "proof_attack_benchmark",
        "proof_attack_leaderboard_json",
        "proof_attack_leaderboard",
        "proof_attack_triage_json",
        "proof_attack_triage",
        "proof_attack_policy_json",
        "proof_attack_policy",
        "proof_attack_adaptive_spec",
        "proof_attack_adaptive_benchmark_json",
        "proof_attack_adaptive_benchmark",
        "proof_attack_adaptive_leaderboard_json",
        "proof_attack_adaptive_leaderboard",
        "proof_attack_adaptive_triage_json",
        "proof_attack_adaptive_triage",
        "proof_attack_adaptive_json",
        "proof_attack_adaptive",
        "proof_attack_repair_json",
        "proof_attack_repair",
        "proof_attack_certificate_json",
        "proof_attack_certificate",
        "proof_attack_scorecard_json",
        "proof_attack_scorecard",
        "proof_attack_scorecard_sarif",
        "proof_attack_cegar_json",
        "proof_attack_cegar",
        "proof_html_report",
        "proof_bundle",
        "proof_replay",
        "proof_mutation_lab",
        "proof_scorecard",
        "proof_impact",
        "proof_regression_contract_json",
        "proof_regression_contract",
        "proof_regression_contract_verification",
        "proof_pr_guard",
        "proof_pr_guard_sarif",
        "temporal_proof_regression_json",
        "temporal_proof_regression",
        "temporal_repair_benchmark_json",
        "temporal_repair_benchmark",
        "temporal_repair_scorecard_json",
        "temporal_repair_scorecard",
        "temporal_repair_scorecard_sarif",
        "agent_court_json",
        "agent_court",
        "agent_frontier_json",
        "agent_frontier",
        "agent_frontier_ablation_json",
        "agent_frontier_ablation",
        "agent_frontier_interactions_json",
        "agent_frontier_interactions",
        "agent_frontier_stability_json",
        "agent_frontier_stability",
        "agent_artifact_review_json",
        "agent_artifact_review",
        "artifact_provenance_json",
        "artifact_provenance",
        "artifact_provenance_verification_json",
        "artifact_provenance_verification",
        "release_pack_readme",
    }.issubset(artifact_names)
    assert payload["metrics"]["impact_risk_level"] == "high"
    assert payload["metrics"]["impact_exposed_routes"] >= 1
    assert payload["metrics"]["impact_impacted_files"] >= 1
    assert payload["metrics"]["contract_status"] == "valid"
    assert payload["metrics"]["benchmark_adapter_status"] in {"pass", "needs_attention"}
    assert payload["metrics"]["benchmark_adapter_cases"] >= 10
    assert payload["metrics"]["benchmark_adapter_top1"] >= 0.4
    assert payload["metrics"]["benchmark_adapter_top3"] >= 0.75
    assert payload["metrics"]["benchmark_adapter_mrr"] >= 0.6
    assert payload["metrics"]["benchmark_adapter_distractor_top1"] <= 0.07
    assert payload["metrics"]["benchmark_adapter_repo_groups"] >= 4
    assert payload["metrics"]["benchmark_adapter_tag_groups"] >= 8
    assert payload["metrics"]["benchmark_adapter_generalization_gaps"] >= 0
    assert payload["metrics"]["benchmark_diagnostics_status"] in {"clean", "actionable", "blocked"}
    assert payload["metrics"]["benchmark_diagnostics_weak_cases"] >= 0
    assert payload["metrics"]["benchmark_diagnostics_blockers"] >= 0
    assert payload["metrics"]["benchmark_diagnostics_actions"] >= 0
    assert payload["metrics"]["benchmark_diagnostics_taxonomy_count"] >= 0
    assert payload["metrics"]["benchmark_diagnostics_recoverable_cases"] >= 0
    assert payload["metrics"]["benchmark_diagnostics_projected_top1"] >= payload["metrics"]["benchmark_adapter_top1"]
    assert payload["metrics"]["benchmark_repair_status"] in {"validated", "needs_repair"}
    assert payload["metrics"]["benchmark_repair_score"] >= 70
    assert payload["metrics"]["benchmark_repair_passed_guards"] == payload["metrics"]["benchmark_repair_guards"] == 2
    assert payload["metrics"]["benchmark_repair_reason_cases"] >= 2
    assert payload["metrics"]["benchmark_repair_synthesis_status"] in {"validated", "repair_plan"}
    assert payload["metrics"]["benchmark_repair_synthesis_score"] >= 40
    assert payload["metrics"]["benchmark_repair_synthesis_candidates"] == 5
    assert payload["metrics"]["benchmark_repair_synthesis_validated_rules"] + payload["metrics"]["benchmark_repair_synthesis_proposed_rules"] >= 2
    assert payload["metrics"]["benchmark_repair_synthesis_projected_top1"] >= payload["metrics"]["benchmark_adapter_top1"]
    assert payload["metrics"]["benchmark_repair_implementation_status"] in {"verified", "implementation_plan"}
    assert payload["metrics"]["benchmark_repair_implementation_score"] >= 60
    assert payload["metrics"]["benchmark_repair_implementation_implemented_rules"] <= payload["metrics"]["benchmark_repair_synthesis_validated_rules"]
    assert payload["metrics"]["benchmark_repair_implementation_missing_rules"] == 0
    assert payload["metrics"]["benchmark_repair_implementation_found_anchors"] >= payload["metrics"]["benchmark_repair_implementation_implemented_rules"]
    assert payload["metrics"]["benchmark_repair_implementation_found_reasons"] >= payload["metrics"]["benchmark_repair_implementation_implemented_rules"]
    assert payload["metrics"]["benchmark_repair_compiler_status"] in {"compiled_noop_verified", "patch_plan_ready"}
    assert payload["metrics"]["benchmark_repair_compiler_score"] >= 70
    assert payload["metrics"]["benchmark_repair_compiler_patch_required"] >= 0
    assert payload["metrics"]["benchmark_repair_compiler_regression_locks"] == payload["metrics"]["benchmark_repair_synthesis_validated_rules"]
    assert payload["metrics"]["benchmark_repair_compiler_ablation_toggles"] >= (
        payload["metrics"]["benchmark_repair_synthesis_validated_rules"]
        + payload["metrics"]["benchmark_repair_synthesis_proposed_rules"]
    )
    assert payload["metrics"]["benchmark_repair_compiler_validation_commands"] >= 4
    assert payload["metrics"]["benchmark_repair_workbench_status"] == "patch_workbench_ready"
    assert payload["metrics"]["benchmark_repair_workbench_score"] == 100
    assert payload["metrics"]["benchmark_repair_workbench_patch_candidates"] >= payload["metrics"]["benchmark_repair_compiler_ablation_toggles"]
    assert payload["metrics"]["benchmark_repair_workbench_review_apply_patches"] >= payload["metrics"]["benchmark_repair_compiler_ablation_toggles"]
    assert payload["metrics"]["benchmark_repair_workbench_experiments"] >= payload["metrics"]["benchmark_repair_compiler_ablation_toggles"]
    assert payload["metrics"]["proof_attack_cases"] == 3
    assert payload["metrics"]["proof_attack_resistance_rate"] == 1.0
    assert payload["metrics"]["proof_attack_graph_mcts_top1"] == 1.0
    assert payload["metrics"]["proof_attack_graph_mcts_distractor_top1"] == 0.0
    assert payload["metrics"]["proof_attack_proof_proved_rate"] == 1.0
    assert payload["metrics"]["proof_attack_generated_decoy_count"] == 6
    assert payload["metrics"]["proof_attack_mitigated_decoy_rate"] == 1.0
    assert payload["metrics"]["proof_attack_mitigation_signal_rate"] > 0.0
    assert payload["metrics"]["proof_attack_suite"] == "repo-agent-default-proof-attacks"
    assert payload["metrics"]["proof_attack_hardest_case"]
    assert payload["metrics"]["proof_attack_max_pressure"] > 0
    assert payload["metrics"]["proof_attack_max_residual_risk"] == 0
    assert payload["metrics"]["proof_attack_triage_status"] == "needs_hardening"
    assert payload["metrics"]["proof_attack_triage_actions"] >= 3
    assert payload["metrics"]["proof_attack_triage_p0"] == 0
    assert payload["metrics"]["proof_attack_triage_p1"] >= 1
    assert payload["metrics"]["proof_attack_policy_status"] == "policy_converges"
    assert payload["metrics"]["proof_attack_policy_rules"] >= 3
    assert payload["metrics"]["proof_attack_policy_coverage"] == 1.0
    assert payload["metrics"]["proof_attack_policy_residual_actions"] == 0
    assert payload["metrics"]["proof_attack_adaptive_status"] == "adaptive_gap_found"
    assert payload["metrics"]["proof_attack_adaptive_cases"] >= 3
    assert payload["metrics"]["proof_attack_adaptive_policy_coverage"] < 1.0
    assert payload["metrics"]["proof_attack_adaptive_uncovered_actions"] >= 1
    assert payload["metrics"]["proof_attack_repair_status"] == "repair_converges"
    assert payload["metrics"]["proof_attack_repair_patch_rules"] >= 1
    assert payload["metrics"]["proof_attack_repair_coverage"] == 1.0
    assert payload["metrics"]["proof_attack_repair_uncovered_actions"] == 0
    assert payload["metrics"]["proof_attack_certificate_status"] == "accepted"
    assert payload["metrics"]["proof_attack_certificate_score"] == 100
    assert payload["metrics"]["proof_attack_certificate_claims"] == 5
    assert payload["metrics"]["proof_attack_certificate_passed_claims"] == 5
    assert payload["metrics"]["proof_attack_scorecard_status"] == "pass"
    assert payload["metrics"]["proof_attack_score"] == 100
    assert payload["metrics"]["proof_attack_grade"] == "A"
    assert payload["metrics"]["proof_attack_cegar_status"] == "needs_refinement"
    assert payload["metrics"]["proof_attack_cegar_iterations"] == 1
    assert payload["metrics"]["proof_attack_cegar_next_actions"] >= 1
    assert payload["metrics"]["contract_passed_checks"] == payload["metrics"]["contract_total_checks"]
    assert payload["metrics"]["pr_guard_status"] == "warn"
    assert payload["metrics"]["pr_guard_touched_files"] >= 1
    assert payload["metrics"]["temporal_status"] == "regression_found"
    assert payload["metrics"]["temporal_failed_commits"] >= 1
    assert payload["metrics"]["temporal_first_failing_commit"]
    assert payload["metrics"]["proof_repair_status"] == "successor_candidates_found"
    assert payload["metrics"]["proof_repair_top_candidate"] == "server.js:writeExperimentalChatDelta"
    assert payload["metrics"]["proof_graph_delta_status"] == "causal_relink_found"
    assert payload["metrics"]["proof_graph_delta_broken_edges"] >= 1
    assert payload["metrics"]["proof_graph_delta_successor_relinks"] >= 1
    assert payload["metrics"]["proof_contract_migration_status"] == "ready_for_review"
    assert payload["metrics"]["proof_contract_migration_patch_ops"] >= 4
    assert payload["metrics"]["temporal_repair_benchmark_cases"] == 4
    assert payload["metrics"]["temporal_repair_successor_top1"] == 1.0
    assert payload["metrics"]["temporal_repair_abstention_accuracy"] == 1.0
    assert payload["metrics"]["temporal_repair_false_repair_rate"] == 0.0
    assert payload["metrics"]["temporal_repair_causal_delta_rate"] == 1.0
    assert payload["metrics"]["temporal_repair_migration_ready_rate"] == 1.0
    assert payload["metrics"]["temporal_repair_scorecard_status"] == "pass"
    assert payload["metrics"]["temporal_repair_score"] == 100
    assert payload["metrics"]["temporal_repair_grade"] == "A"
    assert payload["metrics"]["agent_court_status"] == "accepted"
    assert payload["metrics"]["agent_court_score"] == 100
    assert payload["metrics"]["agent_court_grade"] == "A"
    assert payload["metrics"]["agent_court_claims"] == 6
    assert payload["metrics"]["agent_court_challenges"] >= 3
    assert payload["metrics"]["agent_court_discharged_challenges"] == payload["metrics"]["agent_court_challenges"]
    assert payload["metrics"]["agent_frontier_status"] == "accepted"
    assert payload["metrics"]["agent_frontier_score"] >= 80
    assert payload["metrics"]["agent_frontier_profiles"] == 6
    assert payload["metrics"]["agent_frontier_pareto_profiles"] >= 2
    assert payload["metrics"]["agent_frontier_ablation_status"] == "attributed"
    assert payload["metrics"]["agent_frontier_ablation_count"] == 6
    assert payload["metrics"]["agent_frontier_ablation_top_driver"]
    assert payload["metrics"]["agent_frontier_ablation_max_score_drop"] > 0
    assert payload["metrics"]["agent_frontier_interactions_status"] == "mapped"
    assert payload["metrics"]["agent_frontier_interactions_pairs"] == 15
    assert payload["metrics"]["agent_frontier_interactions_top_pair"]
    assert payload["metrics"]["agent_frontier_interactions_fragile_pairs"] >= 1
    assert payload["metrics"]["agent_frontier_stability_status"] in {"stable", "uncertain"}
    assert payload["metrics"]["agent_frontier_stability_samples"] == 64
    assert payload["metrics"]["agent_frontier_stability_score_ci_low"] <= payload["metrics"]["agent_frontier_stability_score_ci_high"]
    assert 0.0 <= payload["metrics"]["agent_frontier_stability_frontier_jaccard"] <= 1.0
    assert payload["metrics"]["agent_frontier_stability_top_interaction"]
    assert payload["metrics"]["agent_frontier_stability_top_interaction_probability"] > 0.0
    assert payload["metrics"]["agent_artifact_review_status"] in {"accepted", "accepted_with_limitations"}
    assert payload["metrics"]["agent_artifact_review_score"] >= 90
    assert payload["metrics"]["agent_artifact_review_grade"] in {"A", "B"}
    assert payload["metrics"]["agent_artifact_review_claims"] == 9
    assert payload["metrics"]["agent_artifact_review_supported_claims"] >= 8
    assert payload["metrics"]["artifact_provenance_status"] == "complete"
    assert payload["metrics"]["artifact_provenance_claims"] == payload["metrics"]["agent_artifact_review_claims"]
    assert payload["metrics"]["artifact_provenance_complete_claims"] == payload["metrics"]["artifact_provenance_claims"]
    assert payload["metrics"]["artifact_provenance_edges"] >= payload["metrics"]["artifact_provenance_claims"] * 4
    assert payload["metrics"]["artifact_provenance_artifact_edges"] >= payload["metrics"]["artifact_provenance_claims"] - 1
    assert payload["metrics"]["artifact_provenance_command_edges"] >= payload["metrics"]["artifact_provenance_claims"]
    assert payload["metrics"]["artifact_provenance_falsifier_edges"] >= payload["metrics"]["artifact_provenance_claims"]
    assert payload["metrics"]["artifact_provenance_verification_status"] == "pass"
    assert payload["metrics"]["artifact_provenance_verification_failures"] == 0
    assert artifact_names == manifest_names
    assert all(item["size_bytes"] > 0 for item in manifest_payload["artifacts"])
    assert all(len(item["sha256"]) == 64 for item in manifest_payload["artifacts"])
    assert verification["valid"] is True
    assert verification["verified_count"] == len(manifest_payload["artifacts"])
    assert Path(payload["manifest_path"]).is_file()
    assert Path(payload["readme_path"]).is_file()
    assert "# Repo Agent Release Pack" in markdown
    assert "## Integrity" in markdown
    assert "# Repo Agent Release Pack Integrity" in verification_markdown


def test_release_pack_verification_detects_tampering(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    payload = build_release_pack(runtime, output_dir=tmp_path / "release-pack", top_k=6)
    artifact = next(item for item in payload["artifacts"] if item["name"] == "proof_scorecard")
    artifact_path = Path(artifact["path"])

    artifact_path.write_text(artifact_path.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")
    verification = verify_release_pack(Path(payload["manifest_path"]))

    assert verification["valid"] is False
    assert verification["verified_count"] == len(payload["artifacts"]) - 1
    assert verification["failures"][0]["name"] == "proof_scorecard"
    assert verification["failures"][0]["reason"] in {"size_mismatch", "sha256_mismatch"}


def test_temporal_repair_scorecard_grades_benchmark(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "temporal-benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "case_count": 4,
                    "successor_top1_accuracy": 1.0,
                    "abstention_accuracy": 1.0,
                    "false_repair_rate": 0.0,
                    "causal_delta_rate": 1.0,
                    "migration_ready_rate": 1.0,
                },
                "cases": [
                    {
                        "id": "case-a",
                        "successor_top1": True,
                        "graph_delta_status": "causal_relink_found",
                        "migration_status": "ready_for_review",
                    },
                    {
                        "id": "negative",
                        "expected_abstain": True,
                        "successor_top1": False,
                        "abstention_correct": True,
                        "graph_delta_status": "broken_path_found",
                        "migration_status": "not_applicable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_temporal_repair_scorecard(benchmark_path)
    markdown = render_temporal_scorecard_markdown(payload)
    sarif = render_temporal_scorecard_sarif(payload)
    output_path = write_temporal_scorecard_output(payload, tmp_path / "temporal-scorecard.md")
    sarif_path = write_temporal_scorecard_sarif(payload, tmp_path / "temporal-scorecard.sarif")

    assert payload["status"] == "pass"
    assert payload["score"] == 100
    assert payload["grade"] == "A"
    assert all(item["passed"] for item in payload["items"])
    assert any(item["id"] == "negative_control_abstention" for item in payload["items"])
    assert not payload["failed_cases"]
    assert payload["github_annotations"][0].startswith("::notice")
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"] == []
    assert "# Repo Agent Temporal Repair Scorecard" in markdown
    assert output_path.is_file()
    assert sarif_path.is_file()


def test_temporal_repair_scorecard_fails_thresholds_and_emits_ci_artifacts(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "temporal-benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "case_count": 2,
                    "successor_top1_accuracy": 0.5,
                    "abstention_accuracy": 0.0,
                    "false_repair_rate": 1.0,
                    "causal_delta_rate": 0.5,
                    "migration_ready_rate": 0.5,
                },
                "cases": [
                    {
                        "id": "renamed-writer",
                        "successor_top1": False,
                        "top_candidate": "server.js:preparePublicStreamEnvelope",
                        "graph_delta_status": "broken_path_found",
                        "migration_status": "not_applicable",
                    },
                    {
                        "id": "deleted-writer",
                        "expected_abstain": True,
                        "abstention_correct": False,
                        "false_repair": True,
                        "top_candidate": "server.js:preparePublicStreamEnvelope",
                        "graph_delta_status": "broken_path_found",
                        "migration_status": "not_applicable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_temporal_repair_scorecard(benchmark_path)
    sarif = render_temporal_scorecard_sarif(payload)
    sarif_path = tmp_path / "temporal-scorecard.sarif"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "temporal-repair-scorecard",
            "--benchmark",
            str(benchmark_path),
            "--sarif-output",
            str(sarif_path),
            "--github-annotations",
            "--fail-on-fail",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["status"] == "fail"
    assert payload["score"] < 100
    assert {item["id"] for item in payload["items"] if not item["passed"]} == {
        "successor_top1",
        "negative_control_abstention",
        "causal_graph_delta",
        "migration_ready",
    }
    assert len(payload["failed_cases"]) == 2
    assert any(annotation.startswith("::error") for annotation in payload["github_annotations"])
    assert {result["ruleId"] for result in sarif["runs"][0]["results"]} == {
        "repo-agent/temporal-repair-threshold-failed",
        "repo-agent/temporal-repair-case-failed",
    }
    assert result.returncode == 1
    assert "::error title=Repo Agent temporal repair threshold failed" in result.stdout
    assert sarif_path.is_file()
