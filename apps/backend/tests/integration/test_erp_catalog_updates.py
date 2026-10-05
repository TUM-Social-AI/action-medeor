"""ERP updates against PostgreSQL, isolated in a rolled-back outer transaction."""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.catalog import progress
from app.catalog.embeddings import CatalogEmbeddingJobService, EmbeddingModelSpec
from app.catalog.listing import list_catalogue_articles
from app.catalog.service import CatalogImportService
from app.jobs.seed_suspended_example import ITEM_NUMBER, seed_suspended_example
from app.matching.adapters.in_memory import InMemoryHistoryRepository
from app.matching.adapters.persistence import (
    PgVectorRepository,
    PostgresCatalogRepository,
    PostgresMatchRunRepository,
)
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import AvailabilityStatus, MatchRequestV1, ProductDomain, QuantityValue
from app.matching.eligibility import erp_exclusion
from app.matching.packaging import (
    calculate_packaging,
    observed_availability,
    required_stock_quantity,
)
from app.matching.service import MatchingService
from tests.matching.factories import line

pytestmark = pytest.mark.integration
HEADER = (
    "Nr.;Nummer 2;Beschreibung;Beschreibung 2;Basiseinheit;Artikelkategoriencode;"
    "Zollware (T1);Lagerbestand;Menge in Bestellung;Menge in Auftrag;"
    "Wiederbeschaffungsverfahren;Gesperrt;Verkauf gesperrt;Einkauf gesperrt\n"
)
TRANSLATIONS = b"Artikelnr.;Sprachcode;Beschreibung;Beschreibung 2\n"


class Provider:
    model_id = "erp-update-test"

    def __init__(self):
        self.calls = []
        self.fail = False

    async def spec(self):
        return EmbeddingModelSpec(self.model_id, "test", "test", "1", 3)

    async def embed_documents(self, texts):
        self.calls.extend(texts)
        if self.fail:
            raise RuntimeError("Test provider unavailable")
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
async def session():
    url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as value:
            yield value
        await transaction.rollback()
    await engine.dispose()


async def upload(session, rows, translations=TRANSLATIONS):
    return await CatalogImportService(session).import_files(
        article_data=(HEADER + "\n".join(rows) + "\n").encode(),
        translation_data=translations,
        article_filename="erp-updates.csv",
        translation_filename="translations.csv",
        captured_at=datetime(2026, 10, 5, tzinfo=UTC),
    )


@pytest.mark.parametrize("pinned", [True, False])
async def test_legacy_stock_display_uses_historical_inventory_without_rewriting_run(session, pinned):
    description = "Fixierpflaster 1,25 cm x 9,1 m Kunstseide, 24 Rollen"
    row = f"401101001;401101000;{description};;PAKET;404;nein;60;15;5;2;nein;nein;nein"
    first = await upload(session, [row])
    inquiry = line(description=description).model_copy(update={
        "quantity": QuantityValue(value=1200, unit="rolls"),
    })
    runs = PostgresMatchRunRepository(session)
    service = MatchingService(
        catalog_repository=PostgresCatalogRepository(session),
        history_repository=InMemoryHistoryRepository(), run_repository=runs,
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(
        inquiry_line=inquiry, catalog_snapshot_id=str(first.catalog_snapshot_id) if pinned else None,
    ))
    assert result.candidates[0].available_quantity == 50
    legacy = result.model_dump(mode="json")
    for candidate in legacy["candidates"]:
        for field in ("available_quantity", "stock_unit", "required_stock_quantity"):
            candidate.pop(field)
    await session.execute(text(
        "UPDATE match_runs SET result_payload = CAST(:payload AS jsonb) WHERE id = :id"
    ), {"id": result.match_run_id, "payload": json.dumps(legacy)})
    newer = await upload(session, [row.replace(";60;15;5;", ";999;0;0;")])
    # The rollback transaction fixes CURRENT_TIMESTAMP; simulate the later
    # import's completion as it would be in independent transactions.
    await session.execute(text("UPDATE catalog_imports SET completed_at = :later WHERE id = :id"),
                          {"later": datetime.now(UTC), "id": newer.import_id})
    restored = await runs.get_run(result.match_run_id)
    candidate = restored.candidates[0]
    assert candidate.available_quantity == 50
    assert candidate.stock_unit == "PAKET"
    assert candidate.required_stock_quantity == 50
    assert candidate.availability_status == result.candidates[0].availability_status
    assert candidate.rank == result.candidates[0].rank
    assert candidate.candidate_id == result.candidates[0].candidate_id
    assert await session.scalar(text("SELECT result_payload FROM match_runs WHERE id = :id"),
                                {"id": result.match_run_id}) == legacy


async def test_erp_description_conversions_use_pinned_versions_and_legacy_fallback(session, monkeypatch):
    provider = Provider()
    monkeypatch.setattr(progress, "create_embedding_provider", lambda _: provider)
    embeddings = CatalogEmbeddingJobService(session)
    await embeddings.register_and_activate(provider, preserve_active=True)
    row = "401101001;401101000;Fixierpflaster 1,25 cm x 9,1 m Kunstseide, 24 Rollen;;PAKET;404;nein;60;15;5;2;nein;nein;ja"
    first = await upload(session, [row])
    assert await embeddings.process_pending(provider) == {"completed": 1, "failed": 0}
    package = await session.scalar(text(
        "SELECT package FROM catalog_item_versions WHERE item_number = '401101001'"
    ))
    assert package["units_per_package"] == "24" and package["stock_unit"] == "PAKET"

    # Simulate a pre-feature database version in the isolated test database.
    await session.execute(text(
        "UPDATE catalog_item_versions SET package = NULL WHERE item_number = '401101001'"
    ))
    repository = PostgresCatalogRepository(session)
    old = (await repository.list_items(
        domain=ProductDomain.EQUIPMENT, snapshot_id=str(first.catalog_snapshot_id)
    ))[0]
    requested = QuantityValue(value=Decimal("1200"), unit="rolls")
    inquiry = line().model_copy(update={"quantity": requested})
    packaging = calculate_packaging(requested, old)
    assert old.stock.fulfillable_quantity == 50
    assert old.package.units_per_package == 24
    assert "24 rolls per PAKET" in packaging.basis
    assert not packaging.warnings
    assert required_stock_quantity(requested, old) == 50
    assert observed_availability(requested, old, packaging) == (
        AvailabilityStatus.ON_HAND_SUFFICIENT, None
    )
    assert erp_exclusion(inquiry, old) is None
    assert erp_exclusion(inquiry.model_copy(update={
        "quantity": requested.model_copy(update={"value": Decimal("1201")})
    }), old) is not None

    status_only = await upload(session, [row.removesuffix(";ja") + ";nein"])
    assert status_only.metadata_updated_items == 1
    assert status_only.embedding_jobs_created == 0
    assert len(provider.calls) == 1

    changed = await upload(session, [row.replace("24 Rollen", "12 Rollen")])
    assert changed.text_updated_items == 1
    assert changed.embedding_jobs_created == 1
    current = (await repository.list_items(domain=ProductDomain.EQUIPMENT))[0]
    assert current.package.units_per_package == 12
    assert erp_exclusion(inquiry, current) is not None
    pinned = (await repository.list_items(
        domain=ProductDomain.EQUIPMENT, snapshot_id=str(first.catalog_snapshot_id)
    ))[0]
    assert pinned.package.units_per_package == 24
    assert erp_exclusion(inquiry, pinned) is None
    replay = await upload(session, [row.replace("24 Rollen", "12 Rollen")])
    assert replay.idempotent_replay
    assert replay.import_id == changed.import_id


async def test_dose_contents_compare_tablets_without_treating_tin_stock_as_tablets(session):
    await upload(session, [
        "202100001;202100000;Acetylsalicylic acid 500 mg tablets, 1000;;DOSE;201;nein;2;0;0;2;nein;nein;ja"
    ])
    item = (await PostgresCatalogRepository(session).list_items(domain=ProductDomain.MEDICINE))[0]
    for value, unit, required, status in [
        (2000, "tabs", 2, AvailabilityStatus.ON_HAND_SUFFICIENT),
        (2001, "tablets", Decimal("2.001"), AvailabilityStatus.ON_HAND_PARTIAL),
        (2, "DOSE", 2, AvailabilityStatus.ON_HAND_SUFFICIENT),
    ]:
        requested = QuantityValue(value=Decimal(value), unit=unit)
        packaging = calculate_packaging(requested, item)
        assert required_stock_quantity(requested, item) == required
        assert observed_availability(requested, item, packaging) == (status, None)
        if unit == "DOSE":
            assert packaging.status == "not_required" and not packaging.warnings
    assert required_stock_quantity(QuantityValue(value=2000, unit="capsules"), item) is None


async def test_suspended_example_is_durable_visible_idempotent_and_ineligible(session):
    imports_before = await session.scalar(text("SELECT count(*) FROM catalog_imports"))
    assert await seed_suspended_example(session) is True
    await session.commit()
    assert await seed_suspended_example(session) is False
    article = next(a for a in await list_catalogue_articles(session) if a.reference == ITEM_NUMBER)
    assert article.name == "Infusion Set 20 drops/ml, Luer Lock"
    assert article.blocked is True
    assert article.stock == "340"
    assert article.on_hand == "340"
    assert "suspension_since" not in article.model_dump()
    assert "suspension_reason" not in article.model_dump()
    assert "suspension_by" not in article.model_dump()
    item = next(i for i in await PostgresCatalogRepository(session).list_items(
        domain=ProductDomain.EQUIPMENT
    ) if i.item_number == ITEM_NUMBER)
    assert item.active is False
    assert item.blocked is True
    assert await session.scalar(text("SELECT count(*) FROM catalog_imports")) == imports_before
    assert await session.scalar(text(
        "SELECT count(*) FROM catalog_embedding_jobs j JOIN catalog_item_versions v "
        "ON v.id = j.catalog_item_version_id WHERE v.item_number = :number"
    ), {"number": ITEM_NUMBER}) == 0

    # A real CSV update must retain the manually added sample and its inventory.
    await upload(session, ["410008101;410008100;Foley;;STÜCK;404;nein;10;0;0;2;nein;nein;nein"])
    assert any(a.reference == ITEM_NUMBER for a in await list_catalogue_articles(session))
    assert await session.scalar(text(
        "SELECT count(*) FROM catalog_item_versions WHERE item_number = :number"
    ), {"number": ITEM_NUMBER}) == 1


async def test_suspended_example_refuses_to_overwrite_existing_identity(session):
    await session.execute(text(
        "INSERT INTO catalog_items (item_number, domain) VALUES (:number, 'equipment')"
    ), {"number": ITEM_NUMBER})
    with pytest.raises(ValueError, match="refusing to overwrite"):
        await seed_suspended_example(session)


@pytest.mark.asyncio
async def test_inventory_flags_text_and_snapshot_updates_reuse_vectors(session, monkeypatch):
    provider = Provider()
    monkeypatch.setattr(progress, "create_embedding_provider", lambda _: provider)
    embeddings = CatalogEmbeddingJobService(session)
    await embeddings.register_and_activate(provider, preserve_active=True)
    first_row = "410008101;410008100;Foley catheter;;STÜCK;404;nein;10;4;2;2;nein;nein;nein"
    master = "410008100;;Foley base;;STÜCK;404;nein;0;0;0;2;nein;nein;nein"
    first = await upload(session, [first_row, master])
    assert first.embedding_jobs_created == 1
    assert await embeddings.process_pending(provider) == {"completed": 1, "failed": 0}
    first_item = await CatalogImportService(session).get_item("410008101")
    assert first_item.available_raw == "8"

    stock_row = first_row.replace(";10;4;2;", ";20;4;2;")
    stock = await upload(session, [stock_row, master])
    assert stock.unchanged_items == 2
    assert stock.inventory_refreshed_items == 2
    assert stock.embedding_jobs_created == 0

    blocked_row = stock_row.removesuffix(";nein;nein;nein") + ";ja;nein;nein"
    blocked = await upload(session, [blocked_row, master])
    assert blocked.metadata_updated_items == 1
    assert blocked.embedding_jobs_created == 0
    assert (await embeddings.process_pending(provider))["completed"] == 0
    assert len(provider.calls) == 1
    current = await CatalogImportService(session).get_item("410008101")
    assert current.blocked is True
    assert current.available_raw == "18"
    catalogue = await list_catalogue_articles(session)
    assert next(a for a in catalogue if a.reference == "410008101").blocked is True
    assert next(a for a in catalogue if a.reference == "410008100").master_item is True

    repository = PostgresCatalogRepository(session)
    old = await repository.list_items(
        domain=ProductDomain.EQUIPMENT, snapshot_id=str(first.catalog_snapshot_id)
    )
    assert next(a for a in old if a.item_number == "410008101").blocked is False
    assert next(a for a in old if a.item_number == "410008101").stock.available_raw == 8
    hits = await PgVectorRepository(session).search(
        embedding=[1, 0, 0],
        model_id=provider.model_id,
        domain=ProductDomain.EQUIPMENT,
        limit=10,
        snapshot_id=str(blocked.catalog_snapshot_id),
    )
    assert hits == []
    old_hits = await PgVectorRepository(session).search(
        embedding=[1, 0, 0],
        model_id=provider.model_id,
        domain=ProductDomain.EQUIPMENT,
        limit=10,
        snapshot_id=str(first.catalog_snapshot_id),
    )
    assert [hit.item_number for hit in old_hits] == ["410008101"]
    status = await progress.embedding_status(session, blocked.import_id)
    assert status.completed == 1 and status.pending == 0 and status.configuration_error is None

    translated = TRANSLATIONS + b"410008101;ENU;Urinary catheter;;\n"
    changed = await upload(session, [blocked_row, master], translated)
    assert changed.text_updated_items == 1 and changed.embedding_jobs_created == 1
    assert (await progress.embedding_status(session, changed.import_id)).pending == 1
    await embeddings.process_pending(provider)
    assert len(provider.calls) == 2
    replay = await upload(session, [blocked_row, master], translated)
    assert replay.idempotent_replay is True
    assert replay.import_id == changed.import_id
    assert await session.scalar(text("SELECT COUNT(*) FROM inventory_snapshots")) == 8
    assert await progress.embedding_status(session, uuid4()) is None


@pytest.mark.asyncio
async def test_pending_metadata_versions_embed_once_and_stale_jobs_recover(session):
    provider = Provider()
    embeddings = CatalogEmbeddingJobService(session)
    await embeddings.register_and_activate(provider, preserve_active=True)
    row = "410008101;;Catheter;;STÜCK;404;nein;10;0;0;2;nein;nein;nein"
    await upload(session, [row])
    await upload(session, [row.removesuffix(";nein;nein;nein") + ";nein;nein;ja"])
    await session.execute(
        text("""UPDATE catalog_embedding_jobs SET status = 'running',
        started_at = CURRENT_TIMESTAMP - INTERVAL '2 hours'""")
    )
    await session.commit()
    assert await embeddings.process_pending(provider) == {"completed": 2, "failed": 0}
    assert len(provider.calls) == 1
    assert await session.scalar(text("SELECT COUNT(*) FROM product_embeddings")) == 2


@pytest.mark.asyncio
async def test_worker_preserves_active_model_and_failed_jobs(session):
    provider = Provider()
    embeddings = CatalogEmbeddingJobService(session)
    await embeddings.register_and_activate(provider, preserve_active=True)
    other = Provider()
    other.model_id = "another-model"
    with pytest.raises(ValueError, match="does not match"):
        await embeddings.register_and_activate(other, preserve_active=True)
    assert (
        await session.scalar(text("SELECT id FROM embedding_models WHERE active"))
        == provider.model_id
    )
    assert await embeddings.configuration_error(other) is not None
    assert await embeddings.configuration_error(None) is not None
    await upload(session, ["410008101;;Catheter;;STÜCK;404;nein;10;0;0;2;nein;nein;nein"])
    provider.fail = True
    assert await embeddings.process_pending(provider) == {"completed": 0, "failed": 1}
    _, queued = await embeddings.register_and_activate(provider, preserve_active=True)
    assert queued == 0
    assert await session.scalar(text("SELECT status FROM catalog_embedding_jobs")) == "failed"


@pytest.mark.asyncio
async def test_legacy_flags_and_two_digit_master_are_derived_without_rewrite(session):
    provider = Provider()
    await upload(session, ["410008100;;Legacy base;;STÜCK;404;nein;0;0;0;2;nein;nein;nein"])
    # Simulate the old importer, which considered this 00 record eligible.
    await session.execute(text("UPDATE catalog_items SET matching_eligible = TRUE"))
    await session.execute(
        text("""UPDATE catalog_item_versions SET matching_eligible = TRUE,
        attributes = CAST(:attributes AS jsonb)"""),
        {
            "attributes": json.dumps(
                {"base_unit": {"value": "STÜCK"}, "master_item": {"value": False}}
            )
        },
    )
    await session.commit()
    view = await CatalogImportService(session).get_item("410008100")
    assert view.master_item is True and view.matching_eligible is False
    assert (view.blocked, view.sales_blocked, view.purchasing_blocked) == (False, False, False)
    listing = await list_catalogue_articles(session)
    assert listing[0].master_item is True
    _, queued = await CatalogEmbeddingJobService(session).register_and_activate(
        provider, preserve_active=True
    )
    assert queued == 0


@pytest.mark.asyncio
async def test_full_updated_exports_refresh_inventory_and_embed_incrementally(session, monkeypatch):
    data = Path(__file__).resolve().parents[4] / "data"
    if not all(
        (data / name).exists()
        for name in (
            "Artikeldaten.csv",
            "Artikeluebersetzungen.csv",
            "Artikeldaten (2).csv",
            "Artikeluebersetzungen (2).csv",
        )
    ):
        pytest.skip("Private ERP sample exports are not available")
    provider = Provider()
    monkeypatch.setattr(progress, "create_embedding_provider", lambda _: provider)
    embeddings = CatalogEmbeddingJobService(session)
    await embeddings.register_and_activate(provider, preserve_active=True)
    original_lines = (data / "Artikeldaten.csv").read_text(encoding="utf-8-sig").splitlines()
    original = (
        original_lines[0]
        + ";Gesperrt;Verkauf gesperrt;Einkauf gesperrt\n"
        + "\n".join(row + ";nein;nein;nein" for row in original_lines[1:])
        + "\n"
    ).encode()
    service = CatalogImportService(session)
    initial = await service.import_files(
        article_data=original,
        translation_data=(data / "Artikeluebersetzungen.csv").read_bytes(),
        article_filename="baseline.csv",
        translation_filename="baseline-translations.csv",
    )
    assert initial.inventory_refreshed_items == 2773
    await embeddings.process_pending(provider, batch_size=128)
    provider.calls.clear()
    articles = (data / "Artikeldaten (2).csv").read_bytes()
    translations = (data / "Artikeluebersetzungen (2).csv").read_bytes()
    current = await service.import_files(
        article_data=articles,
        translation_data=translations,
        article_filename="updated.csv",
        translation_filename="updated-translations.csv",
    )
    assert current.inserted_items == 807
    assert current.missing_items == 4
    assert current.inventory_refreshed_items == 3576
    assert 500 <= current.embedding_jobs_created < 600
    pending = await progress.embedding_status(session, current.import_id)
    assert pending.pending == current.embedding_jobs_created
    await embeddings.process_pending(provider, batch_size=128)
    ready = await progress.embedding_status(session, current.import_id)
    assert ready.completed == 2141 and ready.pending == 0 and ready.failed == 0
    assert len(provider.calls) <= current.embedding_jobs_created
    catalogue = await list_catalogue_articles(session)
    assert len([article for article in catalogue if article.source == "erp"]) == 3576
    assert sum(article.master_item for article in catalogue) == 1430
    assert sum(article.blocked for article in catalogue) == 10
    assert sum(article.sales_blocked for article in catalogue) == 1327
    assert sum(article.purchasing_blocked for article in catalogue) == 1303


@pytest.mark.asyncio
async def test_unchanged_article_missing_vector_is_queued_without_duplicates(session):
    row = "410008101;;Catheter;;STÜCK;404;nein;10;0;0;2;nein;nein;nein"
    first = await upload(session, [row])
    assert first.embedding_jobs_created == 0
    # Model activation elsewhere did not backfill this article.
    await session.execute(
        text("""INSERT INTO embedding_models
        (id, provider, name, version, dimensions, distance_metric, active)
        VALUES ('erp-update-test', 'test', 'test', '1', 3, 'cosine', TRUE)""")
    )
    await session.commit()
    updated = await upload(session, [row.replace(";10;0;0;", ";20;0;0;")])
    assert updated.unchanged_items == 1 and updated.embedding_jobs_created == 1
    another = await upload(session, [row.replace(";10;0;0;", ";30;0;0;")])
    assert another.unchanged_items == 1 and another.embedding_jobs_created == 0
