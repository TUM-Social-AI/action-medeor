"""Offline end-to-end pipeline: PostgreSQL/pgvector with mocked Graph, Luna and embeddings."""

import os
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.embeddings import EmbeddingModelSpec
from app.core.config import Settings
from app.jobs import sharepoint_sync as job
from app.matching.adapters.persistence import PostgresHistoryRepository
from app.matching.contracts import ProductDomain
from app.offers.embeddings import process_file, register_model
from app.offers.files import SharePointOfferFileService
from app.sharepoint.changes import SharePointChange, parse_item
from app.sharepoint.extraction import DownloadedDocument, normalize
from app.sharepoint.processing import archive_file, claim, enqueue, publish
from tests.test_offer_pipeline import batch_result, offered

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_single_document_pipeline_replay_versions_failures_and_matching(monkeypatch):
    url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    root = "root-" + suffix
    equipment = "equipment-" + suffix
    medicine = "medicine-" + suffix
    file_id = "file-" + suffix
    drive = "drive-" + suffix
    settings = Settings(
        _env_file=None,
        sharepoint_equipment_folder_id=equipment,
        sharepoint_medication_folder_id=medicine,
        embedding_batch_size=2,
    )

    class Graph:
        drive_id = drive
        ctag = "c1"
        downloads = 0
        change_during_extraction = False

        async def get_item(self, id):
            if id == root:
                return {"id": root, "name": "Offers", "folder": {}}
            if id in (equipment, medicine):
                return {"id": id, "name": id, "folder": {}, "parentReference": {"id": root}}
            assert id == file_id
            return {
                "id": id,
                "name": "offer.pdf",
                "file": {"mimeType": "application/pdf"},
                "parentReference": {"id": equipment},
                "cTag": self.ctag,
                "eTag": "e1",
                "size": 5,
                "createdDateTime": "2026-10-02T00:00:00Z",
                "webUrl": "https://example.sharepoint.com/offer.pdf",
            }

        async def download(self, id, *, max_bytes):
            assert id == file_id
            self.downloads += 1
            return b"offer"

        async def list_children(self, *args):
            raise AssertionError("process-one must not enumerate documents")

    class Provider:
        model_id = "test-offer-" + suffix
        calls = 0
        bad_dimensions = False

        async def spec(self):
            return EmbeddingModelSpec(self.model_id, "test", "test", "v1", 3)

        async def embed_documents(self, texts):
            self.calls += 1
            return [[1, 0] if self.bad_dimensions else [1, 0, 0] for _ in texts]

        async def embed_queries(self, texts):
            return [[1, 0, 0] for _ in texts]

    graph = Graph()
    provider = Provider()
    extraction_calls = []
    rows = [
        offered(),
        offered(alternative_index=2, price_amount="70"),
        offered(source_id="Sheet!A2:supplier2", supplier="Supplier B", price_conflict=True),
    ]

    async def extractor(change, document, **kwargs):
        extraction_calls.append(change.item.ctag)
        if graph.change_during_extraction:
            graph.ctag = "c4"
        return normalize(change, document, batch_result(rows))

    monkeypatch.setattr(job, "async_session", sessions)
    monkeypatch.setattr(job, "create_embedding_provider", lambda settings: provider)
    monkeypatch.setattr("app.matching.api.create_embedding_provider", lambda settings: provider)
    try:
        first = await job.process_one(graph, root, file_id, settings, extractor=extractor)
        assert first["processed"] == 1 and first["offers"] == 3
        assert first["matching"]["verified"]
        candidate = first["matching"]["candidates"][0]
        assert candidate["offer_date_source"] == "sharepoint_created"
        assert candidate["offer_validity_source"] == "relative_sharepoint_created"
        assert candidate["offer_valid_until"] == "2026-10-16"
        assert candidate["price_basis"] == "100 Stück"
        repeat = await job.process_one(graph, root, file_id, settings, extractor=extractor)
        assert repeat["idempotent_replay"] and graph.downloads == 1 and provider.calls == 1
        assert extraction_calls == ["c1"]
        async with sessions() as session:
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM sharepoint_sync_sources WHERE drive_id=:drive"),
                    {"drive": drive},
                )
                == 0
            )
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM catalog_embedding_jobs WHERE model_id=:model"),
                    {"model": provider.model_id},
                )
                == 0
            )
            assert not any(
                f.external_id == file_id
                for f in await SharePointOfferFileService(session).list_current(
                    needs_extraction=True
                )
            )
            assert (
                await PostgresHistoryRepository(session).search_offers(
                    query="Sterile catheter",
                    domain=ProductDomain.MEDICINE,
                    limit=1,
                    embedding=[1, 0, 0],
                    model_id=provider.model_id,
                )
                == []
            )

        # A changed file replaces its offer set and reuses the product vector across versions.
        graph.ctag = "c2"
        rows = rows[:1]
        rows[0] = offered(price_amount="55")
        changed = await job.process_one(graph, root, file_id, settings, extractor=extractor)
        assert changed["offers"] == 1 and changed["embeddings"][0]["reused"] == 1
        assert provider.calls == 1
        async with sessions() as session:
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM historical_offers WHERE source_drive_id=:drive AND is_current AND active"
                    ),
                    {"drive": drive},
                )
                == 1
            )

        # A version changed while extracting must not replace the prior successful set.
        graph.ctag = "c3"
        graph.change_during_extraction = True
        failed = await job.process_one(graph, root, file_id, settings, extractor=extractor)
        assert failed["failed"] == 1 and failed["status"] == "failed"
        async with sessions() as session:
            assert (
                await session.scalar(
                    text(
                        "SELECT price FROM historical_offers WHERE source_drive_id=:drive AND is_current AND active"
                    ),
                    {"drive": drive},
                )
                == 55
            )

        # Successful empty results clear prior offers and count as processed.
        graph.change_during_extraction = False
        graph.ctag = "c5"
        rows = []
        empty = await job.process_one(graph, root, file_id, settings, extractor=extractor)
        assert empty["processed"] == 1 and empty["offers"] == 0
        async with sessions() as session:
            assert not await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM historical_offers WHERE source_drive_id=:drive AND is_current AND active)"
                ),
                {"drive": drive},
            )
            files = await SharePointOfferFileService(session).list_current()
            assert next(f for f in files if f.external_id == file_id).structured_output_available

        # Claims are exclusive, and a superseding discovery fences an old worker.
        graph.ctag = "c6"
        source = replace(parse_item(await graph.get_item(file_id)), domain="equipment")
        async with sessions() as session:
            await enqueue(session, drive, root, source)
            await session.commit()
            claimed = await claim(session, drive, root, settings, file_id)
        async with sessions() as session:
            assert await claim(session, drive, root, settings, file_id) is None
            await enqueue(session, drive, root, replace(source, ctag="c7"))
            await session.commit()
        document = DownloadedDocument(
            file_id, source.name, source.mime_type, b"offer", source.modified_at, source.created_at
        )
        async with sessions() as session:
            with pytest.raises(RuntimeError, match="lease"):
                await publish(
                    session,
                    claimed,
                    normalize(SharePointChange("new", source), document, batch_result()),
                )
            await session.rollback()
        async with sessions() as session:
            claimed = await claim(session, drive, root, settings, file_id)
            source = replace(source, ctag="c7")
            duplicate = batch_result([offered(), offered()])
            with pytest.raises(ValueError, match="duplicate"):
                await publish(
                    session,
                    claimed,
                    normalize(SharePointChange("new", source), document, duplicate),
                )
            await session.rollback()
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM historical_offers WHERE source_drive_id=:drive AND is_current AND active"
                    ),
                    {"drive": drive},
                )
                == 0
            )
            await publish(
                session,
                claimed,
                normalize(SharePointChange("new", source), document, batch_result()),
            )

        # Wrong dimensions fail only embeddings; extraction and lexical matching remain available.
        provider.model_id += "-bad"
        provider.bad_dimensions = True
        result = await process_file(provider, sessions, settings, drive, root, file_id)
        assert result["failed"] == 1 and "dimension" in result["error"]
        async with sessions() as session:
            assert (
                await session.scalar(
                    text("SELECT status FROM sharepoint_offer_jobs WHERE drive_id=:drive"),
                    {"drive": drive},
                )
                == "completed"
            )
            assert await PostgresHistoryRepository(session).search_offers(
                query="Sterile catheter", domain=ProductDomain.EQUIPMENT, limit=1
            )
            with pytest.raises(ValueError, match="specification"):
                await register_model(
                    session, EmbeddingModelSpec(provider.model_id, "test", "test", "v1", 4)
                )
            await session.rollback()
            await archive_file(session, drive, root, file_id)
            await session.commit()
            assert (
                await PostgresHistoryRepository(session).search_offers(
                    query="Sterile catheter", domain=ProductDomain.EQUIPMENT, limit=1
                )
                == []
            )
    finally:
        async with sessions() as session:
            await session.execute(
                text(
                    "DELETE FROM match_runs WHERE request_payload->'inquiry_line'->'source'->>'document_id'=:id"
                ),
                {"id": file_id},
            )
            await session.execute(
                text("DELETE FROM historical_offers WHERE source_drive_id=:drive"), {"drive": drive}
            )
            await session.execute(
                text("DELETE FROM sharepoint_offer_files WHERE external_id=:id"), {"id": file_id}
            )
            await session.execute(
                text(
                    "DELETE FROM source_snapshots WHERE document_id=:id OR metadata_json->>'sharepoint_item_id'=:id"
                ),
                {"id": file_id},
            )
            await session.execute(
                text("DELETE FROM sharepoint_offer_jobs WHERE drive_id=:drive"), {"drive": drive}
            )
            await session.execute(
                text("DELETE FROM embedding_models WHERE id LIKE :id"),
                {"id": "test-offer-" + suffix + "%"},
            )
            await session.commit()
        await engine.dispose()
