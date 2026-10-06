"""Mapping persistence and safe custom-column merges through the real review API."""

import os
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.repository import get_request_by_id
from app.db.session import async_session
from app.main import app
from app.parsing import llm_table_classifier
from app.parsing.llm_client import LlmUnavailable
from tests.test_llm_table_classifier import rfq_mapping, rfq_rows
from tests.test_parsing import build_xlsx

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_saved_layout_and_source_rows_preserve_custom_values_and_manual_edits(monkeypatch):
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    call = Mock(return_value=rfq_mapping())
    monkeypatch.setattr(llm_table_classifier, "call_llm", call)
    request_id = None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        try:
            response = await client.post(
                "/api/imports",
                files={
                    "file": (
                        "synthetic-rfq.xlsx",
                        build_xlsx(rfq_rows()),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            request_id = body["requestId"]
            first_id, second_id = [item["id"] for item in body["items"][:2]]
            assert body["usedLlm"] is True
            assert call.call_count == 1
            async with async_session() as session:
                saved = await get_request_by_id(session, request_id)
                assert saved.table_mappings["version"] == 1
                assert saved.table_mappings["tables"]["0"]["mapping"]
                # Position is not a source identity. Force a gap to catch the previous join.
                await session.execute(
                    text("UPDATE request_items SET position = 99 WHERE id = :id"), {"id": first_id}
                )
                await session.commit()
            edited = await client.patch(
                f"/api/requests/{request_id}/items/{second_id}",
                json={"name": "User's corrected name", "notes": "Keep edit"},
            )
            assert edited.status_code == 200, edited.text
            added = await client.post(
                f"/api/requests/{request_id}/items",
                json={
                    "name": "Manual catheter",
                    "quantity": 2,
                    "unit": "pcs",
                    "domain": "equipment",
                },
            )
            assert added.status_code == 201, added.text
            custom = await client.post(
                f"/api/requests/{request_id}/custom-columns",
                json={"displayName": "Pack breakdown", "hint": "UNITS PER PACK"},
            )
            assert custom.status_code == 200, custom.text
            assert call.call_count == 1
            items = {item["id"]: item for item in custom.json()["items"]}
            assert items[first_id]["attributes"]["Pack breakdown"] == "1"
            assert items[second_id]["name"] == "User's corrected name"
            assert items[second_id]["notes"] == "Keep edit"
            assert items[added.json()["id"]]["manual"] is True
            assert "Pack breakdown" not in items[added.json()["id"]]["attributes"]
            reopened = await client.get(f"/api/requests/{request_id}/review")
            assert reopened.status_code == 200
            assert reopened.json()["usedLlm"] is True
        finally:
            if request_id:
                await client.delete(f"/api/requests/{request_id}")


@pytest.mark.asyncio
async def test_mapping_failure_is_visible_when_review_reopens(monkeypatch):
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    monkeypatch.setattr(
        llm_table_classifier,
        "call_llm",
        Mock(side_effect=LlmUnavailable("sensitive provider details")),
    )
    request_id = None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        try:
            response = await client.post(
                "/api/imports",
                files={
                    "file": (
                        "synthetic-rfq.xlsx",
                        build_xlsx(rfq_rows()),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            request_id = body["requestId"]
            assert body["usedLlm"] is False
            assert body["parserWarnings"]
            assert "sensitive" not in str(body["parserWarnings"])
            assert all(item["status"] != "verified" for item in body["items"])
            reopened = await client.get(f"/api/requests/{request_id}/review")
            assert reopened.json()["parserWarnings"] == body["parserWarnings"]
        finally:
            if request_id:
                await client.delete(f"/api/requests/{request_id}")


@pytest.mark.asyncio
async def test_free_text_pdf_keeps_custom_column_behavior(monkeypatch):
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    from app.parsing import llm_extractor
    from tests.test_parsing import build_minimal_pdf

    def extract(_prompt, schema):
        return schema.model_validate(
            {
                "items": [
                    {
                        "name": "Catheter CH18",
                        "quantity": 5,
                        "unit": "pcs",
                        "name_confidence": 90,
                        "quantity_confidence": 90,
                        "extra_fields": [{"key": "Brand", "value": "Example manufacturer"}],
                    }
                ]
            }
        )

    monkeypatch.setattr(llm_extractor, "call_llm", extract)
    request_id = None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        try:
            response = await client.post(
                "/api/imports",
                files={
                    "file": (
                        "free-text.pdf",
                        build_minimal_pdf(["5 pcs Catheter CH18 by Example manufacturer"]),
                        "application/pdf",
                    ),
                },
            )
            assert response.status_code == 200, response.text
            request_id = response.json()["requestId"]
            custom = await client.post(
                f"/api/requests/{request_id}/custom-columns", json={"displayName": "Brand"}
            )
            assert custom.status_code == 200, custom.text
            assert custom.json()["items"][0]["attributes"]["Brand"] == "Example manufacturer"
        finally:
            if request_id:
                await client.delete(f"/api/requests/{request_id}")
