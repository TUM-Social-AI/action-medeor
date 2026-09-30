from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from app.jobs import sharepoint_sync as job
from app.offers.contracts import NormalizedOfferUpsertV1
from app.sharepoint.changes import (
    FolderSnapshotChangeSource,
    GraphDeltaChangeSource,
    Item,
    compare,
)
from app.sharepoint.graph import GraphClient, GraphError
from app.sharepoint.store import SavedState

DRIVE = "drive-1"
ROOT = "root-1"
NOW = datetime(2026, 9, 29, tzinfo=UTC)


class Token:
    async def get_token(self) -> str:
        return "test-token"


def item(
    item_id: str,
    parent: str | None = ROOT,
    *,
    name: str | None = None,
    folder: bool = False,
    ctag: str = "c1",
    etag: str = "e1",
) -> Item:
    return Item(
        item_id=item_id,
        parent_id=parent,
        name=name or item_id,
        path=name or item_id,
        web_url=f"https://example.sharepoint.com/{item_id}",
        etag=etag,
        ctag=ctag,
        modified_at=NOW,
        size_bytes=10,
        mime_type=None if folder else "text/plain",
        is_folder=folder,
    )


ROOT_ITEM = replace(item(ROOT, None, folder=True), path="")


@pytest.mark.asyncio
async def test_snapshot_traverses_nested_folders_and_pagination() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        path = request.url.path
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "file-a",
                            "name": "a.csv",
                            "file": {"mimeType": "text/csv"},
                            "parentReference": {"id": ROOT},
                            "cTag": "c1",
                        },
                    ]
                },
            )
        if path.endswith(f"/{ROOT}/children"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "folder",
                            "name": "nested",
                            "folder": {},
                            "parentReference": {"id": ROOT},
                        },
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/drive-1/items/root-1/children?page=2",
                },
            )
        if path.endswith("/folder/children"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "file-b",
                            "name": "b.pdf",
                            "file": {},
                            "parentReference": {"id": "folder"},
                            "cTag": "c1",
                        },
                    ]
                },
            )
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        graph = GraphClient(DRIVE, Token(), client)
        result = await FolderSnapshotChangeSource(graph).enumerate(ROOT_ITEM, {}, None)
    assert set(result.items) == {ROOT, "folder", "file-a", "file-b"}
    assert result.items["file-b"].path == "nested/b.pdf"
    assert len(requests) == 3


@pytest.mark.parametrize(
    ("old", "new", "kind"),
    [
        (None, item("f"), "new"),
        (item("f"), item("f", ctag="c2", etag="e2"), "modified"),
        (item("f"), item("f", name="renamed", etag="e2"), "metadata"),
        (item("f"), item("f", parent="other", etag="e2"), "metadata"),
    ],
)
def test_change_comparison(old: Item | None, new: Item, kind: str) -> None:
    prior = {old.item_id: old} if old else {}
    changes = compare(prior, {new.item_id: new})
    assert [change.kind for change in changes] == [kind]


def test_no_change_and_deletion() -> None:
    old = item("f")
    assert compare({"f": old}, {"f": old}) == []
    assert [change.kind for change in compare({"f": old}, {})] == ["deleted"]


@pytest.mark.asyncio
async def test_delta_initial_pages_and_followup_change() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/delta") and not request.url.params:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "f",
                            "name": "f.txt",
                            "file": {},
                            "parentReference": {"id": ROOT},
                            "eTag": "e1",
                        }
                    ],
                    "@odata.nextLink": f"https://graph.microsoft.com/v1.0/drives/{DRIVE}/items/{ROOT}/delta?page=2",
                },
            )
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.deltaLink": f"https://graph.microsoft.com/v1.0/drives/{DRIVE}/items/{ROOT}/delta?token=next",
                },
            )
        if request.url.params.get("token") == "next":
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "f",
                            "name": "f.txt",
                            "file": {},
                            "parentReference": {"id": ROOT},
                            "eTag": "e2",
                        }
                    ],
                    "@odata.deltaLink": f"https://graph.microsoft.com/v1.0/drives/{DRIVE}/items/{ROOT}/delta?token=again",
                },
            )
        if request.url.path.endswith("/f"):
            version = "c2" if any("token=next" in call for call in calls) else "c1"
            return httpx.Response(
                200,
                json={
                    "id": "f",
                    "name": "f.txt",
                    "file": {},
                    "parentReference": {"id": ROOT},
                    "eTag": "e2" if version == "c2" else "e1",
                    "cTag": version,
                    "webUrl": "https://example.sharepoint.com/f",
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GraphDeltaChangeSource(GraphClient(DRIVE, Token(), client))
        initial = await source.enumerate(ROOT_ITEM, {}, None)
        assert initial.items["f"].ctag == "c1"
        followup = await source.enumerate(ROOT_ITEM, initial.items, initial.delta_link)
        assert followup.items["f"].ctag == "c2"
        assert compare(initial.items, followup.items)[0].kind == "modified"
        assert followup.delta_link.endswith("token=again")


@pytest.mark.asyncio
async def test_delta_403_falls_back_to_folder_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/delta"):
            return httpx.Response(
                403,
                json={
                    "error": {
                        "code": "accessDenied",
                        "message": "Selected permission is insufficient",
                    }
                },
            )
        if request.url.path.endswith("/children"):
            return httpx.Response(200, json={"value": []})
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        graph = GraphClient(DRIVE, Token(), client)
        result = await job.choose_enumeration(graph, ROOT_ITEM, {}, None, None)
    assert result.mode == "snapshot"


@pytest.mark.asyncio
async def test_children_403_is_fatal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": {"code": "accessDenied", "message": "Folder is unavailable"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        graph = GraphClient(DRIVE, Token(), client)
        with pytest.raises(GraphError, match="SelectedOperations"):
            await FolderSnapshotChangeSource(graph).enumerate(ROOT_ITEM, {}, None)


@pytest.mark.asyncio
async def test_sync_extraction_failure_does_not_commit_or_call_offer_api(monkeypatch) -> None:
    class FakeGraph:
        drive_id = DRIVE

        async def get_item(self, item_id):
            return {"id": ROOT, "name": "root", "folder": {}}

        async def list_children(self, folder_id):
            return [
                {
                    "id": "f",
                    "name": "f.txt",
                    "file": {},
                    "cTag": "c1",
                    "webUrl": "https://example.sharepoint.com/f",
                }
            ]

        async def download(self, item_id):
            return b"hello"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    saved = []

    async def fake_load(*args):
        return SavedState({}, "snapshot", None)

    async def fake_save(*args):
        saved.append(args)

    async def broken_extract(*args):
        raise RuntimeError("extractor failed")

    monkeypatch.setattr(job, "async_session", FakeSession)
    monkeypatch.setattr(job, "load_state", fake_load)
    monkeypatch.setattr(job, "save_success", fake_save)
    with pytest.raises(RuntimeError, match="extractor failed"):
        await job.sync(FakeGraph(), ROOT, extractor=broken_extract)
    assert saved == []

    async def good_extract(*args):
        return NormalizedOfferUpsertV1(
            source_version="smoke-v1",
            source_url="https://example.sharepoint.com/f",
            captured_at=NOW,
            raw_request_text="Mock extraction for f.txt",
            metadata={"extraction_status": "mock"},
        )

    result = await job.sync(FakeGraph(), ROOT, extractor=good_extract)
    assert result["processed"] == 1
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_offer_smoke_makes_one_put_with_stable_identity() -> None:
    puts = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(f"/{ROOT}"):
            return httpx.Response(200, json={"id": ROOT, "name": "root", "folder": {}})
        if path.endswith("/children"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "f",
                            "name": "f.txt",
                            "file": {},
                            "cTag": "c1",
                            "webUrl": "https://example.sharepoint.com/f",
                        }
                    ]
                },
            )
        if path.endswith("/content"):
            return httpx.Response(200, content=b"hello")
        if request.method == "PUT":
            puts.append(request)
            return httpx.Response(200, json={"idempotent_replay": len(puts) > 1})
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        graph = GraphClient(DRIVE, Token(), client)
        first = await job.offer_smoke(graph, ROOT, "http://localhost:8000", client)
        second = await job.offer_smoke(graph, ROOT, "http://localhost:8000", client)
    assert len(puts) == 2  # one per explicit invocation
    assert puts[0].url == puts[1].url
    assert b'"source_version":"smoke-v1"' in puts[0].read()
    assert b'"extraction_status":"mock"' in puts[0].read()
    assert first["external_id"] == second["external_id"]


@pytest.mark.asyncio
async def test_invalid_client_credentials_raise_clear_authentication_error(monkeypatch) -> None:
    from app.sharepoint.graph import AuthenticationError, MsalTokenProvider

    class RejectedApp:
        def acquire_token_for_client(self, *, scopes):
            assert scopes == ["https://graph.microsoft.com/.default"]
            return {"error": "invalid_client", "error_description": "Client credential rejected"}

    monkeypatch.setattr(
        "app.sharepoint.graph.msal.ConfidentialClientApplication",
        lambda *args, **kwargs: RejectedApp(),
    )
    provider = MsalTokenProvider("tenant", "client", "redacted-secret")
    with pytest.raises(AuthenticationError, match="invalid_client"):
        await provider.get_token()


@pytest.mark.asyncio
async def test_download_redirect_does_not_forward_graph_authorization() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "graph.microsoft.com":
            assert request.headers["Authorization"] == "Bearer test-token"
            return httpx.Response(
                302, headers={"Location": "https://example.sharepoint.com/download?preauth=opaque"}
            )
        assert request.url.host == "example.sharepoint.com"
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=b"document bytes")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        graph = GraphClient(DRIVE, Token(), client)
        assert await graph.download("f") == b"document bytes"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_delta_scans_children_of_newly_visible_folder() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/delta"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "nested",
                            "name": "nested",
                            "folder": {},
                            "parentReference": {"id": ROOT},
                        }
                    ],
                    "@odata.deltaLink": f"https://graph.microsoft.com/v1.0/drives/{DRIVE}/items/{ROOT}/delta?token=next",
                },
            )
        if request.url.path.endswith("/nested/children"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "child",
                            "name": "child.pdf",
                            "file": {},
                            "parentReference": {"id": "nested"},
                            "webUrl": "https://example.sharepoint.com/child",
                        },
                    ]
                },
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = GraphDeltaChangeSource(GraphClient(DRIVE, Token(), client))
        result = await source.enumerate(
            ROOT_ITEM,
            {ROOT: ROOT_ITEM},
            f"https://graph.microsoft.com/v1.0/drives/{DRIVE}/items/{ROOT}/delta?token=old",
        )
    assert result.items["child"].path == "nested/child.pdf"
