"""Versioned public contracts for the matching boundary.

The extraction layer owns source parsing.  These models deliberately keep raw
values and provenance next to normalized values so matching never has to guess
where a fact came from.
"""

from __future__ import annotations

import math
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProductDomain(StrEnum):
    MEDICINE = "medicine"
    EQUIPMENT = "equipment"


class SourceType(StrEnum):
    EXCEL = "excel"
    OUTLOOK_MESSAGE = "outlook_message"
    OUTLOOK_ATTACHMENT = "outlook_attachment"
    SHAREPOINT = "sharepoint"
    ERP = "erp"
    SUPPLIER = "supplier"
    OTHER = "other"


class CandidateType(StrEnum):
    CATALOG = "catalog"
    HISTORICAL_OFFER = "historical_offer"
    PROCUREMENT = "procurement"


class ValidationStatus(StrEnum):
    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    REVIEW_REQUIRED = "review_required"
    INVALID = "invalid"


class RuleOutcome(StrEnum):
    PASS = "pass"
    EXCLUDE = "exclude"
    REVIEW = "review"
    WARNING = "warning"
    UNKNOWN = "unknown"


class AvailabilityStatus(StrEnum):
    ON_HAND_SUFFICIENT = "on_hand_sufficient"
    ON_HAND_PARTIAL = "on_hand_partial"
    PROCUREMENT_INDICATED = "procurement_indicated"
    UNKNOWN = "unknown"
    NOT_ALLOWED = "not_allowed"


class MatchRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DecisionType(StrEnum):
    ACCEPT_SUGGESTION = "accept_suggestion"
    SELECT_ALTERNATIVE = "select_alternative"
    MANUAL_MATCH = "manual_match"
    NO_MATCH = "no_match"
    PROCUREMENT_REQUIRED = "procurement_required"


class SourceReferenceV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    source_type: SourceType
    document_id: str = Field(min_length=1)
    external_id: str | None = None
    uri: str | None = None
    checksum: str | None = None
    captured_at: AwareDatetime
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)
    locator: dict[str, Any] = Field(default_factory=dict)


class AttributeValue(ContractModel):
    value: str | int | float | bool
    unit: str | None = None
    raw_value: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    def comparable(self) -> tuple[str, str | None]:
        if isinstance(self.value, bool):
            value = "true" if self.value else "false"
        elif isinstance(self.value, float):
            value = f"{self.value:g}"
        else:
            value = str(self.value).strip().casefold()
        unit = self.unit.strip().casefold() if self.unit else None
        return value, unit


class QuantityValue(ContractModel):
    value: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    raw_expression: str | None = None


class ProductPackage(ContractModel):
    units_per_package: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None
    package_label: str | None = None


class StockSnapshot(ContractModel):
    on_hand: Decimal | None = Field(default=None, ge=0)
    incoming_purchase_order: Decimal | None = Field(default=None, ge=0)
    purchasing_inquiry: Decimal | None = Field(default=None, ge=0)
    committed_order: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    captured_at: AwareDatetime


class InquiryLineV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    inquiry_id: str = Field(min_length=1)
    line_id: str = Field(min_length=1)
    domain: ProductDomain
    raw_description: str = Field(min_length=1)
    translated_description: str | None = None
    requested_item_number: str | None = None
    quantity: QuantityValue = Field(default_factory=QuantityValue)
    package_request: ProductPackage | None = None
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    partner_id: str | None = None
    destination_country: str | None = None
    urgency: str | None = None
    desired_shelf_life: str | None = None
    special_instructions: tuple[str, ...] = ()
    parsing_warnings: tuple[str, ...] = ()
    source: SourceReferenceV1


class InventoryItemV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    item_number: str = Field(pattern=r"^\S+$")
    domain: ProductDomain
    descriptions: tuple[str, ...] = Field(min_length=1)
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    manufacturer: str | None = None
    brand: str | None = None
    family_id: str | None = None
    package: ProductPackage | None = None
    replenishment_method: str | None = None
    t1: bool | None = None
    active: bool = True
    quality_blocked: bool = False
    stock: StockSnapshot | None = None
    source: SourceReferenceV1


class HistoricalOfferV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    record_id: str = Field(min_length=1)
    raw_request_text: str = Field(min_length=1)
    item_number: str | None = None
    offered_description: str | None = None
    partner_id: str | None = None
    destination_country: str | None = None
    supplier: str | None = None
    quantity: QuantityValue | None = None
    package: ProductPackage | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    price_basis: str | None = None
    offer_date: AwareDatetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: SourceReferenceV1


class MatchRequestV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    inquiry_line: InquiryLineV1
    catalog_snapshot_id: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    retrieval_limit: int = Field(default=50, ge=1, le=500)
    query_embedding: tuple[float, ...] | None = None
    embedding_model_id: str | None = None

    @model_validator(mode="after")
    def validate_embedding_pair(self) -> Self:
        if (self.query_embedding is None) != (self.embedding_model_id is None):
            raise ValueError("query_embedding and embedding_model_id must be provided together")
        if self.query_embedding is not None:
            if not self.query_embedding:
                raise ValueError("query_embedding cannot be empty")
            if not all(math.isfinite(value) for value in self.query_embedding):
                raise ValueError("query_embedding must contain only finite values")
        return self


class ValidationReport(ContractModel):
    status: ValidationStatus
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class ConstraintResult(ContractModel):
    code: str
    outcome: RuleOutcome
    message: str
    attribute: str | None = None
    requested_value: str | None = None
    candidate_value: str | None = None


class RetrievalEvidence(ContractModel):
    retriever: str
    rank: int = Field(ge=1)
    score: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PackagingOption(ContractModel):
    packages: int = Field(ge=0)
    total_units: Decimal = Field(ge=0)
    difference: Decimal
    direction: str


class PackagingResult(ContractModel):
    status: str
    options: tuple[PackagingOption, ...] = ()
    recommended_option: PackagingOption | None = None
    warnings: tuple[str, ...] = ()


class MatchCandidateV1(ContractModel):
    candidate_id: UUID
    item_number: str
    candidate_type: CandidateType = CandidateType.CATALOG
    rank: int = Field(ge=1)
    descriptions: tuple[str, ...]
    manufacturer: str | None = None
    review_status: RuleOutcome
    availability_status: AvailabilityStatus
    retrieval_evidence: tuple[RetrievalEvidence, ...]
    score_components: dict[str, float]
    constraints: tuple[ConstraintResult, ...]
    packaging: PackagingResult
    warnings: tuple[str, ...]
    provenance: tuple[SourceReferenceV1, ...]


class MatchRunResponseV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    match_run_id: UUID
    status: MatchRunStatus
    inquiry_id: str
    inquiry_line_id: str
    algorithm_version: str
    policy_version: str
    embedding_model_id: str | None = None
    validation: ValidationReport
    candidates: tuple[MatchCandidateV1, ...]
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    error: str | None = None


class MatchDecisionRequestV1(ContractModel):
    contract_version: str = Field(default="1", pattern=r"^1$")
    match_run_id: UUID
    inquiry_line_id: str = Field(min_length=1)
    decision_type: DecisionType
    candidate_id: UUID | None = None
    selected_item_number: str | None = None
    offered_quantity: Decimal | None = Field(default=None, ge=0)
    override_reason: str | None = None
    note: str | None = None
    actor: str | None = None

    @model_validator(mode="after")
    def validate_selected_item(self) -> Self:
        needs_item = self.decision_type in {
            DecisionType.ACCEPT_SUGGESTION,
            DecisionType.SELECT_ALTERNATIVE,
            DecisionType.MANUAL_MATCH,
        }
        if needs_item and not self.selected_item_number:
            raise ValueError("selected_item_number is required for a product selection")
        if self.decision_type is DecisionType.SELECT_ALTERNATIVE and not self.override_reason:
            raise ValueError("override_reason is required when selecting an alternative")
        return self


class MatchDecisionResponseV1(ContractModel):
    decision_id: UUID
    match_run_id: UUID
    decision_type: DecisionType
    created_at: AwareDatetime
