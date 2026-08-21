"""Validation for immutable human decisions.

There is deliberately no online weight update here. Decisions are evidence for
offline evaluation and later versioned learning-to-rank experiments.
"""

from app.matching.contracts import (
    DecisionType,
    MatchDecisionRequestV1,
    MatchRunResponseV1,
)


def validate_decision_against_run(
    decision: MatchDecisionRequestV1, run: MatchRunResponseV1
) -> None:
    if run.inquiry_line_id != decision.inquiry_line_id:
        raise ValueError("Decision inquiry line does not match the match run")

    if decision.decision_type not in {
        DecisionType.ACCEPT_SUGGESTION,
        DecisionType.SELECT_ALTERNATIVE,
    }:
        return

    matching_candidate = next(
        (
            candidate
            for candidate in run.candidates
            if candidate.item_number == decision.selected_item_number
            and (decision.candidate_id is None or candidate.candidate_id == decision.candidate_id)
        ),
        None,
    )
    if matching_candidate is None:
        raise ValueError("Selected candidate was not part of the match run")


__all__ = [
    "DecisionType",
    "MatchDecisionRequestV1",
    "validate_decision_against_run",
]
