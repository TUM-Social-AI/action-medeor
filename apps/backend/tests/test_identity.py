import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.identity import _default_avatar, router
from app.db.session import get_session


class FakeSession:
    def __init__(self, avatar_id: str | None = None) -> None:
        self.avatar_id = avatar_id
        self.executed = False
        self.committed = False

    async def get(self, _model, _user_id: str):
        return SimpleNamespace(avatar_id=self.avatar_id) if self.avatar_id else None

    async def execute(self, _statement) -> None:
        self.executed = True

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: FakeSession()
    return app


async def get(app: FastAPI, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get(path, headers=headers)


def principal(name: str) -> str:
    payload = {"claims": [{"typ": "name", "val": name}]}
    return base64.b64encode(json.dumps(payload).encode()).decode()


@pytest.mark.asyncio
async def test_current_user_reads_entra_display_name(app: FastAPI) -> None:
    response = await get(app, "/api/me", {"x-ms-client-principal": principal("Ada Lovelace")})
    assert response.json() == {"displayName": "Ada Lovelace"}


@pytest.mark.asyncio
async def test_current_user_falls_back_locally(app: FastAPI) -> None:
    response = await get(app, "/api/me")
    assert response.json() == {"displayName": "Local User"}


@pytest.mark.asyncio
async def test_current_user_uses_name_header_when_claim_is_upn(app: FastAPI) -> None:
    response = await get(app, "/api/me", {
        "x-ms-client-principal": principal("ada@example.com"),
        "x-ms-client-principal-name": "Ada Lovelace",
    })
    assert response.json() == {"displayName": "Ada Lovelace"}


@pytest.mark.asyncio
async def test_default_avatar_is_stable_for_each_user(app: FastAPI) -> None:
    response = await get(app, "/api/me/avatar", {"x-ms-client-principal-id": "entra-user-1"})
    assert response.json() == {"avatarId": _default_avatar("entra-user-1")}
    assert _default_avatar("entra-user-1") == _default_avatar("entra-user-1")


@pytest.mark.asyncio
async def test_saved_avatar_wins_over_default(app: FastAPI) -> None:
    app.dependency_overrides[get_session] = lambda: FakeSession("owl")
    response = await get(app, "/api/me/avatar", {"x-ms-client-principal-id": "entra-user-1"})
    assert response.json() == {"avatarId": "owl"}


@pytest.mark.asyncio
async def test_avatar_choice_is_validated_and_saved(app: FastAPI) -> None:
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        invalid = await client.put("/api/me/avatar", json={"avatarId": "invalid"})
        valid = await client.put("/api/me/avatar", json={"avatarId": "fox"})
    assert invalid.status_code == 422
    assert valid.json() == {"avatarId": "fox"}
    assert session.executed and session.committed
