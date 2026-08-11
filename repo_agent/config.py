from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RepoAgentConfig:
    project_root: Path
    workspace_root: Path
    allowed_roots: tuple[Path, ...]
    max_question_chars: int
    max_top_k: int
    max_index_files: int
    max_index_file_bytes: int
    audit_log_path: Path

    @classmethod
    def load(cls, project_root: Path) -> RepoAgentConfig:
        project_root = project_root.resolve()
        workspace_root = project_root.parent.resolve()
        extra_roots_raw = os.environ.get("REPO_AGENT_ALLOWED_ROOTS", "").strip()
        extra_roots = tuple(
            Path(item).expanduser().resolve()
            for item in extra_roots_raw.split(os.pathsep)
            if item.strip()
        )
        allowed_roots = (workspace_root, project_root, *extra_roots)
        return cls(
            project_root=project_root,
            workspace_root=workspace_root,
            allowed_roots=allowed_roots,
            max_question_chars=int(os.environ.get("REPO_AGENT_MAX_QUESTION_CHARS", "500")),
            max_top_k=int(os.environ.get("REPO_AGENT_MAX_TOP_K", "12")),
            max_index_files=int(os.environ.get("REPO_AGENT_MAX_INDEX_FILES", "2500")),
            max_index_file_bytes=int(os.environ.get("REPO_AGENT_MAX_INDEX_FILE_BYTES", str(512 * 1024))),
            audit_log_path=project_root / "logs" / "audit.jsonl",
        )
