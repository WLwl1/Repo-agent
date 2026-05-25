from __future__ import annotations

import re
import shlex
from pathlib import Path
from pathlib import PurePosixPath

from .config import RepoAgentConfig


ALLOWED_VERIFICATION_COMMANDS = (
    "npm test",
    "npm run test",
    "npm run build",
    "npm run lint",
    "python -m pytest",
    "python -m repo_agent eval",
    "python -m compileall <paths>",
    "node --check <file>",
    "uv run pytest",
)


def agent_policy(
    *,
    allowed_roots: tuple[Path, ...] = (),
    protected_dirs: tuple[str, ...] = (),
    protected_files: tuple[str, ...] = (),
) -> dict:
    return {
        "repository_access": {
            "allowed_roots": [str(path) for path in allowed_roots],
            "protected_dirs": sorted(protected_dirs),
            "protected_files": sorted(protected_files),
        },
        "tooling": {
            "file_reads": "repository-relative text files only; protected paths are blocked",
            "file_writes": "repository-relative writes only; protected paths and oversized writes are blocked",
            "command_execution": "shell=False verification commands from the allow list only",
            "allowed_verification_commands": list(ALLOWED_VERIFICATION_COMMANDS),
        },
        "execution_modes": {
            "local": "edit the source repository directly",
            "workspace": "edit an isolated runs/<run_id>/workspace copy before applying reviewed changes",
            "recommended_default": "workspace",
        },
    }


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


def parse_command(command: str) -> list[str]:
    try:
        raw_args = shlex.split(str(command or "").strip(), posix=False)
    except ValueError:
        return []
    return [_strip_quotes(arg) for arg in raw_args if _strip_quotes(arg)]


def is_safe_verification_command(command: str) -> bool:
    args = parse_command(command)
    if not args:
        return False

    executable = _executable_stem(args[0])
    lowered = [arg.lower() for arg in args]

    if executable == "npm":
        return _is_safe_npm_command(lowered)
    if executable in {"python", "py"}:
        return _is_safe_python_command(lowered)
    if executable == "node":
        return _is_safe_node_command(args)
    if executable == "uv":
        return lowered == [lowered[0], "run", "pytest"]
    return False


def _is_within_allowed_roots(candidate: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        resolved_root = root.resolve()
        if candidate == resolved_root or resolved_root in candidate.parents:
            return True
    return False


def _strip_quotes(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _executable_stem(value: str) -> str:
    return Path(_strip_quotes(value)).stem.lower()


def _is_safe_npm_command(args: list[str]) -> bool:
    if len(args) == 2 and args[1] == "test":
        return True
    return len(args) == 3 and args[1] == "run" and args[2] in {"test", "build", "lint"}


def _is_safe_python_command(args: list[str]) -> bool:
    executable = args[0]
    if args == [executable, "-m", "pytest"]:
        return True
    if args == [executable, "-m", "repo_agent", "eval"]:
        return True
    if len(args) >= 4 and args[1:3] == ["-m", "compileall"]:
        return all(_is_safe_relative_arg(arg) for arg in args[3:])
    return False


def _is_safe_node_command(args: list[str]) -> bool:
    if len(args) != 3 or args[1].lower() != "--check":
        return False
    target = _strip_quotes(args[2])
    return _is_safe_relative_arg(target) and PurePosixPath(target.replace("\\", "/")).suffix.lower() in {
        ".cjs",
        ".js",
        ".mjs",
    }


def _is_safe_relative_arg(value: str) -> bool:
    text = _strip_quotes(value).replace("\\", "/").strip()
    if not text or text.startswith("-") or "\x00" in text:
        return False
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return False
    path = PurePosixPath(text)
    return ".." not in path.parts
