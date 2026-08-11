from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from repo_agent.contract import (
    build_regression_contract,
    guard_pr_with_contract,
    render_contract_markdown,
    render_pr_guard_markdown,
    render_pr_guard_sarif,
    verify_regression_contract,
    write_contract_output,
    write_pr_guard_sarif,
)
from repo_agent.impact import analyze_impact_bundle, render_impact_markdown, write_impact_output
from repo_agent.proof import (
    build_proof_scorecard,
    replay_proof_bundle,
    run_proof_mutation_lab,
    write_mutation_output,
    write_replay_output,
    write_scorecard_output,
)
from repo_agent.runtime import RepoAgentRuntime


def _workspace(name: str) -> Path:
    root = Path.cwd() / "test-workspaces" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_runtime_generates_codex_markdown_evidence_bundle() -> None:
    workspace = _workspace("bundle-markdown")
    repo_root = workspace / "repo"
    try:
        _write(
            repo_root / "server.js",
            """
const express = require('express');
const app = express();

app.post('/api/chat', handleChat);

function handleChat(req, res) {
  res.json({ ok: true });
}
""".strip(),
        )
        runtime = RepoAgentRuntime(Path.cwd())
        _bundle, output_path = runtime.generate_bundle(
            repo_path=repo_root,
            question="Where is the chat endpoint implemented?",
            target="codex",
            fmt="markdown",
            force_rebuild=True,
            output_path=workspace / "evidence.md",
        )

        text = output_path.read_text(encoding="utf-8")

        assert output_path.is_file()
        assert "# Repo Agent Evidence Bundle" in text
        assert "Target: `codex`" in text
        assert "Use this Repo Agent evidence bundle" in text
        assert "## Evidence Diagnostics" in text
        assert "## Graph Search Audit" in text
        assert "## Proof-Carrying Retrieval" in text
        assert "### Proof Graph" in text
        assert "graph_mcts" in text
        assert "Confidence:" in text
        assert "server.js" in text
        assert "handleChat" in text
    finally:
        _cleanup(workspace)


def test_runtime_generates_json_evidence_bundle() -> None:
    workspace = _workspace("bundle-json")
    repo_root = workspace / "repo"
    try:
        _write(
            repo_root / "app.py",
            """
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
""".strip(),
        )
        runtime = RepoAgentRuntime(Path.cwd())
        _bundle, output_path = runtime.generate_bundle(
            repo_path=repo_root,
            question="Where is the health route?",
            target="generic",
            fmt="json",
            force_rebuild=True,
            output_path=workspace / "evidence.json",
        )

        payload = json.loads(output_path.read_text(encoding="utf-8"))

        assert payload["schema_version"]
        assert payload["target"] == "generic"
        assert payload["evidence"]
        assert payload["evidence"][0]["relpath"] == "app.py"
        assert payload["diagnostics"]["evidence_count"] == len(payload["evidence"])
        assert payload["diagnostics"]["confidence"] > 0
        assert payload["graph_search"]["iterations"] > 0
        assert payload["graph_search"]["top_visited"]
        assert payload["proof"]["strategy"] == "proof_carrying_retrieval"
        assert payload["proof"]["checks"]
        assert payload["proof"]["proof_graph"]["nodes"]
        assert payload["proof"]["proof_graph"]["edges"]
        assert "decoy_audit" in payload["proof"]
    finally:
        _cleanup(workspace)


def test_counterfactual_markdown_bundle_includes_decoy_audit(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="codex",
        fmt="markdown",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.md",
    )

    text = output_path.read_text(encoding="utf-8")

    assert "### Contrastive Decoy Audit" in text
    assert "admin" in text.lower()
    assert "legacy" in text.lower()
    assert "candidate belongs to admin surface" in text


def test_replay_proof_validates_counterfactual_json_bundle(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    payload = replay_proof_bundle(output_path, strict=True)

    assert payload["status"] == "valid"
    assert payload["valid"] is True
    assert payload["strict"] is True
    assert {item["name"] for item in payload["checks"]} >= {
        "top_hit_exists",
        "evidence_fingerprints_match",
        "route_literals_exist",
        "supporting_paths_exist",
        "proof_graph_edges_resolve",
        "proof_graph_edges_verified",
        "decoy_audit_still_rejected",
    }
    assert all(item["passed"] for item in payload["checks"])
    assert payload["drift_diagnosis"][0]["type"] == "none"


def test_replay_proof_detects_stale_top_hit(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    bundle["proof"]["top_hit"] = "server.js:missingWriter"
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = replay_proof_bundle(output_path)

    assert payload["status"] == "invalid"
    assert any(item["name"] == "top_hit_exists" and not item["passed"] for item in payload["checks"])
    assert any(item["type"] == "top_hit_missing" for item in payload["drift_diagnosis"])
    assert any("renamed or moved" in item["suggested_action"] for item in payload["drift_diagnosis"])


def test_replay_proof_diagnoses_missing_route_anchor(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    bundle["proof"]["route_literals"] = ["/api/chat/v2"]
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = replay_proof_bundle(output_path)

    assert payload["status"] == "invalid"
    assert any(item["type"] == "route_anchor_missing" for item in payload["drift_diagnosis"])
    assert any("endpoint surface" in item["suggested_action"] for item in payload["drift_diagnosis"])


def test_strict_replay_detects_unverified_proof_graph_edge(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    bundle["proof"]["proof_graph"]["edges"].append(
        {
            "source": "server.js:writeAdminChatDelta",
            "target": "server.js:writeChatDelta",
            "label": "route_path",
        }
    )
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = replay_proof_bundle(output_path, strict=True)

    assert payload["status"] == "invalid"
    assert any(item["name"] == "proof_graph_edges_verified" and not item["passed"] for item in payload["checks"])
    assert any(item["type"] == "proof_graph_edge_unverified" for item in payload["drift_diagnosis"])


def test_replay_proof_detects_stale_evidence_snippet(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    bundle["evidence"][0]["snippet"] = "__stale_proof_evidence_snippet__"
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = replay_proof_bundle(output_path, strict=True)

    assert payload["status"] == "invalid"
    assert any(item["name"] == "evidence_fingerprints_match" and not item["passed"] for item in payload["checks"])
    assert any(item["type"] == "evidence_content_drift" for item in payload["drift_diagnosis"])


def test_replay_proof_cli_outputs_markdown(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    report_path = tmp_path / "replay-report.md"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "replay-proof",
            "--bundle",
            str(output_path),
            "--strict",
            "--output",
            str(report_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Proof Replay" in completed.stdout
    assert "Status: `valid`" in completed.stdout
    assert "Strict graph edge verification: `True`" in completed.stdout
    assert "## Drift Diagnosis" in completed.stdout
    assert "`none`" in completed.stdout
    assert report_path.read_text(encoding="utf-8").startswith("# Repo Agent Proof Replay")
    assert f"Report: {report_path}" in completed.stdout


def test_proof_mutation_lab_detects_all_seeded_mutations(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    payload = run_proof_mutation_lab(output_path)

    assert payload["baseline_status"] == "valid"
    assert payload["mutation_count"] == 6
    assert payload["detected_count"] == 6
    assert payload["detection_rate"] == 1.0
    assert {case["mutation"] for case in payload["cases"]} == {
        "top_hit_missing",
        "evidence_snippet_drift",
        "route_anchor_missing",
        "supporting_path_missing",
        "proof_graph_edge_unverified",
        "decoy_audit_stale",
    }
    json_path = write_mutation_output(payload, tmp_path / "mutation-report.json")

    assert json.loads(json_path.read_text(encoding="utf-8"))["detection_rate"] == 1.0


def test_proof_mutation_cli_outputs_markdown(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    report_path = tmp_path / "mutation-report.md"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-mutate",
            "--bundle",
            str(output_path),
            "--output",
            str(report_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Proof Mutation Lab" in completed.stdout
    assert "Detection rate: `100.0%`" in completed.stdout
    assert "`proof_graph_edge_unverified`" in completed.stdout
    assert report_path.read_text(encoding="utf-8").startswith("# Repo Agent Proof Mutation Lab")
    assert f"Report: {report_path}" in completed.stdout


def test_replay_output_writes_json(tmp_path: Path) -> None:
    payload = {
        "status": "valid",
        "strategy": "proof_replay",
        "strict": True,
        "checks": [],
        "drift_diagnosis": [],
    }

    output_path = write_replay_output(payload, tmp_path / "replay.json")

    assert json.loads(output_path.read_text(encoding="utf-8"))["strategy"] == "proof_replay"


def test_proof_scorecard_summarizes_reliability(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    payload = build_proof_scorecard(output_path)
    json_path = write_scorecard_output(payload, tmp_path / "scorecard.json")

    assert payload["grade"] == "A"
    assert payload["score"] == 100
    assert payload["metrics"]["mutation_detection_rate"] == 1.0
    assert any(item["name"] == "evidence_fingerprints_match" and item["passed"] for item in payload["score_items"])
    assert all(item["passed"] for item in payload["score_items"])
    assert json.loads(json_path.read_text(encoding="utf-8"))["strategy"] == "proof_reliability_scorecard"


def test_proof_scorecard_cli_outputs_markdown(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    report_path = tmp_path / "scorecard.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "proof-scorecard",
            "--bundle",
            str(output_path),
            "--output",
            str(report_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Proof Reliability Scorecard" in completed.stdout
    assert "Score: `100/100`" in completed.stdout
    assert "Grade: `A`" in completed.stdout
    assert report_path.read_text(encoding="utf-8").startswith("# Repo Agent Proof Reliability Scorecard")
    assert f"Report: {report_path}" in completed.stdout


def test_proof_guided_impact_analysis_finds_route_exposure(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    payload = analyze_impact_bundle(output_path)
    markdown = render_impact_markdown(payload)
    json_path = write_impact_output(payload, tmp_path / "impact.json")

    assert payload["status"] == "analyzed"
    assert payload["target"]["label"] == "server.js:writeChatDelta"
    assert payload["impact_summary"]["risk_level"] == "high"
    assert payload["impact_summary"]["exposed_route_count"] >= 1
    assert any(item["route"] == "/api/chat" for item in payload["exposed_routes"])
    assert any(item["priority"] == "P0" and "Replay" in item["check"] for item in payload["verification_plan"])
    assert "# Repo Agent Proof-Guided Impact Analysis" in markdown
    assert json.loads(json_path.read_text(encoding="utf-8"))["strategy"] == "proof_guided_impact_analysis"


def test_impact_cli_outputs_markdown(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    report_path = tmp_path / "impact.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "impact",
            "--bundle",
            str(output_path),
            "--output",
            str(report_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Proof-Guided Impact Analysis" in completed.stdout
    assert "Risk level: `high`" in completed.stdout
    assert "`/api/chat`" in completed.stdout
    assert report_path.read_text(encoding="utf-8").startswith("# Repo Agent Proof-Guided Impact Analysis")
    assert f"Report: {report_path}" in completed.stdout


def test_proof_regression_contract_verifies_invariants(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )

    contract = build_regression_contract(output_path)
    contract_path = write_contract_output(contract, tmp_path / "contract.json")
    markdown = render_contract_markdown(contract)
    verification = verify_regression_contract(contract_path)

    invariant_ids = {item["id"] for item in contract["invariants"]}
    assert contract["strategy"] == "proof_regression_contract"
    assert "target_exists" in invariant_ids
    assert "strict_proof_replay" in invariant_ids
    assert "impact_route_exposure_preserved" in invariant_ids
    assert contract["impact_summary"]["risk_level"] == "high"
    assert "# Repo Agent Proof Regression Contract" in markdown
    assert verification["status"] == "valid"
    assert verification["summary"]["passed_count"] == verification["summary"]["check_count"]


def test_proof_regression_contract_detects_missing_route_requirement(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract = build_regression_contract(output_path)
    route_invariant = next(item for item in contract["invariants"] if item["id"] == "route_literals_exist")
    route_invariant["routes"] = ["/api/chat/v2"]
    contract_path = write_contract_output(contract, tmp_path / "contract.json")

    verification = verify_regression_contract(contract_path)

    assert verification["status"] == "invalid"
    assert any(item["id"] == "route_literals_exist" and not item["passed"] for item in verification["checks"])


def test_contract_cli_outputs_markdown_and_verification(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract_path = tmp_path / "contract.json"

    contract_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "contract",
            "--bundle",
            str(output_path),
            "--output",
            str(contract_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    verify_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "verify-contract",
            "--contract",
            str(contract_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Proof Regression Contract" in contract_completed.stdout
    assert json.loads(contract_path.read_text(encoding="utf-8"))["strategy"] == "proof_regression_contract"
    assert "# Repo Agent Proof Regression Contract Verification" in verify_completed.stdout
    assert "Status: `PASS`" in verify_completed.stdout


def test_proof_backed_pr_guard_flags_protected_surface(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract = build_regression_contract(output_path)
    contract_path = write_contract_output(contract, tmp_path / "contract.json")

    payload = guard_pr_with_contract(contract_path, changed_files=["server.js"])
    markdown = render_pr_guard_markdown(payload)

    assert payload["strategy"] == "proof_backed_pr_guard"
    assert payload["status"] == "warn"
    assert payload["exit_code"] == 0
    assert payload["requires_verification"] is True
    assert payload["touched_protected_files"] == ["server.js"]
    assert any("verify-contract" in command for command in payload["required_commands"])
    assert any(annotation.startswith("::warning file=server.js") for annotation in payload["github_annotations"])
    assert "# Repo Agent Proof-Backed PR Guard" in markdown
    sarif = render_pr_guard_sarif(payload)
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"][0]["ruleId"] == "repo-agent/protected-proof-surface"
    assert sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "server.js"


def test_proof_backed_pr_guard_passes_unrelated_change(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract_path = write_contract_output(build_regression_contract(output_path), tmp_path / "contract.json")

    payload = guard_pr_with_contract(contract_path, changed_files=["README.md"])

    assert payload["status"] == "pass"
    assert payload["exit_code"] == 0
    assert payload["requires_verification"] is False
    assert payload["required_commands"] == []


def test_proof_backed_pr_guard_fail_on_warn_sets_exit_code(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract_path = write_contract_output(build_regression_contract(output_path), tmp_path / "contract.json")

    payload = guard_pr_with_contract(contract_path, changed_files=["server.js"], fail_on="warn")

    assert payload["status"] == "warn"
    assert payload["fail_on"] == "warn"
    assert payload["exit_code"] == 1


def test_proof_backed_pr_guard_writes_sarif(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract_path = write_contract_output(build_regression_contract(output_path), tmp_path / "contract.json")
    payload = guard_pr_with_contract(contract_path, changed_files=["server.js"])

    sarif_path = write_pr_guard_sarif(payload, tmp_path / "guard.sarif")
    sarif = json.loads(sarif_path.read_text(encoding="utf-8"))

    assert sarif["runs"][0]["tool"]["driver"]["name"] == "Repo Agent Proof-Backed PR Guard"
    assert sarif["runs"][0]["results"][0]["level"] == "warning"


def test_pr_guard_cli_outputs_markdown(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract_path = write_contract_output(build_regression_contract(output_path), tmp_path / "contract.json")
    report_path = tmp_path / "pr-guard.md"
    sarif_path = tmp_path / "pr-guard.sarif"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "pr-guard",
            "--contract",
            str(contract_path),
            "--changed-files",
            "server.js",
            "--output",
            str(report_path),
            "--sarif-output",
            str(sarif_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Proof-Backed PR Guard" in completed.stdout
    assert "Status: `WARN`" in completed.stdout
    assert "server.js" in completed.stdout
    assert report_path.read_text(encoding="utf-8").startswith("# Repo Agent Proof-Backed PR Guard")
    assert json.loads(sarif_path.read_text(encoding="utf-8"))["runs"][0]["results"]


def test_pr_guard_cli_fail_on_warn_emits_github_annotations(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, output_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract_path = write_contract_output(build_regression_contract(output_path), tmp_path / "contract.json")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "pr-guard",
            "--contract",
            str(contract_path),
            "--changed-files",
            "server.js",
            "--fail-on",
            "warn",
            "--github-annotations",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Status: `WARN`" in completed.stdout
    assert "::warning file=server.js" in completed.stdout


def test_release_pack_cli_generates_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "release-pack"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "release-pack",
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    manifest_path = output_dir / "manifest.json"
    readme_path = output_dir / "README.md"

    assert "# Repo Agent Release Pack" in completed.stdout
    assert manifest_path.is_file()
    assert readme_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["metrics"]["proof_grade"] == "A"
    assert all(item["sha256"] for item in manifest["artifacts"])


def test_verify_release_pack_cli_checks_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "release-pack"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "release-pack",
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "verify-release-pack",
            "--manifest",
            str(output_dir / "manifest.json"),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "# Repo Agent Release Pack Integrity" in completed.stdout
    assert "Status: `PASS`" in completed.stdout


def test_runtime_health_exposes_agent_policy() -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    policy = runtime.health()["agent_policy"]

    assert policy["execution_modes"]["recommended_default"] == "workspace"
    assert ".env" in policy["repository_access"]["protected_files"]
    assert ".git" in policy["repository_access"]["protected_dirs"]
    assert "python -m pytest" in policy["tooling"]["allowed_verification_commands"]
    assert "shell=False" in policy["tooling"]["command_execution"]
