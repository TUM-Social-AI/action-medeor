from decimal import Decimal

from app.matching.constraints.engine import ConstraintEngine, load_default_policy
from app.matching.contracts import AvailabilityStatus, RuleOutcome
from app.matching.packaging import calculate_packaging, observed_availability
from tests.matching.factories import item, line


def test_mismatched_medical_size_requires_review_not_guessed_exclusion() -> None:
    results = ConstraintEngine(load_default_policy()).evaluate(
        line(), item("410001002", "Foley catheter CH12", charriere=12)
    )
    size_result = next(result for result in results if result.attribute == "charriere")
    assert size_result.outcome is RuleOutcome.REVIEW
    assert size_result.requested_value == "18 ch"
    assert size_result.candidate_value == "12 ch"


def test_authoritative_inactive_flag_excludes_candidate() -> None:
    results = ConstraintEngine(load_default_policy()).evaluate(
        line(), item("410001001", "Foley catheter CH18", active=False)
    )
    assert any(result.outcome is RuleOutcome.EXCLUDE for result in results)


def test_packaging_returns_both_rounding_options_without_auto_selection() -> None:
    candidate = item("410001001", "Foley catheter CH18", units_per_package=Decimal("12"))
    result = calculate_packaging(line().quantity, candidate)
    assert [(option.packages, option.total_units) for option in result.options] == [
        (4, Decimal("48")),
        (5, Decimal("60")),
    ]
    assert result.recommended_option is None
    assert "not confirmed" in result.warnings[0]


def test_observed_stock_is_unknown_when_stock_basis_is_missing() -> None:
    candidate = item("410001001", "Foley catheter CH18", on_hand=Decimal("100"))
    candidate = candidate.model_copy(
        update={"stock": candidate.stock.model_copy(update={"unit": None})}
    )
    packaging = calculate_packaging(line().quantity, candidate)
    status, warning = observed_availability(line().quantity, candidate, packaging)
    assert status is AvailabilityStatus.UNKNOWN
    assert warning and "not confirmed" in warning
