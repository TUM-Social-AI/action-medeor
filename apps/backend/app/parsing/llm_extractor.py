"""LLM fallback extraction for documents whose layout isn't a clean, heuristically-parseable
table: free-form PDF pages and Word documents.

Used only when there's no reliable table structure to key column roles off of. One call per
document, not per line, to keep this bounded and cheap. Provider is chosen by
app.core.config.Settings.llm_provider ("anthropic" or "gemini") - Gemini exists as a free-tier
option for testing this pipeline before committing to a paid key; the schema/prompt/output
shape are shared, so swapping providers (or adding another one later, e.g. Azure) doesn't touch
callers. Requires the matching API key to be configured; callers must treat LlmUnavailable as an
expected, recoverable condition and fall back to the naive text parser.
"""

from pydantic import BaseModel

from app.core.config import Settings, get_settings
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
    text = raw_text.strip()
    if not text:
        raise LlmUnavailable("No text extracted from document to send to the LLM")

    prompt = _PROMPT.format(text=text[:_MAX_INPUT_CHARS])
    if settings.llm_provider == "gemini":
        result = _call_gemini(prompt, settings)
    else:
        result = _call_anthropic(prompt, settings)

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


def _call_anthropic(prompt: str, settings: Settings) -> _LlmExtractionResult:
    if not settings.anthropic_api_key:
        raise LlmUnavailable("ANTHROPIC_API_KEY is not configured")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.parse(
            model=settings.anthropic_extraction_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            output_format=_LlmExtractionResult,
        )
    except anthropic.APIError as exc:
        raise LlmUnavailable(f"Anthropic extraction call failed: {exc}") from exc

    return response.parsed_output


def _call_gemini(prompt: str, settings: Settings) -> _LlmExtractionResult:
    if not settings.gemini_api_key:
        raise LlmUnavailable("GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = client.models.generate_content(
            model=settings.gemini_extraction_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_LlmExtractionResult,
            ),
        )
    except genai_errors.APIError as exc:
        raise LlmUnavailable(f"Gemini extraction call failed: {exc}") from exc

    if response.parsed is not None:
        return response.parsed

    # The SDK couldn't map the response onto the schema automatically - fall back to parsing the
    # raw JSON text ourselves before giving up.
    try:
        return _LlmExtractionResult.model_validate_json(response.text)
    except Exception as exc:  # noqa: BLE001 - any parse failure here means "treat as unavailable"
        raise LlmUnavailable(f"Gemini response did not match the expected schema: {exc}") from exc
