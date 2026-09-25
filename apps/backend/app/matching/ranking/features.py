"""Inspectable score components; none of these values is a confidence probability."""

from __future__ import annotations

from difflib import SequenceMatcher

from app.matching.contracts import RuleOutcome
from app.matching.domain import CandidateState
from app.matching.representation import normalize_text


def calculate_score_components(candidate: CandidateState) -> dict[str, float]:
    components: dict[str, float] = {"rrf": candidate.fused_score}
    for hit in candidate.evidence:
        if hit.score is not None:
            components[hit.retriever] = max(hit.score, components.get(hit.retriever, float("-inf")))
        if hit.retriever == "exact":
            components["exact_reference"] = 1.0

    attribute_results = [result for result in candidate.constraints if result.attribute]
    comparable = [
        result for result in attribute_results if result.outcome not in {RuleOutcome.UNKNOWN}
    ]
    if comparable:
        matches = sum(result.outcome is RuleOutcome.PASS for result in comparable)
        components["attribute_match_ratio"] = matches / len(comparable)
    return components


def description_similarity(requested: str, descriptions: tuple[str, ...]) -> float:
    """Direct normalized name similarity, 0..1; not a confidence probability."""
    name = normalize_text(requested)
    if not name:
        return 0.0
    return max(
        (SequenceMatcher(None, name, normalize_text(description), autojunk=False).ratio()
         for description in descriptions),
        default=0.0,
    )
