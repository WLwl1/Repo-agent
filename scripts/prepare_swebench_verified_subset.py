"""Prepare a pinned SWE-bench Verified file-localization manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

from repo_agent.external_bench import build_external_localization_suite, freeze_external_suite, write_suite
from repo_agent.research_protocol import PROTOCOL_ID, audit_external_suite, freeze_test_partition, split_summary


DATASET_ID = "princeton-nlp/SWE-bench_Verified"
DATASET_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
PARQUET_PATH = "data/test-00000-of-00001.parquet"
DEFAULT_API_URL = "https://huggingface.co/api/datasets/princeton-nlp/SWE-bench_Verified"
DEFAULT_RESOLVE_URL = "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest-output", required=True, type=Path)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--resolve-url", default=DEFAULT_RESOLVE_URL)
    parser.add_argument("--revision", default=DATASET_REVISION)
    args = parser.parse_args()
    payload = prepare(args.output_dir, args.api_url, args.resolve_url, args.revision)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["component_audit"], ensure_ascii=False, indent=2))
    if payload["component_audit"]["status"] != "pass":
        raise SystemExit(2)


def prepare(output_dir: Path, api_url: str, resolve_url: str, revision: str) -> dict[str, Any]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas and pyarrow are required to prepare SWE-bench Verified") from exc
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(_request(api_url).decode("utf-8"))
    if str(metadata.get("sha", "")) != revision:
        raise ValueError(f"dataset revision mismatch: expected {revision}, received {metadata.get('sha', '')}")
    parquet_path = output_dir / "swebench-verified.parquet"
    if not parquet_path.exists():
        parquet_path.write_bytes(_request(f"{resolve_url.rstrip('/')}/{revision}/{PARQUET_PATH}"))
    frame = pd.read_parquet(parquet_path)
    records = [{str(key): value for key, value in row.items()} for row in frame.to_dict(orient="records")]
    full_suite = build_external_localization_suite(
        records,
        repo_root=output_dir / "repos",
        dataset_name="SWE-bench Verified",
        include_missing_repositories=True,
    )
    freeze_external_suite(full_suite)
    write_suite(full_suite, output_dir / "suite.json")
    compact_cases = [
        {
            "id": str(case.get("id", "")),
            "repo": str(dict(case.get("metadata") or {}).get("source_repository", "")),
            "expected_path": str(case.get("expected_path", "")),
            "metadata": {
                key: value
                for key, value in dict(case.get("metadata") or {}).items()
                if key in {"source_instance_id", "source_repository", "base_commit", "repository_identity", "split", "split_seed"}
            },
        }
        for case in full_suite["cases"]
    ]
    compact_suite: dict[str, Any] = {"source": "external:SWE-bench Verified", "cases": compact_cases}
    compact_suite["freeze"] = freeze_test_partition(compact_suite)
    audit = audit_external_suite(compact_suite, minimum_cases=200, minimum_repositories=10)
    return {
        "schema_version": "1.0",
        "protocol_id": PROTOCOL_ID,
        "dataset": DATASET_ID,
        "dataset_revision": revision,
        "source_issue_count": len(records),
        "file_localization_case_count": len(compact_cases),
        "repository_count": audit["metrics"]["repository_count"],
        "cases": compact_cases,
        "splits": split_summary(compact_cases),
        "freeze": compact_suite["freeze"],
        "component_audit": audit,
        "raw_artifact": {
            "source_path": PARQUET_PATH,
            "size_bytes": parquet_path.stat().st_size,
            "sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
        },
        "claim_boundary": "SWE-bench Verified has 12 repositories; it is an external component, not the standalone 20-repository gate.",
    }


def _request(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "repo-agent-research/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


if __name__ == "__main__":
    main()
