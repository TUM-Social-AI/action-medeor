"""Supplier-offer embeddings, isolated from catalog activation and catalog jobs."""

from __future__ import annotations

import asyncio
import hashlib
from uuid import uuid4

from sqlalchemy import text

from app.catalog.embeddings import _vector_literal
from app.matching.representation import normalize_text


def represent_offer(description: str, domain: str) -> tuple[str, str]:
    value = f"{normalize_text(description)}; domain={domain}"
    return value, hashlib.sha256(value.encode()).hexdigest()


async def register_model(session, spec) -> None:
    await session.execute(
        text("""
        INSERT INTO embedding_models(id,provider,name,version,dimensions,distance_metric,active)
        VALUES (:id,:provider,:name,:version,:dimensions,'cosine',FALSE)
        ON CONFLICT (id) DO NOTHING
    """),
        {
            "id": spec.model_id,
            "provider": spec.provider,
            "name": spec.name,
            "version": spec.version,
            "dimensions": spec.dimensions,
        },
    )
    existing = (
        (
            await session.execute(
                text("""
        SELECT provider,name,version,dimensions FROM embedding_models WHERE id=:id
    """),
                {"id": spec.model_id},
            )
        )
        .mappings()
        .one()
    )
    if tuple(existing.values()) != (spec.provider, spec.name, spec.version, spec.dimensions):
        raise ValueError(
            "Configured offer embedding model conflicts with its registered specification"
        )


async def enqueue_file(session, drive_id: str, folder_id: str, item_id: str, spec) -> int:
    await register_model(session, spec)
    rows = (
        (
            await session.execute(
                text("""
        SELECT id,offered_description,domain FROM historical_offers
        WHERE source_drive_id=:drive AND source_folder_id=:folder AND source_item_id=:item
            AND is_current AND active AND matching_eligible
    """),
                {"drive": drive_id, "folder": folder_id, "item": item_id},
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        value, digest = represent_offer(row["offered_description"], row["domain"])
        await session.execute(
            text("""
            INSERT INTO offer_embedding_jobs(offer_id,model_id,content_hash,content_text)
            VALUES (:id,:model,:hash,:value) ON CONFLICT (offer_id,model_id) DO NOTHING
        """),
            {"id": row["id"], "model": spec.model_id, "hash": digest, "value": value},
        )
    await session.commit()
    return len(rows)


async def process_file(
    provider, sessions, settings, drive_id: str, folder_id: str, item_id: str
) -> dict:
    spec = await provider.spec()
    async with sessions() as session:
        await enqueue_file(session, drive_id, folder_id, item_id, spec)
    result = {"embedded": 0, "reused": 0, "failed": 0, "model_id": spec.model_id}
    while True:
        token = uuid4()
        params = {
            "drive": drive_id,
            "folder": folder_id,
            "item": item_id,
            "model": spec.model_id,
            "max_attempts": settings.sharepoint_max_attempts,
            "token": token,
            "limit": settings.embedding_batch_size,
            "lease": settings.sharepoint_document_timeout_seconds + 120,
        }
        async with sessions() as session:
            await session.execute(
                text("""
                UPDATE offer_embedding_jobs SET status='failed',lease_token=NULL,
                    error='Embedding lease expired' WHERE model_id=:model AND status='running'
                    AND lease_until < now() AND attempts >= :max_attempts
            """),
                params,
            )
            jobs = (
                (
                    await session.execute(
                        text("""
                WITH picked AS (
                    SELECT j.offer_id,j.model_id FROM offer_embedding_jobs j
                    JOIN historical_offers h ON h.id=j.offer_id
                    WHERE h.source_drive_id=:drive AND h.source_folder_id=:folder
                        AND h.source_item_id=:item AND h.is_current AND h.active AND h.matching_eligible
                        AND j.model_id=:model AND j.attempts < :max_attempts
                        AND ((j.status IN ('pending','failed') AND
                             (j.next_attempt_at IS NULL OR j.next_attempt_at <= now()))
                             OR (j.status='running' AND j.lease_until < now()))
                    ORDER BY j.offer_id FOR UPDATE OF j SKIP LOCKED LIMIT :limit
                ) UPDATE offer_embedding_jobs j SET status='running',lease_token=:token,
                    lease_until=now()+make_interval(secs=>:lease),attempts=j.attempts+1
                FROM picked p WHERE j.offer_id=p.offer_id AND j.model_id=p.model_id RETURNING j.*
            """),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            await session.commit()
        if not jobs:
            break
        try:
            cached = {}
            async with sessions() as session:
                for job in jobs:
                    cached[job["content_hash"]] = await session.scalar(
                        text("""
                        SELECT embedding::text FROM offer_embeddings
                        WHERE model_id=:model AND content_hash=:hash LIMIT 1
                    """),
                        {"model": spec.model_id, "hash": job["content_hash"]},
                    )
            missing = {
                job["content_hash"]: job["content_text"]
                for job in jobs
                if cached[job["content_hash"]] is None
            }
            if missing:
                async with asyncio.timeout(settings.sharepoint_document_timeout_seconds):
                    vectors = await provider.embed_documents(list(missing.values()))
                if len(vectors) != len(missing):
                    raise ValueError("Offer embedding provider returned an unexpected batch size")
                for digest, vector in zip(missing, vectors, strict=True):
                    if len(vector) != spec.dimensions:
                        raise ValueError("Offer embedding dimension mismatch")
                    cached[digest] = _vector_literal(vector)
            async with sessions() as session:
                for job in jobs:
                    owned = await session.scalar(
                        text("""
                        SELECT offer_id FROM offer_embedding_jobs WHERE offer_id=:id AND model_id=:model
                            AND status='running' AND lease_token=:token AND lease_until > now() FOR UPDATE
                    """),
                        {**params, "id": job["offer_id"]},
                    )
                    if owned is None:
                        continue
                    await session.execute(
                        text("""
                        INSERT INTO offer_embeddings(offer_id,model_id,content_hash,embedding)
                        VALUES (:id,:model,:hash,CAST(:vector AS vector))
                        ON CONFLICT (offer_id,model_id) DO NOTHING
                    """),
                        {
                            **params,
                            "id": job["offer_id"],
                            "hash": job["content_hash"],
                            "vector": cached[job["content_hash"]],
                        },
                    )
                    await session.execute(
                        text("""
                        UPDATE offer_embedding_jobs SET status='completed',error=NULL,lease_token=NULL,
                            next_attempt_at=NULL WHERE offer_id=:id AND model_id=:model
                    """),
                        {**params, "id": job["offer_id"]},
                    )
                    result["embedded" if job["content_hash"] in missing else "reused"] += 1
                await session.commit()
        except Exception as exc:
            async with sessions() as session:
                for job in jobs:
                    await session.execute(
                        text("""
                        UPDATE offer_embedding_jobs SET status='failed',error=:error,lease_token=NULL,
                            next_attempt_at=now()+make_interval(secs=>:delay)
                        WHERE offer_id=:id AND model_id=:model AND lease_token=:token
                    """),
                        {
                            **params,
                            "id": job["offer_id"],
                            "error": str(exc)[:4000],
                            "delay": min(3600, 60 * 2 ** (job["attempts"] - 1)),
                        },
                    )
                await session.commit()
            result["failed"] += len(jobs)
            result["error"] = str(exc)
            break
    return result
