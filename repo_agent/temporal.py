from __future__ import annotations

import difflib
import io
import json
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from .contract import verify_regression_contract
from .indexer import RepositoryIndex, build_index, tokenize
from .models import CodeChunk


def run_temporal_proof_regression(
    contract_path: Path,
    *,
    git_repo_path: Path | None = None,
    repo_subdir: str | None = None,
    rev_range: str = "HEAD",
    commits: list[str] | None = None,
    max_commits: int = 20,
) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract_repo = Path(str(contract.get("repo_root", "")))
    git_root = _resolve_git_root(git_repo_path or contract_repo)
    selected_subdir = _resolve_repo_subdir(git_root, contract_repo, repo_subdir)
    selected_commits = list(commits or _rev_list(git_root, rev_range))
    if max_commits > 0:
        selected_commits = selected_commits[-max_commits:]
    if not selected_commits:
        raise ValueError("no commits selected for temporal proof regression")

    timeline = []
    snapshot_by_sha: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="repo-agent-temporal-") as tmp:
        tmp_root = Path(tmp)
        for ordinal, commit in enumerate(selected_commits, start=1):
            snapshot_root = tmp_root / f"snapshot-{ordinal:03d}"
            repo_snapshot = _export_commit(git_root, commit, snapshot_root, selected_subdir)
            item = _verify_snapshot(contract_path, repo_snapshot, git_root, commit, ordinal)
            timeline.append(item)
            snapshot_by_sha[str(item.get("sha", ""))] = repo_snapshot

        first_failing = _first_failing_commit(timeline)
        last_passing_before_failure = _last_passing_before(timeline, first_failing)
        proof_repair = _infer_temporal_repair(
            contract,
            snapshot_by_sha,
            first_failing,
            last_passing_before_failure,
        )
        if first_failing and last_passing_before_failure:
            status = "regression_found"
        elif first_failing:
            status = "always_failing"
        else:
            status = "valid_across_history"

        return {
            "schema_version": "1.0",
            "strategy": "temporal_proof_regression",
            "status": status,
            "contract": str(contract_path),
            "git_repo": str(git_root),
            "repo_subdir": selected_subdir,
            "rev_range": rev_range,
            "commit_count": len(timeline),
            "first_failing_commit": first_failing,
            "last_passing_commit": last_passing_before_failure,
            "proof_repair": proof_repair,
            "timeline": timeline,
            "summary": {
                "passed_count": sum(1 for item in timeline if item.get("valid")),
                "failed_count": sum(1 for item in timeline if not item.get("valid")),
                "transition": "pass_to_fail" if first_failing and last_passing_before_failure else status,
                "repair_status": proof_repair.get("status", "not_applicable"),
            },
        }


def render_temporal_markdown(payload: dict[str, Any]) -> str:
    summary = dict(payload.get("summary") or {})
    first_failing = dict(payload.get("first_failing_commit") or {})
    last_passing = dict(payload.get("last_passing_commit") or {})
    lines = [
        "# Repo Agent Temporal Proof Regression",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Contract: `{payload.get('contract', '')}`",
        f"- Git repository: `{payload.get('git_repo', '')}`",
        f"- Repository subdir: `{payload.get('repo_subdir', '') or '.'}`",
        f"- Commits checked: `{payload.get('commit_count', 0)}`",
        f"- Passed: `{summary.get('passed_count', 0)}`",
        f"- Failed: `{summary.get('failed_count', 0)}`",
        f"- Transition: `{summary.get('transition', 'unknown')}`",
    ]
    if first_failing:
        lines.append(
            f"- First failing commit: `{first_failing.get('short_sha', '')}` {first_failing.get('subject', '')}"
        )
    if last_passing:
        lines.append(
            f"- Last passing commit: `{last_passing.get('short_sha', '')}` {last_passing.get('subject', '')}"
        )
    lines.extend(
        [
            "",
            "## Timeline",
            "",
            "| # | Commit | Status | Subject | Failed Checks |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("timeline", []):
        failed = ", ".join(str(check.get("id", "")) for check in item.get("failed_checks", [])) or "-"
        status = "PASS" if item.get("valid") else "FAIL"
        lines.append(
            f"| {int(item.get('ordinal', 0))} | `{item.get('short_sha', '')}` | `{status}` | "
            f"{item.get('subject', '')} | {failed} |"
        )
    if first_failing:
        lines.extend(["", "## Regression Diagnosis", ""])
        lines.append(
            "The proof contract first fails at "
            f"`{first_failing.get('short_sha', '')}` after "
            f"`{last_passing.get('short_sha', 'no prior pass')}`."
        )
        failed_checks = list(first_failing.get("failed_checks") or [])
        if failed_checks:
            lines.extend(["", "| Invariant | Detail |", "| --- | --- |"])
            for check in failed_checks:
                lines.append(f"| `{check.get('id', '')}` | {check.get('detail', '')} |")
    repair = dict(payload.get("proof_repair") or {})
    graph_delta = dict(repair.get("proof_graph_delta") or {})
    edge_deltas = list(graph_delta.get("edge_deltas") or [])
    successor_relinks = list(graph_delta.get("successor_relinks") or [])
    if edge_deltas or successor_relinks:
        lines.extend(
            [
                "",
                "## Proof Graph Delta",
                "",
                f"- Delta status: `{graph_delta.get('status', 'unknown')}`",
                f"- Broken proof edges: `{int(graph_delta.get('broken_edge_count', 0))}`",
                f"- Successor relinks: `{int(graph_delta.get('successor_relink_count', 0))}`",
                "",
                "| Edge | Before | After | Status |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in edge_deltas:
            before = item.get("before_label", "") or "missing"
            after = item.get("after_label", "") or "missing"
            lines.append(
                f"| `{item.get('source', '')} -> {item.get('target', '')}` | "
                f"`{before}` | `{after}` | `{item.get('status', '')}` |"
            )
        if successor_relinks:
            lines.extend(["", "| Successor Relink | Edge | Route Reachable | Status |", "| --- | --- | --- | --- |"])
            for item in successor_relinks:
                edge = item.get("after_edge_label", "") or "missing"
                reachable = "yes" if item.get("route_reachable") else "no"
                lines.append(
                    f"| `{item.get('predecessor', '')} -> {item.get('successor', '')}` | "
                    f"`{edge}` | `{reachable}` | `{item.get('status', '')}` |"
                )
    candidates = list(repair.get("candidates") or [])
    if candidates:
        top = dict(repair.get("top_candidate") or candidates[0])
        lines.extend(
            [
                "",
                "## Proof Repair Candidates",
                "",
                f"- Repair status: `{repair.get('status', 'unknown')}`",
                f"- Original target: `{repair.get('target_label', '')}`",
                f"- Top successor: `{top.get('label', '')}` (`{top.get('confidence', 'unknown')}`, score `{float(top.get('score', 0.0)):.2f}`)",
                "",
                "| Rank | Candidate | Score | Signals |",
                "| ---: | --- | ---: | --- |",
            ]
        )
        for item in candidates:
            signals = "; ".join(str(reason) for reason in item.get("reasons", [])) or "-"
            lines.append(
                f"| {int(item.get('rank', 0))} | `{item.get('label', '')}` | "
                f"{float(item.get('score', 0.0)):.2f} | {signals} |"
            )
        migration = dict(repair.get("contract_migration_plan") or {})
        if migration.get("json_patch"):
            lines.extend(
                [
                    "",
                    "## Proof Contract Migration Plan",
                    "",
                    f"- Migration status: `{migration.get('status', 'unknown')}`",
                    f"- Old target: `{migration.get('old_target', '')}`",
                    f"- New target: `{migration.get('new_target', '')}`",
                    "",
                    "| Check | Result | Detail |",
                    "| --- | --- | --- |",
                ]
            )
            for check in migration.get("simulation_checks", []):
                result = "PASS" if check.get("passed") else "FAIL"
                lines.append(f"| `{check.get('id', '')}` | `{result}` | {check.get('detail', '')} |")
            lines.extend(["", "| Operation | JSON Pointer | Value |", "| --- | --- | --- |"])
            for op in migration.get("json_patch", []):
                value = json.dumps(op.get("value", ""), ensure_ascii=False)
                lines.append(f"| `{op.get('op', '')}` | `{op.get('path', '')}` | `{value}` |")
            artifacts = list(migration.get("regenerate_artifacts") or [])
            if artifacts:
                lines.extend(["", "Regenerate after approval:"])
                for artifact in artifacts:
                    lines.append(f"- {artifact}")
        actions = list(repair.get("recommended_actions") or [])
        if actions:
            lines.extend(["", "## Recommended Repair Actions", ""])
            for action in actions:
                lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_temporal_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_temporal_markdown(payload), encoding="utf-8")
    return output_path


def _verify_snapshot(
    contract_path: Path,
    repo_snapshot: Path,
    git_root: Path,
    commit: str,
    ordinal: int,
) -> dict[str, Any]:
    verification = verify_regression_contract(contract_path, repo_path=repo_snapshot)
    failed_checks = [
        {"id": item.get("id", ""), "detail": item.get("detail", "")}
        for item in verification.get("checks", [])
        if not item.get("passed")
    ]
    metadata = _commit_metadata(git_root, commit)
    return {
        "ordinal": ordinal,
        "sha": metadata["sha"],
        "short_sha": metadata["short_sha"],
        "subject": metadata["subject"],
        "author_date": metadata["author_date"],
        "valid": bool(verification.get("valid")),
        "status": verification.get("status", "unknown"),
        "failed_checks": failed_checks,
        "summary": verification.get("summary", {}),
    }


def _infer_temporal_repair(
    contract: dict[str, Any],
    snapshot_by_sha: dict[str, Path],
    first_failing: dict[str, Any] | None,
    last_passing: dict[str, Any] | None,
) -> dict[str, Any]:
    if not first_failing or not last_passing:
        return {
            "strategy": "proof_successor_inference",
            "status": "not_applicable",
            "reason": "repair inference requires a pass-to-fail transition",
            "candidates": [],
        }
    before_repo = snapshot_by_sha.get(str(last_passing.get("sha", "")))
    after_repo = snapshot_by_sha.get(str(first_failing.get("sha", "")))
    if before_repo is None or after_repo is None:
        return {
            "strategy": "proof_successor_inference",
            "status": "not_applicable",
            "reason": "snapshot path not available for transition",
            "candidates": [],
        }
    return infer_proof_successors(contract, before_repo=before_repo, after_repo=after_repo)


def infer_proof_successors(
    contract: dict[str, Any],
    *,
    before_repo: Path,
    after_repo: Path,
    limit: int = 5,
) -> dict[str, Any]:
    before_index = build_index(before_repo)
    after_index = build_index(after_repo)
    target_label = _contract_target_label(contract)
    before_chunk = _chunk_by_label(before_index, target_label)
    if before_chunk is None:
        return {
            "strategy": "proof_successor_inference",
            "status": "target_not_found_in_last_passing_snapshot",
            "target_label": target_label,
            "candidates": [],
            "recommended_actions": ["Regenerate the proof bundle because the original target cannot be found in the last passing snapshot."],
        }

    route_literals = [str(item) for item in (contract.get("proof_context") or {}).get("route_literals", []) if str(item)]
    predecessor_labels = _supporting_predecessor_labels(contract, target_label)
    candidates = [
        _score_successor_candidate(before_chunk, candidate, after_index, route_literals, predecessor_labels)
        for candidate in after_index.chunks
        if candidate.symbol_name and candidate.source_label != target_label
    ]
    ranked = [
        item
        for item in sorted(candidates, key=lambda item: item["score"], reverse=True)
        if _candidate_has_successor_evidence(item)
    ]
    for rank, item in enumerate(ranked[:limit], start=1):
        item["rank"] = rank
    top = ranked[0] if ranked else None
    graph_delta = _build_proof_graph_delta(
        contract,
        before_index,
        after_index,
        target_label,
        str(top.get("label", "")) if top else "",
        route_literals,
    )
    migration_plan = _build_contract_migration_plan(
        contract,
        after_index,
        before_chunk,
        str(top.get("label", "")) if top else "",
        graph_delta,
    )
    status = "successor_candidates_found" if top else "no_successor_candidate"
    actions = [
        f"Review whether `{top['label']}` is the semantic successor of `{target_label}`." if top else f"Regenerate localization for `{target_label}` because no strong successor was inferred.",
        "If confirmed, regenerate the proof bundle and proof regression contract for the same query.",
        "Rerun strict proof replay, mutation lab, scorecard, impact analysis, and PR guard before merging.",
    ]
    return {
        "schema_version": "1.0",
        "strategy": "proof_successor_inference",
        "status": status,
        "target_label": target_label,
        "target_symbol": before_chunk.symbol_name,
        "route_literals": route_literals,
        "proof_graph_delta": graph_delta,
        "contract_migration_plan": migration_plan,
        "top_candidate": top or {},
        "candidates": ranked[:limit],
        "recommended_actions": actions,
    }


def _score_successor_candidate(
    before_chunk: CodeChunk,
    candidate: CodeChunk,
    after_index: RepositoryIndex,
    route_literals: list[str],
    predecessor_labels: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0
    if candidate.relpath == before_chunk.relpath:
        score += 0.18
        reasons.append("same file")
    if candidate.symbol_kind == before_chunk.symbol_kind:
        score += 0.10
        reasons.append(f"same symbol kind `{candidate.symbol_kind}`")

    name_similarity = _name_similarity(before_chunk.symbol_name, candidate.symbol_name)
    if name_similarity >= 0.45:
        contribution = 0.22 * name_similarity
        score += contribution
        reasons.append(f"name similarity {name_similarity:.2f}")

    body_similarity = _token_jaccard(before_chunk.text, candidate.text)
    if body_similarity >= 0.35:
        contribution = 0.28 * body_similarity
        score += contribution
        reasons.append(f"body token overlap {body_similarity:.2f}")

    call_similarity = _list_jaccard(before_chunk.calls, candidate.calls)
    if call_similarity > 0:
        contribution = 0.12 * call_similarity
        score += contribution
        reasons.append(f"call overlap {call_similarity:.2f}")

    if _candidate_reachable_from_routes(after_index, candidate, route_literals):
        score += 0.22
        reasons.append("reachable from original route")

    if _candidate_called_by_predecessor(after_index, candidate, predecessor_labels):
        score += 0.18
        reasons.append("called by previous proof-path predecessor")

    score = min(score, 1.0)
    return {
        "label": candidate.source_label,
        "relpath": candidate.relpath,
        "symbol": candidate.symbol_name,
        "kind": candidate.symbol_kind,
        "lines": [candidate.start_line, candidate.end_line],
        "score": round(score, 3),
        "confidence": _repair_confidence(score),
        "semantic_continuity": bool(name_similarity >= 0.45 or body_similarity >= 0.55 or call_similarity >= 0.5),
        "proof_path_continuity": bool(
            _candidate_reachable_from_routes(after_index, candidate, route_literals)
            or _candidate_called_by_predecessor(after_index, candidate, predecessor_labels)
        ),
        "reasons": reasons,
    }


def _candidate_has_successor_evidence(candidate: dict[str, Any]) -> bool:
    return (
        float(candidate.get("score", 0.0)) >= 0.52
        and bool(candidate.get("semantic_continuity"))
        and bool(candidate.get("proof_path_continuity"))
    )


def _contract_target_label(contract: dict[str, Any]) -> str:
    proof = dict(contract.get("proof_context") or {})
    target = dict(contract.get("target") or {})
    return str(proof.get("top_hit") or target.get("label") or "")


def _chunk_by_label(repo_index: RepositoryIndex, label: str) -> CodeChunk | None:
    return next((chunk for chunk in repo_index.chunks if chunk.source_label == label), None)


def _supporting_predecessor_labels(contract: dict[str, Any], target_label: str) -> list[str]:
    labels = []
    for invariant in contract.get("invariants", []):
        if invariant.get("id") != "supporting_paths_exist":
            continue
        for item in invariant.get("paths", []):
            path = [str(label) for label in item.get("path", []) if str(label)]
            if target_label in path:
                index = path.index(target_label)
                if index > 0:
                    labels.append(path[index - 1])
    return sorted(set(labels))


def _build_proof_graph_delta(
    contract: dict[str, Any],
    before_index: RepositoryIndex,
    after_index: RepositoryIndex,
    target_label: str,
    successor_label: str,
    route_literals: list[str],
) -> dict[str, Any]:
    proof_paths = _supporting_paths(contract)
    edge_deltas = []
    successor_relinks = []
    for path_item in proof_paths:
        path = list(path_item.get("path") or [])
        route = str(path_item.get("route", ""))
        for source, target in zip(path, path[1:], strict=False):
            before_edge = _edge_between_labels(before_index, source, target)
            after_edge = _edge_between_labels(after_index, source, target)
            if before_edge and after_edge:
                status = "preserved"
            elif before_edge and not after_edge:
                status = "removed"
            elif not before_edge and after_edge:
                status = "added"
            else:
                status = "unresolved"
            edge_deltas.append(
                {
                    "route": route,
                    "source": source,
                    "target": target,
                    "before_exists": bool(before_edge),
                    "after_exists": bool(after_edge),
                    "before_label": before_edge.get("label", "") if before_edge else "",
                    "after_label": after_edge.get("label", "") if after_edge else "",
                    "status": status,
                }
            )
        if successor_label and target_label in path:
            target_index = path.index(target_label)
            predecessor = path[target_index - 1] if target_index > 0 else ""
            relink_edge = _edge_between_labels(after_index, predecessor, successor_label) if predecessor else {}
            successor_chunk = _chunk_by_label(after_index, successor_label)
            route_reachable = (
                _candidate_reachable_from_routes(after_index, successor_chunk, route_literals)
                if successor_chunk is not None
                else False
            )
            successor_relinks.append(
                {
                    "route": route,
                    "predecessor": predecessor,
                    "old_target": target_label,
                    "successor": successor_label,
                    "after_edge_exists": bool(relink_edge),
                    "after_edge_label": relink_edge.get("label", "") if relink_edge else "",
                    "route_reachable": route_reachable,
                    "status": "relinked" if relink_edge and route_reachable else "candidate_unverified",
                }
            )
    broken_edges = [item for item in edge_deltas if item["status"] in {"removed", "unresolved"}]
    relinked = [item for item in successor_relinks if item["status"] == "relinked"]
    if broken_edges and relinked:
        status = "causal_relink_found"
    elif broken_edges:
        status = "broken_path_found"
    else:
        status = "no_graph_delta"
    return {
        "strategy": "proof_graph_delta",
        "status": status,
        "target_label": target_label,
        "successor_label": successor_label,
        "broken_edge_count": len(broken_edges),
        "successor_relink_count": len(relinked),
        "edge_deltas": edge_deltas,
        "successor_relinks": successor_relinks,
    }


def _build_contract_migration_plan(
    contract: dict[str, Any],
    after_index: RepositoryIndex,
    before_chunk: CodeChunk,
    successor_label: str,
    graph_delta: dict[str, Any],
) -> dict[str, Any]:
    successor = _chunk_by_label(after_index, successor_label) if successor_label else None
    if successor is None:
        return {
            "strategy": "proof_contract_migration_plan",
            "status": "not_applicable",
            "reason": "no successor candidate available",
            "simulation_checks": [],
            "json_patch": [],
        }

    target_label = before_chunk.source_label
    checks = [
        {
            "id": "successor_target_exists",
            "passed": True,
            "detail": successor.source_label,
        },
        {
            "id": "successor_relinks_proof_path",
            "passed": int(graph_delta.get("successor_relink_count", 0)) > 0,
            "detail": f"{int(graph_delta.get('successor_relink_count', 0))} relinked proof-path edges",
        },
        {
            "id": "broken_edges_explained",
            "passed": int(graph_delta.get("broken_edge_count", 0)) > 0,
            "detail": f"{int(graph_delta.get('broken_edge_count', 0))} broken proof-path edges",
        },
    ]
    json_patch = _contract_target_patch_ops(contract, target_label, successor)
    status = "ready_for_review" if all(item["passed"] for item in checks) and json_patch else "needs_manual_review"
    return {
        "schema_version": "1.0",
        "strategy": "proof_contract_migration_plan",
        "status": status,
        "old_target": target_label,
        "new_target": successor.source_label,
        "simulation_checks": checks,
        "json_patch": json_patch,
        "regenerate_artifacts": [
            "proof-carrying evidence bundle",
            "strict proof replay report",
            "proof mutation lab report",
            "proof reliability scorecard",
            "proof-guided impact report",
            "proof regression contract",
            "proof-backed PR guard report",
        ],
    }


def _contract_target_patch_ops(
    contract: dict[str, Any],
    target_label: str,
    successor: CodeChunk,
) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    target = dict(contract.get("target") or {})
    if target:
        replacements = {
            "/target/label": successor.source_label,
            "/target/id": successor.chunk_id,
            "/target/relpath": successor.relpath,
            "/target/symbol": successor.symbol_name,
            "/target/kind": successor.symbol_kind,
            "/target/lines": [successor.start_line, successor.end_line],
        }
        for path, value in replacements.items():
            if _json_pointer_get(contract, path, missing=None) is not None:
                ops.append({"op": "replace", "path": path, "value": value})
    if _json_pointer_get(contract, "/proof_context/top_hit", missing=None) is not None:
        ops.append({"op": "replace", "path": "/proof_context/top_hit", "value": successor.source_label})

    for invariant_index, invariant in enumerate(contract.get("invariants", [])):
        if invariant.get("id") == "target_exists" and invariant.get("source_label") == target_label:
            ops.append(
                {
                    "op": "replace",
                    "path": f"/invariants/{invariant_index}/source_label",
                    "value": successor.source_label,
                }
            )
        if invariant.get("id") != "supporting_paths_exist":
            continue
        for path_index, path_item in enumerate(invariant.get("paths", [])):
            for label_index, label in enumerate(path_item.get("path", [])):
                if label == target_label:
                    ops.append(
                        {
                            "op": "replace",
                            "path": f"/invariants/{invariant_index}/paths/{path_index}/path/{label_index}",
                            "value": successor.source_label,
                        }
                    )
    return ops


def _json_pointer_get(payload: dict[str, Any], pointer: str, *, missing: Any = None) -> Any:
    current: Any = payload
    for raw_part in pointer.strip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return missing
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return missing
            current = current[index]
        else:
            return missing
    return current


def _supporting_paths(contract: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    for invariant in contract.get("invariants", []):
        if invariant.get("id") == "supporting_paths_exist":
            paths.extend(dict(item) for item in invariant.get("paths", []))
    return paths


def _edge_between_labels(repo_index: RepositoryIndex, source_label: str, target_label: str) -> dict[str, Any]:
    source = _chunk_by_label(repo_index, source_label)
    target = _chunk_by_label(repo_index, target_label)
    if source is None or target is None:
        return {}
    for edge in repo_index.edges:
        if edge.source == source.chunk_id and edge.target == target.chunk_id:
            return {"label": edge.label, "weight": edge.weight}
    return {}


def _candidate_reachable_from_routes(
    repo_index: RepositoryIndex,
    candidate: CodeChunk,
    route_literals: list[str],
    max_depth: int = 5,
) -> bool:
    route_ids = [
        chunk.chunk_id
        for chunk in repo_index.chunks
        if chunk.route_path in route_literals or chunk.source_label in route_literals
    ]
    return any(_has_graph_path(repo_index, route_id, candidate.chunk_id, max_depth=max_depth) for route_id in route_ids)


def _candidate_called_by_predecessor(
    repo_index: RepositoryIndex,
    candidate: CodeChunk,
    predecessor_labels: list[str],
) -> bool:
    predecessor_ids = {
        chunk.chunk_id
        for chunk in repo_index.chunks
        if chunk.source_label in predecessor_labels
    }
    if not predecessor_ids:
        return False
    return any(
        edge.target == candidate.chunk_id and edge.source in predecessor_ids and edge.label in {"calls", "routes_to"}
        for edge in repo_index.edges
    )


def _has_graph_path(repo_index: RepositoryIndex, start_id: str, target_id: str, max_depth: int) -> bool:
    frontier = [(start_id, 0)]
    visited = {start_id}
    while frontier:
        current, depth = frontier.pop(0)
        if current == target_id:
            return True
        if depth >= max_depth:
            continue
        for edge in repo_index.forward_edges.get(current, []):
            if edge.target in visited:
                continue
            visited.add(edge.target)
            frontier.append((edge.target, depth + 1))
    return False


def _name_similarity(left: str, right: str) -> float:
    sequence = difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()
    token_overlap = _list_jaccard(tokenize(left), tokenize(right))
    return max(sequence, token_overlap)


def _token_jaccard(left: str, right: str) -> float:
    return _list_jaccard(tokenize(left), tokenize(right))


def _list_jaccard(left: list[str], right: list[str]) -> float:
    left_set = {item.lower() for item in left if item}
    right_set = {item.lower() for item in right if item}
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _repair_confidence(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    return "low"


def _resolve_git_root(path: Path) -> Path:
    result = _git(path, ["rev-parse", "--show-toplevel"])
    return Path(result.strip()).resolve()


def _resolve_repo_subdir(git_root: Path, contract_repo: Path, explicit: str | None) -> str:
    if explicit is not None:
        return _normalize_subdir(explicit)
    try:
        return _normalize_subdir(str(contract_repo.resolve().relative_to(git_root)))
    except ValueError:
        return ""


def _normalize_subdir(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    return "" if normalized == "." else normalized


def _rev_list(git_root: Path, rev_range: str) -> list[str]:
    return _git(git_root, ["rev-list", "--reverse", rev_range]).splitlines()


def _export_commit(git_root: Path, commit: str, output_root: Path, repo_subdir: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    args = ["archive", "--format=tar", commit]
    if repo_subdir:
        args.extend(["--", repo_subdir])
    archive = _git_bytes(git_root, args)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        tar.extractall(output_root, filter="data")
    return output_root / repo_subdir if repo_subdir else output_root


def _commit_metadata(git_root: Path, commit: str) -> dict[str, str]:
    raw = _git(git_root, ["show", "-s", "--format=%H%x00%h%x00%ad%x00%s", "--date=short", commit])
    sha, short_sha, author_date, subject = (raw.split("\x00", 3) + ["", "", "", ""])[:4]
    return {
        "sha": sha.strip(),
        "short_sha": short_sha.strip(),
        "author_date": author_date.strip(),
        "subject": subject.strip(),
    }


def _first_failing_commit(timeline: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in timeline if not item.get("valid")), None)


def _last_passing_before(
    timeline: list[dict[str, Any]],
    failing: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not failing:
        return timeline[-1] if timeline else None
    passing = [item for item in timeline if int(item.get("ordinal", 0)) < int(failing.get("ordinal", 0)) and item.get("valid")]
    return passing[-1] if passing else None


def _git(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _git_bytes(cwd: Path, args: list[str]) -> bytes:
    result = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)
    return result.stdout


def build_temporal_demo_repo(source_repo: Path, output_dir: Path) -> Path:
    demo_repo = output_dir / "_temporal-proof-demo-repo"
    if demo_repo.exists():
        _remove_tree(demo_repo)
    demo_repo.mkdir(parents=True, exist_ok=True)
    source_file = source_repo / "server.js"
    target_file = demo_repo / "server.js"
    target_file.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
    _git(demo_repo, ["init"])
    _git(demo_repo, ["config", "user.email", "repo-agent@example.local"])
    _git(demo_repo, ["config", "user.name", "Repo Agent"])
    _git(demo_repo, ["add", "server.js"])
    _git(demo_repo, ["commit", "-m", "preserve proved public chat writer"])
    text = target_file.read_text(encoding="utf-8").replace("writeChatDelta", "writeExperimentalChatDelta")
    target_file.write_text(text, encoding="utf-8")
    _git(demo_repo, ["add", "server.js"])
    _git(demo_repo, ["commit", "-m", "rename public chat writer without updating proof contract"])
    return demo_repo


def _remove_tree(path: Path) -> None:
    def _make_writable_and_retry(func: Any, raw_path: str, _exc_info: Any) -> None:
        target = Path(raw_path)
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
        func(raw_path)

    shutil.rmtree(path, onerror=_make_writable_and_retry)
