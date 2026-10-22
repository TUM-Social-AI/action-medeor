"""Run manually requested development syncs inside the backend process."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.db.models import SharePointSyncRunRow
from app.db.session import async_session
from app.jobs.sharepoint_sync import run_command
from app.sharepoint.run_status import STALE_SECONDS, track_sync

logger = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}


class SyncAlreadyRunning(Exception):
    pass


async def _execute(job_name: str, run_id: UUID) -> None:
    try:
        await track_sync(job_name, lambda: run_command("sync", ""), run_id=run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Local SharePoint sync failed (%s)", type(exc).__name__)


async def start_local_sync(job_name: str) -> str:
    if job_name in _tasks and not _tasks[job_name].done():
        raise SyncAlreadyRunning
    async with async_session() as session:
        locked = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": f"local-sharepoint-sync:{job_name}"},
        )
        if not locked:
            raise SyncAlreadyRunning
        active = await session.scalar(select(SharePointSyncRunRow.id).where(
            SharePointSyncRunRow.job_name == job_name,
            SharePointSyncRunRow.status == "running",
            SharePointSyncRunRow.updated_at >= datetime.now(UTC) - timedelta(seconds=STALE_SECONDS),
        ).limit(1))
        if active is not None:
            raise SyncAlreadyRunning
        run_id = uuid4()
        execution_name = f"local-{run_id}"
        session.add(SharePointSyncRunRow(
            id=run_id, job_name=job_name, execution_name=execution_name,
            status="running", summary={},
        ))
        await session.commit()
    task = asyncio.create_task(_execute(job_name, run_id), name=execution_name)
    _tasks[job_name] = task
    task.add_done_callback(lambda finished: _tasks.pop(job_name, None)
                           if _tasks.get(job_name) is finished else None)
    return execution_name


async def stop_local_syncs() -> None:
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
