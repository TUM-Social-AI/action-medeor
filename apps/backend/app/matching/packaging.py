"""Reversible pack calculations without assuming an unconfirmed rounding rule."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.matching.contracts import (
    AvailabilityStatus,
    InventoryItemV1,
    PackagingOption,
    PackagingResult,
    QuantityValue,
)


def _same_unit(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.strip().casefold() == right.strip().casefold())


def calculate_packaging(requested: QuantityValue, item: InventoryItemV1) -> PackagingResult:
    if requested.value is None:
        return PackagingResult(
            status="unknown",
            warnings=("Requested quantity is not normalized.",),
        )
    if item.package is None or item.package.units_per_package is None:
        return PackagingResult(
            status="unknown",
            warnings=("Candidate package size is not available.",),
        )
    if not _same_unit(requested.unit, item.package.unit):
        return PackagingResult(
            status="unit_mismatch",
            warnings=("Requested and package units are not confirmed as comparable.",),
        )

    units_per_package = item.package.units_per_package
    exact_packages = requested.value / units_per_package
    floor_packages = int(exact_packages.to_integral_value(rounding=ROUND_FLOOR))
    ceil_packages = int(exact_packages.to_integral_value(rounding=ROUND_CEILING))

    options: list[PackagingOption] = []
    for package_count, direction in (
        (floor_packages, "down"),
        (ceil_packages, "up"),
    ):
        total = units_per_package * Decimal(package_count)
        option = PackagingOption(
            packages=package_count,
            total_units=total,
            difference=total - requested.value,
            direction="exact" if total == requested.value else direction,
        )
        if option not in options:
            options.append(option)

    exact = next((option for option in options if option.direction == "exact"), None)
    return PackagingResult(
        status="calculated",
        options=tuple(options),
        recommended_option=exact,
        warnings=()
        if exact
        else ("Rounding policy is not confirmed; no option was auto-selected.",),
    )


def observed_availability(
    requested: QuantityValue,
    item: InventoryItemV1,
    packaging: PackagingResult,
) -> tuple[AvailabilityStatus, str | None]:
    stock = item.stock
    if stock is None or stock.on_hand is None:
        return AvailabilityStatus.UNKNOWN, "On-hand stock is not available."

    required: Decimal | None = None
    if _same_unit(stock.unit, requested.unit) and requested.value is not None:
        required = requested.value
    elif stock.unit and stock.unit.casefold() == "package" and packaging.recommended_option:
        required = Decimal(packaging.recommended_option.packages)

    if required is None:
        return (
            AvailabilityStatus.UNKNOWN,
            "Stock basis is not confirmed as comparable with the requested quantity.",
        )
    if stock.on_hand >= required:
        return AvailabilityStatus.ON_HAND_SUFFICIENT, None
    if stock.on_hand > 0:
        return AvailabilityStatus.ON_HAND_PARTIAL, None
    return AvailabilityStatus.PROCUREMENT_INDICATED, None
