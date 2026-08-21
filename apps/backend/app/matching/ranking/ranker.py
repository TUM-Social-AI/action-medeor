"""Lexicographic ranking that cannot trade safety for price or stock."""

from __future__ import annotations

from app.matching.contracts import AvailabilityStatus, RuleOutcome
from app.matching.domain import CandidateState
from app.matching.ranking.features import calculate_score_components

AVAILABILITY_ORDER = {
    AvailabilityStatus.ON_HAND_SUFFICIENT: 0,
    AvailabilityStatus.ON_HAND_PARTIAL: 1,
    AvailabilityStatus.PROCUREMENT_INDICATED: 2,
    AvailabilityStatus.UNKNOWN: 3,
    AvailabilityStatus.NOT_ALLOWED: 4,
}


def rank_candidates(
    candidates: list[CandidateState],
    availability: dict[str, AvailabilityStatus],
) -> list[CandidateState]:
    for candidate in candidates:
        candidate.score_components = calculate_score_components(candidate)

    eligible = [
        candidate for candidate in candidates if candidate.review_status is not RuleOutcome.EXCLUDE
    ]

    def sort_key(candidate: CandidateState) -> tuple[object, ...]:
        components = candidate.score_components
        review_order = 0 if candidate.review_status is RuleOutcome.PASS else 1
        exact_order = -components.get("exact_reference", 0.0)
        attribute_order = -components.get("attribute_match_ratio", -1.0)
        fused_order = -candidate.fused_score
        availability_order = AVAILABILITY_ORDER[availability[candidate.item.item_number]]
        return (
            review_order,
            exact_order,
            attribute_order,
            fused_order,
            availability_order,
            candidate.item.item_number,
        )

    return sorted(eligible, key=sort_key)
