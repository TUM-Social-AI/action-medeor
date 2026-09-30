"""Small Microsoft Graph client restricted to configured drive-item routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote, urlparse

import httpx
import msal

logger = logging.getLogger(__name__)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    def __init__(self, status: int, path: str, code: str, message: str, response: str) -> None:
        self.status = status
        self.path = path
        self.code = code
        self.message = message
        self.response = response
        suffix = (
            " Current Files.SelectedOperations.Selected folder permission may not support this "
            "operation."
            if status == 403
            else ""
        )
        super().__init__(f"Graph {status} {code} at {path}: {message}.{suffix}")


class AuthenticationError(RuntimeError):
    pass


class MsalTokenProvider:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )

    async def get_token(self) -> str:
        result = await asyncio.to_thread(
            self._app.acquire_token_for_client,
            scopes=["https://graph.microsoft.com/.default"],
        )
        token = result.get("access_token")
        if not isinstance(token, str):
            raise AuthenticationError(
                f"SharePoint authentication failed: {result.get('error', 'unknown_error')}: "
                f"{result.get('error_description', 'no access token returned')}"
            )
        logger.info("SharePoint authentication successful")
        return token


def _safe_path(url: str) -> str:
    """Keep endpoint identity while hiding opaque delta and download URL queries."""
    parsed = urlparse(url)
    return parsed.path or url


def _graph_url(value: str) -> str:
    url = value if value.startswith("https://") else f"{GRAPH_BASE}/{value.lstrip('/')}"
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com":
        raise ValueError("Graph pagination or delta URL must use graph.microsoft.com")
    if not parsed.path.startswith("/v1.0/"):
        raise ValueError("Graph pagination or delta URL must use v1.0")
    return url


class GraphClient:
    def __init__(
        self,
        drive_id: str,
        token_provider: MsalTokenProvider,
        client: httpx.AsyncClient,
    ) -> None:
        self.drive_id = drive_id
        self._tokens = token_provider
        self._client = client

    def item_path(self, item_id: str) -> str:
        return f"drives/{quote(self.drive_id, safe='')}/items/{quote(item_id, safe='')}"

    async def _request(self, path: str, *, follow_redirects: bool = False) -> httpx.Response:
        url = _graph_url(path)
        token = await self._tokens.get_token()
        try:
            response = await self._client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=follow_redirects,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Graph request failed at {_safe_path(url)}: {exc}") from exc
        if response.status_code >= 400:
            try:
                payload = response.json().get("error", {})
            except (ValueError, AttributeError):
                payload = {}
            code = str(payload.get("code", "unknown_error"))
            message = str(payload.get("message", response.reason_phrase))
            body = response.text
            logger.error(
                "Graph failure path=%s status=%s code=%s message=%s response=%s",
                _safe_path(url),
                response.status_code,
                code,
                message,
                body,
            )
            raise GraphError(response.status_code, _safe_path(url), code, message, body)
        return response

    async def get_item(self, item_id: str) -> dict:
        return (await self._request(self.item_path(item_id))).json()

    async def pages(self, path: str) -> AsyncIterator[list[dict]]:
        next_url: str | None = path
        while next_url:
            payload = (await self._request(next_url)).json()
            items = payload.get("value")
            if not isinstance(items, list):
                raise ValueError(f"Graph collection missing value at {_safe_path(next_url)}")
            yield items
            next_url = payload.get("@odata.nextLink")
            if next_url is not None and not isinstance(next_url, str):
                raise ValueError("Invalid Graph nextLink")

    async def list_children(self, folder_id: str) -> list[dict]:
        result: list[dict] = []
        async for page in self.pages(f"{self.item_path(folder_id)}/children"):
            result.extend(page)
        return result

    async def delta(self, folder_id: str, cursor: str | None) -> tuple[list[dict], str]:
        path = cursor or f"{self.item_path(folder_id)}/delta"
        changes: list[dict] = []
        while True:
            payload = (await self._request(path)).json()
            page = payload.get("value")
            if not isinstance(page, list):
                raise ValueError(f"Graph delta missing value at {_safe_path(path)}")
            changes.extend(page)
            next_url = payload.get("@odata.nextLink")
            if next_url:
                path = _graph_url(next_url)
                continue
            delta_link = payload.get("@odata.deltaLink")
            if not isinstance(delta_link, str):
                raise ValueError("Graph delta completed without a deltaLink")
            return changes, _graph_url(delta_link)

    async def download(self, item_id: str) -> bytes:
        response = await self._request(f"{self.item_path(item_id)}/content")
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            parsed = urlparse(location)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("Graph returned an invalid content redirect")
            # The preauthenticated URL must not receive the Graph bearer token.
            try:
                response = await self._client.get(location, follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"SharePoint content download failed for item {item_id}"
                ) from exc
        return response.content
