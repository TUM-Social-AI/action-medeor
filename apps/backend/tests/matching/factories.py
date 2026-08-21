from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.matching.contracts import (
    AttributeValue,
    HistoricalOfferV1,
    InquiryLineV1,
    InventoryItemV1,
    ProductDomain,
    ProductPackage,
    QuantityValue,
    SourceReferenceV1,
    SourceType,
    StockSnapshot,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def source(document_id: str = "catalog-v1") -> SourceReferenceV1:
    return SourceReferenceV1(
        source_type=SourceType.ERP,
        document_id=document_id,
        checksum=f"checksum-{document_id}",
        captured_at=NOW,
    )


def line(
    *,
    description: str = "SONDE VESICALE FOLEY sterile CH18",
    item_number: str | None = None,
    attributes: dict[str, AttributeValue] | None = None,
) -> InquiryLineV1:
    return InquiryLineV1(
        inquiry_id="request-1",
        line_id="line-1",
        domain=ProductDomain.EQUIPMENT,
        raw_description=description,
        requested_item_number=item_number,
        quantity=QuantityValue(value=Decimal("50"), unit="piece", raw_expression="50"),
        attributes=attributes
        or {
            "charriere": AttributeValue(value=18, unit="CH"),
            "sterile": AttributeValue(value=True),
        },
        partner_id="partner-1",
        destination_country="CD",
        source=SourceReferenceV1(
            source_type=SourceType.EXCEL,
            document_id="request.xlsx",
            checksum="request-checksum",
            captured_at=NOW,
            sheet="Tabelle1",
            row=7,
        ),
    )


def item(
    item_number: str,
    description: str,
    *,
    charriere: int = 18,
    active: bool = True,
    quality_blocked: bool = False,
    units_per_package: Decimal = Decimal("12"),
    on_hand: Decimal | None = None,
) -> InventoryItemV1:
    stock = (
        StockSnapshot(on_hand=on_hand, unit="piece", captured_at=NOW)
        if on_hand is not None
        else None
    )
    return InventoryItemV1(
        item_number=item_number,
        domain=ProductDomain.EQUIPMENT,
        descriptions=(description,),
        attributes={
            "charriere": AttributeValue(value=charriere, unit="CH"),
            "sterile": AttributeValue(value=True),
        },
        manufacturer="Example Medical",
        package=ProductPackage(units_per_package=units_per_package, unit="piece"),
        active=active,
        quality_blocked=quality_blocked,
        stock=stock,
        source=source(),
    )


def historical_offer(item_number: str) -> HistoricalOfferV1:
    return HistoricalOfferV1(
        record_id="history-1",
        raw_request_text="sonde vesicale Foley CH18 sterile",
        item_number=item_number,
        partner_id="partner-1",
        destination_country="CD",
        source=SourceReferenceV1(
            source_type=SourceType.SHAREPOINT,
            document_id="old-offer.xlsx",
            checksum="history-checksum",
            captured_at=NOW,
        ),
    )
