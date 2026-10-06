"""Preferences, cached saved review, protection and stale-result rejection with PostgreSQL."""

import asyncio
import os
import threading
from unittest.mock import Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.db.models import UserExtractionPreferenceRow
from app.db.repository import get_request_by_id
from app.db.session import async_session
from app.main import app
from app.parsing import ai_review
from app.parsing.ai_review import Correction, ReviewBatch
from app.parsing.llm_client import LlmUnavailable
from tests.test_ai_review import checked
from tests.test_excel_first_sheet import workbook_bytes
from tests.test_late_excel_header import (
    checked_covered_request,
    covered_request_mapping,
    covered_request_rows,
)
from tests.test_parsing import build_xlsx
from tests.test_partner_extraction import combined_response

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def client():
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    user = "review-test-" + uuid4().hex
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"x-ms-client-principal-id": user},
    ) as value:
        yield value
    async with async_session() as session:
        await session.execute(
            delete(UserExtractionPreferenceRow).where(UserExtractionPreferenceRow.user_id == user)
        )
        await session.commit()


async def upload(client, filename="scanner.xlsx", rows=None):
    result = await client.post(
        "/api/imports",
        files={
            "file": (
                filename,
                build_xlsx(
                    rows
                    if rows is not None
                    else [
                        ["Product", "Quantity", "Unit", "Type", "Notes"],
                        ["Diagnostic scanner model A", 2, "", "", "Original presentation"],
                    ]
                ),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("mode", ["basic", "balanced"])
async def test_rejected_mapping_with_zero_items_can_be_saved_and_completed_manually(
    client, monkeypatch, mode
):
    from app.parsing import llm_table_classifier
    from app.parsing.llm_table_classifier import ColumnMapping, TableMapping
    from app.parsing.partner_extraction import PartnerEnvelope

    await client.put("/api/me/extraction-preferences", json={"mode": mode})
    # No usable name cells, plus an invalid AI mapping that assigns quantity twice.
    mapper = Mock(return_value=TableMapping(
        header_row_index=0,
        columns=[
            ColumnMapping(column_index=0, role="name", scope="request"),
            ColumnMapping(column_index=1, role="quantity", scope="request"),
            ColumnMapping(column_index=2, role="quantity", scope="request"),
        ],
    ))
    monkeypatch.setattr(llm_table_classifier, "call_llm", mapper)
    monkeypatch.setattr(ai_review, "call_llm", Mock(return_value=PartnerEnvelope(
        partner_json='{"partner":null,"region":null,"contact":null}',
    )))
    body = await upload(client, "missing-names.xlsx", rows=[
        ["Product", "Quantity", "Quantity"], [None, 7, 8],
    ])
    rid = body["requestId"]
    try:
        assert mapper.call_count == 1
        assert body["items"] == []
        assert body["sourceReferences"] == []
        assert body["counts"]["total"] == 0
        assert body["partner"]["confirmed"] is False
        assert any("Columns could not be confirmed" in warning for warning in body["parserWarnings"])
        assert any("No requested line items" in warning for warning in body["parserWarnings"])
        reopened = await client.get(f"/api/requests/{rid}/review")
        assert reopened.status_code == 200
        assert reopened.json()["items"] == []
        assert reopened.json()["parserWarnings"] == body["parserWarnings"]
        async with async_session() as session:
            request = await get_request_by_id(session, rid)
            assert request.ai_review["sources"] == {}
            assert request.workflow_status == "review"
        manual = await client.post(f"/api/requests/{rid}/items", json={
            "name": "Manual catheter", "quantity": 7, "unit": "pcs", "domain": "equipment",
        })
        assert manual.status_code == 201, manual.text
        assert (await client.get(f"/api/requests/{rid}/review")).json()["counts"]["total"] == 1
    finally:
        await client.delete(f"/api/requests/{rid}")


@pytest.mark.parametrize("mode", ["basic", "balanced"])
@pytest.mark.parametrize("use_draft", [False, True])
async def test_empty_first_sheet_warning_persists_for_both_upload_paths(
    client, monkeypatch, mode, use_draft
):
    from app.parsing import llm_table_classifier
    from app.parsing.partner_extraction import PartnerEnvelope

    await client.put("/api/me/extraction-preferences", json={"mode": mode})
    mapper = Mock(side_effect=AssertionError("No mapping for an empty sheet"))
    monkeypatch.setattr(llm_table_classifier, "call_llm", mapper)
    monkeypatch.setattr(ai_review, "call_llm", Mock(return_value=PartnerEnvelope(
        partner_json='{"partner":null,"region":null,"contact":null}',
    )))
    rid = None
    try:
        endpoint = "/api/imports"
        if use_draft:
            created = await client.post("/api/requests")
            assert created.status_code == 201, created.text
            rid = created.json()["requestId"]
            endpoint = f"/api/requests/{rid}/file"
        result = await client.post(endpoint, files={"file": (
            "multi-sheet.xlsx",
            workbook_bytes([], [["Product", "Quantity", "Unit"], ["Later device", 5, "pcs"]]),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )})
        assert result.status_code == 200, result.text
        body = result.json()
        if rid:
            assert body["requestId"] == rid
        rid = body["requestId"]
        assert body["items"] == []
        assert body["partner"]["confirmed"] is False
        assert mapper.call_count == 0
        assert any("delete the unnecessary sheets" in note for note in body["parserWarnings"])
        reopened = await client.get(f"/api/requests/{rid}/review")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["parserWarnings"] == body["parserWarnings"]
        assert reopened.json()["items"] == []
    finally:
        if rid:
            await client.delete(f"/api/requests/{rid}")


async def test_balanced_cover_metadata_import_saves_real_rows_and_source_alignment(client, monkeypatch):
    from app.parsing import llm_table_classifier

    mapper = Mock(return_value=covered_request_mapping())
    reviewer = Mock(side_effect=checked_covered_request)
    monkeypatch.setattr(llm_table_classifier, "call_llm", mapper)
    monkeypatch.setattr(ai_review, "call_llm", reviewer)
    body = await upload(client, "covered-request.xlsx", rows=covered_request_rows())
    rid = body["requestId"]
    try:
        assert body["extractionMode"] == "balanced"
        assert body["counts"]["total"] == 8
        assert body["reviewSummary"]["checked"] == 8
        assert body["reviewSummary"]["unresolved"] == 2
        assert body["partner"]["region"] == "Example Region"
        assert body["partner"]["confirmed"] is False
        assert [reference["row"] for reference in body["sourceReferences"]] == list(range(12, 20))
        added = await client.post(f"/api/requests/{rid}/custom-columns", json={
            "displayName": "Source reviewer note", "hint": "Reviewer note",
        })
        assert added.status_code == 200, added.text
        assert mapper.call_count == reviewer.call_count == 1
        assert [item["attributes"]["Source reviewer note"] for item in added.json()["items"]] == [
            row[7] for row in covered_request_rows()[11:]
        ]
        assert added.json()["partner"] == body["partner"]
        assert added.json()["reviewSummary"] == body["reviewSummary"]
        reopened = await client.get(f"/api/requests/{rid}/review")
        assert reopened.json()["items"] == added.json()["items"]
    finally:
        await client.delete(f"/api/requests/{rid}")


async def test_partner_suggestions_confirmation_edits_and_item_retry_are_independent(
    client, monkeypatch
):
    call = Mock(side_effect=combined_response)
    monkeypatch.setattr(ai_review, "call_llm", call)
    body = await upload(client, "Anfrage 127 Somalia UHO.xlsx")
    rid = body["requestId"]
    try:
        assert body["partner"]["partner"] == "UHO"
        assert body["partner"]["region"] == "Somalia"
        assert body["partner"]["contact"] == ""
        assert body["partner"]["confirmed"] is False
        assert call.call_count == 1
        assert body["reviewSummary"]["status"] == "completed"
        assert (await client.get(f"/api/requests/{rid}/review")).json()["partner"] == body[
            "partner"
        ]
        confirmed = (await client.post(f"/api/requests/{rid}/partner/confirm")).json()
        assert confirmed["confirmed"] is True
        unchanged = await client.patch(f"/api/requests/{rid}/partner", json=confirmed)
        assert unchanged.status_code == 200
        assert unchanged.json()["confirmed"] is True
        changed = await client.patch(
            f"/api/requests/{rid}/partner",
            json={
                **confirmed,
                "contact": "Human contact",
                "requestId": "cannot-change-system-id",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["confirmed"] is False
        assert changed.json()["requestId"] == rid
        expected = (await client.post(f"/api/requests/{rid}/partner/confirm")).json()
        item_id = body["items"][0]["id"]
        await client.patch(f"/api/requests/{rid}/items/{item_id}", json={"notes": "Human notes"})
        reviewed = await client.post(f"/api/requests/{rid}/ai-review")
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["partner"] == expected
        await client.post(f"/api/requests/{rid}/custom-columns", json={"displayName": "Notes"})
        assert (await client.get(f"/api/requests/{rid}/review")).json()["partner"] == expected
        assert call.call_count == 2
    finally:
        await client.delete(f"/api/requests/{rid}")


async def test_basic_partner_document_labels_persist_without_ai_calls(client, monkeypatch):
    await client.put("/api/me/extraction-preferences", json={"mode": "basic"})
    call = Mock(side_effect=AssertionError("Basic metadata must not call AI"))
    monkeypatch.setattr(ai_review, "call_llm", call)
    body = await upload(
        client,
        "Anfrage 127 Somalia UHO.xlsx",
        rows=[
            ["Requester", "Health Relief"],
            ["Country", "Uganda"],
            ["Contact", "test@example.test"],
            ["Product", "Quantity", "Unit", "Type"],
            ["Diagnostic scanner", 2, "pcs", "Equipment"],
        ],
    )
    rid = body["requestId"]
    try:
        assert {
            key: body["partner"][key] for key in ("partner", "region", "contact", "confirmed")
        } == {
            "partner": "Health Relief",
            "region": "Uganda",
            "contact": "test@example.test",
            "confirmed": False,
        }
        assert call.call_count == 0
        assert (await client.get(f"/api/requests/{rid}/review")).json()["partner"] == body[
            "partner"
        ]
        async with async_session() as session:
            saved = await get_request_by_id(session, rid)
            assert not saved.confirmed
            assert saved.contact == "test@example.test"
    finally:
        await client.delete(f"/api/requests/{rid}")


async def test_partner_edit_waits_for_confirmation_transaction_and_resets_it(client, monkeypatch):
    from app.db import repository

    monkeypatch.setattr(ai_review, "call_llm", Mock(side_effect=combined_response))
    body = await upload(client, "Anfrage 127 Somalia UHO.xlsx")
    rid = body["requestId"]
    original = repository.get_request_by_id
    entered = asyncio.Event()
    locks = []

    async def observed(session, request_id, *, lock=False):
        if request_id == rid:
            locks.append(lock)
            entered.set()
        return await original(session, request_id, lock=lock)

    monkeypatch.setattr(repository, "get_request_by_id", observed)
    task = None
    try:
        async with async_session() as session:
            request = await original(session, rid, lock=True)
            request.confirmed = True
            task = asyncio.create_task(client.patch(f"/api/requests/{rid}/partner", json={
                **body["partner"], "contact": "Later human edit",
            }))
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert not task.done(), "the edit must wait for the confirmation transaction"
            await session.commit()
        response = await asyncio.wait_for(task, timeout=5)
        assert response.status_code == 200, response.text
        assert response.json()["confirmed"] is False
        assert locks == [True, True]
        async with async_session() as session:
            saved = await original(session, rid)
            assert not saved.confirmed and saved.contact == "Later human edit"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.delete(f"/api/requests/{rid}")


async def test_balanced_default_basic_preference_and_saved_review_cache(client, monkeypatch):
    call = Mock(side_effect=checked)
    monkeypatch.setattr(ai_review, "call_llm", call)
    assert (await client.get("/api/me/extraction-preferences")).json() == {"mode": "balanced"}
    balanced = await upload(client)
    basic = None
    try:
        assert balanced["extractionMode"] == "balanced"
        assert balanced["items"][0]["verificationSource"] == "ai"
        assert balanced["items"][0]["confidence"] == 95
        assert balanced["items"][0]["inferredFields"]["unit"]
        assert balanced["reviewSummary"]["unresolved"] == 0
        assert call.call_count == 1
        saved = await client.post(f"/api/requests/{balanced['requestId']}/ai-review")
        assert saved.status_code == 200 and call.call_count == 1
        put = await client.put("/api/me/extraction-preferences", json={"mode": "basic"})
        assert put.status_code == 200
        assert (await client.get("/api/me/extraction-preferences")).json()["mode"] == "basic"
        invalid = await client.put("/api/me/extraction-preferences", json={"mode": "everything"})
        assert invalid.status_code == 422
        basic = await upload(client)
        assert basic["extractionMode"] == "basic"
        assert basic["items"][0]["verificationSource"] is None
        assert call.call_count == 1
        reviewed = await client.post(f"/api/requests/{basic['requestId']}/ai-review")
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["items"][0]["verificationSource"] == "ai"
        assert call.call_count == 2
        assert reviewed.json()["extractionMode"] == "basic"
        assert (await client.get("/api/me/extraction-preferences")).json()["mode"] == "basic"
        await client.post(f"/api/requests/{basic['requestId']}/ai-review")
        assert call.call_count == 2
        reopened = (await client.get(f"/api/requests/{balanced['requestId']}/review")).json()
        assert reopened["extractionMode"] == "balanced"
    finally:
        await client.delete(f"/api/requests/{balanced['requestId']}")
        if basic:
            await client.delete(f"/api/requests/{basic['requestId']}")


@pytest.mark.parametrize("failure", ["unavailable", "invalid"])
async def test_failure_is_visible_and_retryable(client, monkeypatch, failure):
    if failure == "unavailable":
        call = Mock(side_effect=LlmUnavailable("Do not expose sensitive provider details"))
    else:
        call = Mock(
            return_value=ReviewBatch(
                confidence=95,
                completed=True,
                reviewed_count=1,
                corrections=[
                    Correction(
                        row_id="row-0001", field="quantity", value=999, inferred=False, evidence="2"
                    )
                ],
                issues=[],
            )
        )
    monkeypatch.setattr(ai_review, "call_llm", call)
    body = await upload(client)
    rid = body["requestId"]
    try:
        assert body["reviewSummary"]["status"] == "unavailable"
        assert "provider details" not in body["reviewSummary"]["message"]
        assert body["items"][0]["verificationSource"] is None
        assert body["items"][0]["status"] != "verified"
        call.side_effect = checked
        result = await client.post(f"/api/requests/{rid}/ai-review")
        assert result.status_code == 200, result.text
        assert result.json()["reviewSummary"]["status"] == "completed"
        assert result.json()["items"][0]["status"] == "verified"
        assert call.call_count == 2
        async with async_session() as session:
            saved = await get_request_by_id(session, rid)
            assert saved.ai_review["attempt_history"][-1]["status"] == "unavailable"
            assert saved.ai_review["attempt_history"][-1]["failures"]
    finally:
        await client.delete(f"/api/requests/{rid}")


async def test_edits_manual_rows_and_custom_columns_preserve_review(client, monkeypatch):
    call = Mock(side_effect=checked)
    monkeypatch.setattr(ai_review, "call_llm", call)
    body = await upload(client)
    rid = body["requestId"]
    item_id = body["items"][0]["id"]
    try:
        edit = await client.patch(
            f"/api/requests/{rid}/items/{item_id}", json={"notes": "Human presentation"}
        )
        assert edit.status_code == 200
        assert edit.json()["verificationSource"] == "human"
        manual = await client.post(
            f"/api/requests/{rid}/items",
            json={"name": "Manual device", "quantity": 3, "unit": "pcs", "domain": "equipment"},
        )
        assert manual.status_code == 201
        columns = await client.post(
            f"/api/requests/{rid}/custom-columns",
            json={"displayName": "Source notes", "hint": "Notes"},
        )
        assert columns.status_code == 200, columns.text
        item = next(i for i in columns.json()["items"] if i["id"] == item_id)
        assert item["notes"] == "Human presentation"
        assert item["verificationSource"] == "human"
        assert item["inferredFields"]["unit"]
        assert item["attributes"]["Source notes"] == "Original presentation"
        assert call.call_count == 1

        # A source-supported proposal cannot overwrite a human edit.
        def discrepancy(prompt, schema):
            result = checked(prompt, schema)
            result.corrections.append(
                Correction(
                    row_id=str(item_id),
                    field="notes",
                    value="Original presentation",
                    inferred=False,
                    evidence="Original presentation",
                )
            )
            return result

        call.side_effect = discrepancy
        review = await client.post(f"/api/requests/{rid}/ai-review")
        assert review.status_code == 200, review.text
        items = {i["id"]: i for i in review.json()["items"]}
        assert items[item_id]["notes"] == "Human presentation"
        assert items[item_id]["reviewReasons"]
        assert items[manual.json()["id"]]["verificationSource"] == "human"
        assert items[manual.json()["id"]]["status"] == "verified"
        assert call.call_count == 2
    finally:
        await client.delete(f"/api/requests/{rid}")


async def test_legacy_values_are_preserved_but_gaps_can_be_filled(client, monkeypatch):
    await client.put("/api/me/extraction-preferences", json={"mode": "basic"})
    body = await upload(client)
    rid = body["requestId"]
    item_id = body["items"][0]["id"]
    try:
        async with async_session() as session:
            await session.execute(
                text(
                    "UPDATE request_items SET protected_fields = NULL, notes = :notes WHERE id = :id"
                ),
                {"notes": "Legacy notes", "id": item_id},
            )
            await session.execute(
                text("UPDATE import_requests SET ai_review = '{}' WHERE request_id = :id"),
                {"id": rid},
            )
            await session.commit()

        def model(prompt, schema):
            result = checked(prompt, schema)
            result.corrections.append(
                Correction(
                    row_id=str(item_id),
                    field="notes",
                    value="Original presentation",
                    inferred=False,
                    evidence="Original presentation",
                )
            )
            return result

        monkeypatch.setattr(ai_review, "call_llm", model)
        result = await client.post(f"/api/requests/{rid}/ai-review")
        assert result.status_code == 200, result.text
        item = result.json()["items"][0]
        assert item["notes"] == "Legacy notes"
        assert item["domain"] == "equipment" and item["unit"] == "pcs"
        assert item["status"] == "needs_review"
    finally:
        await client.delete(f"/api/requests/{rid}")


@pytest.mark.parametrize("change", ["edit", "matching"])
async def test_stale_results_are_rejected_atomically(client, monkeypatch, change):
    await client.put("/api/me/extraction-preferences", json={"mode": "basic"})
    body = await upload(client)
    rid = body["requestId"]
    item_id = body["items"][0]["id"]
    entered, release = threading.Event(), threading.Event()

    def slow(prompt, schema):
        entered.set()
        assert release.wait(10)
        return checked(prompt, schema)

    monkeypatch.setattr(ai_review, "call_llm", slow)
    pending = asyncio.create_task(client.post(f"/api/requests/{rid}/ai-review"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        if change == "edit":
            edit = await client.patch(
                f"/api/requests/{rid}/items/{item_id}", json={"notes": "Concurrent edit"}
            )
            assert edit.status_code == 200
        else:
            async with async_session() as session:
                await session.execute(
                    text(
                        "UPDATE import_requests SET workflow_status = 'matching_queued' WHERE request_id = :id"
                    ),
                    {"id": rid},
                )
                await session.commit()
        release.set()
        result = await pending
        assert result.status_code == 409, result.text
        async with async_session() as session:
            saved = await get_request_by_id(session, rid)
            assert saved.items[0].unit == ""
            assert saved.items[0].verification_source != "ai"
            if change == "edit":
                assert saved.items[0].notes == "Concurrent edit"
            else:
                assert saved.workflow_status == "matching_queued"
        if change == "matching":
            locked = await client.post(f"/api/requests/{rid}/ai-review")
            assert locked.status_code == 409
    finally:
        release.set()
        if not pending.done():
            await pending
        async with async_session() as session:
            await session.execute(
                text(
                    "UPDATE import_requests SET workflow_status = 'review' WHERE request_id = :id"
                ),
                {"id": rid},
            )
            await session.commit()
        await client.delete(f"/api/requests/{rid}")


async def test_free_text_extraction_receives_same_balanced_review(client, monkeypatch):
    from app.parsing import free_text_parser
    from app.parsing.types import ParsedDocument, ParsedLineItem
    from tests.test_parsing import build_docx

    extraction = Mock(
        return_value=ParsedDocument(
            items=[
                ParsedLineItem(
                    name="Diagnostic scanner model A",
                    quantity=2,
                    unit="",
                    excerpt="Diagnostic scanner model A: 2 pcs",
                )
            ]
        )
    )
    monkeypatch.setattr(free_text_parser, "extract_items_with_llm", extraction)
    review = Mock(side_effect=checked)
    monkeypatch.setattr(ai_review, "call_llm", review)
    result = await client.post(
        "/api/imports",
        files={
            "file": (
                "scanner.docx",
                build_docx(["Diagnostic scanner model A: 2 pcs"]),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert result.status_code == 200, result.text
    rid = result.json()["requestId"]
    try:
        assert extraction.call_count == 1 and review.call_count == 1
        item = result.json()["items"][0]
        assert item["status"] == "verified" and item["verificationSource"] == "ai"
        assert item["domain"] == "equipment" and item["unit"] == "pcs"
        await client.post(f"/api/requests/{rid}/ai-review")
        assert extraction.call_count == 1 and review.call_count == 1
    finally:
        await client.delete(f"/api/requests/{rid}")
