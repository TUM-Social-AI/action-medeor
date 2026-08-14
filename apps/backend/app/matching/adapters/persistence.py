"""PostgreSQL and pgvector adapters for matching ports."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matching.contracts import (
    AttributeValue,
    HistoricalOfferV1,
    InventoryItemV1,
    MatchDecisionRequestV1,
    MatchDecisionResponseV1,
    MatchRequestV1,
    MatchRunResponseV1,
    ProductDomain,
    ProductPackage,
    QuantityValue,
    SourceReferenceV1,
    StockSnapshot,
)
from app.matching.domain import RetrievalHit
from app.matching.feedback import validate_decision_against_run


def _attributes(value: object) -> dict[str, AttributeValue]:
    if not isinstance(value, dict):
        return {}
    return {str(key): AttributeValue.model_validate(item) for key, item in value.items()}


def _package(value: object) -> ProductPackage | None:
    return ProductPackage.model_validate(value) if isinstance(value, dict) else None


def _vector_literal(embedding: Sequence[float]) -> str:
    if not embedding or not all(math.isfinite(value) for value in embedding):
        raise ValueError("Embedding must be non-empty and finite")
    return "[" + ",".join(format(float(value), ".17g") for value in embedding) + "]"


class PostgresCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_items(
        self, *, domain: ProductDomain, snapshot_id: str | None = None
    ) -> list[InventoryItemV1]:
        result = await self._session.execute(
            text(
                """
                WITH versions AS (
                    SELECT v.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY v.item_number ORDER BY v.valid_from DESC, v.id DESC
                           ) AS row_number
                    FROM catalog_item_versions v
                    WHERE (
                        CAST(:snapshot_id AS TEXT) IS NULL
                        OR CAST(v.source_snapshot_id AS TEXT) = :snapshot_id
                    )
                ), inventory AS (
                    SELECT i.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY i.item_number ORDER BY i.captured_at DESC, i.id DESC
                           ) AS row_number
                    FROM inventory_snapshots i
                )
                SELECT c.item_number, c.domain, c.active, c.quality_blocked,
                       v.descriptions, v.attributes, v.manufacturer, v.brand,
                       v.family_id, v.package, v.replenishment_method, v.t1,
                       s.source_type, s.document_id, s.external_id, s.uri,
                       s.checksum, s.captured_at AS source_captured_at, s.locator,
                       i.on_hand, i.incoming_purchase_order, i.purchasing_inquiry,
                       i.committed_order, i.unit AS stock_unit, i.captured_at AS stock_captured_at
                FROM catalog_items c
                JOIN versions v ON v.item_number = c.item_number AND v.row_number = 1
                JOIN source_snapshots s ON s.id = v.source_snapshot_id
                LEFT JOIN inventory i ON i.item_number = c.item_number AND i.row_number = 1
                WHERE c.domain = :domain
                ORDER BY c.item_number
                """
            ),
            {"domain": domain.value, "snapshot_id": snapshot_id},
        )
        items: list[InventoryItemV1] = []
        for row in result.mappings():
            source = SourceReferenceV1(
                source_type=row["source_type"],
                document_id=row["document_id"],
                external_id=row["external_id"],
                uri=row["uri"],
                checksum=row["checksum"],
                captured_at=row["source_captured_at"],
                locator=row["locator"] or {},
            )
            stock = None
            if row["stock_captured_at"] is not None:
                stock = StockSnapshot(
                    on_hand=row["on_hand"],
                    incoming_purchase_order=row["incoming_purchase_order"],
                    purchasing_inquiry=row["purchasing_inquiry"],
                    committed_order=row["committed_order"],
                    unit=row["stock_unit"],
                    captured_at=row["stock_captured_at"],
                )
            items.append(
                InventoryItemV1(
                    item_number=row["item_number"],
                    domain=row["domain"],
                    descriptions=tuple(row["descriptions"]),
                    attributes=_attributes(row["attributes"]),
                    manufacturer=row["manufacturer"],
                    brand=row["brand"],
                    family_id=row["family_id"],
                    package=_package(row["package"]),
                    replenishment_method=row["replenishment_method"],
                    t1=row["t1"],
                    active=row["active"],
                    quality_blocked=row["quality_blocked"],
                    stock=stock,
                    source=source,
                )
            )
        return items


class PgVectorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        embedding: Sequence[float],
        model_id: str,
        domain: ProductDomain,
        limit: int,
    ) -> list[RetrievalHit]:
        dimensions = await self._session.scalar(
            text("SELECT dimensions FROM embedding_models WHERE id = :model_id"),
            {"model_id": model_id},
        )
        if dimensions is None:
            raise ValueError(f"Unknown embedding model: {model_id}")
        if dimensions != len(embedding):
            raise ValueError(
                f"Embedding dimension mismatch: model expects {dimensions}, got {len(embedding)}"
            )

        result = await self._session.execute(
            text(
                """
                WITH latest_versions AS (
                    SELECT v.id, v.item_number,
                           ROW_NUMBER() OVER (
                               PARTITION BY v.item_number ORDER BY v.valid_from DESC, v.id DESC
                           ) AS row_number
                    FROM catalog_item_versions v
                )
                SELECT lv.item_number,
                       1 - (pe.embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM product_embeddings pe
                JOIN latest_versions lv ON lv.id = pe.catalog_item_version_id
                                         AND lv.row_number = 1
                JOIN catalog_items c ON c.item_number = lv.item_number
                WHERE pe.model_id = :model_id AND c.domain = :domain
                ORDER BY pe.embedding <=> CAST(:embedding AS vector), lv.item_number
                LIMIT :limit
                """
            ),
            {
                "embedding": _vector_literal(embedding),
                "model_id": model_id,
                "domain": domain.value,
                "limit": limit,
            },
        )
        return [
            RetrievalHit(
                item_number=row["item_number"],
                retriever="vector",
                rank=rank,
                score=float(row["similarity"]),
                details={"model_id": model_id},
            )
            for rank, row in enumerate(result.mappings(), start=1)
        ]


class PostgresHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_offers(
        self,
        *,
        partner_id: str | None,
        destination_country: str | None,
        limit: int,
    ) -> list[HistoricalOfferV1]:
        result = await self._session.execute(
            text(
                """
                SELECT h.*, s.source_type, s.document_id, s.external_id, s.uri,
                       s.checksum, s.captured_at AS source_captured_at, s.locator
                FROM historical_offers h
                JOIN source_snapshots s ON s.id = h.source_snapshot_id
                WHERE (
                    CAST(:partner_id AS TEXT) IS NULL
                    OR h.partner_id IS NULL
                    OR h.partner_id = :partner_id
                  )
                  AND (CAST(:country AS TEXT) IS NULL OR h.destination_country IS NULL
                       OR h.destination_country = :country)
                ORDER BY h.offer_date DESC NULLS LAST, h.id
                LIMIT :limit
                """
            ),
            {"partner_id": partner_id, "country": destination_country, "limit": limit},
        )
        offers: list[HistoricalOfferV1] = []
        for row in result.mappings():
            source = SourceReferenceV1(
                source_type=row["source_type"],
                document_id=row["document_id"],
                external_id=row["external_id"],
                uri=row["uri"],
                checksum=row["checksum"],
                captured_at=row["source_captured_at"],
                locator=row["locator"] or {},
            )
            offers.append(
                HistoricalOfferV1(
                    record_id=str(row["id"]),
                    raw_request_text=row["raw_request_text"],
                    item_number=row["item_number"],
                    offered_description=row["offered_description"],
                    partner_id=row["partner_id"],
                    destination_country=row["destination_country"],
                    supplier=row["supplier"],
                    quantity=QuantityValue.model_validate(row["quantity"])
                    if row["quantity"]
                    else None,
                    package=_package(row["package"]),
                    price=row["price"],
                    currency=row["currency"],
                    price_basis=row["price_basis"],
                    offer_date=row["offer_date"],
                    metadata=row["metadata_json"] or {},
                    source=source,
                )
            )
        return offers


class PostgresMatchRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self,
        *,
        run_id: UUID,
        request: MatchRequestV1,
        algorithm_version: str,
        policy_version: str,
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO match_runs (
                    id, inquiry_id, inquiry_line_id, status, algorithm_version,
                    policy_version, embedding_model_id, request_payload, source_versions
                ) VALUES (
                    :id, :inquiry_id, :line_id, 'running', :algorithm_version,
                    :policy_version, :embedding_model_id, CAST(:request_payload AS jsonb),
                    CAST(:source_versions AS jsonb)
                )
                """
            ),
            {
                "id": run_id,
                "inquiry_id": request.inquiry_line.inquiry_id,
                "line_id": request.inquiry_line.line_id,
                "algorithm_version": algorithm_version,
                "policy_version": policy_version,
                "embedding_model_id": request.embedding_model_id,
                "request_payload": request.model_dump_json(),
                "source_versions": _json_text({"catalog_snapshot_id": request.catalog_snapshot_id}),
            },
        )
        await self._session.commit()

    async def complete_run(self, result: MatchRunResponseV1) -> None:
        await self._session.execute(
            text(
                """
                UPDATE match_runs
                SET status = 'completed', completed_at = :completed_at,
                    embedding_model_id = :embedding_model_id,
                    result_payload = CAST(:result_payload AS jsonb), error = NULL
                WHERE id = :id
                """
            ),
            {
                "id": result.match_run_id,
                "completed_at": result.completed_at,
                "embedding_model_id": result.embedding_model_id,
                "result_payload": result.model_dump_json(),
            },
        )
        for candidate in result.candidates:
            await self._session.execute(
                text(
                    """
                    INSERT INTO match_candidates (
                        id, match_run_id, item_number, candidate_type, rank,
                        retrieval_evidence, score_components, constraint_results,
                        packaging, warnings, provenance
                    ) VALUES (
                        :id, :run_id, :item_number, :candidate_type, :rank,
                        CAST(:retrieval AS jsonb), CAST(:scores AS jsonb),
                        CAST(:constraints AS jsonb), CAST(:packaging AS jsonb),
                        CAST(:warnings AS jsonb), CAST(:provenance AS jsonb)
                    )
                    """
                ),
                {
                    "id": candidate.candidate_id,
                    "run_id": result.match_run_id,
                    "item_number": candidate.item_number,
                    "candidate_type": candidate.candidate_type.value,
                    "rank": candidate.rank,
                    "retrieval": _json_text(candidate.retrieval_evidence),
                    "scores": _json_text(candidate.score_components),
                    "constraints": _json_text(candidate.constraints),
                    "packaging": candidate.packaging.model_dump_json(),
                    "warnings": _json_text(candidate.warnings),
                    "provenance": _json_text(candidate.provenance),
                },
            )
        await self._session.commit()

    async def fail_run(self, *, run_id: UUID, error: str) -> None:
        # A failure may originate from complete_run after PostgreSQL rejected one
        # of the candidate rows. Clear that failed transaction before recording
        # the terminal audit state in a fresh one.
        await self._session.rollback()
        await self._session.execute(
            text(
                """
                UPDATE match_runs
                SET status = 'failed', completed_at = :completed_at, error = :error
                WHERE id = :id
                """
            ),
            {"id": run_id, "completed_at": datetime.now(UTC), "error": error[:4000]},
        )
        await self._session.commit()

    async def get_run(self, run_id: UUID) -> MatchRunResponseV1 | None:
        payload = await self._session.scalar(
            text("SELECT result_payload FROM match_runs WHERE id = :id"), {"id": run_id}
        )
        return MatchRunResponseV1.model_validate(payload) if payload else None

    async def save_decision(self, decision: MatchDecisionRequestV1) -> MatchDecisionResponseV1:
        run = await self.get_run(decision.match_run_id)
        if run is None:
            raise LookupError("Match run not found or not completed")
        validate_decision_against_run(decision, run)

        decision_id = uuid4()
        created_at = datetime.now(UTC)
        await self._session.execute(
            text(
                """
                INSERT INTO match_decisions (
                    id, match_run_id, inquiry_line_id, decision_type, candidate_id,
                    selected_item_number, offered_quantity, override_reason, note, actor,
                    created_at
                ) VALUES (
                    :id, :run_id, :line_id, :decision_type, :candidate_id,
                    :item_number, :quantity, :override_reason, :note, :actor, :created_at
                )
                """
            ),
            {
                "id": decision_id,
                "run_id": decision.match_run_id,
                "line_id": decision.inquiry_line_id,
                "decision_type": decision.decision_type.value,
                "candidate_id": decision.candidate_id,
                "item_number": decision.selected_item_number,
                "quantity": decision.offered_quantity,
                "override_reason": decision.override_reason,
                "note": decision.note,
                "actor": decision.actor,
                "created_at": created_at,
            },
        )
        await self._session.commit()
        return MatchDecisionResponseV1(
            decision_id=decision_id,
            match_run_id=decision.match_run_id,
            decision_type=decision.decision_type,
            created_at=created_at,
        )


def _json_text(value: object) -> str:
    def default(item: object) -> object:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, (datetime, UUID)):
            return str(item)
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(value, default=default, separators=(",", ":"), sort_keys=True)
