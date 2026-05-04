from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def run_engineering_benchmark(runtime, cases_path: Path, *, max_steps: int = 6) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    records = []
    run_model_cases = os.environ.get("REPO_AGENT_RUN_ENGINEERING_BENCHMARKS", "").strip().lower() in {"1", "true", "yes"}
    for case in cases:
        repo = (cases_path.parent / case["repo"]).resolve()
        task = str(case["task"]).strip()
        if not run_model_cases or not runtime.llm.available:
            skip_reason = (
                "Set REPO_AGENT_RUN_ENGINEERING_BENCHMARKS=1 to run model-dependent engineering cases."
                if not run_model_cases
                else "Engineering benchmarks require OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL."
            )
            records.append(
                {
                    "name": case.get("name", task[:60]),
                    "task": task,
                    "run_id": "",
                    "status": "skipped_model_unavailable",
                    "execution_mode": str(case.get("execution_mode", "workspace")),
                    "changed_files": [],
                    "expected_changed_files": [str(item).replace("\\", "/") for item in case.get("expected_changed_files", [])],
                    "verification_exit_code": None,
                    "passed": False,
                    "skipped": True,
                    "skip_reason": skip_reason,
                }
            )
            continue
        result, _repo_index = runtime.engineer(
            repo_path=repo,
            task=task,
            max_steps=int(case.get("max_steps", max_steps)),
            execution_mode=str(case.get("execution_mode", "workspace")),
            force_rebuild=True,
        )
        expected_files = [str(item).replace("\\", "/") for item in case.get("expected_changed_files", [])]
        changed_files = [str(item).replace("\\", "/") for item in result.get("changed_files", [])]
        expected_terms = [str(item).lower() for item in case.get("expected_answer_terms", [])]
        answer = str(result.get("answer", "")).lower()
        verification = result.get("verification", [])
        last_exit = verification[-1].get("exit_code") if verification else None
        passed = (
            result.get("status") in {"completed", "max_steps_reached"}
            and all(any(expected in changed for changed in changed_files) for expected in expected_files)
            and all(term in answer for term in expected_terms)
        )
        if case.get("require_verification_passed"):
            passed = passed and last_exit == 0
        records.append(
            {
                "name": case.get("name", task[:60]),
                "task": task,
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "execution_mode": result.get("execution_mode"),
                "changed_files": changed_files,
                "expected_changed_files": expected_files,
                "verification_exit_code": last_exit,
                "passed": bool(passed),
                "skipped": False,
            }
        )
    runnable = [item for item in records if not item.get("skipped")]
    total = max(len(runnable), 1)
    return {
        "case_count": len(records),
        "runnable_count": len(runnable),
        "skipped_count": sum(1 for item in records if item.get("skipped")),
        "pass_rate": sum(1 for item in runnable if item["passed"]) / total,
        "cases": records,
    }
