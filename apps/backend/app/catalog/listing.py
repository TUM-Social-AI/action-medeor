"""Read the current ERP articles and normalized supplier offers for the catalogue screen."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.contracts import CatalogueArticleV1


async def list_catalogue_articles(session: AsyncSession) -> list[CatalogueArticleV1]:
    erp = await session.execute(
        text(
            """
            SELECT c.item_number, c.domain, v.descriptions, v.manufacturer,
                   i.unit, CASE WHEN i.id IS NULL THEN NULL ELSE
                       GREATEST(0, COALESCE(i.on_hand, 0)
                           + COALESCE(i.incoming_purchase_order, 0)
                           - COALESCE(i.committed_order, 0)) END AS stock,
                   EXISTS (SELECT 1 FROM product_embeddings e
                           WHERE e.catalog_item_version_id = v.id) AS embedded
            FROM catalog_items c
            JOIN LATERAL (
                SELECT id, descriptions, manufacturer FROM catalog_item_versions
                WHERE item_number = c.item_number
                ORDER BY version_sequence DESC LIMIT 1
            ) v ON TRUE
            LEFT JOIN LATERAL (
                SELECT id, unit, on_hand, incoming_purchase_order, committed_order
                FROM inventory_snapshots WHERE item_number = c.item_number
                ORDER BY inventory_sequence DESC LIMIT 1
            ) i ON TRUE
            WHERE c.active = TRUE AND c.source_missing = FALSE
            ORDER BY c.item_number
            """
        )
    )
    articles = [
        CatalogueArticleV1(
            id=f"erp:{row['item_number']}",
            source="erp",
            name=next((value for value in row["descriptions"] or [] if value), row["item_number"]),
            vendor=row["manufacturer"],
            category=row["domain"],
            reference=row["item_number"],
            stock=str(row["stock"]) if row["stock"] is not None else None,
            unit=row["unit"],
            embedded=bool(row["embedded"]),
        )
        for row in erp.mappings()
    ]

    offers = await session.execute(
        text(
            """
            SELECT h.id, h.offered_description, h.raw_request_text, h.supplier,
                   h.domain, h.valid_until, h.unit_price, h.unit_price_unit,
                   h.currency, h.metadata_json, s.uri AS source_url, f.name AS file_name,
                   EXISTS (SELECT 1 FROM offer_embeddings e
                           WHERE e.offer_id = h.id) AS embedded
            FROM historical_offers h
            JOIN source_snapshots s ON s.id = h.source_snapshot_id
            LEFT JOIN LATERAL (
                SELECT name FROM sharepoint_offer_files
                WHERE external_id = h.source_item_id AND is_current = TRUE
                ORDER BY updated_at DESC LIMIT 1
            ) f ON TRUE
            WHERE h.is_current = TRUE AND h.active = TRUE
              AND COALESCE(h.metadata_json->>'extraction_status', '') != 'mock'
            ORDER BY h.updated_at DESC, h.id
            """
        )
    )
    for row in offers.mappings():
        metadata = row["metadata_json"] or {}
        reference = row["file_name"] or metadata.get("path")
        if not isinstance(reference, str) or not reference.strip():
            reference = unquote(urlparse(row["source_url"]).path).rstrip("/").split("/")[-1]
        reference = reference.rstrip("/").split("/")[-1] or "Supplier offer"
        articles.append(
            CatalogueArticleV1(
                id=f"offer:{row['id']}",
                source="sharepoint",
                name=row["offered_description"] or row["raw_request_text"],
                vendor=row["supplier"],
                category=row["domain"] or metadata.get("domain") or "unknown",
                reference=reference,
                source_url=row["source_url"],
                unit=row["unit_price_unit"],
                valid_until=row["valid_until"].isoformat() if row["valid_until"] else None,
                price=str(row["unit_price"]) if row["unit_price"] is not None else None,
                currency=row["currency"],
                embedded=bool(row["embedded"]),
            )
        )
    return articles
