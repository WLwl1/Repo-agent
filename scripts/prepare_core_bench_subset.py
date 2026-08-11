"""Prepare a pinned, repository-disjoint CORE-Bench Level-2 subset.

The committed manifest contains only repository and query identifiers. Raw
queries, qrels, and optional corpora stay in the user-selected output folder.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from repo_agent.research_protocol import (
    DEFAULT_SPLIT_SEED,
    PROTOCOL_ID,
    assign_repository_splits,
    audit_external_suite,
    freeze_test_partition,
    split_summary,
)


DATASET_ID = "zhangfw123/CORE-Bench"
DATASET_REVISION = "23aee66caabfcd8fec37cb5518c96ae43069460a"
DEFAULT_API_URL = "https://huggingface.co/api/datasets/zhangfw123/CORE-Bench"
DEFAULT_RESOLVE_URL = "https://huggingface.co/datasets/zhangfw123/CORE-Bench/resolve"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest-output", required=True, type=Path)
    parser.add_argument("--subdataset", default="Multi-SWE-bench")
    parser.add_argument("--repository-count", type=int, default=20)
    parser.add_argument("--query-count", type=int, default=200)
    parser.add_argument("--split-seed", type=int, default=DEFAULT_SPLIT_SEED)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--resolve-url", default=DEFAULT_RESOLVE_URL)
    parser.add_argument("--revision", default=DATASET_REVISION)
    parser.add_argument("--include-corpus", action="store_true")
    args = parser.parse_args()
    payload = prepare_subset(
        output_dir=args.output_dir,
        subdataset=args.subdataset,
        repository_count=max(3, args.repository_count),
        query_count=max(1, args.query_count),
        split_seed=args.split_seed,
        api_url=args.api_url,
        resolve_url=args.resolve_url,
        revision=args.revision,
        include_corpus=args.include_corpus,
    )
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["external_validity_audit"], ensure_ascii=False, indent=2))
    if payload["external_validity_audit"]["status"] != "pass":
        raise SystemExit(2)


def prepare_subset(
    *,
    output_dir: Path,
    subdataset: str,
    repository_count: int,
    query_count: int,
    split_seed: int,
    api_url: str,
    resolve_url: str,
    revision: str,
    include_corpus: bool,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = _read_json(api_url)
    if str(metadata.get("sha", "")) != revision:
        raise ValueError(f"dataset revision mismatch: expected {revision}, received {metadata.get('sha', '')}")
    prefix = f"data/LEVEL-2/{subdataset}/"
    repositories = sorted(
        {
            str(item["rfilename"])[len(prefix) :].split("/", 1)[0]
            for item in metadata.get("siblings", [])
            if str(item.get("rfilename", "")).startswith(prefix) and str(item.get("rfilename", "")).endswith("/queries.jsonl")
        },
        key=lambda repo: hashlib.sha256(f"{revision}:{repo}".encode()).hexdigest(),
    )
    selected_queries: list[dict[str, Any]] = []
    selected_qrels: list[dict[str, Any]] = []
    selected_repositories: list[str] = []
    downloaded: list[dict[str, Any]] = []
    remaining = query_count
    for repository in repositories:
        if len(selected_repositories) >= repository_count and remaining <= 0:
            break
        repo_prefix = f"{prefix}{repository}"
        cached_queries = output_dir / repository / "queries.jsonl"
        cached_qrels = output_dir / repository / "qrels.jsonl"
        queries_bytes = cached_queries.read_bytes() if cached_queries.exists() else _download(resolve_url, revision, f"{repo_prefix}/queries.jsonl")
        queries = _jsonl(queries_bytes)
        if not queries:
            continue
        repositories_left = max(1, repository_count - len(selected_repositories))
        take = min(len(queries), max(1, (remaining + repositories_left - 1) // repositories_left))
        chosen = queries[:take]
        chosen_ids = {str(item.get("_id") or item.get("id") or "") for item in chosen}
        qrels_bytes = cached_qrels.read_bytes() if cached_qrels.exists() else _download(resolve_url, revision, f"{repo_prefix}/qrels.jsonl")
        qrels = [item for item in _jsonl(qrels_bytes) if str(item.get("query_id") or item.get("qid") or "") in chosen_ids]
        for item in chosen:
            item["repository"] = repository
        for item in qrels:
            item["repository"] = repository
        selected_queries.extend(chosen)
        selected_qrels.extend(qrels)
        selected_repositories.append(repository)
        remaining -= len(chosen)
        downloaded.extend(
            [
                _write_raw(output_dir / repository / "queries.jsonl", _encode_jsonl(chosen), f"{repo_prefix}/queries.jsonl"),
                _write_raw(output_dir / repository / "qrels.jsonl", _encode_jsonl(qrels), f"{repo_prefix}/qrels.jsonl"),
            ]
        )
    if len(selected_repositories) < repository_count or len(selected_queries) != query_count:
        raise ValueError(f"unable to select requested external suite: {len(selected_repositories)} repos, {len(selected_queries)} queries")
    if include_corpus:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(
                    _download_corpus,
                    output_dir,
                    repository,
                    prefix,
                    resolve_url,
                    revision,
                )
                for repository in selected_repositories
            ]
            downloaded.extend(future.result() for future in futures)
    cases = assign_repository_splits(
        [
            {
                "id": str(item.get("_id") or item.get("id") or ""),
                "repo": str(item["repository"]),
                "metadata": {"source_repository": str(item["repository"]), "dataset_revision": revision},
            }
            for item in selected_queries
        ],
        seed=split_seed,
    )
    suite = {"source": "external:CORE-Bench/LEVEL-2", "cases": cases}
    suite["freeze"] = freeze_test_partition(suite)
    audit = audit_external_suite(suite, minimum_cases=200, minimum_repositories=20)
    combined_artifacts = [
        _write_raw(output_dir / "queries.jsonl", _encode_jsonl(selected_queries), "combined/queries.jsonl"),
        _write_raw(output_dir / "qrels.jsonl", _encode_jsonl(selected_qrels), "combined/qrels.jsonl"),
    ]
    return {
        "schema_version": "1.0",
        "protocol_id": PROTOCOL_ID,
        "dataset": DATASET_ID,
        "dataset_revision": revision,
        "level": "LEVEL-2",
        "subdataset": subdataset,
        "selection": {
            "algorithm": "sha256(dataset_revision:repository), then prefix query order",
            "repository_count": len(selected_repositories),
            "query_count": len(selected_queries),
            "repositories": selected_repositories,
        },
        "cases": cases,
        "splits": split_summary(cases),
        "freeze": suite["freeze"],
        "raw_artifacts": downloaded + combined_artifacts,
        "corpus_downloaded": include_corpus,
        "external_validity_audit": audit,
        "claim_boundary": "This manifest proves dataset selection, disjoint splitting, and test freezing; retrieval metrics require the corpus and a completed evaluator run.",
    }


def _read_json(url: str) -> dict[str, Any]:
    return dict(json.loads(_request(url).decode("utf-8")))


def _download(resolve_url: str, revision: str, path: str) -> bytes:
    quoted_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    return _request(f"{resolve_url.rstrip('/')}/{revision}/{quoted_path}")


def _download_corpus(
    output_dir: Path,
    repository: str,
    prefix: str,
    resolve_url: str,
    revision: str,
) -> dict[str, Any]:
    source_path = f"{prefix}{repository}/corpus.jsonl"
    corpus_path = output_dir / repository / "corpus.jsonl"
    payload = corpus_path.read_bytes() if corpus_path.exists() else _download(resolve_url, revision, source_path)
    return _write_raw(corpus_path, payload, source_path)


def _request(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "repo-agent-research/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _jsonl(payload: bytes) -> list[dict[str, Any]]:
    return [dict(json.loads(line)) for line in payload.decode("utf-8-sig").splitlines() if line.strip()]


def _encode_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8")


def _write_raw(path: Path, payload: bytes, source_path: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"source_path": source_path, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


if __name__ == "__main__":
    main()
