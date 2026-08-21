from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.matching.contracts import (
    DecisionType,
    MatchDecisionRequestV1,
    MatchRequestV1,
    SourceReferenceV1,
)
from tests.matching.factories import line


def test_embedding_and_model_must_be_provided_together() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        MatchRequestV1(inquiry_line=line(), query_embedding=(0.1, 0.2))


def test_embedding_must_be_finite() -> None:
    with pytest.raises(ValidationError, match="finite"):
        MatchRequestV1(
            inquiry_line=line(),
            query_embedding=(float("nan"),),
            embedding_model_id="model-v1",
        )


def test_alternative_selection_requires_reason() -> None:
    with pytest.raises(ValidationError, match="override_reason"):
        MatchDecisionRequestV1(
            match_run_id=uuid4(),
            inquiry_line_id="line-1",
            decision_type=DecisionType.SELECT_ALTERNATIVE,
            selected_item_number="410001001",
            offered_quantity=Decimal("50"),
        )


def test_source_timestamp_must_include_a_timezone() -> None:
    payload = line().source.model_dump()
    payload["captured_at"] = datetime(2026, 8, 14, 12, 0)

    with pytest.raises(ValidationError, match="timezone"):
        SourceReferenceV1.model_validate(payload)
