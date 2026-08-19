"""Transactional, idempotent synchronization of the ERP catalog."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.contracts import (
    CatalogImportErrorV1,
    CatalogImportResponseV1,
    CatalogImportStatus,
    CatalogImportValidationError,
    CatalogItemViewV1,
)
from app.catalog.parser import ParsedCatalogImport, parse_catalog_files


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class CatalogImportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_import(self, import_id: UUID) -> CatalogImportResponseV1 | None:
        summary = await self._session.scalar(
            text("SELECT summary FROM catalog_imports WHERE id = :id"), {"id": import_id}
        )
        return CatalogImportResponseV1.model_validate(summary) if summary else None

    async def get_item(self, item_number: str) -> CatalogItemViewV1 | None:
        result = await self._session.execute(
            text(
                """
                WITH latest_version AS (
                    SELECT * FROM catalog_item_versions
                    WHERE item_number = :item_number
                    ORDER BY valid_from DESC, id DESC LIMIT 1
                ), latest_inventory AS (
                    SELECT * FROM inventory_snapshots
                    WHERE item_number = :item_number
                    ORDER BY captured_at DESC, id DESC LIMIT 1
                )
                SELECT c.item_number, c.domain, c.matching_eligible, c.source_missing,
                       v.descriptions, v.family_id, v.attributes,
                       i.on_hand, i.incoming_purchase_order, i.committed_order,
                       CASE WHEN i.id IS NULL THEN NULL
                            ELSE i.on_hand + COALESCE(i.incoming_purchase_order, 0)
                                 - COALESCE(i.committed_order, 0) END AS available_raw,
                       CASE WHEN i.id IS NULL THEN NULL
                            ELSE GREATEST(0, i.on_hand + COALESCE(i.incoming_purchase_order, 0)
                                 - COALESCE(i.committed_order, 0)) END AS fulfillable_quantity
                FROM catalog_items c
                LEFT JOIN latest_version v ON TRUE
                LEFT JOIN latest_inventory i ON TRUE
                WHERE c.item_number = :item_number
                """
            ),
            {"item_number": item_number},
        )
        row = result.mappings().first()
        if row is None:
            return None
        attributes = row["attributes"] or {}
        return CatalogItemViewV1(
            item_number=row["item_number"],
            domain=row["domain"],
            matching_eligible=row["matching_eligible"],
            source_missing=row["source_missing"],
            descriptions=tuple(row["descriptions"] or ()),
            family_id=row["family_id"],
            base_unit=(attributes.get("base_unit") or {}).get("value"),
            available_raw=str(row["available_raw"])
            if row["available_raw"] is not None
            else None,
            fulfillable_quantity=str(row["fulfillable_quantity"])
            if row["fulfillable_quantity"] is not None
            else None,
            metadata={"attributes": attributes},
        )

    async def import_files(
        self,
        *,
        article_data: bytes,
        translation_data: bytes,
        article_filename: str,
        translation_filename: str,
        captured_at: datetime | None = None,
        source_uri: str | None = None,
    ) -> CatalogImportResponseV1:
        parsed = parse_catalog_files(article_data, translation_data)
        captured_at = captured_at or datetime.now(UTC)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('allocura-catalog-import-v1'))")
        )
        previous = await self._session.execute(
            text(
                """
                SELECT id, summary
                FROM catalog_imports
                WHERE article_checksum = :article_checksum
                  AND translation_checksum = :translation_checksum
                  AND status IN ('completed', 'completed_with_warnings')
                """
            ),
            {
                "article_checksum": parsed.article_checksum,
                "translation_checksum": parsed.translation_checksum,
            },
        )
        existing_import = previous.mappings().first()
        if existing_import:
            response = CatalogImportResponseV1.model_validate(existing_import["summary"])
            await self._session.rollback()
            return response.model_copy(update={"idempotent_replay": True})

        try:
            return await self._apply_import(
                parsed=parsed,
                article_filename=article_filename,
                translation_filename=translation_filename,
                captured_at=captured_at,
                source_uri=source_uri,
            )
        except Exception:
            await self._session.rollback()
            raise

    async def _source_snapshot(
        self,
        *,
        document_id: str,
        checksum: str,
        captured_at: datetime,
        uri: str | None,
        metadata: dict[str, object],
    ) -> UUID:
        existing = await self._session.scalar(
            text(
                """
                SELECT id FROM source_snapshots
                WHERE source_type = 'erp' AND document_id = :document_id AND checksum = :checksum
                """
            ),
            {"document_id": document_id, "checksum": checksum},
        )
        if existing:
            return existing
        snapshot_id = uuid4()
        await self._session.execute(
            text(
                """
                INSERT INTO source_snapshots (
                    id, source_type, document_id, uri, checksum, captured_at, locator, metadata_json
                ) VALUES (
                    :id, 'erp', :document_id, :uri, :checksum, :captured_at,
                    '{}'::jsonb, CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "id": snapshot_id,
                "document_id": document_id,
                "uri": uri,
                "checksum": checksum,
                "captured_at": captured_at,
                "metadata": _json(metadata),
            },
        )
        return snapshot_id

    async def _apply_import(
        self,
        *,
        parsed: ParsedCatalogImport,
        article_filename: str,
        translation_filename: str,
        captured_at: datetime,
        source_uri: str | None,
    ) -> CatalogImportResponseV1:
        import_id = uuid4()
        # source_snapshots.checksum is VARCHAR(128). Hash the ordered pair instead of storing
        # two 64-character digests plus a separator (129 characters).
        combined_checksum = hashlib.sha256(
            f"{parsed.article_checksum}:{parsed.translation_checksum}".encode()
        ).hexdigest()
        article_source_id = await self._source_snapshot(
            document_id=article_filename,
            checksum=parsed.article_checksum,
            captured_at=captured_at,
            uri=source_uri,
            metadata={"role": "article_data", "import_id": str(import_id)},
        )
        translation_source_id = await self._source_snapshot(
            document_id=translation_filename,
            checksum=parsed.translation_checksum,
            captured_at=captured_at,
            uri=source_uri,
            metadata={"role": "article_translations", "import_id": str(import_id)},
        )
        combined_source_id = await self._source_snapshot(
            document_id="erp-catalog-import",
            checksum=combined_checksum,
            captured_at=captured_at,
            uri=source_uri,
            metadata={
                "article_source_snapshot_id": str(article_source_id),
                "translation_source_snapshot_id": str(translation_source_id),
                "import_id": str(import_id),
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO catalog_imports (
                    id, article_source_snapshot_id, translation_source_snapshot_id,
                    combined_source_snapshot_id, article_checksum, translation_checksum,
                    status, summary, warnings, started_at
                ) VALUES (
                    :id, :article_source_id, :translation_source_id, :combined_source_id,
                    :article_checksum, :translation_checksum, 'running', '{}'::jsonb,
                    CAST(:warnings AS jsonb), :started_at
                )
                """
            ),
            {
                "id": import_id,
                "article_source_id": article_source_id,
                "translation_source_id": translation_source_id,
                "combined_source_id": combined_source_id,
                "article_checksum": parsed.article_checksum,
                "translation_checksum": parsed.translation_checksum,
                "warnings": _json(parsed.warnings),
                "started_at": captured_at,
            },
        )

        previous_result = await self._session.execute(
            text(
                """
                WITH latest_versions AS (
                    SELECT DISTINCT ON (item_number)
                           item_number, content_hash, record_hash, id
                    FROM catalog_item_versions
                    ORDER BY item_number, valid_from DESC, id DESC
                )
                SELECT c.item_number, c.source_missing, v.content_hash, v.record_hash,
                       v.id AS version_id
                FROM catalog_items c
                LEFT JOIN latest_versions v ON v.item_number = c.item_number
                WHERE c.last_seen_import_id IS NOT NULL
                """
            )
        )
        previous = {row["item_number"]: row for row in previous_result.mappings()}
        if previous and len(parsed.items) * 2 < len(previous):
            raise CatalogImportValidationError(
                [
                    CatalogImportErrorV1(
                        code="suspicious_row_drop",
                        message=(
                            "The new article report contains less than half of the previously "
                            "known article numbers; import was stopped to avoid mass-missing flags."
                        ),
                    )
                ]
            )
        current_numbers = {item.item_number for item in parsed.items}
        inserted = sum(item.item_number not in previous for item in parsed.items)
        text_changed = sum(
            item.item_number in previous
            and previous[item.item_number]["content_hash"] != item.content_hash
            for item in parsed.items
        )
        metadata_changed = sum(
            item.item_number in previous
            and previous[item.item_number]["content_hash"] == item.content_hash
            and previous[item.item_number]["record_hash"] != item.record_hash
            for item in parsed.items
        )
        unchanged = len(parsed.items) - inserted - text_changed - metadata_changed
        newly_missing = sum(
            item_number not in current_numbers and not row["source_missing"]
            for item_number, row in previous.items()
        )
        reactivated = sum(
            item.item_number in previous and previous[item.item_number]["source_missing"]
            for item in parsed.items
        )

        catalog_rows = [
            {
                "item_number": item.item_number,
                "domain": item.domain,
                "matching_eligible": item.matching_eligible,
                "import_id": import_id,
            }
            for item in parsed.items
        ]
        await self._session.execute(
            text(
                """
                INSERT INTO catalog_items (
                    item_number, domain, matching_eligible, source_missing,
                    last_seen_import_id, missing_since_import_id, updated_at
                ) VALUES (
                    :item_number, :domain, :matching_eligible, FALSE,
                    :import_id, NULL, CURRENT_TIMESTAMP
                )
                ON CONFLICT (item_number) DO UPDATE SET
                    domain = EXCLUDED.domain,
                    matching_eligible = EXCLUDED.matching_eligible,
                    source_missing = FALSE,
                    last_seen_import_id = EXCLUDED.last_seen_import_id,
                    missing_since_import_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            catalog_rows,
        )

        version_rows: list[dict[str, object]] = []
        reusable_embedding_rows: list[dict[str, UUID]] = []
        for item in parsed.items:
            old = previous.get(item.item_number)
            if old and old["record_hash"] == item.record_hash:
                continue
            version_id = uuid4()
            if old and old["content_hash"] == item.content_hash:
                reusable_embedding_rows.append(
                    {"new_version_id": version_id, "old_version_id": old["version_id"]}
                )
            attributes = {
                "category_code": {"value": item.category_code or "unknown"},
                "base_unit": {"value": item.base_unit or "unknown"},
                "master_item": {"value": item.master_item},
            }
            version_rows.append(
                {
                    "id": version_id,
                    "item_number": item.item_number,
                    "source_snapshot_id": combined_source_id,
                    "descriptions": _json(item.descriptions),
                    "attributes": _json(attributes),
                    "family_id": item.family_id,
                    "replenishment_method": item.replenishment_method,
                    "t1": item.t1,
                    "canonical_text": item.canonical_text,
                    "content_hash": item.content_hash,
                    "record_hash": item.record_hash,
                    "valid_from": captured_at,
                }
            )
        if version_rows:
            await self._session.execute(
                text(
                    """
                    INSERT INTO catalog_item_versions (
                        id, item_number, source_snapshot_id, descriptions, attributes,
                        family_id, replenishment_method, t1, canonical_text,
                        content_hash, record_hash, valid_from
                    ) VALUES (
                        :id, :item_number, :source_snapshot_id, CAST(:descriptions AS jsonb),
                        CAST(:attributes AS jsonb), :family_id, :replenishment_method, :t1,
                        :canonical_text, :content_hash, :record_hash, :valid_from
                    )
                    """
                ),
                version_rows,
            )

        if reusable_embedding_rows:
            await self._session.execute(
                text(
                    """
                    INSERT INTO product_embeddings (
                        catalog_item_version_id, model_id, content_hash, embedding
                    )
                    SELECT :new_version_id, model_id, content_hash, embedding
                    FROM product_embeddings
                    WHERE catalog_item_version_id = :old_version_id
                    ON CONFLICT (catalog_item_version_id, model_id) DO NOTHING
                    """
                ),
                reusable_embedding_rows,
            )

        translation_rows = [
            {
                "id": uuid4(),
                "item_number": item.item_number,
                "source_snapshot_id": translation_source_id,
                "raw_language_code": translation.raw_language_code,
                "locale": translation.locale,
                "description": translation.description,
                "description_2": translation.description_2,
                "content_hash": translation.content_hash,
                "captured_at": captured_at,
            }
            for item in parsed.items
            for translation in item.translations
        ]
        if translation_rows:
            await self._session.execute(
                text(
                    """
                    INSERT INTO catalog_item_translations (
                        id, item_number, source_snapshot_id, raw_language_code, locale,
                        description, description_2, content_hash, captured_at
                    ) VALUES (
                        :id, :item_number, :source_snapshot_id, :raw_language_code, :locale,
                        :description, :description_2, :content_hash, :captured_at
                    )
                    ON CONFLICT (
                        item_number, source_snapshot_id, raw_language_code
                    ) DO NOTHING
                    """
                ),
                translation_rows,
            )

        inventory_rows = [
            {
                "id": uuid4(),
                "item_number": item.item_number,
                "source_snapshot_id": combined_source_id,
                "on_hand": item.on_hand,
                "incoming": item.incoming_purchase_order,
                "committed": item.committed_order,
                "unit": item.base_unit,
                "captured_at": captured_at,
            }
            for item in parsed.items
        ]
        await self._session.execute(
            text(
                """
                INSERT INTO inventory_snapshots (
                    id, item_number, source_snapshot_id, on_hand, incoming_purchase_order,
                    committed_order, unit, captured_at
                ) VALUES (
                    :id, :item_number, :source_snapshot_id, :on_hand, :incoming,
                    :committed, :unit, :captured_at
                )
                """
            ),
            inventory_rows,
        )

        await self._session.execute(
            text(
                """
                UPDATE catalog_items
                SET source_missing = TRUE,
                    missing_since_import_id = COALESCE(missing_since_import_id, :import_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE last_seen_import_id IS NOT NULL AND last_seen_import_id <> :import_id
                """
            ),
            {"import_id": import_id},
        )

        active_models = list(
            (
                await self._session.scalars(
                    text("SELECT id FROM embedding_models WHERE active = TRUE ORDER BY id")
                )
            ).all()
        )
        eligibility_by_item = {
            item.item_number: item.matching_eligible for item in parsed.items
        }
        eligible_version_ids = [
            row["id"]
            for row in version_rows
            if eligibility_by_item[str(row["item_number"])]
        ]
        existing_embedding_pairs: set[tuple[UUID, str]] = set()
        if eligible_version_ids and active_models:
            existing_result = await self._session.execute(
                text(
                    """
                    SELECT catalog_item_version_id, model_id
                    FROM product_embeddings
                    WHERE catalog_item_version_id = ANY(CAST(:version_ids AS uuid[]))
                      AND model_id = ANY(CAST(:model_ids AS text[]))
                    """
                ),
                {"version_ids": eligible_version_ids, "model_ids": active_models},
            )
            existing_embedding_pairs = {
                (row["catalog_item_version_id"], row["model_id"])
                for row in existing_result.mappings()
            }
        job_rows = [
            {"id": uuid4(), "version_id": version_id, "model_id": model_id}
            for version_id in eligible_version_ids
            for model_id in active_models
            if (version_id, model_id) not in existing_embedding_pairs
        ]
        if job_rows:
            await self._session.execute(
                text(
                    """
                    INSERT INTO catalog_embedding_jobs (
                        id, catalog_item_version_id, model_id, status
                    ) VALUES (:id, :version_id, :model_id, 'pending')
                    ON CONFLICT (catalog_item_version_id, model_id) DO NOTHING
                    """
                ),
                job_rows,
            )

        completed_at = datetime.now(UTC)
        status = (
            CatalogImportStatus.COMPLETED_WITH_WARNINGS
            if parsed.warnings
            else CatalogImportStatus.COMPLETED
        )
        response = CatalogImportResponseV1(
            import_id=import_id,
            status=status,
            inserted_items=inserted,
            text_updated_items=text_changed,
            metadata_updated_items=metadata_changed,
            unchanged_items=unchanged,
            inventory_refreshed_items=len(parsed.items),
            missing_items=newly_missing,
            reactivated_items=reactivated,
            embedding_jobs_created=len(job_rows),
            warnings=parsed.warnings,
            completed_at=completed_at,
        )
        await self._session.execute(
            text(
                """
                UPDATE catalog_imports
                SET status = :status, summary = CAST(:summary AS jsonb), completed_at = :completed_at
                WHERE id = :id
                """
            ),
            {
                "id": import_id,
                "status": status.value,
                "summary": response.model_dump_json(),
                "completed_at": completed_at,
            },
        )
        await self._session.commit()
        return response
