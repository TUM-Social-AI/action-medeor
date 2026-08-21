from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.matching.adapters.persistence import PgVectorRepository, PostgresCatalogRepository
from app.matching.contracts import ProductDomain

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_catalog_and_exact_pgvector_search_against_migrated_database() -> None:
    database_url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")

    engine = create_async_engine(database_url)
    source_id = uuid4()
    current_source_id = uuid4()
    version_id = uuid4()
    current_version_id = uuid4()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO source_snapshots (
                        id, source_type, document_id, checksum, captured_at, locator, metadata_json
                    ) VALUES (
                        :id, 'erp', 'integration-catalog', 'integration-checksum',
                        CURRENT_TIMESTAMP, '{}'::jsonb, '{}'::jsonb
                    )
                    """
                ),
                {"id": source_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO source_snapshots (
                        id, source_type, document_id, checksum, captured_at, locator, metadata_json
                    ) VALUES (
                        :id, 'erp', 'integration-catalog-current',
                        'integration-checksum-current', CURRENT_TIMESTAMP,
                        '{}'::jsonb, '{}'::jsonb
                    )
                    """
                ),
                {"id": current_source_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO catalog_items (item_number, domain)
                    VALUES ('410001001', 'equipment')
                    """
                )
            )
            await session.execute(
                text(
                    """
                    INSERT INTO catalog_item_versions (
                        id, item_number, source_snapshot_id, descriptions, attributes,
                        package, content_hash, valid_from
                    ) VALUES (
                        :id, '410001001', :source_id,
                        CAST(:descriptions AS jsonb),
                        CAST(:attributes AS jsonb),
                        CAST(:package AS jsonb),
                        'integration-content-hash', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": version_id,
                    "source_id": source_id,
                    "descriptions": json.dumps(["Foley urinary catheter CH18 sterile"]),
                    "attributes": json.dumps(
                        {"charriere": {"value": 18, "unit": "CH"}}
                    ),
                    "package": json.dumps(
                        {"units_per_package": "10", "unit": "piece"}
                    ),
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO catalog_item_versions (
                        id, item_number, source_snapshot_id, descriptions, attributes,
                        package, content_hash, valid_from
                    ) VALUES (
                        :id, '410001001', :source_id,
                        CAST(:descriptions AS jsonb),
                        CAST(:attributes AS jsonb),
                        CAST(:package AS jsonb),
                        'integration-content-hash-current', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": current_version_id,
                    "source_id": current_source_id,
                    "descriptions": json.dumps(["Current catheter CH12"]),
                    "attributes": json.dumps(
                        {"charriere": {"value": 12, "unit": "CH"}}
                    ),
                    "package": json.dumps(
                        {"units_per_package": "10", "unit": "piece"}
                    ),
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO inventory_snapshots (
                        id, item_number, source_snapshot_id, on_hand, unit, captured_at
                    ) VALUES
                        (:old_id, '410001001', :old_source_id, 7, 'piece', CURRENT_TIMESTAMP),
                        (:current_id, '410001001', :current_source_id, 20, 'piece',
                         CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "old_id": uuid4(),
                    "old_source_id": source_id,
                    "current_id": uuid4(),
                    "current_source_id": current_source_id,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO embedding_models (
                        id, provider, name, version, dimensions, distance_metric
                    ) VALUES ('integration-model', 'test', 'integration', '1', 2, 'cosine')
                    """
                )
            )
            await session.execute(
                text(
                    """
                    INSERT INTO product_embeddings (
                        catalog_item_version_id, model_id, content_hash, embedding
                    ) VALUES
                        (:version_id, 'integration-model', 'integration-content-hash', '[1,0]'),
                        (:current_version_id, 'integration-model',
                         'integration-content-hash-current', '[0,1]')
                    """
                ),
                {"version_id": version_id, "current_version_id": current_version_id},
            )
            await session.flush()

            items = await PostgresCatalogRepository(session).list_items(
                domain=ProductDomain.EQUIPMENT,
                snapshot_id=str(source_id),
            )
            hits = await PgVectorRepository(session).search(
                embedding=(1.0, 0.0),
                model_id="integration-model",
                domain=ProductDomain.EQUIPMENT,
                limit=10,
                snapshot_id=str(source_id),
            )
            latest_items = await PostgresCatalogRepository(session).list_items(
                domain=ProductDomain.EQUIPMENT
            )

            assert items[0].item_number == "410001001"
            assert items[0].attributes["charriere"].comparable() == ("18", "ch")
            assert items[0].stock is not None
            assert items[0].stock.on_hand == 7
            assert hits[0].item_number == "410001001"
            assert hits[0].score == pytest.approx(1.0)
            assert latest_items[0].attributes["charriere"].comparable() == ("12", "ch")
            assert latest_items[0].stock is not None
            assert latest_items[0].stock.on_hand == 20
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
