"""Automatic defaults for saved request matches.

Search similarity is a retrieval score, not a calibrated confidence probability.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RequestItemRow
from app.matching.api import get_matching_service
from app.matching.contracts import (
    AvailabilityStatus,
    DecisionType,
    MatchCandidateV1,
    MatchDecisionRequestV1,
    ProductDomain,
    RuleOutcome,
)
from app.matching.ranking.features import search_similarity_components


def _has_confirmed_ingredient(candidate: MatchCandidateV1) -> bool:
    return candidate.score_components.get("ingredient_fallback") != 1.0 and any(
        check.code == "medicine_active_ingredient_match" and check.outcome is RuleOutcome.PASS
        for check in candidate.constraints
    )


def automatic_candidate(
    domain: ProductDomain,
    candidates: tuple[MatchCandidateV1, ...],
) -> MatchCandidateV1 | None:
    if not candidates:
        return None
    best = candidates[0]
    if (
        best.rank != 1
        or best.review_status is RuleOutcome.EXCLUDE
        or best.availability_status is AvailabilityStatus.NOT_ALLOWED
    ):
        return None
    score = best.score_components.get("search_similarity")
    if score is None:
        score = search_similarity_components(best.score_components).get("search_similarity", 0.0)
    if domain == ProductDomain.MEDICINE:
        return best if _has_confirmed_ingredient(best) and score > 50 else None
    if domain == ProductDomain.EQUIPMENT:
        return best if score > 50 else None
    return None


async def auto_select_item(session: AsyncSession, item: RequestItemRow) -> bool:
    """Save a default for an undecided run, leaving unconfirmed ingredients for review."""
    if item.current_match_run_id is None or item.match_status != "completed":
        return False
    await session.execute(
        text("SELECT id FROM request_items WHERE id = :id FOR UPDATE"), {"id": item.id}
    )
    existing = await session.scalar(
        text("SELECT id FROM match_decisions WHERE match_run_id = :run_id LIMIT 1"),
        {"run_id": item.current_match_run_id},
    )
    if existing is not None:
        return False

    service = get_matching_service(session)
    run = await service.get_run(item.current_match_run_id)
    if run is None:
        return False
    if (
        item.domain == ProductDomain.MEDICINE
        and run.candidates
        and not _has_confirmed_ingredient(run.candidates[0])
    ):
        return False
    candidate = automatic_candidate(item.domain, run.candidates)
    await service.save_decision(
        MatchDecisionRequestV1(
            match_run_id=run.match_run_id,
            inquiry_line_id=str(item.id),
            decision_type=DecisionType.ACCEPT_SUGGESTION if candidate else DecisionType.NO_MATCH,
            candidate_id=candidate.candidate_id if candidate else None,
            selected_item_number=candidate.item_number if candidate else None,
            actor="automatic",
        )
    )
    return True
