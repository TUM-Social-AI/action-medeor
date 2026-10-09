from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
)
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import MatchRequestV1
from app.matching.domain import RetrievalHit
from app.matching.service import MatchingService
from tests.matching.factories import historical_offer, item, line


@pytest.mark.parametrize("cutoff,scores,expected", [
    (0.65, [0.64, 0.65, 0.8], ["c", "b"]),
    (0.65, [0.2, 0.5, 0.64], []),
    (0.65, [], []),
    (0, [], ["a", "b", "c"]),
])
@pytest.mark.parametrize("top_k", [1, 10])
async def test_semantic_cutoff_includes_boundary_and_handles_missing_scores(cutoff, scores, expected, top_k):
    products = [item(key, "Foley catheter sterile CH18") for key in ("a", "b", "c")]
    vectors = AsyncMock()
    vectors.search.return_value = [
        RetrievalHit(key, "vector", rank, score)
        for rank, (key, score) in enumerate(zip(("a", "b", "c"), scores), 1)
    ]
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository(products),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(), vector_repository=vectors,
        min_semantic_score=cutoff,
    )
    result = await service.match(MatchRequestV1(
        inquiry_line=line(), query_embedding=(1.0, 0.0), embedding_model_id="test", top_k=top_k,
    ))
    expected = expected[:top_k]
    assert [candidate.item_number for candidate in result.candidates] == expected
    assert [candidate.rank for candidate in result.candidates] == list(range(1, len(expected) + 1))


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_settings_reject_invalid_semantic_cutoffs(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, matching_min_semantic_score=value)


@pytest.mark.parametrize("score,count", [(0.59, 0), (0.60, 1)])
async def test_historical_offers_follow_same_cutoff(score, count):
    offer = historical_offer("unused").model_copy(update={"item_number": None})
    search = AsyncMock()
    search.search_offers.return_value = [(offer, [
        RetrievalHit(f"offer:{offer.record_id}", "vector", 1, score),
        RetrievalHit(f"offer:{offer.record_id}", "lexical", 1, 0.9),
    ])]
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository([]),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(),
        policy=load_default_policy(), offer_search_repository=search,
    )
    result = await service.match(MatchRequestV1(inquiry_line=line(), top_k=1))
    assert len(result.candidates) == count
