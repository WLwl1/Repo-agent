from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

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
    finally:
        _cleanup(workspace)


def test_runtime_health_exposes_agent_policy() -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    policy = runtime.health()["agent_policy"]

    assert policy["execution_modes"]["recommended_default"] == "workspace"
    assert ".env" in policy["repository_access"]["protected_files"]
    assert ".git" in policy["repository_access"]["protected_dirs"]
    assert "python -m pytest" in policy["tooling"]["allowed_verification_commands"]
    assert "shell=False" in policy["tooling"]["command_execution"]
