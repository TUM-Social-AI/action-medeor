"""Async document extraction adapter and literal-to-domain normalization."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.offers.contracts import NormalizedOfferUpsertV1
from app.offers.dates import resolve_validity
from app.offers.extraction import PROMPT_VERSION, OfferExtraction, extract_offers
from app.sharepoint.changes import SharePointChange
from app.sharepoint.scope import content_version

EXTRACTION_VERSION = f"{PROMPT_VERSION}:normalization-v1"
BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class DownloadedDocument:
    sharepoint_item_id: str
    filename: str
    mime_type: str | None
    content: bytes
    modified_at: datetime | None
    created_at: datetime | None = None


async def extract_mock(
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


class UnsupportedDocument(ValueError):
    pass


class ExtractionFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class OfferBatch:
    offers: list[NormalizedOfferUpsertV1]
    extraction: OfferExtraction


def normalize(
    change: SharePointChange,
    document: DownloadedDocument,
    result: OfferExtraction,
) -> OfferBatch:
    if result.failures:
        raise ExtractionFailure("; ".join(result.failures))
    if any("unsupported" in warning for warning in result.warnings):
        raise UnsupportedDocument("; ".join(result.warnings))
    if not result.chunks_succeeded:
        raise UnsupportedDocument(
            "; ".join(result.warnings) or "Document contains no readable data"
        )
    if not change.item.web_url or change.item.domain not in ("medicine", "equipment"):
        raise ValueError("Offer file needs a SharePoint URL and configured product domain")
    normalized = []
    for offer in result.offers:
        warnings = list(offer.warnings)
        if not offer.item_description.strip():
            warnings.append("Offered item description missing; excluded from automatic matching.")
        if offer.offer_date is not None:
            offer_date = datetime.combine(offer.offer_date, time(), BERLIN)
            date_source = "document"
        else:
            offer_date = document.created_at
            date_source = "sharepoint_created" if offer_date else None
            warnings.append(
                "Offer date estimated from SharePoint file creation."
                if offer_date
                else "Offer date unknown; file creation date unavailable."
            )
        anchor = offer_date.astimezone(BERLIN).date() if offer_date else None
        valid_until, validity_source, date_warnings = resolve_validity(
            offer.valid_until,
            offer.validity_text,
            anchor,
        )
        warnings.extend(date_warnings)
        if validity_source == "relative":
            validity_source = f"relative_{date_source}"
            warnings.append(
                "Offer expiry calculated from relative validity and the resolved offer date."
            )
        evidenced = {entry.field for entry in offer.evidence}
        matching_eligible = (
            bool((offer.supplier or "").strip() and offer.item_description.strip())
            and {
                "supplier",
                "item_description",
            }
            <= evidenced
            and not any(
                warning.startswith("Unverified source identity")
                or warning.startswith("Unverified source evidence: supplier")
                or warning.startswith("Unverified source evidence: item_description")
                for warning in warnings
            )
        )
        normalized.append(
            NormalizedOfferUpsertV1(
                source_version=f"{content_version(change.item)}:{EXTRACTION_VERSION}",
                source_url=change.item.web_url,
                captured_at=datetime.now(UTC),
                raw_request_text=(
                    offer.item_description
                    if offer.item_description.strip()
                    else f"Unidentified offered item at {offer.source_id}"
                ),
                offered_description=offer.item_description
                if offer.item_description.strip()
                else None,
                supplier=offer.supplier,
                price=offer.price_amount,
                currency=offer.currency,
                price_basis=offer.price_basis,
                offer_date=offer_date,
                valid_until=valid_until,
                metadata={
                    "extraction_status": "completed",
                    "extraction_version": EXTRACTION_VERSION,
                    "source_id": offer.source_id,
                    "alternative_index": offer.alternative_index,
                    "offer_reference": offer.offer_reference,
                    "date_kind": offer.date_kind,
                    "offer_date_source": date_source,
                    "offer_validity_source": validity_source,
                    "validity_text": offer.validity_text,
                    "price_text": offer.price_text,
                    "price_conflict": offer.price_conflict,
                    "evidence": [entry.model_dump() for entry in offer.evidence],
                    "warnings": warnings,
                    "matching_eligible": matching_eligible,
                    "domain": change.item.domain,
                },
            )
        )
    return OfferBatch(normalized, result)


async def extract(
    change: SharePointChange,
    document: DownloadedDocument,
    *,
    max_chunks: int = 32,
) -> OfferBatch:
    cancelled = threading.Event()
    try:
        result = await asyncio.to_thread(
            extract_offers,
            document.content,
            document.filename,
            max_chunks=max_chunks,
            should_stop=cancelled.is_set,
        )
    except asyncio.CancelledError:
        cancelled.set()
        raise
    return normalize(change, document, result)
