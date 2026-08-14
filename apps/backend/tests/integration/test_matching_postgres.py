from __future__ import annotations

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
    version_id = uuid4()
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
                        '["Foley urinary catheter CH18 sterile"]'::jsonb,
                        '{"charriere":{"value":18,"unit":"CH"}}'::jsonb,
                        '{"units_per_package":"10","unit":"piece"}'::jsonb,
                        'integration-content-hash', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"id": version_id, "source_id": source_id},
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
                    ) VALUES (
                        :version_id, 'integration-model', 'integration-content-hash', '[1,0]'
                    )
                    """
                ),
                {"version_id": version_id},
            )
            await session.flush()

            items = await PostgresCatalogRepository(session).list_items(
                domain=ProductDomain.EQUIPMENT
            )
            hits = await PgVectorRepository(session).search(
                embedding=(1.0, 0.0),
                model_id="integration-model",
                domain=ProductDomain.EQUIPMENT,
                limit=10,
            )

            assert items[0].item_number == "410001001"
            assert items[0].attributes["charriere"].comparable() == ("18", "ch")
            assert hits[0].item_number == "410001001"
            assert hits[0].score == pytest.approx(1.0)
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
