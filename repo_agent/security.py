from __future__ import annotations

from pathlib import Path

from .config import RepoAgentConfig


def validate_repo_path(repo_path: str | Path, config: RepoAgentConfig) -> Path:
    candidate = Path(repo_path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("repo path does not exist or is not a directory")
    if not _is_within_allowed_roots(candidate, config.allowed_roots):
        raise ValueError("repo path is outside the allowed workspace")
    return candidate


def validate_question(question: str, config: RepoAgentConfig) -> str:
    cleaned = str(question or "").strip()
    if not cleaned:
        raise ValueError("question is required")
    if len(cleaned) > config.max_question_chars:
        raise ValueError(f"question is too long (max {config.max_question_chars} characters)")
    return cleaned


def clamp_top_k(value: int | str | None, config: RepoAgentConfig, default: int = 6) -> int:
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = default
    return max(1, min(config.max_top_k, numeric))


def safe_join(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / relative_path).resolve()
    if base_dir.resolve() not in candidate.parents and candidate != base_dir.resolve():
        raise ValueError("path traversal is not allowed")
    return candidate


def _is_within_allowed_roots(candidate: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        resolved_root = root.resolve()
        if candidate == resolved_root or resolved_root in candidate.parents:
            return True
    return False
