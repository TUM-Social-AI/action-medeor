"""Manual requests and additions use the same persisted review/matching workflow."""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.request_workflow import to_inquiry_line
from app.db.repository import get_request_by_id
from app.db.session import async_session
from app.main import app
from app.matching.contracts import SourceType

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_first_manual_item_creates_request_and_invalid_items_save_nothing() -> None:
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")

    request_id = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        async with async_session() as session:
            before = await session.scalar(text("SELECT count(*) FROM import_requests"))
        try:
            for payload in (
                {}, {"item": {}},
                {"item": {"name": "Catheter", "quantity": 0, "domain": "equipment"}},
            ):
                invalid = await client.post("/api/requests/manual", json=payload)
                assert invalid.status_code == 422, invalid.text
            async with async_session() as session:
                assert await session.scalar(text("SELECT count(*) FROM import_requests")) == before

            created = await client.post("/api/requests/manual", json={
                "item": {"name": "Catheter", "quantity": 2, "domain": "equipment"},
                "partner": "Partner clinic", "region": "Test region", "contact": "Contact",
                "confirmed": True, "columnLabels": {"name": "Product"},
            })
            assert created.status_code == 201, created.text
            review = created.json()
            request_id = review["requestId"]
            assert review["counts"]["total"] == review["counts"]["verified"] == 1
            assert review["items"][0]["manual"] is True
            assert review["partner"]["partner"] == "Partner clinic"
            assert review["partner"]["region"] == "Test region"
            assert review["partner"]["contact"] == "Contact"
            assert review["partner"]["confirmed"] is True
            assert review["columnLabels"] == {"name": "Product"}
            restored = await client.get(f"/api/requests/{request_id}/review")
            assert restored.json() == review
            saved = await client.get(f"/api/requests/{request_id}")
            assert saved.json()["status"] == "review"
            assert saved.json()["itemCount"] == 1
        finally:
            if request_id:
                assert (await client.delete(f"/api/requests/{request_id}")).status_code == 204


@pytest.mark.asyncio
async def test_first_item_database_failure_leaves_no_empty_request() -> None:
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")

    from sqlalchemy import event

    from app.api.schemas import ManualRequestCreate
    from app.db.models import RequestItemRow
    from app.db.repository import create_manual_request

    def fail_insert(*_args):
        raise RuntimeError("First item could not be saved")

    async with async_session() as session:
        before = await session.scalar(text("SELECT count(*) FROM import_requests"))
        event.listen(RequestItemRow, "before_insert", fail_insert)
        try:
            with pytest.raises(RuntimeError, match="First item could not be saved"):
                await create_manual_request(session, ManualRequestCreate.model_validate({
                    "item": {"name": "Catheter", "quantity": 2, "domain": "equipment"},
                }))
            await session.rollback()
            assert await session.scalar(text("SELECT count(*) FROM import_requests")) == before
        finally:
            event.remove(RequestItemRow, "before_insert", fail_insert)


@pytest.mark.asyncio
async def test_manual_request_and_uploaded_additions_survive_reload() -> None:
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")

    request_ids = []
    payload = {"name": " Sterile catheter CH18 ", "quantity": 2, "domain": "equipment"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        try:
            created = await client.post("/api/requests", json={"mode": "manual"})
            assert created.status_code == 201, created.text
            manual_id = created.json()["requestId"]
            request_ids.append(manual_id)
            assert created.json()["status"] == "review"
            assert created.json()["sourceFile"] is None
            review = (await client.get(f"/api/requests/{manual_id}/review")).json()
            assert review["items"] == []
            assert review["partner"]["partner"] == ""
            assert review["sourceReferences"] == []
            assert (await client.post(f"/api/requests/{manual_id}/matching")).status_code == 422

            for invalid in (
                {"name": ""}, {"name": "   "}, {"quantity": None}, {"quantity": 0},
                {"quantity": -1}, {"quantity": 1.5}, {"domain": None},
            ):
                response = await client.post(
                    f"/api/requests/{manual_id}/items", json={**payload, **invalid}
                )
                assert response.status_code == 422, response.text

            added = await client.post(f"/api/requests/{manual_id}/items", json=payload)
            assert added.status_code == 201, added.text
            item = added.json()
            assert item["name"] == "Sterile catheter CH18"
            assert item["manual"] is True
            assert item["status"] == "verified"
            assert item["confidence"] is None
            item_url = f"/api/requests/{manual_id}/items/{item['id']}"
            assert (await client.patch(item_url, json={"quantity": 0})).status_code == 422
            edited = await client.patch(item_url, json={"quantity": 5, "notes": "Sterile"})
            assert edited.status_code == 200, edited.text
            reloaded = (await client.get(f"/api/requests/{manual_id}/review")).json()
            assert reloaded["items"][0]["quantity"] == 5
            assert reloaded["items"][0]["manual"] is True
            assert reloaded["counts"]["verified"] == 1
            assert reloaded["sourceReferences"] == []
            history = (await client.get("/api/requests")).json()
            assert next(row for row in history if row["requestId"] == manual_id)["itemCount"] == 1

            # A manual addition to an Excel request must not inherit Excel provenance.
            async with async_session() as session:
                saved = await get_request_by_id(session, manual_id)
                line = to_inquiry_line(saved, saved.items[0])
                assert line.source.source_type == SourceType.OTHER
                assert line.source.row is None
                assert line.source.locator == {"entry_method": "manual"}

            assert (await client.delete(item_url)).status_code == 204
            assert (await client.delete(item_url)).status_code == 404
            assert (await client.get(f"/api/requests/{manual_id}/review")).json()["items"] == []

            draft = await client.post("/api/requests")
            assert draft.status_code == 201, draft.text
            upload_id = draft.json()["requestId"]
            request_ids.append(upload_id)
            assert draft.json()["status"] == "draft"
            assert (await client.post(f"/api/requests/{upload_id}/items", json=payload)).status_code == 409
            from tests.test_api_routes import build_xlsx

            uploaded = await client.post(f"/api/requests/{upload_id}/file", files={
                "file": ("manual-additions.xlsx", build_xlsx([
                    ["Item", "Quantity", "Unit", "Brand"],
                    ["Amoxicillin 500mg Capsules", 20, "caps", "Test brand"],
                ]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            })
            assert uploaded.status_code == 200, uploaded.text
            extracted = uploaded.json()["items"][0]
            assert extracted["manual"] is False
            assert (await client.delete(
                f"/api/requests/{upload_id}/items/{extracted['id']}"
            )).status_code == 409
            added = await client.post(f"/api/requests/{upload_id}/items", json=payload)
            assert added.status_code == 201, added.text
            manual_item = added.json()
            assert (await client.delete(
                f"/api/requests/{manual_id}/items/{manual_item['id']}"
            )).status_code == 404
            assert (await client.post("/api/requests/MISSING/items", json=payload)).status_code == 404
            column = await client.post(f"/api/requests/{upload_id}/custom-columns", json={
                "displayName": "Maker", "hint": "Brand",
            })
            assert column.status_code == 200, column.text
            assert column.json()["items"][0]["attributes"]["Maker"] == "Test brand"
            assert column.json()["items"][1]["attributes"] == {}
            async with async_session() as session:
                saved = await get_request_by_id(session, upload_id)
                line = to_inquiry_line(saved, saved.items[1])
                assert line.source.source_type == SourceType.OTHER
                assert "file_name" not in line.source.locator
                await session.execute(text(
                    "UPDATE import_requests SET workflow_status = 'matching_queued' "
                    "WHERE request_id = :id"
                ), {"id": upload_id})
                await session.commit()
            assert (await client.post(f"/api/requests/{upload_id}/items", json=payload)).status_code == 409
            assert (await client.delete(
                f"/api/requests/{upload_id}/items/{manual_item['id']}"
            )).status_code == 409
        finally:
            for request_id in request_ids:
                async with async_session() as session:
                    await session.execute(text(
                        "UPDATE import_requests SET workflow_status = 'review' WHERE request_id = :id"
                    ), {"id": request_id})
                    await session.commit()
                deleted = await client.delete(f"/api/requests/{request_id}")
                assert deleted.status_code == 204, deleted.text
