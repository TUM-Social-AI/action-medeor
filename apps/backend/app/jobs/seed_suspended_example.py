"""Add the requested suspended catalogue example to the configured database once.

Run explicitly from apps/backend: uv run python -m app.jobs.seed_suspended_example
This is sample data, with its own provenance, rather than an ERP CSV import.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session, engine

ITEM_NUMBER = "ERP-51108"
EXAMPLE_KEY = "suspended-infusion-set-v1"
DESCRIPTION = "Infusion Set 20 drops/ml, Luer Lock"


async def seed_suspended_example(session: AsyncSession) -> bool:
    """Insert without committing; return False on replay and refuse identity collisions."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('allocura-catalog-import-v1'))")
    )
    existing = await session.execute(
        text("""
            SELECT c.item_number, s.metadata_json->>'example_key' AS example_key
            FROM catalog_items c
            LEFT JOIN LATERAL (
                SELECT source_snapshot_id FROM catalog_item_versions
                WHERE item_number = c.item_number ORDER BY version_sequence DESC LIMIT 1
            ) v ON TRUE
            LEFT JOIN source_snapshots s ON s.id = v.source_snapshot_id
            WHERE c.item_number = :item_number
        """),
        {"item_number": ITEM_NUMBER},
    )
    row = existing.mappings().first()
    if row:
        if row["example_key"] == EXAMPLE_KEY:
            return False
        raise ValueError(f"{ITEM_NUMBER} already exists; refusing to overwrite an article")

    attributes = {
        "base_unit": {"value": "pcs"},
        "blocked": {"value": True},
        "sales_blocked": {"value": False},
        "purchasing_blocked": {"value": False},
    }
    canonical_text = f"{ITEM_NUMBER}\n{DESCRIPTION}\nFlowMed GmbH"
    content_hash = hashlib.sha256(canonical_text.encode()).hexdigest()
    record_hash = hashlib.sha256(
        json.dumps({"text": canonical_text, "attributes": attributes}, sort_keys=True).encode()
    ).hexdigest()
    source_id = uuid4()
    now = datetime.now(UTC)
    params = {
        "item_number": ITEM_NUMBER,
        "source_id": source_id,
        "now": now,
        "description": json.dumps([DESCRIPTION]),
        "attributes": json.dumps(attributes),
        "canonical_text": canonical_text,
        "content_hash": content_hash,
        "record_hash": record_hash,
    }
    await session.execute(
        text("""
            INSERT INTO source_snapshots (
                id, source_type, document_id, checksum, captured_at, metadata_json
            ) VALUES (
                :source_id, 'erp', :document_id, :record_hash, :now, CAST(:metadata AS jsonb)
            )
        """),
        params | {
            "document_id": f"catalogue-example:{EXAMPLE_KEY}",
            "metadata": json.dumps({"example_key": EXAMPLE_KEY, "sample_data": True}),
        },
    )
    await session.execute(
        text("""
            INSERT INTO catalog_items (item_number, domain, matching_eligible)
            VALUES (:item_number, 'equipment', FALSE)
        """), params,
    )
    await session.execute(
        text("""
            INSERT INTO catalog_item_versions (
                id, item_number, source_snapshot_id, descriptions, attributes, manufacturer,
                content_hash, record_hash, canonical_text, valid_from, domain, matching_eligible
            ) VALUES (
                :version_id, :item_number, :source_id, CAST(:description AS jsonb),
                CAST(:attributes AS jsonb), 'FlowMed GmbH', :content_hash, :record_hash,
                :canonical_text, :now, 'equipment', FALSE
            )
        """), params | {"version_id": uuid4()},
    )
    await session.execute(
        text("""
            INSERT INTO inventory_snapshots (
                id, item_number, source_snapshot_id, on_hand, incoming_purchase_order,
                committed_order, unit, captured_at
            ) VALUES (:inventory_id, :item_number, :source_id, 340, 0, 0, 'pcs', :now)
        """), params | {"inventory_id": uuid4()},
    )
    return True


async def _main() -> None:
    try:
        async with async_session() as session, session.begin():
            created = await seed_suspended_example(session)
        print(f"{ITEM_NUMBER}: {'added suspended example' if created else 'example already exists'}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
