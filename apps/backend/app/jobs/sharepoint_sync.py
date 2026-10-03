"""One-shot SharePoint discovery, real offer pipeline and legacy API smoke check.

From apps/backend: uv run python -m app.jobs.sharepoint_sync inspect|sync|process-one --item-id ID
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import text

from app.catalog.embedding_factory import create_embedding_provider
from app.core.config import Settings, get_settings
from app.db.session import async_session, engine
from app.offers.contracts import NormalizedOfferUpsertV1, SharePointOfferFileUpsertV1
from app.offers.embeddings import process_file
from app.offers.files import SharePointOfferFileService
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
from app.sharepoint.extraction import EXTRACTION_VERSION, DownloadedDocument, extract, extract_mock
from app.sharepoint.graph import GraphClient, GraphError, MsalTokenProvider
from app.sharepoint.processing import enqueue, process_pending
from app.sharepoint.scope import (
    assign_domains,
    content_version,
    domain_folders,
    resolve_item,
    supported,
)
from app.sharepoint.store import file_version, load_state, save_success

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


async def inspect_folder(graph: GraphClient, root_id: str, folder_id: str | None = None) -> dict:
    """List one folder after confirming its ancestry stays below the configured root."""
    root = await root_item(graph, root_id)
    selected = (
        root
        if folder_id is None or folder_id == root_id
        else parse_item(await graph.get_item(folder_id))
    )
    if not selected.is_folder:
        raise ValueError("Selected SharePoint item is not a folder")
    names = []
    seen = set()
    ancestor = selected
    while ancestor.item_id != root_id:
        if ancestor.item_id in seen or not ancestor.parent_id:
            raise ValueError("Selected folder is outside the permitted SharePoint root")
        seen.add(ancestor.item_id)
        names.append(ancestor.name)
        ancestor = (
            root
            if ancestor.parent_id == root_id
            else parse_item(await graph.get_item(ancestor.parent_id))
        )
    children = await graph.list_children(selected.item_id)
    return {
        "root_id": root_id,
        "folder_id": selected.item_id,
        "folder_name": selected.name,
        "path": "/".join(reversed(names)),
        "children": [
            {"id": child["id"], "name": child.get("name"), "folder": "folder" in child}
            for child in children
        ],
    }


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
        (item for item in enumeration.items.values() if supported(item)),
        key=lambda item: item.item_id,
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


async def embed_pending(graph, folder_id, settings, *, item_id=None) -> list[dict]:
    provider = create_embedding_provider(settings)
    if provider is None:
        raise ValueError("Embedding provider must be configured for offer processing")
    if item_id:
        items = [item_id]
    else:
        async with async_session() as session:
            items = list(
                (
                    await session.execute(
                        text("""
                SELECT DISTINCT h.source_item_id FROM historical_offers h
                LEFT JOIN offer_embeddings e ON e.offer_id=h.id AND e.model_id=:model
                LEFT JOIN offer_embedding_jobs j ON j.offer_id=h.id AND j.model_id=:model
                WHERE h.source_drive_id=:drive AND h.source_folder_id=:folder
                    AND h.is_current AND h.active AND h.matching_eligible AND e.offer_id IS NULL
                    AND (j.offer_id IS NULL OR (j.status IN ('pending','failed') AND
                         j.attempts < :attempts AND
                         (j.next_attempt_at IS NULL OR j.next_attempt_at <= now()))
                         OR (j.status='running' AND j.lease_until < now()))
                ORDER BY h.source_item_id LIMIT :limit
            """),
                        {
                            "drive": graph.drive_id,
                            "folder": folder_id,
                            "model": provider.model_id,
                            "attempts": settings.sharepoint_max_attempts,
                            "limit": settings.sharepoint_max_documents_per_run,
                        },
                    )
                ).scalars()
            )
    return [
        await process_file(provider, async_session, settings, graph.drive_id, folder_id, item)
        for item in items
    ]


async def sync(
    graph: GraphClient, folder_id: str, *, settings: Settings | None = None, extractor=extract
) -> dict[str, object]:
    settings = settings or get_settings()
    folders = domain_folders(settings)
    async with async_session() as session:
        locked = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": f"sharepoint-discovery:{graph.drive_id}:{folder_id}"},
        )
        if not locked:
            return {"skipped": "Another discovery is running", "processed": 0}
        prior = await load_state(session, graph.drive_id, folder_id)
        root = await root_item(graph, folder_id)
        enumeration = await choose_enumeration(
            graph, root, prior.items, prior.mode, prior.delta_link
        )
        enumeration = replace(
            enumeration, items=assign_domains(enumeration.items, folder_id, folders)
        )
        changes = compare(prior.items, enumeration.items)
        # The complete discovery and pending queue commit before any document download/model call.
        await save_success(session, graph.drive_id, folder_id, enumeration, prior, changes)
    result = {
        "mode": enumeration.mode,
        "changes": len(changes),
        "cursor_updated": True,
        "processed": 0,
        "failed": 0,
        "catalog_api_call_count": 0,
        "offer_repository_write_count": 0,
        "offer_repository_writes": [],
        "no_offer_item_ids": [],
        "processing_enabled": settings.sharepoint_processing_enabled,
        **{
            kind: sum(c.kind == kind for c in changes)
            for kind in ("new", "modified", "metadata", "deleted")
        },
    }
    if settings.sharepoint_processing_enabled:
        result.update(
            await process_pending(graph, folder_id, settings, async_session, extractor=extractor)
        )
        attempted = result.get("attempted_item_ids", [])
        if attempted:
            result["embeddings"] = []
            for item in result.get("successful_offer_item_ids", []):
                result["embeddings"].extend(
                    await embed_pending(graph, folder_id, settings, item_id=item)
                )
        else:
            result["embeddings"] = await embed_pending(graph, folder_id, settings)
    return result


async def process_one(
    graph, folder_id, item_id, settings, *, extractor=extract, retry_failed=False
) -> dict:
    started = time.perf_counter()
    if not item_id:
        raise ValueError("process-one requires --item-id; it never selects a file implicitly")
    item = await resolve_item(graph, folder_id, item_id, domain_folders(settings))
    async with async_session() as session:
        await SharePointOfferFileService(session).upsert(
            item.item_id,
            SharePointOfferFileUpsertV1(
                source_version=file_version(item),
                source_url=item.web_url,
                name=item.name,
                captured_at=datetime.now(UTC),
                modified_at=item.modified_at,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                metadata={
                    "drive_id": graph.drive_id,
                    "folder_id": folder_id,
                    "path": item.path,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "domain": item.domain,
                    "content_version": content_version(item),
                    "extraction_version": EXTRACTION_VERSION,
                },
            ),
            commit=False,
        )
        await enqueue(session, graph.drive_id, folder_id, item)
        if retry_failed:
            await session.execute(
                text("""
                UPDATE sharepoint_offer_jobs SET status='pending',attempts=0,next_attempt_at=NULL
                WHERE drive_id=:drive AND folder_id=:folder AND item_id=:item AND status='failed'
            """),
                {"drive": graph.drive_id, "folder": folder_id, "item": item.item_id},
            )
            await session.execute(
                text("""
                UPDATE offer_embedding_jobs j SET status='pending',attempts=0,next_attempt_at=NULL
                FROM historical_offers h WHERE h.id=j.offer_id AND h.source_drive_id=:drive
                    AND h.source_folder_id=:folder AND h.source_item_id=:item
                    AND h.is_current AND h.active AND j.status='failed'
            """),
                {"drive": graph.drive_id, "folder": folder_id, "item": item.item_id},
            )
        await session.commit()
    result = await process_pending(
        graph,
        folder_id,
        settings,
        async_session,
        item_id=item.item_id,
        extractor=extractor,
    )
    result["item_id"] = item.item_id
    result["domain"] = item.domain
    result["extraction_version"] = EXTRACTION_VERSION
    result["llm_provider"] = settings.llm_provider
    result["llm_deployment"] = settings.azure_openai_deployment
    async with async_session() as session:
        state = (
            (
                await session.execute(
                    text("""
            SELECT status,error,attempts,result_json FROM sharepoint_offer_jobs
            WHERE drive_id=:drive AND folder_id=:folder AND item_id=:item
        """),
                    {"drive": graph.drive_id, "folder": folder_id, "item": item.item_id},
                )
            )
            .mappings()
            .one()
        )
        result["status"] = state["status"]
        result["error"] = state["error"]
        result["warnings"] = (state["result_json"] or {}).get("warnings", [])
        result["idempotent_replay"] = result["processed"] == 0 and state["status"] == "completed"
        result["offers_in_document"] = len((state["result_json"] or {}).get("offers", []))
    result["no_offers_detected"] = (
        result["status"] == "completed" and result["offers_in_document"] == 0
    )
    result["embeddings"] = []
    if result["status"] == "completed" and not result["no_offers_detected"]:
        result["embeddings"] = await embed_pending(graph, folder_id, settings, item_id=item.item_id)
        result["matching"] = await verify_matching(
            graph.drive_id, folder_id, item.item_id, settings
        )
    elif result["no_offers_detected"]:
        result["matching"] = {
            "verified": False,
            "skipped": True,
            "reason": "No offers detected in document",
        }
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return result


async def verify_matching(drive_id, folder_id, item_id, settings) -> dict:
    from uuid import uuid4

    from app.matching.api import get_matching_service
    from app.matching.contracts import InquiryLineV1, MatchRequestV1

    async with async_session() as session:
        row = (
            (
                await session.execute(
                    text("""
            SELECT h.id,h.offered_description,h.domain,s.source_type,s.document_id,s.captured_at,s.uri
            FROM historical_offers h JOIN source_snapshots s ON s.id=h.source_snapshot_id
            WHERE h.source_drive_id=:drive AND h.source_folder_id=:folder AND h.source_item_id=:item
                AND h.is_current AND h.active AND h.matching_eligible ORDER BY h.id LIMIT 1
        """),
                    {"drive": drive_id, "folder": folder_id, "item": item_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return {"verified": False, "reason": "No matching-eligible offers in document"}
        line = InquiryLineV1(
            inquiry_id=str(uuid4()),
            line_id=str(uuid4()),
            domain=row["domain"],
            raw_description=row["offered_description"],
            source={
                "source_type": row["source_type"],
                "document_id": row["document_id"],
                "captured_at": row["captured_at"],
                "uri": row["uri"],
            },
        )
        service = get_matching_service(session)
        response = await service.match(MatchRequestV1(inquiry_line=line, top_k=50))
        candidates = [
            c
            for c in response.candidates
            if c.candidate_type.value == "historical_offer"
            and any(p.document_id == item_id for p in c.provenance)
        ]
        return {
            "verified": bool(candidates),
            "match_run_id": str(response.match_run_id),
            "candidate_count": len(candidates),
            "candidates": [c.model_dump(mode="json") for c in candidates],
        }


async def offer_smoke(
    graph: GraphClient,
    folder_id: str,
    api_url: str,
    client: httpx.AsyncClient,
    *,
    extractor: Extractor = extract_mock,
) -> dict[str, object]:
    root = await root_item(graph, folder_id)
    enumeration = await FolderSnapshotChangeSource(graph).enumerate(root, {}, None)
    files = sorted(
        (item for item in enumeration.items.values() if supported(item)),
        key=lambda item: item.item_id,
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


async def run(
    command: str,
    api_url: str,
    item_id: str | None = None,
    retry_failed=False,
    folder_id: str | None = None,
) -> dict[str, object]:
    if folder_id and command != "inspect":
        raise ValueError("--folder-id is only valid with inspect")
    if item_id and command != "process-one":
        raise ValueError("--item-id is only valid with process-one")
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
                return await sync(graph, settings.sharepoint_root_folder_id, settings=settings)
            if command == "process-one":
                return await process_one(
                    graph,
                    settings.sharepoint_root_folder_id,
                    item_id,
                    settings,
                    retry_failed=retry_failed,
                )
            if command == "inspect":
                return await inspect_folder(graph, settings.sharepoint_root_folder_id, folder_id)
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
    parser.add_argument(
        "command", choices=("test", "sync", "offer-smoke", "process-one", "inspect")
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Backend URL for the explicit offer-smoke command",
    )
    parser.add_argument("--item-id", help="Explicit document for process-one")
    parser.add_argument(
        "--folder-id", help="Folder to list with inspect; defaults to the configured root"
    )
    parser.add_argument(
        "--retry-failed", action="store_true", help="Reset only this file's failed jobs"
    )
    parser.add_argument("--output", type=Path, help="Write a JSON job report")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # Preauthenticated content URLs and opaque delta queries must not enter HTTP request logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        result = asyncio.run(
            run(args.command, args.api_url, args.item_id, args.retry_failed, args.folder_id)
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        logger.info(
            "Job result: %s",
            {k: v for k, v in result.items() if k not in ("matching", "offer_repository_writes")},
        )
        for write in result.get("offer_repository_writes", []):
            logger.info("Offer repository write: %s", json.dumps(write, default=str))
        if args.output:
            logger.info("Full job report: %s", args.output)
        if result.get("failed") or any(e.get("failed") for e in result.get("embeddings", [])):
            raise SystemExit(1)
        if args.command == "process-one" and (
            result.get("status") != "completed"
            or (
                not result.get("no_offers_detected")
                and not result.get("matching", {}).get("verified")
            )
        ):
            raise SystemExit(1)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        logger.error("SharePoint job failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
