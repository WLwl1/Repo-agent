from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_MINIMUMS = {
    "case_count": 10,
    "repo_count": 3,
    "tag_count": 6,
    "hard_negative_count": 4,
}
TEXT_SUFFIXES = {".cjs", ".css", ".html", ".js", ".json", ".jsx", ".md", ".mjs", ".py", ".toml", ".ts", ".tsx"}
ROUTE_SYMBOL_RE = re.compile(r"^(get|post|put|patch|delete|options|head)_(.+)$")


def load_benchmark_suite(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark suite must be a JSON object")
    return payload


def audit_benchmark_suite(
    suite_path: Path,
    *,
    minimums: dict[str, int] | None = None,
    required_tags: set[str] | None = None,
) -> dict[str, Any]:
    suite = load_benchmark_suite(suite_path)
    cases = list(suite.get("cases") or [])
    suite_dir = suite_path.parent.resolve()
    thresholds = {**DEFAULT_MINIMUMS, **(minimums or {})}
    tags = sorted({str(tag) for case in cases for tag in case.get("tags", [])})
    repos = sorted({str(case.get("repo", "")) for case in cases if str(case.get("repo", "")).strip()})
    case_ids = [str(case.get("id", "")) for case in cases]
    duplicate_ids = sorted(item for item, count in Counter(case_ids).items() if item and count > 1)
    hard_negative_cases = [
        str(case.get("id", ""))
        for case in cases
        if case.get("distractor_symbol_contains")
    ]
    expected_symbol_cases = [str(case.get("id", "")) for case in cases if str(case.get("expected_symbol_contains", "")).strip()]
    distractor_reference_count = sum(len(case.get("distractor_symbol_contains") or []) for case in cases)

    checks = [
        _check("suite_id_present", bool(str(suite.get("suite_id", "")).strip()), "suite_id is required"),
        _check("name_present", bool(str(suite.get("name", "")).strip()), "name is required"),
        _check(
            "case_count",
            len(cases) >= thresholds["case_count"],
            f"{len(cases)} cases >= {thresholds['case_count']}",
        ),
        _check(
            "repo_diversity",
            len(repos) >= thresholds["repo_count"],
            f"{len(repos)} repos >= {thresholds['repo_count']}",
        ),
        _check(
            "tag_diversity",
            len(tags) >= thresholds["tag_count"],
            f"{len(tags)} tags >= {thresholds['tag_count']}",
        ),
        _check(
            "hard_negative_coverage",
            len(hard_negative_cases) >= thresholds["hard_negative_count"],
            f"{len(hard_negative_cases)} hard-negative cases >= {thresholds['hard_negative_count']}",
        ),
        _check(
            "case_ids_unique",
            not duplicate_ids,
            "case ids are unique" if not duplicate_ids else f"duplicate ids: {', '.join(duplicate_ids)}",
        ),
    ]
    checks.extend(_case_checks(cases, suite_dir))
    if required_tags:
        missing_tags = sorted(str(tag) for tag in required_tags - set(tags))
        checks.append(
            _check(
                "required_tags_present",
                not missing_tags,
                "all required tags present" if not missing_tags else f"missing tags: {', '.join(missing_tags)}",
            )
        )

    failed = [item for item in checks if not item["passed"]]
    return {
        "schema_version": "1.0",
        "strategy": "benchmark_suite_audit",
        "suite": str(suite_path),
        "suite_id": suite.get("suite_id", ""),
        "status": "pass" if not failed else "fail",
        "valid": not failed,
        "metrics": {
            "case_count": len(cases),
            "repo_count": len(repos),
            "tag_count": len(tags),
            "hard_negative_count": len(hard_negative_cases),
            "expected_symbol_count": len(expected_symbol_cases),
            "distractor_reference_count": distractor_reference_count,
            "self_hosted_count": sum(1 for case in cases if "self-hosted" in case.get("tags", [])),
            "route_grounded_count": sum(1 for case in cases if "route-grounded" in case.get("tags", [])),
        },
        "coverage": {
            "repos": repos,
            "tags": tags,
            "hard_negative_cases": hard_negative_cases,
            "expected_symbol_cases": expected_symbol_cases,
        },
        "checks": checks,
        "failed_checks": failed,
    }


def render_benchmark_suite_audit_markdown(payload: dict[str, Any]) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Benchmark Suite Audit",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Suite: `{payload.get('suite', '')}`",
        f"- Suite id: `{payload.get('suite_id', '')}`",
        f"- Cases: `{int(metrics.get('case_count', 0))}`",
        f"- Repositories: `{int(metrics.get('repo_count', 0))}`",
        f"- Tags: `{int(metrics.get('tag_count', 0))}`",
        f"- Hard-negative cases: `{int(metrics.get('hard_negative_count', 0))}`",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("checks", []):
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(f"| `{item.get('id', '')}` | {result} | {item.get('detail', '')} |")
    coverage = dict(payload.get("coverage") or {})
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Repositories: {', '.join(f'`{item}`' for item in coverage.get('repos', [])) or '`none`'}",
            f"- Tags: {', '.join(f'`{item}`' for item in coverage.get('tags', [])) or '`none`'}",
        ]
    )
    return "\n".join(lines)


def _case_checks(cases: list[dict[str, Any]], suite_dir: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    repo_text_cache: dict[Path, list[tuple[str, str]]] = {}
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id", f"case_{index}"))
        repo_value = str(case.get("repo", "")).strip()
        expected_value = str(case.get("expected_path", "")).strip()
        expected_symbol = str(case.get("expected_symbol_contains", "")).strip()
        distractors = [str(item).strip() for item in case.get("distractor_symbol_contains") or [] if str(item).strip()]
        question = str(case.get("question", "")).strip()
        tags = list(case.get("tags") or [])
        repo_path = (suite_dir / repo_value).resolve() if repo_value else suite_dir
        expected_path = repo_path / expected_value if expected_value else repo_path
        repo_texts = repo_text_cache.setdefault(repo_path, _repo_text_index(repo_path)) if repo_path.exists() else []
        expected_text = _read_text(expected_path) if expected_path.exists() and expected_path.is_file() else ""
        checks.extend(
            [
                _check(f"{case_id}:id_present", bool(str(case.get("id", "")).strip()), "case id is required"),
                _check(f"{case_id}:repo_exists", bool(repo_value and repo_path.exists()), str(repo_path)),
                _check(f"{case_id}:expected_path_exists", bool(expected_value and expected_path.exists()), str(expected_path)),
                _check(f"{case_id}:question_present", bool(question), "question is required"),
                _check(f"{case_id}:tags_present", bool(tags), "at least one tag is required"),
            ]
        )
        if expected_symbol:
            checks.append(
                _check(
                    f"{case_id}:expected_symbol_resolves",
                    _symbol_resolves_in_expected(expected_symbol, expected_text),
                    f"`{expected_symbol}` resolves in {expected_path}",
                )
            )
        if distractors:
            unresolved = [item for item in distractors if not _needle_resolves_in_repo(item, repo_texts)]
            duplicate_targets = sorted(item for item in distractors if expected_symbol and item == expected_symbol)
            checks.extend(
                [
                    _check(
                        f"{case_id}:distractors_resolve",
                        not unresolved,
                        "all distractors resolve in repo" if not unresolved else f"unresolved distractors: {', '.join(unresolved)}",
                    ),
                    _check(
                        f"{case_id}:distractors_distinct",
                        not duplicate_targets,
                        "distractors are distinct from expected target"
                        if not duplicate_targets
                        else f"distractors duplicate expected symbol: {', '.join(duplicate_targets)}",
                    ),
                ]
            )
    return checks


def _repo_text_index(repo_path: Path) -> list[tuple[str, str]]:
    if not repo_path.exists():
        return []
    if repo_path.is_file():
        return [(repo_path.name.lower(), _read_text(repo_path).lower())]
    rows: list[tuple[str, str]] = []
    for path in repo_path.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relpath = path.relative_to(repo_path).as_posix().lower()
        rows.append((relpath, _read_text(path).lower()))
    return rows


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _symbol_resolves_in_expected(symbol: str, expected_text: str) -> bool:
    if symbol in expected_text:
        return True
    route_match = ROUTE_SYMBOL_RE.match(symbol.lower())
    if not route_match:
        return False
    method, route_tail = route_match.groups()
    route_path = "/" + route_tail.replace("_", "/")
    lowered = expected_text.lower()
    return method in lowered and route_path in lowered


def _needle_resolves_in_repo(needle: str, repo_texts: list[tuple[str, str]]) -> bool:
    lowered = needle.lower().replace("\\", "/")
    return any(lowered in relpath or lowered in text for relpath, text in repo_texts)


def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "detail": detail}
