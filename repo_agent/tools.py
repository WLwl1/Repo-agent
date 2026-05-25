from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .ignore import IGNORED_DIRS, IGNORED_FILES, is_ignored_relpath, relpath_has_ignored_part
from .memory import build_repo_memory, render_repo_brief
from .security import is_safe_verification_command, parse_command, safe_join
EXTRA_TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".ps1",
    ".md",
    ".rst",
    ".txt",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".env",
}
MAX_WRITE_BYTES = 512 * 1024


class RepoTools:
    def __init__(self, repo_index):
        self.repo_index = repo_index

    def repo_memory(self) -> dict:
        return build_repo_memory(self.repo_index)

    def repo_brief(self) -> str:
        return render_repo_brief(self.repo_index)

    def plan(self, query: str):
        return self.repo_index.plan_query(query)

    def semantic_scores(self, query: str) -> dict[str, float]:
        return self.repo_index.semantic_scores_for(query)

    def scout_files(self, plan, limit: int = 6):
        return self.repo_index.scout_files(plan, limit=limit)

    def read_candidates(self, query: str, plan, file_hits, semantic_scores: dict[str, float], *, top_k: int):
        return self.repo_index.read_candidates(query, plan, file_hits, semantic_scores, top_k=top_k)

    def follow_neighbors(self, seed_hits, plan):
        return self.repo_index.follow_neighbors(seed_hits, plan)

    def rerank(self, query: str, plan, seed_hits, file_boosts, relation_boosts, semantic_scores: dict[str, float], *, top_k: int):
        return self.repo_index.rerank_candidates(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )

    def relevant_edges(self, hits):
        return self.repo_index.relevant_edges(hits)

    def list_directory(self, relpath: str = ".", limit: int = 40) -> list[dict]:
        path = self._resolve_repo_path(relpath)
        if not path.is_dir():
            raise ValueError(f"{relpath} is not a directory")
        entries: list[dict] = []
        for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.name in IGNORED_DIRS or child.name in IGNORED_FILES:
                continue
            rel = child.relative_to(self.repo_index.repo_root).as_posix()
            entries.append(
                {
                    "name": child.name,
                    "relpath": rel or ".",
                    "kind": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else 0,
                }
            )
            if len(entries) >= limit:
                break
        return entries

    def search_text(self, terms: list[str], *, relpaths: list[str] | None = None, limit: int = 12) -> list[dict]:
        normalized_terms = [term.strip().lower() for term in terms if term and len(term.strip()) >= 2]
        normalized_terms = list(dict.fromkeys(normalized_terms))
        if not normalized_terms:
            return []

        matches: list[dict] = []
        phrase_terms = [term for term in normalized_terms if " " in term]
        for path in self._search_paths(relpaths):
            text, _encoding = self._read_text_file(path)
            if not text:
                continue
            relpath = path.relative_to(self.repo_index.repo_root).as_posix()
            for line_number, line in enumerate(text.splitlines(), start=1):
                lowered = line.lower()
                matched = [term for term in normalized_terms if term in lowered]
                if not matched:
                    continue
                score = float(len(matched))
                if any(term in lowered for term in phrase_terms):
                    score += 1.5
                matches.append(
                    {
                        "relpath": relpath,
                        "line_number": line_number,
                        "line_text": line.strip(),
                        "matched_terms": matched,
                        "score": score,
                    }
                )
        matches.sort(key=lambda item: (-item["score"], item["relpath"], item["line_number"]))
        return matches[:limit]

    def read_file(self, relpath: str, start_line: int = 1, end_line: int = 120) -> dict:
        path = self._resolve_repo_path(relpath)
        if is_ignored_relpath(path.relative_to(self.repo_index.repo_root).as_posix()):
            raise ValueError(f"{relpath} is protected and cannot be read")
        if not path.is_file():
            raise ValueError(f"{relpath} is not a file")
        text, _encoding = self._read_text_file(path)
        lines = text.splitlines()
        if not lines:
            return {
                "relpath": relpath,
                "start_line": 1,
                "end_line": 1,
                "line_count": 0,
                "content": "",
            }
        start = max(1, start_line)
        end = min(max(start, end_line), len(lines))
        snippet = "\n".join(lines[start - 1 : end]).strip()
        return {
            "relpath": path.relative_to(self.repo_index.repo_root).as_posix(),
            "start_line": start,
            "end_line": end,
            "line_count": len(lines),
            "content": snippet,
        }

    def replace_text(self, relpath: str, old: str, new: str, *, count: int | None = None) -> dict:
        if not old:
            raise ValueError("old text is required")
        path = self._resolve_repo_path(relpath)
        normalized_relpath = path.relative_to(self.repo_index.repo_root).as_posix()
        if is_ignored_relpath(normalized_relpath):
            raise ValueError(f"{relpath} is protected and cannot be edited")
        if not path.is_file():
            raise ValueError(f"{relpath} is not a file")
        text, encoding = self._read_text_file(path)
        occurrences = text.count(old)
        if occurrences == 0:
            return {
                "changed": False,
                "relpath": path.relative_to(self.repo_index.repo_root).as_posix(),
                "occurrences": 0,
            }
        max_count = occurrences if count is None else min(max(0, count), occurrences)
        updated = text.replace(old, new, max_count)
        replaced = max_count if count is not None else occurrences
        path.write_text(updated, encoding=encoding)
        return {
            "changed": True,
            "relpath": normalized_relpath,
            "occurrences": occurrences,
            "replacements": replaced,
        }

    def write_file(self, relpath: str, content: str, *, overwrite: bool = False) -> dict:
        path = self._resolve_repo_path(relpath)
        normalized_relpath = path.relative_to(self.repo_index.repo_root).as_posix()
        if is_ignored_relpath(normalized_relpath):
            raise ValueError(f"{relpath} is protected and cannot be written")
        if path.exists() and not path.is_file():
            raise ValueError(f"{relpath} is not a file")
        if path.exists() and not overwrite:
            raise ValueError(f"{relpath} already exists; use replace_text for existing files or set overwrite=true")
        encoded = str(content or "").encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ValueError(f"content is too large for autonomous write_file ({len(encoded)} bytes)")
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(str(content or ""), encoding="utf-8")
        return {
            "changed": True,
            "created": not existed,
            "relpath": normalized_relpath,
            "bytes": len(encoded),
        }

    def run_command(self, command: str, *, timeout_seconds: int = 20) -> dict:
        args = parse_command(command)
        if not args:
            raise ValueError("command is required")
        if not is_safe_verification_command(command):
            raise ValueError(f"command is not an allowed verification command: {command}")
        normalized_args = self._normalize_command(args)
        completed = subprocess.run(
            normalized_args,
            cwd=self.repo_index.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
        return {
            "command": command,
            "cwd": str(self.repo_index.repo_root),
            "exit_code": completed.returncode,
            "stdout": _trim_output(completed.stdout),
            "stderr": _trim_output(completed.stderr),
        }

    def startup_hints(self) -> dict:
        root = self.repo_index.repo_root
        commands: list[dict] = []

        if (root / "start_studio.bat").is_file():
            commands.append(
                {
                    "label": "Studio bat",
                    "command": "start_studio.bat",
                    "reason": "one-click local web studio launcher",
                }
            )
        if (root / "repo_agent" / "__main__.py").is_file():
            commands.append(
                {
                    "label": "Repo Agent web",
                    "command": "python -m repo_agent serve --host 127.0.0.1 --port 8787",
                    "reason": "start the local Repo Agent web studio",
                }
            )

        package_json = root / "package.json"
        if package_json.is_file():
            scripts = self._package_scripts(package_json)
            for script_name, label, reason in (
                ("dev", "npm dev", "start the development server"),
                ("start", "npm start", "start the application"),
                ("build", "npm build", "build the project"),
                ("test", "npm test", "run the project test suite"),
            ):
                if script_name in scripts:
                    commands.append(
                        {
                            "label": label,
                            "command": f"npm run {script_name}" if script_name not in {"start", "test"} else f"npm {script_name}",
                            "reason": reason,
                        }
                    )

        for filename, label, reason in (
            ("main.py", "main.py", "run the Python main entry"),
            ("app.py", "app.py", "run the Python app entry"),
            ("server.py", "server.py", "run the Python server entry"),
        ):
            if (root / filename).is_file():
                commands.append(
                    {
                        "label": label,
                        "command": f"python {filename}",
                        "reason": reason,
                    }
                )

        verify_command = self.infer_verification_command("检查这个项目现在能不能用")
        return {
            "repo_root": str(root),
            "commands": _dedupe_commands(commands),
            "verify_command": verify_command,
        }

    def infer_verification_command(self, query: str) -> str:
        lowered = query.lower()
        root = self.repo_index.repo_root

        if any(term in lowered for term in ("eval", "评估")) and (root / "repo_agent" / "eval_cases.json").is_file():
            return "python -m repo_agent eval"

        if any(term in lowered for term in ("compile", "编译", "syntax", "语法")):
            parts = [name for name in ("repo_agent", "web", "examples") if (root / name).exists()]
            if parts:
                return "python -m compileall " + " ".join(parts)

        wants_check = any(
            term in lowered
            for term in ("test", "测试", "verify", "验证", "check", "检查", "没法用", "不能用", "跑不起来", "broken")
        )
        if not wants_check:
            return ""

        package_json = root / "package.json"
        if package_json.is_file():
            scripts = self._package_scripts(package_json)
            if "test" in scripts:
                return "npm test"
            if "build" in scripts:
                return "npm run build"
        if (root / "repo_agent" / "eval_cases.json").is_file():
            return "python -m repo_agent eval"
        if (root / "pytest.ini").exists() or (root / "tests").exists():
            return "python -m pytest"
        if (root / "pyproject.toml").exists():
            return "python -m compileall ."
        return ""

    def _resolve_repo_path(self, relpath: str) -> Path:
        clean_relpath = str(relpath or ".").replace("\\", "/")
        return safe_join(self.repo_index.repo_root, clean_relpath)

    def _search_paths(self, relpaths: list[str] | None) -> list[Path]:
        seen: set[str] = set()
        candidates: list[Path] = []
        if relpaths:
            for relpath in relpaths:
                try:
                    path = self._resolve_repo_path(relpath)
                except ValueError:
                    continue
                if path.is_file() and path.name not in IGNORED_FILES:
                    key = str(path)
                    if key not in seen:
                        seen.add(key)
                        candidates.append(path)
        else:
            for fact in self.repo_index.file_facts:
                path = self.repo_index.repo_root / fact.relpath
                key = str(path)
                if path.is_file() and key not in seen:
                    seen.add(key)
                    candidates.append(path)
            for extra in ("README.md", "pyproject.toml", "package.json", ".env.example"):
                path = self.repo_index.repo_root / extra
                key = str(path)
                if path.is_file() and key not in seen:
                    seen.add(key)
                    candidates.append(path)
            for path in sorted(self.repo_index.repo_root.rglob("*")):
                if not path.is_file():
                    continue
                relpath = path.relative_to(self.repo_index.repo_root).as_posix()
                if relpath_has_ignored_part(relpath) or path.name in IGNORED_FILES:
                    continue
                if path.suffix.lower() not in EXTRA_TEXT_SUFFIXES:
                    continue
                key = str(path)
                if key in seen:
                    continue
                try:
                    if path.stat().st_size > 512 * 1024:
                        continue
                except OSError:
                    continue
                seen.add(key)
                candidates.append(path)
        return candidates

    def _normalize_command(self, args: list[str]) -> list[str]:
        executable = Path(args[0].strip("\"")).name.lower()
        executable_stem = Path(executable).stem.lower()
        if executable_stem in {"python", "py"}:
            return [sys.executable, *args[1:]]
        return args

    @staticmethod
    def _package_scripts(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        scripts = payload.get("scripts")
        return scripts if isinstance(scripts, dict) else {}

    @staticmethod
    def _read_text_file(path: Path) -> tuple[str, str]:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                return path.read_text(encoding=encoding), encoding
            except UnicodeDecodeError:
                continue
        return "", "utf-8"


def _trim_output(text: str, max_chars: int = 4000) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 4].rstrip() + "\n..."


def _dedupe_commands(commands: list[dict]) -> list[dict]:
    seen: set[str] = set()
    ordered: list[dict] = []
    for item in commands:
        command = str(item.get("command", "")).strip()
        if not command or command in seen:
            continue
        seen.add(command)
        ordered.append(item)
    return ordered
