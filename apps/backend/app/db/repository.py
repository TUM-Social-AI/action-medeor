"""Persistence for parsed import requests, and the DB row <-> API schema conversions."""

import datetime as dt
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    ExtractedItem,
    ManualItemCreate,
    ManualRequestCreate,
    PartnerDetails,
    PartnerUpdate,
    ReviewCounts,
    ReviewResponse,
    SourceInfo,
    SourceReference,
)
from app.db.models import ImportRequestRow, RequestItemRow, RequestSourceReferenceRow
from app.parsing.ai_review import FIELDS, fingerprint
from app.parsing.domain_inference import suggest_domain
from app.parsing.keywords import match_column_role
from app.parsing.service import parse_upload
from app.parsing.types import CustomColumnSpec, ParsedDocument, ParsedLineItem


def generate_request_id() -> str:
    return f"IMP-{dt.date.today():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


class RawFileUnavailable(Exception):
    """Raised by add_custom_column() when the request has no stored source file to re-parse -
    rows created before this feature, or the fixture demo request."""


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
    raw_file: bytes | None = None,
    request_id: str | None = None,
) -> ImportRequestRow:
    request = await get_request_by_id(session, request_id) if request_id else None
    if request_id and (request is None or request.workflow_status != "draft"):
        raise ValueError("Only an existing draft request can receive a file")
    if request is None:
        request_id = generate_request_id()
        request = ImportRequestRow(request_id=request_id, source_file_name="")
    request.source_file_name = file_name
    request.rows_detected = parsed.rows_detected
    request.request_date = dt.date.today().isoformat()
    request.used_llm_fallback = parsed.used_llm_fallback
    request.parser_warnings = parsed.warnings
    request.table_mappings = parsed.table_mappings
    request.extraction_mode = parsed.extraction_mode
    request.partner = parsed.partner.get("partner", "")
    request.region = parsed.partner.get("region", "")
    request.contact = parsed.partner.get("contact", "")
    request.confirmed = False
    request.attribute_columns = parsed.attribute_columns
    request.available_columns = parsed.available_columns
    request.raw_file = raw_file
    request.workflow_status = "review"

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
            source_reference=None,
            domain=parsed_item.domain,
            verification_source=parsed_item.verification_source,
            inferred_fields=parsed_item.inferred_fields,
            review_reasons=parsed_item.review_reasons,
            protected_fields=parsed_item.protected_fields,
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
    await session.flush()
    sources = {
        str(item.id): source.review_source
        for item, source in zip(request.items, parsed.items, strict=True)
    }
    request.ai_review = {"summary": parsed.review_summary, "sources": sources}
    saved_document = review_document_from_request(request)
    request.ai_review = {
        **request.ai_review,
        "fingerprint": fingerprint(raw_file or b"", saved_document),
    }
    await session.commit()

    # session.refresh(request, attribute_names=["items"]) reloads the items collection but does
    # NOT eager-load each item's source_reference - to_review_response() touching it afterward
    # (a plain sync call, not awaited) then triggers a real lazy-load outside any async-bridged
    # context, which fails with MissingGreenlet. get_request_by_id() eager-loads both levels in
    # one query via selectinload, so nothing downstream ever needs an implicit lazy load.
    refreshed = await get_request_by_id(session, request_id)
    assert refreshed is not None  # we just committed this row in the same session
    return refreshed


async def get_request_by_id(
    session: AsyncSession, request_id: str, *, lock: bool = False
) -> ImportRequestRow | None:
    statement = (
        select(ImportRequestRow)
        .where(ImportRequestRow.request_id == request_id)
        .options(
            selectinload(ImportRequestRow.items).selectinload(RequestItemRow.source_reference),
        )
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def suggest_missing_item_domains(
    session: AsyncSession, request: ImportRequestRow, *, commit: bool = True
) -> None:
    """Fill suggestions for review rows uploaded before automatic classification existed."""
    if request.workflow_status != "review":
        return
    changed = False
    for item in request.items:
        if item.domain is None and not item.review_reasons:
            source_type = next(
                (
                    value
                    for label, value in (item.attributes or {}).items()
                    if match_column_role(label) == "domain"
                ),
                "",
            )
            domain = suggest_domain(item.name, item.unit, source_type=source_type)
            if domain:
                item.domain = domain
                changed = True
    if changed and commit:
        await session.commit()


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
    actual_changes = {
        _ITEM_UPDATE_FIELD_MAP.get(key, key)
        for key, value in fields.items()
        if getattr(item, _ITEM_UPDATE_FIELD_MAP.get(key, key)) != value
    }
    for key, value in fields.items():
        setattr(item, _ITEM_UPDATE_FIELD_MAP.get(key, key), value)
    item.status = "verified"
    item.verification_source = "human"
    item.review_reasons = []
    # Editing confirms the submitted values; a verification click confirms every core field.
    changed_fields = {_ITEM_UPDATE_FIELD_MAP.get(key, key) for key in fields}
    legacy = (
        {field for field in FIELDS if getattr(item, field) not in (None, "")}
        if item.protected_fields is None
        else set(item.protected_fields)
    )
    item.protected_fields = sorted(legacy | changed_fields)
    inferred = dict(item.inferred_fields or {})
    for field in actual_changes:
        inferred.pop(
            {"domain": "type", "item_number": "itemNumber", "shelf_life": "shelfLife"}.get(
                field, field
            ),
            None,
        )
    item.inferred_fields = inferred
    await session.commit()
    await session.refresh(item)
    return item


async def verify_item(session: AsyncSession, item_id: int) -> RequestItemRow | None:
    item = await get_item_by_id(session, item_id)
    if item is None:
        return None
    item.status = "verified"
    item.verification_source = "human"
    item.review_reasons = []
    item.protected_fields = sorted(set(item.protected_fields or []) | set(FIELDS))
    await session.commit()
    await session.refresh(item)
    return item


async def update_partner(
    session: AsyncSession,
    request_id: str,
    payload: PartnerUpdate,
) -> ImportRequestRow | None:
    request = await get_request_by_id(session, request_id, lock=True)
    if request is None:
        return None
    changed = any(
        getattr(request, field) != getattr(payload, field)
        for field in ("partner", "region", "contact")
    )
    for field in ("partner", "region", "contact"):
        setattr(request, field, getattr(payload, field))
    if changed:
        request.confirmed = False
    await session.commit()
    await session.refresh(request)
    return request


async def confirm_partner(session: AsyncSession, request_id: str) -> ImportRequestRow | None:
    request = await get_request_by_id(session, request_id, lock=True)
    if request is None:
        return None
    request.confirmed = True
    await session.commit()
    await session.refresh(request)
    return request


async def update_column_label(
    session: AsyncSession,
    request_id: str,
    column_key: str,
    label: str,
) -> ImportRequestRow | None:
    request = await get_request_by_id(session, request_id)
    if request is None:
        return None

    # Reassign rather than mutate in place: SQLAlchemy's change-tracking for a JSON column only
    # notices a new object being assigned to the attribute, not an in-place dict mutation.
    updated_labels = dict(request.column_labels or {})
    label = label.strip()
    if label:
        updated_labels[column_key] = label
    else:
        updated_labels.pop(column_key, None)  # blank label = reset to the default
    request.column_labels = updated_labels

    await session.commit()
    await session.refresh(request)
    return request


async def add_custom_column(
    session: AsyncSession,
    request_id: str,
    display_name: str,
    hint: str,
) -> ImportRequestRow | None:
    """Adds one more field to extract, requested from the review screen after the fact (see
    ReviewItemsScreen's "Add column" control) - re-parses the original file with every custom
    column requested so far (this one plus any earlier ones) and merges only the newly resolved
    values into table items by page/row source reference. Stored layouts keep extraction stable;
    existing items, including manual edits to their core fields, are left untouched."""
    request = await get_request_by_id(session, request_id)
    if request is None:
        return None

    spec = CustomColumnSpec(display_name=display_name, hint=hint)
    if not spec.display_name:
        return request

    existing_specs = [CustomColumnSpec(**entry) for entry in (request.custom_columns or [])]
    if any(existing.display_name.lower() == spec.display_name.lower() for existing in existing_specs):
        return request  # already requested - no-op rather than erroring on a duplicate click

    if request.raw_file is None:
        raise RawFileUnavailable(request_id)

    all_specs = [*existing_specs, spec]
    parsed = parse_upload(
        filename=request.source_file_name, content=request.raw_file, custom_columns=all_specs,
        table_mappings=request.table_mappings or {}
    )

    tabular_file = request.source_file_name.lower().endswith((".xlsx", ".xls", ".csv"))
    table_pages = parsed.table_mappings.get("tables", {})
    by_source = {(item.page, item.row): item for item in parsed.items if item.row > 0}
    for item in request.items:
        if item.manual:
            continue
        reference = item.source_reference
        table_item = tabular_file or (reference is not None and str(reference.page) in table_pages)
        if table_item and reference and reference.row > 0:
            source_item = by_source.get((reference.page, reference.row))
        elif not table_item and item.position < len(parsed.items):
            source_item = parsed.items[item.position]
        else:
            source_item = None
        value = source_item.attributes.get(spec.display_name) if source_item else None
        if value:
            updated_attributes = dict(item.attributes or {})
            updated_attributes[spec.display_name] = value
            item.attributes = updated_attributes
    request.table_mappings = parsed.table_mappings
    request.parser_warnings = list(dict.fromkeys([*(request.parser_warnings or []), *parsed.warnings]))
    request.used_llm_fallback = request.used_llm_fallback or parsed.used_llm_fallback

    request.custom_columns = [
        *(request.custom_columns or []),
        {"display_name": spec.display_name, "hint": spec.hint},
    ]
    if spec.display_name not in request.attribute_columns:
        request.attribute_columns = [*request.attribute_columns, spec.display_name]

    normalized_name = spec.display_name.strip().lower()
    normalized_hint = spec.hint.strip().lower()
    request.available_columns = [
        label
        for label in request.available_columns or []
        if label.strip().lower() not in (normalized_name, normalized_hint)
    ]

    await session.commit()

    # Same MissingGreenlet trap as save_parsed_request(): session.refresh(request) would reload
    # the request's own columns but not eager-load items.source_reference, and
    # to_review_response() touching it afterward would trigger a real lazy-load outside any
    # async-bridged context. Re-fetch via get_request_by_id() instead, which eager-loads both
    # levels in one query.
    refreshed = await get_request_by_id(session, request_id)
    assert refreshed is not None  # we just committed this row in the same session
    return refreshed


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
        domain=row.domain,
        manual=bool(row.manual),
        verificationSource=row.verification_source,
        inferredFields=row.inferred_fields or {},
        reviewReasons=row.review_reasons or [],
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
        columnLabels=row.column_labels or {},
        availableColumns=row.available_columns or [],
        parserWarnings=row.parser_warnings or [],
        usedLlm=bool(row.used_llm_fallback),
        extractionMode=row.extraction_mode,
        reviewSummary=(row.ai_review or {}).get("summary", {}),
    )


def review_counts(items: list[ExtractedItem]) -> ReviewCounts:
    return ReviewCounts(
        total=len(items),
        verified=sum(1 for item in items if item.status == "verified"),
        needsReview=sum(1 for item in items if item.status == "needs_review"),
        lowConfidence=sum(1 for item in items if item.status == "low_confidence"),
        missing=sum(1 for item in items if item.status == "missing"),
    )


async def create_draft_request(session: AsyncSession, *, manual: bool = False) -> ImportRequestRow:
    request = ImportRequestRow(
        request_id=generate_request_id(), source_file_name="",
        workflow_status="review" if manual else "draft",
        request_date=dt.date.today().isoformat() if manual else None,
    )
    session.add(request)
    await session.commit()
    saved = await get_request_by_id(session, request.request_id)
    assert saved is not None
    return saved


def append_manual_item(request: ImportRequestRow, payload: ManualItemCreate) -> RequestItemRow:
    fields = payload.model_dump()
    item = RequestItemRow(
        request_id=request.request_id,
        position=max((row.position for row in request.items), default=-1) + 1,
        **{_ITEM_UPDATE_FIELD_MAP.get(key, key): value for key, value in fields.items()},
        manual=True,
        status="verified",
        confidence=None,
        verification_source="human",
        protected_fields=list(FIELDS),
    )
    item.name = item.name.strip()
    request.items.append(item)
    return item


async def create_manual_request(
    session: AsyncSession, payload: ManualRequestCreate
) -> ImportRequestRow:
    """Save the request and its first item together, without creating an empty request."""
    request = ImportRequestRow(
        request_id=generate_request_id(), source_file_name="", workflow_status="review",
        request_date=dt.date.today().isoformat(), partner=payload.partner,
        region=payload.region, contact=payload.contact, confirmed=payload.confirmed,
        column_labels=payload.columnLabels,
    )
    append_manual_item(request, payload.item)
    session.add(request)
    await session.commit()
    saved = await get_request_by_id(session, request.request_id)
    assert saved is not None
    return saved


async def add_manual_item(
    session: AsyncSession, request: ImportRequestRow, payload: ManualItemCreate
) -> RequestItemRow:
    item = append_manual_item(request, payload)
    await session.commit()
    await session.refresh(item)
    return item


async def request_match_rates(session: AsyncSession) -> dict[str, int]:
    """Count selected articles for completed requests using each line's latest decision."""
    result = await session.execute(
        text("""SELECT ri.request_id, COUNT(md.candidate_id) AS matched
                FROM request_items ri
                JOIN import_requests r ON r.request_id = ri.request_id
                LEFT JOIN LATERAL (
                    SELECT candidate_id FROM match_decisions
                    WHERE match_run_id = ri.current_match_run_id
                    ORDER BY created_at DESC, id DESC LIMIT 1
                ) md ON TRUE
                WHERE r.workflow_status IN ('complete', 'finalized')
                GROUP BY ri.request_id""")
    )
    return {row.request_id: int(row.matched) for row in result}


class RequestCurrentlyMatching(Exception):
    """An active worker could recreate matching records after a request is removed."""


async def delete_request(session: AsyncSession, request_id: str) -> bool:
    """Remove a saved request and its matching data in one transaction."""
    params = {"id": request_id}
    # Match workers lock the job before the request, so use the same order here.
    await session.execute(
        text("SELECT request_id FROM request_matching_jobs WHERE request_id = :id FOR UPDATE"),
        params,
    )
    status = await session.scalar(
        text("SELECT workflow_status FROM import_requests WHERE request_id = :id FOR UPDATE"),
        params,
    )
    if status is None:
        await session.rollback()
        return False
    if status == "matching":
        await session.rollback()
        raise RequestCurrentlyMatching()

    await session.execute(text("DELETE FROM request_matching_jobs WHERE request_id = :id"), params)
    await session.execute(
        text("""DELETE FROM match_decisions
                WHERE match_run_id IN (SELECT id FROM match_runs WHERE inquiry_id = :id)"""),
        params,
    )
    await session.execute(text("DELETE FROM match_runs WHERE inquiry_id = :id"), params)
    await session.execute(text("DELETE FROM request_source_references WHERE request_id = :id"), params)
    await session.execute(text("DELETE FROM request_items WHERE request_id = :id"), params)
    await session.execute(text("DELETE FROM import_requests WHERE request_id = :id"), params)
    await session.commit()
    return True


async def list_requests(session: AsyncSession) -> list[ImportRequestRow]:
    result = await session.execute(
        select(ImportRequestRow)
        .options(selectinload(ImportRequestRow.items))
        .where(ImportRequestRow.workflow_status != "draft")
        .order_by(ImportRequestRow.created_at.desc(), ImportRequestRow.id.desc())
    )
    return list(result.scalars().all())


def review_document_from_request(request: ImportRequestRow) -> ParsedDocument:
    sources = (request.ai_review or {}).get("sources", {})
    document = ParsedDocument(extraction_mode=request.extraction_mode)
    for item in request.items:
        reference = item.source_reference
        document.items.append(
            ParsedLineItem(
                **{field: getattr(item, field) for field in FIELDS},
                priority=item.priority,
                attributes=dict(item.attributes or {}),
                confidence=item.confidence,
                status=item.status,
                page=reference.page if reference else 0,
                row=reference.row if reference else 0,
                excerpt=reference.excerpt if reference else "",
                review_id=str(item.id),
                manual=item.manual,
                verification_source=item.verification_source,
                protected_fields=item.protected_fields,
                inferred_fields=dict(item.inferred_fields or {}),
                review_reasons=list(item.review_reasons or []),
                review_source=sources.get(str(item.id), {}),
            )
        )
    return document


def apply_ai_review(request: ImportRequestRow, document: ParsedDocument) -> None:
    items = {str(item.id): item for item in request.items}
    for result in document.items:
        item = items[result.review_id]
        if item.manual:
            continue
        for field in FIELDS:
            setattr(item, field, getattr(result, field))
        item.status = result.status
        item.confidence = result.confidence
        item.verification_source = result.verification_source
        item.inferred_fields = result.inferred_fields
        item.review_reasons = result.review_reasons
    request.used_llm_fallback = request.used_llm_fallback or document.used_llm_fallback
    history = list((request.ai_review or {}).get("attempt_history", []))
    previous = (request.ai_review or {}).get("summary", {})
    if previous.get("status") in {"unavailable", "partial"}:
        history.append({"status": previous["status"], "failures": previous.get("failures", {}),
                        "checked": previous.get("checked", 0)})
    request.ai_review = {
        "attempt_history": history[-5:],
        "summary": document.review_summary,
        "sources": {item.review_id: item.review_source for item in document.items},
        "fingerprint": fingerprint(request.raw_file or b"", document),
    }
