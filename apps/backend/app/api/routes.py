from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import fixtures
from app.api.schemas import (
    ColumnLabelUpdate,
    CustomColumnRequest,
    ErpMatch,
    ExtractedItem,
    HomeResponse,
    ItemUpdate,
    MatchingResponse,
    MatchSelection,
    MatchSelectionResponse,
    OfferResponse,
    PartnerDetails,
    PartnerUpdate,
    RecentImport,
    ReviewResponse,
    SummaryResponse,
    TrendsResponse,
)
from app.db import repository
from app.db.session import get_session
from app.parsing import CustomColumnSpec, ParsingError, parse_upload
from app.parsing.service import MAX_CUSTOM_COLUMNS

router = APIRouter(prefix="/api")

SUPPORTED_IMPORT_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/csv": "csv",
    # Browsers are inconsistent about CSV's content type - "application/csv" and "text/plain"
    # both show up in practice. Left out of this dict deliberately: an unrecognized content type
    # skips the mismatch check entirely (see create_import below) rather than being rejected.
}
SUPPORTED_IMPORT_EXTENSIONS = {"pdf", "xlsx", "xls", "docx", "csv"}
MAX_IMPORT_BYTES = 20 * 1024 * 1024


def require_mock_request(request_id: str) -> None:
    if request_id != fixtures.REQUEST_ID:
        raise HTTPException(status_code=404, detail="Request not found")


async def require_known_request(request_id: str, session: AsyncSession) -> None:
    """Matching/summary/offer are still fixture-backed (separate workstream), but must not 404
    just because a real upload produced a request_id other than the fixture's - so accept any
    request_id that actually exists, whether persisted from a real import or the fixture one."""
    if request_id == fixtures.REQUEST_ID:
        return
    if await repository.get_request_by_id(session, request_id) is not None:
        return
    raise HTTPException(status_code=404, detail="Request not found")


def find_item(item_id: int) -> ExtractedItem:
    for item in fixtures.EXTRACTED_ITEMS:
        if item.id == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")


def find_match(item_id: int, match_id: str) -> ErpMatch:
    for match in fixtures.ERP_MATCHES.get(item_id, []):
        if match.id == match_id:
            return match
    raise HTTPException(status_code=404, detail="Match candidate not found")


@router.get("/home")
async def home() -> HomeResponse:
    return fixtures.HOME_RESPONSE


@router.get("/imports/recent")
async def recent_imports() -> list[RecentImport]:
    return fixtures.RECENT_IMPORTS


_CustomColumnsList = TypeAdapter(list[CustomColumnRequest])


def _parse_custom_columns(raw: str) -> list[CustomColumnSpec]:
    """raw is a JSON-encoded array from the multipart form (see IngestionScreen) - a plain string
    field rather than real multipart list support, since the fields inside each entry need their
    own validation. Silently caps at MAX_CUSTOM_COLUMNS rather than rejecting the whole upload
    over a list that's merely too long."""
    if not raw or not raw.strip():
        return []
    try:
        requests = _CustomColumnsList.validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid customColumns: {exc}") from exc

    return [
        CustomColumnSpec(display_name=item.displayName, hint=item.hint)
        for item in requests[:MAX_CUSTOM_COLUMNS]
        if item.displayName.strip()
    ]


@router.post("/imports")
async def create_import(
    file: UploadFile = File(...),
    custom_columns: str = Form("[]"),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    file_name = file.filename or ""
    file_extension = file_name.lower().rsplit(".", maxsplit=1)[-1] if "." in file_name else ""

    if file_extension not in SUPPORTED_IMPORT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content_type = file.content_type or ""
    expected_extension = SUPPORTED_IMPORT_CONTENT_TYPES.get(content_type)
    if expected_extension is not None and expected_extension != file_extension:
        raise HTTPException(status_code=400, detail="File extension does not match content type")

    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")

    custom_column_specs = _parse_custom_columns(custom_columns)

    try:
        parsed = parse_upload(
            filename=file_name, content=bytes(content), custom_columns=custom_column_specs
        )
    except ParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    request = await repository.save_parsed_request(session, parsed=parsed, file_name=file_name)
    return repository.to_review_response(request)


@router.get("/requests/{request_id}/review")
async def review(request_id: str, session: AsyncSession = Depends(get_session)) -> ReviewResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is not None:
        return repository.to_review_response(request)

    require_mock_request(request_id)
    return fixtures.review_response()


@router.patch("/requests/{request_id}/items/{item_id}")
async def update_item(
    request_id: str,
    item_id: int,
    payload: ItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> ExtractedItem:
    request = await repository.get_request_by_id(session, request_id)
    if request is not None:
        if not any(item.id == item_id for item in request.items):
            raise HTTPException(status_code=404, detail="Item not found")
        update = payload.model_dump(exclude_unset=True)
        updated = await repository.update_item_fields(session, item_id, update)
        return repository.to_extracted_item(updated)

    require_mock_request(request_id)
    item = find_item(item_id)
    update = payload.model_dump(exclude_unset=True)
    return item.model_copy(update={**update, "status": "verified"})


@router.post("/requests/{request_id}/items/{item_id}/verify")
async def verify_item(
    request_id: str,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> ExtractedItem:
    request = await repository.get_request_by_id(session, request_id)
    if request is not None:
        if not any(item.id == item_id for item in request.items):
            raise HTTPException(status_code=404, detail="Item not found")
        updated = await repository.verify_item(session, item_id)
        return repository.to_extracted_item(updated)

    require_mock_request(request_id)
    item = find_item(item_id)
    return item.model_copy(update={"status": "verified"})


@router.patch("/requests/{request_id}/partner")
async def update_partner(
    request_id: str,
    payload: PartnerUpdate,
    session: AsyncSession = Depends(get_session),
) -> PartnerDetails:
    request = await repository.get_request_by_id(session, request_id)
    if request is not None:
        updated = await repository.update_partner(session, request_id, payload)
        return repository.to_partner_details(updated)

    require_mock_request(request_id)
    return PartnerDetails(**payload.model_dump(), confirmed=True)


@router.patch("/requests/{request_id}/column-labels")
async def update_column_label(
    request_id: str,
    payload: ColumnLabelUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    request = await repository.get_request_by_id(session, request_id)
    if request is not None:
        updated = await repository.update_column_label(
            session, request_id, payload.columnKey, payload.label
        )
        return updated.column_labels or {}

    # The fixture demo request has nothing to persist to - echo the rename back so the frontend
    # can still apply it to its local state, same as every other fixture-fallback route here.
    require_mock_request(request_id)
    label = payload.label.strip()
    return {payload.columnKey: label} if label else {}


@router.post("/requests/{request_id}/matching")
async def start_matching(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> MatchingResponse:
    await require_known_request(request_id, session)
    selected = {
        item.id: fixtures.ERP_MATCHES[item.id][0].id
        for item in fixtures.REQUESTED_ITEMS
        if fixtures.ERP_MATCHES.get(item.id)
    }
    return MatchingResponse(
        requestId=request_id,
        requestedItems=fixtures.REQUESTED_ITEMS,
        matches=fixtures.ERP_MATCHES,
        selectedMatches=selected,
    )


@router.patch("/requests/{request_id}/matching/{item_id}")
async def update_matching(
    request_id: str,
    item_id: int,
    payload: MatchSelection,
    session: AsyncSession = Depends(get_session),
) -> MatchSelectionResponse:
    await require_known_request(request_id, session)
    find_match(item_id, payload.matchId)
    return MatchSelectionResponse(itemId=item_id, matchId=payload.matchId)


@router.get("/requests/{request_id}/summary")
async def summary(request_id: str, session: AsyncSession = Depends(get_session)) -> SummaryResponse:
    await require_known_request(request_id, session)
    return fixtures.summary_response()


@router.post("/requests/{request_id}/offer")
async def create_offer(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> OfferResponse:
    await require_known_request(request_id, session)
    summary = fixtures.summary_response()
    return OfferResponse(
        requestId=request_id,
        fileName=f"Offer-{request_id}.pdf",
        lineItems=summary.metrics.totalLineItems,
        totalValue=summary.metrics.estimatedTotalValue,
        partner=summary.partner.partner,
        generatedAt="Jun 13, 2024",
    )


@router.get("/trends")
async def trends() -> TrendsResponse:
    return fixtures.TREND_RESPONSE
