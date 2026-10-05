from decimal import Decimal

import pytest

from app.matching.constraints.engine import ConstraintEngine, load_default_policy
from app.matching.contracts import AvailabilityStatus, QuantityValue, RuleOutcome
from app.matching.packaging import (
    calculate_packaging,
    observed_availability,
    required_stock_quantity,
)
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


def test_availability_uses_on_hand_minus_purchase_orders_plus_sales_orders() -> None:
    candidate = item("410001001", "Foley catheter", on_hand=Decimal("10"))
    assert candidate.stock is not None
    candidate = candidate.model_copy(
        update={
            "stock": candidate.stock.model_copy(
                update={
                    "incoming_purchase_order": Decimal("20"),
                    "committed_order": Decimal("5"),
                }
            )
        }
    )
    packaging = calculate_packaging(line().quantity, candidate)

    availability, warning = observed_availability(line().quantity, candidate, packaging)

    assert candidate.stock.available_raw == Decimal("-5")
    assert candidate.stock.fulfillable_quantity == Decimal("0")
    assert availability is AvailabilityStatus.PROCUREMENT_INDICATED
    assert warning is None


@pytest.mark.parametrize(
    "flags",
    [
        {"blocked": True},
        {"sales_blocked": True},
        {"blocked": True, "purchasing_blocked": True},
        {"sales_blocked": True, "purchasing_blocked": True},
        {"blocked": True, "sales_blocked": True},
        {"blocked": True, "sales_blocked": True, "purchasing_blocked": True},
    ],
)
def test_full_and_sales_blocks_exclude_even_with_stock(flags) -> None:
    candidate = item("410001001", "Foley catheter", on_hand=Decimal("1000"))
    results = ConstraintEngine(load_default_policy()).evaluate(
        line(), candidate.model_copy(update=flags)
    )
    assert any(result.outcome is RuleOutcome.EXCLUDE for result in results)


@pytest.mark.parametrize(
    "stock,unit,quantity,excluded",
    [
        ("50", "STÜCK", "50", False),
        ("51", "piece", "50", False),
        ("49", "piece", "50", True),
        ("0", "piece", "50", True),
        (None, "piece", "50", True),
        ("100", "bottle", "50", True),
        ("100", "piece", None, True),
        ("100", "piece", "0", True),
    ],
)
def test_purchase_block_requires_confirmed_full_stock(stock, unit, quantity, excluded) -> None:
    candidate = item("410001001", "Foley catheter", on_hand=Decimal(stock) if stock else None)
    if candidate.stock:
        candidate = candidate.model_copy(
            update={"stock": candidate.stock.model_copy(update={"unit": unit})}
        )
    candidate = candidate.model_copy(update={"purchasing_blocked": True})
    inquiry = line()
    inquiry = inquiry.model_copy(
        update={
            "quantity": inquiry.quantity.model_copy(
                update={
                    "value": Decimal(quantity) if quantity is not None else None,
                }
            )
        }
    )
    results = ConstraintEngine(load_default_policy()).evaluate(inquiry, candidate)
    assert any(result.outcome is RuleOutcome.EXCLUDE for result in results) is excluded


def test_purchase_block_uses_confirmed_package_conversion_only() -> None:
    candidate = item("410001001", "Catheter", units_per_package=Decimal("10"), on_hand=Decimal("5"))
    candidate = candidate.model_copy(
        update={
            "purchasing_blocked": True,
            "stock": candidate.stock.model_copy(update={"unit": "PAKET"}),
        }
    )
    engine = ConstraintEngine(load_default_policy())
    assert not any(
        result.outcome is RuleOutcome.EXCLUDE for result in engine.evaluate(line(), candidate)
    )
    candidate = candidate.model_copy(update={"package": None})
    assert any(
        result.outcome is RuleOutcome.EXCLUDE for result in engine.evaluate(line(), candidate)
    )


def test_legacy_master_is_excluded_without_metadata_flag() -> None:
    results = ConstraintEngine(load_default_policy()).evaluate(
        line(), item("401108100", "Legacy master", on_hand=Decimal("100"))
    )
    assert any(
        result.code == "master_item" and result.outcome is RuleOutcome.EXCLUDE for result in results
    )


@pytest.mark.parametrize(
    "stock_unit,request_unit",
    [("STÜCK", "pcs"), ("PAKET", "packs"), ("FLASCHE", "bottles"),
     ("PAAR", "pairs"), ("ROLLE", "rolls"), ("TUBE", "tubes"),
     ("KANISTER", "canisters"), ("EIMER", "buckets"), ("PALETTE", "pallets")],
)
def test_same_count_units_need_no_package_size(stock_unit, request_unit):
    candidate = item("410001001", "Article", on_hand=Decimal("60")).model_copy(
        update={"package": None, "purchasing_blocked": True}
    )
    candidate = candidate.model_copy(
        update={"stock": candidate.stock.model_copy(update={"unit": stock_unit})}
    )
    request = QuantityValue(value=Decimal("50"), unit=request_unit)
    packaging = calculate_packaging(request, candidate)
    assert packaging.status == "not_required" and not packaging.warnings
    assert observed_availability(request, candidate, packaging) == (
        AvailabilityStatus.ON_HAND_SUFFICIENT, None
    )
    assert required_stock_quantity(request, candidate) == Decimal("50")
    inquiry = line().model_copy(update={"quantity": request})
    assert not any(r.outcome is RuleOutcome.EXCLUDE for r in
                   ConstraintEngine(load_default_policy()).evaluate(inquiry, candidate))


@pytest.mark.parametrize(
    "stock_unit,request_unit,stock,quantity,expected",
    [("PAKET", "pieces", "5", "50", AvailabilityStatus.ON_HAND_SUFFICIENT),
     ("PAKET", "pieces", "4", "50", AvailabilityStatus.ON_HAND_PARTIAL),
     ("STÜCK", "packs", "60", "5", AvailabilityStatus.ON_HAND_SUFFICIENT),
     ("STÜCK", "packs", "59", "5", AvailabilityStatus.ON_HAND_PARTIAL)],
)
def test_confirmed_conversion_compares_quantity_in_both_directions(
    stock_unit, request_unit, stock, quantity, expected
):
    candidate = item("410001001", "Article", units_per_package=Decimal("12"),
                     on_hand=Decimal(stock))
    candidate = candidate.model_copy(
        update={"stock": candidate.stock.model_copy(update={"unit": stock_unit})}
    )
    requested = QuantityValue(value=Decimal(quantity), unit=request_unit)
    packaging = calculate_packaging(requested, candidate)
    assert observed_availability(requested, candidate, packaging) == (expected, None)
    assert required_stock_quantity(requested, candidate) == (
        Decimal(quantity) / Decimal("12") if stock_unit == "PAKET"
        else Decimal(quantity) * Decimal("12")
    )
    if request_unit == "pieces":
        assert packaging.recommended_option is None
        assert "not confirmed" in packaging.warnings[0]


def test_unstructured_names_do_not_supply_conversions_without_erp_package_metadata():
    candidate = item("410001001", "Fixierpflaster 24 Rollen", on_hand=Decimal("50"))
    candidate = candidate.model_copy(update={
        "package": None, "purchasing_blocked": True,
        "stock": candidate.stock.model_copy(update={"unit": "PAKET"}),
    })
    requested = QuantityValue(value=Decimal("200"), unit="rolls")
    packaging = calculate_packaging(requested, candidate)
    status, warning = observed_availability(requested, candidate, packaging)
    assert status is AvailabilityStatus.UNKNOWN
    assert "PAKET" in warning and "rolls" in warning
    assert required_stock_quantity(requested, candidate) is None
    assert warning == packaging.warnings[0]
    assert any(r.outcome is RuleOutcome.EXCLUDE for r in
               ConstraintEngine(load_default_policy()).evaluate(
                   line().model_copy(update={"quantity": requested}), candidate))


@pytest.mark.parametrize("quantity,unit", [(None, "pcs"), ("50", None), ("50", " ")])
def test_missing_request_quantity_or_unit_does_not_claim_missing_inventory(quantity, unit):
    candidate = item("410001001", "Article", on_hand=Decimal("60"))
    requested = QuantityValue(value=Decimal(quantity) if quantity else None, unit=unit)
    packaging = calculate_packaging(requested, candidate)
    status, warning = observed_availability(requested, candidate, packaging)
    assert status is AvailabilityStatus.UNKNOWN
    assert warning == packaging.warnings[0]
    assert "Requested" in warning and "missing" in warning
    assert candidate.stock.fulfillable_quantity == Decimal("60")
    assert required_stock_quantity(requested, candidate) is None
