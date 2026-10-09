"""Medicine ingredient-label eligibility; no strength or dosage-form checks.

Literal normalized labels must agree. Brands and ambiguous ingredient identities
are not inferred from therapeutic similarity and are excluded when unverified.
"""

from __future__ import annotations

import re

from app.matching.contracts import AttributeValue, ConstraintResult, InquiryLineV1, RuleOutcome

# Measurements and form words locate the end of an ingredient label only.
# Their values are deliberately not compared by this check.
_MEASUREMENT = re.compile(
    r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:mcg|µg|ug|mg|g|iu|%|mega|units?|i\.?u\.?)"
    r"(?!\w)",
    re.I,
)
_FORM = re.compile(
    r"\b(?:effervescent\s+|film[- ]coated\s+|extended[- ]release\s+|"
    r"modified[- ]release\s+|sustained[- ]release\s+|delayed[- ]release\s+|"
    r"controlled[- ]release\s+|prolonged[- ]release\s+|oral\s+)?"
    r"(?:tablets?|tabs?|capsules?|inhalers?|injection|injectable|suspension|"
    r"solution|liquid|cream|ointment|drops)\b",
    re.I,
)


def _text(value: str) -> str:
    return " ".join(value.casefold().replace("μ", "µ").split())


def ingredients_from_label(description: str) -> tuple[str, ...] | None:
    labels = []
    for part in re.split(r"\s*\+\s*|\s+and\s+", _text(description)):
        boundaries = [
            match.start() for pattern in (_MEASUREMENT, _FORM) if (match := pattern.search(part))
        ]
        if not boundaries:
            return None
        label = part[: min(boundaries)].strip(" ,;:")
        if not re.fullmatch(r"[^\W\d_]+(?:[ -][^\W\d_]+)*|vitamin\s+[bd]\d+", label):
            return None
        labels.append(label)
    return tuple(sorted(labels)) if labels else None


def _identity(description: str, attributes: dict[str, AttributeValue]) -> tuple[str, ...] | None:
    if "active_ingredient" in attributes:
        value, _ = attributes["active_ingredient"].comparable()
        labels = re.split(r"\s*\+\s*|\s+and\s+", _text(value))
        return tuple(sorted(labels)) if all(labels) else None
    return ingredients_from_label(description)


def medicine_checks(
    line: InquiryLineV1,
    descriptions: tuple[str, ...],
    attributes: dict[str, AttributeValue] | None = None,
) -> list[ConstraintResult]:
    requested_label = line.raw_description
    hint = _FORM.search(line.quantity.unit or "")
    if hint and not _FORM.search(requested_label):
        requested_label += f" {hint[0]}"
    requested = _identity(requested_label, line.attributes)
    identities = [_identity(description, attributes or {}) for description in descriptions]
    candidate = (
        requested
        if requested is not None and requested in identities
        else next(
            (identity for identity in identities if identity is not None),
            None,
        )
    )
    verified = requested is not None and candidate is not None
    matches = verified and requested == candidate
    return [
        ConstraintResult(
            code=f"medicine_active_ingredient_{'match' if matches else 'mismatch' if verified else 'unverified'}",
            outcome=RuleOutcome.PASS if matches else RuleOutcome.EXCLUDE,
            attribute="active_ingredient",
            message="Medicine active ingredient: "
            + (
                "labels agree."
                if matches
                else "labels differ."
                if verified
                else "could not be confirmed from the labels."
            ),
            requested_value=str(requested) if requested is not None else None,
            candidate_value=str(candidate) if candidate is not None else None,
        )
    ]


def ingredient_review_results(results: list[ConstraintResult]) -> list[ConstraintResult]:
    """Retain ingredient failures as evidence while building the fallback pool."""
    return [
        result.model_copy(update={"outcome": RuleOutcome.REVIEW})
        if result.code.startswith("medicine_active_ingredient_")
        and result.outcome is RuleOutcome.EXCLUDE else result
        for result in results
    ]
