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

_UNIT_ALIASES = {
    alias: canonical
    for canonical, aliases in {
        "piece": {
            "stück",
            "stueck",
            "st",
            "st.",
            "stk",
            "stk.",
            "pc",
            "pcs",
            "piece",
            "pieces",
            "pièce",
            "pièces",
        },
        "package": {
            "paket",
            "pakete",
            "packung",
            "packungen",
            "package",
            "packages",
            "pack",
            "packs",
            "pkg",
            "pkgs",
        },
        "bottle": {"flasche", "flaschen", "bottle", "bottles", "flacon", "flacons"},
        "pair": {"paar", "paare", "pair", "pairs", "paire", "paires"},
        "roll": {"rolle", "rollen", "roll", "rolls", "rouleau", "rouleaux"},
        "tube": {"tube", "tuben", "tubes"},
        "canister": {"kanister", "canister", "canisters", "jerrycan", "jerrycans"},
        "bucket": {"eimer", "bucket", "buckets"},
        "pallet": {"palette", "paletten", "pallet", "pallets"},
        "tablet": {"tablet", "tablets", "tab", "tabs", "tablette", "tabletten"},
        "capsule": {"capsule", "capsules", "cap", "caps", "kapsel", "kapseln"},
        "vial": {"vial", "vials", "vial(s)", "fläschchen"},
        "ampoule": {"ampoule", "ampoules", "ampule", "ampules", "amp", "amp.", "ampulle", "ampullen"},
        "sachet": {"sachet", "sachets", "beutel"},
        "suppository": {"suppository", "suppositories", "zäpfchen"},
        "inhaler": {"inhaler", "inhalers", "inhalator", "inhalatoren"},
        "test": {"test", "tests"},
        "kit": {"kit", "kits"},
        "set": {"set", "sets"},
    }.items()
    for alias in aliases
}


def normalized_unit(unit: str | None) -> str | None:
    value = unit.strip().casefold() if unit else None
    return _UNIT_ALIASES.get(value, value)


def _same_unit(left: str | None, right: str | None) -> bool:
    return bool(normalized_unit(left) and normalized_unit(left) == normalized_unit(right))


def calculate_packaging(requested: QuantityValue, item: InventoryItemV1) -> PackagingResult:
    if requested.value is None:
        return PackagingResult(
            status="unknown",
            warnings=("Requested quantity is missing; stock cannot be compared.",),
        )
    if not normalized_unit(requested.unit):
        return PackagingResult(
            status="unknown", warnings=("Requested unit is missing; stock cannot be compared.",)
        )
    package = item.package
    if (
        item.stock is not None
        and _same_unit(item.stock.unit, requested.unit)
        and (
            package is None
            or package.units_per_package is None
            or _same_unit(requested.unit, package.stock_unit)
            or not _same_unit(requested.unit, package.unit)
        )
    ):
        return PackagingResult(status="not_required", basis=package.package_label if package else None)
    if package is None or package.units_per_package is None:
        warning = "Units per package are not recorded; package conversion cannot be calculated."
        if item.stock and item.stock.unit and requested.unit:
            warning = (
                f"Available stock is recorded in {item.stock.unit}; the request is in "
                f"{requested.unit}. Units per package are needed to compare these quantities."
            )
        return PackagingResult(
            status="unknown",
            warnings=(warning,),
        )
    if _same_unit(requested.unit, package.stock_unit or "package"):
        return PackagingResult(status="not_required", basis=package.package_label)
    if not _same_unit(requested.unit, package.unit):
        return PackagingResult(
            status="unit_mismatch",
            warnings=("Requested and package units are not confirmed as comparable.",),
        )

    units_per_package = package.units_per_package
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
        basis=package.package_label,
        options=tuple(options),
        recommended_option=exact,
        warnings=()
        if exact
        else ("Rounding policy is not confirmed; no option was auto-selected.",),
    )


def required_stock_quantity(requested: QuantityValue, item: InventoryItemV1) -> Decimal | None:
    """Express the request in the ERP stock unit using confirmed conversions only."""
    if requested.value is None or not item.stock:
        return None
    if not normalized_unit(requested.unit) or not normalized_unit(item.stock.unit):
        return None
    if _same_unit(item.stock.unit, requested.unit):
        return requested.value
    package = item.package
    if package and package.units_per_package is not None:
        if _same_unit(item.stock.unit, package.stock_unit or "package") and _same_unit(requested.unit, package.unit):
            return requested.value / package.units_per_package
        if _same_unit(requested.unit, package.stock_unit or "package") and _same_unit(item.stock.unit, package.unit):
            return requested.value * package.units_per_package
    return None


def observed_availability(
    requested: QuantityValue,
    item: InventoryItemV1,
    packaging: PackagingResult,
) -> tuple[AvailabilityStatus, str | None]:
    stock = item.stock
    if stock is None or stock.fulfillable_quantity is None:
        return AvailabilityStatus.UNKNOWN, "Calculated availability is not available."
    if requested.value is None:
        return (
            AvailabilityStatus.UNKNOWN,
            "Requested quantity is missing; stock cannot be compared.",
        )
    if not normalized_unit(requested.unit):
        return AvailabilityStatus.UNKNOWN, "Requested unit is missing; stock cannot be compared."
    if not normalized_unit(stock.unit):
        return (
            AvailabilityStatus.UNKNOWN,
            "ERP stock unit is not confirmed; stock cannot be compared with the request.",
        )

    # Comparing exact quantities is separate from choosing a floor/ceil supply option.
    required = required_stock_quantity(requested, item)
    if required is None:
        return (
            AvailabilityStatus.UNKNOWN,
            packaging.warnings[0]
            if packaging.status == "unknown" and packaging.warnings
            else (
                f"Available stock is recorded in {stock.unit}; the request is in "
                f"{requested.unit}. A confirmed unit conversion is required."
            ),
        )
    if stock.fulfillable_quantity >= required:
        return AvailabilityStatus.ON_HAND_SUFFICIENT, None
    if stock.fulfillable_quantity > 0:
        return AvailabilityStatus.ON_HAND_PARTIAL, None
    return AvailabilityStatus.PROCUREMENT_INDICATED, None
