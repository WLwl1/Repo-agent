"""CORE-Bench-compatible corpus/query/qrels evaluation.

The evaluator intentionally works on exported JSONL files and does not require
the Hugging Face datasets runtime.  This keeps experiments reproducible in
the lightweight Repo Agent environment while matching the standard IR shape:
documents, queries, and graded relevance judgments.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .indexer import tokenize
from .retrieval import BM25Index, MultiViewBM25Index, weighted_reciprocal_rank_fusion
from .research_protocol import DEFAULT_SPLIT_SEED, assign_repository_splits, audit_external_suite, freeze_test_partition


DECLARATION_RE = re.compile(r"\b(?:async\s+def|def|class|function|fn|struct|enum|interface|trait)\s+([A-Za-z_$][\w$]*)")
CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
IMPORT_RE = re.compile(r"\b(?:from|import|use|require)\s+([A-Za-z_$][\w$.:/]*)")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as handle:
        return [dict(json.loads(line)) for line in handle if line.strip()]


def load_core_bench(corpus_path: Path, queries_path: Path, qrels_path: Path) -> dict[str, Any]:
    corpus = load_jsonl(corpus_path)
    queries = load_jsonl(queries_path)
    qrels = load_jsonl(qrels_path)
    documents = [_document_record(item, index) for index, item in enumerate(corpus)]
    query_records = [_query_record(item, index) for index, item in enumerate(queries)]
    judgments: dict[str, dict[str, float]] = {}
    for index, item in enumerate(qrels):
        query_id = _first(item, "query_id", "qid", "query", "id") or f"q{index}"
        document_id = _first(item, "corpus_id", "doc_id", "document_id", "pid")
        if document_id is None:
            continue
        relevance = float(item.get("relevance", item.get("score", item.get("label", 1))))
        judgments.setdefault(query_id, {})[document_id] = relevance
    return {
        "corpus": documents,
        "queries": query_records,
        "qrels": judgments,
        "source": {
            "corpus": str(corpus_path),
            "queries": str(queries_path),
            "qrels": str(qrels_path),
        },
    }


def evaluate_core_bench(
    dataset: dict[str, Any],
    *,
    methods: Iterable[str] = ("bm25", "multiview_rrf"),
    top_k: int = 10,
    split_seed: int = DEFAULT_SPLIT_SEED,
) -> dict[str, Any]:
    documents = list(dataset.get("corpus") or [])
    queries = list(dataset.get("queries") or [])
    qrels = dict(dataset.get("qrels") or {})
    global_indexes = _build_indexes(documents)
    documents_by_repository: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        repository = str(document.get("repository") or "").strip()
        if repository:
            documents_by_repository[repository].append(document)
    repository_indexes = {repository: _build_indexes(rows) for repository, rows in documents_by_repository.items()}
    method_results: dict[str, Any] = {}
    for method in methods:
        started = time.perf_counter()
        cases: list[dict[str, Any]] = []
        for query in queries:
            query_id = str(query["id"])
            query_text = str(query.get("text", ""))
            repository = str(query.get("repository") or "").strip()
            bm25, multiview, ids = repository_indexes.get(repository, global_indexes)
            candidate_ids = {str(value) for value in query.get("candidate_ids") or []}
            ranking = _rank(method, query_text, bm25, multiview, ids, top_k, candidate_ids=candidate_ids)
            relevance = qrels.get(query_id, {})
            case = _case_metrics(query_id, ranking, relevance, top_k)
            case["repository"] = repository
            cases.append(case)
        method_results[method] = _aggregate_method(cases, time.perf_counter() - started)
    split_audit = build_core_bench_split_audit(dataset, seed=split_seed)
    return {
        "schema_version": "1.0",
        "benchmark": "CORE-Bench-compatible",
        "corpus_count": len(documents),
        "query_count": len(queries),
        "judged_query_count": sum(1 for query in queries if str(query["id"]) in qrels),
        "top_k": top_k,
        "methods": method_results,
        "paired_statistics": _paired_statistics(method_results),
        "repository_split_audit": split_audit,
        "source": dataset.get("source", {}),
    }


def write_core_bench_report(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def evaluate_core_bench_directory(
    dataset_root: Path,
    *,
    methods: Iterable[str] = ("bm25", "multiview_rrf"),
    top_k: int = 100,
) -> dict[str, Any]:
    """Evaluate repository folders one at a time to bound peak memory."""

    method_names = list(methods)
    collected: dict[str, list[dict[str, Any]]] = {method: [] for method in method_names}
    elapsed: dict[str, float] = {method: 0.0 for method in method_names}
    repositories: list[str] = []
    for repository_dir in sorted(path for path in dataset_root.iterdir() if path.is_dir()):
        corpus_path = repository_dir / "corpus.jsonl"
        queries_path = repository_dir / "queries.jsonl"
        qrels_path = repository_dir / "qrels.jsonl"
        if not all(path.exists() for path in (corpus_path, queries_path, qrels_path)):
            continue
        dataset = load_core_bench(corpus_path, queries_path, qrels_path)
        for query in dataset["queries"]:
            query["repository"] = repository_dir.name
        for document in dataset["corpus"]:
            document["repository"] = repository_dir.name
        result = evaluate_core_bench(dataset, methods=method_names, top_k=top_k)
        repositories.append(repository_dir.name)
        for method in method_names:
            method_payload = result["methods"][method]
            collected[method].extend(method_payload["cases"])
            elapsed[method] += float(method_payload["elapsed_seconds"])
    method_results = {method: _aggregate_method(collected[method], elapsed[method]) for method in method_names}
    return {
        "schema_version": "1.0",
        "benchmark": "CORE-Bench Level-2 repository-streaming subset",
        "dataset_root": str(dataset_root),
        "repository_count": len(repositories),
        "repositories": repositories,
        "query_count": len(next(iter(collected.values()), [])),
        "top_k": top_k,
        "methods": method_results,
        "paired_statistics": _paired_statistics(method_results),
        "per_repository": _per_repository_metrics(method_results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Repo Agent on CORE-Bench JSONL exports.")
    parser.add_argument("--dataset-root", type=Path, help="Root containing per-repository corpus/queries/qrels folders.")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--methods", default="bm25,multiview_rrf")
    parser.add_argument("--top-k", default=10, type=int)
    parser.add_argument("--split-seed", default=DEFAULT_SPLIT_SEED, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    methods = [item.strip() for item in args.methods.split(",") if item.strip()]
    if args.dataset_root:
        payload = evaluate_core_bench_directory(args.dataset_root, methods=methods, top_k=max(1, args.top_k))
    else:
        if not all((args.corpus, args.queries, args.qrels)):
            parser.error("provide --dataset-root or all of --corpus/--queries/--qrels")
        payload = evaluate_core_bench(
            load_core_bench(args.corpus, args.queries, args.qrels),
            methods=methods,
            top_k=max(1, args.top_k),
            split_seed=args.split_seed,
        )
    write_core_bench_report(payload, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _document_record(item: dict[str, Any], index: int) -> dict[str, Any]:
    document_id = _first(item, "id", "_id", "doc_id", "corpus_id") or f"doc_{index}"
    text = _first(item, "text", "contents", "content", "code") or ""
    repository = _first(item, "repo", "repository", "repository_name") or ""
    metadata = item.get("metadata", item.get("repo", item.get("repository", "")))
    title = _first(item, "title", "symbol", "name") or " ".join(DECLARATION_RE.findall(text))
    structure = " ".join(CALL_RE.findall(text) + IMPORT_RE.findall(text))
    return {
        "id": document_id,
        "text": text,
        "title": title,
        "path": _first(item, "path", "file_path", "filepath") or "",
        "metadata": f"{metadata} {structure}".strip(),
        "repository": repository,
    }


def _query_record(item: dict[str, Any], index: int) -> dict[str, Any]:
    query_id = _first(item, "id", "_id", "query_id", "qid") or f"query_{index}"
    text = _first(item, "text", "query", "question", "problem_statement") or ""
    candidate_ids = item.get("filtered_corpus_id") or item.get("candidate_ids") or []
    return {
        "id": query_id,
        "text": text,
        "repository": _first(item, "repo", "repository", "repository_name") or "",
        "candidate_ids": [str(value) for value in candidate_ids] if isinstance(candidate_ids, list) else [],
    }


def build_core_bench_split_audit(dataset: dict[str, Any], *, seed: int = DEFAULT_SPLIT_SEED) -> dict[str, Any]:
    """Build a repository-disjoint audit from generic CORE-Bench exports.

    CORE-Bench releases may store the repository on the query, on the corpus
    document, or inside metadata.  Queries without an identifiable repository
    are reported as a blocked condition instead of being silently mixed into a
    split.
    """

    documents = list(dataset.get("corpus") or [])
    queries = list(dataset.get("queries") or [])
    qrels = dict(dataset.get("qrels") or {})
    doc_repositories = {str(doc.get("id")): str(doc.get("repository") or "").strip() for doc in documents}
    cases: list[dict[str, Any]] = []
    missing: list[str] = []
    for query in queries:
        query_id = str(query.get("id", ""))
        repository = str(query.get("repository") or "").strip()
        if not repository:
            repositories = {doc_repositories.get(str(doc_id), "") for doc_id in qrels.get(query_id, {})}
            repositories.discard("")
            if len(repositories) == 1:
                repository = next(iter(repositories))
        if not repository:
            missing.append(query_id)
            continue
        cases.append({"id": query_id, "repo": repository, "metadata": {"source_repository": repository}})
    if len({str(case["repo"]) for case in cases}) < 3:
        return {
            "status": "blocked_external_validity",
            "reason": "fewer than three repositories with query-level identities",
            "query_count": len(queries),
            "repository_count": len({str(case["repo"]) for case in cases}),
            "missing_repository_query_ids": missing[:50],
        }
    split_cases = assign_repository_splits(cases, seed=seed)
    suite: dict[str, Any] = {"source": "external:CORE-Bench", "cases": split_cases}
    suite["freeze"] = freeze_test_partition(suite)
    audit = audit_external_suite(
        suite,
        minimum_cases=200,
        minimum_repositories=20,
    )
    audit["missing_repository_query_ids"] = missing[:50]
    audit["query_count"] = len(queries)
    audit["repository_count"] = len({str(case["repo"]) for case in split_cases})
    return audit


def _rank(
    method: str,
    query: str,
    bm25: BM25Index,
    multiview: MultiViewBM25Index,
    ids: list[str],
    top_k: int,
    *,
    candidate_ids: set[str] | None = None,
) -> list[str]:
    terms = tokenize(query)
    if method == "bm25":
        scores = bm25.scores(terms)
        if candidate_ids:
            scores = {item: score for item, score in scores.items() if item in candidate_ids}
        return sorted(scores, key=lambda item: (-scores[item], item))[:top_k]
    if method == "multiview_rrf":
        scores = multiview.scores(terms)
        if candidate_ids:
            scores = {item: score for item, score in scores.items() if item in candidate_ids}
        return sorted(scores, key=lambda item: (-scores[item], item))[:top_k]
    if method in {"content_identifier_rrf", "content_structure_rrf"}:
        selected_views = {
            "content_identifier_rrf": {"content", "identifier"},
            "content_structure_rrf": {"content", "structure"},
        }[method]
        rankings = []
        for name, ranking, weight in multiview.rankings(terms):
            if name not in selected_views:
                continue
            if candidate_ids:
                ranking = [item for item in ranking if item in candidate_ids]
            if ranking:
                rankings.append((ranking, weight))
        fused = weighted_reciprocal_rank_fusion(rankings, rank_constant=30)
        return sorted(fused, key=lambda item: (-fused[item], item))[:top_k]
    if method == "bm25_rrf_multiview":
        base = bm25.scores(terms)
        view = multiview.scores(terms)
        if candidate_ids:
            base = {item: score for item, score in base.items() if item in candidate_ids}
            view = {item: score for item, score in view.items() if item in candidate_ids}
        base_ranking = sorted(base, key=lambda item: (-base[item], item))
        view_ranking = sorted(view, key=lambda item: (-view[item], item))
        fused = weighted_reciprocal_rank_fusion(
            [(base_ranking, 1.0), (view_ranking, 1.0)], rank_constant=30
        )
        return sorted(fused, key=lambda item: (-fused[item], item))[:top_k]
    raise ValueError(f"unsupported CORE-Bench method: {method}")


def _build_indexes(documents: list[dict[str, Any]]) -> tuple[BM25Index, MultiViewBM25Index, list[str]]:
    ids = [str(item["id"]) for item in documents]
    content_docs = [tokenize(str(item.get("text", ""))) for item in documents]
    bm25 = BM25Index(ids, content_docs)
    multiview = MultiViewBM25Index(
        ids,
        {
            "content": content_docs,
            "identifier": [tokenize(str(item.get("title", ""))) for item in documents],
            "path": [tokenize(str(item.get("path", ""))) for item in documents],
            "structure": [tokenize(str(item.get("metadata", ""))) for item in documents],
        },
        weights={"content": 1.0, "identifier": 1.8, "path": 1.1, "structure": 1.25},
        rank_constant=30,
    )
    return bm25, multiview, ids


def _case_metrics(query_id: str, ranking: list[str], relevance: dict[str, float], top_k: int) -> dict[str, Any]:
    relevant = {str(document_id): float(score) for document_id, score in relevance.items() if float(score) > 0}
    rank = next((index for index, document_id in enumerate(ranking, start=1) if document_id in relevant), None)
    hits = [document_id for document_id in ranking[:100] if document_id in relevant]
    ranking_at_10 = ranking[:10]
    dcg = sum((2 ** relevant[document_id] - 1) / math.log2(index + 2) for index, document_id in enumerate(ranking_at_10) if document_id in relevant)
    ideal = sorted(relevant.values(), reverse=True)[:10]
    idcg = sum((2 ** score - 1) / math.log2(index + 2) for index, score in enumerate(ideal))
    precision_sum = 0.0
    relevant_seen = 0
    for index, document_id in enumerate(ranking[:100], start=1):
        if document_id in relevant:
            relevant_seen += 1
            precision_sum += relevant_seen / index
    return {
        "query_id": query_id,
        "rank": rank,
        "hit_at_1": bool(rank == 1),
        "hit_at_3": bool(rank is not None and rank <= 3),
        "hit_at_5": bool(rank is not None and rank <= 5),
        "mrr": 1.0 / rank if rank else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
        "ndcg_at_10": dcg / idcg if idcg else 0.0,
        "recall_at_100": len(hits) / len(relevant) if relevant else 0.0,
        "map_at_100": precision_sum / len(relevant) if relevant else 0.0,
        "retrieved_relevant": len(hits),
        "relevant_count": len(relevant),
        "top_hit": ranking[0] if ranking else "",
    }


def _aggregate_method(cases: list[dict[str, Any]], elapsed_seconds: float) -> dict[str, Any]:
    count = max(1, len(cases))
    return {
        "query_count": len(cases),
        "hit_at_1": sum(item["hit_at_1"] for item in cases) / count,
        "hit_at_3": sum(item["hit_at_3"] for item in cases) / count,
        "hit_at_5": sum(item["hit_at_5"] for item in cases) / count,
        "mrr": sum(item["mrr"] for item in cases) / count,
        "ndcg": sum(item["ndcg"] for item in cases) / count,
        "ndcg_at_10": sum(item["ndcg_at_10"] for item in cases) / count,
        "recall_at_100": sum(item["recall_at_100"] for item in cases) / count,
        "map_at_100": sum(item["map_at_100"] for item in cases) / count,
        "queries_per_second": len(cases) / elapsed_seconds if elapsed_seconds else 0.0,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "cases": cases,
    }


def _paired_statistics(method_results: dict[str, Any], baseline: str = "bm25", *, samples: int = 2000) -> dict[str, Any]:
    if baseline not in method_results:
        return {}
    base = {str(case["query_id"]): case for case in method_results[baseline]["cases"]}
    output: dict[str, Any] = {}
    for method, payload in method_results.items():
        if method == baseline:
            continue
        other = {str(case["query_id"]): case for case in payload["cases"]}
        common = sorted(base.keys() & other.keys())
        metrics: dict[str, Any] = {}
        for metric in ("ndcg_at_10", "recall_at_100", "mrr"):
            deltas = [float(other[key][metric]) - float(base[key][metric]) for key in common]
            metrics[metric] = _bootstrap_delta(deltas, samples=samples, seed=DEFAULT_SPLIT_SEED)
        ndcg_deltas = [float(other[key]["ndcg_at_10"]) - float(base[key]["ndcg_at_10"]) for key in common]
        output[method] = {
            "baseline": baseline,
            "paired_query_count": len(common),
            "metrics": metrics,
            "wins": sum(delta > 1e-12 for delta in ndcg_deltas),
            "ties": sum(abs(delta) <= 1e-12 for delta in ndcg_deltas),
            "losses": sum(delta < -1e-12 for delta in ndcg_deltas),
        }
    return output


def _bootstrap_delta(deltas: list[float], *, samples: int, seed: int) -> dict[str, Any]:
    if not deltas:
        return {"mean_delta": 0.0, "ci95": [0.0, 0.0], "significant": False}
    rng = random.Random(seed)
    means = sorted(sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas) for _ in range(samples))
    lower = means[int(0.025 * (len(means) - 1))]
    upper = means[int(0.975 * (len(means) - 1))]
    mean = sum(deltas) / len(deltas)
    return {"mean_delta": mean, "ci95": [lower, upper], "significant": lower > 0.0 or upper < 0.0}


def _per_repository_metrics(method_results: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for method, payload in method_results.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in payload["cases"]:
            grouped[str(case.get("repository", ""))].append(case)
        output[method] = {
            repository: {
                "query_count": len(cases),
                "ndcg_at_10": sum(float(case["ndcg_at_10"]) for case in cases) / len(cases),
                "recall_at_100": sum(float(case["recall_at_100"]) for case in cases) / len(cases),
            }
            for repository, cases in sorted(grouped.items())
        }
    return output


def _first(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


if __name__ == "__main__":
    main()
