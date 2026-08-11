from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from repo_agent.llm import LLMClient
from repo_agent.engineering import EngineeringAgent, EngineeringRun
from repo_agent.indexer import build_index
from repo_agent.runtime import _execution_mode
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


@pytest.mark.parametrize("value", [None, "", "workspace", " Workspace ", "sandbox", "copy"])
def test_execution_mode_defaults_to_workspace(value: str | None) -> None:
    assert _execution_mode(value) == "workspace"


@pytest.mark.parametrize("value", ["local", " Local ", "source"])
def test_execution_mode_accepts_explicit_local_mode(value: str) -> None:
    assert _execution_mode(value) == "local"


@pytest.mark.parametrize("value", ["direct", "repo", "true"])
def test_execution_mode_rejects_unknown_modes(value: str) -> None:
    with pytest.raises(ValueError, match="execution_mode"):
        _execution_mode(value)


def test_runtime_engineer_defaults_to_workspace_copy() -> None:
    workspace = _workspace("engineer-workspace-default")
    repo_root = workspace / "repo"
    run_path: Path | None = None
    try:
        _write(repo_root / "app.py", "def answer():\n    return 42\n")
        runtime = RepoAgentRuntime(Path.cwd())
        runtime.llm = LLMClient()

        result, repo_index = runtime.engineer(
            repo_path=repo_root,
            task="Add a tiny health check",
            execution_mode=None,
            max_steps=1,
            force_rebuild=True,
        )
        run_path = Path(str(result["run_path"])).resolve()
        workspace_root = Path(str(result["workspace_root"])).resolve()

        assert result["status"] == "model_unavailable"
        assert result["execution_mode"] == "workspace"
        assert Path(str(result["source_repo_root"])).resolve() == repo_root.resolve()
        assert workspace_root.is_dir()
        assert repo_index.repo_root == workspace_root
        assert (workspace_root / "app.py").read_text(encoding="utf-8") == "def answer():\n    return 42\n"
        assert repo_root.joinpath("app.py").read_text(encoding="utf-8") == "def answer():\n    return 42\n"
        assert result["timeline"]
        assert any(item["agent"] == "Coordinator Agent" for item in result["timeline"])
        assert any(item["agent"] == "Verifier Agent" for item in result["timeline"])
        assert any(item["agent"] == "Reviewer Agent" for item in result["timeline"])
        assert result["verifier_result"]["status"] in {"not_run", "missing"}
        assert result["reviewer_result"]["risk_score"] >= 0
    finally:
        _cleanup(workspace)
        _cleanup_run_path(run_path)


def test_runtime_engineer_uses_source_repo_only_when_local_is_explicit() -> None:
    workspace = _workspace("engineer-local-explicit")
    repo_root = workspace / "repo"
    run_path: Path | None = None
    try:
        _write(repo_root / "app.py", "def answer():\n    return 42\n")
        runtime = RepoAgentRuntime(Path.cwd())
        runtime.llm = LLMClient()

        result, repo_index = runtime.engineer(
            repo_path=repo_root,
            task="Add a tiny health check",
            execution_mode="local",
            max_steps=1,
            force_rebuild=True,
        )
        run_path = Path(str(result["run_path"])).resolve()

        assert result["status"] == "model_unavailable"
        assert result["execution_mode"] == "local"
        assert result["workspace_root"] == ""
        assert repo_index.repo_root == repo_root.resolve()
    finally:
        _cleanup(workspace)
        _cleanup_run_path(run_path)


def test_apply_workspace_run_skips_protected_and_generated_paths() -> None:
    workspace = _workspace("apply-run-protected")
    repo_root = workspace / "repo"
    runtime = RepoAgentRuntime(Path.cwd())
    run_id = f"run_test_{uuid.uuid4().hex}"
    run_path = (runtime.runs_dir / run_id).resolve()
    workspace_root = run_path / "workspace"
    try:
        _write(repo_root / "src" / "app.py", "def answer():\n    return 1\n")
        _write(repo_root / ".git" / "config", "source git config\n")
        _write(repo_root / ".env", "OPENAI_API_KEY=source\n")

        _write(workspace_root / "src" / "app.py", "def answer():\n    return 2\n")
        _write(workspace_root / ".git" / "config", "workspace git config\n")
        _write(workspace_root / ".env", "OPENAI_API_KEY=workspace\n")
        _write(workspace_root / "reports" / "summary.txt", "generated report\n")

        _write(
            run_path / "run.json",
            json.dumps(
                {
                    "run_id": run_id,
                    "repo_root": str(workspace_root),
                    "source_repo_root": str(repo_root),
                    "workspace_root": str(workspace_root),
                    "execution_mode": "workspace",
                    "changed_files": [
                        "src/app.py",
                        ".git/config",
                        ".env",
                        "reports/summary.txt",
                    ],
                    "applied": False,
                    "trace": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

        result = runtime.apply_engineering_run(run_id, confirm=True)

        assert result["applied_files"] == ["src/app.py"]
        assert repo_root.joinpath("src", "app.py").read_text(encoding="utf-8") == "def answer():\n    return 2\n"
        assert repo_root.joinpath(".git", "config").read_text(encoding="utf-8") == "source git config\n"
        assert repo_root.joinpath(".env").read_text(encoding="utf-8") == "OPENAI_API_KEY=source\n"
        assert not repo_root.joinpath("reports", "summary.txt").exists()
    finally:
        _cleanup(workspace)
        _cleanup_run_path(run_path)


def test_verifier_and_reviewer_flag_unverified_changes() -> None:
    workspace = _workspace("agent-gates")
    repo_root = workspace / "repo"
    runs_dir = workspace / "runs"
    try:
        _write(repo_root / "server.js", "app.get('/health', health);\nfunction health(req, res) { res.send('ok'); }\n")
        repo_index = build_index(repo_root)
        agent = EngineeringAgent(repo_index, LLMClient(), runs_dir)
        run = EngineeringRun(
            run_id="run_test_gates",
            repo_root=str(repo_root),
            source_repo_root=str(repo_root),
            task="Change the health route",
            status="completed",
            model="",
            run_path=str(runs_dir / "run_test_gates"),
            changed_files=["server.js"],
            diff="--- a/server.js\n+++ b/server.js\n@@\n-app.get('/health', health);\n+app.get('/ready', health);",
        )
        Path(run.run_path).mkdir(parents=True)

        verifier = agent._verify_run(run)
        run.verifier_result = verifier
        reviewer = agent._review_run(run)

        assert verifier["status"] == "missing"
        assert any("without an observed verification" in item for item in verifier["warnings"])
        assert reviewer["status"] in {"needs_review", "high_risk"}
        assert reviewer["risk_score"] >= 0.38
        assert any(item["title"] == "Missing verification" for item in reviewer["findings"])
        assert any("Public surface" in item["title"] for item in reviewer["findings"])
    finally:
        _cleanup(workspace)


def test_finalize_auto_runs_inferred_verification_for_changed_files() -> None:
    workspace = _workspace("auto-verifier")
    repo_root = workspace / "repo"
    runs_dir = workspace / "runs"
    try:
        _write(repo_root / "app.py", "def answer():\n    return 42\n")
        _write(repo_root / "tests" / "test_app.py", "from app import answer\n\n\ndef test_answer():\n    assert answer() == 42\n")
        repo_index = build_index(repo_root)
        agent = EngineeringAgent(repo_index, LLMClient(), runs_dir)
        run = EngineeringRun(
            run_id="run_test_auto_verify",
            repo_root=str(repo_root),
            source_repo_root=str(repo_root),
            task="Change answer and verify the project",
            status="completed",
            model="",
            run_path=str(runs_dir / "run_test_auto_verify"),
            changed_files=["app.py", "tests/test_app.py"],
            diff="--- a/app.py\n+++ b/app.py\n@@\n-    return 41\n+    return 42\n",
        )
        Path(run.run_path).mkdir(parents=True)

        agent._finalize_run(run)

        assert run.verification
        assert run.verification[0]["command"] == "python -m pytest"
        assert run.verifier_result["status"] == "passed"
        assert any(item["phase"] == "verify_select" for item in run.timeline)
        assert any(item["phase"] == "verify_run" for item in run.timeline)
    finally:
        _cleanup(workspace)


def test_engineering_persist_recreates_missing_run_directory() -> None:
    workspace = _workspace("persist-missing-dir")
    repo_root = workspace / "repo"
    runs_dir = workspace / "runs"
    try:
        _write(repo_root / "app.py", "def answer():\n    return 42\n")
        repo_index = build_index(repo_root)
        agent = EngineeringAgent(repo_index, LLMClient(), runs_dir)
        run = EngineeringRun(
            run_id="run_test_missing_dir",
            repo_root=str(repo_root),
            source_repo_root=str(repo_root),
            task="Persist even if the run directory was cleaned",
            status="completed",
            model="",
            run_path=str(runs_dir / "run_test_missing_dir"),
        )

        agent._persist(run)

        run_json = Path(run.run_path) / "run.json"
        assert run_json.is_file()
        assert json.loads(run_json.read_text(encoding="utf-8"))["run_id"] == "run_test_missing_dir"
    finally:
        _cleanup(workspace)


def test_verifier_failure_analysis_and_file_risk_review() -> None:
    workspace = _workspace("failure-risk")
    repo_root = workspace / "repo"
    runs_dir = workspace / "runs"
    try:
        _write(repo_root / "app.py", "def answer():\n    return 41\n")
        repo_index = build_index(repo_root)
        agent = EngineeringAgent(repo_index, LLMClient(), runs_dir)
        run = EngineeringRun(
            run_id="run_test_failure_risk",
            repo_root=str(repo_root),
            source_repo_root=str(repo_root),
            task="Update public behavior",
            status="completed",
            model="",
            run_path=str(runs_dir / "run_test_failure_risk"),
            changed_files=["app.py"],
            verification=[
                {
                    "command": "python -m pytest",
                    "cwd": str(repo_root),
                    "exit_code": 1,
                    "stdout": "FAILED tests/test_app.py::test_answer - AssertionError\napp.py:2: AssertionError\n",
                    "stderr": "",
                }
            ],
            diff="--- a/app.py\n+++ b/app.py\n@@\n-    return 41\n+    return 42\n",
        )
        Path(run.run_path).mkdir(parents=True)

        verifier = agent._verify_run(run)
        run.verifier_result = verifier
        reviewer = agent._review_run(run)

        assert verifier["status"] == "failed"
        assert verifier["primary_failure"]["type"] == "test_failure"
        assert "tests/test_app.py::test_answer" in verifier["primary_failure"]["failed_tests"]
        assert "app.py" in verifier["primary_failure"]["referenced_files"]
        assert reviewer["file_risks"]
        assert reviewer["file_risks"][0]["relpath"] == "app.py"
        assert any("Rerun the failing verification" in item for item in reviewer["suggested_actions"])
    finally:
        _cleanup(workspace)


def _cleanup_run_path(run_path: Path | None) -> None:
    if run_path is None:
        return
    runs_root = (Path.cwd() / "runs").resolve()
    if run_path == runs_root or runs_root not in run_path.parents:
        return
    shutil.rmtree(run_path, ignore_errors=True)
