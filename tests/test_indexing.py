from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from repo_agent.cache import IndexCache
from repo_agent.indexer import build_index


def _workspace(name: str) -> Path:
    root = Path.cwd() / "test-workspaces" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_index_ignores_generated_directories() -> None:
    repo_root = _workspace("index-ignore")
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
        _write(
            repo_root / "runs" / "run_123" / "workspace" / "server.js",
            "app.post('/api/chat', handleChat); function handleChat(req, res) { res.send('generated'); }",
        )
        _write(repo_root / "reports" / "report.py", "def generated_report():\n    return 'ignore me'\n")

        repo_index = build_index(repo_root)
        relpaths = {fact.relpath for fact in repo_index.file_facts}

        assert "app.py" in relpaths
        assert all(not relpath.startswith(("runs/", "reports/")) for relpath in relpaths)
        assert all(not chunk.relpath.startswith(("runs/", "reports/")) for chunk in repo_index.chunks)
    finally:
        _cleanup(repo_root.parent)


def test_cache_signature_ignores_generated_directories() -> None:
    workspace = _workspace("cache-ignore")
    repo_root = workspace / "repo"
    cache_root = workspace / "cache"
    try:
        _write(repo_root / "app.py", "def answer():\n    return 42\n")

        cache = IndexCache(cache_root)
        first_signature = cache.signature_for(repo_root)

        _write(repo_root / ".cache" / "index.py", "def generated():\n    return 'noise'\n")
        _write(repo_root / "runs" / "run_123" / "workspace" / "app.py", "def generated():\n    return 'noise'\n")

        assert cache.signature_for(repo_root) == first_signature

        _write(repo_root / "app.py", "def answer():\n    return 43\n")

        assert cache.signature_for(repo_root) != first_signature
    finally:
        _cleanup(workspace)
