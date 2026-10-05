"""Read the ERP's final comma-separated pack count, without using doses or dimensions."""

from __future__ import annotations

import re
from decimal import Decimal

from app.matching.contracts import ProductPackage
from app.matching.packaging import normalized_unit

_INTEGER = r"(?:[1-9]\d{0,2}(?:\.\d{3})+|[1-9]\d*)"
_SUFFIX = re.compile(
    rf"(?P<count>{_INTEGER}(?:\s*[x×*]\s*{_INTEGER})*)\s*(?P<unit>[^\W\d_]+\.?)?",
    re.IGNORECASE,
)
_COUNT_UNITS = {
    "piece", "tablet", "capsule", "bottle", "vial", "ampoule", "sachet",
    "suppository", "inhaler", "pair", "roll", "tube", "test", "kit", "set",
}
_STOCK_UNITS = {"package", "dose", "bottle", "piece", "pair", "roll", "tube",
                "canister", "bucket", "pallet"}
_DOZENS = {"dz", "dz.", "dzd", "dzd.", "dtz", "dtz.", "dtzd", "dtzd.",
           "dutzend", "dozen", "dozens"}


def package_from_erp_description(description: str, base_unit: str | None) -> ProductPackage | None:
    """The name convention is ERP-specific; translations are never used as a fallback."""
    if normalized_unit(base_unit) not in _STOCK_UNITS:
        return None
    prefix, separator, suffix = description.strip().rpartition(",")
    if not separator or not prefix.strip() or not suffix.strip():
        return None
    # A decimal comma within the final measurement is not a pack-count separator.
    if prefix[-1:].isdigit() and suffix[:1].isdigit():
        return None
    match = _SUFFIX.fullmatch(suffix.strip())
    if match is None:
        return None
    count = Decimal(1)
    for factor in re.split(r"\s*[x×*]\s*", match["count"]):
        count *= Decimal(factor.replace(".", ""))
    if match["unit"]:
        unit = normalized_unit(match["unit"])
        if unit in _DOZENS:
            count *= 12
            unit = "piece"
        elif unit not in _COUNT_UNITS:
            return None
    else:
        units = {
            normalized_unit(word)
            for word in re.findall(r"[^\W\d_]+\.?", prefix)
            if normalized_unit(word) in _COUNT_UNITS
        }
        if len(units) != 1:
            return None
        unit = units.pop()
    # A stock unit cannot simultaneously represent itself and several of itself.
    if normalized_unit(base_unit) == unit and count != 1:
        return None
    return ProductPackage(
        units_per_package=count,
        unit=unit,
        stock_unit=base_unit,
        package_label=f"{count} {unit if count == 1 else unit + 's'} per {base_unit} (ERP description)",
    )
