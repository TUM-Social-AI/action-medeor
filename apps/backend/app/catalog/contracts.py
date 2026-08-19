"""Versioned contracts for the ERP catalog boundary."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CatalogContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogImportStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"


class CatalogImportResponseV1(CatalogContract):
    contract_version: str = Field(default="1", pattern=r"^1$")
    import_id: UUID
    status: CatalogImportStatus
    idempotent_replay: bool = False
    inserted_items: int = 0
    text_updated_items: int = 0
    metadata_updated_items: int = 0
    unchanged_items: int = 0
    inventory_refreshed_items: int = 0
    missing_items: int = 0
    reactivated_items: int = 0
    embedding_jobs_created: int = 0
    warnings: tuple[str, ...] = ()
    completed_at: datetime


class CatalogImportErrorV1(CatalogContract):
    row: int | None = None
    field: str | None = None
    code: str
    message: str


class CatalogImportValidationError(ValueError):
    def __init__(self, errors: list[CatalogImportErrorV1]) -> None:
        super().__init__("Catalog import validation failed")
        self.errors = errors


class CatalogItemViewV1(CatalogContract):
    item_number: str
    domain: str
    matching_eligible: bool
    source_missing: bool
    descriptions: tuple[str, ...]
    family_id: str | None = None
    base_unit: str | None = None
    available_raw: str | None = None
    fulfillable_quantity: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
