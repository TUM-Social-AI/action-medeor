"""Contracts consumed by the separate SharePoint extraction workstream."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.matching.contracts import ProductPackage, QuantityValue


class OfferContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validated_sharepoint_url(value: HttpUrl) -> HttpUrl:
    host = (value.host or "").casefold()
    if value.scheme != "https" or not host.endswith(".sharepoint.com"):
        raise ValueError("source_url must be an HTTPS Microsoft SharePoint URL")
    return value


class NormalizedOfferUpsertV1(OfferContract):
    contract_version: str = Field(default="1", pattern=r"^1$")
    source_version: str = Field(min_length=1, max_length=500)
    source_url: HttpUrl
    captured_at: AwareDatetime
    raw_request_text: str = Field(min_length=1)
    offered_description: str | None = None
    item_number: str | None = None
    partner_id: str | None = None
    destination_country: str | None = None
    supplier: str | None = None
    quantity: QuantityValue | None = None
    package: ProductPackage | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    price_basis: str | None = None
    offer_date: AwareDatetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    _sharepoint_source = field_validator("source_url")(_validated_sharepoint_url)


class OfferArchiveRequestV1(OfferContract):
    contract_version: str = Field(default="1", pattern=r"^1$")
    source_version: str | None = Field(default=None, max_length=500)
    archived_at: AwareDatetime | None = None


class SharePointOfferFileUpsertV1(OfferContract):
    """Metadata discovered by a separate read-only Microsoft Graph sync."""

    contract_version: str = Field(default="1", pattern=r"^1$")
    source_version: str = Field(min_length=1, max_length=500)
    source_url: HttpUrl
    name: str = Field(min_length=1)
    captured_at: AwareDatetime
    modified_at: AwareDatetime | None = None
    mime_type: str | None = Field(default=None, max_length=300)
    size_bytes: int | None = Field(default=None, ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)

    _sharepoint_source = field_validator("source_url")(_validated_sharepoint_url)


class SharePointOfferFileRecordV1(OfferContract):
    contract_version: str = Field(default="1", pattern=r"^1$")
    file_id: UUID
    external_id: str
    source_version: str
    source_url: str
    name: str
    active: bool
    modified_at: datetime | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    structured_output_available: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
    archived_at: datetime | None = None
    updated_at: datetime
    idempotent_replay: bool = False


class OfferRecordV1(OfferContract):
    contract_version: str = Field(default="1", pattern=r"^1$")
    offer_id: UUID
    external_id: str
    source_version: str
    source_url: str
    active: bool
    raw_request_text: str
    offered_description: str | None = None
    item_number: str | None = None
    partner_id: str | None = None
    destination_country: str | None = None
    supplier: str | None = None
    quantity: QuantityValue | None = None
    package: ProductPackage | None = None
    price: Decimal | None = None
    currency: str | None = None
    price_basis: str | None = None
    offer_date: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    archived_at: datetime | None = None
    updated_at: datetime
    idempotent_replay: bool = False
