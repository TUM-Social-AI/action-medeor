from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import app


@pytest.mark.parametrize("unit_price", [None, Decimal("0.37"), Decimal("0")])
async def test_catalogue_preserves_quoted_price_basis_and_offer_dates(unit_price) -> None:
    offer_id = uuid4()
    offer = {
        "id": offer_id,
        "offered_description": "Accu Check test strips",
        "raw_request_text": "test strips",
        "supplier": "Centramed",
        "domain": "equipment",
        "valid_until": date(2026, 12, 31) if unit_price is not None else None,
        # PostgreSQL returns the Berlin issue date as a UTC instant.
        "offer_date": datetime(2026, 1, 26, 23, tzinfo=UTC),
        "price": Decimal("18.50"),
        "price_basis": "50 St.",
        "unit_price": unit_price,
        "unit_price_unit": "St." if unit_price is not None else None,
        "currency": "EUR",
        "metadata_json": {
            "offer_date_source": "document",
            "offer_validity_source": "relative_document",
        },
        "source_url": "https://medeor.sharepoint.com/offers/offer.pdf",
        "file_name": "offer.pdf",
        "embedded": True,
    }
    erp = {
        "item_number": "123", "domain": "equipment", "descriptions": ["ERP item"],
        "manufacturer": None, "unit": "piece", "stock": Decimal("12"), "on_hand": Decimal("14"), "embedded": False, "attributes": {}, "family_id": None,
    }
    session = AsyncMock()
    session.execute.side_effect = [
        Mock(mappings=Mock(return_value=[erp])),
        Mock(mappings=Mock(return_value=[offer])),
    ]

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/v1/catalogue/articles")
        assert response.status_code == 200
        stock_item, quoted_offer = response.json()
        assert stock_item["stock"] == "12"
        assert stock_item["on_hand"] == "14"
        assert "suspension_reason" not in stock_item
        assert "suspension_by" not in stock_item
        assert stock_item["price"] is None
        assert stock_item["offer_date"] is None
        assert quoted_offer["price"] == "18.50"
        assert quoted_offer["price_basis"] == "50 St."
        assert quoted_offer["unit_price"] == (str(unit_price) if unit_price is not None else None)
        assert quoted_offer["unit_price_unit"] == offer["unit_price_unit"]
        assert quoted_offer["offer_date"] == "2026-01-26T23:00:00+00:00"
        assert quoted_offer["offer_date_source"] == "document"
        assert quoted_offer["offer_validity_source"] == "relative_document"
        assert quoted_offer["valid_until"] == ("2026-12-31" if unit_price is not None else None)
    finally:
        app.dependency_overrides.pop(get_session, None)
