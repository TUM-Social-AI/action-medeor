"""Persistence for parsed import requests, and the DB row <-> API schema conversions."""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    ExtractedItem,
    PartnerDetails,
    PartnerUpdate,
    ReviewCounts,
    ReviewResponse,
    SourceInfo,
    SourceReference,
)
from app.db.models import ImportRequestRow, RequestItemRow, RequestSourceReferenceRow
from app.parsing.types import ParsedDocument


def generate_request_id() -> str:
    return f"IMP-{dt.date.today():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


# ItemUpdate (API, camelCase) -> RequestItemRow (SQLAlchemy, snake_case) attribute names, for the
# fields where they differ. update_item_fields() applies this before setattr - without it, a
# camelCase key would silently set an unmapped, unpersisted instance attribute instead of erroring.
_ITEM_UPDATE_FIELD_MAP = {
    "itemNumber": "item_number",
    "shelfLife": "shelf_life",
}


async def save_parsed_request(
    session: AsyncSession,
    *,
    parsed: ParsedDocument,
    file_name: str,
) -> ImportRequestRow:
    request_id = generate_request_id()
    request = ImportRequestRow(
        request_id=request_id,
        source_file_name=file_name,
        rows_detected=parsed.rows_detected,
        request_date=dt.date.today().isoformat(),
        used_llm_fallback=parsed.used_llm_fallback,
        parser_warnings=parsed.warnings,
        attribute_columns=parsed.attribute_columns,
    )

    for position, parsed_item in enumerate(parsed.items):
        item = RequestItemRow(
            request_id=request_id,
            position=position,
            name=parsed_item.name,
            quantity=parsed_item.quantity,
            unit=parsed_item.unit,
            notes=parsed_item.notes,
            item_number=parsed_item.item_number,
            shelf_life=parsed_item.shelf_life,
            attributes=parsed_item.attributes,
            priority=parsed_item.priority,
            confidence=parsed_item.confidence,
            status=parsed_item.status,
        )
        if parsed_item.excerpt:
            item.source_reference = RequestSourceReferenceRow(
                request_id=request_id,
                page=parsed_item.page,
                row=parsed_item.row,
                excerpt=parsed_item.excerpt,
            )
        request.items.append(item)

    session.add(request)
    await session.commit()

    # session.refresh(request, attribute_names=["items"]) reloads the items collection but does
    # NOT eager-load each item's source_reference - to_review_response() touching it afterward
    # (a plain sync call, not awaited) then triggers a real lazy-load outside any async-bridged
    # context, which fails with MissingGreenlet. get_request_by_id() eager-loads both levels in
    # one query via selectinload, so nothing downstream ever needs an implicit lazy load.
    refreshed = await get_request_by_id(session, request_id)
    assert refreshed is not None  # we just committed this row in the same session
    return refreshed


async def get_request_by_id(session: AsyncSession, request_id: str) -> ImportRequestRow | None:
    statement = (
        select(ImportRequestRow)
        .where(ImportRequestRow.request_id == request_id)
        .options(
            selectinload(ImportRequestRow.items).selectinload(RequestItemRow.source_reference),
        )
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_item_by_id(session: AsyncSession, item_id: int) -> RequestItemRow | None:
    return await session.get(RequestItemRow, item_id)


async def update_item_fields(
    session: AsyncSession,
    item_id: int,
    fields: dict,
) -> RequestItemRow | None:
    item = await get_item_by_id(session, item_id)
    if item is None:
        return None
    for key, value in fields.items():
        setattr(item, _ITEM_UPDATE_FIELD_MAP.get(key, key), value)
    item.status = "verified"
    await session.commit()
    await session.refresh(item)
    return item


async def verify_item(session: AsyncSession, item_id: int) -> RequestItemRow | None:
    item = await get_item_by_id(session, item_id)
    if item is None:
        return None
    item.status = "verified"
    await session.commit()
    await session.refresh(item)
    return item


async def update_partner(
    session: AsyncSession,
    request_id: str,
    payload: PartnerUpdate,
) -> ImportRequestRow | None:
    request = await get_request_by_id(session, request_id)
    if request is None:
        return None
    request.partner = payload.partner
    request.region = payload.region
    request.contact = payload.contact
    request.confirmed = True
    await session.commit()
    await session.refresh(request)
    return request


def to_extracted_item(row: RequestItemRow) -> ExtractedItem:
    return ExtractedItem(
        id=row.id,
        name=row.name,
        quantity=row.quantity,
        unit=row.unit,
        notes=row.notes,
        itemNumber=row.item_number,
        shelfLife=row.shelf_life,
        attributes=row.attributes or {},
        priority=row.priority,
        confidence=row.confidence,
        status=row.status,
    )


def to_partner_details(row: ImportRequestRow) -> PartnerDetails:
    return PartnerDetails(
        partner=row.partner,
        region=row.region,
        requestId=row.request_id,
        contact=row.contact,
        confirmed=row.confirmed,
        requestDate=row.request_date,
        sourceFile=row.source_file_name,
    )


def to_review_response(row: ImportRequestRow) -> ReviewResponse:
    items = [to_extracted_item(item) for item in row.items]
    source_references = [
        SourceReference(
            itemId=item.id,
            page=item.source_reference.page,
            row=item.source_reference.row,
            excerpt=item.source_reference.excerpt,
        )
        for item in row.items
        if item.source_reference is not None
    ]

    return ReviewResponse(
        requestId=row.request_id,
        source=SourceInfo(
            fileName=row.source_file_name,
            rowsDetected=row.rows_detected,
            partner=row.partner,
        ),
        partner=to_partner_details(row),
        items=items,
        sourceReferences=source_references,
        counts=review_counts(items),
        attributeColumns=row.attribute_columns or [],
    )


def review_counts(items: list[ExtractedItem]) -> ReviewCounts:
    return ReviewCounts(
        total=len(items),
        verified=sum(1 for item in items if item.status == "verified"),
        needsReview=sum(1 for item in items if item.status == "needs_review"),
        lowConfidence=sum(1 for item in items if item.status == "low_confidence"),
        missing=sum(1 for item in items if item.status == "missing"),
    )
