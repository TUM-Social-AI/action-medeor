"""LLM fallback extraction for PDFs whose layout isn't a clean, heuristically-parseable table.

Used only when app.parsing.table_parser.is_table_well_structured() says the extracted PDF text
doesn't look like a table (free-running prose, inconsistent columns, mixed languages). One call
per document, not per line, to keep this bounded and cheap. Requires ANTHROPIC_API_KEY to be
configured (app.core.config.Settings.anthropic_api_key); callers must treat LlmUnavailable as an
expected, recoverable condition and fall back to the naive text parser.
"""

from pydantic import BaseModel

from app.core.config import get_settings
from app.parsing.text_heuristics import build_item
from app.parsing.types import ParsedDocument, Priority


class LlmUnavailable(Exception):
    """Raised when the LLM fallback can't run (no API key) or the call itself fails."""


class _LlmLineItem(BaseModel):
    name: str
    quantity: int | None = None
    unit: str = ""
    notes: str = ""
    priority: Priority = "medium"
    source_excerpt: str = ""


class _LlmExtractionResult(BaseModel):
    items: list[_LlmLineItem]


_PROMPT = """\
You are extracting a medical supply request into structured line items from partner-submitted
document text. The text may be in English, German, French, or Arabic, and may be messy (OCR
artifacts, inconsistent formatting, free-running sentences instead of a table).

For each distinct requested item, extract:
- name: the item name, translated to English if the source language isn't English
- quantity: the requested amount as an integer, or null if not stated/illegible
- unit: the unit of measure (e.g. "caps", "vials", "bags"), translated to English, or "" if unclear
- notes: any qualifiers (packaging, sterility, brand preference, etc.), translated to English
- priority: "critical" | "high" | "medium" | "low", inferred from urgency language, default "medium"
- source_excerpt: the original text snippet (in its original language) this item was extracted from

Do not invent items that aren't in the text. If a field can't be determined, use null/"" rather
than guessing.

Document text:
---
{text}
---
"""

_MAX_INPUT_CHARS = 20_000  # keeps a single fallback call cheap and within a small model's comfort zone


def extract_items_with_llm(raw_text: str) -> ParsedDocument:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise LlmUnavailable("ANTHROPIC_API_KEY is not configured")

    text = raw_text.strip()
    if not text:
        raise LlmUnavailable("No text extracted from document to send to the LLM")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.parse(
            model=settings.anthropic_extraction_model,
            max_tokens=4096,
            messages=[
                {"role": "user", "content": _PROMPT.format(text=text[:_MAX_INPUT_CHARS])},
            ],
            output_format=_LlmExtractionResult,
        )
    except anthropic.APIError as exc:
        raise LlmUnavailable(f"LLM extraction call failed: {exc}") from exc

    result = response.parsed_output
    document = ParsedDocument(used_llm_fallback=True)
    for entry in result.items:
        document.items.append(
            build_item(
                name=entry.name,
                quantity=entry.quantity,
                unit=entry.unit,
                notes=entry.notes,
                priority=entry.priority,
                excerpt=entry.source_excerpt,
                # LLM extraction is read as lower-confidence than a clean detected table,
                # even when every field is present - it's a fallback, not a source of truth.
                confidence=75 if entry.quantity is not None and entry.unit else 55,
            )
        )
    document.rows_detected = len(document.items)
    return document
