"""Shared "raw text -> items" path for sources with no reliable table structure to key off of:
free-form PDF pages and Word documents. Tries the LLM fallback first (one call for the whole
text, not per line); if no API key is configured or the call fails, degrades further to a naive
per-line regex parse so the endpoint still returns *something* rather than failing the upload.
"""

from app.parsing.llm_extractor import LlmUnavailable, extract_items_with_llm
from app.parsing.text_heuristics import build_item, extract_quantity_and_unit
from app.parsing.types import CustomColumnSpec, ParsedDocument, ParsedLineItem


def extract_from_free_text(
    text: str,
    document: ParsedDocument,
    custom_columns: list[CustomColumnSpec] | None = None,
) -> list[ParsedLineItem]:
    try:
        llm_result = extract_items_with_llm(text, custom_columns=custom_columns)
        document.warnings.extend(llm_result.warnings)
        document.used_llm_fallback = True
        return llm_result.items
    except LlmUnavailable as exc:
        document.warnings.append(f"LLM fallback unavailable ({exc}); used naive text parsing")
        if custom_columns:
            document.warnings.append(
                "Custom columns could not be extracted without an LLM (naive text parsing only)"
            )
        return naive_line_parse(text)


def naive_line_parse(text: str) -> list[ParsedLineItem]:
    """Best-effort, no-LLM fallback: one candidate item per non-empty line with a number in it."""
    items = []
    for row_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or not any(char.isdigit() for char in stripped):
            continue

        quantity, unit = extract_quantity_and_unit(stripped)
        if quantity is None:
            continue

        items.append(
            build_item(
                name=stripped,
                quantity=quantity,
                unit=unit or "",
                row=row_number,
                excerpt=stripped,
                confidence=40,  # naive regex parse, no header/table context, no LLM - low trust
            )
        )
    return items
