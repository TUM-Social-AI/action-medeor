"""Authoritative ERP restrictions, shared by retrieval and final validation."""

from app.catalog.state import is_master_item
from app.matching.contracts import AvailabilityStatus, InquiryLineV1, InventoryItemV1
from app.matching.packaging import calculate_packaging, observed_availability


def erp_exclusion(line: InquiryLineV1, item: InventoryItemV1) -> tuple[str, str] | None:
    if is_master_item(item.item_number, item.family_id):
        return "master_item", "Stammartikel is a base article, not sellable inventory."
    if item.blocked:
        return "item_blocked", "The ERP marks this article suspended (Gesperrt)."
    if item.sales_blocked:
        return "sales_blocked", "The ERP blocks sales of this article (Verkauf gesperrt)."
    if item.purchasing_blocked:
        status, _ = observed_availability(
            line.quantity, item, calculate_packaging(line.quantity, item)
        )
        if (
            line.quantity.value is None
            or line.quantity.value <= 0
            or status is not AvailabilityStatus.ON_HAND_SUFFICIENT
        ):
            return (
                "purchasing_blocked_insufficient_stock",
                "Purchasing is blocked and stock cannot cover the full requested quantity.",
            )
    return None
