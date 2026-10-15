"""Live extraction stage of an upload, so the loading screen reflects real work (issue #24).

The browser sends a random token with the file and polls GET /api/imports/progress/{token}.
Each write uses its own short session and commit, so it is visible to the poll immediately and
independent of the upload's own transaction. Progress is best-effort: a failed write is logged and
never fails the upload.
"""

import datetime as dt
import logging
import re

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert

from app.db.models import ImportProgressRow
from app.db.session import async_session

logger = logging.getLogger(__name__)

# Stages in order; "reviewing" only happens in balanced mode.
STAGES = ("reading", "reviewing", "saving")
_TOKEN = re.compile(r"[A-Za-z0-9-]{8,64}")


def valid_token(token: str | None) -> str | None:
    return token if token and _TOKEN.fullmatch(token) else None


async def report(
    token: str | None, stage: str, *, mode: str = "basic", items: int | None = None
) -> None:
    if not token:
        return
    try:
        async with async_session() as session:
            statement = insert(ImportProgressRow).values(
                token=token, stage=stage, mode=mode, items=items
            )
            statement = statement.on_conflict_do_update(
                index_elements=[ImportProgressRow.token],
                set_={
                    "stage": stage,
                    "mode": mode,
                    # A later stage that doesn't know the count keeps the one already reported.
                    # excluded["items"], not .items - that attribute is ColumnCollection.items().
                    "items": func.coalesce(statement.excluded["items"], ImportProgressRow.items),
                    "updated_at": func.now(),
                },
            )
            await session.execute(statement)
            await session.commit()
    except Exception:  # noqa: BLE001 - progress must never break an upload
        logger.warning("Could not record import progress stage=%s", stage, exc_info=True)


async def finish(token: str | None) -> None:
    """Remove this upload's row, plus any left behind by an upload that never finished."""
    if not token:
        return
    try:
        async with async_session() as session:
            # Compared in the database, against its own clock (it may not share our timezone).
            stale = func.now() - dt.timedelta(days=1)
            await session.execute(
                delete(ImportProgressRow).where(
                    (ImportProgressRow.token == token) | (ImportProgressRow.updated_at < stale)
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Could not clear import progress", exc_info=True)
