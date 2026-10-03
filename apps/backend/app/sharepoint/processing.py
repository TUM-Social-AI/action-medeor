"""Durable per-document work, fenced leases and atomic multi-offer publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from sqlalchemy import text

from app.core.config import Settings
from app.offers.service import OfferRepositoryService
from app.sharepoint.changes import Item, SharePointChange
from app.sharepoint.extraction import (
    EXTRACTION_VERSION,
    DownloadedDocument,
    OfferBatch,
    UnsupportedDocument,
    extract,
)
from app.sharepoint.scope import content_version, domain_folders, resolve_item, supported

logger = logging.getLogger(__name__)


def item_json(item: Item) -> str:
    return json.dumps(asdict(item), default=str)


def stored_item(raw: dict) -> Item:
    raw = dict(raw)
    for field in ("created_at", "modified_at", "last_processed_at"):
        if isinstance(raw.get(field), str):
            raw[field] = datetime.fromisoformat(raw[field])
    return Item(**raw)


def source_params(drive_id: str, folder_id: str, item_id: str) -> dict:
    return {"drive": drive_id, "folder": folder_id, "item": item_id}


def offer_external_id(job: dict, offer) -> str:
    identity = [
        job["drive_id"],
        job["item_id"],
        offer.metadata["source_id"],
        offer.metadata["alternative_index"],
    ]
    return "sharepoint-offer-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()


async def enqueue(session, drive_id: str, folder_id: str, item: Item) -> None:
    if not supported(item) or item.domain is None:
        return
    await session.execute(
        text("""
        INSERT INTO sharepoint_offer_jobs
            (drive_id,folder_id,item_id,content_version,domain,item_json,extraction_version)
        VALUES (:drive,:folder,:item,:version,:domain,CAST(:data AS jsonb),:extraction)
        ON CONFLICT (drive_id,folder_id,item_id) DO UPDATE SET
            item_json=EXCLUDED.item_json, domain=EXCLUDED.domain,
            content_version=EXCLUDED.content_version, extraction_version=EXCLUDED.extraction_version,
            status=CASE WHEN sharepoint_offer_jobs.content_version != EXCLUDED.content_version
                OR sharepoint_offer_jobs.extraction_version IS DISTINCT FROM EXCLUDED.extraction_version
                OR sharepoint_offer_jobs.status='archived' THEN 'pending'
                ELSE sharepoint_offer_jobs.status END,
            attempts=CASE WHEN sharepoint_offer_jobs.content_version != EXCLUDED.content_version
                OR sharepoint_offer_jobs.extraction_version IS DISTINCT FROM EXCLUDED.extraction_version
                OR sharepoint_offer_jobs.status='archived' THEN 0 ELSE sharepoint_offer_jobs.attempts END,
            next_attempt_at=CASE WHEN sharepoint_offer_jobs.content_version != EXCLUDED.content_version
                OR sharepoint_offer_jobs.extraction_version IS DISTINCT FROM EXCLUDED.extraction_version
                OR sharepoint_offer_jobs.status='archived' THEN NULL
                ELSE sharepoint_offer_jobs.next_attempt_at END,
            lease_token=CASE WHEN sharepoint_offer_jobs.content_version != EXCLUDED.content_version
                OR sharepoint_offer_jobs.extraction_version IS DISTINCT FROM EXCLUDED.extraction_version
                OR sharepoint_offer_jobs.status='archived' THEN NULL
                ELSE sharepoint_offer_jobs.lease_token END,
            updated_at=now()
    """),
        {
            **source_params(drive_id, folder_id, item.item_id),
            "version": content_version(item),
            "domain": item.domain,
            "data": item_json(item),
            "extraction": EXTRACTION_VERSION,
        },
    )


async def archive_file(session, drive_id: str, folder_id: str, item_id: str) -> None:
    params = source_params(drive_id, folder_id, item_id)
    await session.execute(
        text("""
        UPDATE sharepoint_offer_jobs SET status='archived', lease_token=NULL, updated_at=now()
        WHERE drive_id=:drive AND folder_id=:folder AND item_id=:item
    """),
        params,
    )
    await session.execute(
        text("""
        UPDATE historical_offers SET active=FALSE, archived_at=now(), updated_at=now()
        WHERE is_current AND active AND
            ((source_drive_id=:drive AND source_folder_id=:folder AND source_item_id=:item)
             OR (source_item_id IS NULL AND external_id=:item))
    """),
        params,
    )


async def claim(session, drive_id: str, folder_id: str, settings: Settings, item_id=None):
    token = uuid4()
    params = {
        "drive": drive_id,
        "folder": folder_id,
        "item": item_id,
        "max_attempts": settings.sharepoint_max_attempts,
        "token": token,
        "lease_seconds": settings.sharepoint_document_timeout_seconds + 120,
    }
    await session.execute(
        text("""
        UPDATE sharepoint_offer_jobs SET status='failed',error='Processing lease expired',
            lease_token=NULL WHERE drive_id=:drive AND folder_id=:folder AND status='running'
            AND lease_until < now() AND attempts >= :max_attempts
    """),
        params,
    )
    row = (
        (
            await session.execute(
                text("""
        WITH picked AS (
            SELECT drive_id,folder_id,item_id FROM sharepoint_offer_jobs
            WHERE drive_id=:drive AND folder_id=:folder
              AND (CAST(:item AS text) IS NULL OR item_id=:item)
              AND attempts < :max_attempts
              AND ((status IN ('pending','failed') AND
                    (next_attempt_at IS NULL OR next_attempt_at <= now()))
                   OR (status='running' AND lease_until < now()))
            ORDER BY updated_at,item_id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE sharepoint_offer_jobs j SET status='running',attempts=j.attempts+1,
            lease_token=:token,lease_until=now()+make_interval(secs=>:lease_seconds),error=NULL
        FROM picked p WHERE j.drive_id=p.drive_id AND j.folder_id=p.folder_id AND j.item_id=p.item_id
        RETURNING j.*
    """),
                params,
            )
        )
        .mappings()
        .first()
    )
    await session.commit()
    return dict(row) if row else None


async def publish(session, job: dict, batch: OfferBatch) -> list[str]:
    params = {
        **source_params(job["drive_id"], job["folder_id"], job["item_id"]),
        "token": job["lease_token"],
        "version": job["content_version"],
    }
    locked = await session.scalar(
        text("""
        SELECT item_id FROM sharepoint_offer_jobs WHERE drive_id=:drive AND folder_id=:folder
            AND item_id=:item AND status='running' AND lease_token=:token
            AND content_version=:version AND lease_until > now() FOR UPDATE
    """),
        params,
    )
    if locked is None:
        raise RuntimeError(
            "Document processing lease or content version changed; results discarded"
        )
    service = OfferRepositoryService(session)
    offer_ids = []
    external_ids = []
    for offer in batch.offers:
        if offer.source_version != f"{job['content_version']}:{job['extraction_version']}":
            raise ValueError("Extracted offer version does not match its processing job")
        external_id = offer_external_id(job, offer)
        if external_id in external_ids:
            raise ValueError("Extraction returned duplicate source/alternative identity")
        external_ids.append(external_id)
        metadata = {
            **offer.metadata,
            "sharepoint_item_id": job["item_id"],
            "sharepoint_drive_id": job["drive_id"],
            "path": job["item_json"]["path"],
        }
        record = await service.upsert(
            external_id,
            offer.model_copy(update={"metadata": metadata}),
            commit=False,
            source_document_id=job["item_id"],
        )
        offer_ids.append(str(record.offer_id))
        await session.execute(
            text("""
            UPDATE historical_offers SET source_drive_id=:drive,source_folder_id=:folder,
                source_item_id=:item, domain=:domain, matching_eligible=:eligible WHERE id=:id
        """),
            {
                **params,
                "domain": job["domain"],
                "id": record.offer_id,
                "eligible": bool(offer.metadata["matching_eligible"]),
            },
        )
    await session.execute(
        text("""
        UPDATE historical_offers SET active=FALSE,archived_at=now(),updated_at=now()
        WHERE is_current AND active AND source_drive_id=:drive AND source_folder_id=:folder
            AND source_item_id=:item AND NOT (external_id=ANY(CAST(:ids AS text[])))
    """),
        {**params, "ids": external_ids},
    )
    # Retire legacy single-record output for this source file, if present.
    await session.execute(
        text("""
        UPDATE historical_offers SET active=FALSE,archived_at=now(),updated_at=now()
        WHERE external_id=:item AND source_item_id IS NULL AND is_current AND active
    """),
        params,
    )
    await session.execute(
        text("""
        UPDATE sharepoint_offer_jobs SET status='completed',completed_at=now(),updated_at=now(),
            result_json=CAST(:result AS jsonb),error=NULL,lease_token=NULL,next_attempt_at=NULL
        WHERE drive_id=:drive AND folder_id=:folder AND item_id=:item
    """),
        {**params, "result": batch.extraction.model_dump_json()},
    )
    await session.execute(
        text("""
        UPDATE sharepoint_sync_items SET pending_extraction=FALSE,last_processed_at=now()
        WHERE drive_id=:drive AND folder_id=:folder AND item_id=:item
    """),
        params,
    )
    await session.commit()
    return offer_ids


async def fail(session, job: dict, exc: Exception) -> None:
    await session.execute(
        text("""
        UPDATE sharepoint_offer_jobs SET status=:status,error=:error,lease_token=NULL,
            next_attempt_at=now()+make_interval(secs=>:delay),updated_at=now()
        WHERE drive_id=:drive AND folder_id=:folder AND item_id=:item AND lease_token=:token
    """),
        {
            **source_params(job["drive_id"], job["folder_id"], job["item_id"]),
            "token": job["lease_token"],
            "status": "unsupported" if isinstance(exc, UnsupportedDocument) else "failed",
            "error": f"{type(exc).__name__}: {exc}"[:4000],
            "delay": min(3600, 60 * 2 ** (job["attempts"] - 1)),
        },
    )
    await session.commit()


async def process_pending(
    graph,
    folder_id: str,
    settings: Settings,
    sessions,
    *,
    item_id: str | None = None,
    extractor=extract,
) -> dict:
    result = {
        "processed": 0,
        "failed": 0,
        "offers": 0,
        "offer_ids": [],
        "offer_repository_writes": [],
        "offer_repository_write_count": 0,
        "catalog_api_call_count": 0,
        "no_offer_item_ids": [],
        "successful_offer_item_ids": [],
        "failures": [],
        "attempted_item_ids": [],
    }
    limit = 1 if item_id else settings.sharepoint_max_documents_per_run
    for _ in range(limit):
        async with sessions() as session:
            job = await claim(session, graph.drive_id, folder_id, settings, item_id)
        if job is None:
            break
        result["attempted_item_ids"].append(job["item_id"])
        item = stored_item(job["item_json"])
        try:
            async with asyncio.timeout(settings.sharepoint_document_timeout_seconds):
                current = await resolve_item(
                    graph, folder_id, item.item_id, domain_folders(settings)
                )
                if content_version(current) != job["content_version"] or not supported(current):
                    raise RuntimeError("Document changed before download; rediscovery required")
                if (
                    current.size_bytes
                    and current.size_bytes > settings.sharepoint_max_document_bytes
                ):
                    raise UnsupportedDocument("Document exceeds configured byte limit")
                content = await graph.download(
                    item.item_id,
                    max_bytes=settings.sharepoint_max_document_bytes,
                )
                batch = await extractor(
                    SharePointChange("modified", current),
                    DownloadedDocument(
                        item.item_id,
                        current.name,
                        current.mime_type,
                        content,
                        current.modified_at,
                        current.created_at,
                    ),
                    max_chunks=settings.sharepoint_max_extraction_chunks,
                )
                after = await resolve_item(graph, folder_id, item.item_id, domain_folders(settings))
                if (
                    content_version(after) != job["content_version"]
                    or after.parent_id != current.parent_id
                ):
                    raise RuntimeError("Document changed during extraction; results discarded")
                async with sessions() as session:
                    ids = await publish(session, job, batch)
                result["processed"] += 1
                result["offers"] += len(ids)
                result["offer_ids"].extend(ids)
                if not ids:
                    result["no_offer_item_ids"].append(item.item_id)
                else:
                    result["successful_offer_item_ids"].append(item.item_id)
                result["offer_repository_writes"].extend(
                    {
                        "item_id": item.item_id,
                        "external_id": offer_external_id(job, offer),
                        "offer_id": offer_id,
                        "source_document_id": item.item_id,
                        "payload": offer.model_copy(
                            update={
                                "metadata": {
                                    **offer.metadata,
                                    "sharepoint_item_id": item.item_id,
                                    "sharepoint_drive_id": graph.drive_id,
                                    "path": job["item_json"]["path"],
                                }
                            }
                        ).model_dump(mode="json"),
                    }
                    for offer, offer_id in zip(batch.offers, ids, strict=True)
                )
                result["offer_repository_write_count"] += len(ids)
        except Exception as exc:
            logger.exception("Offer extraction failed item=%s", item.item_id)
            async with sessions() as session:
                await fail(session, job, exc)
            result["failed"] += 1
            result["failures"].append({"item_id": item.item_id, "error": str(exc)})
    return result
