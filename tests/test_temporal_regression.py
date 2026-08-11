from __future__ import annotations

import subprocess
import sys
import shutil
import uuid
from pathlib import Path

from repo_agent.contract import build_regression_contract, write_contract_output
from repo_agent.runtime import RepoAgentRuntime
from repo_agent.temporal import (
    render_temporal_markdown,
    run_temporal_proof_regression,
    write_temporal_output,
)


QUESTION = "Which function finally writes streamed tokens for the public /api/chat endpoint?"


def test_temporal_proof_regression_finds_first_failing_commit(tmp_path: Path) -> None:
    source_repo = Path.cwd() / "examples" / "counterfactual_agent_app"
    workspace = _workspace("temporal")
    repo = workspace / "history-repo"
    try:
        repo.mkdir()
        (repo / "server.js").write_text((source_repo / "server.js").read_text(encoding="utf-8"), encoding="utf-8")
        _git(repo, ["init"])
        _git(repo, ["config", "user.email", "repo-agent@example.local"])
        _git(repo, ["config", "user.name", "Repo Agent"])
        _git(repo, ["add", "server.js"])
        _git(repo, ["commit", "-m", "preserve proved public chat writer"])

        runtime = RepoAgentRuntime(Path.cwd())
        _bundle, bundle_path = runtime.generate_bundle(
            repo_path=repo,
            question=QUESTION,
            target="generic",
            fmt="json",
            force_rebuild=True,
            output_path=tmp_path / "proof.bundle.json",
        )
        contract = build_regression_contract(bundle_path, repo_path=repo)
        contract_path = write_contract_output(contract, tmp_path / "proof-contract.json")

        text = (repo / "server.js").read_text(encoding="utf-8").replace("writeChatDelta", "writeExperimentalChatDelta")
        (repo / "server.js").write_text(text, encoding="utf-8")
        _git(repo, ["add", "server.js"])
        _git(repo, ["commit", "-m", "rename public chat writer without updating proof contract"])

        payload = run_temporal_proof_regression(
            contract_path,
            git_repo_path=repo,
            repo_subdir="",
            rev_range="HEAD",
            max_commits=10,
        )
        markdown = render_temporal_markdown(payload)
        json_path = write_temporal_output(payload, tmp_path / "temporal.json")
        md_path = write_temporal_output(payload, tmp_path / "temporal.md")

        assert payload["status"] == "regression_found"
        assert payload["summary"]["transition"] == "pass_to_fail"
        assert payload["commit_count"] == 2
        assert payload["summary"]["passed_count"] == 1
        assert payload["summary"]["failed_count"] == 1
        assert payload["first_failing_commit"]["subject"] == "rename public chat writer without updating proof contract"
        assert payload["last_passing_commit"]["subject"] == "preserve proved public chat writer"
        assert any(item["id"] == "target_exists" for item in payload["first_failing_commit"]["failed_checks"])
        assert payload["proof_repair"]["status"] == "successor_candidates_found"
        assert payload["proof_repair"]["top_candidate"]["label"] == "server.js:writeExperimentalChatDelta"
        assert payload["proof_repair"]["top_candidate"]["confidence"] in {"medium", "high"}
        graph_delta = payload["proof_repair"]["proof_graph_delta"]
        assert graph_delta["status"] == "causal_relink_found"
        assert graph_delta["broken_edge_count"] >= 1
        assert graph_delta["successor_relink_count"] >= 1
        assert any(
            item["source"] == "server.js:streamPublicChatTurn"
            and item["target"] == "server.js:writeChatDelta"
            and item["status"] == "removed"
            for item in graph_delta["edge_deltas"]
        )
        assert any(
            item["predecessor"] == "server.js:streamPublicChatTurn"
            and item["successor"] == "server.js:writeExperimentalChatDelta"
            and item["status"] == "relinked"
            for item in graph_delta["successor_relinks"]
        )
        migration = payload["proof_repair"]["contract_migration_plan"]
        assert migration["status"] == "ready_for_review"
        assert migration["old_target"] == "server.js:writeChatDelta"
        assert migration["new_target"] == "server.js:writeExperimentalChatDelta"
        assert all(item["passed"] for item in migration["simulation_checks"])
        assert any(
            op["path"] == "/proof_context/top_hit"
            and op["value"] == "server.js:writeExperimentalChatDelta"
            for op in migration["json_patch"]
        )
        assert any(
            op["path"].endswith("/path/3")
            and op["value"] == "server.js:writeExperimentalChatDelta"
            for op in migration["json_patch"]
        )
        assert "# Repo Agent Temporal Proof Regression" in markdown
        assert "Regression Diagnosis" in markdown
        assert "Proof Graph Delta" in markdown
        assert "Proof Repair Candidates" in markdown
        assert "Proof Contract Migration Plan" in markdown
        assert json_path.is_file()
        assert md_path.is_file()
    finally:
        _cleanup(workspace)


def test_temporal_proof_regression_cli_outputs_report(tmp_path: Path) -> None:
    source_repo = Path.cwd() / "examples" / "counterfactual_agent_app"
    workspace = _workspace("temporal-cli")
    repo = workspace / "history-repo"
    try:
        repo.mkdir()
        (repo / "server.js").write_text((source_repo / "server.js").read_text(encoding="utf-8"), encoding="utf-8")
        _git(repo, ["init"])
        _git(repo, ["config", "user.email", "repo-agent@example.local"])
        _git(repo, ["config", "user.name", "Repo Agent"])
        _git(repo, ["add", "server.js"])
        _git(repo, ["commit", "-m", "good proof path"])

        runtime = RepoAgentRuntime(Path.cwd())
        _bundle, bundle_path = runtime.generate_bundle(
            repo_path=repo,
            question=QUESTION,
            target="generic",
            fmt="json",
            force_rebuild=True,
            output_path=tmp_path / "proof.bundle.json",
        )
        contract = build_regression_contract(bundle_path, repo_path=repo)
        contract_path = write_contract_output(contract, tmp_path / "proof-contract.json")

        text = (repo / "server.js").read_text(encoding="utf-8").replace("writeChatDelta", "writeExperimentalChatDelta")
        (repo / "server.js").write_text(text, encoding="utf-8")
        _git(repo, ["add", "server.js"])
        _git(repo, ["commit", "-m", "bad proof path"])

        output_path = tmp_path / "temporal-report.md"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "repo_agent",
                "temporal-proof-regression",
                "--contract",
                str(contract_path),
                "--git-repo",
                str(repo),
                "--repo-subdir",
                "",
                "--rev-range",
                "HEAD",
                "--output",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert "temporal_proof_regression" in result.stdout
        assert "First failing commit" in result.stdout
        assert "Proof Graph Delta" in result.stdout
        assert "Proof Contract Migration Plan" in result.stdout
        assert "writeExperimentalChatDelta" in result.stdout
        assert output_path.is_file()
        assert "bad proof path" in output_path.read_text(encoding="utf-8")
    finally:
        _cleanup(workspace)


def _git(repo: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _workspace(name: str) -> Path:
    root = Path.cwd() / "test-workspaces" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
