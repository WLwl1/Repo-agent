from __future__ import annotations

import hashlib
import difflib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import LLMClient, message_text
from .security import is_safe_verification_command, safe_join
from .tools import RepoTools


@dataclass(slots=True)
class EngineeringRun:
    run_id: str
    repo_root: str
    task: str
    status: str
    model: str
    run_path: str
    source_repo_root: str = ""
    workspace_root: str = ""
    execution_mode: str = "local"
    plan: str = ""
    answer: str = ""
    review: str = ""
    applied: bool = False
    applied_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    verification: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    diff: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "repo_root": self.repo_root,
            "task": self.task,
            "status": self.status,
            "model": self.model,
            "run_path": self.run_path,
            "source_repo_root": self.source_repo_root,
            "workspace_root": self.workspace_root,
            "execution_mode": self.execution_mode,
            "plan": self.plan,
            "answer": self.answer,
            "review": self.review,
            "applied": self.applied,
            "applied_files": self.applied_files,
            "changed_files": self.changed_files,
            "verification": self.verification,
            "trace": self.trace,
            "messages": self.messages,
            "diff": self.diff,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngineeringRun":
        return cls(
            run_id=str(data.get("run_id", "")),
            repo_root=str(data.get("repo_root", "")),
            task=str(data.get("task", "")),
            status=str(data.get("status", "running")),
            model=str(data.get("model", "")),
            run_path=str(data.get("run_path", "")),
            source_repo_root=str(data.get("source_repo_root", "")),
            workspace_root=str(data.get("workspace_root", "")),
            execution_mode=str(data.get("execution_mode", "local")),
            plan=str(data.get("plan", "")),
            answer=str(data.get("answer", "")),
            review=str(data.get("review", "")),
            applied=bool(data.get("applied", False)),
            applied_files=[str(item) for item in data.get("applied_files", [])],
            changed_files=[str(item) for item in data.get("changed_files", [])],
            verification=list(data.get("verification", [])),
            trace=list(data.get("trace", [])),
            messages=list(data.get("messages", [])),
            diff=str(data.get("diff", "")),
        )


class EngineeringAgent:
    def __init__(
        self,
        repo_index,
        llm_client: LLMClient,
        runs_dir: Path,
        *,
        source_repo_root: Path | None = None,
        execution_mode: str = "local",
    ):
        self.repo_index = repo_index
        self.tools = RepoTools(repo_index)
        self.llm_client = llm_client
        self.runs_dir = runs_dir
        self.source_repo_root = source_repo_root or repo_index.repo_root
        self.execution_mode = execution_mode
        self._snapshots: dict[str, dict[str, Any]] = {}

    def run(
        self,
        task: str,
        *,
        max_steps: int | None = None,
        run_id: str | None = None,
        resume_data: dict[str, Any] | None = None,
    ) -> EngineeringRun:
        max_steps = max(1, min(max_steps or _env_int("AGENT_MAX_STEPS", 6), 20))
        if resume_data:
            run = EngineeringRun.from_dict(resume_data)
            run.status = "running"
            run.model = self.llm_client.model if self.llm_client.available else run.model
            messages = run.messages or self._initial_messages(run)
            self._record(run, "run_resumed", f"repo={run.repo_root}\nmodel={run.model}\nmax_steps={max_steps}")
        else:
            run = self._new_run(task, run_id=run_id)
            messages = self._initial_messages(run)
            run.messages = messages
            self._record(
                run,
                "run_start",
                (
                    f"repo={run.repo_root}\n"
                    f"source_repo={run.source_repo_root}\n"
                    f"execution_mode={run.execution_mode}\n"
                    f"model={run.model}\n"
                    f"max_steps={max_steps}"
                ),
            )

        if not self.llm_client.available:
            run.status = "model_unavailable"
            run.answer = "Model is not configured. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL in .env."
            self._record(run, "stop", run.answer)
            self._persist(run)
            return run

        if not resume_data:
            run.plan = self._plan_run(run)
            if run.plan:
                self._record(run, "planner", run.plan)
                messages.append({"role": "assistant", "content": f"Plan:\n{run.plan}"})
                run.messages = _trim_messages(messages)
                self._persist(run)

        final_answer = ""
        for _ in range(max_steps):
            response = self.llm_client.chat(messages, tools=self._tool_schemas(), tool_choice="auto", temperature=0.12)
            if response is None:
                run.status = "failed"
                run.answer = "Model request failed before the engineering run could complete."
                self._record(run, "model_error", run.answer)
                break

            assistant_message = response.message
            messages.append(_assistant_message_for_history(assistant_message))
            run.messages = _trim_messages(messages)
            self._persist(run)
            content = message_text(assistant_message).strip()
            if content:
                self._record(run, "agent_message", content)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                final_answer = content
                run.status = "completed" if content else "stopped"
                break

            should_finish = False
            for call in tool_calls[:4]:
                function = call.get("function") or {}
                name = str(function.get("name", "")).strip()
                args = _json_object(function.get("arguments", "{}"))
                self._record(run, "tool_call", f"{name}({json.dumps(args, ensure_ascii=False)})")

                observation = self._execute_tool(name, args, run)
                observation_text = _compact_json(observation)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": name,
                        "content": observation_text,
                    }
                )
                run.messages = _trim_messages(messages)
                self._record(run, "tool_observation", observation_text)
                if name == "finish":
                    should_finish = True
                    final_answer = str(args.get("summary", "") or observation.get("summary", "")).strip()
                    run.status = str(args.get("status", "completed") or "completed")
                    break

            if should_finish:
                break

        if not run.status or run.status == "running":
            run.status = "max_steps_reached"
            final_answer = final_answer or "Stopped after reaching the maximum autonomous step budget."

        run.diff = _run_diff(self.repo_index.repo_root, self._snapshots)
        run.answer = final_answer or run.answer or self._fallback_answer(run)
        run.review = self._review_run(run)
        if run.review:
            self._record(run, "review", run.review)
        self._record(run, "run_end", run.answer)
        self._persist(run)
        return run

    def _execute_tool(self, name: str, args: dict[str, Any], run: EngineeringRun) -> dict[str, Any]:
        try:
            if name == "repo_brief":
                return {"brief": self.tools.repo_brief(), "memory": self.tools.repo_memory()}

            if name == "find_relevant_code":
                question = str(args.get("question", run.task) or run.task)
                top_k = _int(args.get("top_k"), default=6, minimum=1, maximum=12)
                return self._find_relevant_code(question, top_k=top_k)

            if name == "list_directory":
                path = str(args.get("path", ".") or ".")
                limit = _int(args.get("limit"), default=40, minimum=1, maximum=120)
                return {"path": path, "entries": self.tools.list_directory(path, limit=limit)}

            if name == "search_text":
                terms = _string_list(args.get("terms"))
                relpaths = _string_list(args.get("relpaths")) or None
                limit = _int(args.get("limit"), default=20, minimum=1, maximum=80)
                return {"terms": terms, "matches": self.tools.search_text(terms, relpaths=relpaths, limit=limit)}

            if name == "read_file":
                return self.tools.read_file(
                    str(args.get("path", "")).strip(),
                    start_line=_int(args.get("start_line"), default=1, minimum=1, maximum=200000),
                    end_line=_int(args.get("end_line"), default=160, minimum=1, maximum=200000),
                )

            if name == "replace_text":
                self._snapshot_file(str(args.get("path", "")).strip())
                result = self.tools.replace_text(
                    str(args.get("path", "")).strip(),
                    str(args.get("old", "")),
                    str(args.get("new", "")),
                    count=_optional_int(args.get("count")),
                )
                if result.get("changed"):
                    self._remember_changed_file(run, str(result.get("relpath", "")))
                return result

            if name == "write_file":
                self._snapshot_file(str(args.get("path", "")).strip())
                result = self.tools.write_file(
                    str(args.get("path", "")).strip(),
                    str(args.get("content", "")),
                    overwrite=bool(args.get("overwrite", False)),
                )
                if result.get("changed"):
                    self._remember_changed_file(run, str(result.get("relpath", "")))
                return result

            if name == "run_command":
                command = str(args.get("command", "")).strip()
                if not _is_safe_engineering_command(command):
                    return {"error": f"command is not allowed for autonomous engineering: {command}"}
                result = self.tools.run_command(
                    command,
                    timeout_seconds=_int(args.get("timeout_seconds"), default=90, minimum=1, maximum=180),
                )
                run.verification.append(result)
                return result

            if name == "git_status":
                return _git_status(self.repo_index.repo_root)

            if name == "diff_summary":
                return {
                    "changed_files": run.changed_files,
                    "diff": _run_diff(self.repo_index.repo_root, self._snapshots),
                }

            if name == "revert_file":
                relpath = str(args.get("path", "")).strip()
                return self._revert_file(run, relpath)

            if name == "finish":
                return {
                    "status": str(args.get("status", "completed") or "completed"),
                    "summary": str(args.get("summary", "") or ""),
                    "changed_files": run.changed_files,
                    "verification": run.verification[-4:],
                }

            return {"error": f"unknown tool: {name}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "tool": name}

    def _initial_messages(self, run: EngineeringRun) -> list[dict[str, Any]]:
        workspace_note = (
            "You are editing an isolated workspace copy. Do not assume changes are applied to the source repository "
            "until the user copies or reviews the diff."
            if run.execution_mode == "workspace"
            else "You are editing the source repository directly. Keep changes tightly scoped."
        )
        return [
            {
                "role": "system",
                "content": (
                    "You are an autonomous software engineering agent. "
                    "Your job is to inspect the repository, make focused code changes when needed, "
                    "run verification commands, repair failures, and finish with a concise delivery note. "
                    "Use tools for all repository facts, edits, and command results. "
                    "Prefer replace_text for existing files and write_file only for new or full-file rewrites. "
                    "Never read or edit protected paths such as .env, .git, logs, reports, caches, or saved run workspaces. "
                    "Use git_status and diff_summary before finish when you edited files. "
                    "Use revert_file if an edit is wrong. "
                    "Never claim tests passed unless run_command observed a zero exit code. "
                    "Keep edits minimal and consistent with the existing codebase."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Repository root: {self.repo_index.repo_root}\n"
                    f"Source repository root: {run.source_repo_root}\n"
                    f"Execution mode: {run.execution_mode}\n"
                    f"{workspace_note}\n\n"
                    f"Repository brief:\n{self.tools.repo_brief()}\n\n"
                    f"Engineering task:\n{run.task}\n\n"
                    "Work autonomously. Call finish only when you have completed the task or found a concrete blocker."
                ),
            },
        ]

    def _find_relevant_code(self, question: str, *, top_k: int) -> dict[str, Any]:
        plan = self.tools.plan(question)
        semantic_scores = self.tools.semantic_scores(question)
        file_hits = self.tools.scout_files(plan, limit=max(6, top_k + 2))
        seed_hits, file_boosts = self.tools.read_candidates(question, plan, file_hits, semantic_scores, top_k=top_k)
        relation_boosts, _hop_trace = self.tools.follow_neighbors(seed_hits[: max(2, min(4, top_k))], plan)
        final_hits = self.tools.rerank(
            question,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )
        return {
            "mode": plan.mode,
            "intent": plan.intent,
            "focus_terms": plan.focus_terms[:12],
            "hits": [
                {
                    "source_label": hit.chunk.source_label,
                    "relpath": hit.chunk.relpath,
                    "symbol_name": hit.chunk.symbol_name,
                    "start_line": hit.chunk.start_line,
                    "end_line": hit.chunk.end_line,
                    "score": round(hit.score, 3),
                    "reasons": hit.reasons[:6],
                    "snippet": _trim_text(hit.chunk.text, 24),
                }
                for hit in final_hits
            ],
        }

    def _new_run(self, task: str, *, run_id: str | None = None) -> EngineeringRun:
        run_id = run_id or _run_id(task)
        run_path = self.runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)
        return EngineeringRun(
            run_id=run_id,
            repo_root=str(self.repo_index.repo_root),
            task=task,
            status="running",
            model=self.llm_client.model if self.llm_client.available else "",
            run_path=str(run_path),
            source_repo_root=str(self.source_repo_root),
            workspace_root=str(self.repo_index.repo_root) if self.execution_mode == "workspace" else "",
            execution_mode=self.execution_mode,
        )

    def _record(self, run: EngineeringRun, event_type: str, content: str) -> None:
        run.trace.append(
            {
                "step": len(run.trace) + 1,
                "type": event_type,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._persist(run)

    def _persist(self, run: EngineeringRun) -> None:
        path = Path(run.run_path) / "run.json"
        path.write_text(json.dumps(run.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _remember_changed_file(self, run: EngineeringRun, relpath: str) -> None:
        if relpath and relpath not in run.changed_files:
            run.changed_files.append(relpath)

    def _snapshot_file(self, relpath: str) -> None:
        if not relpath or relpath in self._snapshots:
            return
        try:
            path = safe_join(self.repo_index.repo_root, relpath)
        except ValueError:
            return
        try:
            self._snapshots[relpath] = {
                "exists": path.is_file(),
                "content": path.read_text(encoding="utf-8") if path.is_file() else "",
            }
        except UnicodeDecodeError:
            self._snapshots[relpath] = {"exists": path.is_file(), "content": ""}

    def _revert_file(self, run: EngineeringRun, relpath: str) -> dict[str, Any]:
        snapshot = self._snapshots.get(relpath)
        if snapshot is None:
            return {"changed": False, "error": f"no snapshot is available for {relpath}"}
        path = safe_join(self.repo_index.repo_root, relpath)
        if snapshot.get("exists"):
            path.write_text(str(snapshot.get("content", "")), encoding="utf-8")
            changed = True
        elif path.exists() and path.is_file():
            path.unlink()
            changed = True
        else:
            changed = False
        if relpath in run.changed_files:
            run.changed_files.remove(relpath)
        return {"changed": changed, "relpath": relpath, "reverted": True}

    def _review_run(self, run: EngineeringRun) -> str:
        if not self.llm_client.available or not run.diff:
            return ""
        prompt = (
            "Review this autonomous engineering run. Focus on bugs, missing verification, unsafe changes, "
            "and whether the final answer is supported by the observed verification. Be concise.\n\n"
            f"Task:\n{run.task}\n\n"
            f"Changed files:\n{', '.join(run.changed_files) or 'none'}\n\n"
            f"Verification:\n{json.dumps(run.verification[-5:], ensure_ascii=False, indent=2)}\n\n"
            f"Diff:\n{run.diff[:12000]}"
        )
        response = self.llm_client.chat(
            [
                {"role": "system", "content": "You are a strict code reviewer for an autonomous coding agent."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        return message_text(response.message).strip() if response else ""

    def _plan_run(self, run: EngineeringRun) -> str:
        response = self.llm_client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the planner for an autonomous software engineering agent. "
                        "Return a short implementation plan with likely files to inspect, verification strategy, "
                        "and risks. Do not claim to have read files."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Repository brief:\n{self.tools.repo_brief()}\n\n"
                        f"Task:\n{run.task}\n\n"
                        f"Execution mode: {run.execution_mode}"
                    ),
                },
            ],
            temperature=0.1,
        )
        return message_text(response.message).strip() if response else ""

    def _fallback_answer(self, run: EngineeringRun) -> str:
        parts = [f"Engineering run `{run.run_id}` ended with status `{run.status}`."]
        if run.changed_files:
            parts.append("Changed files: " + ", ".join(f"`{item}`" for item in run.changed_files))
        if run.verification:
            last = run.verification[-1]
            parts.append(f"Last verification: `{last.get('command', '')}` exit code `{last.get('exit_code', '?')}`.")
        return "\n".join(parts)

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            _tool("repo_brief", "Return repository memory and a compact overview.", {}),
            _tool(
                "find_relevant_code",
                "Run graph-aware code retrieval for the task.",
                {
                    "question": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                ["question"],
            ),
            _tool(
                "list_directory",
                "List a repository directory.",
                {
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 120},
                },
                ["path"],
            ),
            _tool(
                "search_text",
                "Search exact text terms in the repository.",
                {
                    "terms": {"type": "array", "items": {"type": "string"}},
                    "relpaths": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 80},
                },
                ["terms"],
            ),
            _tool(
                "read_file",
                "Read a repository file range.",
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                ["path"],
            ),
            _tool(
                "replace_text",
                "Replace exact text in an existing file. Use small, unique old text.",
                {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "count": {"type": "integer", "minimum": 0},
                },
                ["path", "old", "new"],
            ),
            _tool(
                "write_file",
                "Create a new file or overwrite a full file when explicitly needed.",
                {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                ["path", "content"],
            ),
            _tool(
                "run_command",
                "Run an allow-listed verification command such as tests, builds, compile checks, or node --check.",
                {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 180},
                },
                ["command"],
            ),
            _tool("git_status", "Return git status for the active repository/workspace.", {}),
            _tool("diff_summary", "Return the current diff from files edited in this run.", {}),
            _tool(
                "revert_file",
                "Revert a file to its pre-run snapshot if the current edit is wrong.",
                {"path": {"type": "string"}},
                ["path"],
            ),
            _tool(
                "finish",
                "Finish the engineering run with status and delivery summary.",
                {
                    "status": {"type": "string", "enum": ["completed", "blocked", "failed"]},
                    "summary": {"type": "string"},
                },
                ["status", "summary"],
            ),
        ]


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def _assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
    history = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        history["tool_calls"] = message["tool_calls"]
    return history


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace("\r", "\n").replace(",", "\n").split("\n") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(maximum, numeric))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _compact_json(payload: dict[str, Any], max_chars: int = 14000) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n... <truncated>"


def _trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limit = max(4, _env_int("AGENT_MAX_HISTORY_MESSAGES", 24))
    if len(messages) <= limit:
        return messages
    return messages[:2] + messages[-(limit - 2) :]


def _trim_text(text: str, max_lines: int) -> str:
    lines = str(text or "").splitlines()
    if len(lines) <= max_lines:
        return str(text or "").strip()
    return "\n".join(lines[:max_lines]).strip() + "\n..."


def _run_id(task: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha1(task.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"run_{stamp}_{digest}"


def new_run_id(task: str) -> str:
    return _run_id(task)


def _is_safe_engineering_command(command: str) -> bool:
    return is_safe_verification_command(command)


def _run_diff(repo_root: Path, snapshots: dict[str, dict[str, Any]], max_chars: int = 30000) -> str:
    chunks: list[str] = []
    for relpath, snapshot in snapshots.items():
        try:
            path = safe_join(repo_root, relpath)
        except ValueError:
            continue
        before = str(snapshot.get("content", ""))
        try:
            after = path.read_text(encoding="utf-8") if path.is_file() else ""
        except UnicodeDecodeError:
            after = ""
        if before == after:
            continue
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=f"a/{relpath}",
                tofile=f"b/{relpath}",
                lineterm="",
            )
        )
    diff = "\n".join(chunks).strip()
    if len(diff) <= max_chars:
        return diff
    return diff[: max_chars - 20].rstrip() + "\n... <truncated>"


def _git_status(repo_root: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"supported": False, "error": str(exc)}
    return {
        "supported": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def create_workspace_copy(source_root: Path, runs_dir: Path, run_id: str) -> Path:
    workspace_root = runs_dir / run_id / "workspace"
    if workspace_root.exists():
        return workspace_root
    workspace_root.parent.mkdir(parents=True, exist_ok=True)

    ignored = {
        ".git",
        ".cache",
        ".tmp",
        "logs",
        "reports",
        "runs",
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
    }

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored or name.endswith(".pyc")}

    shutil.copytree(source_root, workspace_root, ignore=ignore)
    return workspace_root
