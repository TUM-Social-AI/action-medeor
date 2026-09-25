"""Saved request workflow through the real catalog and matching worker."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.jobs.match_requests as match_worker
from app.api.request_workflow import latest_snapshot_id
from app.catalog.service import CatalogImportService
from app.core.config import get_settings
from app.db.session import async_session
from app.jobs.match_requests import claim_next, process_request
from app.main import app
from app.matching.adapters.persistence import PostgresCatalogRepository
from app.matching.api import get_matching_service as real_matching_service
from app.matching.contracts import ProductDomain

pytestmark = pytest.mark.integration

ARTICLE_HEADER = (
    "Nr.;Nummer 2;Beschreibung;Beschreibung 2;Basiseinheit;Artikelkategoriencode;"
    "Zollware (T1);Lagerbestand;Menge in Bestellung;Menge in Auftrag;"
    "Wiederbeschaffungsverfahren\r\n"
)
TRANSLATION_HEADER = "Artikelnr.;Sprachcode;Beschreibung;Beschreibung 2\r\n"


@pytest.mark.asyncio
async def test_saved_request_matches_and_reopens(monkeypatch) -> None:
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "")
    get_settings.cache_clear()
    suffix = uuid4().hex[:9]
    first_number, second_number = f"4{suffix}1", f"4{suffix}2"
    descriptions = (f"Sterile catheter CH18 {suffix}", f"Sterile catheter CH12 {suffix}")
    articles = (
        ARTICLE_HEADER
        + f"{first_number};;{descriptions[0]};;STÜCK;404;nein;10;0;0;2\r\n"
        + f"{second_number};;{descriptions[1]};;STÜCK;404;nein;20;0;0;2\r\n"
    ).encode()
    changed_stock = articles.replace(b";nein;10;", b";nein;8;")
    translations = TRANSLATION_HEADER.encode()
    request_id = None
    try:
        async with async_session() as session:
            catalog = CatalogImportService(session)
            first = await catalog.import_files(
                article_data=articles, translation_data=translations,
                article_filename=f"workflow-{suffix}-articles.csv",
                translation_filename=f"workflow-{suffix}-translations.csv",
            )
            second = await catalog.import_files(
                article_data=changed_stock, translation_data=translations,
                article_filename=f"workflow-{suffix}-articles.csv",
                translation_filename=f"workflow-{suffix}-translations.csv",
            )
            assert first.catalog_snapshot_id != second.catalog_snapshot_id
            catalog_items = PostgresCatalogRepository(session)
            old_items = await catalog_items.list_items(
                domain=ProductDomain.EQUIPMENT, snapshot_id=str(first.catalog_snapshot_id)
            )
            new_items = await catalog_items.list_items(
                domain=ProductDomain.EQUIPMENT, snapshot_id=str(second.catalog_snapshot_id)
            )
            assert {first_number, second_number} <= {item.item_number for item in old_items}
            assert {first_number, second_number} <= {item.item_number for item in new_items}
            assert next(item for item in old_items if item.item_number == first_number).stock.on_hand == 10
            assert next(item for item in new_items if item.item_number == first_number).stock.on_hand == 8
            assert await latest_snapshot_id(session) == second.catalog_snapshot_id

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            created = await client.post("/api/requests")
            assert created.status_code == 201, created.text
            request_id = created.json()["requestId"]
            assert created.json()["status"] == "draft"
            content = (
                "Item,Quantity,Unit\n"
                + f"{descriptions[0]},2,pcs\n"
                + f"{descriptions[1]},3,pcs\n"
            ).encode()
            uploaded = await client.post(
                f"/api/requests/{request_id}/file",
                files={"file": (f"request-{suffix}.csv", content, "text/csv")},
            )
            assert uploaded.status_code == 200, uploaded.text
            items = uploaded.json()["items"]
            assert len(items) == 2
            blocked = await client.post(f"/api/requests/{request_id}/matching")
            assert blocked.status_code == 422
            for item in items:
                reviewed = await client.patch(
                    f"/api/requests/{request_id}/items/{item['id']}",
                    json={"domain": "equipment"},
                )
                assert reviewed.status_code == 200, reviewed.text
            await client.patch(
                f"/api/requests/{request_id}/items/{items[0]['id']}", json={"quantity": -1}
            )
            invalid = await client.post(f"/api/requests/{request_id}/matching")
            assert invalid.status_code == 422
            await client.patch(
                f"/api/requests/{request_id}/items/{items[0]['id']}", json={"quantity": 2}
            )
            queued = await client.post(f"/api/requests/{request_id}/matching")
            assert queued.status_code == 202, queued.text
            assert queued.json()["status"] == "matching_queued"
            # A newer import changes the live domain while this request waits.
            # The queued job must still use its pinned snapshot.
            async with async_session() as session:
                changed_domain = changed_stock.replace(b";404;nein;8;", b";204;nein;8;")
                third = await CatalogImportService(session).import_files(
                    article_data=changed_domain, translation_data=translations,
                    article_filename=f"workflow-{suffix}-articles.csv",
                    translation_filename=f"workflow-{suffix}-translations.csv",
                )
                assert third.catalog_snapshot_id != second.catalog_snapshot_id
                current_items = await PostgresCatalogRepository(session).list_items(domain=ProductDomain.EQUIPMENT)
                assert first_number not in {item.item_number for item in current_items}
                pinned_items = await PostgresCatalogRepository(session).list_items(
                    domain=ProductDomain.EQUIPMENT, snapshot_id=str(second.catalog_snapshot_id)
                )
                assert first_number in {item.item_number for item in pinned_items}
            assert await claim_next() == request_id
            # A dead process leaves a lease; a new worker reclaims it after expiry.
            async with async_session() as session:
                await session.execute(text("UPDATE request_matching_jobs SET lease_until = CURRENT_TIMESTAMP - INTERVAL '1 second' WHERE request_id = :id"), {"id": request_id})
                await session.commit()
            assert await claim_next() == request_id
            original_service = match_worker.get_matching_service
            class FailSecondLine:
                def __init__(self, service):
                    self.service = service
                async def match(self, payload):
                    if payload.inquiry_line.raw_description == descriptions[1]:
                        raise RuntimeError("simulated item failure")
                    return await self.service.match(payload)
            monkeypatch.setattr(match_worker, "get_matching_service", lambda session: FailSecondLine(real_matching_service(session)))
            await process_request(request_id)
            failed = (await client.get(f"/api/requests/{request_id}/matching")).json()
            assert failed["status"] == "matching_failed"
            assert [line["status"] for line in failed["lines"]] == ["completed", "failed"]
            completed_run = failed["lines"][0]["runId"]
            monkeypatch.setattr(match_worker, "get_matching_service", original_service)
            retried = await client.post(f"/api/requests/{request_id}/matching")
            assert retried.status_code == 202
            assert await claim_next() == request_id
            await process_request(request_id)
            matched = await client.get(f"/api/requests/{request_id}/matching")
            assert matched.status_code == 200, matched.text
            state = matched.json()
            assert state["completed"] == state["total"] == 2
            assert state["status"] == "match_review"
            assert state["lines"][0]["runId"] == completed_run
            assert all(line["candidates"] for line in state["lines"])
            assert {first_number, second_number} <= {
                candidate["item_number"] for line in state["lines"] for candidate in line["candidates"]
            }
            repeat = await client.post(f"/api/requests/{request_id}/matching")
            assert repeat.status_code == 202
            assert repeat.json()["status"] == "match_review"
            first_line, second_line = state["lines"]
            chosen = await client.post(
                f"/api/requests/{request_id}/items/{first_line['itemId']}/decision",
                json={"candidateId": first_line["candidates"][0]["candidate_id"]},
            )
            assert chosen.status_code == 200, chosen.text
            unmatched = await client.post(
                f"/api/requests/{request_id}/items/{second_line['itemId']}/decision",
                json={"noMatch": True},
            )
            assert unmatched.status_code == 200, unmatched.text
            assert unmatched.json()["status"] == "complete"
            reopened = await client.get(f"/api/requests/{request_id}")
            assert reopened.json()["status"] == "complete"
            restored = await client.get(f"/api/requests/{request_id}/matching")
            assert restored.json()["lines"][0]["selectedCandidateId"]
            assert restored.json()["lines"][1]["decisionType"] == "no_match"
            summary = await client.get(f"/api/requests/{request_id}/summary")
            assert summary.status_code == 200, summary.text
            assert summary.json()["matchedCount"] == 1
            assert summary.json()["unmatchedCount"] == 1
            assert "totalPrice" not in summary.json()
            listed = await client.get("/api/requests")
            assert any(row["requestId"] == request_id for row in listed.json())
    finally:
        # Keep this integration test independent of other catalog fixtures.
        if request_id:
            async with async_session() as session:
                await session.execute(text("DELETE FROM request_matching_jobs WHERE request_id = :id"), {"id": request_id})
                await session.execute(text("DELETE FROM request_source_references WHERE request_id = :id"), {"id": request_id})
                await session.execute(text("DELETE FROM request_items WHERE request_id = :id"), {"id": request_id})
                await session.execute(text("DELETE FROM import_requests WHERE request_id = :id"), {"id": request_id})
                await session.execute(text("DELETE FROM match_decisions WHERE match_run_id IN (SELECT id FROM match_runs WHERE inquiry_id = :id)"), {"id": request_id})
                await session.execute(text("DELETE FROM match_runs WHERE inquiry_id = :id"), {"id": request_id})
                await session.commit()
        async with async_session() as session:
            import_rows = (await session.execute(text(
                "SELECT id, article_source_snapshot_id, translation_source_snapshot_id, combined_source_snapshot_id "
                "FROM catalog_imports WHERE article_source_snapshot_id IN "
                "(SELECT id FROM source_snapshots WHERE document_id = :document_id)"
            ), {"document_id": f"workflow-{suffix}-articles.csv"})).mappings().all()
            if import_rows:
                await session.execute(text("DELETE FROM catalog_items WHERE item_number IN (:first, :second)"), {"first": first_number, "second": second_number})
                for row in import_rows:
                    await session.execute(text("DELETE FROM catalog_imports WHERE id = :id"), {"id": row["id"]})
                source_ids = {value for row in import_rows for key, value in row.items() if key != "id"}
                for source_id in source_ids:
                    await session.execute(text("DELETE FROM source_snapshots WHERE id = :id"), {"id": source_id})
                await session.commit()
        get_settings.cache_clear()
