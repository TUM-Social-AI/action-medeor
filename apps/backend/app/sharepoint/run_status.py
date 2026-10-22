"""The sync job writes run status; the web application only reads it."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID, uuid4

from sqlalchemy import func, update

from app.db.models import SharePointSyncRunRow
from app.db.session import async_session

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 300


async def begin_run(job_name: str) -> UUID:
    run_id = uuid4()
    async with async_session() as session:
        session.add(SharePointSyncRunRow(
            id=run_id, job_name=job_name,
            execution_name=os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
            status="running", summary={},
        ))
        await session.commit()
    return run_id


async def update_run(run_id: UUID, **values) -> None:
    async with async_session() as session:
        await session.execute(
            update(SharePointSyncRunRow).where(SharePointSyncRunRow.id == run_id)
            .values(updated_at=func.now(), **values)
        )
        await session.commit()


async def heartbeat(run_id: UUID) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            await update_run(run_id)
        except Exception as exc:
            logger.warning("Could not update sync heartbeat (%s)", type(exc).__name__)


async def track_sync(job_name: str, operation: Callable[[], Awaitable[dict]]) -> dict:
    # Commit before discovery starts, so another process can immediately see this run.
    run_id = await begin_run(job_name)
    pulse = asyncio.create_task(heartbeat(run_id))
    try:
        result = await operation()
        summary = {key: result[key] for key in (
            "processed", "failed", "turns", "deferred", "changes", "processing_enabled"
        ) if key in result}
        summary["embedded"] = sum(part.get("embedded", 0) for part in result.get("embeddings", []))
        summary["embedding_failed"] = sum(
            part.get("failed", 0) for part in result.get("embeddings", [])
        )
        failed = bool(result.get("failed") or summary["embedding_failed"])
        status = "skipped" if result.get("skipped") else "failed" if failed else "completed"
        message = (
            "Another discovery is already running." if status == "skipped" else
            "Some documents or embeddings failed. Check the job logs." if failed else None
        )
        if result.get("deferred") and status != "skipped":
            count = result["deferred"]
            budget_message = (
                f"Processing budget reached. Progress saved for {count} unfinished "
                f"document{'s' if count != 1 else ''}. Processing will continue on a later sync."
            )
            message = f"{message} {budget_message}" if message else budget_message
        await update_run(run_id, status=status, finished_at=func.now(), summary=summary, message=message)
        return result
    except BaseException as exc:
        # Never copy exception text, document data, URLs, or credentials to the browser.
        try:
            await update_run(
                run_id, status="failed", finished_at=func.now(),
                message="Sync was interrupted. Check the job logs." if isinstance(
                    exc, asyncio.CancelledError
                ) else "Sync failed. Check the job logs.",
            )
        except Exception as report_error:
            logger.warning("Could not record sync failure (%s)", type(report_error).__name__)
        raise
    finally:
        pulse.cancel()
        with suppress(asyncio.CancelledError):
            await pulse
