"""Database-backed embedding progress for one immutable catalogue import."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.contracts import CatalogEmbeddingStatusV1
from app.catalog.embedding_factory import create_embedding_provider
from app.catalog.embeddings import CatalogEmbeddingJobService
from app.core.config import get_settings


async def embedding_status(
    session: AsyncSession, import_id: UUID
) -> CatalogEmbeddingStatusV1 | None:
    snapshot = (
        (
            await session.execute(
                text(
                    "SELECT combined_source_snapshot_id, import_sequence FROM catalog_imports WHERE id = :id"
                ),
                {"id": import_id},
            )
        )
        .mappings()
        .first()
    )
    if snapshot is None:
        return None
    model_id = await session.scalar(
        text("SELECT id FROM embedding_models WHERE active = TRUE ORDER BY id LIMIT 1")
    )
    try:
        provider = create_embedding_provider(get_settings())
        error = await CatalogEmbeddingJobService(session).configuration_error(provider)
    except (ValueError, RuntimeError):
        error = "The embedding provider configuration is invalid."
    result = CatalogEmbeddingStatusV1(
        import_id=import_id, model_id=model_id, configuration_error=error
    )
    if model_id is None:
        return result
    rows = await session.execute(
        text("""
            SELECT CASE WHEN e.catalog_item_version_id IS NOT NULL THEN 'completed'
                        ELSE COALESCE(j.status, 'pending') END AS status, COUNT(*) AS count
            FROM inventory_snapshots i
            JOIN LATERAL (
                SELECT v.id, v.item_number, v.family_id, v.matching_eligible
                FROM catalog_item_versions v
                JOIN catalog_imports vi ON vi.combined_source_snapshot_id = v.source_snapshot_id
                WHERE v.item_number = i.item_number AND vi.import_sequence <= :sequence
                ORDER BY v.version_sequence DESC LIMIT 1
            ) v ON TRUE
            LEFT JOIN product_embeddings e ON e.catalog_item_version_id = v.id
                                         AND e.model_id = :model_id
            LEFT JOIN catalog_embedding_jobs j ON j.catalog_item_version_id = v.id
                                              AND j.model_id = :model_id
            WHERE i.source_snapshot_id = :snapshot_id AND v.matching_eligible = TRUE
              AND NOT (RIGHT(v.item_number, 2) = '00' AND COALESCE(TRIM(v.family_id), '') = '')
            GROUP BY 1
        """),
        {
            "snapshot_id": snapshot["combined_source_snapshot_id"],
            "sequence": snapshot["import_sequence"],
            "model_id": model_id,
        },
    )
    return result.model_copy(update={row["status"]: row["count"] for row in rows.mappings()})
