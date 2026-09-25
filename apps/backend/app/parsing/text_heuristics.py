"""Shared parsing helpers used by both the Excel and PDF table parsers."""

import re

from app.parsing.domain_inference import suggest_domain
from app.parsing.keywords import PRIORITY_TOKENS, PROCUREMENT_PRIORITY_TOKENS, UNIT_TOKENS
from app.parsing.types import ItemStatus, ParsedLineItem, Priority

# "2000 pcs", "2,000 pcs", "2000pcs", "500 Beutel" - number optionally followed by a unit word.
_QUANTITY_UNIT_RE = re.compile(
    r"(?P<qty>\d[\d.,]*)\s*(?P<unit>[a-zA-ZäöüÄÖÜß]+)?",
)

_UNIT_TOKEN_SET = {token.lower() for token in UNIT_TOKENS}


def parse_number(raw: object) -> int | None:
    """Best-effort coercion of a spreadsheet/PDF cell into an integer quantity."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return round(raw)

    text = str(raw).strip()
    if not text:
        return None

    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return None

    digits = match.group(0).replace(",", "").replace(".", "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def extract_quantity_and_unit(text: str) -> tuple[int | None, str | None]:
    """Pull a "<number> <unit>" expression out of a free-text line, e.g. "2000 pcs"."""
    for match in _QUANTITY_UNIT_RE.finditer(text):
        quantity = parse_number(match.group("qty"))
        unit_candidate = (match.group("unit") or "").strip().lower()
        if quantity is None:
            continue
        if unit_candidate in _UNIT_TOKEN_SET:
            return quantity, unit_candidate
    # Fall back to the first plain number even without a recognizable unit token.
    match = re.search(r"\d[\d.,]*", text)
    if match:
        return parse_number(match.group(0)), None
    return None, None


def detect_priority(text: str) -> Priority | None:
    lowered = text.lower()
    for token, priority in PRIORITY_TOKENS.items():
        if token in lowered:
            return priority
    return None


def detect_priority_from_column_value(text: str) -> Priority | None:
    """Maps a partner's own priority-tier wording, found in a dedicated priority column, onto
    our scale. Checks the procurement-specific vocabulary first, then falls back to the same
    urgency words detect_priority() recognizes (a column literally containing "High"/"Critical"
    already works via that set)."""
    lowered = text.lower()
    for token, priority in PROCUREMENT_PRIORITY_TOKENS.items():
        if token in lowered:
            return priority
    return detect_priority(text)


def classify_item(name: str, quantity: int | None, unit: str) -> tuple[ItemStatus, int]:
    """Derive a status + confidence score from how complete the extracted fields are."""
    if not name.strip():
        return "missing", 20
    if quantity is None:
        return "missing", 35
    if not unit.strip():
        return "needs_review", 60
    return "verified", 90


def build_item(
    *,
    name: str,
    quantity: int | None,
    unit: str,
    notes: str = "",
    item_number: str = "",
    shelf_life: str = "",
    attributes: dict[str, str] | None = None,
    priority: Priority | None = None,
    default_priority: Priority | None = None,
    page: int = 0,
    row: int = 0,
    excerpt: str = "",
    confidence: int | None = None,
    source_type: str = "",
    llm_domain: str | None = None,
) -> ParsedLineItem:
    status, default_confidence = classify_item(name, quantity, unit)
    return ParsedLineItem(
        name=name.strip(),
        quantity=quantity,
        unit=unit.strip(),
        notes=notes.strip(),
        item_number=item_number.strip(),
        shelf_life=shelf_life.strip(),
        attributes=dict(attributes or {}),
        # Precedence: an explicit column value, then a keyword found on this row's own text,
        # then the request-level hint (e.g. from "Besondere Informationen:"), then "medium".
        priority=priority or detect_priority(f"{name} {notes}") or default_priority or "medium",
        confidence=confidence if confidence is not None else default_confidence,
        status=status,
        domain=(
            llm_domain
            if llm_domain in {"medicine", "equipment"}
            else suggest_domain(name, unit, source_type=source_type)
        ),
        page=page,
        row=row,
        excerpt=excerpt.strip(),
    )
