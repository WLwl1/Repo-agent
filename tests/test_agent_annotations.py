from __future__ import annotations

from typing import get_type_hints

from repo_agent import agent
from repo_agent.models import RetrievalHit


def test_agent_retrieval_hit_annotations_resolve_at_runtime() -> None:
    """Keep delayed annotations usable by introspection-based tooling."""

    for function in (
        agent._build_decoy_audit,
        agent._dedupe_retrieval_hits,
        agent._build_proof_graph,
    ):
        hints = get_type_hints(function)
        assert RetrievalHit in _annotation_types(hints)


def _annotation_types(hints: dict[str, object]) -> set[object]:
    discovered: set[object] = set()
    pending = list(hints.values())
    while pending:
        annotation = pending.pop()
        discovered.add(annotation)
        pending.extend(getattr(annotation, "__args__", ()))
    return discovered
