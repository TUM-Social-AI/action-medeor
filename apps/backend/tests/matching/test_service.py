from decimal import Decimal

import pytest

from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
    InMemoryVectorRepository,
)
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import (
    DecisionType,
    MatchDecisionRequestV1,
    MatchRequestV1,
    RuleOutcome,
)
from app.matching.service import MatchingService
from tests.matching.factories import historical_offer, item, line


@pytest.mark.asyncio
async def test_complete_hybrid_match_is_reproducible_and_excludes_inactive_item() -> None:
    correct = item("410001001", "Foley urinary catheter sterile CH18", on_hand=Decimal("80"))
    wrong_size = item(
        "410001002", "Foley urinary catheter sterile CH12", charriere=12, on_hand=Decimal("500")
    )
    inactive = item(
        "410001003", "Foley urinary catheter sterile CH18", active=False, on_hand=Decimal("500")
    )
    catalog = InMemoryCatalogRepository([wrong_size, inactive, correct])
    history = InMemoryHistoryRepository([historical_offer("410001003")])
    vectors = InMemoryVectorRepository()
    vectors.add(
        item_number="410001001",
        model_id="model-v1",
        domain=correct.domain,
        embedding=(1.0, 0.0),
    )
    vectors.add(
        item_number="410001002",
        model_id="model-v1",
        domain=correct.domain,
        embedding=(0.5, 0.5),
    )
    vectors.add(
        item_number="410001003",
        model_id="model-v1",
        domain=correct.domain,
        embedding=(1.0, 0.0),
    )
    runs = InMemoryMatchRunRepository()
    service = MatchingService(
        catalog_repository=catalog,
        history_repository=history,
        run_repository=runs,
        vector_repository=vectors,
        policy=load_default_policy(),
    )

    result = await service.match(
        MatchRequestV1(
            inquiry_line=line(),
            query_embedding=(1.0, 0.0),
            embedding_model_id="model-v1",
        )
    )

    assert [candidate.item_number for candidate in result.candidates] == [
        "410001001",
        "410001002",
    ]
    assert result.candidates[0].review_status is RuleOutcome.PASS
    assert result.candidates[1].review_status is RuleOutcome.REVIEW
    assert "410001003" not in {candidate.item_number for candidate in result.candidates}
    assert await service.get_run(result.match_run_id) == result

    decision = await service.save_decision(
        MatchDecisionRequestV1(
            match_run_id=result.match_run_id,
            inquiry_line_id="line-1",
            decision_type=DecisionType.ACCEPT_SUGGESTION,
            candidate_id=result.candidates[0].candidate_id,
            selected_item_number="410001001",
            offered_quantity=Decimal("60"),
            actor="tester",
        )
    )
    assert decision.match_run_id == result.match_run_id
    assert len(runs.decisions) == 1


@pytest.mark.asyncio
async def test_fallback_without_vectors_or_history_still_returns_lexical_candidates() -> None:
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18")]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=line()))
    assert result.candidates[0].item_number == "410001001"
    assert {evidence.retriever for evidence in result.candidates[0].retrieval_evidence} == {
        "lexical"
    }


@pytest.mark.asyncio
async def test_completed_run_may_return_no_candidate_instead_of_padding_top_ten() -> None:
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18", active=False)]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )

    result = await service.match(MatchRequestV1(inquiry_line=line()))

    assert result.candidates == ()


@pytest.mark.asyncio
async def test_suggested_decision_must_reference_an_exposed_candidate() -> None:
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(
            [item("410001001", "Foley urinary catheter sterile CH18")]
        ),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(),
    )
    result = await service.match(MatchRequestV1(inquiry_line=line()))

    with pytest.raises(ValueError, match="not part of the match run"):
        await service.save_decision(
            MatchDecisionRequestV1(
                match_run_id=result.match_run_id,
                inquiry_line_id=result.inquiry_line_id,
                decision_type=DecisionType.ACCEPT_SUGGESTION,
                selected_item_number="not-exposed",
            )
        )
