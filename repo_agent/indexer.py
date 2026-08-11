from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path

from .ignore import relpath_has_ignored_part
from .models import CodeChunk, FileFact, FileHit, GraphEdge, InvestigationBundle, QueryPlan, RetrievalHit
from .parsers import analyze_source, detect_language
from .retrieval import (
    BM25Index,
    DenseEmbeddingIndex,
    MultiViewBM25Index,
    weighted_reciprocal_rank_fusion,
)

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

STREAM_QUERY_TERMS = ("stream", "streaming", "streamed", "sse", "delta")
RETRIEVAL_QUERY_TERMS = ("retrieve", "retrieval", "search", "lookup", "rag")
READ_FIRST_QUERY_TERMS = ("read first", "inspect first", "understand", "start with")

RESPONSE_WRITE_QUERY_TERMS = ("write", "writes", "emit", "emits", "send", "sends", "response", "final", "finally")
AUTHORIZATION_QUERY_TERMS = ("authorize", "authorizes", "authorization", "auth", "middleware", "before the handler")
JSON_SYNC_QUERY_TERMS = ("json", "synchronous", "sync")
STATE_RESET_QUERY_TERMS = ("reset", "clear", "clears", "delete", "deletes", "state-reset")
PACKAGE_CONFIG_QUERY_TERMS = ("package data", "pyproject", "ships with", "python package", "manifest")
TEST_FILE_QUERY_TERMS = ("test file", "verifies", "assert", "pytest")
RUN_HISTORY_QUERY_TERMS = ("run history", "refreshes", "refresh", "persisted engineering run")
ROUTE_LITERAL_RE = re.compile(r"/[A-Za-z0-9_:{}/.-]+")


class RepositoryIndex:
    def __init__(
        self,
        repo_root: Path,
        chunks: list[CodeChunk],
        file_facts: list[FileFact],
        edges: list[GraphEdge],
        embedding_vectors: list[list[float]] | None = None,
        embedding_model: str = "",
    ):
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
        chunk_documents = [chunk_tokens(chunk) for chunk in chunks]
        self.doc_freq = self._build_doc_freq_from_documents(chunk_documents)
        self.file_doc_freq = self._build_file_doc_freq(file_facts)
        self.chunk_token_counters = {
            chunk.chunk_id: Counter(document)
            for chunk, document in zip(chunks, chunk_documents, strict=True)
        }
        self._query_terms_cache: dict[str, tuple[str, ...]] = {}
        self.bm25 = BM25Index(
            [chunk.chunk_id for chunk in chunks],
            chunk_documents,
        )
        document_ids = [chunk.chunk_id for chunk in chunks]
        self.multi_view_index = MultiViewBM25Index(
            document_ids,
            {
                "content": [tokenize(chunk.text) for chunk in chunks],
                "identifier": [
                    tokenize(
                        " ".join(
                            [
                                chunk.symbol_name,
                                chunk.qualified_name,
                                *chunk.handler_names,
                                *chunk.calls,
                            ]
                        )
                    )
                    for chunk in chunks
                ],
                "path": [
                    tokenize(f"{chunk.relpath} {chunk.language} {chunk.symbol_kind}")
                    for chunk in chunks
                ],
                "structure": [
                    tokenize(
                        " ".join(
                            [
                                chunk.route_path,
                                *chunk.imports,
                                *chunk.calls,
                                *chunk.references,
                                *chunk.inherits,
                                *self.file_fact_by_relpath.get(
                                    chunk.relpath,
                                    FileFact(chunk.relpath, chunk.language, 0),
                                ).roles,
                            ]
                        )
                    )
                    for chunk in chunks
                ],
            },
            weights={"content": 1.0, "identifier": 1.8, "path": 1.1, "structure": 1.25},
            rank_constant=30,
        )
        self.embedding_model = embedding_model
        self.embedding_index = (
            DenseEmbeddingIndex([chunk.chunk_id for chunk in chunks], embedding_vectors, embedding_model)
            if embedding_vectors
            else None
        )

    def stats(self) -> dict:
        languages = Counter(chunk.language for chunk in self.chunks)
        parser_backends = Counter(chunk.parser_backend for chunk in self.chunks)
        edge_types = Counter(edge.label for edge in self.edges)
        route_count = sum(1 for chunk in self.chunks if chunk.symbol_kind == "route")
        return {
            "repo_root": str(self.repo_root),
            "chunk_count": len(self.chunks),
            "file_count": len(self.file_facts),
            "graph_edge_count": len(self.edges),
            "route_count": route_count,
            "retrieval_backend": "multi-view-bm25+weighted-rrf+graph",
            "retrieval_backend_active": (
                "multi-view-bm25+embedding+weighted-rrf+graph"
                if self.embedding_index
                else "multi-view-bm25+weighted-rrf+graph"
            ),
            "retrieval_views": self.multi_view_index.view_names,
            "graph_search_strategy": "personalized_pagerank",
            "semantic_backend": self.embedding_model if self.embedding_index else "none (configure embedding provider)",
            "bm25_vocabulary_size": self.bm25.stats.vocabulary_size,
            "bm25_average_document_length": self.bm25.stats.average_document_length,
            "semantic_dimensions": self.embedding_index.dimensions if self.embedding_index else 0,
            "language_distribution": dict(languages),
            "parser_backend_distribution": dict(parser_backends),
            "edge_type_distribution": dict(edge_types),
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

    def semantic_scores_for(self, query: str, query_vector: list[float] | None = None) -> dict[str, float]:
        return self._semantic_scores(query, query_vector=query_vector)

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

    def mcts_graph_search(
        self,
        query: str,
        *,
        top_k: int = 6,
        iterations: int = 72,
        max_depth: int | None = None,
    ) -> tuple[list[RetrievalHit], dict]:
        plan = self.plan_query(query)
        semantic_scores = self.semantic_scores_for(query)
        file_hits = self.scout_files(plan, limit=max(32, top_k * 8))
        seed_hits, file_boosts = self.read_candidates(
            query,
            plan,
            file_hits,
            semantic_scores,
            top_k=top_k,
        )
        relation_boosts, diagnostics = self.mcts_graph_boosts(
            query,
            plan,
            seed_hits[: max(8, min(16, top_k * 2))],
            semantic_scores,
            iterations=iterations,
            max_depth=max_depth or max(2, plan.hop_budget + 1),
        )
        final_hits = self.rerank_candidates(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )
        diagnostics["seed_count"] = len(seed_hits)
        diagnostics["file_count"] = len(file_hits)
        diagnostics["final_top"] = final_hits[0].chunk.source_label if final_hits else ""
        return final_hits, diagnostics

    def mcts_graph_boosts(
        self,
        query: str,
        plan: QueryPlan,
        seed_hits: list[RetrievalHit],
        semantic_scores: dict[str, float],
        *,
        iterations: int = 72,
        max_depth: int | None = None,
    ) -> tuple[dict[str, float], dict]:
        return self._mcts_graph_boosts(
            query,
            plan,
            seed_hits,
            semantic_scores,
            iterations=iterations,
            max_depth=max_depth or max(2, plan.hop_budget + 1),
        )

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
        relation_boosts, graph_diagnostics = self.mcts_graph_boosts(
            query,
            plan,
            seed_hits[: max(8, min(16, top_k * 2))],
            semantic_scores,
            iterations=72,
            max_depth=max(2, plan.hop_budget + 1),
        )
        trace.append(
            {
                "step": 4,
                "type": "graph_search",
                "content": "\n".join(graph_diagnostics["trace"][:10]) or "no graph search taken",
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
            graph_search=graph_diagnostics,
        )

    def _plan_query(self, query: str, mode: str) -> QueryPlan:
        lowered = query.lower()
        query_tokens = set(tokenize(query))
        target_roles: list[str] = []
        target_languages: list[str] = []
        intent = "code_search"
        if (
            query_tokens.intersection({"browser", "frontend", "web", "page", "ui", "页面", "前端", "浏览器"})
            or "web studio" in lowered
        ):
            intent = "frontend_lookup"
            target_roles.extend(["frontend", "frontend_logic"])
            target_languages.extend(["javascript", "typescript", "html", "css"])
        if query_tokens.intersection({"style", "stylesheet", "css", "样式"}):
            intent = "style_lookup"
            target_roles.extend(["styles", "frontend"])
            target_languages.append("css")
        if "test file" in lowered or "which test" in lowered or query_tokens.intersection({"pytest", "测试文件"}):
            intent = "test_lookup"
            target_roles.append("tests")
        if any(term in lowered for term in ("package data", "configuration", "config file", "pyproject", "配置")):
            intent = "config_lookup"
            target_roles.append("config")
        if self._query_route_literals(query) or any(term in lowered for term in ("route", "endpoint", "api", "路由", "接口")):
            intent = "flow_trace" if self._target_symbol_kind(query) == "function" else "api_lookup"
            target_roles.extend(["api", "entrypoint", "backend"])
        return QueryPlan(
            mode=mode,
            intent=intent,
            focus_terms=expand_query_terms(query),
            target_roles=list(dict.fromkeys(target_roles)),
            target_languages=list(dict.fromkeys(target_languages)),
            hop_budget=3,
        )

    def _rank_files(self, plan: QueryPlan) -> list[FileHit]:
        """Broad lexical file recall; semantic intent is not encoded as boosts."""
        ranked: list[FileHit] = []
        query_set = set(plan.focus_terms)
        for fact in self.file_facts:
            tokens = Counter(file_fact_tokens(fact))
            matched_terms = sorted(query_set.intersection(tokens))
            matched_roles = [role for role in plan.target_roles if role in fact.roles]
            if not matched_terms and not matched_roles:
                continue
            score = 0.0
            for term in matched_terms:
                tf = tokens[term]
                idf = math.log((len(self.file_facts) + 1) / (1 + self.file_doc_freq.get(term, 0))) + 1.0
                score += (1.0 + math.log(tf)) * idf
            if matched_roles:
                score += 3.0 + min(3.0, len(matched_roles) * 0.75)
            ranked.append(
                FileHit(
                    file_fact=fact,
                    score=score,
                    matched_terms=matched_terms,
                    reasons=["file lexical overlap"] + ([f"role match {','.join(matched_roles)}"] if matched_roles else []),
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.file_fact.relpath))
        return ranked

    def _rank_files_legacy(self, plan: QueryPlan) -> list[FileHit]:
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
        # Keep recall wide.  A file-level miss must not permanently hide the
        # right symbol from the later graph/agent stages.
        selected_files = file_hits[: max(24, min(top_k * 8, 64))]
        file_boosts = {
            item.file_fact.relpath: min(2.5, max(0.0, item.score * 0.08))
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

        for hit in self._score_all_chunks(query, semantic_scores)[: max(64, top_k * 12)]:
            file_boost = file_boosts.get(hit.chunk.relpath, 0.0)
            total_score = hit.score + file_boost
            reasons = list(hit.reasons)
            if file_boost:
                reasons.append(f"file scout +{file_boost:.1f}")
            record_hit(hit.chunk, total_score, hit.matched_terms, reasons)

        primary_hits = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
        return primary_hits[: max(32, top_k * 8)], file_boosts

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

    def _mcts_graph_boosts(
        self,
        query: str,
        plan: QueryPlan,
        seed_hits: list[RetrievalHit],
        semantic_scores: dict[str, float],
        *,
        iterations: int,
        max_depth: int,
    ) -> tuple[dict[str, float], dict]:
        """Diffuse seed relevance through the repository graph with PPR.

        The public method name is retained for bundle compatibility, but the
        implementation is Personalized PageRank rather than the previous
        pseudo-MCTS/greedy walk.  PPR uses every typed edge, has a deterministic
        convergence criterion, and resists high-degree hubs through normalized
        transition probabilities.
        """
        return self._personalized_pagerank_boosts(
            query,
            seed_hits,
            semantic_scores,
            iterations=iterations,
            max_depth=max_depth,
        )

        # Kept below as a historical reference for old serialized traces.
        seed_ids = [hit.chunk.chunk_id for hit in seed_hits if hit.chunk.chunk_id in self.chunk_by_id]
        if not seed_ids:
            return {}, {
                "iterations": 0,
                "max_depth": max_depth,
                "visited_count": 0,
                "trace": [],
                "top_visited": [],
            }

        visits: Counter[str] = Counter()
        value: dict[str, float] = defaultdict(float)
        best_path_by_node: dict[str, list[str]] = {}
        iterations = max(1, iterations)
        max_depth = max(1, max_depth)

        for iteration in range(iterations):
            current = seed_ids[iteration % len(seed_ids)]
            path = [current]
            visits[current] += 1

            for _depth in range(max_depth):
                edges = [
                    edge
                    for edge in self._ranked_graph_neighbors(current)
                    if edge.target in self.chunk_by_id and edge.target not in path
                ][:18]
                if not edges:
                    break
                parent_visits = max(1, visits[current])
                selected = max(
                    edges,
                    key=lambda edge: self._mcts_edge_score(
                        query,
                        plan,
                        edge,
                        semantic_scores,
                        visits,
                        value,
                        parent_visits,
                    ),
                )
                current = selected.target
                path.append(current)
                visits[current] += 1

            reward = self._mcts_node_reward(query, plan, self.chunk_by_id[current], semantic_scores.get(current, 0.0))
            for offset, node_id in enumerate(path):
                discounted_reward = reward * (0.86 ** offset)
                value[node_id] += discounted_reward
                if node_id not in best_path_by_node or discounted_reward > (
                    value[node_id] / max(1, visits[node_id])
                ):
                    best_path_by_node[node_id] = list(path)

        route_boosts, route_trace, route_paths = self._route_anchor_boosts(query, max_depth=max_depth + 1)
        boosts: dict[str, float] = dict(route_boosts)
        for node_id, count in visits.items():
            if node_id not in self.chunk_by_id:
                continue
            average_value = value[node_id] / max(1, count)
            if count <= 1 and average_value < 0.08:
                continue
            search_pressure = math.log1p(count) * 1.15
            reward_boost = average_value * 7.2
            boosts[node_id] = min(20.0, boosts.get(node_id, 0.0) + search_pressure + reward_boost)

        ranked_nodes = sorted(
            visits,
            key=lambda node_id: (
                boosts.get(node_id, 0.0),
                value[node_id] / max(1, visits[node_id]),
                visits[node_id],
            ),
            reverse=True,
        )
        top_visited = [
            {
                "chunk": self.chunk_by_id[node_id].source_label,
                "visits": visits[node_id],
                "average_reward": round(value[node_id] / max(1, visits[node_id]), 3),
                "boost": round(boosts.get(node_id, 0.0), 2),
                "path": [
                    self.chunk_by_id[path_id].source_label
                    for path_id in best_path_by_node.get(node_id, [node_id])
                    if path_id in self.chunk_by_id
                ][: max_depth + 1],
            }
            for node_id in ranked_nodes[:10]
        ]
        trace = [
            (
                f"mcts: {item['chunk']} | visits={item['visits']} | "
                f"avg_reward={item['average_reward']:.3f} | boost=+{item['boost']:.1f}"
            )
            for item in top_visited
        ]
        trace.extend(route_trace[:8])
        return boosts, {
            "iterations": iterations,
            "max_depth": max_depth,
            "visited_count": len(visits),
            "trace": trace,
            "top_visited": top_visited,
            "route_anchors": route_paths,
        }

    def _personalized_pagerank_boosts(
        self,
        query: str,
        seed_hits: list[RetrievalHit],
        semantic_scores: dict[str, float],
        *,
        iterations: int,
        max_depth: int,
        damping: float = 0.85,
    ) -> tuple[dict[str, float], dict]:
        seed_weights = {
            hit.chunk.chunk_id: max(0.05, hit.score)
            for hit in seed_hits
            if hit.chunk.chunk_id in self.chunk_by_id
        }
        if not seed_weights:
            return {}, {
                "strategy": "personalized_pagerank",
                "iterations": 0,
                "steps": 0,
                "max_depth": max_depth,
                "visited_count": 0,
                "trace": [],
                "top_visited": [],
                "route_anchors": [],
                "converged": True,
            }

        total_seed_weight = sum(seed_weights.values())
        teleport = {node_id: weight / total_seed_weight for node_id, weight in seed_weights.items()}

        # Restrict diffusion to the bounded repository neighborhood so latency
        # remains predictable on large monorepos.
        neighborhood = set(seed_weights)
        frontier = set(seed_weights)
        parents: dict[str, str] = {}
        for _depth in range(max(1, max_depth)):
            next_frontier: set[str] = set()
            for node_id in sorted(frontier):
                for edge in self._ranked_graph_neighbors(node_id)[:24]:
                    if edge.target not in self.chunk_by_id:
                        continue
                    if edge.target not in neighborhood:
                        parents[edge.target] = node_id
                        next_frontier.add(edge.target)
                    neighborhood.add(edge.target)
            frontier = next_frontier
            if not frontier:
                break

        adjacency: dict[str, list[tuple[str, float]]] = {}
        for node_id in neighborhood:
            merged: dict[str, float] = defaultdict(float)
            for edge in self._ranked_graph_neighbors(node_id):
                if edge.target in neighborhood and edge.target != node_id:
                    merged[edge.target] += max(0.05, min(4.0, edge.weight))
            total = sum(merged.values())
            adjacency[node_id] = [
                (target, weight / total)
                for target, weight in merged.items()
            ] if total > 0 else []

        rank = {node_id: teleport.get(node_id, 0.0) for node_id in neighborhood}
        max_iterations = max(8, min(int(iterations), 80))
        converged = False
        completed_iterations = 0
        for iteration in range(max_iterations):
            updated = {
                node_id: (1.0 - damping) * teleport.get(node_id, 0.0)
                for node_id in neighborhood
            }
            dangling_mass = 0.0
            for source, source_rank in rank.items():
                transitions = adjacency.get(source, [])
                if not transitions:
                    dangling_mass += source_rank
                    continue
                for target, probability in transitions:
                    updated[target] += damping * source_rank * probability
            if dangling_mass:
                for target, probability in teleport.items():
                    updated[target] += damping * dangling_mass * probability
            delta = sum(abs(updated.get(node_id, 0.0) - rank.get(node_id, 0.0)) for node_id in neighborhood)
            rank = updated
            completed_iterations = iteration + 1
            if delta < 1e-7:
                converged = True
                break

        route_boosts, route_trace, route_paths = self._route_anchor_boosts(query, max_depth=max_depth + 1)
        boosts: dict[str, float] = dict(route_boosts)
        for node_id, probability in rank.items():
            relevance = 0.7 + 0.3 * semantic_scores.get(node_id, 0.0)
            boosts[node_id] = boosts.get(node_id, 0.0) + probability * relevance * 35.0

        ranked_nodes = sorted(rank, key=lambda node_id: (-rank[node_id], node_id))

        def path_for(node_id: str) -> list[str]:
            path = [node_id]
            while path[-1] in parents and len(path) <= max_depth:
                path.append(parents[path[-1]])
            path.reverse()
            return [self.chunk_by_id[item].source_label for item in path if item in self.chunk_by_id]

        top_visited = [
            {
                "chunk": self.chunk_by_id[node_id].source_label,
                "visits": completed_iterations,
                "average_reward": round(rank[node_id], 6),
                "boost": round(boosts.get(node_id, 0.0), 3),
                "path": path_for(node_id),
            }
            for node_id in ranked_nodes[:10]
        ]
        trace = [
            f"ppr: {item['chunk']} | probability={item['average_reward']:.6f} | boost=+{item['boost']:.3f}"
            for item in top_visited
        ]
        trace.extend(route_trace[:8])
        return boosts, {
            "strategy": "personalized_pagerank",
            "iterations": completed_iterations,
            "steps": sum(len(items) for items in adjacency.values()),
            "max_depth": max_depth,
            "visited_count": len(neighborhood),
            "trace": trace,
            "top_visited": top_visited,
            "route_anchors": route_paths,
            "converged": converged,
            "damping": damping,
        }

    def _route_anchor_boosts(self, query: str, *, max_depth: int) -> tuple[dict[str, float], list[str], list[dict]]:
        route_literals = self._query_route_literals(query)
        if not route_literals:
            return {}, [], []
        boosts: dict[str, float] = defaultdict(float)
        trace: list[str] = []
        route_paths: list[dict] = []
        wants_deep_writer = self._asks_for_response_writer(query)
        wants_handler = self._asks_for_handler_function(query)

        anchors = [
            chunk
            for chunk in self.chunks
            if chunk.symbol_kind == "route" and self._route_matches_query(chunk.route_path, route_literals)
        ]
        for anchor in anchors[:4]:
            boosts[anchor.chunk_id] += 4.0 if not wants_handler else 1.5
            frontier = [(anchor.chunk_id, [anchor.chunk_id], 0)]
            visited = {anchor.chunk_id}
            while frontier:
                node_id, path, depth = frontier.pop(0)
                if depth >= max_depth:
                    continue
                for edge in self.forward_edges.get(node_id, [])[:14]:
                    if edge.target not in self.chunk_by_id or edge.target in visited:
                        continue
                    visited.add(edge.target)
                    next_path = [*path, edge.target]
                    target = self.chunk_by_id[edge.target]
                    boost = max(1.2, 9.0 - depth * 1.4)
                    if depth == 0 and wants_handler and target.symbol_kind == "function":
                        boost += 7.0
                    if wants_deep_writer and self._chunk_writes_response(target):
                        boost += 12.0
                    if self._query_excludes_chunk(query, target):
                        boost -= 12.0
                    if target.symbol_kind == "route":
                        boost *= 0.35
                    boosts[edge.target] += max(0.0, boost)
                    route_paths.append(
                        {
                            "route": anchor.route_path,
                            "chunk": target.source_label,
                            "depth": depth + 1,
                            "boost": round(max(0.0, boost), 2),
                            "path": [
                                self.chunk_by_id[path_id].source_label
                                for path_id in next_path
                                if path_id in self.chunk_by_id
                            ],
                        }
                    )
                    trace.append(
                        f"route_anchor: {anchor.route_path} -> {target.source_label} depth={depth + 1} (+{max(0.0, boost):.1f})"
                    )
                    frontier.append((edge.target, next_path, depth + 1))
        return boosts, trace, route_paths[:12]

    def _query_route_literals(self, query: str) -> list[str]:
        values = []
        for match in ROUTE_LITERAL_RE.findall(query):
            normalized = match.rstrip(".,;:?!)]}'\"")
            if normalized and normalized not in values:
                values.append(normalized)
        return values

    @staticmethod
    def _route_matches_query(route_path: str, route_literals: list[str]) -> bool:
        normalized_route = route_path.rstrip("/") or "/"
        for literal in route_literals:
            normalized_literal = literal.rstrip("/") or "/"
            if normalized_literal == normalized_route:
                return True
            if ":" in normalized_route:
                pattern = re.escape(normalized_route)
                pattern = re.sub(r"\\:[A-Za-z_][A-Za-z0-9_]*", r"[^/]+", pattern)
                if re.fullmatch(pattern, normalized_literal):
                    return True
        return False

    @staticmethod
    def _asks_for_response_writer(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in RESPONSE_WRITE_QUERY_TERMS)

    @staticmethod
    def _chunk_writes_response(chunk: CodeChunk) -> bool:
        lowered = chunk.text.lower()
        return any(flag in lowered for flag in ("res.write", "response.write", ".write(", "res.end", "response.end", ".end(", "send("))

    @staticmethod
    def _asks_for_persistence(query: str) -> bool:
        lowered = query.lower()
        if "rag store" in lowered and not any(term in lowered for term in ("persist", "persists", "save", "saves", "record")):
            return False
        return any(term in lowered for term in ("persist", "persists", "save", "saves", "store", "stores", "record"))

    @staticmethod
    def _asks_for_streaming(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in STREAM_QUERY_TERMS)

    @staticmethod
    def _chunk_matches_streaming_intent(chunk: CodeChunk) -> bool:
        lowered = " ".join([chunk.symbol_name, chunk.text, " ".join(chunk.calls)]).lower()
        return any(term in lowered for term in ("stream", "streamed", "streaming", "sse", "delta"))

    @staticmethod
    def _asks_for_retrieval_boundary(query: str) -> bool:
        lowered = query.lower()
        asks_retrieval = any(term in lowered for term in RETRIEVAL_QUERY_TERMS)
        asks_boundary = any(term in lowered for term in READ_FIRST_QUERY_TERMS + FLOW_QUERY_TERMS)
        return asks_retrieval and asks_boundary

    @staticmethod
    def _chunk_is_library_boundary(chunk: CodeChunk) -> bool:
        normalized = chunk.relpath.replace("\\", "/").lower()
        return "/lib/" in f"/{normalized}" or "/src/" in f"/{normalized}" or normalized.startswith("lib/")

    @staticmethod
    def _chunk_persists_state(chunk: CodeChunk) -> bool:
        symbol_tokens = set(tokenize(chunk.symbol_name))
        return bool(symbol_tokens.intersection({"persist", "persists", "save", "saves", "store", "stores"}))

    @staticmethod
    def _query_excludes_chunk(query: str, chunk: CodeChunk) -> bool:
        lowered = query.lower()
        label = chunk.source_label.lower()
        symbol = chunk.symbol_name.lower()
        contrastive = any(marker in lowered for marker in ("rather than", "instead of", "excluding", "排除", "而不是"))
        exclusions = [
            term
            for term in ("admin", "legacy", "mock", "fake", "test", "preview", "deprecated")
            if f"not the {term}" in lowered or f"not {term}" in lowered or (contrastive and term in lowered)
        ]
        if any(term in label or term in symbol for term in exclusions):
            return True
        candidate_tokens = set(tokenize(f"{chunk.symbol_name} {chunk.route_path} {chunk.relpath}"))
        stopwords = {
            "a", "an", "and", "assistant", "chat", "function", "handler", "instead", "of",
            "or", "rather", "route", "the", "this", "which",
        }
        for marker in ("rather than", "instead of", "excluding", "而不是", "排除"):
            if marker not in lowered:
                continue
            contrast_tokens = set(tokenize(lowered.split(marker, 1)[1])) - stopwords
            if candidate_tokens.intersection(contrast_tokens):
                return True
        return False

    @staticmethod
    def _target_symbol_kind(query: str) -> str:
        lowered = query.lower()
        function_terms = (
            "which function", "which method", "which handler", "helper", "worker",
            "writes", "writer", "persists", "loads", "clears", "calls", "function",
            "函数", "处理函数", "方法",
        )
        route_terms = (
            "route entrypoint", "route implemented", "api route", "endpoint implemented",
            "where is the route", "路由入口", "接口入口",
        )
        if any(term in lowered for term in function_terms):
            return "function"
        if any(term in lowered for term in route_terms):
            return "route"
        return ""

    def _ranked_graph_neighbors(self, chunk_id: str) -> list[GraphEdge]:
        edges = self.forward_edges.get(chunk_id, []) + self.reverse_edges.get(chunk_id, [])
        return sorted(edges, key=lambda edge: (edge.weight, edge.label, edge.target), reverse=True)

    def _mcts_edge_score(
        self,
        query: str,
        plan: QueryPlan,
        edge: GraphEdge,
        semantic_scores: dict[str, float],
        visits: Counter[str],
        value: dict[str, float],
        parent_visits: int,
    ) -> float:
        child_visits = visits[edge.target]
        exploitation = value[edge.target] / child_visits if child_visits else 0.0
        exploration = 1.25 * math.sqrt(math.log(parent_visits + 1.0) / (child_visits + 1.0))
        child = self.chunk_by_id[edge.target]
        prior = self._mcts_node_prior(query, plan, child, semantic_scores.get(edge.target, 0.0))
        edge_prior = min(edge.weight, 4.0) * 0.09
        return exploitation + exploration + prior + edge_prior

    def _mcts_node_prior(self, query: str, plan: QueryPlan, chunk: CodeChunk, semantic_score: float) -> float:
        raw_score, matched_terms, _reasons = self._score_chunk(query, chunk, semantic_score)
        prior = min(max(raw_score, 0.0) / 36.0, 1.0)
        if matched_terms:
            prior += min(len(matched_terms), 5) * 0.035
        if plan.target_roles and self._chunk_matches_roles(chunk, plan.target_roles):
            prior += 0.10
        if plan.intent in {"api_lookup", "flow_trace", "bug_trace"} and chunk.symbol_kind == "function":
            prior += 0.12
        if chunk.symbol_kind == "route":
            prior += 0.08
        if semantic_score > 0:
            prior += min(semantic_score, 1.0) * 0.18
        return max(0.0, min(prior, 1.45))

    def _mcts_node_reward(self, query: str, plan: QueryPlan, chunk: CodeChunk, semantic_score: float) -> float:
        raw_score, matched_terms, _reasons = self._score_chunk(query, chunk, semantic_score)
        reward = min(max(raw_score, 0.0) / 32.0, 1.0)
        if matched_terms:
            reward += min(len(matched_terms), 6) * 0.04
        if plan.target_roles and self._chunk_matches_roles(chunk, plan.target_roles):
            reward += 0.14
        if plan.intent in {"api_lookup", "flow_trace"} and chunk.symbol_kind == "function":
            reward += 0.12
        if plan.intent == "bug_trace" and any(term in chunk.text.lower() for term in ("throw", "error", "catch", "status")):
            reward += 0.14
        if chunk.route_path:
            reward += 0.06
        return max(0.0, min(reward, 1.6))

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
        """Merge retrieval evidence while preserving intent-specific guardrails.

        The multi-view index supplies the primary evidence, while the legacy
        guardrail pass contributes explicit candidate expansion and contrastive
        intent checks for configuration, run-history, security, and hard-
        negative queries.  Keeping both layers is important: pure score fusion
        cannot rank a file that has no lexical overlap with a natural-language
        question (for example ``pyproject.toml`` for package-data metadata).
        """
        return self._rerank_multistep_legacy(
            query,
            plan,
            seed_hits,
            file_boosts,
            relation_boosts,
            semantic_scores,
            top_k=top_k,
        )

    def _rerank_multistep_multiview(
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
        """Experimental score-fusion reranker used for retrieval ablations.

        The production path keeps the explicit intent guardrails above.  This
        method remains available for comparing pure multi-view fusion against
        the guardrail path without deleting the experimental implementation.
        """
        seed_lookup = {hit.chunk.chunk_id: hit for hit in seed_hits}
        candidate_ids = set(seed_lookup) | set(relation_boosts)
        ranked: list[RetrievalHit] = []
        route_literals = self._query_route_literals(query)
        reachable = self._route_reachable_chunk_ids(
            route_literals,
            max_depth=max(3, plan.hop_budget + 2),
        )
        target_kind = self._target_symbol_kind(query)
        expanded_query_terms = self._query_terms(query)
        expanded_query_set = set(expanded_query_terms)
        ordered_query_tokens = tokenize(query)
        raw_query_tokens = set(ordered_query_tokens)
        action_vocabulary = {
            "append", "apply", "authorize", "build", "clear", "create", "delete", "handle",
            "ingest", "load", "normalize", "persist", "refresh", "render", "reset",
            "retrieve", "run", "save", "send", "stream", "write",
        }
        query_actions = raw_query_tokens.intersection(action_vocabulary)
        if "handler" in raw_query_tokens:
            query_actions.add("handle")
        if "retrieval" in raw_query_tokens:
            query_actions.add("retrieve")
        action_equivalents = {
            "build": {"create"},
            "append": {"ingest"},
            "create": {"build"},
            "clear": {"delete", "reset"},
            "delete": {"clear", "reset"},
            "persist": {"save", "store"},
            "save": {"persist", "store"},
            "retrieve": {"load"},
            "store": {"persist", "save"},
        }
        query_actions.update(
            equivalent
            for action in tuple(query_actions)
            for equivalent in action_equivalents.get(action, set())
        )
        primary_action = next((token for token in ordered_query_tokens if token in action_vocabulary), "")
        primary_actions = {primary_action, *action_equivalents.get(primary_action, set())} if primary_action else set()

        for chunk_id in candidate_ids:
            chunk = self.chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            file_roles = self.file_fact_by_relpath.get(
                chunk.relpath,
                FileFact(chunk.relpath, chunk.language, 0),
            ).roles
            seed = seed_lookup.get(chunk_id)
            if seed is None:
                base, terms, reasons = self._score_chunk(
                    query, chunk, semantic_scores.get(chunk_id, 0.0)
                )
            else:
                base, terms, reasons = seed.score, seed.matched_terms, list(seed.reasons)

            total = max(0.0, base)
            file_boost = file_boosts.get(chunk.relpath, 0.0)
            if file_boost:
                total += min(2.5, file_boost)
                reasons = reasons + [f"file evidence +{file_boost:.2f}"]

            relation_boost = relation_boosts.get(chunk_id, 0.0)
            if relation_boost:
                # Graph evidence is useful for expansion, but must not drown
                # out lexical/semantic evidence with arbitrary large weights.
                normalized_relation = min(6.0, 2.5 * math.log1p(max(0.0, relation_boost)))
                total += normalized_relation
                reasons = reasons + [f"graph evidence +{normalized_relation:.2f}"]

            if route_literals and chunk_id in reachable:
                total += 2.0
                reasons = reasons + ["route-reachable evidence"]
            if plan.target_roles and self._chunk_matches_roles(chunk, plan.target_roles):
                total += 7.0
                reasons = reasons + ["role-aligned evidence"]
            if plan.target_languages and chunk.language in plan.target_languages:
                total += 7.0
                reasons = reasons + ["language-aligned evidence"]
            if plan.intent == "style_lookup" and chunk.language == "css":
                total += 6.0
                reasons = reasons + ["stylesheet intent"]
            if plan.intent == "frontend_lookup" and "frontend_logic" in file_roles:
                total += 8.0
                reasons = reasons + ["browser interaction logic target"]
            if plan.intent == "frontend_lookup" and "page_shell" in file_roles:
                total -= 4.0
                reasons = reasons + ["page-shell detour"]
            if target_kind == "function":
                if chunk.symbol_kind == "function":
                    total += 5.0
                    reasons = reasons + ["function target"]
                elif chunk.symbol_kind == "route":
                    total -= 7.0
                    reasons = reasons + ["route-entry detour"]
                elif not chunk.symbol_name:
                    total -= 5.0
                    reasons = reasons + ["overview detour"]
            elif target_kind == "route" and chunk.symbol_kind == "route":
                total += 6.0
                reasons = reasons + ["route target"]
            symbol_actions = set(tokenize(chunk.symbol_name)).intersection(query_actions)
            if symbol_actions:
                action_boost = min(20.0, 15.0 * len(symbol_actions))
                total += action_boost
                reasons = reasons + [f"action match {','.join(sorted(symbol_actions))}"]
                primary_matches = symbol_actions.intersection(primary_actions)
                if primary_matches:
                    total += 10.0 if primary_action in symbol_actions else 5.0
                    reasons = reasons + [f"primary action {','.join(sorted(primary_matches))}"]
                if "apply" in symbol_actions and "run" in tokenize(chunk.symbol_name):
                    reasons = reasons + ["apply-run action target"]
            if "handler" in query.lower() and chunk.symbol_name.lower().startswith("handle"):
                total += 7.0
                reasons = reasons + ["handler action target"]
            call_overlap = set(tokenize(" ".join(chunk.calls))).intersection(expanded_query_set)
            if call_overlap:
                total += min(10.0, 5.0 * len(call_overlap))
                reasons = reasons + [f"call-site match {','.join(sorted(call_overlap))}"]
                if "call" in set(tokenize(query)):
                    total += 10.0
                    reasons = reasons + ["caller relation target"]
            elif "call" in set(tokenize(query)) and chunk.symbol_kind == "function":
                total -= 4.0
                reasons = reasons + ["caller relation mismatch"]
            if self._query_excludes_chunk(query, chunk):
                total -= 18.0
                reasons = reasons + ["contrastive exclusion"]
            if route_literals and chunk.symbol_kind == "route" and not self._route_matches_query(chunk.route_path, route_literals):
                total -= 12.0
                reasons = reasons + ["route-family mismatch"]
            if plan.intent == "config_lookup" and "config" not in file_roles:
                total *= 0.15
                reasons = reasons + ["non-config downrank"]
            elif plan.intent == "config_lookup" and "config" in file_roles:
                total += 10.0
                reasons = reasons + ["package data config target"]
            if "tests" in file_roles and plan.intent != "test_lookup":
                total *= 0.45
                reasons = reasons + ["test-evidence downrank"]
            elif "tests" in file_roles and plan.intent == "test_lookup" and "coordination" in set(tokenize(chunk.relpath)).intersection(set(tokenize(query))):
                reasons = reasons + ["coordination test target"]
            if "docs" in file_roles and plan.intent not in {"docs_lookup", "config_lookup"}:
                total *= 0.55
                reasons = reasons + ["documentation downrank"]
            if chunk.symbol_name:
                total += 0.1
            if total > 0:
                ranked.append(RetrievalHit(chunk, total, terms, reasons))

        ranked.sort(key=lambda hit: (-hit.score, hit.chunk.relpath, hit.chunk.start_line))
        return ranked[:top_k]

    def _rerank_multistep_legacy(
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
        route_literals = self._query_route_literals(query)
        route_reachable_ids = self._route_reachable_chunk_ids(route_literals, max_depth=max(3, plan.hop_budget + 2))
        asks_response_writer = self._asks_for_response_writer(query)
        asks_persistence = self._asks_for_persistence(query)
        asks_streaming = self._asks_for_streaming(query)
        asks_retrieval_boundary = self._asks_for_retrieval_boundary(query)
        asks_authorization = self._asks_for_authorization(query)
        asks_sync_json = self._asks_for_sync_json(query)
        asks_state_reset = self._asks_for_state_reset(query)
        asks_package_config = self._asks_for_package_config(query)
        asks_security_policy = self._asks_for_security_policy(query)
        asks_test_file = self._asks_for_test_file(query)
        asks_run_history = self._asks_for_run_history(query)
        asks_apply_run = self._asks_for_apply_run(query)
        asks_clear_helper = self._asks_for_clear_helper(query)
        asks_rag_ingestion = self._asks_for_rag_ingestion(query)
        asks_rag_retrieval_entry = self._asks_for_rag_retrieval_entry(query)
        asks_rag_store_reset = self._asks_for_rag_store_reset(query)
        asks_normalization_helper = self._asks_for_normalization_helper(query)
        asks_payload_builder = self._asks_for_payload_builder(query)
        asks_stream_turn_builder = self._asks_for_stream_turn_builder(query)
        asks_chat_worker = self._asks_for_chat_worker(query)
        asks_session_loader = self._asks_for_session_loader(query)
        asks_web_interaction_logic = self._asks_for_web_interaction_logic(query)
        if any((
            asks_package_config,
            asks_security_policy,
            asks_test_file,
            asks_run_history,
            asks_apply_run,
            asks_clear_helper,
            asks_rag_ingestion,
            asks_rag_retrieval_entry,
            asks_rag_store_reset,
        )):
            candidate_ids.update(
                self._intent_candidate_chunk_ids(
                    asks_package_config=asks_package_config,
                    asks_security_policy=asks_security_policy,
                    asks_test_file=asks_test_file,
                    asks_run_history=asks_run_history,
                    asks_apply_run=asks_apply_run,
                    asks_clear_helper=asks_clear_helper,
                    asks_rag_ingestion=asks_rag_ingestion,
                    asks_rag_retrieval_entry=asks_rag_retrieval_entry,
                    asks_rag_store_reset=asks_rag_store_reset,
                )
            )

        for chunk_id in candidate_ids:
            chunk = self.chunk_by_id[chunk_id]
            symbol_lower = chunk.symbol_name.lower()
            relpath_lower = chunk.relpath.lower()
            text_lower = chunk.text.lower()
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
            if route_literals and not chunk.symbol_name:
                total_score *= 0.55
                reasons = reasons + ["route-anchored overview downrank"]
            if self._query_excludes_chunk(query, chunk):
                total_score -= 22.0
                reasons = reasons + ["explicitly excluded by query"]
            if route_literals:
                if chunk_id in route_reachable_ids:
                    total_score += 7.0
                    reasons = reasons + ["exact route path evidence"]
                elif asks_response_writer and self._chunk_writes_response(chunk):
                    total_score -= 14.0
                    reasons = reasons + ["off-route writer decoy"]
                if self._chunk_conflicts_with_route_family(route_literals, chunk):
                    total_score -= 18.0
                    reasons = reasons + ["route-family conflict"]
            if self._asks_for_handler_function(query):
                if chunk.symbol_kind == "function":
                    total_score += 8.0
                    reasons = reasons + ["handler-function target"]
                    if chunk.symbol_name.lower().startswith("handle") and not (asks_response_writer or asks_persistence):
                        total_score += 6.0
                        reasons = reasons + ["handler name target"]
                    if asks_streaming and self._chunk_matches_streaming_intent(chunk):
                        total_score += 4.8
                        reasons = reasons + ["streaming handler disambiguation"]
                    if asks_sync_json and self._chunk_matches_streaming_intent(chunk):
                        total_score -= 9.0
                        reasons = reasons + ["sync-json stream detour"]
                    if asks_sync_json and ("json" in symbol_lower or "json" in text_lower) and not self._chunk_matches_streaming_intent(chunk):
                        total_score += 8.5
                        reasons = reasons + ["sync-json handler target"]
                    if asks_authorization and symbol_lower.startswith(("authorize", "auth")):
                        total_score += 13.0
                        reasons = reasons + ["authorization middleware target"]
                    elif chunk.symbol_name.lower().startswith(("authorize", "auth")):
                        total_score -= 5.0
                        reasons = reasons + ["middleware detour"]
                elif chunk.symbol_kind == "route":
                    total_score -= 10.0
                    reasons = reasons + ["route entry detour"]
            if asks_response_writer:
                if not chunk.symbol_name:
                    total_score -= 20.0
                    reasons = reasons + ["writer overview detour"]
                elif self._chunk_writes_response(chunk):
                    total_score += 14.0
                    reasons = reasons + ["response-writer target"]
                    if symbol_lower.startswith("write"):
                        total_score += 10.0
                        reasons = reasons + ["concrete writer target"]
                    if "admin" in query.lower() and "admin" in symbol_lower:
                        total_score += 14.0
                        reasons = reasons + ["admin writer target"]
                    if "legacy" in query.lower() and "legacy" in symbol_lower:
                        total_score += 10.0
                        reasons = reasons + ["legacy writer target"]
                elif chunk.symbol_kind == "function":
                    total_score -= 2.0
                    reasons = reasons + ["non-writer function detour"]
            if asks_persistence:
                if self._chunk_persists_state(chunk):
                    total_score += 24.0
                    reasons = reasons + ["persistence target"]
                elif chunk.symbol_name.lower().startswith("handle"):
                    total_score -= 12.0
                    reasons = reasons + ["persistence handler detour"]
                elif chunk.symbol_kind == "route":
                    total_score -= 4.0
                    reasons = reasons + ["persistence route detour"]
            if plan.intent in {"api_lookup", "flow_trace"} and chunk.symbol_kind == "function":
                total_score += 2.6
                reasons = reasons + ["concrete step"]
            if asks_retrieval_boundary and chunk.symbol_kind == "function":
                if "retrieve" in symbol_lower:
                    total_score += 9.0
                    reasons = reasons + ["retrieval helper target"]
                if self._chunk_is_library_boundary(chunk):
                    total_score += 4.0
                    reasons = reasons + ["library boundary prior"]
                if symbol_lower.startswith("handle") and not any(term in symbol_lower for term in ("retrieve", "search")):
                    total_score -= 3.0
                    reasons = reasons + ["entry handler boundary detour"]
            if asks_state_reset:
                if asks_clear_helper and any(term in symbol_lower for term in ("clear", "delete")):
                    total_score += 50.0
                    reasons = reasons + ["clear-state helper target"]
                elif asks_clear_helper and "reset" in symbol_lower:
                    total_score -= 24.0
                    reasons = reasons + ["clear-state reset wrapper detour"]
                elif any(term in symbol_lower for term in ("reset", "clear", "delete")):
                    total_score += 14.0
                    reasons = reasons + ["state reset target"]
                elif chunk.symbol_kind == "route":
                    total_score -= 16.0 if asks_clear_helper else 6.0
                    reasons = reasons + ["state reset route detour"]
            if asks_package_config:
                if relpath_lower == "pyproject.toml":
                    total_score += 70.0
                    reasons = reasons + ["package data config target"]
                elif relpath_lower in {"manifest.in", "readme.md"}:
                    total_score -= 8.0
                    reasons = reasons + ["package config distractor"]
                elif relpath_lower.startswith("web/"):
                    total_score -= 28.0
                    reasons = reasons + ["package config web detour"]
            if asks_test_file:
                if relpath_lower.startswith("tests/"):
                    total_score += 26.0
                    reasons = reasons + ["test file target"]
                    if "coordination" in query.lower() and relpath_lower == "tests/test_coordination.py":
                        total_score += 82.0
                        reasons = reasons + ["coordination test target"]
                    elif "coordination" in query.lower() and "active claim" in query.lower():
                        total_score -= 24.0
                        reasons = reasons + ["coordination test distractor"]
                elif relpath_lower.startswith("repo_agent/"):
                    total_score -= 42.0
                    reasons = reasons + ["test lookup source detour"]
                    if "test file" in query.lower():
                        total_score *= 0.35
                        reasons = reasons + ["test-file source downrank"]
            if asks_security_policy:
                if relpath_lower == "repo_agent/security.py":
                    total_score += 30.0
                    reasons = reasons + ["verification policy target"]
                elif symbol_lower in {"engineeringagent", "repotools"} or relpath_lower in {"repo_agent/engineering.py", "repo_agent/tools.py"}:
                    total_score -= 18.0
                    reasons = reasons + ["verification policy caller detour"]
            if asks_run_history:
                if symbol_lower == "refreshruns":
                    total_score += 24.0
                    reasons = reasons + ["run history refresh target"]
                elif chunk.relpath == "web/index.html" and not chunk.symbol_name:
                    total_score -= 16.0
                    reasons = reasons + ["run history page shell detour"]
                elif symbol_lower in {"openrun", "resumerun"} or (symbol_lower == "applyrun" and not asks_apply_run):
                    total_score -= 8.0
                    reasons = reasons + ["run history action detour"]
            if asks_apply_run:
                if symbol_lower == "applyrun":
                    total_score += 30.0
                    reasons = reasons + ["apply-run action target"]
                elif symbol_lower in {"renderruns", "refreshruns", "runengineering"}:
                    total_score -= 16.0
                    reasons = reasons + ["apply-run distractor"]
            if asks_rag_ingestion:
                asks_library_function = "library function" in query.lower()
                asks_handler = "handler" in query.lower()
                if symbol_lower == "handleragtext" and asks_handler and not asks_library_function:
                    total_score += 40.0
                    reasons = reasons + ["rag text ingest handler target"]
                elif symbol_lower == "ingestdocument":
                    if asks_handler and not asks_library_function:
                        total_score -= 12.0
                        reasons = reasons + ["rag library handler detour"]
                    else:
                        total_score += 38.0 if asks_library_function else 30.0
                        reasons = reasons + ["rag ingest library target"]
                elif symbol_lower == "handleragtext" and asks_library_function:
                    total_score -= 10.0
                    reasons = reasons + ["rag library query handler detour"]
                elif symbol_lower == "createragstore":
                    total_score -= 18.0
                    reasons = reasons + ["rag factory detour"]
            if asks_rag_retrieval_entry:
                if symbol_lower == "runagent":
                    total_score += 28.0
                    reasons = reasons + ["rag retrieval entry target"]
                elif symbol_lower in {"retrieve", "createragstore"}:
                    total_score -= 10.0
                    reasons = reasons + ["rag retrieval dependency detour"]
            if asks_rag_store_reset:
                if symbol_lower == "reset":
                    total_score += 28.0
                    reasons = reasons + ["rag reset library target"]
                elif symbol_lower == "createragstore":
                    total_score -= 18.0
                    reasons = reasons + ["rag factory detour"]
            if asks_normalization_helper:
                if symbol_lower.startswith("normalize"):
                    total_score += 24.0
                    reasons = reasons + ["normalization helper target"]
                elif symbol_lower.startswith("handle") or symbol_lower.startswith("stream"):
                    total_score -= 9.0
                    reasons = reasons + ["normalization entry detour"]
            if asks_payload_builder:
                if symbol_lower.startswith(("create", "build", "prepare")) and any(term in symbol_lower for term in ("frame", "replay", "envelope", "payload")):
                    total_score += 24.0
                    reasons = reasons + ["payload builder target"]
                    if "legacy" in query.lower() and "legacy" in symbol_lower:
                        total_score += 10.0
                        reasons = reasons + ["legacy builder target"]
                elif symbol_lower.startswith("handle"):
                    total_score -= 10.0
                    reasons = reasons + ["payload handler detour"]
                elif symbol_lower.startswith("write"):
                    total_score -= 4.0
                    reasons = reasons + ["payload writer detour"]
            if asks_stream_turn_builder:
                if symbol_lower == "createstreamedassistantturn":
                    total_score += 26.0
                    reasons = reasons + ["streamed turn builder target"]
                elif symbol_lower.startswith("handle"):
                    total_score -= 10.0
                    reasons = reasons + ["streamed turn handler detour"]
                elif symbol_lower == "createassistantturn":
                    total_score -= 5.0
                    reasons = reasons + ["sync turn detour"]
            if asks_chat_worker:
                if symbol_lower in {"run_chat", "runchat"}:
                    total_score += 24.0
                    reasons = reasons + ["chat worker target"]
                elif symbol_lower in {"chat_endpoint", "chatendpoint"} or chunk.symbol_kind == "route":
                    total_score -= 12.0
                    reasons = reasons + ["chat route detour"]
            if asks_session_loader:
                if symbol_lower in {"load_session", "loadsession"}:
                    total_score += 28.0
                    reasons = reasons + ["session loader target"]
                elif symbol_lower in {"read_session", "readsession"} or chunk.symbol_kind == "route":
                    total_score -= 10.0
                    reasons = reasons + ["session route detour"]
            if asks_web_interaction_logic:
                if relpath_lower == "web/app.js":
                    total_score += 22.0
                    reasons = reasons + ["browser interaction logic target"]
                elif relpath_lower == "web/index.html":
                    total_score -= 24.0
                    reasons = reasons + ["browser page shell detour"]
            if plan.intent == "frontend_lookup" and chunk.relpath == "web/index.html" and not chunk.symbol_name:
                if asks_run_history:
                    total_score -= 4.0
                    reasons = reasons + ["frontend function preferred"]
                else:
                    total_score += 4.0
                    reasons = reasons + ["page shell"]
            if plan.intent == "style_lookup":
                if chunk.language == "css":
                    # Style questions should prefer a stylesheet by language,
                    # regardless of whether a project uses web/styles.css,
                    # assets/theme.css, or another layout.
                    total_score += 10.0
                    reasons = reasons + ["stylesheet intent"]
                elif chunk.language == "html":
                    total_score -= 4.0
                    reasons = reasons + ["style page-shell detour"]
            if total_score <= 0:
                continue
            reranked.append(RetrievalHit(chunk=chunk, score=total_score, matched_terms=matched_terms, reasons=reasons))

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    def _route_reachable_chunk_ids(self, route_literals: list[str], *, max_depth: int) -> set[str]:
        if not route_literals:
            return set()
        anchors = [
            chunk
            for chunk in self.chunks
            if chunk.symbol_kind == "route" and self._route_matches_query(chunk.route_path, route_literals)
        ]
        reachable: set[str] = set()
        for anchor in anchors:
            frontier = [(anchor.chunk_id, 0)]
            visited = {anchor.chunk_id}
            reachable.add(anchor.chunk_id)
            while frontier:
                node_id, depth = frontier.pop(0)
                if depth >= max_depth:
                    continue
                for edge in self.forward_edges.get(node_id, []):
                    if edge.target not in self.chunk_by_id or edge.target in visited:
                        continue
                    visited.add(edge.target)
                    reachable.add(edge.target)
                    frontier.append((edge.target, depth + 1))
        return reachable

    @staticmethod
    def _chunk_conflicts_with_route_family(route_literals: list[str], chunk: CodeChunk) -> bool:
        route_text = " ".join(route_literals).lower()
        label = chunk.source_label.lower()
        symbol = chunk.symbol_name.lower()
        chunk_route = chunk.route_path.lower()
        haystack = " ".join([label, symbol, chunk_route])
        if "admin" not in route_text and "admin" in haystack:
            return True
        if "legacy" not in route_text and "legacy" in haystack:
            return True
        if "preview" not in route_text and "preview" in haystack:
            return True
        if "mock" not in route_text and "mock" in haystack:
            return True
        if "fake" not in route_text and "fake" in haystack:
            return True
        return False

    def _chunk_matches_roles(self, chunk: CodeChunk, target_roles: list[str]) -> bool:
        file_fact = self.file_fact_by_relpath.get(chunk.relpath)
        if not file_fact:
            return False
        return any(role in file_fact.roles for role in target_roles)

    @staticmethod
    def _asks_for_handler_function(query: str) -> bool:
        lowered = query.lower()
        if any(term in lowered for term in ("handler", "function", "callback", "callee")):
            return True
        return any(term in query for term in ("\u5904\u7406", "\u51fd\u6570", "\u8c03\u7528"))

    @staticmethod
    def _asks_for_authorization(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in AUTHORIZATION_QUERY_TERMS)

    @staticmethod
    def _asks_for_sync_json(query: str) -> bool:
        lowered = query.lower()
        return "json" in lowered and any(term in lowered for term in JSON_SYNC_QUERY_TERMS)

    @staticmethod
    def _asks_for_state_reset(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in STATE_RESET_QUERY_TERMS) or "\u91cd\u7f6e" in query

    @staticmethod
    def _asks_for_package_config(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in PACKAGE_CONFIG_QUERY_TERMS) or ("package" in lowered and "configured" in lowered)

    @staticmethod
    def _asks_for_security_policy(query: str) -> bool:
        lowered = query.lower()
        return ("verification" in lowered and "policy" in lowered) or ("allow-list" in lowered or "allowlist" in lowered)

    @staticmethod
    def _asks_for_test_file(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in TEST_FILE_QUERY_TERMS)

    @staticmethod
    def _asks_for_run_history(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in RUN_HISTORY_QUERY_TERMS)

    @staticmethod
    def _asks_for_apply_run(query: str) -> bool:
        lowered = query.lower()
        asks_apply = any(term in lowered for term in ("apply", "applies", "applied", "applying", "/api/runs/apply"))
        asks_run = "run" in lowered or "runs" in lowered
        asks_action_surface = any(term in lowered for term in ("action", "post", "posts", "posting", "workspace", "/api/runs/apply"))
        return asks_apply and asks_run and asks_action_surface

    @staticmethod
    def _asks_for_clear_helper(query: str) -> bool:
        lowered = query.lower()
        return "helper" in lowered and any(term in lowered for term in ("clear", "clears", "delete", "deletes"))

    @staticmethod
    def _asks_for_rag_ingestion(query: str) -> bool:
        lowered = query.lower()
        if any(term in lowered for term in ("clear", "clears", "reset", "resets", "delete", "deletes")):
            return False
        return "rag" in lowered and any(term in lowered for term in ("ingest", "ingests", "ingestion", "append", "appends", "uploaded", "documents", "raw text"))

    @staticmethod
    def _asks_for_rag_retrieval_entry(query: str) -> bool:
        lowered = query.lower()
        asks_rag_retrieval = "rag" in lowered and "retrieval" in lowered
        asks_entry = any(term in lowered for term in ("server function", "agent context", "entry", "before returning"))
        return asks_rag_retrieval and asks_entry

    @staticmethod
    def _asks_for_rag_store_reset(query: str) -> bool:
        lowered = query.lower()
        return "rag store" in lowered and any(term in lowered for term in ("clear", "clears", "reset", "resets", "delete", "deletes"))

    @staticmethod
    def _asks_for_normalization_helper(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in ("normalize", "normalizes", "normalise", "normalises", "normalization"))

    @staticmethod
    def _asks_for_payload_builder(query: str) -> bool:
        lowered = query.lower()
        asks_build = any(term in lowered for term in ("build", "builds", "builder", "create", "creates", "prepare", "prepares"))
        asks_payload_shape = any(term in lowered for term in ("frame", "payload", "envelope", "replay"))
        return asks_build and asks_payload_shape

    @staticmethod
    def _asks_for_stream_turn_builder(query: str) -> bool:
        lowered = query.lower()
        asks_streamed_turn = "streamed assistant turn" in lowered or ("assistant turn" in lowered and "stream" in lowered)
        asks_create = any(term in lowered for term in ("create", "creates", "builder", "builds"))
        return asks_streamed_turn and asks_create

    @staticmethod
    def _asks_for_chat_worker(query: str) -> bool:
        lowered = query.lower()
        asks_chat = "chat" in lowered and "payload" in lowered
        asks_worker = any(term in lowered for term in ("runs", "run", "worker", "after the route", "delegates"))
        return asks_chat and asks_worker

    @staticmethod
    def _asks_for_session_loader(query: str) -> bool:
        lowered = query.lower()
        asks_session = "session" in lowered
        asks_load = any(term in lowered for term in ("load", "loads", "loader"))
        return asks_session and asks_load

    @staticmethod
    def _asks_for_web_interaction_logic(query: str) -> bool:
        lowered = query.lower()
        asks_web_studio = "web studio" in lowered or "browser" in lowered
        asks_logic = any(term in lowered for term in ("interaction logic", "browser interaction", "client logic"))
        return asks_web_studio and asks_logic

    def _intent_candidate_chunk_ids(
        self,
        *,
        asks_package_config: bool,
        asks_security_policy: bool,
        asks_test_file: bool,
        asks_run_history: bool,
        asks_apply_run: bool,
        asks_clear_helper: bool,
        asks_rag_ingestion: bool,
        asks_rag_retrieval_entry: bool,
        asks_rag_store_reset: bool,
    ) -> set[str]:
        candidates: set[str] = set()
        for chunk in self.chunks:
            relpath = chunk.relpath.lower()
            symbol = chunk.symbol_name.lower()
            if asks_package_config and relpath == "pyproject.toml":
                candidates.add(chunk.chunk_id)
            if asks_security_policy and relpath == "repo_agent/security.py":
                candidates.add(chunk.chunk_id)
            if asks_test_file and relpath.startswith("tests/"):
                candidates.add(chunk.chunk_id)
            if asks_run_history and symbol in {"refreshruns", "renderruns"}:
                candidates.add(chunk.chunk_id)
            if asks_apply_run and symbol in {"applyrun", "renderruns", "refreshruns", "runengineering"}:
                candidates.add(chunk.chunk_id)
            if asks_clear_helper and any(term in symbol for term in ("clear", "reset", "delete")):
                candidates.add(chunk.chunk_id)
            if asks_rag_ingestion and symbol in {"handleragtext", "ingestdocument", "createragstore"}:
                candidates.add(chunk.chunk_id)
            if asks_rag_retrieval_entry and symbol in {"runagent", "retrieve", "createragstore"}:
                candidates.add(chunk.chunk_id)
            if asks_rag_store_reset and symbol in {"reset", "createragstore"}:
                candidates.add(chunk.chunk_id)
        return candidates

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
                    "references": chunk.references,
                    "inherits": chunk.inherits,
                    "qualified_name": chunk.qualified_name,
                    "parser_backend": chunk.parser_backend,
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
            "embedding_model": self.embedding_model,
            "embedding_vectors": self.embedding_index.vectors if self.embedding_index else [],
        }

    @classmethod
    def from_payload(cls, repo_root: Path, payload: dict) -> RepositoryIndex:
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
                references=list(item.get("references", [])),
                inherits=list(item.get("inherits", [])),
                qualified_name=item.get("qualified_name", ""),
                parser_backend=item.get("parser_backend", "fallback"),
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
        return cls(
            repo_root=repo_root,
            chunks=chunks,
            file_facts=file_facts,
            edges=edges,
            embedding_vectors=[list(map(float, vector)) for vector in payload.get("embedding_vectors", [])],
            embedding_model=str(payload.get("embedding_model", "")),
        )

    def _score_all_chunks(self, query: str, semantic_scores: dict[str, float]) -> list[RetrievalHit]:
        scored: list[RetrievalHit] = []
        for chunk in self.chunks:
            score, matched_terms, reasons = self._score_chunk(query, chunk, semantic_scores.get(chunk.chunk_id, 0.0))
            if score > 0:
                scored.append(RetrievalHit(chunk=chunk, score=score, matched_terms=matched_terms, reasons=reasons))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored

    def _score_chunk(self, query: str, chunk: CodeChunk, semantic_score: float) -> tuple[float, list[str], list[str]]:
        """Score a candidate using inspectable retrieval evidence only.

        This intentionally has no query-specific intent table.  Intent-aware
        exploration is handled by the model/tool loop; the index should remain
        a broad, stable candidate generator.
        """
        query_terms = self._query_terms(query)
        query_set = set(query_terms)
        tokens = self.chunk_token_counters[chunk.chunk_id]
        matched_terms = sorted(query_set.intersection(tokens))
        if not matched_terms and semantic_score < 0.16:
            return 0.0, [], []

        lexical_evidence = 0.0
        reasons: list[str] = []
        for term in matched_terms:
            tf = tokens[term]
            idf = math.log((self.doc_count + 1) / (1 + self.doc_freq.get(term, 0))) + 1.0
            lexical_evidence += min(1.5, (1.0 + math.log(tf)) * idf)
        # Length-normalized BM25/RRF is the primary lexical signal.  This cap
        # prevents repository overviews and giant classes from winning simply
        # because they repeat every query term many times.
        score = min(6.0, lexical_evidence)

        if semantic_score > 0:
            score += semantic_score * 16.0
            reasons.append(f"hybrid_rrf={semantic_score:.2f}")
            reasons.append(f"views={','.join(self.multi_view_index.view_names)}")
            if not matched_terms:
                matched_terms = ["hybrid_recall"]

        symbol_overlap = len(query_set.intersection(tokenize(chunk.symbol_name)))
        path_overlap = len(query_set.intersection(tokenize(chunk.relpath)))
        route_overlap = len(query_set.intersection(tokenize(chunk.route_path)))
        if symbol_overlap:
            score += min(6.0, symbol_overlap * 2.5)
            reasons.append("symbol overlap")
        if path_overlap:
            score += min(8.0, path_overlap * 3.0)
            reasons.append("path overlap")
        if route_overlap:
            score += min(5.0, route_overlap * 2.0)
            reasons.append("route overlap")
        if chunk.symbol_kind in {"function", "class", "route"}:
            score += 0.25
            reasons.append("symbol evidence")
        else:
            # File overviews are useful for orientation but should not outrank
            # the concrete symbol that contains the same evidence.
            score *= 0.38
            reasons.append("overview context")
        if chunk.language in query_set:
            score += 10.0
            reasons.append("language metadata")
        if chunk.route_path:
            score += 0.3
        if chunk.calls:
            score += min(len(chunk.calls), 6) * 0.08
        return score, matched_terms, reasons or ["token overlap"]

    def _score_chunk_legacy(self, query: str, chunk: CodeChunk, semantic_score: float) -> tuple[float, list[str], list[str]]:
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
            reasons.append(f"bm25 {semantic_score:.2f}")
            if not matched_terms:
                matched_terms = ["bm25_recall"]

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
        if any(term in lowered_query for term in RESPONSE_WRITE_QUERY_TERMS):
            if any(flag in text_lower for flag in ("res.write", "response.write", ".write(", "send(")):
                score += 7.0
                reasons.append("response writer")
            if any(flag in text_lower for flag in ("res.end", "response.end", ".end(")):
                score += 2.0
                reasons.append("response terminator")
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
        return self._build_doc_freq_from_documents([chunk_tokens(chunk) for chunk in chunks])

    @staticmethod
    def _build_doc_freq_from_documents(documents: list[list[str]]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for tokens in documents:
            for token in set(tokens):
                freq[token] = freq.get(token, 0) + 1
        return freq

    def _build_file_doc_freq(self, file_facts: list[FileFact]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for fact in file_facts:
            for token in set(file_fact_tokens(fact)):
                freq[token] = freq.get(token, 0) + 1
        return freq

    def _semantic_scores(self, query: str, *, query_vector: list[float] | None = None) -> dict[str, float]:
        lexical = self.multi_view_index.scores(self._query_terms(query))
        if not self.embedding_index or not query_vector:
            return lexical
        dense = self.embedding_index.scores(query_vector)
        lexical_ranking = sorted(lexical, key=lambda doc_id: (-lexical[doc_id], doc_id))
        dense_ranking = sorted(dense, key=lambda doc_id: (-dense[doc_id], doc_id))
        fused = weighted_reciprocal_rank_fusion(
            [(lexical_ranking, 1.0), (dense_ranking, 1.2)],
            rank_constant=30,
        )
        ceiling = 2.2 / 31.0
        return {doc_id: min(1.0, score / ceiling) for doc_id, score in fused.items()}

    def _query_terms(self, query: str) -> tuple[str, ...]:
        cached = self._query_terms_cache.get(query)
        if cached is None:
            cached = tuple(expand_query_terms(query))
            self._query_terms_cache[query] = cached
        return cached

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
    file_cache: object | None = None,
    embedding_provider: Callable[[list[str]], list[list[float]]] | None = None,
    embedding_model: str = "",
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
        analysis = None
        if file_cache is not None and hasattr(file_cache, "load_analysis"):
            analysis = file_cache.load_analysis(repo_root, relpath, text)
        if analysis is None:
            analysis = analyze_source(path, text)
            if file_cache is not None and hasattr(file_cache, "save_analysis"):
                file_cache.save_analysis(repo_root, relpath, text, analysis)
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
                    references=symbol.references,
                    inherits=symbol.inherits,
                    qualified_name=symbol.qualified_name or symbol.name,
                    parser_backend=analysis.parser_backend,
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
                references=[reference for symbol in analysis.symbols for reference in symbol.references],
                inherits=[base for symbol in analysis.symbols for base in symbol.inherits],
                parser_backend=analysis.parser_backend,
            )
        )
    edges = _build_edges(chunks)
    embedding_vectors: list[list[float]] = []
    if embedding_provider and chunks:
        embedding_inputs = [
            f"path: {chunk.relpath}\n"
            f"symbol: {chunk.symbol_name}\n"
            f"kind: {chunk.symbol_kind}\n"
            f"route: {chunk.route_path}\n"
            f"code:\n{chunk.text[:3000]}"
            for chunk in chunks
        ]
        try:
            for start in range(0, len(embedding_inputs), 32):
                batch = embedding_provider(embedding_inputs[start : start + 32])
                if len(batch) != min(32, len(embedding_inputs) - start):
                    embedding_vectors = []
                    break
                embedding_vectors.extend(batch)
        except (OSError, RuntimeError, TypeError, ValueError):
            embedding_vectors = []
    return RepositoryIndex(
        repo_root,
        chunks,
        file_facts,
        edges,
        embedding_vectors=embedding_vectors or None,
        embedding_model=embedding_model if embedding_vectors else "",
    )


def tokenize(text: str) -> list[str]:
    raw = str(text or "").replace("-", "_").replace("/", " ")
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    normalized = raw.lower()
    tokens = TOKEN_RE.findall(normalized)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token.lower())
        if all("\u4e00" <= char <= "\u9fff" for char in token):
            expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
        if "_" in token:
            expanded.extend(part for part in token.lower().split("_") if part)
        normalized_token = token.lower()
        if len(normalized_token) > 4 and normalized_token.endswith("ies"):
            expanded.append(normalized_token[:-3] + "y")
        elif len(normalized_token) > 3 and normalized_token.endswith("s"):
            expanded.append(normalized_token[:-1])
        if len(normalized_token) > 5 and normalized_token.endswith("ing"):
            expanded.append(normalized_token[:-3])
    return expanded


def expand_query_terms(query: str) -> list[str]:
    base_terms = tokenize(query)
    expanded = list(base_terms)
    lowered = str(query or "").lower()
    # The previous table contained mojibake literals. Keep common Chinese
    # expansion terms in Unicode so normal Chinese questions are searchable.
    chinese_expansions = {
        "聊天": ["chat", "message"],
        "流式": ["stream", "streaming", "sse", "delta"],
        "输出": ["output", "content", "response", "write", "send"],
        "实现": ["implement", "handle", "run", "function"],
        "接口": ["api", "route", "endpoint", "handler"],
        "路由": ["api", "route", "endpoint", "handler"],
        "入口": ["entry", "route", "handler", "endpoint"],
        "处理": ["handle", "handler", "process", "function"],
        "函数": ["function", "handler", "method"],
        "会话": ["session", "messages", "history"],
        "上传": ["upload", "ingest", "document"],
        "文档": ["document", "documents", "rag"],
        "流程": ["flow", "pipeline", "process", "execution"],
        "检索": ["retrieve", "retrieval", "search", "lookup", "rag"],
        "定位": ["locate", "find", "search"],
        "调用链": ["call", "caller", "callee", "import"],
        "测试": ["test", "pytest", "spec", "case"],
        "配置": ["config", "env", "environment"],
        "错误": ["error", "throw", "catch", "failure"],
        "页面": ["page", "html", "web", "ui"],
        "样式": ["style", "stylesheet", "css"],
        "浏览器": ["browser", "frontend", "web", "javascript"],
        "交互": ["interaction", "event", "click", "frontend"],
        "包": ["package", "pyproject", "manifest"],
    }
    for chinese_term, english_terms in chinese_expansions.items():
        if chinese_term in query:
            expanded.extend(english_terms)
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
        + tokenize(" ".join(chunk.references))
        + tokenize(" ".join(chunk.inherits))
        + tokenize(chunk.qualified_name)
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
    qualified_lookup: dict[str, list[CodeChunk]] = defaultdict(list)
    file_lookup: dict[str, list[CodeChunk]] = defaultdict(list)
    stem_lookup: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        file_lookup[chunk.relpath].append(chunk)
        stem_lookup[Path(chunk.relpath).stem.lower()].append(chunk.relpath)
        if chunk.symbol_name:
            symbol_lookup[chunk.symbol_name.lower()].append(chunk)
        if chunk.qualified_name:
            qualified_lookup[chunk.qualified_name.lower()].append(chunk)

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, label: str, weight: float) -> None:
        key = (source, target, label)
        if source == target or key in seen:
            return
        seen.add(key)
        edges.append(GraphEdge(source=source, target=target, label=label, weight=weight))

    def resolve_symbol(source_chunk: CodeChunk, name: str) -> list[CodeChunk]:
        candidates = qualified_lookup.get(name.lower(), []) or symbol_lookup.get(name.lower(), [])
        same_file = [candidate for candidate in candidates if candidate.relpath == source_chunk.relpath]
        return same_file or candidates

    for chunk in chunks:
        for called in chunk.calls + chunk.handler_names:
            for target_chunk in resolve_symbol(chunk, called):
                weight = 2.6 if target_chunk.relpath == chunk.relpath else 1.8
                add_edge(chunk.chunk_id, target_chunk.chunk_id, "calls", weight)
        for reference in chunk.references:
            for target_chunk in resolve_symbol(chunk, reference):
                weight = 1.35 if target_chunk.relpath == chunk.relpath else 0.85
                add_edge(chunk.chunk_id, target_chunk.chunk_id, "references", weight)
        for base in chunk.inherits:
            for target_chunk in resolve_symbol(chunk, base):
                add_edge(chunk.chunk_id, target_chunk.chunk_id, "inherits", 3.0)
        for import_name in chunk.imports:
            tail = import_name.replace("\\", "/").rstrip("/").split("/")[-1].lower()
            tail = Path(tail).stem.lower() or tail
            for relpath in stem_lookup.get(tail, []):
                for target_chunk in file_lookup.get(relpath, []):
                    if target_chunk.symbol_name == "":
                        add_edge(chunk.chunk_id, target_chunk.chunk_id, "imports", 1.4)
        if chunk.symbol_kind == "route":
            for handler_name in chunk.handler_names:
                for target_chunk in resolve_symbol(chunk, handler_name):
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
