"""Atomic bulk decisions, undo and source preservation with PostgreSQL."""

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_parsing import build_xlsx

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def saved_review(monkeypatch):
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    from app.parsing import ai_review
    from app.parsing.llm_client import LlmUnavailable

    monkeypatch.setattr(
        ai_review, "call_llm", lambda *a, **k: (_ for _ in ()).throw(LlmUnavailable("test"))
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.put("/api/me/extraction-preferences", json={"mode": "basic"})
        uploaded = await client.post(
            "/api/imports",
            files={
                "file": (
                    "review.xlsx",
                    build_xlsx(
                        [
                            ["Product", "Quantity", "Unit", "Type", "Brand"],
                            ["Thermometer", 10, "pcs", "Equipment", "Source brand"],
                            ["Sterile syringe", 20, "pcs", "Equipment", "Source brand"],
                        ]
                    ),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        body = uploaded.json()
        try:
            yield client, body
        finally:
            await client.delete(f"/api/requests/{body['requestId']}")


def payload(body, action, ids, **extra):
    return dict(
        operationId=str(uuid4()),
        expectedRevision=body["reviewRevision"],
        action=action,
        itemIds=ids,
        **extra,
    )


async def test_preview_atomic_apply_retry_undo_and_conflict(saved_review):
    client, body = saved_review
    root = f"/api/requests/{body['requestId']}"
    ids = [i["id"] for i in body["items"]]
    edit = payload(body, "edit", ids, changes={"notes": "Human note"})
    preview = await client.post(root + "/review/operations/preview", json=edit)
    assert preview.status_code == 200, preview.text
    assert (await client.get(root + "/review")).json()["items"][0]["notes"] == ""
    applied = await client.post(root + "/review/operations", json=edit)
    assert applied.status_code == 200, applied.text
    latest = applied.json()["review"]
    assert latest["reviewRevision"] == body["reviewRevision"] + 1
    retry = await client.post(root + "/review/operations", json=edit)
    assert retry.status_code == 200
    assert retry.json()["review"]["reviewRevision"] == latest["reviewRevision"]
    undo = await client.post(
        root + f"/review/operations/{edit['operationId']}/undo",
        json={
            "operationId": str(uuid4()),
            "expectedRevision": latest["reviewRevision"],
        },
    )
    assert undo.status_code == 200, undo.text
    latest = undo.json()["review"]
    assert latest["items"][0]["notes"] == ""
    stale = await client.post(root + "/review/operations", json=payload(body, "remove", ids))
    assert stale.status_code == 409
    invalid = await client.post(
        root + "/review/operations",
        json=payload(
            latest,
            "edit",
            ids,
            itemChanges={
                str(ids[0]): {"quantity": 100},
                str(ids[1]): {"quantity": 0},
            },
        ),
    )
    assert invalid.status_code == 422
    assert (await client.get(root + "/review")).json()["items"][0]["quantity"] == 10


async def test_remove_custom_column_restore_and_undo_conflict(saved_review, monkeypatch):
    client, body = saved_review
    root = f"/api/requests/{body['requestId']}"
    first, second = [i["id"] for i in body["items"]]
    removed = await client.post(root + "/review/operations", json=payload(body, "remove", [first]))
    assert removed.status_code == 200, removed.text
    latest = removed.json()["review"]
    assert [i["id"] for i in latest["items"]] == [second]
    assert latest["removedItems"][0]["id"] == first
    assert latest["source"]["rowsDetected"] == 2
    history = (await client.get("/api/requests")).json()
    assert next(r for r in history if r["requestId"] == body["requestId"])["itemCount"] == 1
    matching = (await client.get(root + "/matching")).json()
    assert matching["total"] == 1
    assert [line["itemId"] for line in matching["lines"]] == [second]
    seen = []
    from app.api import routes

    def inspect_review(document):
        seen.extend(item.review_id for item in document.items)
        document.review_summary = {"status": "completed", "checked": len(document.items)}
        return document

    monkeypatch.setattr(routes, "review_document", inspect_review)
    checked = await client.post(root + "/ai-review")
    assert checked.status_code == 200, checked.text
    assert seen == [str(second)]
    assert checked.json()["removedItems"][0]["id"] == first
    columns = await client.post(
        root + "/custom-columns", json={"displayName": "Maker", "hint": "Brand"}
    )
    assert columns.status_code == 200, columns.text
    latest = columns.json()
    assert len(latest["items"]) == 1
    restored = await client.post(
        root + "/review/operations", json=payload(latest, "restore", [first])
    )
    assert restored.status_code == 200, restored.text
    latest = restored.json()["review"]
    assert len(latest["items"]) == 2
    assert any(r["itemId"] == first for r in latest["sourceReferences"])
    edit = payload(latest, "edit", [second], changes={"quantity": 30})
    applied = (await client.post(root + "/review/operations", json=edit)).json()
    latest = applied["review"]
    later = await client.post(
        root + "/review/operations",
        json=payload(latest, "edit", [second], changes={"notes": "Later edit"}),
    )
    assert later.status_code == 200, later.text
    conflict = await client.post(
        root + f"/review/operations/{edit['operationId']}/undo",
        json={
            "operationId": str(uuid4()),
            "expectedRevision": later.json()["review"]["reviewRevision"],
        },
    )
    assert conflict.status_code == 409


async def test_empty_removed_request_cannot_match_and_individual_routes_share_service(saved_review):
    client, body = saved_review
    root = f"/api/requests/{body['requestId']}"
    for item in body["items"]:
        assert (await client.delete(root + f"/items/{item['id']}")).status_code == 204
    review = (await client.get(root + "/review")).json()
    assert review["items"] == []
    assert len(review["removedItems"]) == 2
    assert review["canStartMatching"] is False
    assert (await client.post(root + "/matching")).status_code == 422


async def test_switching_worksheets_preserves_removal_identity(saved_review):
    from tests.test_api_routes import build_two_sheet_xlsx

    client, _ = saved_review
    uploaded = await client.post(
        "/api/imports",
        files={
            "file": (
                "multi.xlsx",
                build_two_sheet_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    body = uploaded.json()
    root = f"/api/requests/{body['requestId']}"
    try:
        original = body["items"][0]
        assert (await client.delete(root + f"/items/{original['id']}")).status_code == 204
        switched = await client.post(root + "/worksheet", json={"sheet": "Second list"})
        assert switched.status_code == 200, switched.text
        assert len(switched.json()["items"]) == 2
        assert original["id"] not in {i["id"] for i in switched.json()["items"]}
        returned = await client.post(root + "/worksheet", json={"sheet": "Request"})
        assert returned.status_code == 200, returned.text
        assert returned.json()["items"] == []
        assert returned.json()["removedItems"][0]["id"] == original["id"]
    finally:
        await client.delete(root)


async def test_undo_allows_unrelated_changes_and_matching_locks_operations(saved_review):
    from sqlalchemy import text

    from app.db.session import async_session

    client, body = saved_review
    root = f"/api/requests/{body['requestId']}"
    first, second = [i["id"] for i in body["items"]]
    edit = payload(body, "edit", [first], changes={"notes": "First decision"})
    applied = (await client.post(root + "/review/operations", json=edit)).json()
    other = await client.post(
        root + "/review/operations",
        json=payload(applied["review"], "edit", [second], changes={"notes": "Other decision"}),
    )
    latest = other.json()["review"]
    undone = await client.post(
        root + f"/review/operations/{edit['operationId']}/undo",
        json={
            "operationId": str(uuid4()),
            "expectedRevision": latest["reviewRevision"],
        },
    )
    assert undone.status_code == 200, undone.text
    latest = undone.json()["review"]
    assert latest["items"][0]["notes"] == ""
    assert latest["items"][1]["notes"] == "Other decision"
    async with async_session() as session:
        await session.execute(
            text(
                "UPDATE import_requests SET workflow_status = 'matching_queued' WHERE request_id = :id"
            ),
            {"id": body["requestId"]},
        )
        await session.commit()
    locked = await client.post(root + "/review/operations", json=payload(latest, "remove", [first]))
    assert locked.status_code == 409


async def test_concurrent_operations_reject_stale_selection_atomically(saved_review):
    import asyncio

    client, body = saved_review
    root = f"/api/requests/{body['requestId']}"
    ids = [item["id"] for item in body["items"]]
    results = await asyncio.gather(
        *[
            client.post(
                root + "/review/operations",
                json=payload(body, "edit", ids, changes={"notes": value}),
            )
            for value in ("First concurrent edit", "Second concurrent edit")
        ]
    )
    assert sorted(result.status_code for result in results) == [200, 409]
    latest = (await client.get(root + "/review")).json()
    assert latest["reviewRevision"] == body["reviewRevision"] + 1
    assert len({item["notes"] for item in latest["items"]}) == 1
