"""Defensive validation beyond Pydantic's structural contract checks."""

from __future__ import annotations

from app.matching.contracts import InquiryLineV1, ValidationReport, ValidationStatus


def validate_inquiry(line: InquiryLineV1) -> ValidationReport:
    warnings = list(line.parsing_warnings)
    errors: list[str] = []

    if line.quantity.value is None:
        warnings.append("Requested quantity is not normalized; packaging cannot be calculated.")
    if line.quantity.value is not None and not line.quantity.unit:
        warnings.append("Requested quantity has no normalized unit.")
    if not line.attributes:
        warnings.append("No structured product attributes were supplied.")

    if errors:
        status = ValidationStatus.INVALID
    elif line.parsing_warnings:
        status = ValidationStatus.REVIEW_REQUIRED
    elif warnings:
        status = ValidationStatus.VALID_WITH_WARNINGS
    else:
        status = ValidationStatus.VALID
    return ValidationReport(
        status=status, warnings=tuple(dict.fromkeys(warnings)), errors=tuple(errors)
    )
