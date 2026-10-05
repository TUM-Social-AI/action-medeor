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

from app.catalog.package_contents import package_from_erp_description
from app.catalog.state import restriction_flags
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
from app.matching.packaging import required_stock_quantity


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
        self, *, domain: ProductDomain, snapshot_id: str | None = None,
        item_numbers: Sequence[str] | None = None,
    ) -> list[InventoryItemV1]:
        result = await self._session.execute(
            text(
                """
                WITH snapshot AS (
                    SELECT import_sequence FROM catalog_imports
                    WHERE CAST(combined_source_snapshot_id AS TEXT) = :snapshot_id
                ), versions AS (
                    SELECT v.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY v.item_number ORDER BY v.version_sequence DESC
                           ) AS row_number
                    FROM catalog_item_versions v
                    LEFT JOIN catalog_imports vi ON vi.combined_source_snapshot_id = v.source_snapshot_id
                    WHERE CAST(:snapshot_id AS TEXT) IS NULL
                       OR vi.import_sequence <= (SELECT import_sequence FROM snapshot)
                       OR ((SELECT import_sequence FROM snapshot) IS NULL
                           AND CAST(v.source_snapshot_id AS TEXT) = :snapshot_id)
                ), inventory AS (
                    SELECT i.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY i.item_number ORDER BY i.inventory_sequence DESC
                           ) AS row_number
                    FROM inventory_snapshots i
                    WHERE CAST(:snapshot_id AS TEXT) IS NULL
                       OR CAST(i.source_snapshot_id AS TEXT) = :snapshot_id
                )
                SELECT c.item_number, COALESCE(v.domain, c.domain) AS domain,
                       (c.active AND COALESCE(v.matching_eligible, c.matching_eligible) AND
                        (CAST(:snapshot_id AS TEXT) IS NOT NULL OR NOT c.source_missing)) AS active,
                       c.quality_blocked,
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
                WHERE COALESCE(v.domain, c.domain) = :domain
                  AND (CAST(:snapshot_id AS TEXT) IS NULL OR i.id IS NOT NULL)
                  AND (CAST(:item_numbers AS TEXT[]) IS NULL
                       OR c.item_number = ANY(CAST(:item_numbers AS TEXT[])))
                ORDER BY c.item_number
                """
            ),
            {"domain": domain.value, "snapshot_id": snapshot_id,
             "item_numbers": list(item_numbers) if item_numbers is not None else None},
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
                    package=_package(row["package"]) or package_from_erp_description(
                        row["descriptions"][0] if row["descriptions"] else "",
                        ((row["attributes"] or {}).get("base_unit") or {}).get("value")
                        or (stock.unit if stock else None),
                    ),
                    replenishment_method=row["replenishment_method"],
                    t1=row["t1"],
                    active=row["active"],
                    quality_blocked=row["quality_blocked"],
                    **restriction_flags(row["attributes"]),
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
        snapshot_id: str | None = None,
        eligible_item_numbers: Sequence[str] | None = None,
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
                WITH snapshot AS (
                    SELECT import_sequence FROM catalog_imports
                    WHERE CAST(combined_source_snapshot_id AS TEXT) = :snapshot_id
                ), latest_versions AS (
                    SELECT v.id, v.item_number, v.domain, v.matching_eligible,
                           v.attributes, v.family_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY v.item_number ORDER BY v.version_sequence DESC
                           ) AS row_number
                    FROM catalog_item_versions v
                    LEFT JOIN catalog_imports vi ON vi.combined_source_snapshot_id = v.source_snapshot_id
                    WHERE CAST(:snapshot_id AS TEXT) IS NULL
                       OR vi.import_sequence <= (SELECT import_sequence FROM snapshot)
                       OR ((SELECT import_sequence FROM snapshot) IS NULL
                           AND CAST(v.source_snapshot_id AS TEXT) = :snapshot_id)
                )
                SELECT lv.item_number,
                       1 - (pe.embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM product_embeddings pe
                JOIN latest_versions lv ON lv.id = pe.catalog_item_version_id
                                         AND lv.row_number = 1
                JOIN catalog_items c ON c.item_number = lv.item_number
                WHERE pe.model_id = :model_id
                  AND COALESCE(lv.domain, c.domain) = :domain
                  AND c.active = TRUE
                  AND COALESCE(lv.matching_eligible, c.matching_eligible) = TRUE
                  AND NOT (RIGHT(lv.item_number, 2) = '00'
                           AND COALESCE(TRIM(lv.family_id), '') = '')
                  AND COALESCE(lv.attributes->'blocked'->>'value', 'false') != 'true'
                  AND COALESCE(lv.attributes->'sales_blocked'->>'value', 'false') != 'true'
                  AND (CAST(:eligible_items AS text[]) IS NULL
                       OR lv.item_number = ANY(CAST(:eligible_items AS text[])))
                  AND (CAST(:snapshot_id AS TEXT) IS NOT NULL OR c.source_missing = FALSE)
                  AND (CAST(:snapshot_id AS TEXT) IS NULL OR EXISTS (
                      SELECT 1 FROM inventory_snapshots si
                      WHERE si.item_number = lv.item_number
                        AND CAST(si.source_snapshot_id AS TEXT) = :snapshot_id
                  ))
                ORDER BY pe.embedding <=> CAST(:embedding AS vector), lv.item_number
                LIMIT :limit
                """
            ),
            {
                "embedding": _vector_literal(embedding),
                "model_id": model_id,
                "domain": domain.value,
                "limit": limit,
                "snapshot_id": snapshot_id,
                "eligible_items": list(eligible_item_numbers)
                if eligible_item_numbers is not None
                else None,
            },
        )
        return [
            RetrievalHit(
                item_number=row["item_number"],
                retriever="vector",
                rank=rank,
                score=float(row["similarity"]),
                details={"model_id": model_id, "catalog_snapshot_id": snapshot_id},
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
                WHERE h.is_current = TRUE AND h.active = TRUE AND h.matching_eligible
                  AND COALESCE(h.metadata_json->>'extraction_status', '') != 'mock'
                  AND (
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
        return self._records(result.mappings())

    @staticmethod
    def _records(rows) -> list[HistoricalOfferV1]:
        offers: list[HistoricalOfferV1] = []
        for row in rows:
            source = SourceReferenceV1(
                source_type=row["source_type"],
                document_id=row["document_id"],
                external_id=row["external_id"],
                uri=row["uri"],
                checksum=row["checksum"],
                captured_at=row["source_captured_at"],
                locator={
                    **(row["locator"] or {}),
                    **(
                        {"source_id": row["metadata_json"]["source_id"]}
                        if (row["metadata_json"] or {}).get("source_id")
                        else {}
                    ),
                },
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
                    unit_price=row["unit_price"],
                    unit_price_unit=row["unit_price_unit"],
                    offer_date=row["offer_date"],
                    valid_until=row["valid_until"],
                    metadata=row["metadata_json"] or {},
                    domain=row.get("domain"),
                    source=source,
                )
            )
        return offers

    async def search_offers(self, *, query, domain, limit, embedding=None, model_id=None):
        from app.matching.domain import SearchRepresentation
        from app.matching.representation import normalize_text, tokenize
        from app.matching.retrieval.history import HistoryRetriever

        params = {
            "domain": domain.value,
            "limit": limit,
            "query": " OR ".join(sorted(tokenize(query))),
        }
        base = """
            SELECT h.*,s.source_type,s.document_id,s.external_id,s.uri,s.checksum,
                   s.captured_at AS source_captured_at,s.locator
            FROM historical_offers h JOIN source_snapshots s ON s.id=h.source_snapshot_id
        """
        eligible = """h.is_current AND h.active AND h.matching_eligible AND h.domain=:domain
            AND h.item_number IS NULL
            AND COALESCE(h.metadata_json->>'extraction_status','') != 'mock'"""
        document = (
            "to_tsvector('simple',COALESCE(h.offered_description,'') || ' ' || h.raw_request_text)"
        )
        tsquery = "websearch_to_tsquery('simple',:query)"
        lexical_rows = (
            (
                await self._session.execute(
                    text(
                        base
                        + f"""
            WHERE {eligible} AND {document} @@ {tsquery}
            ORDER BY ts_rank_cd({document},{tsquery}) DESC,h.id LIMIT :limit
        """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        lexical = HistoryRetriever().search_standalone(
            query=SearchRepresentation(
                semantic_core=normalize_text(query),
                canonical_text=normalize_text(query),
                tokens=tokenize(query),
                content_hash="",
            ),
            offers=self._records(lexical_rows),
            limit=limit,
        )
        vector = []
        if embedding is not None and model_id:
            dimensions = await self._session.scalar(
                text("SELECT dimensions FROM embedding_models WHERE id=:id"), {"id": model_id}
            )
            if dimensions is None or dimensions != len(embedding):
                raise ValueError("Unknown or dimension-incompatible offer embedding model")
            params.update(model=model_id, embedding=_vector_literal(embedding))
            rows = (
                (
                    await self._session.execute(
                        text(
                            base.replace(
                                "SELECT h.*",
                                "SELECT 1-(e.embedding <=> CAST(:embedding AS vector)) AS similarity,h.*",
                            )
                            + f"""
                JOIN offer_embeddings e ON e.offer_id=h.id AND e.model_id=:model
                WHERE {eligible}
                ORDER BY e.embedding <=> CAST(:embedding AS vector),h.id LIMIT :limit
            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            vector = list(zip(self._records(rows), (float(row["similarity"]) for row in rows)))
        by_id = {}
        evidence = {}
        for retriever, results in (("lexical", lexical), ("vector", vector)):
            for rank, (offer, score) in enumerate(results, 1):
                by_id[offer.record_id] = offer
                evidence.setdefault(offer.record_id, []).append(
                    RetrievalHit(
                        item_number=f"offer:{offer.record_id}",
                        retriever=retriever,
                        rank=rank,
                        score=score,
                        details={"record_id": offer.record_id},
                    )
                )
        return [(by_id[key], evidence[key]) for key in sorted(by_id)]


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
        row = (await self._session.execute(
            text("SELECT result_payload, request_payload, source_versions FROM match_runs WHERE id = :id"),
            {"id": run_id},
        )).mappings().first()
        if not row or not row["result_payload"]:
            return None
        result = MatchRunResponseV1.model_validate(row["result_payload"])
        # Older saved runs have coverage statuses but lack quantity display fields.
        # Enrich the response only; saved rankings, decisions, and payloads stay intact.
        missing = {
            candidate.item_number for candidate, payload in zip(
                result.candidates, row["result_payload"].get("candidates", []), strict=True
            )
            if candidate.candidate_type.value == "catalog" and candidate.item_number
            and any(field not in payload for field in (
                "available_quantity", "stock_unit", "required_stock_quantity"
            ))
        }
        if not missing:
            return result
        request = MatchRequestV1.model_validate(row["request_payload"])
        snapshot_id = request.catalog_snapshot_id or (row["source_versions"] or {}).get("catalog_snapshot_id")
        if snapshot_id is None:
            # Early runs did not pin an import explicitly. Use the completed import
            # available when the run started, never the current catalogue.
            snapshot_id = await self._session.scalar(text("""
                SELECT combined_source_snapshot_id FROM catalog_imports
                WHERE completed_at <= :created_at
                  AND status IN ('completed', 'completed_with_warnings')
                ORDER BY import_sequence DESC LIMIT 1
            """), {"created_at": result.created_at})
        if snapshot_id is None:
            return result
        items = {item.item_number: item for item in await PostgresCatalogRepository(self._session).list_items(
            domain=request.inquiry_line.domain, snapshot_id=str(snapshot_id),
            item_numbers=sorted(missing),
        )}
        candidates = []
        for candidate in result.candidates:
            item = items.get(candidate.item_number)
            updates = {}
            if candidate.item_number in missing and item and item.stock:
                if candidate.available_quantity is None:
                    updates["available_quantity"] = item.stock.fulfillable_quantity
                if candidate.stock_unit is None:
                    updates["stock_unit"] = item.stock.unit
                if candidate.required_stock_quantity is None:
                    updates["required_stock_quantity"] = required_stock_quantity(request.inquiry_line.quantity, item)
            candidates.append(candidate.model_copy(update=updates) if updates else candidate)
        return result.model_copy(update={"candidates": tuple(candidates)})

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
