from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[1] / "static"


class SPAStaticFiles(StaticFiles):
    """Serve built frontend files while preserving API and asset 404 responses."""

    async def get_response(self, path: str, scope: dict[str, Any]):
        normalized_path = path.lstrip("/")

        if normalized_path == "api" or normalized_path.startswith("api/"):
            raise HTTPException(status_code=404)

        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self._should_serve_index(normalized_path, scope):
                raise
        else:
            if response.status_code != 404:
                return response
            if not self._should_serve_index(normalized_path, scope):
                return response

        return await super().get_response("index.html", scope)

    @staticmethod
    def _should_serve_index(path: str, scope: dict[str, Any]) -> bool:
        if scope["method"] not in {"GET", "HEAD"}:
            return False
        if path == "assets" or path.startswith("assets/"):
            return False
        return not Path(path).suffix


def mount_frontend(app: FastAPI, directory: Path = FRONTEND_DIST_DIR) -> bool:
    """Mount a production frontend build when it is available."""

    if not (directory / "index.html").is_file():
        return False

    app.mount("/", SPAStaticFiles(directory=directory, html=True), name="frontend")
    return True
