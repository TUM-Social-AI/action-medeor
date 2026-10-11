from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

import app.matching.auto_select as auto_select
from app.matching.auto_select import automatic_candidate
from app.matching.contracts import (
    AvailabilityStatus,
    CandidateType,
    ConstraintResult,
    DecisionType,
    MatchCandidateV1,
    PackagingResult,
    ProductDomain,
    RuleOutcome,
)


def candidate(score, *, ingredient=None, review=RuleOutcome.PASS, rank=1):
    return MatchCandidateV1(
        candidate_id=uuid4(), item_number="410001", rank=rank,
        descriptions=("Paracetamol 125 mg/5 ml syrup",), review_status=review,
        availability_status=AvailabilityStatus.UNKNOWN, retrieval_evidence=(),
        score_components={"search_similarity": score},
        constraints=(ConstraintResult(
            code=f"medicine_active_ingredient_{ingredient}",
            outcome=RuleOutcome.PASS if ingredient == "match" else RuleOutcome.REVIEW,
            message="Ingredient check",
        ),) if ingredient else (),
        packaging=PackagingResult(status="unknown"), warnings=(), provenance=(),
    )


@pytest.mark.parametrize("score,selected", [(49, False), (50, False), (50.01, True), (100, True)])
def test_medicine_requires_score_strictly_above_50(score, selected):
    best = candidate(score, ingredient="match")
    assert automatic_candidate(ProductDomain.MEDICINE, (best,)) == (best if selected else None)


@pytest.mark.parametrize("ingredient", [None, "mismatch", "unverified"])
def test_medicine_requires_confirmed_ingredient_even_with_high_score(ingredient):
    best = candidate(100, ingredient=ingredient)
    assert automatic_candidate(ProductDomain.MEDICINE, (best,)) is None


@pytest.mark.parametrize("score,selected", [(49, False), (50, False), (50.01, True), (100, True)])
def test_equipment_requires_score_strictly_above_50(score, selected):
    best = candidate(score)
    assert automatic_candidate(ProductDomain.EQUIPMENT, (best,)) == (best if selected else None)


def test_only_top_ranked_candidate_is_selected():
    best = candidate(70)
    second = candidate(60, rank=2)
    assert automatic_candidate(ProductDomain.EQUIPMENT, (best, second)) == best
    assert automatic_candidate(ProductDomain.EQUIPMENT, (second,)) is None


def test_review_findings_do_not_prevent_matching_ingredient_selection():
    best = candidate(70, ingredient="match", review=RuleOutcome.REVIEW)
    assert automatic_candidate(ProductDomain.MEDICINE, (best,)) == best


@pytest.mark.parametrize("domain", list(ProductDomain))
def test_empty_results_have_no_selection(domain):
    assert automatic_candidate(domain, ()) is None


@pytest.mark.parametrize("domain", list(ProductDomain))
def test_supplier_offer_can_be_selected_using_the_same_rules(domain):
    best = candidate(70, ingredient="match").model_copy(update={
        "candidate_type": CandidateType.HISTORICAL_OFFER, "item_number": None,
    })
    assert automatic_candidate(domain, (best,)) == best


@pytest.mark.parametrize("updates", [
    {"review_status": RuleOutcome.EXCLUDE},
    {"availability_status": AvailabilityStatus.NOT_ALLOWED},
])
def test_disallowed_candidates_are_not_selected(updates):
    best = candidate(100, ingredient="match").model_copy(update=updates)
    assert automatic_candidate(ProductDomain.MEDICINE, (best,)) is None
    assert automatic_candidate(ProductDomain.EQUIPMENT, (best,)) is None


def test_ingredient_fallback_is_not_selected():
    best = candidate(100, ingredient="match").model_copy(update={
        "score_components": {"search_similarity": 100, "ingredient_fallback": 1.0},
    })
    assert automatic_candidate(ProductDomain.MEDICINE, (best,)) is None


def test_legacy_search_score_uses_retrieval_channels():
    best = candidate(0).model_copy(update={
        "score_components": {"lexical": 0.4, "vector": 0.8, "vector_weight": 2.0},
    })
    assert automatic_candidate(ProductDomain.EQUIPMENT, (best,)) == best


def test_name_similarity_and_normalized_ranking_do_not_replace_search_score():
    best = candidate(0).model_copy(update={
        "score_components": {"name_similarity": 1.0, "ranking_score": 100},
    })
    assert automatic_candidate(ProductDomain.EQUIPMENT, (best,)) is None


@pytest.mark.parametrize("domain,score,ingredient,selected", [
    (ProductDomain.MEDICINE, 51, "match", True),
    (ProductDomain.MEDICINE, 50, "match", False),
    (ProductDomain.MEDICINE, 99, "mismatch", False),
    (ProductDomain.MEDICINE, 99, "unverified", False),
    (ProductDomain.EQUIPMENT, 51, None, True),
    (ProductDomain.EQUIPMENT, 50, None, False),
    (ProductDomain.EQUIPMENT, None, None, False),
])
async def test_worker_saves_selection_or_no_match(monkeypatch, domain, score, ingredient, selected):
    best = candidate(score, ingredient=ingredient) if score is not None else None
    run = SimpleNamespace(match_run_id=uuid4(), candidates=(best,) if best else ())
    service = SimpleNamespace(get_run=AsyncMock(return_value=run), save_decision=AsyncMock())
    monkeypatch.setattr(auto_select, "get_matching_service", lambda session: service)
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=None))
    item = SimpleNamespace(
        id=1, domain=domain.value, current_match_run_id=run.match_run_id, match_status="completed",
        item_number="410001", name="Exact requested article",
    )
    assert await auto_select.auto_select_item(session, item)
    decision = service.save_decision.call_args.args[0]
    assert decision.decision_type == (
        DecisionType.ACCEPT_SUGGESTION if selected else DecisionType.NO_MATCH
    )
    assert decision.candidate_id == (best.candidate_id if selected else None)
    assert decision.selected_item_number == (best.item_number if selected else None)
    assert decision.actor == "automatic"
    assert decision.inquiry_line_id == str(item.id)


async def test_worker_preserves_existing_decisions(monkeypatch):
    service_factory = Mock()
    monkeypatch.setattr(auto_select, "get_matching_service", service_factory)
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=uuid4()))
    item = SimpleNamespace(current_match_run_id=uuid4(), match_status="completed", id=1)
    assert not await auto_select.auto_select_item(session, item)
    service_factory.assert_not_called()


@pytest.mark.parametrize("run_id,status", [
    (None, "completed"), (uuid4(), "running"), (uuid4(), "failed"),
])
async def test_worker_waits_for_completed_run(run_id, status):
    session = SimpleNamespace(execute=AsyncMock())
    item = SimpleNamespace(current_match_run_id=run_id, match_status=status)
    assert not await auto_select.auto_select_item(session, item)
    session.execute.assert_not_called()
