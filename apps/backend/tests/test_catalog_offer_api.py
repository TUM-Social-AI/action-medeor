from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.catalog.api import get_catalog_import_service
from app.catalog.contracts import CatalogImportResponseV1, CatalogImportStatus
from app.main import app
from app.offers.api import get_offer_file_service, get_offer_service
from app.offers.contracts import (
    OfferRecordV1,
    SharePointOfferFileRecordV1,
    SharePointOfferFileUpsertV1,
)

NOW = datetime(2026, 8, 19, 8, tzinfo=UTC)


def test_sharepoint_file_contract_rejects_non_sharepoint_links() -> None:
    with pytest.raises(ValidationError, match="SharePoint"):
        SharePointOfferFileUpsertV1(
            source_version="etag-1",
            source_url="https://example.com/offer.xlsx",
            name="offer.xlsx",
            captured_at=NOW,
        )


class FakeCatalogService:
    async def import_files(self, **_: Any) -> CatalogImportResponseV1:
        return CatalogImportResponseV1(
            import_id=uuid4(),
            catalog_snapshot_id=uuid4(),
            status=CatalogImportStatus.COMPLETED,
            inserted_items=1,
            inventory_refreshed_items=1,
            completed_at=NOW,
        )


class FakeOfferService:
    def __init__(self) -> None:
        self.record = OfferRecordV1(
            offer_id=uuid4(),
            external_id="drive-item-1",
            source_version="etag-1",
            source_url="https://medeor.sharepoint.com/sites/TheLabworks/offer.xlsx",
            active=True,
            raw_request_text="sterile gloves",
            price=Decimal("12.50"),
            updated_at=NOW,
        )

    async def upsert(self, external_id: str, _: Any) -> OfferRecordV1:
        assert external_id == self.record.external_id
        return self.record

    async def archive(self, external_id: str, **_: Any) -> OfferRecordV1:
        assert external_id == self.record.external_id
        return self.record.model_copy(update={"active": False, "archived_at": NOW})

    async def list_current(self, **_: Any) -> list[OfferRecordV1]:
        return [self.record]


class FakeOfferFileService:
    def __init__(self) -> None:
        self.record = SharePointOfferFileRecordV1(
            file_id=uuid4(),
            external_id="drive-item-1",
            source_version="etag-1",
            source_url="https://medeor.sharepoint.com/sites/TheLabworks/offer.xlsx",
            name="offer.xlsx",
            active=True,
            structured_output_available=False,
            updated_at=NOW,
        )

    async def upsert(self, external_id: str, _: Any) -> SharePointOfferFileRecordV1:
        assert external_id == self.record.external_id
        return self.record

    async def archive(self, external_id: str, **_: Any) -> SharePointOfferFileRecordV1:
        assert external_id == self.record.external_id
        return self.record.model_copy(update={"active": False, "archived_at": NOW})

    async def list_current(self, **_: Any) -> list[SharePointOfferFileRecordV1]:
        return [self.record]


@pytest.mark.asyncio
async def test_catalog_import_and_offer_contracts() -> None:
    catalog_service = FakeCatalogService()
    offer_service = FakeOfferService()
    offer_file_service = FakeOfferFileService()

    async def override_catalog_service() -> FakeCatalogService:
        return catalog_service

    async def override_offer_service() -> FakeOfferService:
        return offer_service

    async def override_offer_file_service() -> FakeOfferFileService:
        return offer_file_service

    app.dependency_overrides[get_catalog_import_service] = override_catalog_service
    app.dependency_overrides[get_offer_service] = override_offer_service
    app.dependency_overrides[get_offer_file_service] = override_offer_file_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            catalog = await client.post(
                "/api/v1/catalog-imports",
                files={
                    "article_data": ("Artikeldaten.csv", b"header\n", "text/csv"),
                    "article_translations": (
                        "Artikeluebersetzungen.csv",
                        b"header\n",
                        "text/csv",
                    ),
                },
            )
            assert catalog.status_code == 201
            assert catalog.json()["inserted_items"] == 1
            assert catalog.json()["catalog_snapshot_id"] is not None

            payload = {
                "source_version": "etag-1",
                "source_url": "https://medeor.sharepoint.com/sites/TheLabworks/offer.xlsx",
                "captured_at": NOW.isoformat(),
                "raw_request_text": "sterile gloves",
            }
            offer = await client.put("/api/v1/offers/drive-item-1", json=payload)
            assert offer.status_code == 200
            assert offer.json()["source_url"].startswith("https://medeor.sharepoint.com/")

            listed = await client.get("/api/v1/offers")
            assert listed.status_code == 200
            assert listed.json()[0]["external_id"] == "drive-item-1"

            archived = await client.post(
                "/api/v1/offers/drive-item-1/archive", json={"source_version": "etag-2"}
            )
            assert archived.status_code == 200
            assert archived.json()["active"] is False

            source_payload = {
                "source_version": "etag-1",
                "source_url": "https://medeor.sharepoint.com/sites/TheLabworks/offer.xlsx",
                "name": "offer.xlsx",
                "captured_at": NOW.isoformat(),
            }
            source = await client.put(
                "/api/v1/sharepoint-offer-files/drive-item-1", json=source_payload
            )
            assert source.status_code == 200
            assert source.json()["structured_output_available"] is False

            source_list = await client.get(
                "/api/v1/sharepoint-offer-files?needs_extraction=true"
            )
            assert source_list.status_code == 200
            assert source_list.json()[0]["name"] == "offer.xlsx"
    finally:
        app.dependency_overrides.clear()
