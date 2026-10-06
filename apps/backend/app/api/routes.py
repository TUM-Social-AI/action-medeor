from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api import fixtures
from app.api.identity import extraction_mode
from app.api.matched_results_export import build_matched_results_workbook, results_filename
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
    ManualItemCreate,
    ManualRequestCreate,
    MatchingResponse,
    MatchSelection,
    MatchSelectionResponse,
    OfferResponse,
    PartnerDetails,
    PartnerUpdate,
    RecentImport,
    RequestCreate,
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
from app.matching.auto_select import auto_select_item
from app.matching.contracts import DecisionType, MatchDecisionRequestV1
from app.parsing import ParsingError, parse_upload
from app.parsing.ai_review import fingerprint, review_document
from app.parsing.review_sources import fill_legacy_sources

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
    http_request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    mode = await extraction_mode(http_request, session)
    await session.commit()
    file_name, content, parsed = await _parse_request_file(file, mode)
    request = await repository.save_parsed_request(
        session, parsed=parsed, file_name=file_name, raw_file=content
    )
    return repository.to_review_response(request)


async def _parse_request_file(file: UploadFile, mode: str = "basic"):
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
        parsed = await run_in_threadpool(parse_upload, filename=file_name, content=bytes(content))
        parsed.extraction_mode = mode
        if mode == "balanced":
            parsed = await run_in_threadpool(review_document, parsed)
    except ParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return file_name, bytes(content), parsed


@router.post("/requests", status_code=201)
async def create_request(
    payload: RequestCreate | None = None,
    session: AsyncSession = Depends(get_session),
) -> RequestState:
    request = await repository.create_draft_request(
        session, manual=payload is not None and payload.mode == "manual"
    )
    return request_state(request)


@router.post("/requests/manual", status_code=201)
async def create_manual_request(
    payload: ManualRequestCreate,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    request = await repository.create_manual_request(session, payload)
    return repository.to_review_response(request)


@router.get("/requests")
async def list_requests(session: AsyncSession = Depends(get_session)) -> list[RequestState]:
    requests = await repository.list_requests(session)
    matched = await repository.request_match_rates(session)
    return [
        request_state(
            request,
            match_rate=round(100 * matched[request.request_id] / len(request.items), 1)
            if request.request_id in matched and request.items else None,
        )
        for request in requests
    ]


@router.delete("/requests/{request_id}", status_code=204)
async def delete_request(request_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    try:
        deleted = await repository.delete_request(session, request_id)
    except repository.RequestCurrentlyMatching as exc:
        raise HTTPException(
            status_code=409,
            detail="Wait until matching finishes before deleting this request",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Request not found")
    return Response(status_code=204)


@router.get("/requests/{request_id}")
async def get_request(request_id: str, session: AsyncSession = Depends(get_session)) -> RequestState:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return request_state(request)


@router.post("/requests/{request_id}/file")
async def upload_request_file(
    http_request: Request,
    request_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status != "draft":
        raise HTTPException(status_code=409, detail="This request already has an uploaded file")
    mode = await extraction_mode(http_request, session)
    await session.commit()
    file_name, content, parsed = await _parse_request_file(file, mode)
    saved = await repository.save_parsed_request(
        session, parsed=parsed, file_name=file_name, raw_file=content, request_id=request_id
    )
    return repository.to_review_response(saved)


@router.get("/requests/{request_id}/review")
async def review(request_id: str, session: AsyncSession = Depends(get_session)) -> ReviewResponse:
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is not None:
        await repository.suggest_missing_item_domains(session, request)
        return repository.to_review_response(request)

    require_mock_request(request_id)
    return fixtures.review_response()


@router.post("/requests/{request_id}/items", status_code=201)
async def add_manual_item(
    request_id: str,
    payload: ManualItemCreate,
    session: AsyncSession = Depends(get_session),
) -> ExtractedItem:
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status != "review":
        raise HTTPException(status_code=409, detail="Items can only be added during review")
    item = await repository.add_manual_item(session, request, payload)
    return repository.to_extracted_item(item)


@router.delete("/requests/{request_id}/items/{item_id}", status_code=204)
async def remove_manual_item(
    request_id: str,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    item = next((item for item in request.items if item.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if request.workflow_status != "review":
        raise HTTPException(status_code=409, detail="Review is locked after matching starts")
    if not item.manual:
        raise HTTPException(status_code=409, detail="Only manual items can be removed")
    await session.delete(item)
    await session.commit()
    return Response(status_code=204)


@router.patch("/requests/{request_id}/items/{item_id}")
async def update_item(
    request_id: str,
    item_id: int,
    payload: ItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> ExtractedItem:
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is not None:
        if not any(item.id == item_id for item in request.items):
            raise HTTPException(status_code=404, detail="Item not found")
        if request.workflow_status != "review":
            raise HTTPException(status_code=409, detail="Review is locked after matching starts")
        update = payload.model_dump(exclude_unset=True)
        item = next(item for item in request.items if item.id == item_id)
        if item.manual:
            # Keep manual items complete when editing them, just as on creation.
            try:
                ManualItemCreate.model_validate(
                    {
                        **repository.to_extracted_item(item).model_dump(),
                        **update,
                    }
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Manual items require a name, positive quantity and product type",
                ) from exc
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
    request = await repository.get_request_by_id(session, request_id, lock=True)
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
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is not None:
        if request.workflow_status == "draft":
            raise HTTPException(status_code=409, detail="Upload a file before editing partner details")
        updated = await repository.update_partner(session, request_id, payload)
        return repository.to_partner_details(updated)

    require_mock_request(request_id)
    return PartnerDetails(**payload.model_dump(exclude={"requestId"}), requestId=request_id, confirmed=False)


@router.post("/requests/{request_id}/partner/confirm")
async def confirm_partner(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> PartnerDetails:
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is not None:
        if request.workflow_status == "draft":
            raise HTTPException(status_code=409, detail="Upload a file before confirming partner details")
        updated = await repository.confirm_partner(session, request_id)
        return repository.to_partner_details(updated)

    require_mock_request(request_id)
    return fixtures.review_response().partner.model_copy(update={"confirmed": True})


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

    request = await repository.get_request_by_id(session, request_id, lock=True)
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
    request = await repository.get_request_by_id(session, request_id, lock=True)
    if request is None:
        require_mock_request(request_id)
        response.status_code = 200
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
    if request.workflow_status in {
        "matching_queued",
        "matching",
        "match_review",
        "complete",
        "finalized",
    }:
        state = await matching_state(session, request_id)
        assert state is not None
        return state
    if request.workflow_status not in {"review", "matching_failed"}:
        raise HTTPException(
            status_code=409, detail="Upload a file or create a manual request before matching"
        )
    await repository.suggest_missing_item_domains(session, request, commit=False)
    if not request.items or any(
        item.status != "verified" or not item.domain for item in request.items
    ):
        raise HTTPException(
            status_code=422, detail="Verify and classify every item before matching"
        )
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


@router.post("/requests/{request_id}/matching/auto-select")
async def auto_select_matching(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> RequestMatchingState:
    """Apply the current conservative default to existing, undecided match runs."""
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status in {"match_review", "complete"}:
        for item in request.items:
            await auto_select_item(session, item)
        undecided = await session.scalar(
            text("""SELECT COUNT(*) FROM request_items ri WHERE ri.request_id = :id
                    AND (ri.current_match_run_id IS NULL OR NOT EXISTS
                         (SELECT 1 FROM match_decisions md
                          WHERE md.match_run_id = ri.current_match_run_id))"""),
            {"id": request_id},
        )
        if undecided == 0 and request.items:
            request.workflow_status = "complete"
            await session.commit()
    state = await matching_state(session, request_id)
    assert state is not None
    return state


@router.post("/requests/{request_id}/finalize")
async def finalize_request(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> RequestState:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status not in {"complete", "finalized"}:
        raise HTTPException(status_code=409, detail="Decide every matched item before finalizing")
    undecided = await session.scalar(
        text("""SELECT COUNT(*) FROM request_items ri WHERE ri.request_id = :id
                AND (ri.match_status != 'completed' OR ri.current_match_run_id IS NULL
                     OR NOT EXISTS (SELECT 1 FROM match_decisions md
                                    WHERE md.match_run_id = ri.current_match_run_id))"""),
        {"id": request_id},
    )
    if not request.items or undecided:
        raise HTTPException(status_code=409, detail="Decide every matched item before finalizing")
    request.workflow_status = "finalized"
    await session.commit()
    return request_state(request)


@router.post("/requests/{request_id}/reopen-matching")
async def reopen_matching(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> RequestState:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status == "finalized":
        request.workflow_status = "complete"
        await session.commit()
    return request_state(request)


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
    if request.workflow_status not in {
        "matching_queued", "matching", "matching_failed", "match_review", "complete", "finalized"
    }:
        raise HTTPException(status_code=409, detail="Matching has not started")
    item = next((item for item in request.items if item.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.match_status != "completed" or item.current_match_run_id is None:
        raise HTTPException(status_code=409, detail="This item has not finished matching")
    await session.execute(
        text("SELECT id FROM request_items WHERE id = :id FOR UPDATE"), {"id": item_id}
    )
    service = get_matching_service(session)
    run = await service.get_run(item.current_match_run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="Match run is unavailable")
    candidate = next((candidate for candidate in run.candidates if candidate.candidate_id == payload.candidateId), None)
    if not payload.noMatch and candidate is None:
        raise HTTPException(status_code=422, detail="Choose a candidate or No match")
    if payload.noMatch and payload.candidateId is not None:
        raise HTTPException(status_code=422, detail="No match cannot include a candidate")
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
                AND (ri.match_status != 'completed' OR ri.current_match_run_id IS NULL
                     OR NOT EXISTS (SELECT 1 FROM match_decisions md
                                    WHERE md.match_run_id = ri.current_match_run_id))"""),
        {"id": request_id},
    )
    if undecided == 0 and request.workflow_status != "finalized":
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


async def _saved_summary(session: AsyncSession, request) -> dict:
    if request.workflow_status not in {"complete", "finalized"}:
        raise HTTPException(status_code=409, detail="Decide every matched item before summary")
    state = await matching_state(session, request.request_id)
    assert state is not None
    source_items = {item.id: item for item in request.items}
    items = []
    for line in state.lines:
        candidate = next(
            (candidate for candidate in line.candidates
             if candidate["candidate_id"] == str(line.selectedCandidateId)),
            None,
        )
        source = source_items[line.itemId]
        items.append({
            "itemId": line.itemId,
            "sourceRow": (source.source_reference.row
                          if source.source_reference and source.source_reference.row > 0 else None),
            "requestedItemNumber": source.item_number,
            "requested": line.name,
            "quantity": line.quantity,
            "unit": line.unit,
            "desiredShelfLife": source.shelf_life,
            "notes": source.notes,
            "domain": line.domain,
            "decision": line.decisionType,
            "itemNumber": candidate["item_number"] if candidate else None,
            "candidateType": candidate["candidate_type"] if candidate else None,
            "supplier": candidate.get("supplier") if candidate else None,
            "price": candidate.get("price") if candidate else None,
            "currency": candidate.get("currency") if candidate else None,
            "priceBasis": candidate.get("price_basis") if candidate else None,
            "unitPrice": candidate.get("unit_price") if candidate else None,
            "unitPriceUnit": candidate.get("unit_price_unit") if candidate else None,
            "offerValidUntil": candidate.get("offer_valid_until") if candidate else None,
            "offerDate": candidate.get("offer_date") if candidate else None,
            "product": candidate["descriptions"][0] if candidate else None,
            "availability": candidate["availability_status"] if candidate else None,
            "availableQuantity": candidate.get("available_quantity") if candidate else None,
            "requiredStockQuantity": candidate.get("required_stock_quantity") if candidate else None,
            "stockUnit": candidate.get("stock_unit") if candidate else None,
            "rankingScore": candidate["score_components"].get("ranking_score") if candidate else None,
            "warnings": candidate["warnings"] if candidate else [],
            "retrievalMethods": [evidence["retriever"] for evidence in candidate["retrieval_evidence"]]
            if candidate else [],
            "provenance": candidate["provenance"] if candidate else [],
        })
    return {
        "requestId": request.request_id,
        "status": request.workflow_status,
        "sourceFile": request.source_file_name,
        "partner": request.partner,
        "partnerConfirmed": request.confirmed,
        "region": request.region,
        "contact": request.contact,
        "requestDate": request.request_date,
        "items": items,
        "matchedCount": sum(item["decision"] != "no_match" for item in items),
        "unmatchedCount": sum(item["decision"] == "no_match" for item in items),
    }


@router.get("/requests/{request_id}/summary")
async def summary(request_id: str, session: AsyncSession = Depends(get_session)) -> dict | SummaryResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        require_mock_request(request_id)
        return fixtures.summary_response()
    return await _saved_summary(session, request)


@router.get("/requests/{request_id}/results.xlsx")
async def download_matched_results(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    results = await _saved_summary(session, request)
    return Response(
        content=build_matched_results_workbook(results),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{results_filename(request_id)}"'},
    )


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


@router.post("/requests/{request_id}/ai-review")
async def ai_review(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> ReviewResponse:
    request = await repository.get_request_by_id(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.workflow_status != "review":
        raise HTTPException(status_code=409, detail="AI review is only available during review")
    if not request.raw_file:
        raise HTTPException(
            status_code=422, detail="The original file is unavailable; re-upload it for AI review"
        )
    document = repository.review_document_from_request(request)
    content = request.raw_file
    file_name = request.source_file_name
    table_mappings = request.table_mappings
    before = fingerprint(content, document)
    cached = request.ai_review or {}
    if (
        cached.get("fingerprint") == before
        and cached.get("summary", {}).get("status") == "completed"
    ):
        return repository.to_review_response(request)
    # Release the read transaction during provider work so edits and matching can proceed.
    await session.commit()
    await run_in_threadpool(fill_legacy_sources, document, file_name, content, table_mappings)
    await run_in_threadpool(review_document, document)
    current = await repository.get_request_by_id(session, request_id, lock=True)
    if (
        current is None
        or current.workflow_status != "review"
        or fingerprint(current.raw_file or b"", repository.review_document_from_request(current))
        != before
    ):
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Request changed during AI review. Reload and try again."
        )
    repository.apply_ai_review(current, document)
    await session.commit()
    return repository.to_review_response(current)
