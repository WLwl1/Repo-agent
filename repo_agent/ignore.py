from __future__ import annotations

from pathlib import Path, PurePosixPath


IGNORED_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".pytest_tmp",
    ".ruff_cache",
    ".tmp",
    ".venv",
    ".vs",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "reports",
    "runs",
    "test-tmp",
    "test-workspaces",
    "venv",
}

IGNORED_FILES = {
    ".env",
    ".env.development",
    ".env.local",
    ".env.production",
}


def has_ignored_part(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def relpath_has_ignored_part(relpath: str) -> bool:
    normalized = str(relpath or "").replace("\\", "/")
    return any(part in IGNORED_DIRS for part in PurePosixPath(normalized).parts)
