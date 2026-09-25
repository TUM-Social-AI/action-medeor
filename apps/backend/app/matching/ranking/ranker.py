"""Lexicographic ranking that cannot trade safety for price or stock."""

from __future__ import annotations

from collections.abc import Sequence

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


# Article number is the final deterministic tie-breaker. A mixed-radix score encodes
# the entire lexicographic policy without allowing a later criterion to outweigh an
# earlier one. Its magnitude depends on the candidate pool; it is not a probability.
RankingInput = tuple[str, RuleOutcome, AvailabilityStatus, dict[str, float]]


def calculate_ranking_scores(rows: Sequence[RankingInput]) -> dict[str, float]:
    if not rows:
        return {}

    attribute_values = sorted({components.get("attribute_match_ratio", -1.0) for _, _, _, components in rows})
    retrieval_values = sorted({components.get("rrf", 0.0) for _, _, _, components in rows})
    item_numbers = sorted({item_number for item_number, _, _, _ in rows}, reverse=True)
    attribute_level = {value: index for index, value in enumerate(attribute_values)}
    retrieval_level = {value: index for index, value in enumerate(retrieval_values)}
    item_level = {value: index for index, value in enumerate(item_numbers)}
    scores: dict[str, float] = {}
    for item_number, review_status, availability_status, components in rows:
        pass_level = int(review_status is RuleOutcome.PASS)
        exact_level = int(components.get("exact_reference", 0.0) > 0)
        attributes = attribute_level[components.get("attribute_match_ratio", -1.0)]
        retrieval = retrieval_level[components.get("rrf", 0.0)]
        availability = len(AVAILABILITY_ORDER) - 1 - AVAILABILITY_ORDER[availability_status]
        score = (
            ((((pass_level * 2 + exact_level) * len(attribute_values) + attributes)
              * len(retrieval_values) + retrieval)
             * len(AVAILABILITY_ORDER) + availability)
            * len(item_numbers) + item_level[item_number]
        )
        scores[item_number] = float(score)

    # The encoded policy key can vary greatly with the size of the candidate pool.
    # Normalize it before sorting so the score exposed to clients is consistently
    # 0..100 while retaining exactly the same order. A sole candidate gets 100.
    lowest = min(scores.values())
    spread = max(scores.values()) - lowest
    return {
        item_number: 100.0 if spread == 0 else 100.0 * (score - lowest) / spread
        for item_number, score in scores.items()
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
    scores = calculate_ranking_scores([
        (
            candidate.item.item_number,
            candidate.review_status,
            availability[candidate.item.item_number],
            candidate.score_components,
        )
        for candidate in eligible
    ])
    for candidate in eligible:
        candidate.score_components["ranking_score"] = scores[candidate.item.item_number]
        candidate.score_components["ranking_score_normalized"] = 1.0

    return sorted(eligible, key=lambda candidate: -candidate.score_components["ranking_score"])
