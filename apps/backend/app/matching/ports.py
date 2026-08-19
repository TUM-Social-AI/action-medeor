"""Dependency-inversion ports for data sources and model providers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.matching.contracts import (
    HistoricalOfferV1,
    InventoryItemV1,
    MatchDecisionRequestV1,
    MatchDecisionResponseV1,
    MatchRequestV1,
    MatchRunResponseV1,
    ProductDomain,
)
from app.matching.domain import RetrievalHit


class CatalogRepository(Protocol):
    async def list_items(
        self,
        *,
        domain: ProductDomain,
        snapshot_id: str | None = None,
    ) -> Sequence[InventoryItemV1]: ...


class VectorRepository(Protocol):
    async def search(
        self,
        *,
        embedding: Sequence[float],
        model_id: str,
        domain: ProductDomain,
        limit: int,
    ) -> Sequence[RetrievalHit]: ...


class HistoryRepository(Protocol):
    async def list_offers(
        self,
        *,
        partner_id: str | None,
        destination_country: str | None,
        limit: int,
    ) -> Sequence[HistoricalOfferV1]: ...


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    async def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class MatchRunRepository(Protocol):
    async def create_run(
        self,
        *,
        run_id: UUID,
        request: MatchRequestV1,
        algorithm_version: str,
        policy_version: str,
    ) -> None: ...

    async def complete_run(self, result: MatchRunResponseV1) -> None: ...

    async def fail_run(self, *, run_id: UUID, error: str) -> None: ...

    async def get_run(self, run_id: UUID) -> MatchRunResponseV1 | None: ...

    async def save_decision(self, decision: MatchDecisionRequestV1) -> MatchDecisionResponseV1: ...
