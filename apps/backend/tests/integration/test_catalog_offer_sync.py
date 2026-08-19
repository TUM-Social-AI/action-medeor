from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.service import CatalogImportService
from app.offers.contracts import NormalizedOfferUpsertV1, SharePointOfferFileUpsertV1
from app.offers.files import SharePointOfferFileService
from app.offers.service import OfferRepositoryService

pytestmark = pytest.mark.integration

ARTICLE_HEADER = (
    "Nr.;Nummer 2;Beschreibung;Beschreibung 2;Basiseinheit;Artikelkategoriencode;"
    "Zollware (T1);Lagerbestand;Menge in Bestellung;Menge in Auftrag;"
    "Wiederbeschaffungsverfahren\r\n"
)
TRANSLATION_HEADER = "Artikelnr.;Sprachcode;Beschreibung;Beschreibung 2\r\n"


@pytest.mark.asyncio
async def test_catalog_versions_missing_state_and_offer_archive() -> None:
    database_url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:10]
    item_one = f"4{suffix}1"
    item_two = f"4{suffix}2"
    offer_external_id = f"test-offer-{suffix}"
    source_marker = f"integration-{suffix}"
    first_articles = (
        ARTICLE_HEADER
        + f"{item_one};;Foley catheter CH18;;STÜCK;404;nein;10;5;12;2\r\n"
        + f"{item_two};;Foley catheter CH12;;STÜCK;404;nein;50;0;0;2\r\n"
    ).encode()
    second_articles = (
        ARTICLE_HEADER
        + f"{item_one};;Foley urinary catheter sterile CH18;;STÜCK;404;nein;7;5;20;2\r\n"
    ).encode()
    quantity_only_articles = (
        ARTICLE_HEADER
        + f"{item_one};;Foley urinary catheter sterile CH18;;STÜCK;404;nein;9;5;20;2\r\n"
    ).encode()
    translations = (
        TRANSLATION_HEADER + f"{item_one};FRA;Sonde de Foley CH18;;\r\n"
    ).encode()
    captured_at = datetime(2026, 8, 19, 9, tzinfo=UTC)

    try:
        async with sessions() as session:
            service = CatalogImportService(session)
            first = await service.import_files(
                article_data=first_articles,
                translation_data=translations,
                article_filename=f"{source_marker}-articles-v1.csv",
                translation_filename=f"{source_marker}-translations.csv",
                captured_at=captured_at,
            )
            assert first.inserted_items == 2

        async with sessions() as session:
            service = CatalogImportService(session)
            second = await service.import_files(
                article_data=second_articles,
                translation_data=translations,
                article_filename=f"{source_marker}-articles-v2.csv",
                translation_filename=f"{source_marker}-translations.csv",
                captured_at=captured_at,
            )
            assert second.text_updated_items == 1
            assert second.missing_items == 1
            view = await service.get_item(item_one)
            assert view is not None
            assert view.available_raw == "-8"
            assert view.fulfillable_quantity == "0"

        async with sessions() as session:
            quantity_only = await CatalogImportService(session).import_files(
                article_data=quantity_only_articles,
                translation_data=translations,
                article_filename=f"{source_marker}-articles-v3.csv",
                translation_filename=f"{source_marker}-translations.csv",
                captured_at=captured_at,
            )
            assert quantity_only.text_updated_items == 0
            assert quantity_only.metadata_updated_items == 0
            assert quantity_only.unchanged_items == 1
            assert quantity_only.inventory_refreshed_items == 1

        async with sessions() as session:
            replay = await CatalogImportService(session).import_files(
                article_data=quantity_only_articles,
                translation_data=translations,
                article_filename=f"{source_marker}-articles-v3.csv",
                translation_filename=f"{source_marker}-translations.csv",
                captured_at=captured_at,
            )
            assert replay.idempotent_replay is True

        async with sessions() as session:
            version_count = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM catalog_item_versions WHERE item_number = :item_number"
                ),
                {"item_number": item_one},
            )
            missing = await session.scalar(
                text("SELECT source_missing FROM catalog_items WHERE item_number = :item_number"),
                {"item_number": item_two},
            )
            assert version_count == 2
            assert missing is True

        offer_payload = NormalizedOfferUpsertV1(
            source_version="etag-1",
            source_url=f"https://medeor.sharepoint.com/sites/TheLabworks/{offer_external_id}.xlsx",
            captured_at=captured_at,
            raw_request_text="Foley catheter CH18",
            item_number=item_one,
        )
        file_payload = SharePointOfferFileUpsertV1(
            source_version="etag-1",
            source_url=f"https://medeor.sharepoint.com/sites/TheLabworks/{offer_external_id}.xlsx",
            captured_at=captured_at,
            modified_at=captured_at,
            name=f"{offer_external_id}.xlsx",
            size_bytes=1234,
        )
        async with sessions() as session:
            files = SharePointOfferFileService(session)
            inserted_file = await files.upsert(offer_external_id, file_payload)
            replayed_file = await files.upsert(offer_external_id, file_payload)
            pending = await files.list_current(needs_extraction=True)
            assert inserted_file.structured_output_available is False
            assert replayed_file.idempotent_replay is True
            assert any(file.external_id == offer_external_id for file in pending)

        async with sessions() as session:
            offers = OfferRepositoryService(session)
            inserted = await offers.upsert(offer_external_id, offer_payload)
            replayed = await offers.upsert(offer_external_id, offer_payload)
            assert inserted.active is True
            assert replayed.idempotent_replay is True

        async with sessions() as session:
            files = SharePointOfferFileService(session)
            current_files = await files.list_current(needs_extraction=False)
            assert any(
                file.external_id == offer_external_id
                and file.structured_output_available is True
                for file in current_files
            )

        async with sessions() as session:
            archived = await OfferRepositoryService(session).archive(
                offer_external_id, source_version="etag-2"
            )
            assert archived.active is False

        async with sessions() as session:
            files = SharePointOfferFileService(session)
            current_files = await files.list_current(needs_extraction=False)
            archived_file = await files.archive(offer_external_id)
            assert any(
                file.external_id == offer_external_id
                and file.structured_output_available is False
                for file in current_files
            )
            assert archived_file.active is False

        async with sessions() as session:
            offer_versions = await session.scalar(
                text("SELECT COUNT(*) FROM historical_offers WHERE external_id = :external_id"),
                {"external_id": offer_external_id},
            )
            active_offers = await OfferRepositoryService(session).list_current()
            assert offer_versions == 2
            assert not any(offer.external_id == offer_external_id for offer in active_offers)
    finally:
        async with sessions() as session:
            await session.execute(
                text("DELETE FROM sharepoint_offer_files WHERE external_id = :external_id"),
                {"external_id": offer_external_id},
            )
            await session.execute(
                text("DELETE FROM historical_offers WHERE external_id = :external_id"),
                {"external_id": offer_external_id},
            )
            await session.execute(
                text("DELETE FROM catalog_items WHERE item_number IN (:item_one, :item_two)"),
                {"item_one": item_one, "item_two": item_two},
            )
            await session.execute(
                text(
                    """
                    DELETE FROM catalog_imports
                    WHERE id NOT IN (
                        SELECT last_seen_import_id FROM catalog_items
                        WHERE last_seen_import_id IS NOT NULL
                    )
                    AND article_source_snapshot_id IN (
                        SELECT id FROM source_snapshots WHERE document_id LIKE :marker
                    )
                    """
                ),
                {"marker": f"{source_marker}%"},
            )
            await session.execute(
                text(
                    """
                    DELETE FROM source_snapshots
                    WHERE (document_id LIKE :marker OR document_id = :offer_id)
                      AND id NOT IN (SELECT source_snapshot_id FROM historical_offers)
                      AND id NOT IN (SELECT source_snapshot_id FROM catalog_item_versions)
                      AND id NOT IN (SELECT source_snapshot_id FROM inventory_snapshots)
                      AND id NOT IN (SELECT source_snapshot_id FROM catalog_item_translations)
                      AND id NOT IN (SELECT article_source_snapshot_id FROM catalog_imports)
                      AND id NOT IN (SELECT translation_source_snapshot_id FROM catalog_imports)
                      AND id NOT IN (SELECT combined_source_snapshot_id FROM catalog_imports)
                    """
                ),
                {"marker": f"{source_marker}%", "offer_id": offer_external_id},
            )
            await session.commit()
        await engine.dispose()
