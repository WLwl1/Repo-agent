from __future__ import annotations

import hashlib
import difflib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, UTC
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
    verifier_result: dict[str, Any] = field(default_factory=dict)
    reviewer_result: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
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
            "verifier_result": self.verifier_result,
            "reviewer_result": self.reviewer_result,
            "timeline": self.timeline,
            "applied": self.applied,
            "applied_files": self.applied_files,
            "changed_files": self.changed_files,
            "verification": self.verification,
            "trace": self.trace,
            "messages": self.messages,
            "diff": self.diff,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineeringRun:
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
            verifier_result=dict(data.get("verifier_result") or {}),
            reviewer_result=dict(data.get("reviewer_result") or {}),
            timeline=list(data.get("timeline") or []),
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
            self._timeline_event(
                run,
                agent="Coordinator Agent",
                phase="start",
                status="running",
                title="Engineering run started",
                summary=f"Execution mode: {run.execution_mode}; max steps: {max_steps}.",
                details={"repo_root": run.repo_root, "source_repo_root": run.source_repo_root},
            )

        if not self.llm_client.available:
            run.status = "model_unavailable"
            run.answer = "Model is not configured. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL in .env."
            self._record(run, "stop", run.answer)
            self._timeline_event(
                run,
                agent="Coordinator Agent",
                phase="blocked",
                status="blocked",
                title="Model unavailable",
                summary=run.answer,
            )
            self._finalize_run(run)
            self._persist(run)
            return run

        if not resume_data:
            run.plan = self._plan_run(run)
            if run.plan:
                self._record(run, "planner", run.plan)
                self._timeline_event(
                    run,
                    agent="Planner Agent",
                    phase="plan",
                    status="completed",
                    title="Plan created",
                    summary=_first_line(run.plan, fallback="Planner created an implementation strategy."),
                    details={"plan": run.plan},
                )
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
                self._timeline_event(
                    run,
                    agent="Patch Agent",
                    phase="reason",
                    status="running",
                    title="Patch agent message",
                    summary=_first_line(content, fallback="Patch agent produced an intermediate message."),
                    details={"message": _trim_text(content, 18)},
                )

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
                self._timeline_event(
                    run,
                    agent=_agent_for_tool(name),
                    phase="tool_call",
                    status="running",
                    title=f"Calling {name}",
                    summary=_tool_summary(name, args),
                    details={"tool": name, "arguments": _compact_tool_args(args)},
                )

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
                self._timeline_event(
                    run,
                    agent=_agent_for_tool(name),
                    phase="tool_result",
                    status=_tool_status(name, observation),
                    title=f"{name} result",
                    summary=_observation_summary(name, observation),
                    details={"tool": name, "observation": observation},
                )
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
        self._finalize_run(run)
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
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        self._persist(run)

    def _persist(self, run: EngineeringRun) -> None:
        path = Path(run.run_path) / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def _finalize_run(self, run: EngineeringRun) -> None:
        if not run.diff:
            run.diff = _run_diff(self.repo_index.repo_root, self._snapshots)
        self._auto_verify_run(run)
        run.verifier_result = self._verify_run(run)
        self._timeline_event(
            run,
            agent="Verifier Agent",
            phase="verify",
            status=str(run.verifier_result.get("status", "unknown")),
            title="Verification assessment",
            summary=str(run.verifier_result.get("summary", "")),
            details=run.verifier_result,
        )
        run.reviewer_result = self._review_run(run)
        run.review = str(run.reviewer_result.get("summary", ""))
        if run.review:
            self._record(run, "review", run.review)
        self._timeline_event(
            run,
            agent="Reviewer Agent",
            phase="review",
            status=str(run.reviewer_result.get("status", "unknown")),
            title="Risk review",
            summary=str(run.reviewer_result.get("summary", "")),
            details=run.reviewer_result,
        )
        self._timeline_event(
            run,
            agent="Coordinator Agent",
            phase="finish",
            status=run.status,
            title="Run finalized",
            summary=run.answer or self._fallback_answer(run),
            details={
                "changed_files": run.changed_files,
                "verification_status": run.verifier_result.get("status"),
                "risk_score": run.reviewer_result.get("risk_score"),
            },
        )

    def _auto_verify_run(self, run: EngineeringRun) -> None:
        if run.verification or not run.changed_files:
            return
        command = self.tools.infer_verification_command(run.task)
        if not command:
            self._timeline_event(
                run,
                agent="Verifier Agent",
                phase="verify_select",
                status="skipped",
                title="No verification command inferred",
                summary="Verifier could not infer a safe command for this repository and task.",
                details={"changed_files": run.changed_files},
            )
            return
        if not _is_safe_engineering_command(command):
            self._timeline_event(
                run,
                agent="Verifier Agent",
                phase="verify_select",
                status="blocked",
                title="Inferred command blocked",
                summary=f"Inferred verification command is not allowed: {command}",
                details={"command": command},
            )
            return
        self._timeline_event(
            run,
            agent="Verifier Agent",
            phase="verify_select",
            status="running",
            title="Auto-selected verification",
            summary=f"Verifier selected `{command}` because files changed without observed verification.",
            details={"command": command, "changed_files": run.changed_files},
        )
        try:
            result = self.tools.run_command(command, timeout_seconds=90)
        except Exception as exc:  # noqa: BLE001
            result = {
                "command": command,
                "cwd": str(self.repo_index.repo_root),
                "exit_code": None,
                "stdout": "",
                "stderr": str(exc),
                "error": str(exc),
            }
        run.verification.append(result)
        self._timeline_event(
            run,
            agent="Verifier Agent",
            phase="verify_run",
            status="passed" if result.get("exit_code") == 0 else "failed",
            title="Auto verification completed",
            summary=_observation_summary("run_command", result),
            details={"command": command, "result": result},
        )

    def _verify_run(self, run: EngineeringRun) -> dict[str, Any]:
        commands = list(run.verification)
        passed = [item for item in commands if item.get("exit_code") == 0]
        failed = [item for item in commands if item.get("exit_code") not in (None, 0)]
        failure_analysis = [_analyze_verification_failure(item) for item in failed]
        warnings: list[str] = []
        strengths: list[str] = []

        if commands:
            strengths.append(f"{len(commands)} verification command(s) observed")
        if passed:
            strengths.append(f"{len(passed)} command(s) exited 0")
        if failed:
            warnings.append(f"{len(failed)} command(s) failed")
        if run.changed_files and not commands:
            warnings.append("files changed without an observed verification command")
        if run.status in {"blocked", "failed", "model_unavailable"}:
            warnings.append(f"run ended with status {run.status}")

        if failed:
            status = "failed"
            summary = f"Verifier found {len(failed)} failing command(s); repair is needed before apply."
        elif commands:
            status = "passed"
            summary = f"Verifier observed {len(passed)}/{len(commands)} command(s) passing."
        elif run.changed_files:
            status = "missing"
            summary = "Verifier found code changes but no verification command output."
        else:
            status = "not_run"
            summary = "Verifier had no code changes or verification commands to assess."

        return {
            "agent": "Verifier Agent",
            "status": status,
            "summary": summary,
            "command_count": len(commands),
            "passed_count": len(passed),
            "failed_count": len(failed),
            "last_command": commands[-1].get("command", "") if commands else "",
            "last_exit_code": commands[-1].get("exit_code") if commands else None,
            "failure_analysis": failure_analysis,
            "primary_failure": failure_analysis[0] if failure_analysis else {},
            "warnings": warnings,
            "strengths": strengths,
            "commands": [
                {
                    "command": item.get("command", ""),
                    "exit_code": item.get("exit_code"),
                    "stdout_tail": _tail_text(str(item.get("stdout", "")), 8),
                    "stderr_tail": _tail_text(str(item.get("stderr", "")), 8),
                }
                for item in commands[-6:]
            ],
        }

    def _review_run(self, run: EngineeringRun) -> dict[str, Any]:
        reviewer = _deterministic_review(run)
        if not self.llm_client.available or not run.diff:
            return reviewer
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
        model_summary = message_text(response.message).strip() if response else ""
        if model_summary:
            reviewer["model_summary"] = model_summary
            reviewer["summary"] = f"{reviewer['summary']}\n\nModel review:\n{model_summary}"
        return reviewer

    def _timeline_event(
        self,
        run: EngineeringRun,
        *,
        agent: str,
        phase: str,
        status: str,
        title: str,
        summary: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        run.timeline.append(
            {
                "step": len(run.timeline) + 1,
                "agent": agent,
                "phase": phase,
                "status": status,
                "title": title,
                "summary": _trim_text(summary, 8),
                "details": details or {},
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        self._persist(run)

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


def _first_line(text: str, *, fallback: str = "") -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:240]
    return fallback


def _tail_text(text: str, max_lines: int) -> str:
    lines = str(text or "").splitlines()
    if len(lines) <= max_lines:
        return str(text or "").strip()
    return "\n".join(lines[-max_lines:]).strip()


def _agent_for_tool(name: str) -> str:
    if name in {"find_relevant_code", "repo_brief", "list_directory", "search_text", "read_file"}:
        return "Investigator Agent"
    if name in {"run_command"}:
        return "Verifier Agent"
    if name in {"git_status", "diff_summary"}:
        return "Reviewer Agent"
    if name in {"finish"}:
        return "Coordinator Agent"
    return "Patch Agent"


def _tool_summary(name: str, args: dict[str, Any]) -> str:
    if name == "find_relevant_code":
        return str(args.get("question", "") or "Finding relevant code.")[:240]
    if name == "read_file":
        return f"Reading {args.get('path', '')}."
    if name == "search_text":
        return "Searching for " + ", ".join(_string_list(args.get("terms"))[:4])
    if name in {"replace_text", "write_file", "revert_file"}:
        return f"Editing {args.get('path', '')}."
    if name == "run_command":
        return f"Running `{args.get('command', '')}`."
    if name == "finish":
        return str(args.get("summary", "") or "Finishing run.")[:240]
    return f"Calling {name}."


def _compact_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > 800:
            compact[key] = value[:780].rstrip() + "... <truncated>"
        else:
            compact[key] = value
    return compact


def _tool_status(name: str, observation: dict[str, Any]) -> str:
    if observation.get("error"):
        return "failed"
    if name == "run_command":
        return "passed" if observation.get("exit_code") == 0 else "failed"
    if name in {"replace_text", "write_file", "revert_file"}:
        return "completed" if observation.get("changed") else "skipped"
    return "completed"


def _observation_summary(name: str, observation: dict[str, Any]) -> str:
    if observation.get("error"):
        return str(observation.get("error"))
    if name == "run_command":
        return f"`{observation.get('command', '')}` exited {observation.get('exit_code')}."
    if name in {"replace_text", "write_file", "revert_file"}:
        relpath = observation.get("relpath", "")
        changed = "changed" if observation.get("changed") else "unchanged"
        return f"{relpath} {changed}."
    if name == "find_relevant_code":
        return f"Found {len(observation.get('hits', []))} ranked hit(s)."
    if name == "read_file":
        return f"Read {observation.get('relpath', '')} lines {observation.get('start_line')}-{observation.get('end_line')}."
    if name == "finish":
        return str(observation.get("summary", "") or "Run finish requested.")[:240]
    return "Tool completed."


def _deterministic_review(run: EngineeringRun) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    risk_score = 0.12
    changed_files = [str(item).replace("\\", "/") for item in run.changed_files]
    verifier = run.verifier_result or {}
    file_risks = [_file_risk(relpath, run.diff, verifier) for relpath in changed_files]

    if changed_files:
        risk_score += min(0.24, 0.04 * len(changed_files))
    if file_risks:
        risk_score += min(0.16, max(item["risk_score"] for item in file_risks) * 0.16)
    if len(changed_files) >= 4:
        findings.append(
            {
                "severity": "medium",
                "title": "Broad change set",
                "detail": f"{len(changed_files)} files changed; review the diff for scope creep.",
            }
        )

    verification_status = verifier.get("status")
    if verification_status == "failed":
        risk_score += 0.34
        findings.append(
            {
                "severity": "high",
                "title": "Verification failed",
                "detail": "At least one observed verification command exited non-zero.",
            }
        )
    elif verification_status == "missing":
        risk_score += 0.26
        findings.append(
            {
                "severity": "medium",
                "title": "Missing verification",
                "detail": "The run changed files without an observed test, build, or compile check.",
            }
        )
    elif verification_status == "passed":
        risk_score -= 0.05

    touched_tests = any(_is_test_path(path) for path in changed_files)
    touched_public_surface = any(_looks_public_surface(path) for path in changed_files)
    if touched_public_surface and not touched_tests:
        risk_score += 0.14
        findings.append(
            {
                "severity": "medium",
                "title": "Public surface changed without tests",
                "detail": "A likely route/API/UI surface changed, but no test file was changed.",
            }
        )
    if run.status in {"blocked", "failed", "model_unavailable"}:
        risk_score += 0.18
        findings.append(
            {
                "severity": "medium",
                "title": "Run did not complete cleanly",
                "detail": f"Run status is {run.status}.",
            }
        )
    if not changed_files and run.status == "completed":
        findings.append(
            {
                "severity": "low",
                "title": "No files changed",
                "detail": "The run completed without a recorded code change.",
            }
        )

    risk_score = max(0.0, min(1.0, risk_score))
    status = "high_risk" if risk_score >= 0.68 else "needs_review" if risk_score >= 0.38 else "approved"
    summary = (
        f"Reviewer risk score {risk_score:.2f} ({status}); "
        f"{len(findings)} finding(s), {len(changed_files)} changed file(s), "
        f"verification={verification_status or 'unknown'}."
    )
    suggested_actions = _review_suggested_actions(findings, file_risks, verifier)
    return {
        "agent": "Reviewer Agent",
        "status": status,
        "risk_score": round(risk_score, 2),
        "summary": summary,
        "findings": findings,
        "file_risks": file_risks,
        "suggested_actions": suggested_actions,
        "changed_files": changed_files,
        "touched_tests": touched_tests,
        "touched_public_surface": touched_public_surface,
        "verification_status": verification_status,
    }


def _analyze_verification_failure(item: dict[str, Any]) -> dict[str, Any]:
    command = str(item.get("command", ""))
    output = "\n".join(str(item.get(key, "")) for key in ("stdout", "stderr") if item.get(key))
    lowered = output.lower()
    failure_type = "unknown"
    if "assert" in lowered or "failed" in lowered and "pytest" in lowered:
        failure_type = "test_failure"
    if "syntaxerror" in lowered or "syntax error" in lowered:
        failure_type = "syntax_error"
    elif "modulenotfounderror" in lowered or "cannot find module" in lowered:
        failure_type = "missing_dependency"
    elif "timeout" in lowered or "timed out" in lowered:
        failure_type = "timeout"
    elif "permission" in lowered or "access is denied" in lowered:
        failure_type = "environment_permission"

    referenced_files = _extract_referenced_files(output)
    failed_tests = _extract_failed_tests(output)
    return {
        "command": command,
        "exit_code": item.get("exit_code"),
        "type": failure_type,
        "referenced_files": referenced_files[:8],
        "failed_tests": failed_tests[:8],
        "stdout_tail": _tail_text(str(item.get("stdout", "")), 10),
        "stderr_tail": _tail_text(str(item.get("stderr", "")), 10),
    }


def _extract_referenced_files(text: str) -> list[str]:
    matches: list[str] = []
    patterns = [
        r"([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|css|html|json|toml|md))[:(]\d+",
        r"File \"([^\"]+)\"",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            clean = str(match).replace("\\", "/")
            if clean and clean not in matches:
                matches.append(clean)
    return matches


def _extract_failed_tests(text: str) -> list[str]:
    matches: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("FAILED ") or "::" in stripped and (" failed" in stripped.lower() or "error" in stripped.lower()):
            value = stripped.replace("FAILED ", "", 1).split(" - ", 1)[0].strip()
            if value and value not in matches:
                matches.append(value)
    return matches


def _file_risk(relpath: str, diff: str, verifier: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    suggested_actions: list[str] = []
    risk = 0.12
    if _looks_public_surface(relpath):
        risk += 0.22
        reasons.append("public API/UI surface")
        suggested_actions.append("Add or update a regression test covering the public behavior.")
    if _is_test_path(relpath):
        risk -= 0.08
        reasons.append("test file changed")
    if relpath.lower().endswith((".json", ".toml", ".yaml", ".yml")):
        risk += 0.08
        reasons.append("configuration or metadata file")
        suggested_actions.append("Run a build or startup check after config changes.")
    added, removed = _diff_counts_for_file(diff, relpath)
    total_delta = added + removed
    if total_delta >= 80:
        risk += 0.18
        reasons.append(f"large diff ({total_delta} changed lines)")
        suggested_actions.append("Split or manually inspect the large diff before applying.")
    elif total_delta >= 25:
        risk += 0.08
        reasons.append(f"moderate diff ({total_delta} changed lines)")
    if removed > added * 2 and removed >= 8:
        risk += 0.08
        reasons.append("deletion-heavy change")
    if verifier.get("status") == "failed":
        risk += 0.18
        suggested_actions.append("Repair failing verification before applying this run.")
    elif verifier.get("status") == "missing":
        risk += 0.12
        suggested_actions.append("Run the inferred verification command or a targeted test.")
    if not reasons:
        reasons.append("low-risk source change")
    return {
        "relpath": relpath,
        "risk_score": round(max(0.0, min(1.0, risk)), 2),
        "added_lines": added,
        "removed_lines": removed,
        "reasons": reasons,
        "suggested_actions": list(dict.fromkeys(suggested_actions))[:4],
    }


def _diff_counts_for_file(diff: str, relpath: str) -> tuple[int, int]:
    if not diff:
        return 0, 0
    added = 0
    removed = 0
    current = ""
    expected = relpath.replace("\\", "/")
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line.removeprefix("+++ b/").strip()
            continue
        if line.startswith("--- a/"):
            if not current:
                current = line.removeprefix("--- a/").strip()
            continue
        if current != expected:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _review_suggested_actions(
    findings: list[dict[str, Any]],
    file_risks: list[dict[str, Any]],
    verifier: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if verifier.get("status") == "failed":
        primary = verifier.get("primary_failure") or {}
        if primary.get("type") and primary.get("type") != "unknown":
            actions.append(f"Fix the {primary['type'].replace('_', ' ')} reported by verification.")
        actions.append("Rerun the failing verification command after repair.")
    if verifier.get("status") == "missing":
        actions.append("Run a targeted test, build, or compile check before apply.")
    for finding in findings:
        if finding.get("title") == "Public surface changed without tests":
            actions.append("Add a regression test for the changed public surface.")
        if finding.get("title") == "Broad change set":
            actions.append("Review the diff file by file and split unrelated changes.")
    for item in sorted(file_risks, key=lambda entry: entry.get("risk_score", 0), reverse=True)[:3]:
        actions.extend(item.get("suggested_actions", []))
    return list(dict.fromkeys(actions))[:6]


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or lowered.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts"))
        or "test_" in Path(lowered).name
    )


def _looks_public_surface(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith(("web/", "api/", "app/", "src/routes/", "routes/"))
        or Path(lowered).name in {"server.js", "app.py", "main.py", "index.html"}
    )


def _run_id(task: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
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
