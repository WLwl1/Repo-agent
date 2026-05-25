from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .ignore import relpath_has_ignored_part
from .models import CodeChunk, FileFact, FileHit, GraphEdge, InvestigationBundle, QueryPlan, RetrievalHit
from .parsers import analyze_source, detect_language

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}")
QUERY_SYNONYMS = {
    "聊天": ["chat", "message"],
    "流式": ["stream", "streamed", "sse", "delta"],
    "输出": ["output", "content", "response"],
    "实现": ["handle", "run", "create", "function"],
    "接口": ["api", "route", "post", "get"],
    "路由": ["api", "route", "endpoint", "post", "get"],
    "入口": ["entry", "route", "handler", "endpoint"],
    "处理": ["handle", "handler", "process", "function"],
    "函数": ["function", "handler", "method"],
    "重置": ["reset", "clear", "delete"],
    "会话": ["session", "messages", "history"],
    "上传": ["upload", "ingest", "document"],
    "文档": ["document", "documents", "rag"],
    "流程": ["runagent", "flow", "pipeline", "process"],
    "主流程": ["runagent", "handleagentrequest"],
    "检索": ["retrieve", "search", "rag"],
    "缺陷": ["bug", "error", "throw", "catch"],
    "错误": ["error", "throw", "catch", "status"],
    "报错": ["error", "throw", "catch", "status"],
    "故障": ["bug", "error", "failure"],
    "异常": ["error", "throw", "catch", "status"],
    "定位": ["locate", "find", "search"],
    "调用链": ["call", "handler", "import"],
    "网页": ["web", "html", "frontend", "page", "ui", "browser"],
    "前端": ["web", "frontend", "html", "css", "ui", "browser"],
    "页面": ["page", "html", "view", "ui", "screen"],
    "界面": ["ui", "frontend", "view", "page", "html"],
    "样式": ["css", "style", "stylesheet"],
    "浏览器": ["browser", "frontend", "web", "client"],
    "按钮": ["button", "click", "action"],
    "交互": ["interaction", "event", "click", "frontend", "ui"],
    "逻辑": ["logic", "handler", "state", "function"],
}
WEB_QUERY_TERMS = ("网页", "前端", "页面", "界面", "样式", "浏览器", "html", "css", "ui", "frontend", "web")
INTERACTION_QUERY_TERMS = ("交互", "interaction", "event", "click", "logic")
STYLE_QUERY_TERMS = ("样式", "css", "style")
FLOW_QUERY_TERMS = ("流程", "主流程", "flow", "pipeline", "execution", "path")
CONFIG_QUERY_TERMS = ("配置", "config", "env", "environment", "设置")
TEST_QUERY_TERMS = ("测试", "test", "pytest", "spec", "case")


class RepositoryIndex:
    def __init__(self, repo_root: Path, chunks: list[CodeChunk], file_facts: list[FileFact], edges: list[GraphEdge]):
        self.repo_root = repo_root
        self.chunks = chunks
        self.file_facts = file_facts
        self.edges = edges
        self.doc_count = max(len(chunks), 1)
        self.chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self.file_fact_by_relpath = {fact.relpath: fact for fact in file_facts}
        self.file_to_chunks = self._group_file_chunks(chunks)
        self.symbol_to_chunks = self._group_symbol_chunks(chunks)
        self.forward_edges = self._group_edges(edges, reverse=False)
        self.reverse_edges = self._group_edges(edges, reverse=True)
        self.doc_freq = self._build_doc_freq(chunks)
        self.file_doc_freq = self._build_file_doc_freq(file_facts)
        self.semantic = self._build_semantic_features(chunks)

    def stats(self) -> dict:
        languages = Counter(chunk.language for chunk in self.chunks)
        route_count = sum(1 for chunk in self.chunks if chunk.symbol_kind == "route")
        return {
            "repo_root": str(self.repo_root),
            "chunk_count": len(self.chunks),
            "file_count": len(self.file_facts),
            "graph_edge_count": len(self.edges),
            "route_count": route_count,
            "semantic_dimensions": int(self.semantic["latent"].shape[1]) if self.semantic["latent"] is not None else 0,
            "language_distribution": dict(languages),
        }

    def repository_overview(self, limit: int = 12) -> dict:
        ranked_files = sorted(
            self.file_facts,
            key=lambda item: (len(item.routes), len(item.symbol_names), len(item.imports), item.relpath),
            reverse=True,
        )
        return {
            "stats": self.stats(),
            "top_files": [
                {
                    "relpath": fact.relpath,
                    "language": fact.language,
                    "line_count": fact.line_count,
                    "import_count": len(fact.imports),
                    "symbol_count": len(fact.symbol_names),
                    "route_count": len(fact.routes),
                    "roles": fact.roles,
                }
                for fact in ranked_files[:limit]
            ],
            "top_edges": [
                {
                    "source": self.chunk_by_id.get(
                        edge.source,
                        CodeChunk(edge.source, self.repo_root, edge.source, "unknown", "", 1, 1),
                    ).source_label,
                    "target": self.chunk_by_id.get(
                        edge.target,
                        CodeChunk(edge.target, self.repo_root, edge.target, "unknown", "", 1, 1),
                    ).source_label,
                    "label": edge.label,
                    "weight": edge.weight,
                }
                for edge in sorted(self.edges, key=lambda item: item.weight, reverse=True)[:limit]
            ],
        }

    def search(self, query: str, top_k: int = 5) -> list[tuple[CodeChunk, float, list[str], list[str]]]:
        bundle = self.investigate(query, top_k=top_k)
        return [(hit.chunk, hit.score, hit.matched_terms, hit.reasons) for hit in bundle.final_hits]

    def plan_query(self, query: str) -> QueryPlan:
        return self._plan_query(query, _classify_mode(query))

    def semantic_scores_for(self, query: str) -> dict[str, float]:
        return self._semantic_scores(query)

    def scout_files(self, plan: QueryPlan, limit: int = 6) -> list[FileHit]:
        return self._rank_files(plan)[:limit]

    def read_candidates(
        self,
        query: str,
        plan: QueryPlan,
        file_hits: list[FileHit],
        semantic_scores: dict[str, float],
        *,
        top_k: int,
    ) -> tuple[list[RetrievalHit], dict[str, float]]:
        return self._retrieve_primary_hits(query, plan, file_hits, semantic_scores, top_k=top_k)

    def follow_neighbors(self, seed_hits: list[RetrievalHit], plan: QueryPlan) -> tuple[dict[str, float], list[str]]:
        return self._explore_neighbors(seed_hits, plan)

    def rerank_candidates(
        self,
        query: str,
        plan: QueryPlan,
        seed_hits: list[RetrievalHit],
        file_boosts: dict[str, float],
        relation_boosts: dict[str, float],
        semantic_scores: dict[str, float],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        return self._rerank_multistep(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )

    def relevant_edges(self, hits: list[RetrievalHit]) -> list[GraphEdge]:
        return self._select_relevant_edges(hits)

    def investigate(self, query: str, top_k: int = 6) -> InvestigationBundle:
        mode = _classify_mode(query)
        plan = self._plan_query(query, mode)
        trace = [
            {
                "step": 1,
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
        ]
        semantic_scores = self._semantic_scores(query)
        file_hits = self._rank_files(plan)
        trace.append(
            {
                "step": 2,
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
            }
        )
        seed_hits, file_boosts = self._retrieve_primary_hits(query, plan, file_hits, semantic_scores, top_k=top_k)
        trace.append(
            {
                "step": 3,
                "type": "code_read",
                "content": "\n".join(
                    (
                        f"{hit.chunk.source_label} | {hit.score:.2f} | "
                        f"{', '.join(hit.reasons[:5])}"
                    )
                    for hit in seed_hits[:6]
                )
                or "no primary evidence",
            }
        )
        relation_boosts, hop_trace = self._explore_neighbors(seed_hits[: max(2, min(4, top_k))], plan)
        trace.append(
            {
                "step": 4,
                "type": "graph_hop",
                "content": "\n".join(hop_trace[:10]) or "no graph hops taken",
            }
        )
        final_hits = self._rerank_multistep(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )
        selected_edges = self._select_relevant_edges(final_hits)
        trace.append(
            {
                "step": 5,
                "type": "final_ranking",
                "content": "\n".join(
                    f"{hit.chunk.source_label} | {hit.score:.2f} | {', '.join(hit.reasons[:5])}"
                    for hit in final_hits
                ),
            }
        )
        return InvestigationBundle(
            mode=mode,
            focus_terms=plan.focus_terms,
            seed_hits=seed_hits[:5],
            final_hits=final_hits,
            graph_edges=selected_edges,
            trace=trace,
        )

    def _plan_query(self, query: str, mode: str) -> QueryPlan:
        lowered = query.lower()
        focus_terms = expand_query_terms(query)
        target_roles: list[str] = []
        target_languages: list[str] = []
        intent = "code_lookup"
        hop_budget = 2

        if any(term in lowered for term in WEB_QUERY_TERMS):
            intent = "frontend_lookup"
            target_roles.extend(["frontend"])
        if any(term in lowered for term in STYLE_QUERY_TERMS):
            intent = "style_lookup"
            target_roles.extend(["frontend", "styles"])
            target_languages.append("css")
            hop_budget = 1
        if any(term in lowered for term in INTERACTION_QUERY_TERMS):
            intent = "frontend_interaction"
            target_roles.extend(["frontend", "frontend_logic"])
            target_languages.append("javascript")
        if any(term in lowered for term in ("api", "route", "endpoint", "接口", "路由", "入口")):
            intent = "api_lookup"
            target_roles.extend(["backend", "api", "entrypoint"])
            target_languages.extend(["javascript", "python", "typescript"])
        if any(term in lowered for term in FLOW_QUERY_TERMS):
            intent = "flow_trace"
            target_roles.extend(["entrypoint", "backend", "api"])
            hop_budget = max(hop_budget, 3)
        if any(term in lowered for term in CONFIG_QUERY_TERMS):
            intent = "config_lookup"
            target_roles.extend(["config"])
            hop_budget = 1
        if any(term in lowered for term in TEST_QUERY_TERMS):
            intent = "test_lookup"
            target_roles.extend(["tests"])
            hop_budget = 1
        if mode == "bug_localization":
            intent = "bug_trace"
            hop_budget = max(hop_budget, 3)

        return QueryPlan(
            mode=mode,
            intent=intent,
            focus_terms=focus_terms,
            target_roles=list(dict.fromkeys(target_roles)),
            target_languages=list(dict.fromkeys(target_languages)),
            hop_budget=hop_budget,
        )

    def _rank_files(self, plan: QueryPlan) -> list[FileHit]:
        ranked: list[FileHit] = []
        query_set = set(plan.focus_terms)
        for fact in self.file_facts:
            tokens = file_fact_tokens(fact)
            token_counter = Counter(tokens)
            matched_terms = sorted(query_set.intersection(token_counter.keys()))
            score = 0.0
            reasons: list[str] = []

            for term in matched_terms:
                tf = token_counter[term]
                idf = math.log((len(self.file_facts) + 1) / (1 + self.file_doc_freq.get(term, 0))) + 1.0
                score += (1.0 + math.log(tf)) * idf

            matched_roles = [role for role in plan.target_roles if role in fact.roles]
            if matched_roles:
                score += 6.0 + 1.2 * max(len(matched_roles) - 1, 0)
                reasons.append(f"role match {','.join(matched_roles)}")
            if plan.target_languages and fact.language in plan.target_languages:
                score += 3.5
                reasons.append(f"language match {fact.language}")
            if plan.intent == "flow_trace" and any(role in fact.roles for role in ("entrypoint", "api")):
                score += 2.5
                reasons.append("entry surface")
            if plan.intent == "bug_trace" and any(role in fact.roles for role in ("backend", "frontend", "frontend_logic")):
                score += 1.8
                reasons.append("runtime surface")
            if fact.relpath.startswith("web/") and "frontend" in plan.target_roles:
                score += 2.0
                reasons.append("frontend directory")
            if fact.language == "html" and plan.intent in {"frontend_lookup", "style_lookup"}:
                score += 1.5
                reasons.append("html shell")
            if fact.language == "css" and plan.intent == "style_lookup":
                score += 2.0
                reasons.append("stylesheet file")
            if fact.routes and plan.intent in {"api_lookup", "flow_trace", "bug_trace"}:
                score += 1.6
                reasons.append("contains routes")

            if score <= 0:
                continue
            ranked.append(FileHit(file_fact=fact, score=score, matched_terms=matched_terms, reasons=reasons or ["token overlap"]))

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _retrieve_primary_hits(
        self,
        query: str,
        plan: QueryPlan,
        file_hits: list[FileHit],
        semantic_scores: dict[str, float],
        *,
        top_k: int,
    ) -> tuple[list[RetrievalHit], dict[str, float]]:
        selected_files = file_hits[: max(4, min(top_k + 3, 8))]
        file_boosts = {
            item.file_fact.relpath: max(1.4, min(item.score * 0.32, 8.0))
            for item in selected_files
        }
        candidates: dict[str, RetrievalHit] = {}

        def record_hit(chunk: CodeChunk, total_score: float, matched_terms: list[str], reasons: list[str]) -> None:
            existing = candidates.get(chunk.chunk_id)
            if existing is None or total_score > existing.score:
                candidates[chunk.chunk_id] = RetrievalHit(
                    chunk=chunk,
                    score=total_score,
                    matched_terms=matched_terms,
                    reasons=reasons,
                )

        for file_hit in selected_files:
            relpath = file_hit.file_fact.relpath
            file_boost = file_boosts.get(relpath, 0.0)
            for chunk_id in self.file_to_chunks.get(relpath, []):
                chunk = self.chunk_by_id[chunk_id]
                base_score, matched_terms, reasons = self._score_chunk(query, chunk, semantic_scores.get(chunk_id, 0.0))
                if base_score <= 0 and not matched_terms and chunk.symbol_name:
                    continue
                total_score = max(base_score, 0.0) + file_boost
                if not chunk.symbol_name:
                    total_score += 0.8 if plan.intent in {"frontend_lookup", "style_lookup", "code_lookup"} else -1.2
                record_hit(
                    chunk,
                    total_score,
                    matched_terms,
                    list(reasons or ["token overlap"]) + [f"file scout +{file_boost:.1f}"],
                )

        for hit in self._score_all_chunks(query, semantic_scores)[: max(top_k + 4, 8)]:
            file_boost = file_boosts.get(hit.chunk.relpath, 0.0)
            total_score = hit.score + file_boost
            reasons = list(hit.reasons)
            if file_boost:
                reasons.append(f"file scout +{file_boost:.1f}")
            record_hit(hit.chunk, total_score, hit.matched_terms, reasons)

        primary_hits = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
        return primary_hits[: max(top_k + 4, 8)], file_boosts

    def _explore_neighbors(self, seed_hits: list[RetrievalHit], plan: QueryPlan) -> tuple[dict[str, float], list[str]]:
        boosts: dict[str, float] = defaultdict(float)
        frontier = [hit.chunk.chunk_id for hit in seed_hits[:3]]
        visited = set(frontier)
        trace_lines: list[str] = []

        for hop in range(1, plan.hop_budget + 1):
            if not frontier:
                break
            next_frontier: list[str] = []
            for chunk_id in frontier:
                source_label = self.chunk_by_id[chunk_id].source_label
                edges = self.forward_edges.get(chunk_id, []) + self.reverse_edges.get(chunk_id, [])
                for edge in edges[:8]:
                    target_chunk = self.chunk_by_id.get(edge.target)
                    if target_chunk is None:
                        continue
                    boost = edge.weight * (1.9 if hop == 1 else 1.15)
                    if plan.target_roles and not self._chunk_matches_roles(target_chunk, plan.target_roles):
                        boost *= 0.75
                    boosts[edge.target] += boost
                    trace_lines.append(
                        f"hop {hop}: {source_label} -> {target_chunk.source_label} via {edge.label} (+{boost:.1f})"
                    )
                    if edge.target not in visited:
                        visited.add(edge.target)
                        next_frontier.append(edge.target)
            frontier = next_frontier[:6]

        return boosts, trace_lines

    def _rerank_multistep(
        self,
        query: str,
        plan: QueryPlan,
        seed_hits: list[RetrievalHit],
        file_boosts: dict[str, float],
        relation_boosts: dict[str, float],
        semantic_scores: dict[str, float],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        seed_lookup = {hit.chunk.chunk_id: hit for hit in seed_hits}
        candidate_ids = set(seed_lookup)
        candidate_ids.update(relation_boosts.keys())
        reranked: list[RetrievalHit] = []

        for chunk_id in candidate_ids:
            chunk = self.chunk_by_id[chunk_id]
            seed_hit = seed_lookup.get(chunk_id)
            if seed_hit:
                base_score = seed_hit.score
                matched_terms = seed_hit.matched_terms
                reasons = list(seed_hit.reasons)
            else:
                raw_score, matched_terms, reasons = self._score_chunk(query, chunk, semantic_scores.get(chunk_id, 0.0))
                base_score = max(raw_score, 0.0)
            total_score = base_score + relation_boosts.get(chunk_id, 0.0)
            file_boost = file_boosts.get(chunk.relpath, 0.0)
            if file_boost and not any(reason.startswith("file scout") for reason in reasons):
                total_score += file_boost
                reasons = reasons + [f"file scout +{file_boost:.1f}"]
            if relation_boosts.get(chunk_id):
                reasons = reasons + [f"hop boost +{relation_boosts[chunk_id]:.1f}"]
            if plan.target_roles and self._chunk_matches_roles(chunk, plan.target_roles):
                total_score += 1.4
                reasons = reasons + ["role aligned"]
            if plan.intent in {"api_lookup", "flow_trace", "frontend_interaction"} and not chunk.symbol_name:
                total_score *= 0.82
                reasons = reasons + ["overview downrank"]
            if plan.intent in {"api_lookup", "flow_trace"} and chunk.symbol_kind == "function":
                total_score += 2.6
                reasons = reasons + ["concrete step"]
            if plan.intent == "frontend_lookup" and chunk.relpath == "web/index.html" and not chunk.symbol_name:
                total_score += 4.0
                reasons = reasons + ["page shell"]
            if plan.intent == "style_lookup" and chunk.relpath == "web/styles.css" and not chunk.symbol_name:
                total_score += 4.0
                reasons = reasons + ["style shell"]
            if total_score <= 0:
                continue
            reranked.append(RetrievalHit(chunk=chunk, score=total_score, matched_terms=matched_terms, reasons=reasons))

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    def _chunk_matches_roles(self, chunk: CodeChunk, target_roles: list[str]) -> bool:
        file_fact = self.file_fact_by_relpath.get(chunk.relpath)
        if not file_fact:
            return False
        return any(role in file_fact.roles for role in target_roles)

    def to_payload(self) -> dict:
        return {
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "relpath": chunk.relpath,
                    "language": chunk.language,
                    "text": chunk.text,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "symbol_name": chunk.symbol_name,
                    "symbol_kind": chunk.symbol_kind,
                    "metadata_tokens": chunk.metadata_tokens,
                    "imports": chunk.imports,
                    "calls": chunk.calls,
                    "route_path": chunk.route_path,
                    "handler_names": chunk.handler_names,
                }
                for chunk in self.chunks
            ],
            "file_facts": [
                {
                    "relpath": fact.relpath,
                    "language": fact.language,
                    "line_count": fact.line_count,
                    "imports": fact.imports,
                    "symbol_names": fact.symbol_names,
                    "routes": fact.routes,
                    "roles": fact.roles,
                }
                for fact in self.file_facts
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "label": edge.label,
                    "weight": edge.weight,
                }
                for edge in self.edges
            ],
        }

    @classmethod
    def from_payload(cls, repo_root: Path, payload: dict) -> "RepositoryIndex":
        repo_root = repo_root.resolve()
        chunks = [
            CodeChunk(
                chunk_id=item["chunk_id"],
                repo_root=repo_root,
                relpath=item["relpath"],
                language=item["language"],
                text=item["text"],
                start_line=item["start_line"],
                end_line=item["end_line"],
                symbol_name=item.get("symbol_name", ""),
                symbol_kind=item.get("symbol_kind", ""),
                metadata_tokens=list(item.get("metadata_tokens", [])),
                imports=list(item.get("imports", [])),
                calls=list(item.get("calls", [])),
                route_path=item.get("route_path", ""),
                handler_names=list(item.get("handler_names", [])),
            )
            for item in payload.get("chunks", [])
        ]
        file_facts = [
            FileFact(
                relpath=item["relpath"],
                language=item["language"],
                line_count=item["line_count"],
                imports=list(item.get("imports", [])),
                symbol_names=list(item.get("symbol_names", [])),
                routes=list(item.get("routes", [])),
                roles=list(item.get("roles", [])),
            )
            for item in payload.get("file_facts", [])
        ]
        edges = [
            GraphEdge(
                source=item["source"],
                target=item["target"],
                label=item["label"],
                weight=float(item["weight"]),
            )
            for item in payload.get("edges", [])
        ]
        return cls(repo_root=repo_root, chunks=chunks, file_facts=file_facts, edges=edges)

    def _score_all_chunks(self, query: str, semantic_scores: dict[str, float]) -> list[RetrievalHit]:
        scored: list[RetrievalHit] = []
        for chunk in self.chunks:
            score, matched_terms, reasons = self._score_chunk(query, chunk, semantic_scores.get(chunk.chunk_id, 0.0))
            if score > 0:
                scored.append(RetrievalHit(chunk=chunk, score=score, matched_terms=matched_terms, reasons=reasons))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored

    def _score_chunk(self, query: str, chunk: CodeChunk, semantic_score: float) -> tuple[float, list[str], list[str]]:
        query_terms = expand_query_terms(query)
        query_set = set(query_terms)
        chunk_counter = Counter(chunk_tokens(chunk))
        matched_terms = sorted(query_set.intersection(chunk_counter.keys()))
        if not matched_terms and semantic_score < 0.16:
            return 0.0, [], []

        score = 0.0
        reasons: list[str] = []
        lowered_query = query.lower()
        symbol_lower = chunk.symbol_name.lower()
        text_lower = chunk.text.lower()
        route_tokens = set(tokenize(chunk.route_path))

        for term in matched_terms:
            tf = chunk_counter[term]
            idf = math.log((self.doc_count + 1) / (1 + self.doc_freq.get(term, 0))) + 1.0
            score += (1.0 + math.log(tf)) * idf

        if semantic_score > 0:
            score += semantic_score * 12.0
            reasons.append(f"semantic {semantic_score:.2f}")
            if not matched_terms:
                matched_terms = ["semantic_projection"]

        symbol_overlap = sum(1 for term in matched_terms if term in symbol_lower)
        path_overlap = sum(1 for term in matched_terms if term in chunk.relpath.lower())
        route_overlap = len(query_set.intersection(route_tokens))

        if chunk.symbol_name and symbol_overlap:
            score += 2.8
            reasons.append("symbol match")
            if symbol_overlap > 1:
                score += 1.6 * (symbol_overlap - 1)
                reasons.append(f"symbol overlap x{symbol_overlap}")
        if path_overlap:
            score += 1.8
            reasons.append("path match")
            if path_overlap > 1:
                score += 0.6 * (path_overlap - 1)
                reasons.append(f"path overlap x{path_overlap}")
        if route_overlap:
            score += 2.4 + 0.8 * (route_overlap - 1)
            reasons.append(f"route path overlap x{route_overlap}")
        if any(term in lowered_query for term in ("api", "endpoint", "route", "入口", "接口", "路由")) and chunk.symbol_kind == "route":
            score += 6.0
            reasons.append("route boost")
        if any(term in lowered_query for term in ("entry", "入口")) and chunk.symbol_kind not in {"route", "function"}:
            score -= 2.5
            reasons.append("entry penalty")
        if any(term in lowered_query for term in ("函数", "handler", "function", "处理")):
            if chunk.symbol_kind == "function":
                score += 4.2
                reasons.append("function target")
            elif chunk.symbol_kind == "route":
                score -= 1.6
                reasons.append("route detour")
        if "流式" in query and ("stream" in text_lower or "stream" in symbol_lower):
            score += 4.0
            reasons.append("stream boost")
        if "上传" in query and ("upload" in text_lower or "upload" in symbol_lower):
            score += 3.5
            reasons.append("upload boost")
        if any(term in query for term in ("主流程", "流程")) and symbol_lower in {"runagent", "handleagentrequest"}:
            score += 6.5
            reasons.append("flow boost")
        if any(term in lowered_query for term in FLOW_QUERY_TERMS):
            if chunk.symbol_kind == "function":
                score += 2.8
                reasons.append("flow function boost")
            elif not chunk.symbol_name:
                score -= 1.4
                reasons.append("overview penalty")
        if "聊天" in query and "chat" in symbol_lower:
            score += 2.0
            reasons.append("chat boost")
        if any(term in lowered_query for term in WEB_QUERY_TERMS):
            is_web_surface = chunk.relpath.startswith("web/")
            if chunk.relpath.startswith("web/"):
                score += 12.0
                reasons.append("web app boost")
            if chunk.language == "html":
                score += 5.0
                reasons.append("html boost")
            if chunk.language == "css":
                score += 5.0
                reasons.append("css boost")
            if chunk.language == "javascript" and is_web_surface:
                score += 4.0
                reasons.append("frontend logic boost")
            if not is_web_surface and chunk.language not in {"html", "css"}:
                score *= 0.35
                reasons.append("non-web downrank")
        if any(term in lowered_query for term in ("样式", "css", "style")) and chunk.language == "css":
            score += 8.0
            reasons.append("style boost")
        if any(term in lowered_query for term in ("样式", "css", "style")) and chunk.relpath == "web/styles.css":
            score += 8.0
            reasons.append("stylesheet entry boost")
        if any(term in lowered_query for term in ("交互", "interaction", "event", "click", "logic")):
            if chunk.relpath == "web/app.js":
                score += 12.0
                reasons.append("interaction entry boost")
            elif chunk.language == "javascript" and chunk.relpath.startswith("web/"):
                score += 3.5
                reasons.append("interaction logic boost")
        if (
            any(term in lowered_query for term in ("网页", "页面", "界面", "html", "web"))
            and not any(term in lowered_query for term in ("样式", "css", "style"))
            and chunk.relpath == "web/index.html"
        ):
            score += 8.0
            reasons.append("page entry boost")
        if any(term in lowered_query for term in ("bug", "error", "缺陷", "错误", "报错", "故障", "异常", "500", "定位", "排查")):
            if any(flag in text_lower for flag in ("throw", "error", "catch", "abort", "status")):
                score += 2.5
                reasons.append("bug clue")
        if chunk.route_path:
            score += 0.6
        if chunk.calls:
            score += min(len(chunk.calls), 6) * 0.25
        return score, matched_terms, reasons or ["token overlap"]

    def _expand_from_seed_hits(self, seed_hits: list[RetrievalHit], query: str) -> dict[str, float]:
        boosts: dict[str, float] = defaultdict(float)
        lowered_query = query.lower()
        for hit in seed_hits:
            for sibling_id in self.file_to_chunks.get(hit.chunk.relpath, []):
                if sibling_id != hit.chunk.chunk_id:
                    boosts[sibling_id] += 0.8
            for edge in self.forward_edges.get(hit.chunk.chunk_id, []):
                boosts[edge.target] += edge.weight * 1.4
            for edge in self.reverse_edges.get(hit.chunk.chunk_id, []):
                boosts[edge.target] += edge.weight * 1.1
            if any(term in lowered_query for term in ("bug", "error", "报错", "异常", "定位", "排查")):
                for called_name in hit.chunk.calls + hit.chunk.handler_names:
                    for candidate_id in self.symbol_to_chunks.get(called_name.lower(), []):
                        boosts[candidate_id] += 2.0
        return boosts

    def _rerank_hits(
        self,
        query: str,
        seed_hits: list[RetrievalHit],
        relation_boosts: dict[str, float],
        semantic_scores: dict[str, float],
        top_k: int,
    ) -> list[RetrievalHit]:
        seed_lookup = {hit.chunk.chunk_id: hit for hit in seed_hits}
        candidate_ids = set(seed_lookup)
        candidate_ids.update(relation_boosts.keys())
        reranked: list[RetrievalHit] = []
        for chunk_id in candidate_ids:
            chunk = self.chunk_by_id[chunk_id]
            seed_hit = seed_lookup.get(chunk_id)
            if seed_hit:
                base_score = seed_hit.score
                matched_terms = seed_hit.matched_terms
                reasons = list(seed_hit.reasons)
            else:
                base_score, matched_terms, reasons = self._score_chunk(query, chunk, semantic_scores.get(chunk_id, 0.0))
            total_score = base_score + relation_boosts.get(chunk_id, 0.0)
            if relation_boosts.get(chunk_id):
                reasons = reasons + [f"graph boost +{relation_boosts[chunk_id]:.1f}"]
            if total_score <= 0:
                continue
            reranked.append(RetrievalHit(chunk=chunk, score=total_score, matched_terms=matched_terms, reasons=reasons))
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    def _select_relevant_edges(self, hits: list[RetrievalHit]) -> list[GraphEdge]:
        selected_ids = {hit.chunk.chunk_id for hit in hits[:5]}
        relevant = [edge for edge in self.edges if edge.source in selected_ids and edge.target in selected_ids]
        relevant.sort(key=lambda item: item.weight, reverse=True)
        return relevant[:12]

    def _build_doc_freq(self, chunks: list[CodeChunk]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for chunk in chunks:
            tokens = chunk_tokens(chunk)
            for token in set(tokens):
                freq[token] = freq.get(token, 0) + 1
        return freq

    def _build_file_doc_freq(self, file_facts: list[FileFact]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for fact in file_facts:
            for token in set(file_fact_tokens(fact)):
                freq[token] = freq.get(token, 0) + 1
        return freq

    def _build_semantic_features(self, chunks: list[CodeChunk]) -> dict:
        documents = []
        for chunk in chunks:
            documents.append(chunk_tokens(chunk))
        df = Counter()
        for tokens in documents:
            df.update(set(tokens))
        candidate_terms = [
            term
            for term, count in df.items()
            if count >= 2 and count < max(2, int(len(documents) * 0.85)) and len(term) > 1
        ]
        candidate_terms.sort(key=lambda term: (-df[term], term))
        vocab_terms = candidate_terms[:512]
        if not vocab_terms:
            return {
                "vocab": {},
                "idf": np.zeros(0, dtype=float),
                "matrix": np.zeros((len(documents), 0), dtype=float),
                "latent": None,
                "basis": None,
                "chunk_ids": [chunk.chunk_id for chunk in chunks],
            }

        vocab = {term: index for index, term in enumerate(vocab_terms)}
        matrix = np.zeros((len(documents), len(vocab_terms)), dtype=float)
        idf = np.array(
            [math.log((len(documents) + 1) / (1 + df[term])) + 1.0 for term in vocab_terms],
            dtype=float,
        )
        for row, tokens in enumerate(documents):
            counts = Counter(tokens)
            for term, count in counts.items():
                if term in vocab:
                    matrix[row, vocab[term]] = count
        if matrix.size:
            matrix *= idf
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix = matrix / np.clip(norms, 1e-9, None)
        latent = None
        basis = None
        min_dim = min(matrix.shape) if matrix.size else 0
        if min_dim >= 3:
            u, s, vt = np.linalg.svd(matrix, full_matrices=False)
            k = min(24, min_dim - 1)
            latent = u[:, :k] * s[:k]
            latent_norms = np.linalg.norm(latent, axis=1, keepdims=True)
            latent = latent / np.clip(latent_norms, 1e-9, None)
            basis = vt[:k, :]
        return {
            "vocab": vocab,
            "idf": idf,
            "matrix": matrix,
            "latent": latent,
            "basis": basis,
            "chunk_ids": [chunk.chunk_id for chunk in chunks],
        }

    def _semantic_scores(self, query: str) -> dict[str, float]:
        if not self.semantic["vocab"]:
            return {}
        query_terms = expand_query_terms(query)
        q_vector = np.zeros(len(self.semantic["vocab"]), dtype=float)
        counts = Counter(query_terms)
        for term, count in counts.items():
            index = self.semantic["vocab"].get(term)
            if index is not None:
                q_vector[index] = count
        if not np.any(q_vector):
            return {}
        q_vector *= self.semantic["idf"]
        q_norm = np.linalg.norm(q_vector)
        if q_norm == 0:
            return {}
        q_vector = q_vector / q_norm
        tfidf_scores = self.semantic["matrix"] @ q_vector if self.semantic["matrix"].size else np.zeros(len(self.chunks))
        if self.semantic["latent"] is not None and self.semantic["basis"] is not None:
            q_latent = q_vector @ self.semantic["basis"].T
            latent_norm = np.linalg.norm(q_latent)
            if latent_norm > 0:
                q_latent = q_latent / latent_norm
                latent_scores = self.semantic["latent"] @ q_latent
                combined = 0.45 * tfidf_scores + 0.55 * latent_scores
            else:
                combined = tfidf_scores
        else:
            combined = tfidf_scores
        return {
            chunk_id: float(score)
            for chunk_id, score in zip(self.semantic["chunk_ids"], combined.tolist())
            if score > 0.01
        }

    @staticmethod
    def _group_file_chunks(chunks: list[CodeChunk]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for chunk in chunks:
            grouped[chunk.relpath].append(chunk.chunk_id)
        return grouped

    @staticmethod
    def _group_symbol_chunks(chunks: list[CodeChunk]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for chunk in chunks:
            if chunk.symbol_name:
                grouped[chunk.symbol_name.lower()].append(chunk.chunk_id)
        return grouped

    @staticmethod
    def _group_edges(edges: list[GraphEdge], reverse: bool) -> dict[str, list[GraphEdge]]:
        grouped: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in edges:
            key = edge.target if reverse else edge.source
            target = edge.source if reverse else edge.target
            grouped[key].append(GraphEdge(source=key, target=target, label=edge.label, weight=edge.weight))
        return grouped


def build_index(
    repo_root: Path,
    *,
    max_files: int | None = None,
    max_file_bytes: int | None = None,
) -> RepositoryIndex:
    repo_root = repo_root.resolve()
    chunks: list[CodeChunk] = []
    file_facts: list[FileFact] = []
    processed_files = 0
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        relpath = path.relative_to(repo_root).as_posix()
        if relpath_has_ignored_part(relpath):
            continue
        language = detect_language(path)
        if not language:
            continue
        if max_files is not None and processed_files >= max_files:
            break
        try:
            stat = path.stat()
        except OSError:
            continue
        if max_file_bytes is not None and stat.st_size > max_file_bytes:
            continue
        text = _safe_read(path)
        if not text.strip():
            continue
        processed_files += 1
        analysis = analyze_source(path, text)
        lines = text.splitlines()
        file_facts.append(
            FileFact(
                relpath=relpath,
                language=analysis.language,
                line_count=len(lines),
                imports=analysis.imports,
                symbol_names=[symbol.name for symbol in analysis.symbols if symbol.kind != "route"],
                routes=[symbol.route_path for symbol in analysis.symbols if symbol.route_path],
                roles=detect_file_roles(relpath, analysis.language, analysis.imports, text, analysis.symbols),
            )
        )
        for index, symbol in enumerate(analysis.symbols, start=1):
            snippet = "\n".join(lines[symbol.start_line - 1 : symbol.end_line]).strip()
            if len(snippet) < 8:
                continue
            chunks.append(
                CodeChunk(
                    chunk_id=f"{relpath}::{index}",
                    repo_root=repo_root,
                    relpath=relpath,
                    language=analysis.language,
                    text=snippet,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    symbol_name=symbol.name,
                    symbol_kind=symbol.kind,
                    metadata_tokens=tokenize(relpath) + tokenize(symbol.name) + tokenize(symbol.route_path) + [symbol.kind],
                    imports=analysis.imports,
                    calls=symbol.calls,
                    route_path=symbol.route_path,
                    handler_names=symbol.handler_names,
                )
            )
        chunks.append(
            CodeChunk(
                chunk_id=f"{relpath}::file",
                repo_root=repo_root,
                relpath=relpath,
                language=analysis.language,
                text="\n".join(lines[: min(len(lines), 140)]),
                start_line=1,
                end_line=min(len(lines), 140),
                metadata_tokens=tokenize(relpath) + ["file", analysis.language],
                imports=analysis.imports,
                calls=[symbol.name for symbol in analysis.symbols if symbol.kind != "route"],
            )
        )
    edges = _build_edges(chunks)
    return RepositoryIndex(repo_root, chunks, file_facts, edges)


def tokenize(text: str) -> list[str]:
    raw = str(text or "").replace("-", "_").replace("/", " ")
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    normalized = raw.lower()
    tokens = TOKEN_RE.findall(normalized)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token.lower())
        if "_" in token:
            expanded.extend(part for part in token.lower().split("_") if part)
    return expanded


def expand_query_terms(query: str) -> list[str]:
    base_terms = tokenize(query)
    expanded = list(base_terms)
    lowered = str(query or "").lower()
    for chinese_term, english_terms in QUERY_SYNONYMS.items():
        if chinese_term in query:
            expanded.append(chinese_term)
            expanded.extend(english_terms)
    if "rag" in lowered:
        expanded.extend(["rag", "retrieve", "document"])
    if "api" in lowered:
        expanded.extend(["route", "post", "get"])
    if "endpoint" in lowered or "route" in lowered:
        expanded.extend(["api", "handler", "post", "get"])
    if "handler" in lowered:
        expanded.extend(["handle", "function", "request"])
    if any(term in lowered for term in ("web", "frontend", "page", "ui", "browser")):
        expanded.extend(["web", "frontend", "html", "css", "ui", "page"])
    return list(dict.fromkeys(expanded))


def chunk_tokens(chunk: CodeChunk) -> list[str]:
    return (
        tokenize(chunk.text)
        + chunk.metadata_tokens
        + tokenize(chunk.route_path)
        + tokenize(" ".join(chunk.imports))
        + tokenize(" ".join(chunk.calls))
        + tokenize(" ".join(chunk.handler_names))
    )


def file_fact_tokens(fact: FileFact) -> list[str]:
    return (
        tokenize(fact.relpath)
        + tokenize(" ".join(fact.imports))
        + tokenize(" ".join(fact.symbol_names))
        + tokenize(" ".join(fact.routes))
        + fact.roles
        + [fact.language]
    )


def detect_file_roles(
    relpath: str,
    language: str,
    imports: list[str],
    text: str,
    symbols: list,
) -> list[str]:
    normalized = relpath.replace("\\", "/").lower()
    name = Path(normalized).name
    roles: list[str] = []

    if normalized.startswith("web/") or any(part in normalized for part in ("/components/", "/pages/", "/frontend/")):
        roles.append("frontend")
    if language == "html":
        roles.extend(["frontend", "page_shell"])
    if language == "css":
        roles.extend(["frontend", "styles"])
    if language in {"javascript", "typescript"} and normalized.startswith("web/"):
        roles.extend(["frontend", "frontend_logic"])
    if any(token in normalized for token in ("/api", "/routes", "server.", "controller", "handler")):
        roles.extend(["backend", "api"])
    if any(getattr(symbol, "kind", "") == "route" for symbol in symbols):
        roles.extend(["backend", "api", "entrypoint"])
    if name in {"main.py", "app.py", "server.py", "__main__.py", "server.js"}:
        roles.append("entrypoint")
    if any(token in normalized for token in ("config", ".env", "settings", "pyproject.toml", "package.json")):
        roles.append("config")
    if any(token in normalized for token in ("test", "spec", "__tests__")):
        roles.append("tests")
    if normalized.endswith((".md", ".rst")):
        roles.append("docs")
    if imports and language in {"html", "css"}:
        roles.append("asset_entry")
    if "render" in text.lower() and "document" in text.lower() and normalized.endswith(".py"):
        roles.append("reporting")

    return list(dict.fromkeys(roles))


def _build_edges(chunks: list[CodeChunk]) -> list[GraphEdge]:
    symbol_lookup: dict[str, list[CodeChunk]] = defaultdict(list)
    file_lookup: dict[str, list[CodeChunk]] = defaultdict(list)
    stem_lookup: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        file_lookup[chunk.relpath].append(chunk)
        stem_lookup[Path(chunk.relpath).stem.lower()].append(chunk.relpath)
        if chunk.symbol_name:
            symbol_lookup[chunk.symbol_name.lower()].append(chunk)

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, label: str, weight: float) -> None:
        key = (source, target, label)
        if source == target or key in seen:
            return
        seen.add(key)
        edges.append(GraphEdge(source=source, target=target, label=label, weight=weight))

    for chunk in chunks:
        for called in chunk.calls + chunk.handler_names:
            for target_chunk in symbol_lookup.get(called.lower(), []):
                weight = 2.6 if target_chunk.relpath == chunk.relpath else 1.8
                add_edge(chunk.chunk_id, target_chunk.chunk_id, "calls", weight)
        for import_name in chunk.imports:
            tail = import_name.replace("\\", "/").rstrip("/").split("/")[-1].lower()
            tail = Path(tail).stem.lower() or tail
            for relpath in stem_lookup.get(tail, []):
                for target_chunk in file_lookup.get(relpath, []):
                    if target_chunk.symbol_name == "":
                        add_edge(chunk.chunk_id, target_chunk.chunk_id, "imports", 1.4)
        if chunk.symbol_kind == "route":
            for handler_name in chunk.handler_names:
                for target_chunk in symbol_lookup.get(handler_name.lower(), []):
                    add_edge(chunk.chunk_id, target_chunk.chunk_id, "routes_to", 3.2)
    return edges


def _classify_mode(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in ("bug", "error", "缺陷", "错误", "报错", "故障", "异常", "500", "定位", "排查")):
        return "bug_localization"
    return "repository_qa"


def _safe_read(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return ""
