
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import fixtures
from app.api.request_workflow import (
    latest_snapshot_id,
    matching_state,
    request_state,
    to_inquiry_line,
)
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
    RequestDecision,
    RequestMatchingState,
    RequestState,
    ReviewResponse,
    SummaryResponse,
    TrendsResponse,
)
from app.db import repository
from app.db.repository import RawFileUnavailable
from app.db.session import get_session
from app.matching.api import get_matching_service
from app.matching.contracts import DecisionType, MatchDecisionRequestV1
from app.parsing import ParsingError, parse_upload

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


@router.post("/imports")
async def create_import(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    file_name, content, parsed = await _parse_request_file(file)
    request = await repository.save_parsed_request(
        session, parsed=parsed, file_name=file_name, raw_file=content
    )
    return repository.to_review_response(request)


async def _parse_request_file(file: UploadFile):
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

    try:
        parsed = parse_upload(filename=file_name, content=bytes(content))
    except ParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return file_name, bytes(content), parsed


@router.post("/requests", status_code=201)
async def create_request(session: AsyncSession = Depends(get_session)) -> RequestState:
    request = await repository.create_draft_request(session)
    return request_state(request)


@router.get("/requests")
async def list_requests(session: AsyncSession = Depends(get_session)) -> list[RequestState]:
    return [request_state(request) for request in await repository.list_requests(session)]


@router.get("/requests/{request_id}")
async def get_request(request_id: str, session: AsyncSession = Depends(get_session)) -> RequestState:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return request_state(request)


@router.post("/requests/{request_id}/file")
async def upload_request_file(
    request_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status != "draft":
        raise HTTPException(status_code=409, detail="This request already has an uploaded file")
    file_name, content, parsed = await _parse_request_file(file)
    saved = await repository.save_parsed_request(
        session, parsed=parsed, file_name=file_name, raw_file=content, request_id=request_id
    )
    return repository.to_review_response(saved)


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
        if request.workflow_status != "review":
            raise HTTPException(status_code=409, detail="Review is locked after matching starts")
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
        if request.workflow_status != "review":
            raise HTTPException(status_code=409, detail="Review is locked after matching starts")
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
        if request.workflow_status != "review":
            raise HTTPException(status_code=409, detail="Partner details are locked after matching starts")
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


@router.post("/requests/{request_id}/custom-columns")
async def add_custom_column(
    request_id: str,
    payload: CustomColumnRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """Adds one more field to extract, requested from the review screen after the fact - see
    ReviewItemsScreen's "Add column" control. Re-parses the original file and merges the newly
    resolved values into the already-persisted items; existing items (including manual edits) are
    otherwise untouched. See repository.add_custom_column for how re-parsing is kept consistent
    across repeated additions."""
    if not payload.displayName.strip():
        raise HTTPException(status_code=400, detail="Column name is required")

    request = await repository.get_request_by_id(session, request_id)
    if request is not None:
        if request.workflow_status != "review":
            raise HTTPException(status_code=409, detail="Review is locked after matching starts")
        try:
            updated = await repository.add_custom_column(
                session, request_id, payload.displayName, payload.hint
            )
        except RawFileUnavailable as exc:
            raise HTTPException(
                status_code=422,
                detail="The original file is no longer available for this request - re-upload it to add columns.",
            ) from exc
        except ParsingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return repository.to_review_response(updated)

    require_mock_request(request_id)
    raise HTTPException(
        status_code=422, detail="Columns can't be added to the demo request - upload a file first."
    )


@router.post("/requests/{request_id}/matching", status_code=202)
async def start_matching(
    request_id: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> RequestMatchingState | MatchingResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        require_mock_request(request_id)
        response.status_code = 200
        selected = {
            item.id: fixtures.ERP_MATCHES[item.id][0].id
            for item in fixtures.REQUESTED_ITEMS if fixtures.ERP_MATCHES.get(item.id)
        }
        return MatchingResponse(
            requestId=request_id, requestedItems=fixtures.REQUESTED_ITEMS,
            matches=fixtures.ERP_MATCHES, selectedMatches=selected,
        )
    if request.workflow_status in {"matching_queued", "matching", "match_review", "complete"}:
        state = await matching_state(session, request_id)
        assert state is not None
        return state
    if request.workflow_status not in {"review", "matching_failed"}:
        raise HTTPException(status_code=409, detail="Upload a file before matching")
    if not request.items or any(item.status != "verified" or not item.domain for item in request.items):
        raise HTTPException(status_code=422, detail="Verify and classify every item before matching")
    for item in request.items:
        try:
            to_inquiry_line(request, item)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Item {item.id}: {exc}") from exc
    if request.catalog_snapshot_id is None:
        request.catalog_snapshot_id = await latest_snapshot_id(session)
    if request.catalog_snapshot_id is None:
        raise HTTPException(status_code=409, detail="Import a catalog before matching")
    for item in request.items:
        if item.match_status == "failed":
            item.match_status = "pending"
            item.match_error = None
    request.workflow_status = "matching_queued"
    await session.execute(
        text("""INSERT INTO request_matching_jobs (request_id, status) VALUES (:id, 'queued')
                ON CONFLICT (request_id) DO UPDATE SET status = 'queued',
                lease_until = NULL, updated_at = CURRENT_TIMESTAMP"""),
        {"id": request_id},
    )
    await session.commit()
    state = await matching_state(session, request_id)
    assert state is not None
    return state


@router.get("/requests/{request_id}/matching")
async def get_matching(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> RequestMatchingState:
    state = await matching_state(session, request_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return state


@router.post("/requests/{request_id}/items/{item_id}/decision")
async def decide_match(
    request_id: str,
    item_id: int,
    payload: RequestDecision,
    session: AsyncSession = Depends(get_session),
) -> RequestMatchingState:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status not in {"match_review", "complete"}:
        raise HTTPException(status_code=409, detail="Matching is not complete")
    item = next((item for item in request.items if item.id == item_id), None)
    if item is None or item.current_match_run_id is None:
        raise HTTPException(status_code=404, detail="Matched item not found")
    service = get_matching_service(session)
    run = await service.get_run(item.current_match_run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="Match run is unavailable")
    candidate = next((candidate for candidate in run.candidates if candidate.candidate_id == payload.candidateId), None)
    if not payload.noMatch and candidate is None:
        raise HTTPException(status_code=422, detail="Choose a candidate or No match")
    if payload.noMatch and payload.candidateId is not None:
        raise HTTPException(status_code=422, detail="No match cannot include a candidate")
    if candidate and candidate.rank != 1 and not (payload.overrideReason or "").strip():
        raise HTTPException(status_code=422, detail="Reason required for an alternative")
    decision = MatchDecisionRequestV1(
        match_run_id=item.current_match_run_id,
        inquiry_line_id=str(item.id),
        decision_type=(
            DecisionType.NO_MATCH if payload.noMatch else
            DecisionType.ACCEPT_SUGGESTION if candidate and candidate.rank == 1 else
            DecisionType.SELECT_ALTERNATIVE
        ),
        candidate_id=candidate.candidate_id if candidate else None,
        selected_item_number=candidate.item_number if candidate else None,
        override_reason=payload.overrideReason.strip() if payload.overrideReason else None,
    )
    await service.save_decision(decision)
    undecided = await session.scalar(
        text("""SELECT COUNT(*) FROM request_items ri WHERE ri.request_id = :id
                AND ri.current_match_run_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM match_decisions md
                                WHERE md.match_run_id = ri.current_match_run_id)"""),
        {"id": request_id},
    )
    if undecided == 0:
        request.workflow_status = "complete"
        await session.commit()
    state = await matching_state(session, request_id)
    assert state is not None
    return state


@router.patch("/requests/{request_id}/matching/{item_id}")
async def update_matching(
    request_id: str,
    item_id: int,
    payload: MatchSelection,
    session: AsyncSession = Depends(get_session),
) -> MatchSelectionResponse:
    if await repository.get_request_by_id(session, request_id) is not None:
        raise HTTPException(status_code=409, detail="Use the saved decision API for this request")
    require_mock_request(request_id)
    find_match(item_id, payload.matchId)
    return MatchSelectionResponse(itemId=item_id, matchId=payload.matchId)


@router.get("/requests/{request_id}/summary")
async def summary(request_id: str, session: AsyncSession = Depends(get_session)) -> dict | SummaryResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        require_mock_request(request_id)
        return fixtures.summary_response()
    if request.workflow_status != "complete":
        raise HTTPException(status_code=409, detail="Decide every matched item before summary")
    state = await matching_state(session, request_id)
    assert state is not None
    items = []
    for line in state.lines:
        candidate = next(
            (candidate for candidate in line.candidates
             if candidate["candidate_id"] == str(line.selectedCandidateId)),
            None,
        )
        items.append({
            "itemId": line.itemId,
            "requested": line.name,
            "quantity": line.quantity,
            "unit": line.unit,
            "domain": line.domain,
            "decision": line.decisionType,
            "itemNumber": candidate["item_number"] if candidate else None,
            "product": candidate["descriptions"][0] if candidate else None,
            "availability": candidate["availability_status"] if candidate else None,
            "warnings": candidate["warnings"] if candidate else [],
            "retrievalMethods": [evidence["retriever"] for evidence in candidate["retrieval_evidence"]]
            if candidate else [],
        })
    return {
        "requestId": request_id,
        "sourceFile": request.source_file_name,
        "partner": request.partner,
        "items": items,
        "matchedCount": sum(item["itemNumber"] is not None for item in items),
        "unmatchedCount": sum(item["itemNumber"] is None for item in items),
    }


@router.post("/requests/{request_id}/offer")
async def create_offer(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> OfferResponse:
    if await repository.get_request_by_id(session, request_id) is not None:
        raise HTTPException(status_code=409, detail="Offer generation is not available for real requests")
    require_mock_request(request_id)
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
