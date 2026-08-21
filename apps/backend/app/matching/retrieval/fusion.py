"""Deterministic reciprocal-rank fusion for heterogeneous retrievers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from app.matching.domain import RetrievalHit


def reciprocal_rank_fusion(
    result_sets: Iterable[Iterable[RetrievalHit]], *, rank_constant: int = 60
) -> list[tuple[str, float, list[RetrievalHit]]]:
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")

    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[RetrievalHit]] = defaultdict(list)
    for result_set in result_sets:
        seen_in_retriever: set[str] = set()
        for hit in result_set:
            if hit.item_number in seen_in_retriever:
                continue
            seen_in_retriever.add(hit.item_number)
            scores[hit.item_number] += 1 / (rank_constant + hit.rank)
            evidence[hit.item_number].append(hit)

    return sorted(
        (
            (item_number, score, sorted(hits, key=lambda hit: (hit.retriever, hit.rank)))
            for item_number, score in scores.items()
            for hits in [evidence[item_number]]
        ),
        key=lambda value: (-value[1], value[0]),
    )
