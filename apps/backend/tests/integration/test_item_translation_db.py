"""Exercise translation persistence and concurrent cache reuse through HTTP."""

import asyncio
import os
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.parsing import item_translation

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_translation_persists_and_concurrent_calls_reuse_it(monkeypatch):
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    translate = Mock(return_value="Sterile Nadel 21G")
    monkeypatch.setattr(item_translation, "translate_item_name", translate)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        created = await client.post("/api/requests/manual", json={
            "item": {"name": "Sterile needle 21G", "quantity": 2, "domain": "equipment"},
        })
        assert created.status_code == 201, created.text
        request_id = created.json()["requestId"]
        item_id = created.json()["items"][0]["id"]
        path = f"/api/requests/{request_id}/items/{item_id}/translation"
        try:
            responses = await asyncio.gather(client.post(path), client.post(path))
            assert all(response.status_code == 200 for response in responses)
            assert all(response.json() == {"translation": "Sterile Nadel 21G"}
                       for response in responses)
            translate.assert_called_once_with("Sterile needle 21G")
            restored = await client.get(f"/api/requests/{request_id}/matching")
            assert restored.status_code == 200
            assert restored.json()["lines"][0]["translatedName"] == "Sterile Nadel 21G"
            assert restored.json()["lines"][0]["name"] == "Sterile needle 21G"
            assert (await client.post(path)).status_code == 200
            translate.assert_called_once()
            wrong_request = await client.post(
                f"/api/requests/other-request/items/{item_id}/translation"
            )
            assert wrong_request.status_code == 404
        finally:
            assert (await client.delete(f"/api/requests/{request_id}")).status_code == 204
