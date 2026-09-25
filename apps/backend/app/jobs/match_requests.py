"""Durable Postgres-backed worker for complete partner requests."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.api.request_workflow import to_inquiry_line
from app.db.repository import get_request_by_id
from app.db.session import async_session
from app.matching.api import get_matching_service
from app.matching.contracts import MatchRequestV1

logger = logging.getLogger(__name__)
LEASE = timedelta(seconds=45)


async def claim_next() -> str | None:
    async with async_session() as session:
        request_id = await session.scalar(
            text("""SELECT request_id FROM request_matching_jobs
                    WHERE status = 'queued'
                       OR (status = 'running' AND lease_until < CURRENT_TIMESTAMP)
                    ORDER BY updated_at, request_id
                    LIMIT 1 FOR UPDATE SKIP LOCKED""")
        )
        if request_id is None:
            await session.rollback()
            return None
        await session.execute(
            text("""UPDATE request_matching_jobs SET status = 'running',
                    attempts = attempts + 1, lease_until = :lease_until,
                    updated_at = CURRENT_TIMESTAMP WHERE request_id = :request_id"""),
            {"request_id": request_id, "lease_until": datetime.now(UTC) + LEASE},
        )
        await session.execute(
            text("UPDATE import_requests SET workflow_status = 'matching' WHERE request_id = :id"),
            {"id": request_id},
        )
        await session.commit()
        return request_id


async def process_request(request_id: str) -> None:
    async with async_session() as session:
        request = await get_request_by_id(session, request_id)
        if request is None:
            return
        item_ids = [item.id for item in request.items if item.match_status != "completed"]

    for item_id in item_ids:
        try:
            async with async_session() as session:
                request = await get_request_by_id(session, request_id)
                assert request is not None
                item = next(item for item in request.items if item.id == item_id)
                item.match_status = "running"
                await session.commit()
                # A previous process can finish a run before it links it to the request item.
                # Review fields are locked once matching starts, so that run is reusable.
                prior_run = await session.scalar(
                    text("""SELECT id FROM match_runs
                            WHERE inquiry_id = :request_id AND inquiry_line_id = :line_id
                              AND status = 'completed'
                              AND source_versions->>'catalog_snapshot_id' = :snapshot_id
                            ORDER BY completed_at DESC, id DESC LIMIT 1"""),
                    {
                        "request_id": request_id,
                        "line_id": str(item_id),
                        "snapshot_id": str(request.catalog_snapshot_id),
                    },
                )
                if prior_run is None:
                    line = to_inquiry_line(request, item)
                    service = get_matching_service(session)
                    result = await service.match(
                        MatchRequestV1(
                            inquiry_line=line,
                            catalog_snapshot_id=str(request.catalog_snapshot_id),
                        )
                    )
                    prior_run = result.match_run_id
                item.current_match_run_id = prior_run
                item.match_status = "completed"
                item.match_error = None
                await session.commit()
        except Exception as exc:
            logger.exception("Matching item %s failed", item_id)
            async with async_session() as session:
                request = await get_request_by_id(session, request_id)
                if request:
                    item = next(item for item in request.items if item.id == item_id)
                    item.match_status = "failed"
                    item.match_error = str(exc)[:2000]
                    await session.commit()
        async with async_session() as session:
            await session.execute(
                text("""UPDATE request_matching_jobs SET lease_until = :lease_until,
                        updated_at = CURRENT_TIMESTAMP WHERE request_id = :id"""),
                {"id": request_id, "lease_until": datetime.now(UTC) + LEASE},
            )
            await session.commit()

    async with async_session() as session:
        request = await get_request_by_id(session, request_id)
        if request is None:
            return
        failed = any(item.match_status == "failed" for item in request.items)
        status = "matching_failed" if failed else "match_review"
        request.workflow_status = status
        await session.execute(
            text("""UPDATE request_matching_jobs SET status = :status, lease_until = NULL,
                    updated_at = CURRENT_TIMESTAMP WHERE request_id = :id"""),
            {"status": "failed" if failed else "completed", "id": request_id},
        )
        await session.commit()


async def heartbeat(request_id: str) -> None:
    """Keep a long-running item claimed while allowing crashed workers to recover quickly."""
    while True:
        await asyncio.sleep(15)
        async with async_session() as session:
            await session.execute(
                text("""UPDATE request_matching_jobs SET lease_until = :lease_until,
                        updated_at = CURRENT_TIMESTAMP
                        WHERE request_id = :id AND status = 'running'"""),
                {"id": request_id, "lease_until": datetime.now(UTC) + LEASE},
            )
            await session.commit()


async def run_forever() -> None:
    while True:
        try:
            request_id = await claim_next()
            if request_id:
                keep_alive = asyncio.create_task(heartbeat(request_id))
                try:
                    await process_request(request_id)
                finally:
                    keep_alive.cancel()
                    with suppress(asyncio.CancelledError):
                        await keep_alive
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Matching worker iteration failed")
        await asyncio.sleep(2)
