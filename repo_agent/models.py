from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Symbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    calls: list[str] = field(default_factory=list)
    route_path: str = ""
    handler_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourceAnalysis:
    language: str
    imports: list[str]
    symbols: list[Symbol]


@dataclass(slots=True)
class CodeChunk:
    chunk_id: str
    repo_root: Path
    relpath: str
    language: str
    text: str
    start_line: int
    end_line: int
    symbol_name: str = ""
    symbol_kind: str = ""
    metadata_tokens: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    route_path: str = ""
    handler_names: list[str] = field(default_factory=list)

    @property
    def source_label(self) -> str:
        if self.symbol_name:
            return f"{self.relpath}:{self.symbol_name}"
        return self.relpath


@dataclass(slots=True)
class FileFact:
    relpath: str
    language: str
    line_count: int
    imports: list[str] = field(default_factory=list)
    symbol_names: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FileHit:
    file_fact: FileFact
    score: float
    matched_terms: list[str]
    reasons: list[str]


@dataclass(slots=True)
class QueryPlan:
    mode: str
    intent: str
    focus_terms: list[str]
    target_roles: list[str] = field(default_factory=list)
    target_languages: list[str] = field(default_factory=list)
    hop_budget: int = 2


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    label: str
    weight: float


@dataclass(slots=True)
class RetrievalHit:
    chunk: CodeChunk
    score: float
    matched_terms: list[str]
    reasons: list[str]


@dataclass(slots=True)
class InvestigationBundle:
    mode: str
    focus_terms: list[str]
    seed_hits: list[RetrievalHit]
    final_hits: list[RetrievalHit]
    graph_edges: list[GraphEdge]
    trace: list[dict]


@dataclass(slots=True)
class AgentResult:
    mode: str
    query: str
    answer: str
    hits: list[RetrievalHit]
    trace: list[dict]
    report_path: str = ""
    model_name: str = ""
    repo_brief: str = ""
    diagnostics: "EvidenceDiagnostics | None" = None


@dataclass(slots=True)
class EvidenceDiagnostics:
    confidence: float
    label: str
    evidence_count: int
    unique_files: int
    graph_edge_count: int
    top_score: float
    score_gap: float
    matched_terms: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
