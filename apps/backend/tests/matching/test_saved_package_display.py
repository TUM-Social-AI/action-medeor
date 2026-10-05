from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.matching.adapters.in_memory import (
    InMemoryCatalogRepository,
    InMemoryHistoryRepository,
    InMemoryMatchRunRepository,
)
from app.matching.adapters.persistence import PostgresCatalogRepository, PostgresMatchRunRepository
from app.matching.constraints.engine import load_default_policy
from app.matching.contracts import MatchRequestV1
from app.matching.service import MatchingService
from tests.matching.factories import item, line


@pytest.mark.parametrize("pinned", [True, False])
@pytest.mark.parametrize("package_field", ["missing", "present", "null"])
async def test_saved_package_display_uses_original_snapshot_without_rewriting(
    monkeypatch, pinned, package_field,
):
    snapshot_id = str(uuid4())
    product = item("410001001", "Foley catheter sterile CH18", on_hand=Decimal("60"))
    request = MatchRequestV1(
        inquiry_line=line(), catalog_snapshot_id=snapshot_id if pinned else None,
    )
    service = MatchingService(
        catalog_repository=InMemoryCatalogRepository([product]),
        history_repository=InMemoryHistoryRepository(),
        run_repository=InMemoryMatchRunRepository(), policy=load_default_policy(),
    )
    result = await service.match(request)
    payload = result.model_dump(mode="json")
    if package_field == "missing":
        payload["candidates"][0].pop("package")
    elif package_field == "null":
        payload["candidates"][0]["package"] = None
    saved_payload = deepcopy(payload)
    db_result = Mock()
    db_result.mappings.return_value.first.return_value = {
        "result_payload": payload, "request_payload": request.model_dump(mode="json"),
        "source_versions": {},
    }
    session = AsyncMock()
    session.execute.return_value = db_result
    session.scalar.return_value = snapshot_id
    list_items = AsyncMock(return_value=[product])
    monkeypatch.setattr(PostgresCatalogRepository, "list_items", list_items)

    restored = await PostgresMatchRunRepository(session).get_run(result.match_run_id)

    if package_field == "missing":
        list_items.assert_awaited_once_with(
            domain=request.inquiry_line.domain, snapshot_id=snapshot_id,
            item_numbers=[product.item_number],
        )
        assert session.scalar.await_count == (0 if pinned else 1)
    else:
        list_items.assert_not_awaited()
    assert restored.candidates[0].package == (
        None if package_field == "null" else product.package
    )
    assert restored.candidates[0].candidate_id == result.candidates[0].candidate_id
    assert restored.candidates[0].rank == result.candidates[0].rank
    assert payload == saved_payload
    session.commit.assert_not_awaited()
