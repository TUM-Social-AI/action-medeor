"""Shared LLM-calling plumbing: provider selection (Anthropic/Gemini) and structured-output
parsing, generic over whatever Pydantic schema a caller wants back. One call per document for
every use of this module - see app.parsing.llm_extractor (free-text item extraction) and
app.parsing.llm_table_classifier (table column understanding).

Provider is chosen by app.core.config.Settings.llm_provider. Gemini exists as a free-tier option
for testing before committing to a paid key; swapping providers (or adding another one later,
e.g. Azure) means adding one function here, not touching any caller.
"""

from typing import TypeVar

from pydantic import BaseModel

from app.core.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LlmUnavailable(Exception):
    """Raised when no LLM call can be made (no API key configured) or the call itself fails.
    Callers must treat this as an expected, recoverable condition and fall back to a
    deterministic parse rather than let it propagate."""


def call_llm(prompt: str, schema: type[T]) -> T:
    settings = get_settings()
    if settings.llm_provider == "gemini":
        return _call_gemini(prompt, schema, settings)
    return _call_anthropic(prompt, schema, settings)


def _call_anthropic(prompt: str, schema: type[T], settings: Settings) -> T:
    if not settings.anthropic_api_key:
        raise LlmUnavailable("ANTHROPIC_API_KEY is not configured")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.parse(
            model=settings.anthropic_extraction_model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
    except anthropic.APIError as exc:
        raise LlmUnavailable(f"Anthropic call failed: {exc}") from exc

    return response.parsed_output


def _call_gemini(prompt: str, schema: type[T], settings: Settings) -> T:
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
                response_schema=schema,
            ),
        )
    except genai_errors.APIError as exc:
        raise LlmUnavailable(f"Gemini call failed: {exc}") from exc

    if response.parsed is not None:
        return response.parsed

    # The SDK couldn't map the response onto the schema automatically - fall back to parsing the
    # raw JSON text ourselves before giving up.
    try:
        return schema.model_validate_json(response.text)
    except Exception as exc:  # noqa: BLE001 - any parse failure here means "treat as unavailable"
        raise LlmUnavailable(f"Gemini response did not match the expected schema: {exc}") from exc
