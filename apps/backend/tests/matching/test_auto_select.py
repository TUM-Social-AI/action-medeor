from uuid import uuid4

from app.matching.auto_select import automatic_candidate
from app.matching.contracts import (
    AvailabilityStatus,
    MatchCandidateV1,
    PackagingResult,
    RuleOutcome,
)


def candidate(
    name: str,
    number: str,
    rank: int,
    *,
    review: RuleOutcome = RuleOutcome.PASS,
) -> MatchCandidateV1:
    return MatchCandidateV1(
        candidate_id=uuid4(),
        item_number=number,
        rank=rank,
        descriptions=(name,),
        review_status=review,
        availability_status=AvailabilityStatus.UNKNOWN,
        retrieval_evidence=(),
        score_components={},
        constraints=(),
        packaging=PackagingResult(status="unknown"),
        warnings=(),
        provenance=(),
    )


def test_exact_article_id_is_an_automatic_default() -> None:
    first = candidate("Sterile catheter CH18", "410001", 1)
    second = candidate("Sterile catheter CH12", "410002", 2)
    assert automatic_candidate("Catheter", "410001", (first, second)) == first
    assert automatic_candidate("Catheter", "410002", (first, second)) is None


def test_close_name_is_selected_without_a_lead_over_other_candidates() -> None:
    first = candidate("Paracetamol 125 mg/5 ml syrup 100 ml bottle", "410001", 1)
    second = candidate("Paracetamol 10 mg/ml solution for infusion", "410002", 2)
    assert automatic_candidate(
        "Paracetamol 125mg/5ml syrup 100ml bottle", None, (first, second)
    ) == first


def test_different_strength_or_form_is_never_automatically_selected() -> None:
    requested = "Paracetamol 125 mg/5 ml syrup 100 ml bottle"
    different_strength = candidate("Paracetamol 120 mg/5 ml syrup 100 ml bottle", "410001", 1)
    different_form = candidate("Paracetamol 125 mg/5 ml solution 100 ml bottle", "410002", 1)
    assert automatic_candidate(requested, None, (different_strength,)) is None
    assert automatic_candidate(requested, None, (different_form,)) is None


def test_relaxed_similarity_accepts_extra_descriptors_but_not_flagged_results() -> None:
    requested = "Sterile catheter CH18"
    first = candidate("Sterile urinary catheter CH18", "410001", 1)
    duplicate = candidate(requested, "410002", 2)
    flagged = candidate(requested, "410003", 1, review=RuleOutcome.REVIEW)
    assert automatic_candidate(requested, None, (first, duplicate)) == first
    assert automatic_candidate(requested, "410003", (flagged,)) is None
