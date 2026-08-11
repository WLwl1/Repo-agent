from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from .research_protocol import (
    DEFAULT_SPLIT_SEED,
    PROTOCOL_ID,
    RESEARCH_QUESTIONS,
    assign_repository_splits,
    audit_external_suite,
    freeze_test_partition,
    split_summary,
)


DIFF_PATH_RE = re.compile(r"^\+\+\+\s+b/(.+)$", re.MULTILINE)


def load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [dict(item) for item in payload["data"]]
    raise ValueError(
        "external benchmark input must be a JSON array, JSONL, or an object with a data array"
    )


def build_external_localization_suite(
    records: Iterable[dict[str, Any]],
    *,
    repo_root: Path,
    dataset_name: str,
    max_cases: int | None = None,
    include_missing_repositories: bool = False,
    split_seed: int = DEFAULT_SPLIT_SEED,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    cases: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for record in records:
        instance_id = str(
            record.get("instance_id") or record.get("id") or f"case_{len(cases) + 1}"
        )
        repository = str(record.get("repo") or record.get("repository") or "").strip()
        question = str(
            record.get("problem_statement")
            or record.get("question")
            or record.get("issue")
            or ""
        ).strip()
        expected_paths = _expected_paths(record)
        local_repo = _resolve_local_repository(repo_root, repository)
        if not question or not expected_paths:
            skipped.append(
                {
                    "id": instance_id,
                    "reason": "missing question or patch-derived expected path",
                }
            )
            continue
        if not local_repo.exists() and not include_missing_repositories:
            skipped.append(
                {
                    "id": instance_id,
                    "reason": f"local repository not found: {local_repo}",
                }
            )
            continue
        for path_index, expected_path in enumerate(expected_paths, start=1):
            if max_cases is not None and len(cases) >= max_cases:
                break
            case_id = (
                instance_id
                if len(expected_paths) == 1
                else f"{instance_id}__file_{path_index}"
            )
            cases.append(
                {
                    "id": case_id,
                    "repo": str(local_repo),
                    "question": question,
                    "expected_path": expected_path,
                    "tags": [
                        "external",
                        "real-repository",
                        "issue-localization",
                        "file-level",
                        dataset_name.lower(),
                    ],
                    "metadata": {
                        "source_instance_id": instance_id,
                        "source_repository": repository,
                        "base_commit": str(record.get("base_commit") or ""),
                    },
                }
            )
        if max_cases is not None and len(cases) >= max_cases:
            break
    if cases:
        try:
            cases = assign_repository_splits(cases, seed=split_seed)
        except ValueError as exc:
            # Small smoke imports remain useful for schema tests, but are not
            # eligible for an external-validity claim until enough repositories
            # are present for a disjoint train/dev/test split.
            if "at least three repositories" not in str(exc):
                raise
            for case in cases:
                metadata = dict(case.get("metadata") or {})
                metadata.update({"repository_identity": str(metadata.get("source_repository") or case.get("repo", "")).replace("\\", "/").lower(), "split": "unsplit", "split_seed": split_seed})
                case["metadata"] = metadata
    else:
        cases = []
    return {
        "schema_version": "1.0",
        "suite_id": f"repo-agent-external-{_slug(dataset_name)}",
        "name": f"Repo Agent External Localization: {dataset_name}",
        "description": "Patch-derived file-localization cases from a real-repository benchmark.",
        "source": f"external:{dataset_name}",
        "research_protocol": {
            "protocol_id": PROTOCOL_ID,
            "research_questions": list(RESEARCH_QUESTIONS),
            "primary_scope": "RQ1 localization; RQ2 replay/calibration; RQ3 downstream repair utility",
            "split_seed": split_seed,
            "split_unit": "repository",
            "tuning_policy": "test is frozen before feature/rule changes; test cases cannot provide tuning evidence",
        },
        "cases": cases,
        "splits": split_summary(cases),
        "import_summary": {
            "case_count": len(cases),
            "skipped_count": len(skipped),
            "skipped": skipped[:50],
        },
    }


def freeze_external_suite(suite: dict[str, Any]) -> dict[str, Any]:
    """Attach a deterministic test freeze to an imported external suite."""

    suite["freeze"] = freeze_test_partition(suite)
    return suite


def write_suite(payload: dict[str, Any], output_path: Path) -> Path:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path


def _expected_paths(record: dict[str, Any]) -> list[str]:
    explicit = record.get("expected_paths") or record.get("files")
    if isinstance(explicit, list):
        return list(
            dict.fromkeys(
                str(item).replace("\\", "/") for item in explicit if str(item).strip()
            )
        )
    expected_path = str(record.get("expected_path") or "").strip()
    if expected_path:
        return [expected_path.replace("\\", "/")]
    patch = str(record.get("patch") or record.get("gold_patch") or "")
    return list(
        dict.fromkeys(
            match.replace("\\", "/")
            for match in DIFF_PATH_RE.findall(patch)
            if match != "/dev/null"
        )
    )


def _resolve_local_repository(repo_root: Path, repository: str) -> Path:
    candidates = [
        repo_root / repository.replace("/", "__"),
        repo_root / repository,
        repo_root / repository.rsplit("/", 1)[-1],
    ]
    return next(
        (candidate.resolve() for candidate in candidates if candidate.exists()),
        candidates[0].resolve(),
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "dataset"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import SWE-bench/Loc-Bench compatible records into Repo Agent."
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="JSON or JSONL dataset export."
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        type=Path,
        help="Root containing checked-out benchmark repositories.",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Output Repo Agent suite JSON."
    )
    parser.add_argument("--dataset-name", default="SWE-bench-compatible")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--include-missing-repositories", action="store_true")
    parser.add_argument("--split-seed", type=int, default=DEFAULT_SPLIT_SEED)
    parser.add_argument("--freeze-test", action="store_true", help="Freeze the repository-disjoint test partition.")
    parser.add_argument("--audit-output", type=Path, help="Write the external-validity audit JSON.")
    parser.add_argument("--tuning-log", type=Path, help="JSON/JSONL log of tuning decisions to audit for test leakage.")
    parser.add_argument("--min-cases", type=int, default=200)
    parser.add_argument("--min-repositories", type=int, default=20)
    parser.add_argument("--strict-research-audit", action="store_true", help="Exit non-zero unless external validity checks pass.")
    args = parser.parse_args()
    payload = build_external_localization_suite(
        load_records(args.input),
        repo_root=args.repo_root,
        dataset_name=args.dataset_name,
        max_cases=args.max_cases,
        include_missing_repositories=args.include_missing_repositories,
        split_seed=args.split_seed,
    )
    if args.freeze_test:
        freeze_external_suite(payload)
    tuning_log = load_records(args.tuning_log) if args.tuning_log else []
    audit = audit_external_suite(
        payload,
        minimum_cases=args.min_cases,
        minimum_repositories=args.min_repositories,
        tuning_log=tuning_log,
    )
    payload["external_validity_audit"] = audit
    output = write_suite(payload, args.output)
    print(f"Wrote {len(payload['cases'])} cases to {output}")
    if args.audit_output:
        write_suite(audit, args.audit_output)
    if args.strict_research_audit and audit["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
