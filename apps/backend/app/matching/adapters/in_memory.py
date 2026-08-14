"""Deterministic in-memory adapters for tests and local demonstrations."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

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
from app.matching.feedback import validate_decision_against_run


class InMemoryCatalogRepository:
    def __init__(self, items: Sequence[InventoryItemV1] = ()) -> None:
        self.items = list(items)

    async def list_items(
        self, *, domain: ProductDomain, snapshot_id: str | None = None
    ) -> list[InventoryItemV1]:
        del snapshot_id
        return [item for item in self.items if item.domain is domain]


class InMemoryHistoryRepository:
    def __init__(self, offers: Sequence[HistoricalOfferV1] = ()) -> None:
        self.offers = list(offers)

    async def list_offers(
        self,
        *,
        partner_id: str | None,
        destination_country: str | None,
        limit: int,
    ) -> list[HistoricalOfferV1]:
        matching = [
            offer
            for offer in self.offers
            if (not partner_id or offer.partner_id in {None, partner_id})
            and (
                not destination_country or offer.destination_country in {None, destination_country}
            )
        ]
        return matching[:limit]


class InMemoryVectorRepository:
    def __init__(self) -> None:
        self.vectors: dict[tuple[str, str], tuple[ProductDomain, tuple[float, ...]]] = {}

    def add(
        self,
        *,
        item_number: str,
        model_id: str,
        domain: ProductDomain,
        embedding: Sequence[float],
    ) -> None:
        self.vectors[(item_number, model_id)] = (domain, tuple(embedding))

    async def search(
        self,
        *,
        embedding: Sequence[float],
        model_id: str,
        domain: ProductDomain,
        limit: int,
    ) -> list[RetrievalHit]:
        query = tuple(embedding)
        scored: list[tuple[float, str]] = []
        for (item_number, stored_model), (stored_domain, vector) in self.vectors.items():
            if stored_model != model_id or stored_domain is not domain:
                continue
            if len(vector) != len(query):
                raise ValueError("Embedding dimensions do not match")
            denominator = math.sqrt(sum(v * v for v in query)) * math.sqrt(
                sum(v * v for v in vector)
            )
            similarity = (
                sum(a * b for a, b in zip(query, vector, strict=True)) / denominator
                if denominator
                else 0.0
            )
            scored.append((similarity, item_number))
        scored.sort(key=lambda value: (-value[0], value[1]))
        return [
            RetrievalHit(
                item_number=item_number,
                retriever="vector",
                rank=rank,
                score=score,
            )
            for rank, (score, item_number) in enumerate(scored[:limit], start=1)
        ]


class DeterministicEmbeddingProvider:
    """Small deterministic provider for tests; it is not a production model."""

    def __init__(self, model_id: str = "deterministic-test-v1", dimensions: int = 8) -> None:
        self._model_id = model_id
        self.dimensions = dimensions

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for value in texts:
            digest = hashlib.sha256(value.encode("utf-8")).digest()
            embeddings.append([((digest[index] / 255) * 2) - 1 for index in range(self.dimensions)])
        return embeddings


class InMemoryMatchRunRepository:
    def __init__(self) -> None:
        self.requests: dict[UUID, MatchRequestV1] = {}
        self.runs: dict[UUID, MatchRunResponseV1] = {}
        self.failures: dict[UUID, str] = {}
        self.decisions: dict[UUID, MatchDecisionRequestV1] = {}

    async def create_run(
        self,
        *,
        run_id: UUID,
        request: MatchRequestV1,
        algorithm_version: str,
        policy_version: str,
    ) -> None:
        del algorithm_version, policy_version
        self.requests[run_id] = request

    async def complete_run(self, result: MatchRunResponseV1) -> None:
        self.runs[result.match_run_id] = result

    async def fail_run(self, *, run_id: UUID, error: str) -> None:
        self.failures[run_id] = error

    async def get_run(self, run_id: UUID) -> MatchRunResponseV1 | None:
        return self.runs.get(run_id)

    async def save_decision(self, decision: MatchDecisionRequestV1) -> MatchDecisionResponseV1:
        run = self.runs.get(decision.match_run_id)
        if run is None:
            raise LookupError("Match run not found")
        validate_decision_against_run(decision, run)
        decision_id = uuid4()
        self.decisions[decision_id] = decision
        return MatchDecisionResponseV1(
            decision_id=decision_id,
            match_run_id=decision.match_run_id,
            decision_type=decision.decision_type,
            created_at=datetime.now(UTC),
        )
