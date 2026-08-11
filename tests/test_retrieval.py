from __future__ import annotations

from repo_agent.indexer import expand_query_terms
from repo_agent.retrieval import (
    BM25Index,
    DenseEmbeddingIndex,
    MultiViewBM25Index,
    reciprocal_rank_fusion,
    weighted_reciprocal_rank_fusion,
)


def test_bm25_prefers_specific_document_and_normalizes_scores() -> None:
    index = BM25Index(
        ["route", "writer", "noise"],
        [
            ["chat", "route", "handler"],
            ["chat", "stream", "stream", "delta", "writer"],
            ["admin", "settings"],
        ],
    )

    scores = index.scores(["stream", "delta"])

    assert scores["writer"] == 1.0
    assert "noise" not in scores
    assert index.stats.vocabulary_size >= 7


def test_reciprocal_rank_fusion_rewards_cross_ranking_agreement() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"], ["b", "c"]])

    assert fused["b"] > fused["a"] > fused["c"]


def test_query_normalization_supports_chinese_and_basic_inflections() -> None:
    terms = expand_query_terms("页面样式在哪里，哪个函数 runs the chat request?")

    assert {"css", "stylesheet", "page", "html"}.issubset(terms)
    assert "run" in terms


def test_dense_embedding_index_ranks_by_cosine_similarity() -> None:
    index = DenseEmbeddingIndex(["chat", "database"], [[1.0, 0.0], [0.0, 1.0]], "test")

    scores = index.scores([0.9, 0.1])

    assert scores["chat"] > scores["database"]
    assert index.dimensions == 2


def test_weighted_rrf_can_prioritize_a_high_precision_channel() -> None:
    fused = weighted_reciprocal_rank_fusion(
        [(["body-match", "exact-symbol"], 1.0), (["exact-symbol", "body-match"], 2.0)],
        rank_constant=10,
    )

    assert fused["exact-symbol"] > fused["body-match"]


def test_multi_view_index_prevents_long_body_from_drowning_exact_symbol() -> None:
    index = MultiViewBM25Index(
        ["overview", "writer"],
        {
            "content": [
                ["chat", "stream", "writer", "chat", "stream", "writer"],
                ["write", "delta"],
            ],
            "identifier": [["server"], ["write", "chat", "delta"]],
            "path": [["server", "js"], ["server", "js"]],
            "structure": [["route"], ["response", "write"]],
        },
        weights={"content": 1.0, "identifier": 1.8, "path": 1.0, "structure": 1.2},
        rank_constant=10,
    )

    scores = index.scores(["which", "function", "writes", "chat", "delta"])

    assert scores["writer"] > scores["overview"]
    assert "identifier" in index.contributions(["chat", "delta"], "writer")
