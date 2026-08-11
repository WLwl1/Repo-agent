"""Machine-readable research protocol for repository retrieval experiments.

The protocol keeps the primary research questions narrow and makes external
evaluation auditable.  In particular, repositories—not individual cases—are
the unit of splitting, and the test partition is frozen by a content hash.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


PROTOCOL_ID = "repo-agent-retrieval-research-v1"
DEFAULT_SPLIT_SEED = 20260804
DEFAULT_SPLIT_RATIOS = {"train": 0.6, "dev": 0.2, "test": 0.2}

RESEARCH_QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "RQ1",
        "question": "Does multi-view structural retrieval improve real-issue file/function localization accuracy?",
        "hypothesis": "Identifier, path, structure, and graph signals improve Hit@1/3/5 and MRR over a single-view lexical baseline.",
        "primary_metrics": ["hit_at_1", "hit_at_3", "hit_at_5", "mrr"],
        "required_controls": ["bm25", "multiview_without_graph", "full_hybrid"],
    },
    {
        "id": "RQ2",
        "question": "Does replayable evidence reduce high-confidence errors and enable reliable abstention?",
        "hypothesis": "Evidence replay and explicit abstention reduce selective risk at the same coverage, with calibrated confidence.",
        "primary_metrics": ["ece", "brier", "risk_coverage", "proof_detection_rate"],
        "required_controls": ["ranking_only", "evidence_replay", "replay_with_abstention"],
    },
    {
        "id": "RQ3",
        "question": "Does the evidence layer improve final repair success under the same model and token budget?",
        "hypothesis": "A fixed coding agent resolves more issues with Repo Agent evidence than with the baseline retrieval context at equal cost.",
        "primary_metrics": ["patch_resolved_rate", "test_pass_rate", "tokens", "cost", "wall_time"],
        "required_controls": ["agent_without_repo_agent", "agent_with_repo_agent"],
    },
)

PRIMARY_SCOPE = {
    "in_scope": ["retrieval", "evidence_replay", "downstream_repair_utility"],
    "appendix_or_future_work": [
        "adversarial_proof_attacks",
        "temporal_repair",
        "multi_agent_evidence_court",
        "agent_reliability_frontier",
        "proof_regression_contracts",
        "PR_guard",
    ],
}


def canonical_json(value: Any) -> str:
    """Return a stable JSON representation suitable for hashing."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def repository_identity(case: Mapping[str, Any]) -> str:
    metadata = case.get("metadata")
    if isinstance(metadata, Mapping):
        source = str(metadata.get("source_repository") or "").strip()
        if source:
            return source.replace("\\", "/").lower()
    return str(case.get("repo") or "").replace("\\", "/").strip().lower()


def assign_repository_splits(
    cases: Iterable[Mapping[str, Any]],
    *,
    seed: int = DEFAULT_SPLIT_SEED,
    ratios: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Assign deterministic repository-disjoint train/dev/test labels.

    The hash order is stable across machines.  Splitting by repository avoids
    the common leakage failure where the same project appears in train and
    test through different issue instances.
    """

    rows = [dict(case) for case in cases]
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, case in enumerate(rows):
        identity = repository_identity(case)
        if not identity:
            raise ValueError(f"case {case.get('id', index)} has no repository identity")
        grouped[identity].append(index)
    names = sorted(grouped, key=lambda name: hashlib.sha256(f"{seed}:{name}".encode()).hexdigest())
    split_ratios = dict(DEFAULT_SPLIT_RATIOS if ratios is None else ratios)
    if set(split_ratios) != {"train", "dev", "test"}:
        raise ValueError("split ratios must contain train, dev, and test")
    if abs(sum(float(value) for value in split_ratios.values()) - 1.0) > 1e-6:
        raise ValueError("split ratios must sum to 1")
    if len(names) < 3:
        raise ValueError("at least three repositories are required for disjoint splits")
    train_count = max(1, round(len(names) * float(split_ratios["train"])))
    dev_count = max(1, round(len(names) * float(split_ratios["dev"])))
    if train_count + dev_count >= len(names):
        dev_count = max(1, len(names) - train_count - 1)
    boundaries = {
        "train": names[:train_count],
        "dev": names[train_count : train_count + dev_count],
        "test": names[train_count + dev_count :],
    }
    lookup = {repo: split for split, repos in boundaries.items() for repo in repos}
    for case in rows:
        case["metadata"] = {
            **dict(case.get("metadata") or {}),
            "repository_identity": repository_identity(case),
            "split": lookup[repository_identity(case)],
            "split_seed": seed,
        }
    return rows


def split_summary(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(cases)
    result: dict[str, Any] = {}
    for split in ("train", "dev", "test"):
        subset = [case for case in rows if dict(case.get("metadata") or {}).get("split") == split]
        result[split] = {
            "case_count": len(subset),
            "repository_count": len({repository_identity(case) for case in subset}),
            "case_ids": sorted(str(case.get("id", "")) for case in subset),
        }
    return result


def freeze_test_partition(suite: Mapping[str, Any]) -> dict[str, Any]:
    """Create a deterministic freeze record for a generated suite."""

    cases = [dict(case) for case in suite.get("cases") or []]
    test_cases = [case for case in cases if dict(case.get("metadata") or {}).get("split") == "test"]
    return {
        "protocol_id": PROTOCOL_ID,
        "algorithm": "sha256(canonical_json(test_cases_sorted_by_id))",
        "suite_sha256": sha256_json({"cases": sorted(cases, key=lambda case: str(case.get("id", "")))}),
        "test_sha256": sha256_json(sorted(test_cases, key=lambda case: str(case.get("id", "")))),
        "test_case_ids": sorted(str(case.get("id", "")) for case in test_cases),
        "test_case_count": len(test_cases),
        "test_repository_count": len({repository_identity(case) for case in test_cases}),
    }


def verify_frozen_test_partition(suite: Mapping[str, Any]) -> dict[str, Any]:
    expected = dict(suite.get("freeze") or {})
    actual = freeze_test_partition(suite)
    checks = [
        {"id": "freeze_present", "passed": bool(expected), "detail": "freeze record is present"},
        {"id": "suite_hash", "passed": expected.get("suite_sha256") == actual["suite_sha256"], "detail": "suite content is unchanged"},
        {"id": "test_hash", "passed": expected.get("test_sha256") == actual["test_sha256"], "detail": "test partition is unchanged"},
        {"id": "test_ids", "passed": expected.get("test_case_ids") == actual["test_case_ids"], "detail": "test case ids are unchanged"},
    ]
    return {"status": "pass" if all(item["passed"] for item in checks) else "fail", "checks": checks, "actual": actual}


def audit_external_suite(
    suite: Mapping[str, Any],
    *,
    minimum_cases: int = 200,
    minimum_repositories: int = 20,
    tuning_log: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Audit external validity and test leakage before a result is publishable."""

    cases = [dict(case) for case in suite.get("cases") or []]
    repos = {repository_identity(case) for case in cases if repository_identity(case)}
    splits = split_summary(cases)
    split_repos = {
        split: {
            repository_identity(case)
            for case in cases
            if dict(case.get("metadata") or {}).get("split") == split
        }
        for split in ("train", "dev", "test")
    }
    overlap = sorted((split_a, split_b, sorted(split_repos[split_a] & split_repos[split_b])) for split_a, split_b in (("train", "dev"), ("train", "test"), ("dev", "test")) if split_repos[split_a] & split_repos[split_b])
    tuning_rows = [dict(row) for row in tuning_log]
    test_ids = set(splits["test"]["case_ids"])
    leaked_tuning = [row for row in tuning_rows if str(row.get("split", "")).lower() == "test" or str(row.get("source_case_id", "")) in test_ids]
    checks = [
        {"id": "minimum_cases", "passed": len(cases) >= minimum_cases, "detail": f"{len(cases)} cases >= {minimum_cases}"},
        {"id": "minimum_repositories", "passed": len(repos) >= minimum_repositories, "detail": f"{len(repos)} repositories >= {minimum_repositories}"},
        {"id": "three_nonempty_splits", "passed": all(splits[split]["case_count"] > 0 for split in ("train", "dev", "test")), "detail": "train/dev/test are non-empty"},
        {"id": "repository_disjoint", "passed": not overlap, "detail": "repositories do not cross split boundaries" if not overlap else str(overlap)},
        {"id": "external_source", "passed": str(suite.get("source", "")).startswith("external:"), "detail": str(suite.get("source", ""))},
        {"id": "no_test_tuning", "passed": not leaked_tuning, "detail": "tuning log contains no test cases" if not leaked_tuning else str(leaked_tuning[:5])},
        {"id": "frozen_test_partition", "passed": bool(suite.get("freeze")) and verify_frozen_test_partition(suite)["status"] == "pass", "detail": "test partition is frozen and unchanged"},
    ]
    failed = [item for item in checks if not item["passed"]]
    return {
        "schema_version": "1.0",
        "protocol_id": PROTOCOL_ID,
        "status": "pass" if not failed else "blocked_external_validity",
        "valid": not failed,
        "metrics": {"case_count": len(cases), "repository_count": len(repos), "split_summary": splits},
        "checks": checks,
        "failed_checks": failed,
    }
