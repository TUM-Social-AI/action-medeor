"""Database transaction and version replay for folder-scoped SharePoint state."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.sharepoint.changes import Enumeration, Item, compare
from app.sharepoint.store import SavedState, load_state, save_success

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sharepoint_state_replay_rename_and_archive() -> None:
    database_url = os.getenv("MATCHING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MATCHING_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    drive_id = f"test-drive-{suffix}"
    folder_id = f"test-root-{suffix}"
    item_id = f"test-item-{suffix}"
    now = datetime(2026, 9, 29, tzinfo=UTC)
    root = Item(folder_id, None, "root", "", None, None, None, now, None, None, True)
    file = Item(
        item_id,
        folder_id,
        "offer.pdf",
        "offer.pdf",
        f"https://example.sharepoint.com/sites/test/{item_id}.pdf",
        "etag-1",
        "ctag-1",
        now,
        12,
        "application/pdf",
        False,
        domain="equipment",
    )
    try:
        first = Enumeration({folder_id: root, item_id: file}, "snapshot", None)
        async with sessions() as session:
            await save_success(
                session,
                drive_id,
                folder_id,
                first,
                SavedState({}, None, None),
                compare({}, first.items),
            )
        async with sessions() as session:
            saved = await load_state(session, drive_id, folder_id)
            assert saved.items[item_id].pending_extraction is True
            assert saved.mode == "snapshot"
            await save_success(
                session,
                drive_id,
                folder_id,
                first,
                saved,
                compare(saved.items, first.items),
            )
        async with sessions() as session:
            count = await session.scalar(
                text("SELECT COUNT(*) FROM sharepoint_offer_files WHERE external_id = :id"),
                {"id": item_id},
            )
            assert count == 1
            saved = await load_state(session, drive_id, folder_id)
        renamed = replace(file, name="renamed.pdf", path="renamed.pdf", etag="etag-2")
        second = Enumeration({folder_id: root, item_id: renamed}, "snapshot", None)
        assert [change.kind for change in compare(saved.items, second.items)] == ["metadata"]
        async with sessions() as session:
            await save_success(
                session,
                drive_id,
                folder_id,
                second,
                saved,
                compare(saved.items, second.items),
            )
        async with sessions() as session:
            count = await session.scalar(
                text("SELECT COUNT(*) FROM sharepoint_offer_files WHERE external_id = :id"),
                {"id": item_id},
            )
            assert count == 2
            saved = await load_state(session, drive_id, folder_id)
            assert saved.items[item_id].path == "renamed.pdf"
        empty = Enumeration({folder_id: root}, "snapshot", None)
        async with sessions() as session:
            await save_success(
                session,
                drive_id,
                folder_id,
                empty,
                saved,
                compare(saved.items, empty.items),
            )
        async with sessions() as session:
            saved = await load_state(session, drive_id, folder_id)
            assert saved.items[item_id].is_deleted is True
            active = await session.scalar(
                text("""SELECT active FROM sharepoint_offer_files
                        WHERE external_id = :id AND is_current = TRUE"""),
                {"id": item_id},
            )
            assert active is False
    finally:
        async with sessions() as session:
            await session.execute(
                text("DELETE FROM sharepoint_offer_jobs WHERE drive_id=:drive AND folder_id=:folder"),
                {"drive": drive_id, "folder": folder_id},
            )
            await session.execute(
                text(
                    "DELETE FROM sharepoint_sync_sources WHERE drive_id = :drive AND folder_id = :folder"
                ),
                {"drive": drive_id, "folder": folder_id},
            )
            await session.execute(
                text("DELETE FROM sharepoint_offer_files WHERE external_id = :id"),
                {"id": item_id},
            )
            await session.execute(
                text("""DELETE FROM source_snapshots
                        WHERE source_type = 'sharepoint' AND document_id = :id"""),
                {"id": item_id},
            )
            await session.commit()
        await engine.dispose()
