"""API for already-normalized SharePoint offers; extraction remains external."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.offers.contracts import (
    NormalizedOfferUpsertV1,
    OfferArchiveRequestV1,
    OfferRecordV1,
    SharePointOfferFileRecordV1,
    SharePointOfferFileUpsertV1,
)
from app.offers.files import SharePointOfferFileService
from app.offers.service import OfferRepositoryService

router = APIRouter(prefix="/api/v1/offers", tags=["offers"])
file_router = APIRouter(prefix="/api/v1/sharepoint-offer-files", tags=["offers"])


def get_offer_service(session: AsyncSession = Depends(get_session)) -> OfferRepositoryService:
    return OfferRepositoryService(session)


def get_offer_file_service(
    session: AsyncSession = Depends(get_session),
) -> SharePointOfferFileService:
    return SharePointOfferFileService(session)


@router.put("/{external_id}", response_model=OfferRecordV1)
async def upsert_offer(
    external_id: str,
    payload: NormalizedOfferUpsertV1,
    service: OfferRepositoryService = Depends(get_offer_service),
) -> OfferRecordV1:
    return await service.upsert(external_id, payload)


@router.post("/{external_id}/archive", response_model=OfferRecordV1)
async def archive_offer(
    external_id: str,
    payload: OfferArchiveRequestV1,
    service: OfferRepositoryService = Depends(get_offer_service),
) -> OfferRecordV1:
    try:
        return await service.archive(
            external_id,
            source_version=payload.source_version,
            archived_at=payload.archived_at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[OfferRecordV1], status_code=status.HTTP_200_OK)
async def list_offers(
    active_only: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
    service: OfferRepositoryService = Depends(get_offer_service),
) -> list[OfferRecordV1]:
    return await service.list_current(active_only=active_only, limit=limit)


@file_router.put("/{external_id}", response_model=SharePointOfferFileRecordV1)
async def upsert_sharepoint_offer_file(
    external_id: str,
    payload: SharePointOfferFileUpsertV1,
    service: SharePointOfferFileService = Depends(get_offer_file_service),
) -> SharePointOfferFileRecordV1:
    return await service.upsert(external_id, payload)


@file_router.post("/{external_id}/archive", response_model=SharePointOfferFileRecordV1)
async def archive_sharepoint_offer_file(
    external_id: str,
    payload: OfferArchiveRequestV1,
    service: SharePointOfferFileService = Depends(get_offer_file_service),
) -> SharePointOfferFileRecordV1:
    try:
        return await service.archive(external_id, archived_at=payload.archived_at)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@file_router.get("", response_model=list[SharePointOfferFileRecordV1])
async def list_sharepoint_offer_files(
    active_only: bool = True,
    needs_extraction: bool = False,
    limit: int = Query(default=500, ge=1, le=2000),
    service: SharePointOfferFileService = Depends(get_offer_file_service),
) -> list[SharePointOfferFileRecordV1]:
    return await service.list_current(
        active_only=active_only,
        needs_extraction=needs_extraction,
        limit=limit,
    )
