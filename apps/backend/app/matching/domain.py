"""Internal domain objects used while a match run is evaluated."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.matching.contracts import (
    ConstraintResult,
    InventoryItemV1,
    PackagingResult,
    RetrievalEvidence,
    RuleOutcome,
)


@dataclass(frozen=True, slots=True)
class SearchRepresentation:
    semantic_core: str
    canonical_text: str
    tokens: frozenset[str]
    content_hash: str


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    item_number: str
    retriever: str
    rank: int
    score: float | None = None
    details: dict[str, object] = field(default_factory=dict)

    def as_evidence(self) -> RetrievalEvidence:
        return RetrievalEvidence(
            retriever=self.retriever,
            rank=self.rank,
            score=self.score,
            details=self.details,
        )


@dataclass(slots=True)
class CandidateState:
    item: InventoryItemV1
    fused_score: float
    evidence: list[RetrievalHit]
    constraints: list[ConstraintResult] = field(default_factory=list)
    packaging: PackagingResult | None = None
    score_components: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def review_status(self) -> RuleOutcome:
        outcomes = {result.outcome for result in self.constraints}
        if RuleOutcome.EXCLUDE in outcomes:
            return RuleOutcome.EXCLUDE
        if RuleOutcome.REVIEW in outcomes:
            return RuleOutcome.REVIEW
        if RuleOutcome.WARNING in outcomes or RuleOutcome.UNKNOWN in outcomes:
            return RuleOutcome.WARNING
        return RuleOutcome.PASS
