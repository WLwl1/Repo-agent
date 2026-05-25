from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from repo_agent.indexer import build_index
from repo_agent.security import is_safe_verification_command, safe_join
from repo_agent.tools import RepoTools


def _workspace(name: str) -> Path:
    root = Path.cwd() / "test-workspaces" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_safe_join_blocks_path_traversal() -> None:
    workspace = _workspace("safe-join-blocks")
    base = workspace / "repo"
    base.mkdir()

    try:
        with pytest.raises(ValueError, match="path traversal"):
            safe_join(base, "../outside.py")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_safe_join_allows_nested_repo_paths() -> None:
    workspace = _workspace("safe-join-allows")
    base = workspace / "repo"
    base.mkdir()

    try:
        assert safe_join(base, "src/app.py") == (base / "src" / "app.py").resolve()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest",
        "py -m pytest",
        "python -m repo_agent eval",
        "python -m compileall repo_agent tests",
        "py -m compileall repo_agent",
        "node --check web/app.js",
        "npm test",
        "npm run build",
        "uv run pytest",
    ],
)
def test_verification_command_policy_allows_expected_checks(command: str) -> None:
    assert is_safe_verification_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "python -c \"print(1)\"",
        "py -c \"print(1)\"",
        "node -e \"console.log(1)\"",
        "node --check ..\\outside.js",
        "python -m pip install requests",
        "python -m compileall ..",
        "npm exec eslint",
        "pnpm test",
        "pytest",
    ],
)
def test_verification_command_policy_blocks_arbitrary_execution(command: str) -> None:
    assert not is_safe_verification_command(command)


def test_repo_tools_block_protected_paths() -> None:
    workspace = _workspace("protected-tools")
    repo_root = workspace / "repo"
    try:
        (repo_root / ".git").mkdir(parents=True)
        (repo_root / "runs" / "run_1").mkdir(parents=True)
        (repo_root / "src").mkdir(parents=True)
        (repo_root / ".env").write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
        (repo_root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (repo_root / "runs" / "run_1" / "trace.md").write_text("generated\n", encoding="utf-8")
        (repo_root / "src" / "app.py").write_text("def ok():\n    return True\n", encoding="utf-8")

        tools = RepoTools(build_index(repo_root))

        with pytest.raises(ValueError, match="protected"):
            tools.read_file(".env")
        with pytest.raises(ValueError, match="protected"):
            tools.read_file(".git/config")
        with pytest.raises(ValueError, match="protected"):
            tools.write_file("runs/run_1/new.txt", "generated", overwrite=True)
        with pytest.raises(ValueError, match="protected"):
            tools.replace_text(".git/config", "[core]", "[user]")

        assert tools.read_file("src/app.py")["content"].startswith("def ok")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_replace_text_reports_actual_limited_replacements() -> None:
    workspace = _workspace("replace-count")
    repo_root = workspace / "repo"
    try:
        repo_root.mkdir()
        target = repo_root / "app.py"
        target.write_text("value = 1\nvalue = 1\nvalue = 1\n", encoding="utf-8")

        tools = RepoTools(build_index(repo_root))
        result = tools.replace_text("app.py", "value = 1", "value = 2", count=2)

        assert result["changed"] is True
        assert result["occurrences"] == 3
        assert result["replacements"] == 2
        assert target.read_text(encoding="utf-8").count("value = 2") == 2
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
