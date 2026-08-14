"""Constraint engine that refuses to invent unconfirmed exclusion rules."""

from __future__ import annotations

import json
from importlib.resources import files

from pydantic import BaseModel, ConfigDict

from app.matching.contracts import (
    AttributeValue,
    ConstraintResult,
    InquiryLineV1,
    InventoryItemV1,
    RuleOutcome,
)


class AttributeRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    on_missing: RuleOutcome = RuleOutcome.REVIEW
    on_mismatch: RuleOutcome = RuleOutcome.REVIEW


class MatchingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    attribute_rules: dict[str, AttributeRule]


def load_default_policy() -> MatchingPolicy:
    path = files("app.matching").joinpath("config/default_policy_v1.json")
    return MatchingPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _display(attribute: AttributeValue | None) -> str | None:
    if attribute is None:
        return None
    value, unit = attribute.comparable()
    return f"{value} {unit}" if unit else value


class ConstraintEngine:
    def __init__(self, policy: MatchingPolicy) -> None:
        self.policy = policy

    def evaluate(self, line: InquiryLineV1, item: InventoryItemV1) -> list[ConstraintResult]:
        results: list[ConstraintResult] = []

        if line.domain is not item.domain:
            results.append(
                ConstraintResult(
                    code="domain_mismatch",
                    outcome=RuleOutcome.EXCLUDE,
                    message="Candidate belongs to a different product domain.",
                    requested_value=line.domain.value,
                    candidate_value=item.domain.value,
                )
            )
            return results
        results.append(
            ConstraintResult(
                code="domain_match",
                outcome=RuleOutcome.PASS,
                message="Candidate belongs to the requested product domain.",
                requested_value=line.domain.value,
                candidate_value=item.domain.value,
            )
        )

        if not item.active:
            results.append(
                ConstraintResult(
                    code="item_inactive",
                    outcome=RuleOutcome.EXCLUDE,
                    message="The authoritative catalogue marks this item inactive.",
                )
            )
        if item.quality_blocked:
            results.append(
                ConstraintResult(
                    code="quality_blocked",
                    outcome=RuleOutcome.EXCLUDE,
                    message="The authoritative catalogue marks this item quality-blocked.",
                )
            )

        for name, requested in sorted(line.attributes.items()):
            rule = self.policy.attribute_rules.get(name)
            if rule is None:
                continue
            candidate = item.attributes.get(name)
            if candidate is None:
                results.append(
                    ConstraintResult(
                        code=f"attribute_{name}_missing",
                        outcome=rule.on_missing,
                        message=f"Candidate has no confirmed value for {name}.",
                        attribute=name,
                        requested_value=_display(requested),
                    )
                )
            elif requested.comparable() != candidate.comparable():
                results.append(
                    ConstraintResult(
                        code=f"attribute_{name}_mismatch",
                        outcome=rule.on_mismatch,
                        message=f"Requested and candidate values differ for {name}.",
                        attribute=name,
                        requested_value=_display(requested),
                        candidate_value=_display(candidate),
                    )
                )
            else:
                results.append(
                    ConstraintResult(
                        code=f"attribute_{name}_match",
                        outcome=RuleOutcome.PASS,
                        message=f"Requested and candidate values match for {name}.",
                        attribute=name,
                        requested_value=_display(requested),
                        candidate_value=_display(candidate),
                    )
                )
        return results
