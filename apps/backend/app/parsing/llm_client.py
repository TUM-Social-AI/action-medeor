"""Shared LLM-calling plumbing: provider selection (Anthropic/Gemini/OpenAI-compatible/Azure
OpenAI) and structured-output parsing, generic over whatever Pydantic schema a caller wants back.
Callers control when requests are needed: free-text extraction uses one document call, while
table extraction maps each distinct uncertain layout once and reuses validated mappings.

Provider is chosen by app.core.config.Settings.llm_provider - every caller just calls call_llm()
and gets back an instance of whatever schema it asked for, regardless of provider. Gemini exists
as a free-tier option for testing before committing to a paid key; "openai" is the generic
option for trying other companies' models (see its docstring below); swapping providers, or
adding another one later, means adding one function here, not touching any caller.
"""

import json
import logging
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 60


def _observed_request(operation, label):
    started = perf_counter()
    try:
        response = operation()
    except Exception as exc:
        logger.warning(
            "LLM request provider=%s duration=%.2fs failure=%s",
            label,
            perf_counter() - started,
            type(exc).__name__,
        )
        raise
    usage = getattr(response, "usage", None) or getattr(response, "usage_metadata", None)
    tokens = {
        key: getattr(usage, key, None)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "prompt_token_count",
            "candidates_token_count",
        )
    }
    logger.info(
        "LLM request provider=%s duration=%.2fs tokens=%s",
        label,
        perf_counter() - started,
        {k: v for k, v in tokens.items() if v is not None},
    )
    return response


T = TypeVar("T", bound=BaseModel)


class LlmUnavailable(Exception):
    """Raised when no LLM call can be made (no API key configured) or the call itself fails.
    Callers must treat this as an expected, recoverable condition and fall back to a
    deterministic parse rather than let it propagate."""


def call_llm(prompt: str, schema: type[T]) -> T:
    settings = get_settings()
    providers = {
        "gemini": _call_gemini,
        "openai": _call_openai,
        "azure_openai": _call_azure_openai,
        "anthropic": _call_anthropic,
    }
    try:
        result = providers[settings.llm_provider](prompt, schema, settings)
        return result if isinstance(result, schema) else schema.model_validate(result)
    except LlmUnavailable:
        raise
    except Exception as exc:
        logger.warning(
            "LLM response unavailable provider=%s failure=%s",
            settings.llm_provider,
            type(exc).__name__,
        )
        raise LlmUnavailable("Configured model could not provide a valid response") from exc


def _call_anthropic(prompt: str, schema: type[T], settings: Settings) -> T:
    if not settings.anthropic_api_key:
        raise LlmUnavailable("ANTHROPIC_API_KEY is not configured")

    import anthropic

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0
    )
    try:
        response = _observed_request(
            lambda: client.messages.parse(
                model=settings.anthropic_extraction_model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            ),
            "Anthropic",
        )
    except anthropic.APIError as exc:
        raise LlmUnavailable("Configured model request failed") from exc

    return response.parsed_output


def _call_gemini(prompt: str, schema: type[T], settings: Settings) -> T:
    if not settings.gemini_api_key:
        raise LlmUnavailable("GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_SECONDS * 1000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    try:
        response = _observed_request(
            lambda: client.models.generate_content(
                model=settings.gemini_extraction_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            ),
            "Gemini",
        )
    except genai_errors.APIError as exc:
        raise LlmUnavailable("Configured model request failed") from exc

    if response.parsed is not None:
        return response.parsed

    # The SDK couldn't map the response onto the schema automatically - fall back to parsing the
    # raw JSON text ourselves before giving up.
    try:
        return schema.model_validate_json(response.text)
    except Exception as exc:  # noqa: BLE001 - any parse failure here means "treat as unavailable"
        raise LlmUnavailable("Model response did not match the expected schema") from exc


def _call_openai(prompt: str, schema: type[T], settings: Settings) -> T:
    """Talks to OpenAI itself by default, or to any other provider that speaks the same wire
    protocol when openai_base_url is set - OpenRouter, Groq, Together, a self-hosted vLLM/Ollama
    endpoint, etc. This is the generic "try a different company's model" option: point
    openai_base_url at the provider and openai_extraction_model at whatever model id that
    provider expects, no code change needed."""
    if not settings.openai_api_key:
        raise LlmUnavailable("OPENAI_API_KEY is not configured")

    from openai import OpenAI

    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    return _run_openai_chat(client, settings.openai_extraction_model, prompt, schema, "OpenAI")


def _call_azure_openai(prompt: str, schema: type[T], settings: Settings) -> T:
    """Use Foundry's v1 chat API, with optional extraction-specific resource overrides.

    The model argument is the chat deployment name, which may differ from its model ID.
    Embedding and extraction deployments can share the same resource endpoint and API key.
    """
    api_key = settings.azure_openai_api_key or settings.azure_foundry_api_key
    endpoint = settings.azure_openai_endpoint or settings.azure_foundry_endpoint
    if not api_key:
        raise LlmUnavailable("AZURE_OPENAI_API_KEY or AZURE_FOUNDRY_API_KEY is not configured")
    if not endpoint:
        raise LlmUnavailable("AZURE_OPENAI_ENDPOINT or AZURE_FOUNDRY_ENDPOINT is not configured")
    if not settings.azure_openai_deployment:
        raise LlmUnavailable("AZURE_OPENAI_DEPLOYMENT is not configured")

    from openai import OpenAI

    base_url = endpoint.rstrip("/")
    if not base_url.endswith("/openai/v1"):
        base_url += "/openai/v1"
    client = OpenAI(
        api_key=api_key,
        base_url=base_url + "/",
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    return _run_openai_chat(
        client, settings.azure_openai_deployment, prompt, schema, "Azure OpenAI"
    )


def _run_openai_chat(client, model: str, prompt: str, schema: type[T], label: str) -> T:
    """One structured-output attempt; JSON retry only for unsupported schema mode."""
    from openai import APIError

    try:
        response = _observed_request(
            lambda: client.chat.completions.parse(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format=schema,
            ),
            label,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise LlmUnavailable("Model returned no structured response")
        return parsed
    except APIError as exc:
        message = str(exc).lower()
        unsupported_schema = (
            getattr(exc, "status_code", None) in {400, 422}
            and any(word in message for word in ("not supported", "unsupported"))
            and any(
                word in message for word in ("response_format", "json_schema", "structured output")
            )
        )
        if not unsupported_schema:
            raise LlmUnavailable("Configured model request failed") from exc
    except LlmUnavailable:
        raise
    except Exception as exc:
        raise LlmUnavailable("Model response did not match the expected schema") from exc

    schema_json = json.dumps(schema.model_json_schema())
    fallback_prompt = (
        f"{prompt}\n\nRespond with ONLY a single JSON object matching this JSON schema exactly - "
        f"no markdown fences, no commentary, no surrounding text:\n{schema_json}"
    )
    try:
        response = _observed_request(
            lambda: client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": fallback_prompt}],
                response_format={"type": "json_object"},
            ),
            label,
        )
    except APIError as exc:
        raise LlmUnavailable("Configured model request failed") from exc

    content = response.choices[0].message.content
    if not content:
        raise LlmUnavailable(f"{label} returned an empty response")
    try:
        return schema.model_validate_json(content)
    except Exception as exc:  # noqa: BLE001 - any parse failure here means "treat as unavailable"
        raise LlmUnavailable("Model response did not match the expected schema") from exc
