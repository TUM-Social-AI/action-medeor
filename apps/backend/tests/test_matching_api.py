from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
)
from app.matching.api import get_matching_service
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import MatchRequestV1
from app.matching.service import MatchingService
from tests.matching.factories import item, line


@pytest.mark.asyncio
async def test_matching_api_creates_and_reads_run() -> None:
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18")]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )

    async def override_matching_service() -> MatchingService:
        return service

    app.dependency_overrides[get_matching_service] = override_matching_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/match-runs",
                json=MatchRequestV1(inquiry_line=line()).model_dump(mode="json"),
            )
            assert response.status_code == 201
            body: dict[str, Any] = response.json()
            assert body["candidates"][0]["item_number"] == "410001001"

            stored = await client.get(f"/api/v1/match-runs/{body['match_run_id']}")
            assert stored.status_code == 200
            assert stored.json() == body
    finally:
        app.dependency_overrides.clear()
