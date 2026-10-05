"""Read current and legacy article metadata without changing historical versions."""

from typing import Any


def is_master_item(item_number: str, family_id: str | None) -> bool:
    return item_number.endswith("00") and not (family_id or "").strip()


def restriction_flags(attributes: dict[str, Any] | None) -> dict[str, bool]:
    attributes = attributes or {}
    return {
        name: (attributes.get(name) or {}).get("value") is True
        for name in ("blocked", "sales_blocked", "purchasing_blocked")
    }
