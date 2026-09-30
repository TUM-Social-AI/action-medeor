"""Temporary extraction boundary; the domain extraction workstream replaces this body."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.offers.contracts import NormalizedOfferUpsertV1
from app.sharepoint.changes import SharePointChange


@dataclass(frozen=True)
class DownloadedDocument:
    sharepoint_item_id: str
    filename: str
    mime_type: str | None
    content: bytes
    modified_at: datetime | None


async def extract(
    change: SharePointChange, document: DownloadedDocument
) -> NormalizedOfferUpsertV1:
    """Return an offer-shaped result. Normal sync never persists this mock result."""
    # TODO: replace this mock with the domain document extraction implementation.
    if not change.item.web_url:
        raise ValueError(f"SharePoint file {change.item.item_id} has no webUrl")
    return NormalizedOfferUpsertV1(
        source_version="smoke-v1",
        source_url=change.item.web_url,
        captured_at=datetime.now(UTC),
        raw_request_text=f"Mock extraction for {document.filename}",
        metadata={
            "extraction_status": "mock",
            "sharepoint_item_id": document.sharepoint_item_id,
            "filename": document.filename,
            "mime_type": document.mime_type,
            "size_bytes": len(document.content),
            "modified_at": document.modified_at.isoformat() if document.modified_at else None,
            "change_kind": change.kind,
        },
    )
