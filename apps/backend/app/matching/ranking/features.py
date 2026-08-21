"""Inspectable score components; none of these values is a confidence probability."""

from __future__ import annotations

from app.matching.contracts import RuleOutcome
from app.matching.domain import CandidateState


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
