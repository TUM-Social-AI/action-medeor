"""One-shot SharePoint folder test, sync, and single-call offer API smoke check.

From apps/backend: uv run python -m app.jobs.sharepoint_sync test|sync|offer-smoke
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace

import httpx

from app.core.config import Settings, get_settings
from app.db.session import async_session, engine
from app.offers.contracts import NormalizedOfferUpsertV1
from app.sharepoint.changes import (
    DeltaUnavailable,
    Enumeration,
    FolderSnapshotChangeSource,
    GraphDeltaChangeSource,
    Item,
    SharePointChange,
    compare,
    parse_item,
)
from app.sharepoint.extraction import DownloadedDocument, extract
from app.sharepoint.graph import GraphClient, GraphError, MsalTokenProvider
from app.sharepoint.store import load_state, save_success

logger = logging.getLogger(__name__)
Extractor = Callable[[SharePointChange, DownloadedDocument], Awaitable[NormalizedOfferUpsertV1]]


def required_config(settings: Settings) -> None:
    names = (
        "sharepoint_tenant_id",
        "sharepoint_client_id",
        "sharepoint_client_secret",
        "sharepoint_drive_id",
        "sharepoint_root_folder_id",
    )
    missing = [name.upper() for name in names if not getattr(settings, name)]
    if missing:
        raise ValueError(f"Missing SharePoint configuration: {', '.join(missing)}")


async def root_item(graph: GraphClient, folder_id: str) -> Item:
    root = parse_item(await graph.get_item(folder_id))
    if not root.is_folder:
        raise ValueError("SHAREPOINT_ROOT_FOLDER_ID does not point to a folder")
    return replace(root, parent_id=None, path="")


async def choose_enumeration(
    graph: GraphClient,
    root: Item,
    prior: dict[str, Item],
    mode: str | None,
    cursor: str | None,
) -> Enumeration:
    if mode == "snapshot":
        return await FolderSnapshotChangeSource(graph).enumerate(root, prior, None)

    async def validated_delta(link: str | None) -> Enumeration:
        delta = await GraphDeltaChangeSource(graph).enumerate(root, prior, link)
        if link is None:
            snapshot = await FolderSnapshotChangeSource(graph).enumerate(root, prior, None)
            if set(delta.items) != set(snapshot.items):
                raise DeltaUnavailable(
                    "Initial delta enumeration disagrees with the permitted folder listing"
                )
        return delta

    try:
        return await validated_delta(cursor)
    except GraphError as exc:
        if exc.status == 410 and cursor:
            logger.warning("SharePoint delta cursor expired; retrying initial delta")
            try:
                return await validated_delta(None)
            except (GraphError, DeltaUnavailable, ValueError) as reset_exc:
                if not isinstance(reset_exc, GraphError):
                    logger.warning("Delta reset unusable: %s", reset_exc)
                    return await FolderSnapshotChangeSource(graph).enumerate(root, prior, None)
                exc = reset_exc
        if exc.status not in (400, 403, 404, 410):
            raise
        logger.warning(
            "Folder delta unavailable at %s: HTTP %s %s (%s). "
            "Microsoft documents Files.Read.All for application delta access; "
            "using configured-folder snapshot instead.",
            exc.path,
            exc.status,
            exc.code,
            exc.message,
        )
    except (DeltaUnavailable, ValueError) as exc:
        logger.warning("Folder delta unusable (%s); using configured-folder snapshot", exc)
    return await FolderSnapshotChangeSource(graph).enumerate(root, prior, None)


async def test_connection(graph: GraphClient, folder_id: str) -> dict[str, object]:
    root = await root_item(graph, folder_id)
    enumeration = await FolderSnapshotChangeSource(graph).enumerate(root, {}, None)
    files = sorted(
        (item for item in enumeration.items.values() if item.is_file), key=lambda item: item.item_id
    )
    folders = [item for item in enumeration.items.values() if item.is_folder]
    logger.info("Source drive=%s folder=%s name=%s", graph.drive_id, folder_id, root.name)
    for item in files:
        logger.info("Visible file name=%s id=%s path=%s", item.name, item.item_id, item.path)
    downloaded = False
    if files:
        content = await graph.download(files[0].item_id)
        downloaded = True
        logger.info("Download succeeded: id=%s bytes=%d", files[0].item_id, len(content))
    else:
        logger.info("No visible file available for download test")
    result = {
        "drive_id": graph.drive_id,
        "folder_id": folder_id,
        "folder_name": root.name,
        "files": len(files),
        "folders": len(folders) - 1,
        "downloaded": downloaded,
    }
    logger.info("Connectivity test finished: %s", result)
    return result


async def sync(
    graph: GraphClient,
    folder_id: str,
    *,
    extractor: Extractor = extract,
) -> dict[str, object]:
    logger.info("SharePoint sync started drive=%s folder=%s", graph.drive_id, folder_id)
    processed = 0
    try:
        async with async_session() as session:
            prior = await load_state(session, graph.drive_id, folder_id)
        root = await root_item(graph, folder_id)
        logger.info("Source folder name=%s", root.name)
        enumeration = await choose_enumeration(
            graph,
            root,
            prior.items,
            prior.mode,
            prior.delta_link,
        )
        changes = compare(prior.items, enumeration.items)
        counts = {
            kind: sum(change.kind == kind for change in changes)
            for kind in ("new", "modified", "metadata", "deleted")
        }
        logger.info(
            "Discovered changes=%d new=%d modified=%d metadata=%d deleted=%d mode=%s",
            len(changes),
            counts["new"],
            counts["modified"],
            counts["metadata"],
            counts["deleted"],
            enumeration.mode,
        )
        for change in changes:
            if change.kind not in ("new", "modified"):
                continue
            content = await graph.download(change.item.item_id)
            document = DownloadedDocument(
                sharepoint_item_id=change.item.item_id,
                filename=change.item.name,
                mime_type=change.item.mime_type,
                content=content,
                modified_at=change.item.modified_at,
            )
            # The future extraction implementation receives this same change/document boundary.
            result = await extractor(change, document)
            if not isinstance(result, NormalizedOfferUpsertV1):
                raise TypeError("SharePoint extractor must return NormalizedOfferUpsertV1")
            processed += 1
        async with async_session() as session:
            await save_success(
                session,
                graph.drive_id,
                folder_id,
                enumeration,
                prior,
                changes,
            )
    except Exception:
        logger.exception(
            "SharePoint sync failed processed=%d failed=1 cursor_updated=no", processed
        )
        raise
    logger.info("SharePoint sync finished processed=%d failed=0 cursor_updated=yes", processed)
    return {
        "mode": enumeration.mode,
        "changes": len(changes),
        **counts,
        "processed": processed,
        "failed": 0,
    }


async def offer_smoke(
    graph: GraphClient,
    folder_id: str,
    api_url: str,
    client: httpx.AsyncClient,
    *,
    extractor: Extractor = extract,
) -> dict[str, object]:
    root = await root_item(graph, folder_id)
    enumeration = await FolderSnapshotChangeSource(graph).enumerate(root, {}, None)
    files = sorted(
        (item for item in enumeration.items.values() if item.is_file), key=lambda item: item.item_id
    )
    if not files:
        raise ValueError("No file in the configured folder is available for the offer smoke test")
    item = files[0]
    content = await graph.download(item.item_id)
    change = SharePointChange("new", item)
    payload = await extractor(
        change,
        DownloadedDocument(item.item_id, item.name, item.mime_type, content, item.modified_at),
    )
    # Fixed identity and version ensure repeated explicit smoke invocations do not create versions.
    external_id = (
        "sharepoint-smoke-"
        + hashlib.sha256(f"{graph.drive_id}:{folder_id}".encode()).hexdigest()[:24]
    )
    body = payload.model_dump(mode="json")
    body["source_version"] = "smoke-v1"
    body["metadata"].update(
        {
            "extraction_status": "mock",
            "sharepoint_drive_id": graph.drive_id,
            "sharepoint_root_folder_id": folder_id,
            "sharepoint_item_id": item.item_id,
            "sharepoint_etag": item.etag,
            "sharepoint_ctag": item.ctag,
        }
    )
    endpoint = f"{api_url.rstrip('/')}/api/v1/offers/{external_id}"
    # Exactly one HTTP PUT. No retry policy is attached to this client.
    response = await client.put(endpoint, json=body)
    response.raise_for_status()
    result = response.json()
    logger.info(
        "Offer API smoke succeeded external_id=%s replay=%s",
        external_id,
        result.get("idempotent_replay"),
    )
    return {"external_id": external_id, "idempotent_replay": result.get("idempotent_replay")}


async def run(command: str, api_url: str) -> dict[str, object]:
    settings = get_settings()
    required_config(settings)
    token_provider = MsalTokenProvider(
        settings.sharepoint_tenant_id,
        settings.sharepoint_client_id,
        settings.sharepoint_client_secret,
    )
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            graph = GraphClient(settings.sharepoint_drive_id, token_provider, client)
            if command == "test":
                return await test_connection(graph, settings.sharepoint_root_folder_id)
            if command == "sync":
                return await sync(graph, settings.sharepoint_root_folder_id)
            if command == "offer-smoke":
                return await offer_smoke(
                    graph,
                    settings.sharepoint_root_folder_id,
                    api_url,
                    client,
                )
            raise ValueError(f"Unknown SharePoint job command: {command}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("test", "sync", "offer-smoke"))
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Backend URL for the explicit offer-smoke command",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        result = asyncio.run(run(args.command, args.api_url))
        logger.info("Job result: %s", result)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        logger.error("SharePoint job failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
