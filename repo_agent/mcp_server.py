from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .bundle import build_evidence_bundle
from .impact import analyze_impact
from .proof import replay_proof_bundle
from .runtime import RepoAgentRuntime


mcp = FastMCP(
    "repo-agent",
    instructions=(
        "Evidence-first repository localization. Use investigate_repository before editing, "
        "then replay_evidence_bundle when a saved proof must be checked against current code."
    ),
    json_response=True,
    stateless_http=True,
)


def _runtime() -> RepoAgentRuntime:
    project_root = (
        Path(os.environ.get("REPO_AGENT_PROJECT_ROOT", Path.cwd()))
        .expanduser()
        .resolve()
    )
    return RepoAgentRuntime(project_root)


def _investigate_repository(
    repo_path: str, question: str, top_k: int = 6
) -> dict[str, Any]:
    runtime = _runtime()
    result, repo_index = runtime.ask(repo_path, question, top_k=top_k, use_model=False)
    return {
        "query": result.query,
        "mode": result.mode,
        "answer": result.answer,
        "repository": str(repo_index.repo_root),
        "index": repo_index.stats(),
        "diagnostics": {
            "confidence": result.diagnostics.confidence if result.diagnostics else 0.0,
            "label": result.diagnostics.label if result.diagnostics else "unknown",
            "warnings": result.diagnostics.warnings if result.diagnostics else [],
        },
        "hits": [
            {
                "source": hit.chunk.source_label,
                "path": hit.chunk.relpath,
                "symbol": hit.chunk.symbol_name,
                "qualified_name": hit.chunk.qualified_name,
                "lines": [hit.chunk.start_line, hit.chunk.end_line],
                "score": round(hit.score, 4),
                "reasons": hit.reasons,
                "parser_backend": hit.chunk.parser_backend,
                "snippet": hit.chunk.text[:4000],
            }
            for hit in result.hits
        ],
        "proof": result.proof,
        "graph_search": result.graph_search,
    }


@mcp.tool()
def investigate_repository(
    repo_path: str, question: str, top_k: int = 6
) -> dict[str, Any]:
    """Locate relevant files and symbols and return ranked, proof-carrying evidence."""

    return _investigate_repository(repo_path, question, top_k=top_k)


@mcp.tool()
def repository_overview(repo_path: str) -> dict[str, Any]:
    """Return repository languages, parser backends, graph edge types, and important files."""

    repo_index = _runtime().load_index(repo_path)
    return repo_index.repository_overview(limit=20)


@mcp.tool()
def build_evidence_for_handoff(
    repo_path: str,
    question: str,
    target: str = "generic",
    top_k: int = 6,
) -> dict[str, Any]:
    """Build an in-memory evidence bundle suitable for another coding agent."""

    result, repo_index = _runtime().ask(
        repo_path, question, top_k=top_k, use_model=False
    )
    return build_evidence_bundle(result=result, repo_index=repo_index, target=target)


@mcp.tool()
def replay_evidence_bundle(bundle_path: str, strict: bool = True) -> dict[str, Any]:
    """Verify that a saved proof bundle still resolves against the current repository."""

    return replay_proof_bundle(Path(bundle_path).expanduser().resolve(), strict=strict)


@mcp.tool()
def analyze_change_impact(
    repo_path: str,
    question: str,
    target: str = "",
    max_depth: int = 3,
) -> dict[str, Any]:
    """Trace upstream/downstream impact from the best proved target or an explicit target."""

    result, repo_index = _runtime().ask(repo_path, question, top_k=6, use_model=False)
    selected_target = target or str(result.proof.get("top_hit", ""))
    if not selected_target and result.hits:
        selected_target = result.hits[0].chunk.source_label
    return analyze_impact(
        repo_index,
        target=selected_target,
        query=result.query,
        proof=result.proof,
        max_depth=max_depth,
    )


@mcp.resource("repo-agent://capabilities")
def capabilities() -> str:
    return json.dumps(
        {
            "retrieval": "BM25 + lexical intent + heterogeneous repository graph",
            "parsers": [
                "python-ast",
                "tree-sitter:javascript",
                "tree-sitter:typescript",
            ],
            "proof": ["bundle", "strict replay", "mutation testing", "impact analysis"],
            "transports": ["stdio", "streamable-http", "sse"],
        },
        ensure_ascii=False,
    )


def main() -> None:
    transport = os.environ.get("REPO_AGENT_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "streamable-http", "sse"}:
        raise ValueError(f"Unsupported MCP transport: {transport}")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
