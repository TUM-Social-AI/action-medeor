from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from app.jobs import sharepoint_sync as job
from app.sharepoint import processing
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
async def test_inspect_lists_selected_nested_folder_without_crawling() -> None:
    class Graph:
        requested = []

        async def get_item(self, item_id):
            self.requested.append(item_id)
            parents = {ROOT: None, "equipment": ROOT, "nested": "equipment"}
            return {
                "id": item_id,
                "name": item_id,
                "folder": {},
                "parentReference": {"id": parents[item_id]} if parents[item_id] else {},
            }

        async def list_children(self, folder_id):
            assert folder_id == "nested"
            return [
                {"id": "offer", "name": "offer.pdf", "file": {}},
                {"id": "deeper", "name": "deeper", "folder": {}},
            ]

    graph = Graph()
    result = await job.inspect_folder(graph, ROOT, "nested")
    assert result["path"] == "equipment/nested"
    assert result["children"] == [
        {"id": "offer", "name": "offer.pdf", "folder": False},
        {"id": "deeper", "name": "deeper", "folder": True},
    ]
    assert graph.requested == [ROOT, "nested", "equipment"]


@pytest.mark.asyncio
async def test_inspect_rejects_folder_outside_root_before_listing() -> None:
    class Graph:
        async def get_item(self, item_id):
            parents = {ROOT: None, "outside": "other-root", "other-root": None}
            return {
                "id": item_id,
                "name": item_id,
                "folder": {},
                "parentReference": {"id": parents[item_id]} if parents[item_id] else {},
            }

        async def list_children(self, folder_id):
            raise AssertionError("Outside folder must not be listed")

    with pytest.raises(ValueError, match="outside the permitted"):
        await job.inspect_folder(Graph(), ROOT, "outside")


def test_process_one_empty_report_exits_successfully(monkeypatch, tmp_path) -> None:
    async def run(*args):
        assert args[0] == "process-one"
        return {
            "status": "completed",
            "processed": 1,
            "failed": 0,
            "offers_in_document": 0,
            "no_offers_detected": True,
            "catalog_api_call_count": 0,
            "offer_repository_write_count": 0,
            "offer_repository_writes": [],
            "embeddings": [],
            "matching": {"verified": False, "skipped": True},
        }

    report = tmp_path / "one.json"
    monkeypatch.setattr(job, "run", run)
    monkeypatch.setattr(
        sys, "argv", ["sharepoint_sync", "process-one", "--item-id", "f", "--output", str(report)]
    )
    job.main()
    saved = json.loads(report.read_text())
    assert saved["no_offers_detected"]
    assert saved["catalog_api_call_count"] == 0
    assert saved["offer_repository_writes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("offer_count", [0, 2])
async def test_processing_report_lists_each_offer_write(monkeypatch, offer_count) -> None:
    from app.core.config import Settings
    from app.offers.contracts import NormalizedOfferUpsertV1
    from app.offers.extraction import OfferExtraction
    from app.sharepoint.extraction import OfferBatch
    from app.sharepoint.scope import content_version

    source = replace(item("f", "equipment", name="f.pdf"), domain="equipment")
    source = replace(source, mime_type="application/pdf")
    record = {
        "drive_id": DRIVE,
        "folder_id": ROOT,
        "item_id": "f",
        "content_version": content_version(source),
        "item_json": json.loads(processing.item_json(source)),
    }

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Graph:
        drive_id = DRIVE

        async def download(self, item_id, *, max_bytes):
            assert item_id == "f"
            return b"example"

    async def claim(*args):
        return record

    async def resolve(*args):
        return source

    async def extract(*args, **kwargs):
        offers = [
            NormalizedOfferUpsertV1(
                source_version="v1",
                source_url=source.web_url,
                captured_at=NOW,
                raw_request_text=f"Product {number}",
                supplier="Supplier A",
                metadata={"source_id": f"Sheet!A{number}", "alternative_index": 1},
            )
            for number in range(offer_count)
        ]
        return OfferBatch(offers, OfferExtraction(chunks_succeeded=1))

    async def publish(session, job, batch):
        return [f"offer-{number}" for number in range(len(batch.offers))]

    monkeypatch.setattr(processing, "claim", claim)
    monkeypatch.setattr(processing, "resolve_item", resolve)
    monkeypatch.setattr(processing, "publish", publish)
    settings = Settings(_env_file=None, sharepoint_equipment_folder_id="equipment")
    report = await processing.process_pending(
        Graph(), ROOT, settings, Session, item_id="f", extractor=extract
    )
    assert report["processed"] == 1
    assert report["catalog_api_call_count"] == 0
    assert report["offer_repository_write_count"] == offer_count
    assert len(report["offer_repository_writes"]) == offer_count
    assert [
        write["payload"]["raw_request_text"] for write in report["offer_repository_writes"]
    ] == [f"Product {number}" for number in range(offer_count)]
    assert report["no_offer_item_ids"] == (["f"] if offer_count == 0 else [])


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
                            "name": "f.pdf",
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
                            "name": "f.pdf",
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
                    "name": "f.pdf",
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
async def test_sync_commits_discovery_before_processing_and_defaults_to_no_download(monkeypatch):
    from dataclasses import replace

    from app.core.config import Settings
    from app.sharepoint.changes import Enumeration

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def scalar(self, *args):
            return True

    class FakeGraph:
        drive_id = DRIVE

        async def get_item(self, item_id):
            return {"id": ROOT, "name": "root", "folder": {}}

        async def download(self, *args, **kwargs):
            raise AssertionError("Discovery must not download documents")

    folder = replace(ROOT_ITEM, item_id="equipment", parent_id=ROOT)
    document = replace(ROOT_ITEM, item_id="f", parent_id="equipment", is_folder=False, name="f.pdf")
    events = []

    async def fake_load(*args):
        return SavedState({}, "snapshot", None)

    async def fake_enumeration(*args):
        return Enumeration({ROOT: ROOT_ITEM, "equipment": folder, "f": document}, "snapshot", None)

    async def fake_save(*args):
        events.append("saved")

    async def fake_process(*args, **kwargs):
        assert events[-1] == "saved"
        events.append("processed")
        return {"processed": 0, "failed": 1}

    async def fake_embed(*args, **kwargs):
        return []

    monkeypatch.setattr(job, "async_session", FakeSession)
    monkeypatch.setattr(job, "load_state", fake_load)
    monkeypatch.setattr(job, "choose_enumeration", fake_enumeration)
    monkeypatch.setattr(job, "save_success", fake_save)
    monkeypatch.setattr(job, "process_pending", fake_process)
    monkeypatch.setattr(job, "embed_pending", fake_embed)
    settings = Settings(_env_file=None, sharepoint_equipment_folder_id="equipment")
    result = await job.sync(FakeGraph(), ROOT, settings=settings)
    assert result["processed"] == 0 and events == ["saved"]
    settings.sharepoint_processing_enabled = True
    result = await job.sync(FakeGraph(), ROOT, settings=settings)
    assert result["cursor_updated"] and result["failed"] == 1
    assert events == ["saved", "saved", "processed"]

    async def empty_document(*args, **kwargs):
        return {
            "processed": 1,
            "failed": 0,
            "offers": 0,
            "attempted_item_ids": ["f"],
            "successful_offer_item_ids": [],
            "no_offer_item_ids": ["f"],
        }

    async def no_embedding(*args, **kwargs):
        raise AssertionError("An empty document must not start embeddings")

    monkeypatch.setattr(job, "process_pending", empty_document)
    monkeypatch.setattr(job, "embed_pending", no_embedding)
    result = await job.sync(FakeGraph(), ROOT, settings=settings)
    assert result["no_offer_item_ids"] == ["f"]
    assert result["embeddings"] == []


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
                            "name": "f.pdf",
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
