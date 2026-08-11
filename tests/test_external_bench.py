from __future__ import annotations

from pathlib import Path

from repo_agent.external_bench import build_external_localization_suite


def test_external_benchmark_import_derives_files_from_gold_patch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "org__project"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "service.py").write_text(
        "def fix_me():\n    pass\n", encoding="utf-8"
    )
    records = [
        {
            "instance_id": "org__project-1",
            "repo": "org/project",
            "base_commit": "abc123",
            "problem_statement": "The service returns a stale response.",
            "patch": "diff --git a/src/service.py b/src/service.py\n--- a/src/service.py\n+++ b/src/service.py\n",
        }
    ]

    suite = build_external_localization_suite(
        records, repo_root=tmp_path, dataset_name="SWE-bench Verified"
    )

    assert suite["source"] == "external:SWE-bench Verified"
    assert suite["cases"][0]["expected_path"] == "src/service.py"
    assert Path(suite["cases"][0]["repo"]) == repo.resolve()
    assert "real-repository" in suite["cases"][0]["tags"]
