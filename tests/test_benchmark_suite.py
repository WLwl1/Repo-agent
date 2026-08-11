from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repo_agent.benchmark_suite import audit_benchmark_suite, render_benchmark_suite_audit_markdown


CORE_SUITE_PATH = Path("repo_agent/benchmark_adapter_suite.json")
CHALLENGE_SUITE_PATH = Path("repo_agent/benchmark_challenge_suite.json")


def _suite(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_core_portable_benchmark_suite_stays_release_stable() -> None:
    suite = _suite(CORE_SUITE_PATH)
    cases = list(suite["cases"])
    case_ids = [case["id"] for case in cases]
    tags = {tag for case in cases for tag in case.get("tags", [])}
    repos = {case["repo"] for case in cases}

    assert suite["suite_id"] == "repo-agent-portable-generalization-suite"
    assert len(cases) == 10
    assert len(case_ids) == len(set(case_ids))
    assert len(repos) >= 5
    assert {"express", "fastapi", "rag", "frontend", "route-grounded", "hard-negative"}.issubset(tags)


def test_challenge_benchmark_suite_has_research_grade_coverage() -> None:
    suite = _suite(CHALLENGE_SUITE_PATH)
    cases = list(suite["cases"])
    case_ids = [case["id"] for case in cases]
    tags = {tag for case in cases for tag in case.get("tags", [])}
    repos = {case["repo"] for case in cases}
    hard_negative_cases = [case for case in cases if case.get("distractor_symbol_contains")]

    assert suite["suite_id"] == "repo-agent-portable-challenge-suite"
    assert len(cases) >= 32
    assert len(case_ids) == len(set(case_ids))
    assert len(repos) >= 5
    assert len(hard_negative_cases) >= 20
    assert {
        "api",
        "express",
        "fastapi",
        "rag",
        "frontend",
        "config",
        "security",
        "safety",
        "test",
        "route-grounded",
        "hard-negative",
        "retrieval",
        "state-reset",
        "coordination",
        "verification",
    }.issubset(tags)


def test_benchmark_suite_audit_reports_machine_readable_quality_gate() -> None:
    payload = audit_benchmark_suite(
        CHALLENGE_SUITE_PATH,
        minimums={
            "case_count": 32,
            "repo_count": 5,
            "tag_count": 15,
            "hard_negative_count": 20,
        },
        required_tags={
            "api",
            "security",
            "safety",
            "route-grounded",
            "hard-negative",
            "retrieval",
            "coordination",
            "verification",
        },
    )
    markdown = render_benchmark_suite_audit_markdown(payload)

    assert payload["strategy"] == "benchmark_suite_audit"
    assert payload["status"] == "pass"
    assert payload["valid"] is True
    assert payload["metrics"]["case_count"] >= 32
    assert payload["metrics"]["hard_negative_count"] >= 20
    assert payload["metrics"]["self_hosted_count"] >= 8
    assert payload["metrics"]["expected_symbol_count"] >= 20
    assert payload["metrics"]["distractor_reference_count"] >= 40
    assert payload["failed_checks"] == []
    assert "# Repo Agent Benchmark Suite Audit" in markdown
    assert "required_tags_present" in markdown
    assert "expected_symbol_resolves" in markdown
    assert "distractors_resolve" in markdown


def test_benchmark_suite_audit_rejects_unresolvable_symbols_and_distractors(tmp_path: Path) -> None:
    repo_root = tmp_path / "fixture"
    repo_root.mkdir()
    (repo_root / "server.js").write_text("function handleChat() { return true; }\n", encoding="utf-8")
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "suite_id": "broken-suite",
                "name": "Broken Suite",
                "cases": [
                    {
                        "id": "missing_symbol",
                        "repo": "fixture",
                        "question": "Where is the missing handler?",
                        "expected_path": "server.js",
                        "expected_symbol_contains": "missingHandler",
                        "distractor_symbol_contains": ["missingDistractor"],
                        "tags": ["express", "hard-negative"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = audit_benchmark_suite(
        suite_path,
        minimums={"case_count": 1, "repo_count": 1, "tag_count": 1, "hard_negative_count": 1},
    )
    failed_ids = {item["id"] for item in payload["failed_checks"]}

    assert payload["status"] == "fail"
    assert "missing_symbol:expected_symbol_resolves" in failed_ids
    assert "missing_symbol:distractors_resolve" in failed_ids


def test_benchmark_suite_audit_accepts_route_derived_expected_symbols(tmp_path: Path) -> None:
    repo_root = tmp_path / "fixture"
    repo_root.mkdir()
    (repo_root / "server.js").write_text(
        "const app = require('express')();\napp.post('/api/session/reset', resetSession);\nfunction resetSession() {}\n",
        encoding="utf-8",
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "suite_id": "route-suite",
                "name": "Route Suite",
                "cases": [
                    {
                        "id": "route_symbol",
                        "repo": "fixture",
                        "question": "Where is the reset route?",
                        "expected_path": "server.js",
                        "expected_symbol_contains": "post_api_session_reset",
                        "tags": ["express", "route-grounded"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = audit_benchmark_suite(
        suite_path,
        minimums={"case_count": 1, "repo_count": 1, "tag_count": 1, "hard_negative_count": 0},
    )
    failed_ids = {item["id"] for item in payload["failed_checks"]}

    assert "route_symbol:expected_symbol_resolves" not in failed_ids


def test_portable_benchmark_suites_reference_existing_fixture_paths() -> None:
    for suite_path in (CORE_SUITE_PATH, CHALLENGE_SUITE_PATH):
        suite = _suite(suite_path)
        suite_dir = suite_path.parent.resolve()

        for case in suite["cases"]:
            repo_path = (suite_dir / case["repo"]).resolve()
            expected_path = repo_path / case["expected_path"]

            assert repo_path.exists(), case["id"]
            assert expected_path.exists(), case["id"]
            assert str(case.get("question", "")).strip(), case["id"]
            assert case.get("tags"), case["id"]
            assert "expected_path" in case, case["id"]


def test_challenge_benchmark_adapter_runs_as_harder_generalization_gate(tmp_path: Path) -> None:
    output_path = tmp_path / "challenge.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "benchmark-adapter",
            "--suite",
            str(CHALLENGE_SUITE_PATH),
            "--output",
            str(output_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert payload["suite_id"] == "repo-agent-portable-challenge-suite"
    assert payload["status"] == "pass"
    assert payload["metrics"]["case_count"] >= 32
    assert payload["metrics"]["top3_accuracy"] == 1.0
    assert payload["metrics"]["top1_accuracy"] >= 0.70
    assert payload["metrics"]["distractor_top1_rate"] == 0.0
