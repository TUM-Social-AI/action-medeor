"""Automatic defaults for saved request matches.

Name similarity is a text score, not a calibrated confidence probability.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RequestItemRow
from app.matching.api import get_matching_service
from app.matching.contracts import (
    AvailabilityStatus,
    DecisionType,
    MatchCandidateV1,
    MatchDecisionRequestV1,
    RuleOutcome,
)
from app.matching.ranking.features import description_similarity
from app.matching.representation import normalize_text

MIN_NAME_SIMILARITY = 0.78
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_FORM_ALIASES = {
    "tablet": "tablet", "tablets": "tablet", "tabs": "tablet", "tab": "tablet",
    "capsule": "capsule", "capsules": "capsule", "caps": "capsule", "cap": "capsule",
    "syrup": "syrup", "suspension": "suspension", "solution": "solution",
    "injection": "injection", "infusion": "infusion", "cream": "cream", "ointment": "ointment",
    "drops": "drops", "suppository": "suppository", "powder": "powder",
}


def _numbers_compatible(requested: str, candidate: MatchCandidateV1) -> bool:
    numbers = Counter(_NUMBER.findall(normalize_text(requested)))
    return any(
        not (numbers - Counter(_NUMBER.findall(normalize_text(description))))
        for description in candidate.descriptions
    )


def _form(value: str) -> str | None:
    words = _WORD.findall(normalize_text(value))
    return next((_FORM_ALIASES[word] for word in words if word in _FORM_ALIASES), None)


def _form_compatible(requested: str, candidate: MatchCandidateV1) -> bool:
    requested_form = _form(requested)
    return not requested_form or any(
        _form(description) in {None, requested_form} for description in candidate.descriptions
    )


def automatic_candidate(
    requested_name: str,
    requested_item_number: str | None,
    candidates: tuple[MatchCandidateV1, ...],
) -> MatchCandidateV1 | None:
    if not candidates:
        return None
    best = candidates[0]
    if (
        best.rank != 1
        or best.review_status is not RuleOutcome.PASS
        or best.availability_status is AvailabilityStatus.NOT_ALLOWED
    ):
        return None
    if requested_item_number and requested_item_number.strip().casefold() == best.item_number.casefold():
        return best
    similarity = description_similarity(requested_name, best.descriptions)
    return best if (
        similarity >= MIN_NAME_SIMILARITY
        and _numbers_compatible(requested_name, best)
        and _form_compatible(requested_name, best)
    ) else None


async def auto_select_item(session: AsyncSession, item: RequestItemRow) -> bool:
    """Save one default only when this run has no human or automatic decision yet."""
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
    candidate = automatic_candidate(item.name, item.item_number, run.candidates)
    if candidate is None:
        return False
    await service.save_decision(
        MatchDecisionRequestV1(
            match_run_id=run.match_run_id,
            inquiry_line_id=str(item.id),
            decision_type=DecisionType.ACCEPT_SUGGESTION,
            candidate_id=candidate.candidate_id,
            selected_item_number=candidate.item_number,
            actor="automatic",
        )
    )
    return True
