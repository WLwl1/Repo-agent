from __future__ import annotations

import json
from pathlib import Path

from .agent import RepoAgent
from .audit import AuditLogger
from .bundle import build_evidence_bundle, default_bundle_path, write_evidence_bundle
from .cache import IndexCache
from .config import RepoAgentConfig
from .engineering import EngineeringAgent, create_workspace_copy, new_run_id
from .indexer import RepositoryIndex, build_index
from .llm import LLMClient
from .memory import build_repo_memory, render_repo_brief
from .models import AgentResult
from .report import write_html_report
from .ignore import IGNORED_DIRS, IGNORED_FILES
from .security import agent_policy, safe_join, validate_question, validate_repo_path
from .tools import RepoTools


class RepoAgentRuntime:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config = RepoAgentConfig.load(project_root)
        self.reports_dir = self.project_root / "reports"
        self.runs_dir = self.project_root / "runs"
        self.cache = IndexCache(self.project_root / ".cache")
        self.audit = AuditLogger(self.config.audit_log_path)
        self.llm = LLMClient.from_env(project_root / ".env")
        self._memory: dict[str, RepositoryIndex] = {}
        self._memory_signature: dict[str, str] = {}
        self._repo_memory: dict[str, dict] = {}

    def load_index(self, repo_path: str | Path, force_rebuild: bool = False) -> RepositoryIndex:
        repo_root = validate_repo_path(repo_path, self.config)
        signature = self.cache.signature_for(repo_root)
        cache_key = str(repo_root)
        if not force_rebuild and cache_key in self._memory and self._memory_signature.get(cache_key) == signature:
            self.audit.log("index_cache_hit", repo=str(repo_root))
            return self._memory[cache_key]
        repo_index = None if force_rebuild else self.cache.load(repo_root, signature)
        if repo_index is None:
            repo_index = build_index(
                repo_root,
                max_files=self.config.max_index_files,
                max_file_bytes=self.config.max_index_file_bytes,
            )
            self.cache.save(repo_root, signature, repo_index)
            self.audit.log("index_built", repo=str(repo_root), chunks=repo_index.stats().get("chunk_count", 0))
        else:
            self.audit.log("index_cache_load", repo=str(repo_root))
        self._memory[cache_key] = repo_index
        self._memory_signature[cache_key] = signature
        self._repo_memory[cache_key] = build_repo_memory(repo_index)
        return repo_index

    def ask(
        self,
        repo_path: str | Path,
        question: str,
        top_k: int = 6,
        use_model: bool = False,
        force_rebuild: bool = False,
    ) -> tuple[AgentResult, RepositoryIndex]:
        repo_root = validate_repo_path(repo_path, self.config)
        safe_question = validate_question(question, self.config)
        repo_index = self.load_index(repo_root, force_rebuild=force_rebuild)
        agent = RepoAgent(repo_index, llm_client=self.llm if use_model else None)
        result = agent.answer(safe_question, top_k=top_k, use_model=use_model)
        self.audit.log(
            "ask",
            repo=str(repo_root),
            mode=result.mode,
            use_model=bool(result.model_name),
            top_hit=result.hits[0].chunk.source_label if result.hits else "",
        )
        return result, repo_index

    def generate_report(
        self,
        repo_path: str | Path,
        question: str,
        top_k: int = 6,
        use_model: bool = False,
        force_rebuild: bool = False,
        output_path: str | Path | None = None,
    ) -> tuple[AgentResult, RepositoryIndex, Path]:
        result, repo_index = self.ask(
            repo_path=repo_path,
            question=question,
            top_k=top_k,
            use_model=use_model,
            force_rebuild=force_rebuild,
        )
        if output_path is None:
            output = self._default_report_path(question)
        else:
            output = Path(output_path).expanduser().resolve()
        report_path = write_html_report(
            query=question,
            result=result,
            repo_stats=repo_index.stats(),
            file_facts=repo_index.file_facts,
            output_path=output,
        )
        result.report_path = str(report_path)
        self.audit.log("report_generated", repo=str(validate_repo_path(repo_path, self.config)), report=str(report_path))
        return result, repo_index, report_path

    def generate_bundle(
        self,
        repo_path: str | Path,
        question: str,
        *,
        target: str = "generic",
        fmt: str = "markdown",
        top_k: int = 6,
        use_model: bool = False,
        force_rebuild: bool = False,
        output_path: str | Path | None = None,
    ) -> tuple[dict, Path]:
        result, repo_index = self.ask(
            repo_path=repo_path,
            question=question,
            top_k=top_k,
            use_model=use_model,
            force_rebuild=force_rebuild,
        )
        bundle = build_evidence_bundle(result=result, repo_index=repo_index, target=target)
        output = (
            Path(output_path).expanduser().resolve()
            if output_path is not None
            else default_bundle_path(self.reports_dir, question, fmt=fmt)
        )
        bundle_path = write_evidence_bundle(bundle, output, fmt=fmt)
        self.audit.log(
            "bundle_generated",
            repo=str(repo_index.repo_root),
            bundle=str(bundle_path),
            target=str(bundle.get("target", "")),
        )
        return bundle, bundle_path

    def health(self) -> dict:
        return {
            "ok": True,
            "cached_indexes": len(self._memory),
            "llm_available": self.llm.available,
            "model": self.llm.model if self.llm.available else "",
            "allowed_roots": [str(path) for path in self.config.allowed_roots],
            "max_question_chars": self.config.max_question_chars,
            "max_top_k": self.config.max_top_k,
            "audit_log": str(self.config.audit_log_path),
            "runs_dir": str(self.runs_dir),
            "agent_policy": agent_policy(
                allowed_roots=self.config.allowed_roots,
                protected_dirs=tuple(IGNORED_DIRS),
                protected_files=tuple(IGNORED_FILES),
            ),
        }

    def engineer(
        self,
        repo_path: str | Path,
        task: str,
        *,
        max_steps: int | None = None,
        execution_mode: str = "workspace",
        force_rebuild: bool = False,
    ) -> tuple[dict, RepositoryIndex]:
        repo_root = validate_repo_path(repo_path, self.config)
        safe_task = str(task or "").strip()
        if not safe_task:
            raise ValueError("task is required")
        if len(safe_task) > 4000:
            raise ValueError("task is too long (max 4000 characters)")
        mode = _execution_mode(execution_mode)
        run_id = new_run_id(safe_task)
        effective_repo_root = repo_root
        if mode == "workspace":
            effective_repo_root = create_workspace_copy(repo_root, self.runs_dir, run_id)
        repo_index = self.load_index(effective_repo_root, force_rebuild=force_rebuild or mode == "workspace")
        agent = EngineeringAgent(
            repo_index,
            self.llm,
            self.runs_dir,
            source_repo_root=repo_root,
            execution_mode=mode,
        )
        result = agent.run(safe_task, max_steps=max_steps, run_id=run_id)
        self.audit.log(
            "engineer",
            repo=str(repo_root),
            run_id=result.run_id,
            status=result.status,
            changed_files=",".join(result.changed_files),
        )
        return result.as_dict(), repo_index

    def resume_engineering_run(self, run_id: str, *, max_steps: int | None = None) -> tuple[dict, RepositoryIndex]:
        data = self.read_engineering_run(run_id)
        repo_root = validate_repo_path(data.get("repo_root", ""), self.config)
        repo_index = self.load_index(repo_root, force_rebuild=False)
        source_root = Path(data.get("source_repo_root") or repo_root).expanduser().resolve()
        agent = EngineeringAgent(
            repo_index,
            self.llm,
            self.runs_dir,
            source_repo_root=source_root,
            execution_mode=str(data.get("execution_mode", "local")),
        )
        result = agent.run(str(data.get("task", "")), max_steps=max_steps, resume_data=data)
        self.audit.log("engineer_resume", repo=str(repo_root), run_id=result.run_id, status=result.status)
        return result.as_dict(), repo_index

    def list_engineering_runs(self, limit: int = 30) -> list[dict]:
        runs = []
        if not self.runs_dir.exists():
            return runs
        for path in sorted(self.runs_dir.glob("run_*/run.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            runs.append(
                {
                    "run_id": data.get("run_id", path.parent.name),
                    "status": data.get("status", ""),
                    "task": data.get("task", ""),
                    "model": data.get("model", ""),
                    "execution_mode": data.get("execution_mode", "local"),
                    "applied": bool(data.get("applied", False)),
                    "changed_files": data.get("changed_files", []),
                    "run_path": str(path.parent),
                    "workspace_root": data.get("workspace_root", ""),
                }
            )
            if len(runs) >= limit:
                break
        return runs

    def read_engineering_run(self, run_id: str) -> dict:
        clean = str(run_id or "").strip()
        if not clean or "/" in clean or "\\" in clean or ".." in clean:
            raise ValueError("invalid run id")
        path = self.runs_dir / clean / "run.json"
        if not path.is_file():
            raise ValueError("run not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def apply_engineering_run(self, run_id: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise ValueError("confirm=true is required to apply a workspace run")
        data = self.read_engineering_run(run_id)
        if data.get("execution_mode") != "workspace":
            raise ValueError("only workspace runs can be applied")
        if data.get("applied"):
            return {"run_id": data.get("run_id"), "applied": True, "applied_files": data.get("applied_files", [])}

        source_root = validate_repo_path(data.get("source_repo_root", ""), self.config)
        workspace_root = Path(str(data.get("workspace_root", ""))).expanduser().resolve()
        if not workspace_root.is_dir():
            raise ValueError("workspace root does not exist")
        if self.runs_dir.resolve() not in workspace_root.parents:
            raise ValueError("workspace root is outside the runs directory")

        applied_files: list[str] = []
        for relpath in data.get("changed_files", []):
            clean = str(relpath or "").replace("\\", "/").strip()
            if not clean or clean.startswith(".env") or "/.env" in clean:
                continue
            source_path = safe_join(source_root, clean)
            workspace_path = safe_join(workspace_root, clean)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            if workspace_path.is_file():
                source_path.write_bytes(workspace_path.read_bytes())
                applied_files.append(clean)
            elif source_path.exists() and source_path.is_file():
                source_path.unlink()
                applied_files.append(clean)

        data["applied"] = True
        data["applied_files"] = applied_files
        data["applied_at"] = _utc_now()
        data.setdefault("trace", []).append(
            {
                "step": len(data.get("trace", [])) + 1,
                "type": "applied_to_source",
                "content": "\n".join(applied_files) or "no files applied",
                "created_at": data["applied_at"],
            }
        )
        run_path = self.runs_dir / str(data.get("run_id", run_id)) / "run.json"
        run_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.audit.log("engineer_apply", run_id=str(data.get("run_id", run_id)), applied_files=",".join(applied_files))
        return {
            "run_id": data.get("run_id", run_id),
            "applied": True,
            "applied_files": applied_files,
            "source_repo_root": str(source_root),
        }

    def repo_memory(self, repo_path: str | Path) -> dict:
        repo_index = self.load_index(repo_path)
        cache_key = str(repo_index.repo_root)
        memory = self._repo_memory.get(cache_key)
        if memory is None:
            memory = build_repo_memory(repo_index)
            self._repo_memory[cache_key] = memory
        return {
            **memory,
            "brief": render_repo_brief(repo_index),
        }

    def startup_hints(self, repo_path: str | Path, force_rebuild: bool = False) -> dict:
        repo_index = self.load_index(repo_path, force_rebuild=force_rebuild)
        hints = RepoTools(repo_index).startup_hints()
        self.audit.log("startup_hints", repo=str(repo_index.repo_root), command_count=len(hints.get("commands", [])))
        return hints

    def workspace_tool(
        self,
        repo_path: str | Path,
        action: str,
        payload: dict | None = None,
        *,
        force_rebuild: bool = False,
    ) -> tuple[dict, RepositoryIndex]:
        repo_root = validate_repo_path(repo_path, self.config)
        repo_index = self.load_index(repo_root, force_rebuild=force_rebuild)
        tools = RepoTools(repo_index)
        data = payload or {}
        action_name = str(action or "").strip().lower()

        if action_name == "list":
            result = {
                "action": action_name,
                "path": str(data.get("path", ".") or "."),
                "entries": tools.list_directory(
                    str(data.get("path", ".") or "."),
                    limit=_int_value(data.get("limit"), default=40, minimum=1, maximum=120),
                ),
            }
        elif action_name == "read":
            result = {
                "action": action_name,
                **tools.read_file(
                    str(data.get("path", "")).strip(),
                    start_line=_int_value(data.get("start_line"), default=1, minimum=1, maximum=200000),
                    end_line=_int_value(data.get("end_line"), default=120, minimum=1, maximum=200000),
                ),
            }
        elif action_name == "search":
            terms_raw = data.get("terms", [])
            if isinstance(terms_raw, str):
                terms = [item.strip() for item in terms_raw.replace("\r", "\n").split("\n") if item.strip()]
            elif isinstance(terms_raw, list):
                terms = [str(item).strip() for item in terms_raw if str(item).strip()]
            else:
                terms = []
            relpaths_raw = data.get("relpaths", [])
            relpaths = [str(item).strip() for item in relpaths_raw if str(item).strip()] if isinstance(relpaths_raw, list) else None
            result = {
                "action": action_name,
                "terms": terms,
                "matches": tools.search_text(
                    terms,
                    relpaths=relpaths,
                    limit=_int_value(data.get("limit"), default=12, minimum=1, maximum=60),
                ),
            }
        elif action_name == "run":
            command = str(data.get("command", "")).strip()
            result = {
                "action": action_name,
                **tools.run_command(
                    command,
                    timeout_seconds=_int_value(data.get("timeout_seconds"), default=20, minimum=1, maximum=90),
                ),
            }
        elif action_name == "verify":
            query = str(data.get("query", "帮我检查这个项目现在能不能用")).strip() or "帮我检查这个项目现在能不能用"
            command = tools.infer_verification_command(query)
            if not command:
                result = {
                    "action": action_name,
                    "command": "",
                    "supported": False,
                    "message": "No verification command could be inferred for this repository.",
                }
            else:
                result = {
                    "action": action_name,
                    "supported": True,
                    **tools.run_command(
                        command,
                        timeout_seconds=_int_value(data.get("timeout_seconds"), default=45, minimum=1, maximum=120),
                    ),
                }
        elif action_name == "startup":
            result = {
                "action": action_name,
                **tools.startup_hints(),
            }
        else:
            raise ValueError("unknown tool action")

        self.audit.log("workspace_tool", repo=str(repo_index.repo_root), action=action_name)
        return result, repo_index

    def _default_report_path(self, question: str) -> Path:
        safe_name = "".join(char if char.isalnum() else "_" for char in question.lower()).strip("_") or "report"
        return (self.reports_dir / f"{safe_name[:48]}.html").resolve()


def _int_value(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(maximum, numeric))


def _execution_mode(value: str) -> str:
    mode = str(value or "local").strip().lower()
    if mode in {"workspace", "sandbox", "copy"}:
        return "workspace"
    return "local"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
