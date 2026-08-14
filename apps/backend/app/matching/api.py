"""HTTP boundary for matching, intentionally independent of the Figma UI branch."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.matching.adapters.persistence import (
    PgVectorRepository,
    PostgresCatalogRepository,
    PostgresHistoryRepository,
    PostgresMatchRunRepository,
)
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import (
    MatchDecisionRequestV1,
    MatchDecisionResponseV1,
    MatchRequestV1,
    MatchRunResponseV1,
)
from app.matching.service import MatchingService

router = APIRouter(prefix="/api/v1", tags=["matching"])


def get_matching_service(session: AsyncSession = Depends(get_session)) -> MatchingService:
    return MatchingService(
        catalog_repository=PostgresCatalogRepository(session),
        history_repository=PostgresHistoryRepository(session),
        run_repository=PostgresMatchRunRepository(session),
        vector_repository=PgVectorRepository(session),
        policy=load_default_policy(),
    )


@router.post(
    "/match-runs",
    response_model=MatchRunResponseV1,
    status_code=status.HTTP_201_CREATED,
)
async def create_match_run(
    request: MatchRequestV1,
    service: MatchingService = Depends(get_matching_service),
) -> MatchRunResponseV1:
    try:
        return await service.match(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/match-runs/{match_run_id}", response_model=MatchRunResponseV1)
async def get_match_run(
    match_run_id: UUID,
    service: MatchingService = Depends(get_matching_service),
) -> MatchRunResponseV1:
    result = await service.get_run(match_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Match run not found")
    return result


@router.post(
    "/match-decisions",
    response_model=MatchDecisionResponseV1,
    status_code=status.HTTP_201_CREATED,
)
async def create_match_decision(
    decision: MatchDecisionRequestV1,
    service: MatchingService = Depends(get_matching_service),
) -> MatchDecisionResponseV1:
    try:
        return await service.save_decision(decision)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
