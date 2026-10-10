from unittest.mock import AsyncMock

import pytest

from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
)
from app.matching.auto_select import automatic_candidate
from app.matching.constraints.engine import AttributeRule, load_default_policy
from app.matching.contracts import AttributeValue, MatchRequestV1, ProductDomain, RuleOutcome
from app.matching.domain import RetrievalHit
from app.matching.service import MatchingService
from tests.matching.factories import historical_offer, item, line


def medicine(key, name, **kwargs):
    return item(key, name, **kwargs).model_copy(
        update={"domain": ProductDomain.MEDICINE, "attributes": {}}
    )


async def run(products, *, scores=None, cutoff=0, policy=None, attributes=None, offers=()):
    vectors = AsyncMock()
    vectors.search.return_value = [
        RetrievalHit(key, "vector", rank, value)
        for rank, (key, value) in enumerate((scores or {}).items(), 1)
    ]
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(products),
        history_repository=InMemoryHistoryRepository(list(offers)),
        run_repository=InMemoryMatchRunRepository(),
        policy=policy or load_default_policy(),
        vector_repository=vectors,
        min_semantic_score=cutoff,
    )
    inquiry = line(description="Ibuprofen 200 mg tablets").model_copy(
        update={
            "domain": ProductDomain.MEDICINE,
            "attributes": attributes or {},
        }
    )
    result = await service.match(
        MatchRequestV1(inquiry_line=inquiry, query_embedding=(1.0, 0.0), embedding_model_id="test")
    )
    saved = await service.get_run(result.match_run_id)
    assert saved.candidates == result.candidates
    return result.candidates


async def test_confirmed_candidates_suppress_higher_scoring_fallbacks():
    candidates = await run(
        [
            medicine("exact", "Ibuprofen 200 mg tablets"),
            medicine("typo", "Ibuprofenn 200 mg tablets"),
        ],
        scores={"typo": 0.99, "exact": 0.8},
    )
    assert [candidate.item_number for candidate in candidates] == ["exact"]
    assert "ingredient_fallback" not in candidates[0].score_components


async def test_only_unconfirmed_candidates_are_restored_with_review_and_cannot_autoselect():
    candidates = await run([medicine("typo", "Ibuprofenn 200 mg tablets")])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.rank == 1
    assert candidate.score_components["ingredient_fallback"] == 1
    assert candidate.review_status is RuleOutcome.REVIEW
    assert not any(check.outcome is RuleOutcome.EXCLUDE for check in candidate.constraints)
    assert automatic_candidate("Ibuprofenn 200 mg tablets", "typo", candidates) is None


@pytest.mark.parametrize("cutoff,expected", [(0.65, ["typo"]), (0.95, [])])
async def test_fallback_selection_occurs_after_semantic_cutoff(cutoff, expected):
    candidates = await run(
        [
            medicine("exact", "Ibuprofen 200 mg tablets"),
            medicine("typo", "Ibuprofenn 200 mg tablets"),
        ],
        scores={"exact": 0.6, "typo": 0.9},
        cutoff=cutoff,
    )
    assert [candidate.item_number for candidate in candidates] == expected


async def test_fallback_never_restores_catalog_restrictions_or_other_constraint_exclusions():
    assert await run([medicine("blocked", "Ibuprofenn 200 mg tablets", quality_blocked=True)]) == ()
    policy = load_default_policy().model_copy(
        update={
            "attribute_rules": {
                "strength": AttributeRule(on_missing=RuleOutcome.EXCLUDE),
            }
        }
    )
    assert (
        await run(
            [medicine("typo", "Ibuprofenn 200 mg tablets")],
            policy=policy,
            attributes={"strength": AttributeValue(value="200 mg")},
        )
        == ()
    )


async def test_confirmed_historical_offer_suppresses_catalog_fallback():
    offer = historical_offer("unused").model_copy(
        update={
            "item_number": None,
            "domain": ProductDomain.MEDICINE,
            "offered_description": "Ibuprofen 200 mg tablets",
        }
    )
    candidates = await run([medicine("typo", "Ibuprofenn 200 mg tablets")], offers=[offer])
    assert len(candidates) == 1 and candidates[0].item_number is None
    assert "ingredient_fallback" not in candidates[0].score_components
