from __future__ import annotations

import json
from typing import Any

from .llm import LLMClient, message_text
from .models import AgentResult, InvestigationBundle
from .tools import RepoTools


class RepoAgent:
    def __init__(self, repo_index, llm_client: LLMClient | None = None):
        self.repo_index = repo_index
        self.llm_client = llm_client

    def answer(self, query: str, top_k: int = 6, use_model: bool = False) -> AgentResult:
        tools = RepoTools(self.repo_index)
        repo_brief = tools.repo_brief()
        bundle = self._investigate(query, tools, top_k=top_k)

        baseline_answer = self._compose_answer(query, bundle)
        trace = list(bundle.trace)
        answer = baseline_answer
        model_name = ""

        if use_model and self.llm_client and self.llm_client.available:
            agent_answer, agent_trace = self._run_llm_agent(query, tools, bundle, baseline_answer, top_k=top_k)
            trace.extend(agent_trace)
            if agent_answer:
                answer = agent_answer
                model_name = self.llm_client.model
        elif use_model:
            trace.append(
                {
                    "step": len(trace) + 1,
                    "type": "agent_unavailable",
                    "content": "Model mode was requested, but OPENAI_API_KEY, OPENAI_BASE_URL, or OPENAI_MODEL is not configured.",
                }
            )

        trace.append({"step": len(trace) + 1, "type": "answer", "content": answer})
        return AgentResult(
            mode=bundle.mode,
            query=query,
            answer=answer,
            hits=bundle.final_hits,
            trace=trace,
            model_name=model_name,
            repo_brief=repo_brief,
        )

    def _investigate(self, query: str, tools: RepoTools, *, top_k: int) -> InvestigationBundle:
        repo_brief = tools.repo_brief()
        plan = tools.plan(query)
        semantic_scores = tools.semantic_scores(query)
        file_hits = tools.scout_files(plan, limit=max(6, top_k + 2))
        seed_hits, file_boosts = tools.read_candidates(query, plan, file_hits, semantic_scores, top_k=top_k)
        relation_boosts, hop_trace = tools.follow_neighbors(seed_hits[: max(2, min(4, top_k))], plan)
        final_hits = tools.rerank(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )

        trace = [
            {"step": 1, "type": "repo_memory", "content": repo_brief},
            {
                "step": 2,
                "type": "plan",
                "content": (
                    f"mode={plan.mode}\n"
                    f"intent={plan.intent}\n"
                    f"target_roles={', '.join(plan.target_roles) or 'any'}\n"
                    f"target_languages={', '.join(plan.target_languages) or 'any'}\n"
                    f"hop_budget={plan.hop_budget}\n"
                    f"focus_terms={', '.join(plan.focus_terms[:14])}"
                ),
            },
            {
                "step": 3,
                "type": "file_scout",
                "content": "\n".join(
                    (
                        f"{hit.file_fact.relpath} | {hit.score:.2f} | "
                        f"roles={','.join(hit.file_fact.roles) or 'generic'} | "
                        f"{', '.join(hit.reasons[:4])}"
                    )
                    for hit in file_hits[:6]
                )
                or "no candidate files",
            },
            {
                "step": 4,
                "type": "code_read",
                "content": "\n".join(
                    f"{hit.chunk.source_label} | {hit.score:.2f} | {', '.join(hit.reasons[:5])}"
                    for hit in seed_hits[:6]
                )
                or "no primary evidence",
            },
            {
                "step": 5,
                "type": "graph_hop",
                "content": "\n".join(hop_trace[:10]) or "no graph hops taken",
            },
            {
                "step": 6,
                "type": "final_ranking",
                "content": "\n".join(
                    f"{hit.chunk.source_label} | {hit.score:.2f} | {', '.join(hit.reasons[:5])}"
                    for hit in final_hits
                )
                or "no final hits",
            },
        ]

        return InvestigationBundle(
            mode=plan.mode,
            focus_terms=plan.focus_terms,
            seed_hits=seed_hits[:5],
            final_hits=final_hits,
            graph_edges=tools.relevant_edges(final_hits),
            trace=trace,
        )

    def _run_llm_agent(
        self,
        query: str,
        tools: RepoTools,
        bundle: InvestigationBundle,
        baseline_answer: str,
        *,
        top_k: int,
    ) -> tuple[str, list[dict]]:
        if not self.llm_client:
            return "", []

        trace: list[dict] = []
        step = 1
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are Repo Agent, an autonomous repository investigation agent. "
                    "You can inspect the repository by calling tools. Use the tools when more evidence is needed. "
                    "Never claim that a command ran unless you called a command tool and observed the result. "
                    "Use only observed facts and supplied retrieval evidence. "
                    "Answer in the same language as the user."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Repository root: {self.repo_index.repo_root}\n\n"
                    f"Question:\n{query}\n\n"
                    f"Repository brief:\n{tools.repo_brief()}\n\n"
                    f"Seed retrieval evidence:\n{self._format_hits(bundle.final_hits[:top_k]) or 'none'}\n\n"
                    f"Baseline deterministic answer:\n{baseline_answer}\n\n"
                    "Investigate with tools if needed, then provide a concise final answer with file/line references."
                ),
            },
        ]
        trace.append({"step": step, "type": "agent_start", "content": f"model={self.llm_client.model}\ntool_calling=true"})
        step += 1

        for _turn in range(8):
            response = self.llm_client.chat(messages, tools=self._tool_schemas(), tool_choice="auto", temperature=0.15)
            if response is None:
                trace.append({"step": step, "type": "agent_error", "content": "Model request failed."})
                return "", trace

            assistant_message = response.message
            tool_calls = assistant_message.get("tool_calls") or []
            content = message_text(assistant_message).strip()
            messages.append(_assistant_message_for_history(assistant_message))

            if content:
                trace.append({"step": step, "type": "agent_thought", "content": content})
                step += 1

            if not tool_calls:
                return content, trace

            for call in tool_calls[:4]:
                function = call.get("function") or {}
                name = str(function.get("name", "")).strip()
                args = _json_object(function.get("arguments", "{}"))
                trace.append(
                    {
                        "step": step,
                        "type": "tool_call",
                        "content": f"{name}({json.dumps(args, ensure_ascii=False)})",
                    }
                )
                step += 1

                observation = self._execute_agent_tool(name, args, tools, top_k=top_k)
                observation_text = _compact_json(observation)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": name,
                        "content": observation_text,
                    }
                )
                trace.append({"step": step, "type": "tool_observation", "content": observation_text})
                step += 1

        messages.append(
            {
                "role": "user",
                "content": "Stop calling tools. Provide the best final answer from the evidence already observed.",
            }
        )
        final_response = self.llm_client.chat(messages, temperature=0.15)
        if final_response is None:
            return "", trace
        final_answer = message_text(final_response.message).strip()
        trace.append({"step": step, "type": "agent_final_forced", "content": final_answer})
        return final_answer, trace

    def _execute_agent_tool(self, name: str, args: dict[str, Any], tools: RepoTools, *, top_k: int) -> dict[str, Any]:
        try:
            if name == "repo_brief":
                return {"brief": tools.repo_brief(), "memory": tools.repo_memory()}

            if name == "list_directory":
                relpath = str(args.get("path", ".") or ".")
                limit = _int(args.get("limit"), default=40, minimum=1, maximum=120)
                return {"path": relpath, "entries": tools.list_directory(relpath, limit=limit)}

            if name == "search_text":
                terms = _string_list(args.get("terms"))
                relpaths = _string_list(args.get("relpaths")) or None
                limit = _int(args.get("limit"), default=12, minimum=1, maximum=60)
                return {"terms": terms, "matches": tools.search_text(terms, relpaths=relpaths, limit=limit)}

            if name == "read_file":
                relpath = str(args.get("path", "")).strip()
                start_line = _int(args.get("start_line"), default=1, minimum=1, maximum=200000)
                end_line = _int(args.get("end_line"), default=start_line + 120, minimum=1, maximum=200000)
                return tools.read_file(relpath, start_line=start_line, end_line=end_line)

            if name == "find_relevant_code":
                question = str(args.get("question", "") or "").strip()
                local_top_k = _int(args.get("top_k"), default=top_k, minimum=1, maximum=max(1, top_k))
                bundle = self._investigate(question or "repository overview", tools, top_k=local_top_k)
                return {
                    "mode": bundle.mode,
                    "focus_terms": bundle.focus_terms[:12],
                    "hits": [self._hit_payload(hit) for hit in bundle.final_hits],
                    "graph_edges": [
                        {
                            "source": self._source_label(edge.source),
                            "target": self._source_label(edge.target),
                            "label": edge.label,
                            "weight": edge.weight,
                        }
                        for edge in bundle.graph_edges[:8]
                    ],
                }

            if name == "startup_hints":
                return tools.startup_hints()

            if name == "verify_project":
                question = str(args.get("question", "") or "").strip()
                command = str(args.get("command", "") or "").strip()
                if not command:
                    command = tools.infer_verification_command(question or "verify project")
                if not command:
                    return {"supported": False, "message": "No safe verification command could be inferred."}
                if not _is_verification_command(command):
                    return {
                        "supported": False,
                        "message": f"Command is not a verification command allowed for autonomous agent use: {command}",
                    }
                timeout = _int(args.get("timeout_seconds"), default=45, minimum=1, maximum=120)
                return {"supported": True, **tools.run_command(command, timeout_seconds=timeout)}

            return {"error": f"unknown tool: {name}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "tool": name}

    def _compose_answer(self, query: str, bundle: InvestigationBundle) -> str:
        if not bundle.final_hits:
            if _contains_cjk(query):
                return (
                    "## 结论\n"
                    "我没有找到足够强的代码证据。可以换成更具体的入口、报错、页面或函数名再问一次。\n\n"
                    "## 已做的事\n"
                    "- 建立仓库索引\n"
                    "- 生成检索计划\n"
                    "- 尝试文件召回、代码块读取和图关系扩展"
                )
            return (
                "## Conclusion\n"
                "I did not find strong enough code evidence for this question.\n\n"
                "## What I Tried\n"
                "- Built the repository index\n"
                "- Planned the query\n"
                "- Tried file recall, code reading, and graph expansion"
            )

        if _contains_cjk(query):
            return self._compose_answer_zh(bundle)
        return self._compose_answer_en(bundle)

    def _compose_answer_zh(self, bundle: InvestigationBundle) -> str:
        top = bundle.final_hits[0]
        lines = [
            "## 结论",
            (
                f"这个问题最相关的位置是 `{top.chunk.source_label}`，"
                f"大约在第 `{top.chunk.start_line}-{top.chunk.end_line}` 行。"
            ),
            "",
            "## 证据",
        ]
        for hit in bundle.final_hits[:4]:
            lines.append(
                f"- `{hit.chunk.source_label}` 分数 `{hit.score:.2f}`；"
                f"命中 `{', '.join(hit.matched_terms[:6]) or '语义相关'}`；"
                f"原因：{', '.join(hit.reasons[:5]) or '代码内容相关'}。"
            )
        if bundle.graph_edges:
            lines.extend(["", "## 关系扩展"])
            for edge in bundle.graph_edges[:6]:
                lines.append(
                    f"- `{self._source_label(edge.source)}` -> `{self._source_label(edge.target)}` "
                    f"via `{edge.label}`，权重 `{edge.weight:.1f}`。"
                )
        lines.extend(["", "## 关键片段", "```", _trim_text(top.chunk.text, 22), "```"])
        return "\n".join(lines)

    def _compose_answer_en(self, bundle: InvestigationBundle) -> str:
        top = bundle.final_hits[0]
        lines = [
            "## Conclusion",
            f"Start with `{top.chunk.source_label}` around lines `{top.chunk.start_line}-{top.chunk.end_line}`.",
            "",
            "## Evidence",
        ]
        for hit in bundle.final_hits[:4]:
            lines.append(
                f"- `{hit.chunk.source_label}` scored `{hit.score:.2f}`; "
                f"matched `{', '.join(hit.matched_terms[:6]) or 'semantic relevance'}`; "
                f"reasons: {', '.join(hit.reasons[:5]) or 'related code content'}."
            )
        if bundle.graph_edges:
            lines.extend(["", "## Graph Expansion"])
            for edge in bundle.graph_edges[:6]:
                lines.append(
                    f"- `{self._source_label(edge.source)}` -> `{self._source_label(edge.target)}` "
                    f"via `{edge.label}` with weight `{edge.weight:.1f}`."
                )
        lines.extend(["", "## Key Snippet", "```", _trim_text(top.chunk.text, 22), "```"])
        return "\n".join(lines)

    def _format_hits(self, hits) -> str:
        return "\n\n".join(
            (
                f"{index}. {hit.chunk.source_label} "
                f"lines {hit.chunk.start_line}-{hit.chunk.end_line} score={hit.score:.2f}\n"
                f"reasons: {', '.join(hit.reasons[:5])}\n"
                f"snippet:\n{_trim_text(hit.chunk.text, 16)}"
            )
            for index, hit in enumerate(hits, start=1)
        )

    def _hit_payload(self, hit) -> dict[str, Any]:
        return {
            "source_label": hit.chunk.source_label,
            "relpath": hit.chunk.relpath,
            "symbol_name": hit.chunk.symbol_name,
            "symbol_kind": hit.chunk.symbol_kind,
            "start_line": hit.chunk.start_line,
            "end_line": hit.chunk.end_line,
            "score": round(hit.score, 3),
            "matched_terms": hit.matched_terms[:8],
            "reasons": hit.reasons[:8],
            "snippet": _trim_text(hit.chunk.text, 24),
        }

    def _source_label(self, chunk_id: str) -> str:
        chunk = self.repo_index.chunk_by_id.get(chunk_id)
        return chunk.source_label if chunk else chunk_id

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "repo_brief",
                    "description": "Return a compact memory and overview of the repository.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_relevant_code",
                    "description": "Run graph-aware repository retrieval for a question and return ranked code evidence.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "top_k": {"type": "integer", "minimum": 1, "maximum": 12},
                        },
                        "required": ["question"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List files and directories inside the repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Repository-relative directory path."},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 120},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_text",
                    "description": "Search repository text for exact terms.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "terms": {"type": "array", "items": {"type": "string"}},
                            "relpaths": {"type": "array", "items": {"type": "string"}},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 60},
                        },
                        "required": ["terms"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a repository file range.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Repository-relative file path."},
                            "start_line": {"type": "integer", "minimum": 1},
                            "end_line": {"type": "integer", "minimum": 1},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "startup_hints",
                    "description": "Find likely startup and verification commands for the repository.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "verify_project",
                    "description": "Run a safe allow-listed verification command or infer one from the question.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "command": {"type": "string"},
                            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
                        },
                        "additionalProperties": False,
                    },
                },
            },
        ]


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


def _int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(maximum, numeric))


def _compact_json(payload: dict[str, Any], max_chars: int = 12000) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n... <truncated>"


def _trim_text(text: str, max_lines: int) -> str:
    lines = str(text or "").splitlines()
    if len(lines) <= max_lines:
        return str(text or "").strip()
    return "\n".join(lines[:max_lines]).strip() + "\n..."


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def _is_verification_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().lower().split())
    return (
        normalized == "npm test"
        or normalized == "npm run build"
        or normalized == "python -m pytest"
        or normalized == "python -m repo_agent eval"
        or normalized.startswith("python -m compileall ")
    )
