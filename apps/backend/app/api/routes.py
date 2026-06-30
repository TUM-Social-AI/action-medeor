from fastapi import APIRouter, HTTPException

from app.api import fixtures
from app.api.schemas import (
    ErpMatch,
    ExtractedItem,
    HomeResponse,
    ImportRequest,
    ItemUpdate,
    MatchSelection,
    MatchSelectionResponse,
    MatchingResponse,
    OfferResponse,
    PartnerDetails,
    PartnerUpdate,
    RecentImport,
    ReviewResponse,
    SummaryResponse,
    TrendsResponse,
)

router = APIRouter(prefix="/api")


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
async def create_import(payload: ImportRequest) -> ReviewResponse:
    expected_suffix = f".{payload.fileType}"
    if not payload.fileName.lower().endswith(expected_suffix):
        raise HTTPException(status_code=400, detail="File extension does not match file type")

    return fixtures.review_response()


@router.get("/requests/{request_id}/review")
async def review(request_id: str) -> ReviewResponse:
    require_mock_request(request_id)
    return fixtures.review_response()


@router.patch("/requests/{request_id}/items/{item_id}")
async def update_item(request_id: str, item_id: int, payload: ItemUpdate) -> ExtractedItem:
    require_mock_request(request_id)
    item = find_item(item_id)
    update = payload.model_dump(exclude_unset=True)
    return item.model_copy(update={**update, "status": "verified"})


@router.post("/requests/{request_id}/items/{item_id}/verify")
async def verify_item(request_id: str, item_id: int) -> ExtractedItem:
    require_mock_request(request_id)
    item = find_item(item_id)
    return item.model_copy(update={"status": "verified"})


@router.patch("/requests/{request_id}/partner")
async def update_partner(request_id: str, payload: PartnerUpdate) -> PartnerDetails:
    require_mock_request(request_id)
    return PartnerDetails(**payload.model_dump(), confirmed=True)


@router.post("/requests/{request_id}/matching")
async def start_matching(request_id: str) -> MatchingResponse:
    require_mock_request(request_id)
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
) -> MatchSelectionResponse:
    require_mock_request(request_id)
    find_match(item_id, payload.matchId)
    return MatchSelectionResponse(itemId=item_id, matchId=payload.matchId)


@router.get("/requests/{request_id}/summary")
async def summary(request_id: str) -> SummaryResponse:
    require_mock_request(request_id)
    return fixtures.summary_response()


@router.post("/requests/{request_id}/offer")
async def create_offer(request_id: str) -> OfferResponse:
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

