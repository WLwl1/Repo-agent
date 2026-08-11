from __future__ import annotations

from pathlib import Path

from repo_agent.agent import RepoAgent
from repo_agent.indexer import build_index
from repo_agent.report import write_html_report
from repo_agent.runtime import RepoAgentRuntime
from repo_agent.server import _file_response_headers, _public_impact_payload, _resolve_static_dir


def test_static_assets_resolve_from_source_tree() -> None:
    project_root = Path(__file__).resolve().parents[1]

    static_dir = _resolve_static_dir(project_root)

    assert (static_dir / "index.html").is_file()
    assert (static_dir / "app.js").is_file()
    assert (static_dir / "styles.css").is_file()


def test_web_studio_assets_expose_impact_workflow() -> None:
    project_root = Path(__file__).resolve().parents[1]
    static_dir = _resolve_static_dir(project_root)

    index_text = (static_dir / "index.html").read_text(encoding="utf-8")
    app_text = (static_dir / "app.js").read_text(encoding="utf-8")

    assert "buildImpactBtn" in index_text
    assert "impactLink" in index_text
    assert "evidenceFilterInput" in index_text
    assert "evidenceFilterClearBtn" in index_text
    assert "/api/impact" in app_text
    assert "renderImpact" in app_text
    assert "filteredEvidenceEntries" in app_text
    assert "clearEvidenceFilter" in app_text
    assert "handleSelectionPanelClick" in app_text
    assert "data-selection-action=\"open-file\"" in app_text


def test_static_file_response_headers_are_cache_safe(tmp_path: Path) -> None:
    asset = tmp_path / "app.js"
    data = b"console.log('repo-agent');\n"
    asset.write_bytes(data)

    headers = _file_response_headers(asset, "application/javascript", content_length=len(data))

    assert headers["Content-Type"] == "application/javascript; charset=utf-8"
    assert headers["Content-Length"] == str(len(data))
    assert headers["Cache-Control"] == "no-cache"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["ETag"].startswith('W/"')
    assert headers["ETag"].endswith('"')


def test_web_studio_index_has_clean_fallback_copy() -> None:
    project_root = Path(__file__).resolve().parents[1]
    static_dir = _resolve_static_dir(project_root)

    index_text = (static_dir / "index.html").read_text(encoding="utf-8")

    assert "Repository Evidence Studio" in index_text
    assert "Click an evidence card to inspect details." in index_text
    assert "Generate Impact" in index_text
    assert "Filter evidence by file, symbol, reason, or term" in index_text
    assert ">Clear<" in index_text
    assert "View navigation" in index_text
    assert "鍛" not in index_text
    assert "璇" not in index_text
    assert "鎶" not in index_text
    assert "?/span" not in index_text
    assert "?/div" not in index_text


def test_server_result_payload_includes_graph_search(tmp_path: Path) -> None:
    from repo_agent.server import _serialize_result

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "server.js").write_text(
        """
const express = require('express');
const app = express();
app.post('/api/chat', handleChat);
function handleChat(req, res) {
  res.json({ ok: true });
}
""".strip(),
        encoding="utf-8",
    )
    repo_index = build_index(repo_root)
    result = RepoAgent(repo_index).answer("Where is the chat handler function?", top_k=3)

    payload = _serialize_result(result, repo_index.stats())

    assert payload["graph_search"]["iterations"] > 0
    assert payload["graph_search"]["top_visited"]
    assert payload["proof"]["strategy"] == "proof_carrying_retrieval"
    assert payload["proof"]["checks"]
    assert payload["proof"]["proof_graph"]["nodes"]
    assert "decoy_audit" in payload["proof"]


def test_runtime_generate_impact_writes_report(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())

    payload, impact_path, result, repo_index = runtime.generate_impact(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        force_rebuild=True,
        output_path=tmp_path / "impact.md",
    )
    public_payload = _public_impact_payload(payload)

    assert payload["status"] == "analyzed"
    assert payload["impact_summary"]["risk_level"] == "high"
    assert public_payload["impact_summary"]["exposed_route_count"] >= 1
    assert public_payload["markdown"].startswith("# Repo Agent Proof-Guided Impact Analysis")
    assert impact_path.is_file()
    assert result.proof["status"] == "proved"
    assert repo_index.stats()["graph_edge_count"] > 0


def test_html_report_includes_proof_carrying_retrieval(tmp_path: Path) -> None:
    repo_root = Path.cwd() / "examples" / "counterfactual_agent_app"
    repo_index = build_index(repo_root)
    result = RepoAgent(repo_index).answer(
        "Which function finally writes streamed tokens for the public /api/chat endpoint?",
        top_k=5,
    )
    output_path = tmp_path / "proof-report.html"

    write_html_report(
        query=result.query,
        result=result,
        repo_stats=repo_index.stats(),
        file_facts=repo_index.file_facts,
        output_path=output_path,
    )

    text = output_path.read_text(encoding="utf-8")

    assert "Proof-Carrying Retrieval" in text
    assert "status <code>proved</code>" in text
    assert "top_hit_on_route_path" in text
    assert "Proof graph" in text
    assert "Contrastive Decoy Audit" in text
    assert "decoy candidates" in text
    assert "server.js:writeChatDelta" in text
    assert "admin" in text.lower()
