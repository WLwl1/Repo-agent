from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from repo_agent.indexer import build_index
from repo_agent.proof import proof_bundle_fingerprint, render_replay_markdown, replay_proof


def _bundle(repo_root: Path) -> dict:
    return {
        "schema_version": "1.1",
        "target": "generic",
        "created_at": "2026-01-01T00:00:00+00:00",
        "repository": {
            "root": str(repo_root),
            "stats": {"file_count": 1, "chunk_count": 1, "graph_edge_count": 0},
        },
        "query": "Where is the answer function?",
        "mode": "graph_mcts",
        "diagnostics": {"confidence": 0.9},
        "graph_search": {"iterations": 1, "top_visited": ["app.py:answer"]},
        "proof": {
            "status": "proved",
            "strategy": "proof_carrying_retrieval",
            "top_hit": "app.py:answer",
            "route_literals": [],
            "supporting_paths": [],
            "proof_graph": {"nodes": [], "edges": []},
            "decoy_audit": [],
        },
        "evidence": [
            {
                "rank": 1,
                "source_label": "app.py:answer",
                "relpath": "app.py",
                "symbol_name": "answer",
                "symbol_kind": "function",
                "start_line": 1,
                "end_line": 2,
                "score": 1.0,
                "matched_terms": ["answer"],
                "reasons": ["symbol match"],
                "snippet": "def answer():\n    return 42\n",
            }
        ],
        "graph_edges": [],
    }


def test_proof_bundle_fingerprint_ignores_local_path_and_created_at(tmp_path: Path) -> None:
    left = _bundle(tmp_path / "left")
    right = deepcopy(left)
    right["created_at"] = "2026-07-07T23:59:00+08:00"
    right["repository"]["root"] = str(tmp_path / "right")

    assert proof_bundle_fingerprint(left)["value"] == proof_bundle_fingerprint(right)["value"]


def test_proof_bundle_fingerprint_changes_when_proof_changes(tmp_path: Path) -> None:
    original = _bundle(tmp_path / "repo")
    mutated = deepcopy(original)
    mutated["proof"]["top_hit"] = "app.py:other_answer"

    assert proof_bundle_fingerprint(original)["value"] != proof_bundle_fingerprint(mutated)["value"]


def test_replay_proof_reports_bundle_fingerprint(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    repo_index = build_index(repo_root)
    bundle = _bundle(repo_root)

    payload = replay_proof(bundle, repo_index, strict=True)
    markdown = render_replay_markdown(payload)

    assert payload["status"] == "valid"
    assert payload["bundle_fingerprint"]["algorithm"] == "sha256"
    assert payload["bundle_fingerprint"]["scope"] == "stable_proof_evidence"
    assert len(payload["bundle_fingerprint"]["value"]) == 64
    assert "Bundle fingerprint:" in markdown
    assert payload["bundle_fingerprint"]["value"] in markdown
