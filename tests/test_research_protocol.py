from __future__ import annotations

from repo_agent.external_bench import build_external_localization_suite, freeze_external_suite
from repo_agent.research_protocol import audit_external_suite, assign_repository_splits, verify_frozen_test_partition


def _cases() -> list[dict[str, object]]:
    return [
        {
            "id": f"repo-{repo}-{index}",
            "repo": f"org/{repo}",
            "question": "Which file should change?",
            "expected_path": "src/service.py",
            "metadata": {"source_repository": f"org/{repo}"},
        }
        for repo in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
        for index in range(2)
    ]


def test_repository_split_is_deterministic_and_disjoint() -> None:
    first = assign_repository_splits(_cases(), seed=17)
    second = assign_repository_splits(_cases(), seed=17)
    assert first == second
    by_split = {
        split: {case["metadata"]["repository_identity"] for case in first if case["metadata"]["split"] == split}
        for split in ("train", "dev", "test")
    }
    assert all(by_split[left].isdisjoint(by_split[right]) for left, right in (("train", "dev"), ("train", "test"), ("dev", "test")))


def test_freeze_detects_test_partition_mutation() -> None:
    suite = {"source": "external:test", "cases": assign_repository_splits(_cases(), seed=17)}
    freeze_external_suite(suite)
    assert verify_frozen_test_partition(suite)["status"] == "pass"
    suite["cases"][-1]["question"] = "changed"
    assert verify_frozen_test_partition(suite)["status"] == "fail"


def test_external_audit_blocks_small_or_unfrozen_suite() -> None:
    suite = {"source": "external:test", "cases": assign_repository_splits(_cases(), seed=17)}
    audit = audit_external_suite(suite, minimum_cases=200, minimum_repositories=20)
    assert audit["status"] == "blocked_external_validity"
    assert {item["id"] for item in audit["failed_checks"]} >= {"minimum_cases", "minimum_repositories", "frozen_test_partition"}


def test_external_import_records_protocol_and_unsplit_smoke_metadata(tmp_path) -> None:
    repo = tmp_path / "org__project"
    repo.mkdir()
    (repo / "service.py").write_text("def fix_me():\n    pass\n", encoding="utf-8")
    suite = build_external_localization_suite(
        [{
            "instance_id": "org__project-1",
            "repo": "org/project",
            "problem_statement": "The service returns a stale response.",
            "patch": "+++ b/service.py\n",
        }],
        repo_root=tmp_path,
        dataset_name="SWE-bench Verified",
    )
    assert suite["research_protocol"]["protocol_id"] == "repo-agent-retrieval-research-v1"
    assert suite["cases"][0]["metadata"]["split"] == "unsplit"
