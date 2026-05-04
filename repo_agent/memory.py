from __future__ import annotations

from collections import Counter


def build_repo_memory(repo_index) -> dict:
    file_facts = repo_index.file_facts
    role_counter = Counter(role for fact in file_facts for role in fact.roles)

    def top_files_for(role: str, limit: int = 4) -> list[str]:
        return [
            fact.relpath
            for fact in file_facts
            if role in fact.roles
        ][:limit]

    frontend_files = top_files_for("frontend")
    backend_files = top_files_for("backend")
    entrypoints = top_files_for("entrypoint")
    config_files = top_files_for("config")
    test_files = top_files_for("tests")

    summary_parts = []
    if frontend_files:
        summary_parts.append(f"frontend={', '.join(frontend_files[:2])}")
    if backend_files:
        summary_parts.append(f"backend={', '.join(backend_files[:2])}")
    if entrypoints:
        summary_parts.append(f"entry={', '.join(entrypoints[:2])}")
    if config_files:
        summary_parts.append(f"config={', '.join(config_files[:2])}")

    summary = " | ".join(summary_parts) or "generic repository"
    return {
        "summary": summary,
        "role_counts": dict(role_counter),
        "frontend_files": frontend_files,
        "backend_files": backend_files,
        "entrypoints": entrypoints,
        "config_files": config_files,
        "test_files": test_files,
    }


def render_repo_brief(repo_index) -> str:
    memory = build_repo_memory(repo_index)
    stats = repo_index.stats()
    lines = [
        f"repo={repo_index.repo_root}",
        f"files={stats.get('file_count', 0)} chunks={stats.get('chunk_count', 0)} edges={stats.get('graph_edge_count', 0)}",
        f"summary={memory['summary']}",
    ]
    if memory["entrypoints"]:
        lines.append(f"entrypoints={', '.join(memory['entrypoints'][:3])}")
    if memory["frontend_files"]:
        lines.append(f"frontend={', '.join(memory['frontend_files'][:3])}")
    if memory["backend_files"]:
        lines.append(f"backend={', '.join(memory['backend_files'][:3])}")
    if memory["config_files"]:
        lines.append(f"config={', '.join(memory['config_files'][:3])}")
    return "\n".join(lines)
