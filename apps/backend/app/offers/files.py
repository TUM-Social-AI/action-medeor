"""Versioned SharePoint file catalogue; document extraction remains external."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.offers.contracts import (
    SharePointOfferFileRecordV1,
    SharePointOfferFileUpsertV1,
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class SharePointOfferFileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock(self, external_id: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"allocura-sharepoint-file-v1:{external_id}"},
        )

    async def _current(self, external_id: str) -> dict[str, object] | None:
        result = await self._session.execute(
            text(
                """
                SELECT f.*, s.uri AS source_url,
                       EXISTS (
                           SELECT 1 FROM historical_offers h
                           WHERE h.external_id = f.external_id
                             AND h.is_current = TRUE AND h.active = TRUE
                       ) AS structured_output_available
                FROM sharepoint_offer_files f
                JOIN source_snapshots s ON s.id = f.source_snapshot_id
                WHERE f.external_id = :external_id AND f.is_current = TRUE
                """
            ),
            {"external_id": external_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _record(
        row: dict[str, object], *, replay: bool = False
    ) -> SharePointOfferFileRecordV1:
        return SharePointOfferFileRecordV1(
            file_id=row["id"],
            external_id=str(row["external_id"]),
            source_version=str(row["external_version"]),
            source_url=str(row["source_url"]),
            name=str(row["name"]),
            active=bool(row["active"]),
            modified_at=row["modified_at"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            structured_output_available=bool(row["structured_output_available"]),
            metadata=row["metadata_json"] or {},
            archived_at=row["archived_at"],
            updated_at=row["updated_at"],
            idempotent_replay=replay,
        )

    async def _source_snapshot(
        self,
        *,
        external_id: str,
        payload: SharePointOfferFileUpsertV1,
    ) -> UUID:
        existing = await self._session.scalar(
            text(
                """
                SELECT id FROM source_snapshots
                WHERE source_type = 'sharepoint' AND document_id = :external_id
                  AND checksum = :source_version
                """
            ),
            {"external_id": external_id, "source_version": payload.source_version},
        )
        if existing:
            return existing
        snapshot_id = uuid4()
        await self._session.execute(
            text(
                """
                INSERT INTO source_snapshots (
                    id, source_type, document_id, external_id, uri, checksum,
                    captured_at, locator, metadata_json
                ) VALUES (
                    :id, 'sharepoint', :external_id, :external_id, :source_url,
                    :source_version, :captured_at, '{}'::jsonb, CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "id": snapshot_id,
                "external_id": external_id,
                "source_url": str(payload.source_url),
                "source_version": payload.source_version,
                "captured_at": payload.captured_at,
                "metadata": _json({"role": "offer_file", **payload.metadata}),
            },
        )
        return snapshot_id

    async def upsert(
        self,
        external_id: str,
        payload: SharePointOfferFileUpsertV1,
    ) -> SharePointOfferFileRecordV1:
        await self._lock(external_id)
        current = await self._current(external_id)
        if (
            current
            and current["external_version"] == payload.source_version
            and current["active"]
        ):
            await self._session.rollback()
            return self._record(current, replay=True)
        try:
            source_id = await self._source_snapshot(external_id=external_id, payload=payload)
            if current:
                await self._session.execute(
                    text("UPDATE sharepoint_offer_files SET is_current = FALSE WHERE id = :id"),
                    {"id": current["id"]},
                )
            record_id = uuid4()
            updated_at = datetime.now(UTC)
            await self._session.execute(
                text(
                    """
                    INSERT INTO sharepoint_offer_files (
                        id, source_snapshot_id, external_id, external_version, name,
                        mime_type, size_bytes, modified_at, is_current, active,
                        metadata_json, created_at, updated_at
                    ) VALUES (
                        :id, :source_id, :external_id, :external_version, :name,
                        :mime_type, :size_bytes, :modified_at, TRUE, TRUE,
                        CAST(:metadata AS jsonb), :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": record_id,
                    "source_id": source_id,
                    "external_id": external_id,
                    "external_version": payload.source_version,
                    "name": payload.name,
                    "mime_type": payload.mime_type,
                    "size_bytes": payload.size_bytes,
                    "modified_at": payload.modified_at,
                    "metadata": _json(payload.metadata),
                    "created_at": updated_at,
                    "updated_at": updated_at,
                },
            )
            await self._session.commit()
            row = await self._current(external_id)
            assert row is not None
            return self._record(row)
        except Exception:
            await self._session.rollback()
            raise

    async def archive(
        self,
        external_id: str,
        *,
        archived_at: datetime | None = None,
    ) -> SharePointOfferFileRecordV1:
        await self._lock(external_id)
        current = await self._current(external_id)
        if current is None:
            raise LookupError("SharePoint offer file not found")
        if not current["active"]:
            await self._session.rollback()
            return self._record(current, replay=True)
        archived_at = archived_at or datetime.now(UTC)
        try:
            await self._session.execute(
                text(
                    """
                    UPDATE sharepoint_offer_files
                    SET active = FALSE, archived_at = :archived_at, updated_at = :archived_at
                    WHERE id = :id
                    """
                ),
                {"id": current["id"], "archived_at": archived_at},
            )
            await self._session.commit()
            row = await self._current(external_id)
            assert row is not None
            return self._record(row)
        except Exception:
            await self._session.rollback()
            raise

    async def list_current(
        self,
        *,
        active_only: bool = True,
        needs_extraction: bool = False,
        limit: int = 500,
    ) -> list[SharePointOfferFileRecordV1]:
        result = await self._session.execute(
            text(
                """
                SELECT f.*, s.uri AS source_url,
                       EXISTS (
                           SELECT 1 FROM historical_offers h
                           WHERE h.external_id = f.external_id
                             AND h.is_current = TRUE AND h.active = TRUE
                       ) AS structured_output_available
                FROM sharepoint_offer_files f
                JOIN source_snapshots s ON s.id = f.source_snapshot_id
                WHERE f.is_current = TRUE
                  AND (:active_only = FALSE OR f.active = TRUE)
                  AND (
                      :needs_extraction = FALSE OR NOT EXISTS (
                          SELECT 1 FROM historical_offers h
                          WHERE h.external_id = f.external_id
                            AND h.is_current = TRUE AND h.active = TRUE
                      )
                  )
                ORDER BY f.modified_at DESC NULLS LAST, f.updated_at DESC, f.external_id
                LIMIT :limit
                """
            ),
            {
                "active_only": active_only,
                "needs_extraction": needs_extraction,
                "limit": limit,
            },
        )
        return [self._record(dict(row)) for row in result.mappings()]
