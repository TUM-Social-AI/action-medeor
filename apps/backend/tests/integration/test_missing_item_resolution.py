"""One filled item resolves one warning atomically, including retry, linking and undo."""

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.repository import get_request_by_id
from app.db.session import async_session
from app.main import app
from tests.test_parsing import build_xlsx

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def missing_request():
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.put("/api/me/extraction-preferences", json={"mode": "basic"})
        uploaded = await client.post('/api/imports', files={"file": ("missing.xlsx", build_xlsx([
            ["Product", "Quantity", "Unit", "Type"], ["Thermometer", 10, "pcs", "Equipment"],
        ]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert uploaded.status_code == 200, uploaded.text
        request_id = uploaded.json()["requestId"]
        root = f"/api/requests/{request_id}"
        try:
            async with async_session() as session:
                request = await get_request_by_id(session, request_id)
                request.items[0].review_findings = [
                    {"code": "coverage_uncertain", "fields": [], "origin": "ai", "message": message}
                    for message in ("Missing blanket, 7 pcs", "Missing gauze, 20 pcs")
                ]
                await session.commit()
            yield client, root, (await client.get(root + '/review')).json()
        finally:
            await client.delete(root)


def filled(name="Emergency blanket"):
    return {"name": name, "quantity": 7, "unit": "pcs", "domain": "equipment"}


async def test_add_resolves_only_its_warning_and_retry_does_not_duplicate(missing_request):
    client, root, original = missing_request
    issues = [issue for issue in original["issues"] if issue["code"] == "coverage_uncertain"]
    assert len(issues) == 2
    payload = {"operationId": str(uuid4()), "expectedRevision": original["reviewRevision"],
        "issueId": issues[0]["id"], "item": filled()}
    first = await client.post(root + '/review/missing-items', json=payload)
    assert first.status_code == 201, first.text
    result = first.json()
    assert len(result["review"]["items"]) == len(original["items"]) + 1
    assert next(i for i in result["review"]["issues"] if i["id"] == issues[0]["id"])["addedItemId"] == result["itemId"]
    assert next(i for i in result["review"]["issues"] if i["id"] == issues[1]["id"])["state"] == "open"
    replay = await client.post(root + '/review/missing-items', json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["itemId"] == result["itemId"]
    assert replay.json()["review"]["reviewRevision"] == result["review"]["reviewRevision"]
    assert len(replay.json()["review"]["items"]) == len(result["review"]["items"])
    second = await client.post(root + '/review/missing-items', json={
        "operationId": str(uuid4()), "expectedRevision": result["review"]["reviewRevision"],
        "issueId": issues[1]["id"], "item": filled("Gauze"),
    })
    assert second.status_code == 201, second.text
    assert not any(t["code"] == "coverage_uncertain" for t in second.json()["review"]["tasks"])
    undo = await client.post(root + f"/review/operations/{second.json()['operationId']}/undo", json={
        "operationId": str(uuid4()), "expectedRevision": second.json()["review"]["reviewRevision"],
    })
    assert undo.status_code == 200, undo.text
    restored = undo.json()["review"]
    assert any(item["id"] == result["itemId"] for item in restored["items"])
    assert not any(item["id"] == second.json()["itemId"] for item in restored["items"])
    assert next(i for i in restored["issues"] if i["id"] == issues[0]["id"])["state"] == "accepted"
    assert next(i for i in restored["issues"] if i["id"] == issues[1]["id"])["state"] == "open"


async def test_existing_manual_item_can_be_linked_without_adding_it_again(missing_request):
    client, root, original = missing_request
    added = await client.post(root + '/items', json=filled())
    assert added.status_code == 201, added.text
    current = (await client.get(root + '/review')).json()
    issues = [issue for issue in current["issues"] if issue["code"] == "coverage_uncertain"]
    linked = await client.post(root + '/review/missing-items', json={
        "operationId": str(uuid4()), "expectedRevision": current["reviewRevision"],
        "issueId": issues[0]["id"], "itemId": added.json()["id"],
    })
    assert linked.status_code == 201, linked.text
    assert len(linked.json()["review"]["items"]) == len(current["items"])
    duplicate = await client.post(root + '/review/missing-items', json={
        "operationId": str(uuid4()), "expectedRevision": linked.json()["review"]["reviewRevision"],
        "issueId": issues[1]["id"], "itemId": added.json()["id"],
    })
    assert duplicate.status_code == 422
    removed = await client.delete(root + f"/items/{added.json()['id']}")
    assert removed.status_code == 204, removed.text
    latest = (await client.get(root + '/review')).json()
    assert next(i for i in latest["issues"] if i["id"] == issues[0]["id"])["state"] == "open"


async def test_stale_or_invalid_submissions_do_not_create_a_row(missing_request):
    client, root, original = missing_request
    issue = next(i for i in original["issues"] if i["code"] == "coverage_uncertain")
    for patch, status in [({"expectedRevision": original["reviewRevision"] + 1}, 409),
        ({"item": {**filled(), "quantity": 0}}, 422), ({"issueId": 'not-an-issue'}, 409)]:
        response = await client.post(root + '/review/missing-items', json={
            "operationId": str(uuid4()), "expectedRevision": original["reviewRevision"],
            "issueId": issue["id"], "item": filled(), **patch,
        })
        assert response.status_code == status, response.text
    latest = (await client.get(root + '/review')).json()
    assert len(latest["items"]) == len(original["items"])
    assert latest["reviewRevision"] == original["reviewRevision"]
