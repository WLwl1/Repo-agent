from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from .indexer import RepositoryIndex, build_index
from .models import CodeChunk, GraphEdge
from .proof import load_evidence_bundle


def analyze_impact_bundle(
    bundle_path: Path,
    repo_path: Path | None = None,
    *,
    target: str = "",
    max_depth: int = 3,
) -> dict[str, Any]:
    bundle = load_evidence_bundle(bundle_path)
    repository = dict(bundle.get("repository") or {})
    selected_repo = repo_path or Path(str(repository.get("root", "")))
    if not str(selected_repo):
        raise ValueError("repository path is required when the bundle does not contain repository.root")
    repo_index = build_index(selected_repo)
    proof = dict(bundle.get("proof") or {})
    selected_target = target or str(proof.get("top_hit") or _top_evidence_label(bundle))
    return analyze_impact(
        repo_index,
        target=selected_target,
        query=str(bundle.get("query", "")),
        proof=proof,
        max_depth=max_depth,
        bundle_path=bundle_path,
    )


def analyze_impact(
    repo_index: RepositoryIndex,
    *,
    target: str,
    query: str = "",
    proof: dict[str, Any] | None = None,
    max_depth: int = 3,
    bundle_path: Path | None = None,
) -> dict[str, Any]:
    target_chunk = _find_chunk(repo_index, target)
    if target_chunk is None:
        return {
            "schema_version": "1.0",
            "strategy": "proof_guided_impact_analysis",
            "status": "not_found",
            "repo_root": str(repo_index.repo_root),
            "bundle": str(bundle_path) if bundle_path else "",
            "query": query,
            "target": target,
            "reason": "target symbol or source label was not found in the repository index",
        }

    bounded_depth = max(1, min(max_depth, 5))
    upstream = _walk_graph(repo_index, target_chunk.chunk_id, direction="reverse", max_depth=bounded_depth)
    downstream = _walk_graph(repo_index, target_chunk.chunk_id, direction="forward", max_depth=bounded_depth)
    impacted = _impact_nodes(repo_index, target_chunk, upstream, downstream)
    exposed_routes = _exposed_routes(repo_index, target_chunk, upstream, downstream, proof or {})
    files = _impacted_files(repo_index, target_chunk, impacted)
    risks = _risk_items(target_chunk, exposed_routes, upstream, downstream, proof or {})
    verification = _verification_plan(repo_index, target_chunk, files, exposed_routes, risks)
    unique_routes = {str(item.get("route", "")) for item in exposed_routes if item.get("route")}

    return {
        "schema_version": "1.0",
        "strategy": "proof_guided_impact_analysis",
        "status": "analyzed",
        "repo_root": str(repo_index.repo_root),
        "bundle": str(bundle_path) if bundle_path else "",
        "query": query,
        "target": _chunk_payload(target_chunk, role="target", depth=0),
        "proof_context": {
            "status": (proof or {}).get("status", "unknown"),
            "top_hit": (proof or {}).get("top_hit", ""),
            "route_literals": list((proof or {}).get("route_literals") or []),
            "supporting_path_count": len(list((proof or {}).get("supporting_paths") or [])),
            "decoy_count": len(list((proof or {}).get("decoy_audit") or [])),
        },
        "impact_summary": {
            "risk_level": _risk_level(risks),
            "impacted_node_count": len(impacted),
            "impacted_file_count": len(files),
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "exposed_route_count": len(unique_routes),
            "exposure_path_count": len(exposed_routes),
        },
        "exposed_routes": exposed_routes,
        "upstream": [_walk_payload(repo_index, item, role="caller_or_entrypoint") for item in upstream],
        "downstream": [_walk_payload(repo_index, item, role="callee_or_dependency") for item in downstream],
        "impacted_files": files,
        "risk_items": risks,
        "verification_plan": verification,
    }


def render_impact_markdown(payload: dict[str, Any]) -> str:
    if payload.get("status") != "analyzed":
        return "\n".join(
            [
                "# Repo Agent Proof-Guided Impact Analysis",
                "",
                f"- Status: `{payload.get('status', 'unknown')}`",
                f"- Target: `{payload.get('target', '')}`",
                f"- Reason: {payload.get('reason', '')}",
                "",
            ]
        )

    target = dict(payload.get("target") or {})
    summary = dict(payload.get("impact_summary") or {})
    proof = dict(payload.get("proof_context") or {})
    lines = [
        "# Repo Agent Proof-Guided Impact Analysis",
        "",
        f"- Status: `{payload.get('status', '')}`",
        f"- Strategy: `{payload.get('strategy', '')}`",
        f"- Repository: `{payload.get('repo_root', '')}`",
        f"- Query: {payload.get('query', '')}",
        f"- Target: `{target.get('label', '')}`",
        f"- Risk level: `{summary.get('risk_level', 'unknown')}`",
        f"- Impacted files: `{summary.get('impacted_file_count', 0)}`",
        f"- Impacted graph nodes: `{summary.get('impacted_node_count', 0)}`",
        f"- Exposed routes: `{summary.get('exposed_route_count', 0)}`",
        f"- Exposure paths: `{summary.get('exposure_path_count', 0)}`",
        "",
        "## Proof Context",
        "",
        f"- Proof status: `{proof.get('status', 'unknown')}`",
        f"- Proof top hit: `{proof.get('top_hit', '')}`",
        f"- Route literals: {_inline_code_list(proof.get('route_literals', []))}",
        f"- Supporting paths: `{proof.get('supporting_path_count', 0)}`",
        f"- Contrastive decoys: `{proof.get('decoy_count', 0)}`",
        "",
        "## Exposed Routes",
        "",
    ]
    routes = list(payload.get("exposed_routes") or [])
    if routes:
        lines.extend(["| Route | Via | Depth | Direction |", "| --- | --- | ---: | --- |"])
        for item in routes:
            lines.append(
                f"| `{item.get('route', '')}` | `{item.get('via', '')}` | "
                f"{int(item.get('depth', 0))} | `{item.get('direction', '')}` |"
            )
    else:
        lines.append("No route exposure was found within the configured graph depth.")

    lines.extend(["", "## Risk Items", ""])
    risks = list(payload.get("risk_items") or [])
    if risks:
        lines.extend(["| Level | Risk | Evidence |", "| --- | --- | --- |"])
        for item in risks:
            lines.append(
                f"| `{item.get('level', '')}` | {item.get('risk', '')} | "
                f"{item.get('evidence', '')} |"
            )
    else:
        lines.append("No impact risks were identified.")

    lines.extend(["", "## Verification Plan", ""])
    plan = list(payload.get("verification_plan") or [])
    if plan:
        for item in plan:
            command = item.get("command")
            suffix = f" Command: `{command}`" if command else ""
            check = str(item.get("check", "")).rstrip(".")
            lines.append(f"- `{item.get('priority', '')}` {check}: {item.get('reason', '')}{suffix}")
    else:
        lines.append("No verification checks were suggested.")

    lines.extend(["", "## Upstream Impact", ""])
    _append_walk_table(lines, payload.get("upstream", []))
    lines.extend(["", "## Downstream Impact", ""])
    _append_walk_table(lines, payload.get("downstream", []))

    lines.extend(["", "## Impacted Files", ""])
    files = list(payload.get("impacted_files") or [])
    if files:
        lines.extend(["| File | Nodes | Roles | Routes |", "| --- | ---: | --- | --- |"])
        for item in files:
            lines.append(
                f"| `{item.get('relpath', '')}` | {int(item.get('node_count', 0))} | "
                f"{_inline_code_list(item.get('roles', []))} | {_inline_code_list(item.get('routes', []))} |"
            )
    else:
        lines.append("No impacted files were found.")
    lines.append("")
    return "\n".join(lines)


def write_impact_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_impact_markdown(payload), encoding="utf-8")
    return output_path


def _walk_graph(repo_index: RepositoryIndex, start_id: str, *, direction: str, max_depth: int) -> list[dict[str, Any]]:
    grouped = repo_index.reverse_edges if direction == "reverse" else repo_index.forward_edges
    queue: deque[tuple[str, list[GraphEdge], int]] = deque([(start_id, [], 0)])
    seen = {start_id}
    results: list[dict[str, Any]] = []
    while queue:
        node_id, path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        edges = sorted(grouped.get(node_id, []), key=lambda edge: (edge.weight, edge.label, edge.target), reverse=True)
        for edge in edges[:12]:
            if edge.target not in repo_index.chunk_by_id or edge.target in seen:
                continue
            seen.add(edge.target)
            next_path = path + [edge]
            results.append({"chunk_id": edge.target, "depth": depth + 1, "direction": direction, "path": next_path})
            queue.append((edge.target, next_path, depth + 1))
    results.sort(key=lambda item: (int(item["depth"]), -_path_weight(item["path"])))
    return results[:24]


def _impact_nodes(
    repo_index: RepositoryIndex,
    target_chunk: CodeChunk,
    upstream: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
) -> dict[str, CodeChunk]:
    nodes = {target_chunk.chunk_id: target_chunk}
    for item in upstream + downstream:
        chunk = repo_index.chunk_by_id.get(str(item.get("chunk_id", "")))
        if chunk is not None:
            nodes[chunk.chunk_id] = chunk
    return nodes


def _exposed_routes(
    repo_index: RepositoryIndex,
    target_chunk: CodeChunk,
    upstream: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    proof: dict[str, Any],
) -> list[dict[str, Any]]:
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    route_literals = set(str(item) for item in proof.get("route_literals", []) if str(item))
    for source, role in (({"chunk_id": target_chunk.chunk_id, "depth": 0, "direction": "target"}, "target"),):
        _record_route(repo_index, source, routes, role, route_literals)
    for item in upstream + downstream:
        _record_route(repo_index, item, routes, str(item.get("direction", "")), route_literals)
    for path_item in proof.get("supporting_paths", []) or []:
        route = str(path_item.get("route", ""))
        path = list(path_item.get("path") or [])
        via = str(path[-1]) if path else ""
        if route:
            routes[(route, via)] = {
                "route": route,
                "via": via,
                "depth": int(path_item.get("depth", 0)),
                "direction": "proof_path",
                "proof_anchored": route in route_literals or not route_literals,
            }
    return sorted(routes.values(), key=lambda item: (not bool(item.get("proof_anchored")), item.get("depth", 0), item.get("route", "")))


def _record_route(
    repo_index: RepositoryIndex,
    item: dict[str, Any],
    routes: dict[tuple[str, str], dict[str, Any]],
    direction: str,
    route_literals: set[str],
) -> None:
    chunk = repo_index.chunk_by_id.get(str(item.get("chunk_id", "")))
    if chunk is None:
        return
    route = chunk.route_path
    if not route:
        return
    routes[(route, chunk.source_label)] = {
        "route": route,
        "via": chunk.source_label,
        "depth": int(item.get("depth", 0)),
        "direction": direction,
        "proof_anchored": route in route_literals or not route_literals,
    }


def _impacted_files(repo_index: RepositoryIndex, target_chunk: CodeChunk, nodes: dict[str, CodeChunk]) -> list[dict[str, Any]]:
    grouped: dict[str, list[CodeChunk]] = {}
    for chunk in nodes.values():
        grouped.setdefault(chunk.relpath, []).append(chunk)
    rows = []
    for relpath, chunks in grouped.items():
        fact = repo_index.file_fact_by_relpath.get(relpath)
        rows.append(
            {
                "relpath": relpath,
                "node_count": len(chunks),
                "target_file": relpath == target_chunk.relpath,
                "roles": list(fact.roles if fact else []),
                "routes": list(fact.routes if fact else []),
                "symbols": [chunk.symbol_name for chunk in chunks if chunk.symbol_name],
            }
        )
    return sorted(rows, key=lambda item: (not item["target_file"], item["relpath"]))


def _risk_items(
    target_chunk: CodeChunk,
    exposed_routes: list[dict[str, Any]],
    upstream: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    proof: dict[str, Any],
) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    if exposed_routes:
        risks.append(
            {
                "level": "high",
                "risk": "Target participates in externally reachable route behavior.",
                "evidence": ", ".join(sorted({str(item.get("route", "")) for item in exposed_routes if item.get("route")})),
            }
        )
    if proof.get("status") == "proved":
        risks.append(
            {
                "level": "medium",
                "risk": "Target is part of a proved evidence path; changes can invalidate the proof bundle.",
                "evidence": f"top hit {proof.get('top_hit', target_chunk.source_label)}",
            }
        )
    if len(upstream) >= 3:
        risks.append(
            {
                "level": "medium",
                "risk": "Multiple upstream callers or entrypoints converge on this target.",
                "evidence": f"{len(upstream)} upstream nodes within graph depth",
            }
        )
    if len(downstream) >= 3:
        risks.append(
            {
                "level": "medium",
                "risk": "Target fans out to multiple downstream dependencies.",
                "evidence": f"{len(downstream)} downstream nodes within graph depth",
            }
        )
    if target_chunk.symbol_kind == "route":
        risks.append(
            {
                "level": "high",
                "risk": "Target is a route entrypoint.",
                "evidence": target_chunk.route_path or target_chunk.source_label,
            }
        )
    if not risks:
        risks.append(
            {
                "level": "low",
                "risk": "No route exposure or broad graph fan-in was detected.",
                "evidence": target_chunk.source_label,
            }
        )
    return risks


def _verification_plan(
    repo_index: RepositoryIndex,
    target_chunk: CodeChunk,
    files: list[dict[str, Any]],
    exposed_routes: list[dict[str, Any]],
    risks: list[dict[str, str]],
) -> list[dict[str, str]]:
    plan = [
        {
            "priority": "P0",
            "check": "Replay the proof bundle after changes.",
            "reason": "Confirms the original evidence path and decoy audit still hold.",
            "command": "python -m repo_agent replay-proof --bundle <bundle.json> --strict",
        }
    ]
    if exposed_routes:
        plan.append(
            {
                "priority": "P0",
                "check": "Exercise the exposed route path with an integration or API test.",
                "reason": "The target is reachable from route-level behavior.",
                "command": "",
            }
        )
    if any(item.get("level") == "high" for item in risks):
        plan.append(
            {
                "priority": "P1",
                "check": "Regenerate the proof reliability scorecard.",
                "reason": "High-risk graph exposure should keep replay, mutation, and edge checks green.",
                "command": "python -m repo_agent proof-scorecard --bundle <bundle.json>",
            }
        )
    languages = {
        fact.language
        for item in files
        if (fact := repo_index.file_fact_by_relpath.get(str(item.get("relpath", "")))) is not None
    }
    if "javascript" in languages or target_chunk.language in {"javascript", "typescript"}:
        plan.append(
            {
                "priority": "P1",
                "check": "Run JavaScript syntax and unit checks for impacted files.",
                "reason": "At least one impacted node is JavaScript or TypeScript.",
                "command": "node --check <file.js>",
            }
        )
    if "python" in languages or target_chunk.language == "python":
        plan.append(
            {
                "priority": "P1",
                "check": "Run Python tests or compilation for impacted files.",
                "reason": "At least one impacted node is Python.",
                "command": "python -m pytest",
            }
        )
    return plan


def _walk_payload(repo_index: RepositoryIndex, item: dict[str, Any], *, role: str) -> dict[str, Any]:
    chunk = repo_index.chunk_by_id[str(item["chunk_id"])]
    path_edges = list(item.get("path") or [])
    return {
        **_chunk_payload(chunk, role=role, depth=int(item.get("depth", 0))),
        "direction": item.get("direction", ""),
        "path": [
            {
                "source": _label_for_id(repo_index, edge.source),
                "target": _label_for_id(repo_index, edge.target),
                "label": edge.label,
                "weight": edge.weight,
            }
            for edge in path_edges
        ],
    }


def _chunk_payload(chunk: CodeChunk, *, role: str, depth: int) -> dict[str, Any]:
    return {
        "id": chunk.chunk_id,
        "label": chunk.source_label,
        "role": role,
        "depth": depth,
        "relpath": chunk.relpath,
        "language": chunk.language,
        "symbol": chunk.symbol_name,
        "kind": chunk.symbol_kind,
        "route": chunk.route_path,
        "lines": [chunk.start_line, chunk.end_line],
    }


def _find_chunk(repo_index: RepositoryIndex, target: str) -> CodeChunk | None:
    normalized = target.strip().replace("\\", "/")
    if not normalized:
        return None
    if normalized in repo_index.chunk_by_id:
        return repo_index.chunk_by_id[normalized]
    for chunk in repo_index.chunks:
        if chunk.source_label == normalized:
            return chunk
    lower = normalized.lower()
    for chunk in repo_index.chunks:
        if chunk.source_label.lower() == lower or chunk.symbol_name.lower() == lower:
            return chunk
    return None


def _top_evidence_label(bundle: dict[str, Any]) -> str:
    evidence = list(bundle.get("evidence") or [])
    if not evidence:
        return ""
    return str(dict(evidence[0]).get("source_label", ""))


def _path_weight(path: list[GraphEdge]) -> float:
    return sum(edge.weight for edge in path)


def _label_for_id(repo_index: RepositoryIndex, chunk_id: str) -> str:
    chunk = repo_index.chunk_by_id.get(chunk_id)
    return chunk.source_label if chunk else chunk_id


def _risk_level(risks: list[dict[str, str]]) -> str:
    levels = {item.get("level", "") for item in risks}
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def _append_walk_table(lines: list[str], items: Any) -> None:
    rows = list(items or [])
    if not rows:
        lines.append("No nodes found within the configured graph depth.")
        return
    lines.extend(["| Depth | Node | Edge Path |", "| ---: | --- | --- |"])
    for item in rows[:12]:
        edge_path = " -> ".join(str(edge.get("label", "")) for edge in item.get("path", [])) or "direct"
        lines.append(f"| {int(item.get('depth', 0))} | `{item.get('label', '')}` | `{edge_path}` |")


def _inline_code_list(values: Any) -> str:
    items = [str(item) for item in values if str(item)]
    if not items:
        return "`none`"
    return ", ".join(f"`{item}`" for item in items)
