"""PostgreSQL state and the existing versioned offer-file catalogue."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.offers.contracts import SharePointOfferFileUpsertV1
from app.offers.files import SharePointOfferFileService
from app.offers.service import OfferRepositoryService
from app.sharepoint.changes import Enumeration, Item, SharePointChange


@dataclass(frozen=True)
class SavedState:
    items: dict[str, Item]
    mode: str | None
    delta_link: str | None


async def load_state(session: AsyncSession, drive_id: str, folder_id: str) -> SavedState:
    source = (
        (
            await session.execute(
                text("""SELECT mode, delta_link FROM sharepoint_sync_sources
                    WHERE drive_id = :drive_id AND folder_id = :folder_id"""),
                {"drive_id": drive_id, "folder_id": folder_id},
            )
        )
        .mappings()
        .first()
    )
    rows = (
        await session.execute(
            text("""SELECT * FROM sharepoint_sync_items
                    WHERE drive_id = :drive_id AND folder_id = :folder_id"""),
            {"drive_id": drive_id, "folder_id": folder_id},
        )
    ).mappings()
    items = {
        row["item_id"]: Item(
            item_id=row["item_id"],
            parent_id=row["parent_id"],
            name=row["name"],
            path=row["path"],
            web_url=row["web_url"],
            etag=row["etag"],
            ctag=row["ctag"],
            modified_at=row["modified_at"],
            size_bytes=row["size_bytes"],
            mime_type=row["mime_type"],
            is_folder=row["is_folder"],
            is_deleted=row["is_deleted"],
            pending_extraction=row["pending_extraction"],
            last_processed_at=row["last_processed_at"],
        )
        for row in rows
    }
    return SavedState(
        items, source["mode"] if source else None, source["delta_link"] if source else None
    )


def file_version(item: Item) -> str:
    """Version metadata independently of the content-only cTag."""
    payload = [
        item.etag,
        item.ctag,
        item.name,
        item.path,
        item.web_url,
        item.modified_at.isoformat() if item.modified_at else None,
        item.size_bytes,
    ]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
    return f"graph:{digest}"


async def save_success(
    session: AsyncSession,
    drive_id: str,
    folder_id: str,
    enumeration: Enumeration,
    prior: SavedState,
    changes: list[SharePointChange],
) -> None:
    """Commit file versions, tombstones, item state, and cursor as one transaction."""
    now = datetime.now(UTC)
    files = SharePointOfferFileService(session)
    offers = OfferRepositoryService(session)
    changed = {change.item.item_id: change for change in changes}
    final = dict(prior.items)
    final.update(enumeration.items)
    for item_id, old in prior.items.items():
        if item_id not in enumeration.items and not old.is_deleted:
            final[item_id] = replace(old, is_deleted=True)
    await session.execute(
        text("""INSERT INTO sharepoint_sync_sources
                (drive_id, folder_id, mode, delta_link, last_successful_sync_at)
                VALUES (:drive_id, :folder_id, :mode, :delta_link, :now)
                ON CONFLICT (drive_id, folder_id) DO UPDATE
                SET mode = EXCLUDED.mode, delta_link = EXCLUDED.delta_link,
                    last_successful_sync_at = EXCLUDED.last_successful_sync_at"""),
        {
            "drive_id": drive_id,
            "folder_id": folder_id,
            "mode": enumeration.mode,
            "delta_link": enumeration.delta_link,
            "now": now,
        },
    )
    for item_id, item in final.items():
        change = changed.get(item_id)
        if change and change.kind in ("new", "modified"):
            item = replace(item, pending_extraction=True, last_processed_at=now)
        if change and change.kind == "deleted":
            item = replace(item, is_deleted=True)
        if change and change.kind != "deleted":
            if not item.web_url:
                raise ValueError(f"SharePoint file {item_id} has no webUrl")
            await files.upsert(
                item_id,
                SharePointOfferFileUpsertV1(
                    source_version=file_version(item),
                    source_url=item.web_url,
                    name=item.name,
                    captured_at=now,
                    modified_at=item.modified_at,
                    mime_type=item.mime_type,
                    size_bytes=item.size_bytes,
                    metadata={
                        "drive_id": drive_id,
                        "folder_id": folder_id,
                        "path": item.path,
                        "etag": item.etag,
                        "ctag": item.ctag,
                        "pending_extraction": item.pending_extraction,
                    },
                ),
                commit=False,
            )
        elif change and change.kind == "deleted":
            try:
                await files.archive(item_id, archived_at=now, commit=False)
            except LookupError:
                pass
            try:
                await offers.archive(item_id, archived_at=now, commit=False)
            except LookupError:
                pass
        await session.execute(
            text("""INSERT INTO sharepoint_sync_items (
                    drive_id, folder_id, item_id, parent_id, name, path, web_url,
                    etag, ctag, modified_at, size_bytes, mime_type, is_folder,
                    is_deleted, pending_extraction, last_processed_at)
                VALUES (:drive_id, :folder_id, :item_id, :parent_id, :name, :path,
                    :web_url, :etag, :ctag, :modified_at, :size_bytes, :mime_type,
                    :is_folder, :is_deleted, :pending_extraction, :last_processed_at)
                ON CONFLICT (drive_id, folder_id, item_id) DO UPDATE SET
                    parent_id = EXCLUDED.parent_id, name = EXCLUDED.name,
                    path = EXCLUDED.path, web_url = EXCLUDED.web_url,
                    etag = EXCLUDED.etag, ctag = EXCLUDED.ctag,
                    modified_at = EXCLUDED.modified_at, size_bytes = EXCLUDED.size_bytes,
                    mime_type = EXCLUDED.mime_type, is_folder = EXCLUDED.is_folder,
                    is_deleted = EXCLUDED.is_deleted,
                    pending_extraction = EXCLUDED.pending_extraction,
                    last_processed_at = EXCLUDED.last_processed_at"""),
            {
                "drive_id": drive_id,
                "folder_id": folder_id,
                "item_id": item_id,
                "parent_id": item.parent_id,
                "name": item.name,
                "path": item.path,
                "web_url": item.web_url,
                "etag": item.etag,
                "ctag": item.ctag,
                "modified_at": item.modified_at,
                "size_bytes": item.size_bytes,
                "mime_type": item.mime_type,
                "is_folder": item.is_folder,
                "is_deleted": item.is_deleted,
                "pending_extraction": item.pending_extraction,
                "last_processed_at": item.last_processed_at,
            },
        )
    await session.commit()
