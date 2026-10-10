"""Source-neutral relevance ranking; excluded candidates remain filtered."""

from __future__ import annotations

from collections.abc import Sequence

from app.matching.contracts import AvailabilityStatus, RuleOutcome
from app.matching.domain import CandidateState
from app.matching.ranking.features import calculate_score_components

RankingInput = tuple[str, RuleOutcome, AvailabilityStatus, dict[str, float]]


def calculate_ranking_scores(rows: Sequence[RankingInput]) -> dict[str, float]:
    """Rank all sources by retrieval relevance, independent of review and stock."""
    if not rows:
        return {}
    scores = {key: components.get("rrf", 0.0) for key, _, _, components in rows}
    lowest = min(scores.values())
    spread = max(scores.values()) - lowest
    return {
        key: 100.0 if spread == 0 else 100.0 * (score - lowest) / spread
        for key, score in scores.items()
    }


def availability_tie_break(status: AvailabilityStatus) -> int:
    """Prefer fulfillment coverage only when retrieval relevance is equal."""
    return {
        AvailabilityStatus.ON_HAND_SUFFICIENT: 0,
        AvailabilityStatus.ON_HAND_PARTIAL: 1,
        AvailabilityStatus.PROCUREMENT_INDICATED: 2,
        AvailabilityStatus.UNKNOWN: 3,
        AvailabilityStatus.NOT_ALLOWED: 4,
    }[status]


def rank_candidates(
    candidates: list[CandidateState],
    availability: dict[str, AvailabilityStatus],
) -> list[CandidateState]:
    for candidate in candidates:
        candidate.score_components = calculate_score_components(candidate)

    eligible = [
        candidate for candidate in candidates if candidate.review_status is not RuleOutcome.EXCLUDE
    ]
    scores = calculate_ranking_scores(
        [
            (
                candidate.item.item_number,
                candidate.review_status,
                availability[candidate.item.item_number],
                candidate.score_components,
            )
            for candidate in eligible
        ]
    )
    for candidate in eligible:
        candidate.score_components["ranking_score"] = scores[candidate.item.item_number]
        candidate.score_components["ranking_score_normalized"] = 1.0

    return sorted(eligible, key=lambda candidate: (
        -candidate.score_components["ranking_score"],
        availability_tie_break(availability[candidate.item.item_number]),
        candidate.item.item_number,
    ))
