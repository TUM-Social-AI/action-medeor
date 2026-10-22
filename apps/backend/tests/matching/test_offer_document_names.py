from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
)
from app.matching.adapters.persistence import PostgresHistoryRepository, PostgresMatchRunRepository
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import MatchRequestV1
from app.matching.service import MatchingService
from app.offers.documents import offer_document_name
from tests.matching.factories import historical_offer, item, line


@pytest.mark.parametrize(("file_name", "path", "expected"), [
    ("Actual quotation.xlsx", "/offers/old.xlsx", "Actual quotation.xlsx"),
    (None, "/offers/Stored quotation.xlsx", "Stored quotation.xlsx"),
    ("   ", None, "URL quotation.xlsx"),
])
def test_catalogue_and_matching_share_document_name_precedence(file_name, path, expected):
    assert offer_document_name(
        file_name, path, "https://medeor.sharepoint.com/offers/URL%20quotation.xlsx",
    ) == expected


def test_retrieved_offers_include_filename_and_preserve_source_locator():
    offer = historical_offer("123")
    row = {
        **offer.model_dump(),
        "id": offer.record_id,
        "source_type": "sharepoint", "document_id": "file-1", "external_id": "file-1",
        "uri": "https://medeor.sharepoint.com/_layouts/15/Doc.aspx?sourcedoc=file-1",
        "checksum": "v1", "source_captured_at": offer.source.captured_at,
        "locator": {"sheet": "Offers"}, "metadata_json": {"source_id": "sheet1:row4"},
        "file_name": "Actual quotation.xlsx",
    }
    [retrieved] = PostgresHistoryRepository._records([row])
    assert retrieved.source.locator == {
        "sheet": "Offers", "source_id": "sheet1:row4", "file_name": "Actual quotation.xlsx",
    }
    assert retrieved.source.uri == row["uri"]


async def test_saved_match_filename_refresh_does_not_rewrite_results():
    product = item("123", "Foley catheter sterile CH18")
    request = MatchRequestV1(inquiry_line=line())
    service = MatchingService(
        min_semantic_score=0,
        catalog_repository=InMemoryCatalogRepository([product]),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(), policy=load_default_policy(),
    )
    result = await service.match(request)
    payload = result.model_dump(mode="json")
    source = historical_offer("123").source.model_copy(update={
        "document_id": "file-1",
        "uri": "https://medeor.sharepoint.com/_layouts/15/Doc.aspx?sourcedoc=file-1",
        "locator": {"source_id": "sheet1:row4"},
    })
    payload["candidates"][0].update(
        candidate_type="historical_offer", item_number=None,
        provenance=[source.model_dump(mode="json")],
    )
    saved_payload = deepcopy(payload)
    saved = Mock()
    saved.mappings.return_value.first.return_value = {
        "result_payload": payload, "request_payload": request.model_dump(mode="json"),
        "source_versions": {},
    }
    files = Mock()
    files.mappings.return_value = [{
        "external_id": "file-1", "name": "Actual quotation.xlsx", "metadata_json": {},
    }]
    session = AsyncMock()
    session.execute.side_effect = [saved, files]

    restored = await PostgresMatchRunRepository(session).get_run(result.match_run_id)

    [candidate] = restored.candidates
    assert candidate.provenance[0].locator == {
        "source_id": "sheet1:row4", "file_name": "Actual quotation.xlsx",
    }
    assert candidate.provenance[0].uri == source.uri
    restored_payload = restored.model_dump(mode="json")
    restored_payload["candidates"][0]["provenance"][0]["locator"].pop("file_name")
    assert restored_payload == saved_payload
    assert payload == saved_payload
    session.commit.assert_not_awaited()
