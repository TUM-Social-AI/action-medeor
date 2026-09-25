"""Saved request and matching state shared by the API and background worker."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import MatchingLineState, RequestMatchingState, RequestState
from app.db.models import ImportRequestRow, RequestItemRow
from app.db.repository import get_request_by_id
from app.matching.contracts import (
    AttributeValue,
    InquiryLineV1,
    MatchRunResponseV1,
    QuantityValue,
    SourceReferenceV1,
    SourceType,
)
from app.matching.ranking.features import description_similarity
from app.matching.ranking.ranker import calculate_ranking_scores


def request_state(request: ImportRequestRow, match_rate: float | None = None) -> RequestState:
    return RequestState(
        requestId=request.request_id,
        status=request.workflow_status,
        sourceFile=request.source_file_name or None,
        partner=request.partner,
        region=request.region,
        itemCount=len(request.items),
        matchRate=match_rate,
        createdAt=request.created_at.isoformat() if request.created_at else "",
    )


def to_inquiry_line(request: ImportRequestRow, item: RequestItemRow) -> InquiryLineV1:
    if item.domain not in {"medicine", "equipment"}:
        raise ValueError(f"Item {item.id} needs a medicine/equipment type")
    reference = item.source_reference
    suffix = request.source_file_name.lower().rsplit(".", 1)[-1]
    source_type = SourceType.EXCEL if suffix in {"xlsx", "xls"} else SourceType.OTHER
    captured = request.created_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return InquiryLineV1(
        inquiry_id=request.request_id,
        line_id=str(item.id),
        domain=item.domain,
        raw_description=item.name,
        requested_item_number=item.item_number or None,
        quantity=QuantityValue(value=item.quantity, unit=item.unit or None),
        attributes={
            key: AttributeValue(value=value)
            for key, value in (item.attributes or {}).items()
            if value.strip()
        },
        partner_id=request.partner or None,
        urgency=item.priority,
        desired_shelf_life=item.shelf_life or None,
        special_instructions=(item.notes,) if item.notes else (),
        source=SourceReferenceV1(
            source_type=source_type,
            document_id=request.request_id,
            captured_at=captured,
            row=reference.row if reference and reference.row > 0 else None,
            locator={
                "file_name": request.source_file_name,
                "page": reference.page if reference else None,
                "excerpt": reference.excerpt if reference else None,
            },
        ),
    )


async def latest_snapshot_id(session: AsyncSession) -> UUID | None:
    return await session.scalar(
        text("""SELECT combined_source_snapshot_id FROM catalog_imports
                WHERE status IN ('completed', 'completed_with_warnings')
                ORDER BY import_sequence DESC LIMIT 1""")
    )


async def matching_state(session: AsyncSession, request_id: str) -> RequestMatchingState | None:
    request = await get_request_by_id(session, request_id)
    if request is None:
        return None
    lines: list[MatchingLineState] = []
    for item in request.items:
        candidates: list[dict] = []
        selected_candidate_id = None
        decision_type = None
        if item.current_match_run_id:
            payload = await session.scalar(
                text("SELECT result_payload FROM match_runs WHERE id = :id"),
                {"id": item.current_match_run_id},
            )
            if payload:
                run = MatchRunResponseV1.model_validate(payload)
                candidates = [candidate.model_dump(mode="json") for candidate in run.candidates]
                # Runs saved before ranking scores existed retain their original order.
                # Reconstruct the same sort key from their saved matching evidence.
                scores = calculate_ranking_scores([
                    (
                        candidate.item_number,
                        candidate.review_status,
                        candidate.availability_status,
                        candidate.score_components,
                    )
                    for candidate in run.candidates
                ])
                for candidate in candidates:
                    candidate["score_components"].setdefault(
                        "name_similarity",
                        description_similarity(item.name, tuple(candidate["descriptions"])),
                    )
                    # Preserve the exact normalized score used by new runs, which
                    # includes candidates beyond the returned top-k. Older runs
                    # need their score reconstructed from their saved candidates.
                    if candidate["score_components"].get("ranking_score_normalized") != 1.0:
                        candidate["score_components"]["ranking_score"] = scores[
                            candidate["item_number"]
                        ]
                        candidate["score_components"]["ranking_score_normalized"] = 1.0
            decision = (
                await session.execute(
                    text("""SELECT candidate_id, decision_type FROM match_decisions
                            WHERE match_run_id = :run_id
                            ORDER BY created_at DESC, id DESC LIMIT 1"""),
                    {"run_id": item.current_match_run_id},
                )
            ).mappings().first()
            if decision:
                selected_candidate_id = decision["candidate_id"]
                decision_type = decision["decision_type"]
        if item.domain:
            lines.append(
                MatchingLineState(
                    itemId=item.id,
                    name=item.name,
                    quantity=item.quantity,
                    unit=item.unit,
                    priority=item.priority,
                    domain=item.domain,
                    status=item.match_status,
                    error=item.match_error,
                    runId=item.current_match_run_id,
                    candidates=candidates,
                    selectedCandidateId=selected_candidate_id,
                    decisionType=decision_type,
                )
            )
    return RequestMatchingState(
        requestId=request_id,
        status=request.workflow_status,
        completed=sum(item.match_status == "completed" for item in request.items),
        total=len(request.items),
        lines=lines,
    )
