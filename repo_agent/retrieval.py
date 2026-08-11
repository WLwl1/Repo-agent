from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from collections.abc import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class BM25Stats:
    document_count: int
    vocabulary_size: int
    average_document_length: float
    k1: float
    b: float


class BM25Index:
    """Small, deterministic BM25 index for repository chunks.

    The index deliberately keeps retrieval local and inspectable.  It replaces the
    previous dense TF-IDF/SVD matrix, whose full decomposition scaled poorly and
    was difficult to update incrementally.
    """

    def __init__(
        self,
        document_ids: Sequence[str],
        documents: Sequence[Sequence[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if len(document_ids) != len(documents):
            raise ValueError("document_ids and documents must have the same length")
        self.document_ids = list(document_ids)
        self.k1 = float(k1)
        self.b = float(b)
        self.term_frequencies = [Counter(document) for document in documents]
        self.document_lengths = [
            sum(counter.values()) for counter in self.term_frequencies
        ]
        self.average_document_length = (
            sum(self.document_lengths) / len(self.document_lengths)
            if self.document_lengths
            else 0.0
        )
        self.document_frequency: Counter[str] = Counter()
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for document_index, counter in enumerate(self.term_frequencies):
            self.document_frequency.update(counter.keys())
            for term, frequency in counter.items():
                self.postings[term].append((document_index, frequency))

    @property
    def stats(self) -> BM25Stats:
        return BM25Stats(
            document_count=len(self.document_ids),
            vocabulary_size=len(self.document_frequency),
            average_document_length=round(self.average_document_length, 3),
            k1=self.k1,
            b=self.b,
        )

    def scores(self, query_terms: Iterable[str]) -> dict[str, float]:
        terms = list(dict.fromkeys(term for term in query_terms if term))
        if not terms or not self.document_ids:
            return {}
        document_count = len(self.document_ids)
        average_length = max(self.average_document_length, 1.0)
        raw_scores: dict[int, float] = defaultdict(float)
        for term in terms:
            document_frequency = self.document_frequency.get(term, 0)
            if not document_frequency:
                continue
            inverse_document_frequency = math.log(
                1.0
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for document_index, term_frequency in self.postings.get(term, []):
                document_length = self.document_lengths[document_index]
                length_normalization = self.k1 * (
                    1.0 - self.b + self.b * document_length / average_length
                )
                raw_scores[document_index] += inverse_document_frequency * (
                    term_frequency
                    * (self.k1 + 1.0)
                    / (term_frequency + length_normalization)
                )
        maximum = max(raw_scores.values(), default=0.0)
        if maximum <= 0.0:
            return {}
        return {
            self.document_ids[document_index]: score / maximum
            for document_index, score in raw_scores.items()
            if score > 0.0
        }


class DenseEmbeddingIndex:
    """Small in-memory cosine index for externally produced embeddings.

    The index deliberately knows nothing about a provider.  This keeps model
    choice outside retrieval and lets the runtime use OpenAI-compatible,
    LiteLLM, or local embedding services without changing ranking code.
    """

    def __init__(self, document_ids: Sequence[str], vectors: Sequence[Sequence[float]], model: str = "") -> None:
        if len(document_ids) != len(vectors):
            raise ValueError("document_ids and vectors must have the same length")
        dimensions = {len(vector) for vector in vectors if vector}
        if len(dimensions) > 1:
            raise ValueError("all embedding vectors must have the same dimension")
        self.document_ids = list(document_ids)
        self.vectors = [list(map(float, vector)) for vector in vectors]
        self.model = model
        self.dimensions = next(iter(dimensions), 0)
        self._norms = [math.sqrt(sum(value * value for value in vector)) for vector in self.vectors]

    def scores(self, query_vector: Sequence[float]) -> dict[str, float]:
        if not query_vector or not self.document_ids or len(query_vector) != self.dimensions:
            return {}
        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm <= 0:
            return {}
        scored: dict[str, float] = {}
        for document_id, vector, norm in zip(self.document_ids, self.vectors, self._norms, strict=True):
            if norm <= 0:
                continue
            cosine = sum(left * right for left, right in zip(vector, query_vector, strict=True)) / (norm * query_norm)
            # Cosine is [-1, 1]; retrieval only needs a stable [0, 1] signal.
            scored[document_id] = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
        return scored


class MultiViewBM25Index:
    """Fuse complementary code representations with weighted RRF.

    Repository search has several relevance surfaces that should not share one
    bag of tokens: implementation text, identifiers, paths, and structural
    relations.  Keeping an index per view prevents a long function body from
    drowning an exact symbol/path match and makes every contribution
    inspectable.
    """

    def __init__(
        self,
        document_ids: Sequence[str],
        views: dict[str, Sequence[Sequence[str]]],
        *,
        weights: dict[str, float] | None = None,
        rank_constant: int = 30,
    ) -> None:
        self.document_ids = list(document_ids)
        self.rank_constant = max(1, int(rank_constant))
        self.weights = {name: max(0.0, float((weights or {}).get(name, 1.0))) for name in views}
        self.indexes: dict[str, BM25Index] = {}
        for name, documents in views.items():
            if len(documents) != len(self.document_ids):
                raise ValueError(f"view {name!r} must contain one document per id")
            self.indexes[name] = BM25Index(self.document_ids, documents)

    @property
    def view_names(self) -> list[str]:
        return list(self.indexes)

    def rankings(self, query_terms: Iterable[str]) -> list[tuple[str, list[str], float]]:
        terms = list(query_terms)
        rankings: list[tuple[str, list[str], float]] = []
        for name, index in self.indexes.items():
            weight = self.weights.get(name, 1.0)
            if weight <= 0:
                continue
            scores = index.scores(terms)
            ranking = sorted(scores, key=lambda document_id: (-scores[document_id], document_id))
            if ranking:
                rankings.append((name, ranking, weight))
        return rankings

    def scores(self, query_terms: Iterable[str]) -> dict[str, float]:
        rankings = self.rankings(query_terms)
        if not rankings:
            return {}
        fused = weighted_reciprocal_rank_fusion(
            [(ranking, weight) for _name, ranking, weight in rankings],
            rank_constant=self.rank_constant,
        )
        ceiling = sum(weight / (self.rank_constant + 1) for _name, _ranking, weight in rankings)
        if ceiling <= 0:
            return {}
        return {document_id: min(1.0, score / ceiling) for document_id, score in fused.items()}

    def contributions(self, query_terms: Iterable[str], document_id: str) -> dict[str, float]:
        result: dict[str, float] = {}
        for name, ranking, weight in self.rankings(query_terms):
            try:
                rank = ranking.index(document_id) + 1
            except ValueError:
                continue
            result[name] = weight / (self.rank_constant + rank)
        return result


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    rank_constant: int = 60,
) -> dict[str, float]:
    """Fuse independent rankings without requiring comparable score scales."""

    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, document_id in enumerate(ranking, start=1):
            fused[document_id] = fused.get(document_id, 0.0) + 1.0 / (rank_constant + rank)
    return fused


def weighted_reciprocal_rank_fusion(
    rankings: Sequence[tuple[Sequence[str], float]],
    *,
    rank_constant: int = 60,
) -> dict[str, float]:
    """Weighted reciprocal-rank fusion for heterogeneous retrieval channels."""
    fused: dict[str, float] = {}
    for ranking, weight in rankings:
        if weight <= 0:
            continue
        for rank, document_id in enumerate(ranking, start=1):
            fused[document_id] = fused.get(document_id, 0.0) + float(weight) / (rank_constant + rank)
    return fused
