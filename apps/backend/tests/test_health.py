from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_reports_ok_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_database_health() -> dict[str, str]:
        return {"status": "ok"}

    monkeypatch.setattr("app.main.check_database_health", fake_database_health)

    response = await get_health()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_degrades_when_database_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_database_health() -> dict[str, str]:
        return {"status": "error", "detail": "database unavailable"}

    monkeypatch.setattr("app.main.check_database_health", fake_database_health)

    response = await get_health()

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"]["detail"] == "database unavailable"


async def get_health() -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.get("/api/health")
