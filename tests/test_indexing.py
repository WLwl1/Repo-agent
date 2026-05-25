from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from repo_agent.agent import RepoAgent
from repo_agent.cache import IndexCache
from repo_agent.indexer import build_index, expand_query_terms


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


def test_chinese_query_terms_expand_to_code_vocabulary() -> None:
    terms = expand_query_terms("聊天接口在哪里实现？")

    assert "聊天" in terms
    assert "chat" in terms
    assert "api" in terms
    assert "route" in terms
    assert "function" in terms


def test_chinese_web_style_query_targets_stylesheet() -> None:
    repo_root = _workspace("chinese-style-query")
    try:
        _write(repo_root / "web" / "index.html", '<link rel="stylesheet" href="styles.css">\n<div class="app"></div>\n')
        _write(repo_root / "web" / "styles.css", ".app {\n  color: red;\n}\n")
        _write(repo_root / "server.py", "def api_handler():\n    return {'ok': True}\n")

        repo_index = build_index(repo_root)
        result = repo_index.investigate("页面样式在哪里？", top_k=3)

        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "web/styles.css"
        assert result.mode == "repository_qa"
    finally:
        _cleanup(repo_root.parent)


def test_chinese_bug_query_uses_bug_localization_mode() -> None:
    repo_root = _workspace("chinese-bug-query")
    try:
        _write(
            repo_root / "server.js",
            """
function handleRequest(req, res) {
  try {
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        result = repo_index.investigate("报错时应该从哪里定位？", top_k=3)

        assert result.mode == "bug_localization"
        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "server.js"
    finally:
        _cleanup(repo_root.parent)


def test_chinese_agent_answer_is_readable_utf8() -> None:
    repo_root = _workspace("chinese-answer")
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

        result = RepoAgent(build_index(repo_root)).answer("聊天接口在哪里实现？", top_k=3)

        assert "## 结论" in result.answer
        assert "## 证据" in result.answer
        assert "最相关的位置" in result.answer
        assert "server.js" in result.answer
        assert "缁" not in result.answer
        assert "鎴" not in result.answer
    finally:
        _cleanup(repo_root.parent)


def test_agent_result_includes_evidence_diagnostics() -> None:
    repo_root = _workspace("evidence-diagnostics")
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

        result = RepoAgent(build_index(repo_root)).answer("Where is the chat endpoint implemented?", top_k=3)

        assert result.diagnostics is not None
        assert result.diagnostics.evidence_count == len(result.hits)
        assert result.diagnostics.confidence > 0
        assert result.diagnostics.label in {"low", "medium", "high"}
        assert result.diagnostics.top_score == round(result.hits[0].score, 2)
        assert "chat" in result.diagnostics.matched_terms
    finally:
        _cleanup(repo_root.parent)
