"""The opt-in example persists like an upload and never resets saved user decisions."""

import os
from uuid import uuid4

import pytest

from app.db.repository import get_request_by_id, to_review_response
from app.db.session import async_session
from app.jobs import seed_review_example as example
from app.review.contracts import ReviewOperation
from app.review.service import apply
from app.review.taxonomy import CATEGORIES

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_example_seed_preserves_progress_on_replay(monkeypatch):
    if not os.getenv("MATCHING_TEST_DATABASE_URL"):
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    example_id = f"EXAMPLE-TEST-{uuid4().hex[:10]}"
    monkeypatch.setattr(example, "REQUEST_ID", example_id)
    async with async_session() as session:
        try:
            request, created = await example.seed_review_example(session)
            assert created
            response = to_review_response(request)
            assert len(response.items) == 21
            assert len(response.removedItems) == 1
            assert request.raw_file.startswith(b"PK")
            assert {i["code"] for i in response.issues} == set(CATEGORIES)
            shared = next(i for i in response.issues if i.get("scope") == "table")
            await apply(
                session,
                request,
                ReviewOperation(
                    operationId=str(uuid4()),
                    expectedRevision=request.review_revision,
                    action="accept",
                    itemIds=[],
                    issueIds=[shared["id"]],
                ),
            )
            saved_revision = request.review_revision
            replay, created = await example.seed_review_example(session)
            assert not created
            assert replay.review_revision == saved_revision
            assert (
                next(i for i in to_review_response(replay).issues if i["id"] == shared["id"])[
                    "state"
                ]
                == "accepted"
            )
        finally:
            request = await get_request_by_id(session, example_id)
            if request:
                await session.delete(request)
                await session.commit()
