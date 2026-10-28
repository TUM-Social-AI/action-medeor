"""Stable codes for parser, AI and legacy findings. Never group by prose."""

CATEGORIES = {
    "type_required": "type",
    "type_conflict": "type",
    "quantity_required": "quantity",
    "quantity_invalid": "quantity",
    "quantity_conflict": "totals",
    "pack_total_conflict": "totals",
    "unit_unclear": "unit",
    "unit_conflict": "unit",
    "packaging_unclear": "unit",
    "name_required": "description",
    "name_unclear": "description",
    "mapping_uncertain": "source",
    "non_item_row": "source",
    "coverage_uncertain": "source",
    "low_confidence": "other",
    "confirmation_required": "other",
    "other": "other",
}
FIELDS = {
    "type": ["domain"],
    "quantity": ["quantity"],
    "totals": ["quantity", "unit"],
    "unit": ["unit"],
    "description": ["name"],
    "source": [],
    "other": [],
}


def classify(reason: str, code: str | None = None) -> str:
    if code in CATEGORIES and code != "other":
        return code
    text = reason.casefold()
    if "confirm this item against the source" in text:
        return "confirmation_required"
    if "packs ×" in text or "pack" in text and "total" in text and "conflict" in text:
        return "pack_total_conflict"
    if "mapping" in text or "column" in text and ("unclear" in text or "confirm" in text):
        return "mapping_uncertain"
    if "missing row" in text or "extra row" in text or "missing item" in text:
        return "coverage_uncertain"
    if "name" in text or "description" in text or "identifier" in text:
        return "name_required" if "required" in text else "name_unclear"
    if "type" in text or "classification" in text:
        return (
            "type_conflict"
            if any(t in text for t in ("differ", "conflict", "protected"))
            else "type_required"
        )
    if "packaging" in text or "pack quantity" in text:
        return "packaging_unclear"
    if "unit" in text:
        return (
            "unit_conflict"
            if any(t in text for t in ("differ", "conflict", "protected"))
            else "unit_unclear"
        )
    if "quantity" in text or "requested total" in text:
        if any(t in text for t in ("differ", "conflict", "protected")):
            return "quantity_conflict"
        return (
            "quantity_invalid"
            if any(t in text for t in ("invalid", "whole number", "positive", "not a valid"))
            else "quantity_required"
        )
    if "confidence" in text:
        return "low_confidence"
    return "other"
