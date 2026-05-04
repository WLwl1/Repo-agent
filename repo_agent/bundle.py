from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import AgentResult, GraphEdge, RetrievalHit

if TYPE_CHECKING:
    from .indexer import RepositoryIndex

BUNDLE_SCHEMA_VERSION = "1.0"
BUNDLE_TARGETS = {"generic", "codex", "aider", "openhands"}
BUNDLE_FORMATS = {"markdown", "json"}


def build_evidence_bundle(
    *,
    result: AgentResult,
    repo_index: RepositoryIndex,
    target: str = "generic",
    max_snippet_lines: int = 24,
) -> dict[str, Any]:
    target_name = _normalize_target(target)
    hits = result.hits
    edges = repo_index.relevant_edges(hits)
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "target": target_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(repo_index.repo_root),
            "stats": repo_index.stats(),
        },
        "query": result.query,
        "mode": result.mode,
        "model_name": result.model_name,
        "answer": result.answer,
        "repo_brief": result.repo_brief,
        "handoff_prompt": _handoff_prompt(target_name),
        "evidence": [_hit_payload(hit, rank, max_snippet_lines=max_snippet_lines) for rank, hit in enumerate(hits, 1)],
        "graph_edges": [_edge_payload(edge, repo_index) for edge in edges],
        "trace": result.trace,
        "recommended_next_steps": _recommended_next_steps(result, repo_index),
    }


def write_evidence_bundle(bundle: dict[str, Any], output_path: Path, *, fmt: str = "markdown") -> Path:
    format_name = _normalize_format(fmt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_markdown_bundle(bundle), encoding="utf-8")
    return output_path


def render_markdown_bundle(bundle: dict[str, Any]) -> str:
    repo = bundle.get("repository", {})
    stats = repo.get("stats", {})
    evidence = list(bundle.get("evidence", []))
    graph_edges = list(bundle.get("graph_edges", []))
    trace = list(bundle.get("trace", []))
    next_steps = list(bundle.get("recommended_next_steps", []))

    lines = [
        "# Repo Agent Evidence Bundle",
        "",
        f"- Target: `{bundle.get('target', 'generic')}`",
        f"- Repository: `{repo.get('root', '')}`",
        f"- Query: {bundle.get('query', '')}",
        f"- Mode: `{bundle.get('mode', '')}`",
        f"- Files indexed: `{stats.get('file_count', 0)}`",
        f"- Chunks indexed: `{stats.get('chunk_count', 0)}`",
        f"- Graph edges: `{stats.get('graph_edge_count', 0)}`",
    ]
    if bundle.get("model_name"):
        lines.append(f"- Model: `{bundle.get('model_name')}`")

    lines.extend(
        [
            "",
            "## Handoff Prompt",
            "",
            str(bundle.get("handoff_prompt", "")).strip(),
            "",
            "## Answer",
            "",
            str(bundle.get("answer", "")).strip() or "No answer was produced.",
        ]
    )

    repo_brief = str(bundle.get("repo_brief", "")).strip()
    if repo_brief:
        lines.extend(["", "## Repository Brief", "", "```text", repo_brief, "```"])

    lines.extend(["", "## Evidence"])
    if evidence:
        for item in evidence:
            lines.extend(
                [
                    "",
                    f"### {item.get('rank')}. {item.get('source_label', '')}",
                    "",
                    f"- File: `{item.get('relpath', '')}`",
                    f"- Lines: `{item.get('start_line', '')}-{item.get('end_line', '')}`",
                    f"- Score: `{item.get('score', 0):.2f}`",
                    f"- Symbol: `{item.get('symbol_kind', '')}:{item.get('symbol_name', '')}`",
                    f"- Reasons: {_inline_code_list(item.get('reasons', []))}",
                    f"- Matched terms: {_inline_code_list(item.get('matched_terms', []))}",
                    "",
                    "```text",
                    str(item.get("snippet", "")).strip(),
                    "```",
                ]
            )
    else:
        lines.extend(["", "No evidence hits were found."])

    if graph_edges:
        lines.extend(["", "## Graph Edges"])
        for edge in graph_edges:
            lines.append(
                f"- `{edge.get('source_label', '')}` -> `{edge.get('target_label', '')}` "
                f"via `{edge.get('label', '')}` weight `{edge.get('weight', 0):.2f}`"
            )

    if next_steps:
        lines.extend(["", "## Recommended Next Steps"])
        lines.extend(f"- {step}" for step in next_steps)

    if trace:
        lines.extend(["", "## Investigation Trace"])
        for item in trace:
            lines.extend(
                [
                    "",
                    f"### Step {item.get('step', '?')}: {item.get('type', 'trace')}",
                    "",
                    "```text",
                    str(item.get("content", "")).strip(),
                    "```",
                ]
            )

    lines.append("")
    return "\n".join(lines)


def default_bundle_path(output_dir: Path, question: str, *, fmt: str) -> Path:
    safe_name = "".join(char if char.isalnum() else "_" for char in question.lower()).strip("_") or "evidence_bundle"
    extension = "json" if _normalize_format(fmt) == "json" else "md"
    return (output_dir / f"{safe_name[:48]}.{extension}").resolve()


def _hit_payload(hit: RetrievalHit, rank: int, *, max_snippet_lines: int) -> dict[str, Any]:
    chunk = hit.chunk
    return {
        "rank": rank,
        "source_label": chunk.source_label,
        "relpath": chunk.relpath,
        "language": chunk.language,
        "symbol_name": chunk.symbol_name,
        "symbol_kind": chunk.symbol_kind,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "route_path": chunk.route_path,
        "handler_names": chunk.handler_names,
        "score": hit.score,
        "matched_terms": hit.matched_terms,
        "reasons": hit.reasons,
        "snippet": _trim_snippet(chunk.text, max_snippet_lines),
    }


def _edge_payload(edge: GraphEdge, repo_index: RepositoryIndex) -> dict[str, Any]:
    source = repo_index.chunk_by_id.get(edge.source)
    target = repo_index.chunk_by_id.get(edge.target)
    return {
        "source": edge.source,
        "target": edge.target,
        "source_label": source.source_label if source else edge.source,
        "target_label": target.source_label if target else edge.target,
        "label": edge.label,
        "weight": edge.weight,
    }


def _recommended_next_steps(result: AgentResult, repo_index: RepositoryIndex) -> list[str]:
    steps = []
    if result.hits:
        top = result.hits[0].chunk
        steps.append(f"Open `{top.relpath}` around lines {top.start_line}-{top.end_line} and verify the top-ranked evidence.")
    if len(result.hits) > 1:
        files = ", ".join(f"`{hit.chunk.relpath}`" for hit in result.hits[1:4])
        steps.append(f"Compare nearby evidence in {files} before editing.")
    commands = repo_index.repository_overview().get("top_files", [])
    if commands:
        steps.append("Run the project's most focused test or syntax check after any edit; do not infer test success from retrieval alone.")
    return steps


def _handoff_prompt(target: str) -> str:
    tool_name = {
        "codex": "Codex",
        "aider": "Aider",
        "openhands": "OpenHands",
        "generic": "a coding agent",
    }.get(target, "a coding agent")
    return (
        f"Use this Repo Agent evidence bundle as the starting context for {tool_name}. "
        "Ground any code changes in the ranked evidence below, inspect the referenced files before editing, "
        "and run an appropriate verification command before claiming the task is complete."
    )


def _inline_code_list(items: list[str]) -> str:
    values = [str(item) for item in items if str(item)]
    return ", ".join(f"`{item}`" for item in values) if values else "`none`"


def _trim_snippet(text: str, max_lines: int) -> str:
    lines = str(text or "").splitlines()
    if len(lines) <= max_lines:
        return str(text or "").strip()
    return "\n".join(lines[:max_lines]).strip() + "\n..."


def _normalize_target(value: str) -> str:
    target = str(value or "generic").strip().lower()
    if target not in BUNDLE_TARGETS:
        raise ValueError(f"target must be one of: {', '.join(sorted(BUNDLE_TARGETS))}")
    return target


def _normalize_format(value: str) -> str:
    fmt = str(value or "markdown").strip().lower()
    if fmt in {"md", "markdown"}:
        return "markdown"
    if fmt == "json":
        return "json"
    raise ValueError(f"format must be one of: {', '.join(sorted(BUNDLE_FORMATS))}")
