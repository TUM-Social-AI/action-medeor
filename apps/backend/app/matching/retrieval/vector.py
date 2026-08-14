"""Vector retrieval adapter; embedding generation remains provider-agnostic."""

from __future__ import annotations

from collections.abc import Sequence

from app.matching.contracts import ProductDomain
from app.matching.domain import RetrievalHit
from app.matching.ports import VectorRepository


class VectorRetriever:
    def __init__(self, repository: VectorRepository) -> None:
        self._repository = repository

    async def search(
        self,
        *,
        embedding: Sequence[float],
        model_id: str,
        domain: ProductDomain,
        limit: int,
    ) -> list[RetrievalHit]:
        results = await self._repository.search(
            embedding=embedding,
            model_id=model_id,
            domain=domain,
            limit=limit,
        )
        return list(results)
