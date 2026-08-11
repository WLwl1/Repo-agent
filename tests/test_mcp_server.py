from __future__ import annotations

import json
from pathlib import Path

from repo_agent.mcp_server import _investigate_repository, capabilities


def test_mcp_investigation_returns_grounded_structural_evidence() -> None:
    repo = Path("examples/simple_fastapi_app").resolve()

    payload = _investigate_repository(
        str(repo), "Where is the chat route implemented?", top_k=3
    )

    assert payload["hits"]
    assert payload["hits"][0]["path"] == "app.py"
    assert payload["hits"][0]["parser_backend"] == "python-ast"
    assert payload["index"]["retrieval_backend"] == "multi-view-bm25+weighted-rrf+graph"
    assert payload["index"]["retrieval_backend_active"].startswith("multi-view-bm25+")
    assert payload["index"]["retrieval_views"] == ["content", "identifier", "path", "structure"]
    assert payload["index"]["graph_search_strategy"] == "personalized_pagerank"
    assert payload["proof"]["strategy"] == "proof_carrying_retrieval"


def test_mcp_capability_resource_describes_modern_backends() -> None:
    payload = json.loads(capabilities())

    assert payload["retrieval"].startswith("BM25")
    assert "tree-sitter:typescript" in payload["parsers"]
    assert "streamable-http" in payload["transports"]
