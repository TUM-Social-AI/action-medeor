"""Append-only normalized offer versions with a single active/current pointer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.offers.contracts import NormalizedOfferUpsertV1, OfferRecordV1


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class OfferRepositoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock(self, external_id: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"allocura-offer-v1:{external_id}"},
        )

    async def _current(self, external_id: str) -> dict[str, object] | None:
        result = await self._session.execute(
            text(
                """
                SELECT h.*, s.uri AS source_url
                FROM historical_offers h
                JOIN source_snapshots s ON s.id = h.source_snapshot_id
                WHERE h.external_id = :external_id AND h.is_current = TRUE
                """
            ),
            {"external_id": external_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _record(row: dict[str, object], *, replay: bool = False) -> OfferRecordV1:
        return OfferRecordV1(
            offer_id=row["id"],
            external_id=str(row["external_id"]),
            source_version=str(row["external_version"]),
            source_url=str(row["source_url"]),
            active=bool(row["active"]),
            raw_request_text=str(row["raw_request_text"]),
            offered_description=row["offered_description"],
            item_number=row["item_number"],
            partner_id=row["partner_id"],
            destination_country=row["destination_country"],
            supplier=row["supplier"],
            quantity=row["quantity"],
            package=row["package"],
            price=row["price"],
            currency=row["currency"],
            price_basis=row["price_basis"],
            offer_date=row["offer_date"],
            metadata=row["metadata_json"] or {},
            archived_at=row["archived_at"],
            updated_at=row["updated_at"],
            idempotent_replay=replay,
        )

    async def _source_snapshot(
        self,
        *,
        external_id: str,
        source_version: str,
        source_url: str,
        captured_at: datetime,
        metadata: dict[str, object],
    ) -> UUID:
        existing = await self._session.scalar(
            text(
                """
                SELECT id FROM source_snapshots
                WHERE source_type = 'sharepoint' AND document_id = :external_id
                  AND checksum = :source_version
                """
            ),
            {"external_id": external_id, "source_version": source_version},
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
                "source_url": source_url,
                "source_version": source_version,
                "captured_at": captured_at,
                "metadata": _json(metadata),
            },
        )
        return snapshot_id

    async def upsert(
        self, external_id: str, payload: NormalizedOfferUpsertV1
    ) -> OfferRecordV1:
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
            source_id = await self._source_snapshot(
                external_id=external_id,
                source_version=payload.source_version,
                source_url=str(payload.source_url),
                captured_at=payload.captured_at,
                metadata=payload.metadata,
            )
            reported_item_number = payload.item_number
            item_number = None
            if reported_item_number:
                item_number = await self._session.scalar(
                    text("SELECT item_number FROM catalog_items WHERE item_number = :item_number"),
                    {"item_number": reported_item_number},
                )
            metadata = dict(payload.metadata)
            if reported_item_number and item_number is None:
                metadata["reported_item_number"] = reported_item_number
            if current:
                await self._session.execute(
                    text(
                        "UPDATE historical_offers SET is_current = FALSE WHERE id = :current_id"
                    ),
                    {"current_id": current["id"]},
                )
            offer_id = uuid4()
            updated_at = datetime.now(UTC)
            await self._session.execute(
                text(
                    """
                    INSERT INTO historical_offers (
                        id, source_snapshot_id, external_id, external_version,
                        is_current, active, raw_request_text, item_number,
                        offered_description, partner_id, destination_country, supplier,
                        quantity, package, price, currency, price_basis, offer_date,
                        metadata_json, created_at, updated_at
                    ) VALUES (
                        :id, :source_id, :external_id, :external_version, TRUE, TRUE,
                        :raw_request_text, :item_number, :offered_description, :partner_id,
                        :destination_country, :supplier, CAST(:quantity AS jsonb),
                        CAST(:package AS jsonb), :price, :currency, :price_basis, :offer_date,
                        CAST(:metadata AS jsonb), :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": offer_id,
                    "source_id": source_id,
                    "external_id": external_id,
                    "external_version": payload.source_version,
                    "raw_request_text": payload.raw_request_text,
                    "item_number": item_number,
                    "offered_description": payload.offered_description,
                    "partner_id": payload.partner_id,
                    "destination_country": payload.destination_country,
                    "supplier": payload.supplier,
                    "quantity": _json(payload.quantity.model_dump(mode="json"))
                    if payload.quantity
                    else None,
                    "package": _json(payload.package.model_dump(mode="json"))
                    if payload.package
                    else None,
                    "price": payload.price,
                    "currency": payload.currency,
                    "price_basis": payload.price_basis,
                    "offer_date": payload.offer_date,
                    "metadata": _json(metadata),
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
        source_version: str | None = None,
        archived_at: datetime | None = None,
    ) -> OfferRecordV1:
        await self._lock(external_id)
        current = await self._current(external_id)
        if current is None:
            raise LookupError("Offer not found")
        if not current["active"]:
            await self._session.rollback()
            return self._record(current, replay=True)
        archived_at = archived_at or datetime.now(UTC)
        archive_version = source_version or f"archive:{archived_at.isoformat()}"
        source_id = await self._source_snapshot(
            external_id=external_id,
            source_version=archive_version,
            source_url=str(current["source_url"]),
            captured_at=archived_at,
            metadata={"operation": "archive", "previous_offer_id": str(current["id"])},
        )
        try:
            await self._session.execute(
                text("UPDATE historical_offers SET is_current = FALSE WHERE id = :id"),
                {"id": current["id"]},
            )
            archive_id = uuid4()
            await self._session.execute(
                text(
                    """
                    INSERT INTO historical_offers (
                        id, source_snapshot_id, external_id, external_version, is_current,
                        active, archived_at, raw_request_text, item_number, offered_description,
                        partner_id, destination_country, supplier, quantity, package, price,
                        currency, price_basis, offer_date, metadata_json, created_at, updated_at
                    ) VALUES (
                        :new_id, :source_id, :external_id, :external_version, TRUE,
                        FALSE, :archived_at, :raw_request_text, :item_number,
                        :offered_description, :partner_id, :destination_country, :supplier,
                        CAST(:quantity AS jsonb), CAST(:package AS jsonb), :price, :currency,
                        :price_basis, :offer_date, CAST(:metadata AS jsonb), :created_at, :updated_at
                    )
                    """
                ),
                {
                    "new_id": archive_id,
                    "source_id": source_id,
                    "external_id": external_id,
                    "external_version": archive_version,
                    "archived_at": archived_at,
                    "raw_request_text": current["raw_request_text"],
                    "item_number": current["item_number"],
                    "offered_description": current["offered_description"],
                    "partner_id": current["partner_id"],
                    "destination_country": current["destination_country"],
                    "supplier": current["supplier"],
                    "quantity": _json(current["quantity"]) if current["quantity"] else None,
                    "package": _json(current["package"]) if current["package"] else None,
                    "price": current["price"],
                    "currency": current["currency"],
                    "price_basis": current["price_basis"],
                    "offer_date": current["offer_date"],
                    "metadata": _json(current["metadata_json"] or {}),
                    "created_at": archived_at,
                    "updated_at": archived_at,
                },
            )
            await self._session.commit()
            row = await self._current(external_id)
            assert row is not None
            return self._record(row)
        except Exception:
            await self._session.rollback()
            raise

    async def list_current(self, *, active_only: bool = True, limit: int = 200) -> list[OfferRecordV1]:
        result = await self._session.execute(
            text(
                """
                SELECT h.*, s.uri AS source_url
                FROM historical_offers h
                JOIN source_snapshots s ON s.id = h.source_snapshot_id
                WHERE h.is_current = TRUE AND (:active_only = FALSE OR h.active = TRUE)
                ORDER BY h.updated_at DESC, h.external_id
                LIMIT :limit
                """
            ),
            {"active_only": active_only, "limit": limit},
        )
        return [self._record(dict(row)) for row in result.mappings()]
