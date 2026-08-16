from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.frontend import mount_frontend


@pytest.fixture
def frontend_app(tmp_path: Path) -> FastAPI:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<html>frontend</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('frontend')", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/known")
    async def known_api_route() -> dict[str, str]:
        return {"status": "ok"}

    assert mount_frontend(app, tmp_path)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/patients", "/questionnaire/123", "/settings"])
async def test_frontend_routes_return_index(frontend_app: FastAPI, path: str) -> None:
    response = await request(frontend_app, "GET", path)

    assert response.status_code == 200
    assert response.text == "<html>frontend</html>"


@pytest.mark.asyncio
async def test_real_static_asset_is_served(frontend_app: FastAPI) -> None:
    response = await request(frontend_app, "GET", "/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('frontend')"
    assert response.headers["content-type"].startswith("text/javascript")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/assets/missing.js", "/missing.css"])
async def test_missing_static_asset_returns_404(frontend_app: FastAPI, path: str) -> None:
    response = await request(frontend_app, "GET", path)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_known_api_route_takes_precedence(frontend_app: FastAPI) -> None:
    response = await request(frontend_app, "GET", "/api/known")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_unknown_api_route_returns_json_404(frontend_app: FastAPI, method: str) -> None:
    response = await request(frontend_app, method, "/api/unknown")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_backend_only_app_starts_without_frontend(tmp_path: Path) -> None:
    app = FastAPI()

    assert not mount_frontend(app, tmp_path)

    response = await request(app, "GET", "/")
    assert response.status_code == 404


async def request(app: FastAPI, method: str, path: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path)
