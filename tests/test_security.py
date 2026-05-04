from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from repo_agent.security import safe_join


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
