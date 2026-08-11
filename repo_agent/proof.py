from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from .indexer import RepositoryIndex, build_index


def load_evidence_bundle(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence bundle must be a JSON object")
    return payload


def proof_bundle_fingerprint(bundle: dict[str, Any]) -> dict[str, Any]:
    canonical = _canonical_proof_payload(bundle)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "algorithm": "sha256",
        "scope": "stable_proof_evidence",
        "value": hashlib.sha256(encoded).hexdigest(),
        "canonical_fields": sorted(canonical.keys()),
    }


def replay_proof_bundle(bundle_path: Path, repo_path: Path | None = None, *, strict: bool = False) -> dict[str, Any]:
    bundle = load_evidence_bundle(bundle_path)
    repository = dict(bundle.get("repository") or {})
    selected_repo = repo_path or Path(str(repository.get("root", "")))
    if not str(selected_repo):
        raise ValueError("repository path is required when the bundle does not contain repository.root")
    repo_index = build_index(selected_repo)
    return replay_proof(bundle, repo_index, strict=strict)


def replay_proof(bundle: dict[str, Any], repo_index: RepositoryIndex, *, strict: bool = False) -> dict[str, Any]:
    proof = dict(bundle.get("proof") or {})
    graph = dict(proof.get("proof_graph") or {})
    fingerprint = proof_bundle_fingerprint(bundle)
    checks = [
        _check_top_hit_exists(proof, repo_index),
        _check_evidence_fingerprints_match(bundle, repo_index),
        _check_route_literals_exist(proof, repo_index),
        _check_supporting_paths_exist(proof, repo_index),
        _check_proof_graph_edges_exist(graph, repo_index),
        _check_proof_graph_edges_verified(graph, repo_index, strict=strict),
        _check_decoy_audit_still_rejected(proof, repo_index),
    ]
    passed = all(item["passed"] for item in checks)
    drift_diagnosis = _build_drift_diagnosis(checks)
    return {
        "schema_version": "1.0",
        "strategy": "proof_replay",
        "strict": strict,
        "valid": passed,
        "status": "valid" if passed else "invalid",
        "bundle_query": bundle.get("query", ""),
        "bundle_fingerprint": fingerprint,
        "repo_root": str(repo_index.repo_root),
        "proof_status": proof.get("status", "unknown"),
        "top_hit": proof.get("top_hit", ""),
        "checks": checks,
        "drift_diagnosis": drift_diagnosis,
    }


def render_replay_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Repo Agent Proof Replay",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Strategy: `{payload.get('strategy', '')}`",
        f"- Strict graph edge verification: `{bool(payload.get('strict'))}`",
        f"- Repository: `{payload.get('repo_root', '')}`",
        f"- Query: {payload.get('bundle_query', '')}",
        f"- Bundle fingerprint: `{(payload.get('bundle_fingerprint') or {}).get('value', '')}`",
        f"- Proof status: `{payload.get('proof_status', 'unknown')}`",
        f"- Top hit: `{payload.get('top_hit', '')}`",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("checks", []):
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(f"| `{item.get('name', '')}` | {result} | {item.get('detail', '')} |")
    diagnosis = list(payload.get("drift_diagnosis") or [])
    if diagnosis:
        lines.extend(
            [
                "",
                "## Drift Diagnosis",
                "",
                "| Drift Type | Severity | Suggested Action | Evidence |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in diagnosis:
            lines.append(
                f"| `{item.get('type', '')}` | `{item.get('severity', '')}` | "
                f"{item.get('suggested_action', '')} | {item.get('evidence', '')} |"
            )
    return "\n".join(lines)


def write_replay_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_replay_markdown(payload), encoding="utf-8")
    return output_path


def run_proof_mutation_lab(bundle_path: Path, repo_path: Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    base_bundle = load_evidence_bundle(bundle_path)
    repository = dict(base_bundle.get("repository") or {})
    selected_repo = repo_path or Path(str(repository.get("root", "")))
    if not str(selected_repo):
        raise ValueError("repository path is required when the bundle does not contain repository.root")
    repo_index = build_index(selected_repo)
    baseline = replay_proof(base_bundle, repo_index, strict=strict)
    fingerprint = proof_bundle_fingerprint(base_bundle)
    cases = []
    for mutation_name, mutated_bundle in _mutated_bundles(base_bundle):
        replay = replay_proof(mutated_bundle, repo_index, strict=strict)
        detected = replay["status"] == "invalid"
        cases.append(
            {
                "mutation": mutation_name,
                "detected": detected,
                "status": replay["status"],
                "drift_types": [item.get("type", "") for item in replay.get("drift_diagnosis", [])],
                "failed_checks": [item.get("name", "") for item in replay.get("checks", []) if not item.get("passed")],
            }
        )
    detected_count = sum(1 for item in cases if item["detected"])
    return {
        "schema_version": "1.0",
        "strategy": "proof_mutation_lab",
        "strict": strict,
        "bundle": str(bundle_path),
        "bundle_fingerprint": fingerprint,
        "repo_root": str(repo_index.repo_root),
        "baseline_status": baseline["status"],
        "mutation_count": len(cases),
        "detected_count": detected_count,
        "detection_rate": round(detected_count / len(cases), 3) if cases else 0.0,
        "cases": cases,
    }


def render_mutation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Repo Agent Proof Mutation Lab",
        "",
        f"- Strategy: `{payload.get('strategy', '')}`",
        f"- Strict: `{bool(payload.get('strict'))}`",
        f"- Repository: `{payload.get('repo_root', '')}`",
        f"- Bundle fingerprint: `{(payload.get('bundle_fingerprint') or {}).get('value', '')}`",
        f"- Baseline replay: `{payload.get('baseline_status', '')}`",
        f"- Mutations: `{payload.get('mutation_count', 0)}`",
        f"- Detected: `{payload.get('detected_count', 0)}`",
        f"- Detection rate: `{float(payload.get('detection_rate', 0.0)):.1%}`",
        "",
        "## Mutations",
        "",
        "| Mutation | Detected | Status | Drift Types | Failed Checks |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("cases", []):
        drift_types = ", ".join(f"`{kind}`" for kind in item.get("drift_types", [])) or "`none`"
        failed_checks = ", ".join(f"`{check}`" for check in item.get("failed_checks", [])) or "`none`"
        lines.append(
            f"| `{item.get('mutation', '')}` | {bool(item.get('detected'))} | "
            f"`{item.get('status', '')}` | {drift_types} | {failed_checks} |"
        )
    return "\n".join(lines)


def write_mutation_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_mutation_markdown(payload), encoding="utf-8")
    return output_path


def build_proof_scorecard(bundle_path: Path, repo_path: Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    bundle = load_evidence_bundle(bundle_path)
    proof = dict(bundle.get("proof") or {})
    fingerprint = proof_bundle_fingerprint(bundle)
    replay = replay_proof_bundle(bundle_path, repo_path=repo_path, strict=strict)
    mutation = run_proof_mutation_lab(bundle_path, repo_path=repo_path, strict=strict)
    checks = {str(item.get("name", "")): bool(item.get("passed")) for item in replay.get("checks", [])}
    score_items = [
        ("proof_proved", proof.get("status") == "proved", 20),
        ("strict_replay_valid", replay.get("status") == "valid", 20),
        ("evidence_fingerprints_match", checks.get("evidence_fingerprints_match", False), 10),
        ("proof_edges_verified", checks.get("proof_graph_edges_verified", False), 15),
        ("decoy_audit_present", bool(proof.get("decoy_audit")), 10),
        ("mutation_detection_complete", float(mutation.get("detection_rate", 0.0)) >= 1.0, 25),
    ]
    score = sum(weight for _name, passed, weight in score_items if passed)
    return {
        "schema_version": "1.0",
        "strategy": "proof_reliability_scorecard",
        "bundle": str(bundle_path),
        "bundle_fingerprint": fingerprint,
        "repo_root": replay.get("repo_root", ""),
        "query": bundle.get("query", ""),
        "score": score,
        "grade": _score_grade(score),
        "status": "pass" if score >= 85 else "warn" if score >= 70 else "fail",
        "score_items": [
            {"name": name, "passed": passed, "weight": weight}
            for name, passed, weight in score_items
        ],
        "metrics": {
            "proof_status": proof.get("status", "unknown"),
            "strict_replay_status": replay.get("status", "unknown"),
            "strict": strict,
            "decoy_count": len(list(proof.get("decoy_audit") or [])),
            "mutation_count": int(mutation.get("mutation_count", 0)),
            "mutation_detected": int(mutation.get("detected_count", 0)),
            "mutation_detection_rate": float(mutation.get("detection_rate", 0.0)),
            "drift_types": [item.get("type", "") for item in replay.get("drift_diagnosis", [])],
        },
        "replay": replay,
        "mutation_lab": mutation,
    }


def render_scorecard_markdown(payload: dict[str, Any]) -> str:
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Proof Reliability Scorecard",
        "",
        f"- Grade: `{payload.get('grade', '')}`",
        f"- Score: `{int(payload.get('score', 0))}/100`",
        f"- Status: `{payload.get('status', '')}`",
        f"- Strategy: `{payload.get('strategy', '')}`",
        f"- Repository: `{payload.get('repo_root', '')}`",
        f"- Query: {payload.get('query', '')}",
        f"- Bundle fingerprint: `{(payload.get('bundle_fingerprint') or {}).get('value', '')}`",
        "",
        "## Metrics",
        "",
        f"- Proof status: `{metrics.get('proof_status', 'unknown')}`",
        f"- Strict replay status: `{metrics.get('strict_replay_status', 'unknown')}`",
        f"- Strict edge verification: `{bool(metrics.get('strict'))}`",
        f"- Decoy audit entries: `{int(metrics.get('decoy_count', 0))}`",
        f"- Mutation detection: `{int(metrics.get('mutation_detected', 0))}/{int(metrics.get('mutation_count', 0))}` "
        f"(`{float(metrics.get('mutation_detection_rate', 0.0)):.1%}`)",
        f"- Replay drift types: {', '.join(f'`{item}`' for item in metrics.get('drift_types', [])) or '`none`'}",
        "",
        "## Score Items",
        "",
        "| Item | Result | Weight |",
        "| --- | --- | ---: |",
    ]
    for item in payload.get("score_items", []):
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(f"| `{item.get('name', '')}` | {result} | {int(item.get('weight', 0))} |")
    return "\n".join(lines)


def write_scorecard_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_scorecard_markdown(payload), encoding="utf-8")
    return output_path


def _canonical_proof_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    repository = dict(bundle.get("repository") or {})
    return {
        "schema_version": bundle.get("schema_version", ""),
        "target": bundle.get("target", ""),
        "query": bundle.get("query", ""),
        "mode": bundle.get("mode", ""),
        "repository_stats": repository.get("stats", {}),
        "diagnostics": bundle.get("diagnostics", {}),
        "graph_search": bundle.get("graph_search", {}),
        "proof": bundle.get("proof", {}),
        "evidence": [
            {
                "rank": item.get("rank"),
                "source_label": item.get("source_label", ""),
                "relpath": item.get("relpath", ""),
                "symbol_name": item.get("symbol_name", ""),
                "symbol_kind": item.get("symbol_kind", ""),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "score": item.get("score"),
                "matched_terms": item.get("matched_terms", []),
                "reasons": item.get("reasons", []),
                "snippet": item.get("snippet", ""),
            }
            for item in bundle.get("evidence", [])
        ],
        "graph_edges": [
            {
                "source_label": item.get("source_label", ""),
                "target_label": item.get("target_label", ""),
                "label": item.get("label", ""),
                "weight": item.get("weight"),
            }
            for item in bundle.get("graph_edges", [])
        ],
    }


def _score_grade(score: int) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    return "F"


def _mutated_bundles(bundle: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("top_hit_missing", _mutate_top_hit(bundle)),
        ("evidence_snippet_drift", _mutate_evidence_snippet(bundle)),
        ("route_anchor_missing", _mutate_route_anchor(bundle)),
        ("supporting_path_missing", _mutate_supporting_path(bundle)),
        ("proof_graph_edge_unverified", _mutate_proof_graph_edge(bundle)),
        ("decoy_audit_stale", _mutate_decoy_audit(bundle)),
    ]


def _mutate_top_hit(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    mutated.setdefault("proof", {})["top_hit"] = "server.js:__missingProofTarget"
    return mutated


def _mutate_route_anchor(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    mutated.setdefault("proof", {})["route_literals"] = ["/__missing/proof-route"]
    return mutated


def _mutate_evidence_snippet(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    evidence = list(mutated.get("evidence") or [])
    if evidence:
        evidence[0] = dict(evidence[0])
        evidence[0]["snippet"] = "__stale_proof_evidence_snippet__"
        mutated["evidence"] = evidence
    return mutated


def _mutate_supporting_path(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    proof = mutated.setdefault("proof", {})
    paths = list(proof.get("supporting_paths") or [])
    if paths:
        paths[0] = dict(paths[0])
        path = list(paths[0].get("path") or [])
        path.append("server.js:__missingProofPathNode")
        paths[0]["path"] = path
        proof["supporting_paths"] = paths
    return mutated


def _mutate_proof_graph_edge(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    graph = mutated.setdefault("proof", {}).setdefault("proof_graph", {})
    edges = list(graph.get("edges") or [])
    edges.append(
        {
            "source": "server.js:writeAdminChatDelta",
            "target": "server.js:writeChatDelta",
            "label": "route_path",
        }
    )
    graph["edges"] = edges
    return mutated


def _mutate_decoy_audit(bundle: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    proof = mutated.setdefault("proof", {})
    decoys = list(proof.get("decoy_audit") or [])
    if decoys:
        decoys[0] = dict(decoys[0])
        decoys[0]["rejected"] = False
        proof["decoy_audit"] = decoys
    return mutated


def _check_top_hit_exists(proof: dict[str, Any], repo_index: RepositoryIndex) -> dict[str, Any]:
    top_hit = str(proof.get("top_hit", ""))
    labels = _source_labels(repo_index)
    return {
        "name": "top_hit_exists",
        "passed": bool(top_hit and top_hit in labels),
        "detail": top_hit or "proof has no top hit",
        "drift_type": "none" if top_hit and top_hit in labels else "top_hit_missing",
        "suggested_action": "rerun investigation to find the renamed or moved target symbol",
    }


def _check_evidence_fingerprints_match(bundle: dict[str, Any], repo_index: RepositoryIndex) -> dict[str, Any]:
    evidence = list(bundle.get("evidence") or [])
    if not evidence:
        return {
            "name": "evidence_fingerprints_match",
            "passed": True,
            "detail": "no evidence snippets recorded",
            "drift_type": "none",
            "suggested_action": "regenerate the bundle with JSON evidence snippets for content replay",
        }
    chunks_by_label = {chunk.source_label: chunk for chunk in repo_index.chunks}
    missing: list[str] = []
    drifted: list[str] = []
    checked = 0
    for item in evidence:
        label = str(item.get("source_label", ""))
        snippet = str(item.get("snippet", ""))
        if not label:
            continue
        chunk = chunks_by_label.get(label)
        if chunk is None:
            missing.append(label)
            continue
        if not snippet.strip():
            continue
        checked += 1
        if not _snippet_matches_current_chunk(snippet, chunk.text):
            drifted.append(label)
    failures = sorted(set(missing + drifted))
    detail = f"{checked} evidence snippets match current source"
    if failures:
        detail = f"stale evidence: {', '.join(failures[:6])}"
        if len(failures) > 6:
            detail += f" (+{len(failures) - 6} more)"
    return {
        "name": "evidence_fingerprints_match",
        "passed": not failures,
        "detail": detail,
        "drift_type": "none" if not failures else "evidence_content_drift",
        "suggested_action": "regenerate the bundle and review source changes before trusting stale evidence snippets",
    }


def _check_route_literals_exist(proof: dict[str, Any], repo_index: RepositoryIndex) -> dict[str, Any]:
    requested = [str(route) for route in proof.get("route_literals", []) if route]
    current_routes = {
        chunk.route_path
        for chunk in repo_index.chunks
        if chunk.route_path
    }
    missing = [route for route in requested if route not in current_routes]
    return {
        "name": "route_literals_exist",
        "passed": not missing,
        "detail": "all route literals exist" if not missing else f"missing: {', '.join(missing)}",
        "drift_type": "none" if not missing else "route_anchor_missing",
        "suggested_action": "inspect route definitions and regenerate the proof for the new endpoint surface",
    }


def _check_supporting_paths_exist(proof: dict[str, Any], repo_index: RepositoryIndex) -> dict[str, Any]:
    labels = _source_labels(repo_index)
    missing: list[str] = []
    for item in proof.get("supporting_paths", []):
        for label in item.get("path", []):
            if str(label) not in labels:
                missing.append(str(label))
    unique_missing = sorted(set(missing))
    return {
        "name": "supporting_paths_exist",
        "passed": not unique_missing,
        "detail": "all supporting path nodes exist" if not unique_missing else f"missing: {', '.join(unique_missing)}",
        "drift_type": "none" if not unique_missing else "execution_path_broken",
        "suggested_action": "rebuild the evidence path from route handler to target symbol",
    }


def _check_proof_graph_edges_exist(graph: dict[str, Any], repo_index: RepositoryIndex) -> dict[str, Any]:
    labels = _source_labels(repo_index)
    route_literals = {
        chunk.route_path
        for chunk in repo_index.chunks
        if chunk.route_path
    }
    missing: list[str] = []
    for edge in graph.get("edges", []):
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source and source not in labels and source not in route_literals:
            missing.append(source)
        if target and target not in labels and target not in route_literals:
            missing.append(target)
    unique_missing = sorted(set(missing))
    return {
        "name": "proof_graph_edges_resolve",
        "passed": not unique_missing,
        "detail": "all proof graph edge endpoints resolve" if not unique_missing else f"missing: {', '.join(unique_missing)}",
        "drift_type": "none" if not unique_missing else "proof_graph_stale",
        "suggested_action": "regenerate the proof graph and compare old/new graph endpoints",
    }


def _check_proof_graph_edges_verified(graph: dict[str, Any], repo_index: RepositoryIndex, *, strict: bool) -> dict[str, Any]:
    if not strict:
        return {
            "name": "proof_graph_edges_verified",
            "passed": True,
            "detail": "strict graph edge verification disabled",
            "drift_type": "none",
            "suggested_action": "run replay-proof with --strict to verify proof edges against repository graph edges",
        }
    missing: list[str] = []
    for edge in graph.get("edges", []):
        label = str(edge.get("label", ""))
        if label == "ranked_against":
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if label == "anchors":
            route = str(edge.get("route", source))
            if not _has_route_anchor_edge(repo_index, route, target):
                missing.append(f"{source} -[{label}]-> {target}")
        elif label == "route_path":
            if not _has_repository_edge_between(repo_index, source, target):
                missing.append(f"{source} -[{label}]-> {target}")
    unique_missing = sorted(set(missing))
    return {
        "name": "proof_graph_edges_verified",
        "passed": not unique_missing,
        "detail": "all proof graph route/path edges are backed by repository graph edges"
        if not unique_missing
        else f"unverified: {'; '.join(unique_missing)}",
        "drift_type": "none" if not unique_missing else "proof_graph_edge_unverified",
        "suggested_action": "regenerate the proof and inspect route/call edges that no longer exist",
    }


def _check_decoy_audit_still_rejected(proof: dict[str, Any], repo_index: RepositoryIndex) -> dict[str, Any]:
    decoys = list(proof.get("decoy_audit") or [])
    if not decoys:
        return {
            "name": "decoy_audit_still_rejected",
            "passed": True,
            "detail": "no decoy audit entries recorded",
        }
    labels = _source_labels(repo_index)
    unresolved = [str(item.get("candidate", "")) for item in decoys if str(item.get("candidate", "")) not in labels]
    not_rejected = [str(item.get("candidate", "")) for item in decoys if not item.get("rejected")]
    failures = sorted(set(unresolved + not_rejected))
    return {
        "name": "decoy_audit_still_rejected",
        "passed": not failures,
        "detail": "all audited decoys still resolve and remain rejected" if not failures else f"failed: {', '.join(failures)}",
        "drift_type": "none" if not failures else "decoy_audit_stale",
        "suggested_action": "rerun contrastive audit because a previous decoy changed or is no longer rejected",
    }


def _source_labels(repo_index: RepositoryIndex) -> set[str]:
    return {chunk.source_label for chunk in repo_index.chunks}


def _has_route_anchor_edge(repo_index: RepositoryIndex, route: str, target_label: str) -> bool:
    route_chunk_ids = {
        chunk.chunk_id
        for chunk in repo_index.chunks
        if chunk.route_path == route
    }
    route_chunk_labels = {
        chunk.source_label
        for chunk in repo_index.chunks
        if chunk.route_path == route
    }
    if target_label in route_chunk_labels:
        return True
    target_ids = _chunk_ids_for_label(repo_index, target_label)
    if not route_chunk_ids or not target_ids:
        return False
    for edge in repo_index.edges:
        if edge.label in {"routes_to", "calls"} and edge.source in route_chunk_ids and edge.target in target_ids:
            return True
    return False


def _has_repository_edge_between(repo_index: RepositoryIndex, source_label: str, target_label: str) -> bool:
    source_ids = _chunk_ids_for_label(repo_index, source_label)
    target_ids = _chunk_ids_for_label(repo_index, target_label)
    if not source_ids or not target_ids:
        return False
    for edge in repo_index.edges:
        if edge.label not in {"routes_to", "calls", "imports"}:
            continue
        if edge.source in source_ids and edge.target in target_ids:
            return True
        if edge.source in target_ids and edge.target in source_ids:
            return True
    return False


def _chunk_ids_for_label(repo_index: RepositoryIndex, label: str) -> set[str]:
    return {
        chunk.chunk_id
        for chunk in repo_index.chunks
        if chunk.source_label == label
    }


def _snippet_matches_current_chunk(snippet: str, current_text: str) -> bool:
    recorded = _normalize_evidence_text(snippet).strip()
    current = _normalize_evidence_text(current_text).strip()
    if not recorded:
        return True
    if recorded.endswith("\n..."):
        return current.startswith(recorded[:-4].rstrip())
    if recorded.endswith("..."):
        return current.startswith(recorded[:-3].rstrip())
    return current == recorded


def _normalize_evidence_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _build_drift_diagnosis(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnosis = []
    for check in checks:
        if check.get("passed"):
            continue
        drift_type = str(check.get("drift_type") or "unknown_drift")
        diagnosis.append(
            {
                "type": drift_type,
                "check": check.get("name", ""),
                "severity": _drift_severity(drift_type),
                "evidence": check.get("detail", ""),
                "suggested_action": check.get("suggested_action", "rerun the investigation and regenerate the proof"),
            }
        )
    if not diagnosis:
        return [
            {
                "type": "none",
                "check": "all",
                "severity": "none",
                "evidence": "all replay checks passed",
                "suggested_action": "no action needed; proof is still valid",
            }
        ]
    return diagnosis


def _drift_severity(drift_type: str) -> str:
    if drift_type in {"top_hit_missing", "route_anchor_missing"}:
        return "high"
    if drift_type in {"execution_path_broken", "proof_graph_stale"}:
        return "medium"
    if drift_type in {"decoy_audit_stale", "proof_graph_edge_unverified", "evidence_content_drift"}:
        return "medium"
    if drift_type == "none":
        return "none"
    return "unknown"
