from __future__ import annotations

import json
from pathlib import Path

from repo_agent.core_bench import build_core_bench_split_audit, evaluate_core_bench, load_jsonl


def _dataset(repository_count: int = 20, queries_per_repository: int = 10) -> dict:
    corpus = []
    queries = []
    qrels = {}
    for repo_index in range(repository_count):
        repository = f"org/repo-{repo_index}"
        document_id = f"doc-{repo_index}"
        corpus.append({"id": document_id, "text": f"target implementation {repo_index}", "title": "target", "path": "src/service.py", "metadata": repository, "repository": repository})
        for query_index in range(queries_per_repository):
            query_id = f"query-{repo_index}-{query_index}"
            queries.append({"id": query_id, "text": f"target implementation {repo_index}", "repository": repository})
            qrels[query_id] = {document_id: 1.0}
    return {"corpus": corpus, "queries": queries, "qrels": qrels, "source": {"name": "test"}}


def test_core_bench_external_gate_passes_20_repositories_and_200_queries() -> None:
    audit = build_core_bench_split_audit(_dataset(), seed=17)
    assert audit["status"] == "pass"
    assert audit["metrics"]["case_count"] == 200
    assert audit["metrics"]["repository_count"] == 20


def test_core_bench_evaluation_reports_repository_split_audit() -> None:
    payload = evaluate_core_bench(_dataset(), methods=["bm25"], top_k=5, split_seed=17)
    assert payload["methods"]["bm25"]["hit_at_1"] == 1.0
    assert payload["repository_split_audit"]["status"] == "pass"


def test_jsonl_loader_preserves_unicode_line_separator_inside_string(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(json.dumps({"id": "q1", "text": "before\u2028after"}, ensure_ascii=False) + "\n", encoding="utf-8")
    assert load_jsonl(path)[0]["text"] == "before\u2028after"
