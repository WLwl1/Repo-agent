from __future__ import annotations

import json
from typing import Any

from .llm import LLMClient, message_text
from .models import AgentResult, EvidenceDiagnostics, InvestigationBundle, RetrievalHit
from .security import is_safe_verification_command
from .tools import RepoTools


class RepoAgent:
    def __init__(self, repo_index, llm_client: LLMClient | None = None):
        self.repo_index = repo_index
        self.llm_client = llm_client

    def answer(self, query: str, top_k: int = 6, use_model: bool = False) -> AgentResult:
        tools = RepoTools(self.repo_index)
        repo_brief = tools.repo_brief()
        bundle = self._investigate(query, tools, top_k=top_k)
        rerank_trace: list[dict] = []
        if use_model and self.llm_client and self.llm_client.available:
            bundle, rerank_trace = self._rerank_with_model(query, bundle, top_k=top_k)
        bundle.final_hits = bundle.final_hits[:top_k]
        diagnostics = build_evidence_diagnostics(bundle)
        proof = build_evidence_proof(query, bundle)
        bundle.proof = proof

        baseline_answer = self._compose_answer(query, bundle)
        trace = list(bundle.trace) + rerank_trace
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
            diagnostics=diagnostics,
            graph_search=bundle.graph_search,
            proof=proof,
        )

    def _rerank_with_model(
        self,
        query: str,
        bundle: InvestigationBundle,
        *,
        top_k: int,
    ) -> tuple[InvestigationBundle, list[dict]]:
        """Use a model as a cross-encoder over retrieved evidence only.

        The model can reorder existing candidates and explain relevance, but
        cannot introduce a path or symbol that was not retrieved. This keeps
        the neural layer powerful without allowing unsupported code claims.
        """
        if not self.llm_client or not bundle.final_hits:
            return bundle, []
        candidates = bundle.final_hits[: max(24, top_k * 4)]
        evidence = "\n\n".join(
            f"CANDIDATE {index}\n"
            f"source={hit.chunk.source_label}\n"
            f"lines={hit.chunk.start_line}-{hit.chunk.end_line}\n"
            f"kind={hit.chunk.symbol_kind}\n"
            f"code:\n{_trim_text(hit.chunk.text, 28)}"
            for index, hit in enumerate(candidates)
        )
        response = self.llm_client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a code retrieval cross-encoder. Rank only the supplied candidates for the user's "
                        "question. Do not invent or rename files, symbols, or lines. Return JSON only: "
                        "{\"ranking\":[{\"index\":0,\"relevance\":0.0,\"reason\":\"...\"}]}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question:\n{query}\n\nCandidates:\n{evidence}",
                },
            ],
            temperature=0.0,
        )
        if response is None:
            return bundle, [{"step": len(bundle.trace) + 1, "type": "model_rerank_unavailable", "content": "no response"}]
        raw = message_text(response.message).strip()
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        payload = _json_object(cleaned)
        ranking = payload.get("ranking")
        if not isinstance(ranking, list):
            return bundle, [{"step": len(bundle.trace) + 1, "type": "model_rerank_invalid", "content": raw[:1000]}]

        by_index = {index: hit for index, hit in enumerate(candidates)}
        scored: list[tuple[float, int, RetrievalHit, str]] = []
        for position, item in enumerate(ranking):
            if not isinstance(item, dict):
                continue
            try:
                raw_index = item.get("index")
                if raw_index is None:
                    continue
                index = int(raw_index)
                relevance = max(0.0, min(1.0, float(item.get("relevance", 0.0))))
            except (TypeError, ValueError):
                continue
            hit = by_index.get(index)
            if hit is None:
                continue
            reason = str(item.get("reason", "model relevance"))[:240]
            scored.append((relevance, -position, hit, reason))
        if not scored:
            return bundle, [{"step": len(bundle.trace) + 1, "type": "model_rerank_empty", "content": raw[:1000]}]

        ranked_ids = {id(item[2]) for item in scored}
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        reordered: list[RetrievalHit] = []
        for relevance, _position, hit, reason in scored:
            reordered.append(
                RetrievalHit(
                    chunk=hit.chunk,
                    score=hit.score + relevance * 5.0,
                    matched_terms=hit.matched_terms,
                    reasons=hit.reasons + [f"model relevance={relevance:.2f}: {reason}"],
                )
            )
        reordered.extend(hit for hit in candidates if id(hit) not in ranked_ids)
        bundle.final_hits = reordered
        bundle.graph_edges = self.repo_index.relevant_edges(bundle.final_hits[:top_k])
        return bundle, [
            {
                "step": len(bundle.trace) + 1,
                "type": "model_rerank",
                "content": f"reranked {len(scored)} retrieved candidates with {self.llm_client.model}",
            }
        ]

    def _investigate(self, query: str, tools: RepoTools, *, top_k: int) -> InvestigationBundle:
        repo_brief = tools.repo_brief()
        plan = tools.plan(query)
        query_vector: list[float] | None = None
        if self.llm_client and self.llm_client.available and self.repo_index.embedding_index:
            vectors = self.llm_client.embed([query])
            query_vector = vectors[0] if vectors else None
        semantic_scores = tools.semantic_scores(query, query_vector=query_vector)
        file_hits = tools.scout_files(plan, limit=max(32, top_k * 8))
        seed_hits, file_boosts = tools.read_candidates(query, plan, file_hits, semantic_scores, top_k=top_k)
        relation_boosts, graph_search = tools.mcts_graph_boosts(
            query,
            plan,
            seed_hits[: max(8, min(16, top_k * 2))],
            semantic_scores,
            iterations=72,
            max_depth=max(2, plan.hop_budget + 1),
        )
        final_hits = tools.rerank(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=max(24, top_k * 4),
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
                # Historical trace type kept for evidence-bundle compatibility;
                # graph_search.strategy identifies the active PPR backend.
                "type": "graph_mcts",
                "content": "\n".join(graph_search.get("trace", [])[:10]) or "no graph search taken",
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

        bundle = InvestigationBundle(
            mode=plan.mode,
            focus_terms=plan.focus_terms,
            seed_hits=seed_hits[:5],
            final_hits=final_hits,
            graph_edges=tools.relevant_edges(final_hits),
            trace=trace,
            graph_search=graph_search,
        )
        bundle.proof = build_evidence_proof(query, bundle)
        return bundle

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
                    "Treat ranked retrieval as candidate generation, never as proof. "
                    "Start with exact text or symbol search when the question contains a name, route, or concept; "
                    "then read the relevant files and follow callers/callees before answering. "
                    "Use the tools when more evidence is needed. "
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
                    "Do not accept the baseline ranking without checking it. Investigate with search_symbols, "
                    "search_text, read_file, and find_symbol_relations as needed, then provide a concise final "
                    "answer with file/line references and say when evidence is insufficient."
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

            if name == "search_symbols":
                terms = _string_list(args.get("terms"))
                limit = _int(args.get("limit"), default=30, minimum=1, maximum=80)
                return {"terms": terms, "symbols": tools.search_symbols(terms, limit=limit)}

            if name == "find_symbol_relations":
                symbol = str(args.get("symbol", "") or "").strip()
                direction = str(args.get("direction", "both") or "both").strip().lower()
                if direction not in {"both", "callers", "callees"}:
                    direction = "both"
                limit = _int(args.get("limit"), default=30, minimum=1, maximum=80)
                return {
                    "symbol": symbol,
                    "direction": direction,
                    "relations": tools.find_symbol_relations(symbol, direction=direction, limit=limit),
                }

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
        if bundle.graph_search.get("top_visited"):
            lines.extend(["", "## 图搜索审计"])
            for item in bundle.graph_search["top_visited"][:3]:
                lines.append(
                    f"- `{item.get('chunk', '')}` visits `{item.get('visits', 0)}`；"
                    f"reward `{float(item.get('average_reward', 0.0)):.3f}`；"
                    f"boost `+{float(item.get('boost', 0.0)):.2f}`。"
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
        if bundle.graph_search.get("top_visited"):
            lines.extend(["", "## Graph Search Audit"])
            for item in bundle.graph_search["top_visited"][:3]:
                lines.append(
                    f"- `{item.get('chunk', '')}` visits `{item.get('visits', 0)}`; "
                    f"reward `{float(item.get('average_reward', 0.0)):.3f}`; "
                    f"boost `+{float(item.get('boost', 0.0)):.2f}`."
                )
        if bundle.proof:
            lines.extend(["", "## Proof-Carrying Retrieval"])
            lines.append(f"- status: `{bundle.proof.get('status', 'unknown')}`")
            lines.append(f"- claim: {bundle.proof.get('claim', '')}")
            for check in bundle.proof.get("checks", [])[:3]:
                state = "pass" if check.get("passed") else "fail"
                lines.append(f"- {check.get('name')}: `{state}` ({check.get('detail', '')})")
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
                    "name": "search_symbols",
                    "description": "Search parsed functions, classes, routes, and references by symbol name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "terms": {"type": "array", "items": {"type": "string"}},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 80},
                        },
                        "required": ["terms"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_symbol_relations",
                    "description": "Find parsed callers, callees, imports, and route relations for an exact symbol.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "direction": {"type": "string", "enum": ["both", "callers", "callees"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 80},
                        },
                        "required": ["symbol"],
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
    return is_safe_verification_command(command)


def build_evidence_diagnostics(bundle: InvestigationBundle) -> EvidenceDiagnostics:
    hits = bundle.final_hits
    top_score = hits[0].score if hits else 0.0
    second_score = hits[1].score if len(hits) > 1 else 0.0
    score_gap = max(0.0, top_score - second_score)
    unique_files = len({hit.chunk.relpath for hit in hits})
    graph_edge_count = len(bundle.graph_edges)
    matched_terms = list(dict.fromkeys(term for hit in hits[:4] for term in hit.matched_terms))[:12]
    symbol_hits = sum(1 for hit in hits if hit.chunk.symbol_name)
    route_hits = sum(1 for hit in hits if hit.chunk.route_path)

    confidence = 0.0
    strengths: list[str] = []
    warnings: list[str] = []

    if hits:
        confidence += 0.28
        strengths.append("ranked evidence found")
    else:
        warnings.append("no ranked code evidence was found")

    if top_score >= 18:
        confidence += 0.22
        strengths.append("strong top score")
    elif top_score >= 10:
        confidence += 0.14
        strengths.append("usable top score")
    elif hits:
        confidence += 0.06
        warnings.append("top score is weak")

    if score_gap >= 6:
        confidence += 0.16
        strengths.append("clear separation from the next hit")
    elif len(hits) > 1:
        confidence += 0.06
        warnings.append("top hits are close together")

    if matched_terms:
        confidence += min(0.14, 0.035 * len(matched_terms))
        strengths.append("query terms matched code vocabulary")
    else:
        warnings.append("no direct query-term overlap")

    if graph_edge_count:
        confidence += min(0.12, 0.035 * graph_edge_count)
        strengths.append("repository graph supports the ranking")
    elif len(hits) > 1:
        warnings.append("ranking has no supporting graph edge among top hits")

    if unique_files >= 2:
        confidence += 0.06
        strengths.append("evidence spans multiple files")
    elif hits:
        warnings.append("evidence is concentrated in one file")

    if symbol_hits:
        confidence += 0.06
        strengths.append("symbol-level evidence is available")
    if route_hits:
        confidence += 0.04
        strengths.append("route-level evidence is available")

    if hits and all(not hit.chunk.symbol_name for hit in hits[: min(3, len(hits))]):
        warnings.append("top evidence is file-level rather than symbol-level")

    confidence = max(0.0, min(1.0, confidence))
    label = "high" if confidence >= 0.72 else "medium" if confidence >= 0.45 else "low"
    return EvidenceDiagnostics(
        confidence=round(confidence, 2),
        label=label,
        evidence_count=len(hits),
        unique_files=unique_files,
        graph_edge_count=graph_edge_count,
        top_score=round(top_score, 2),
        score_gap=round(score_gap, 2),
        matched_terms=matched_terms,
        strengths=strengths[:6],
        warnings=warnings[:6],
    )


def build_evidence_proof(query: str, bundle: InvestigationBundle) -> dict[str, Any]:
    hits = bundle.final_hits
    graph_search = bundle.graph_search or {}
    route_anchors = list(graph_search.get("route_anchors") or [])
    top_hit = hits[0] if hits else None
    top_label = top_hit.chunk.source_label if top_hit else ""
    route_literals = list(dict.fromkeys(str(item.get("route", "")) for item in route_anchors if item.get("route")))
    supporting_paths = [
        item
        for item in route_anchors
        if top_label and (item.get("chunk") == top_label or top_label in item.get("path", []))
    ]
    if not supporting_paths and route_anchors:
        supporting_paths = route_anchors[:3]

    has_route_anchor = bool(route_anchors)
    top_on_route_path = bool(top_label and any(item.get("chunk") == top_label for item in route_anchors))
    top_in_route_trace = bool(top_label and any(top_label in item.get("path", []) for item in route_anchors))
    graph_search_ran = int(graph_search.get("iterations", 0) or 0) > 0
    status = "proved" if has_route_anchor and (top_on_route_path or top_in_route_trace) else "partial" if graph_search_ran else "unanchored"
    if not has_route_anchor:
        status = "unanchored"

    checks = [
        {
            "name": "graph_search_ran",
            "passed": graph_search_ran,
            "detail": f"iterations={int(graph_search.get('iterations', 0) or 0)}",
        },
        {
            "name": "route_anchor_present",
            "passed": has_route_anchor,
            "detail": ", ".join(route_literals) or "no exact route literal was anchored",
        },
        {
            "name": "top_hit_on_route_path",
            "passed": top_on_route_path or top_in_route_trace,
            "detail": top_label or "no top hit",
        },
    ]
    warnings = []
    if not has_route_anchor and "/" in query:
        warnings.append("query contains a path-like token, but no route anchor matched the repository graph")
    if has_route_anchor and not (top_on_route_path or top_in_route_trace):
        warnings.append("top hit is not on the route-anchored execution path")

    supporting_path_payload = [
        {
            "route": item.get("route", ""),
            "chunk": item.get("chunk", ""),
            "depth": item.get("depth", 0),
            "boost": item.get("boost", 0.0),
            "path": item.get("path", []),
        }
        for item in supporting_paths[:6]
    ]
    audit_hits = _dedupe_retrieval_hits([*hits, *bundle.seed_hits])
    proof_graph = _build_proof_graph(
        top_label=top_label,
        hits=audit_hits,
        route_literals=route_literals,
        route_anchors=route_anchors,
        supporting_paths=supporting_path_payload,
        graph_search=graph_search,
    )
    decoy_audit = _build_decoy_audit(
        top_hit=top_hit,
        hits=audit_hits,
        route_anchors=route_anchors,
        route_literals=route_literals,
    )

    return {
        "schema_version": "1.0",
        "strategy": "proof_carrying_retrieval",
        "status": status,
        "claim": f"{top_label} is the best-supported answer" if top_label else "no supported answer",
        "top_hit": top_label,
        "route_literals": route_literals,
        "checks": checks,
        "supporting_paths": supporting_path_payload,
        "proof_graph": proof_graph,
        "decoy_audit": decoy_audit,
        "warnings": warnings,
    }


def _build_decoy_audit(
    *,
    top_hit: RetrievalHit | None,
    hits: list[RetrievalHit],
    route_anchors: list[dict[str, Any]],
    route_literals: list[str],
) -> list[dict[str, Any]]:
    if not top_hit:
        return []
    top_label = top_hit.chunk.source_label
    anchored_labels = {
        str(item.get("chunk", ""))
        for item in route_anchors
        if item.get("chunk")
    }
    anchored_path_labels = {
        str(label)
        for item in route_anchors
        for label in item.get("path", [])
    }
    audits: list[dict[str, Any]] = []
    for hit in hits[1:10]:
        label = hit.chunk.source_label
        if not _looks_like_decoy(label, top_label):
            continue
        route_anchored = label in anchored_labels or label in anchored_path_labels
        conflicting_roles = _decoy_roles(label)
        reason = "candidate resembles the top answer lexically but is not on the requested route-anchored path"
        if route_anchored:
            reason = "candidate is route-reachable, but the top answer has stronger writer/path evidence"
        if conflicting_roles:
            reason = (
                f"candidate belongs to {', '.join(conflicting_roles)} surface; "
                "it conflicts with the requested route family"
            )
        audits.append(
            {
                "candidate": label,
                "score": round(hit.score, 2),
                "top_hit": top_label,
                "top_score": round(top_hit.score, 2),
                "score_gap": round(top_hit.score - hit.score, 2),
                "route_anchored": route_anchored,
                "requested_routes": route_literals,
                "conflicting_roles": conflicting_roles,
                "rejected": not route_anchored or bool(conflicting_roles),
                "reason": reason,
            }
        )
    return audits


def _dedupe_retrieval_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    deduped: dict[str, RetrievalHit] = {}
    for hit in hits:
        label = hit.chunk.source_label
        existing = deduped.get(label)
        if existing is None or hit.score > existing.score:
            deduped[label] = hit
    return sorted(deduped.values(), key=lambda item: item.score, reverse=True)


def _decoy_roles(label: str) -> list[str]:
    lowered = label.lower()
    roles = []
    markers = {
        "admin": "admin",
        "legacy": "legacy",
        "fake": "fake/mock",
        "mock": "fake/mock",
        "note": "documentation/notes",
        "doc": "documentation/notes",
    }
    for marker, role in markers.items():
        if marker in lowered and role not in roles:
            roles.append(role)
    return roles


def _build_proof_graph(
    *,
    top_label: str,
    hits: list[RetrievalHit],
    route_literals: list[str],
    route_anchors: list[dict[str, Any]],
    supporting_paths: list[dict[str, Any]],
    graph_search: dict[str, Any],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(node_id: str, role: str, *, label: str = "", score: float | None = None) -> None:
        if not node_id:
            return
        node = nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "label": label or node_id,
                "roles": [],
            },
        )
        if role and role not in node["roles"]:
            node["roles"].append(role)
        if score is not None:
            node["score"] = round(score, 2)

    def add_edge(source: str, target: str, label: str, *, route: str = "", weight: float = 0.0) -> None:
        if not source or not target or source == target:
            return
        key = (source, target, label)
        item = edges.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "label": label,
            },
        )
        if route:
            item["route"] = route
        if weight:
            item["weight"] = round(float(weight), 2)

    for route in route_literals:
        add_node(route, "route_anchor", label=route)

    if top_label:
        add_node(top_label, "top_hit")

    supporting_node_ids = {
        str(label)
        for item in supporting_paths
        for label in item.get("path", [])
    }
    supporting_node_ids.update(str(item.get("chunk", "")) for item in supporting_paths)

    for hit in hits[:8]:
        label = hit.chunk.source_label
        role = "supporting" if label in supporting_node_ids else "candidate"
        if label == top_label:
            role = "top_hit"
        elif _looks_like_decoy(label, top_label):
            role = "decoy"
        add_node(label, role, score=hit.score)

    for item in supporting_paths:
        route = str(item.get("route", ""))
        path = [str(label) for label in item.get("path", []) if label]
        if route and path:
            add_edge(route, path[0], "anchors", route=route, weight=float(item.get("boost", 0.0) or 0.0))
        for label in path:
            add_node(label, "supporting")
        for source, target in zip(path, path[1:], strict=False):
            add_edge(source, target, "route_path", route=route, weight=float(item.get("boost", 0.0) or 0.0))

    for item in route_anchors[:8]:
        route = str(item.get("route", ""))
        path = [str(label) for label in item.get("path", []) if label]
        if route:
            add_node(route, "route_anchor", label=route)
        for label in path:
            add_node(label, "route_reachable")
        if route and path:
            add_edge(route, path[0], "anchors", route=route, weight=float(item.get("boost", 0.0) or 0.0))
        for source, target in zip(path, path[1:], strict=False):
            add_edge(source, target, "route_path", route=route, weight=float(item.get("boost", 0.0) or 0.0))

    for item in list(graph_search.get("top_visited") or [])[:5]:
        chunk = str(item.get("chunk", ""))
        if not chunk:
            continue
        add_node(chunk, "mcts_visited")
        if top_label and chunk != top_label:
            add_edge(top_label, chunk, "ranked_against", weight=float(item.get("boost", 0.0) or 0.0))

    return {
        "schema_version": "1.0",
        "nodes": sorted(nodes.values(), key=lambda item: (0 if "route_anchor" in item["roles"] else 1, item["id"])),
        "edges": list(edges.values()),
    }


def _looks_like_decoy(label: str, top_label: str) -> bool:
    if not label or not top_label:
        return False
    lowered = label.lower()
    top_lowered = top_label.lower()
    if label == top_label:
        return False
    if "chat" not in lowered or "chat" not in top_lowered:
        return False
    return any(marker in lowered for marker in ("admin", "legacy", "fake", "mock", "note", "doc"))
