from unittest.mock import AsyncMock, Mock

import pytest

from app.matching.adapters.persistence import PostgresHistoryRepository
from app.matching.contracts import ProductDomain
from app.matching.domain import SearchRepresentation
from app.matching.representation import normalize_text, represent_offer, tokenize
from app.matching.retrieval.lexical import lexical_similarity
from tests.matching.factories import historical_offer


@pytest.mark.asyncio
async def test_offer_repository_preserves_channel_similarities_for_shared_ranking(monkeypatch):
    offer = historical_offer("erp").model_copy(
        update={
            "item_number": None,
            "offered_description": "Sterile Foley catheter CH18",
        }
    )
    lexical_result = Mock()
    lexical_result.mappings.return_value.all.return_value = [{}]
    vector_result = Mock()
    vector_result.mappings.return_value.all.return_value = [{"similarity": 0.93}]
    session = AsyncMock()
    session.execute.side_effect = [lexical_result, vector_result]
    session.scalar.return_value = 2
    repository = PostgresHistoryRepository(session)
    monkeypatch.setattr(repository, "_records", lambda rows: [offer])

    query_text = "Sterile Foley catheter CH18"
    results = await repository.search_offers(
        query=query_text,
        domain=ProductDomain.EQUIPMENT,
        limit=10,
        embedding=(1.0, 0.0),
        model_id="test-model",
    )

    assert len(results) == 1
    record, hits = results[0]
    assert record == offer
    scores = {hit.retriever: hit.score for hit in hits}
    query = SearchRepresentation(
        normalize_text(query_text),
        normalize_text(query_text),
        tokenize(query_text),
        "",
    )
    assert scores["lexical"] == lexical_similarity(query, represent_offer(offer))
    assert scores["vector"] == 0.93
    assert all(hit.item_number == f"offer:{offer.record_id}" for hit in hits)
    vector_sql = str(session.execute.call_args_list[1].args[0])
    assert "AS similarity" in vector_sql
    assert ">= 0.5" not in vector_sql
