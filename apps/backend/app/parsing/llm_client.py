"""Shared LLM-calling plumbing: provider selection (Anthropic/Gemini/OpenAI-compatible/Azure
OpenAI) and structured-output parsing, generic over whatever Pydantic schema a caller wants back.
One call per document for every use of this module - see app.parsing.llm_extractor (free-text
item extraction) and app.parsing.llm_table_classifier (table column understanding).

Provider is chosen by app.core.config.Settings.llm_provider - every caller just calls call_llm()
and gets back an instance of whatever schema it asked for, regardless of provider. Gemini exists
as a free-tier option for testing before committing to a paid key; "openai" is the generic
option for trying other companies' models (see its docstring below); swapping providers, or
adding another one later, means adding one function here, not touching any caller.
"""

import json
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
    if settings.llm_provider == "openai":
        return _call_openai(prompt, schema, settings)
    if settings.llm_provider == "azure_openai":
        return _call_azure_openai(prompt, schema, settings)
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


def _call_openai(prompt: str, schema: type[T], settings: Settings) -> T:
    """Talks to OpenAI itself by default, or to any other provider that speaks the same wire
    protocol when openai_base_url is set - OpenRouter, Groq, Together, a self-hosted vLLM/Ollama
    endpoint, etc. This is the generic "try a different company's model" option: point
    openai_base_url at the provider and openai_extraction_model at whatever model id that
    provider expects, no code change needed."""
    if not settings.openai_api_key:
        raise LlmUnavailable("OPENAI_API_KEY is not configured")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
    return _run_openai_chat(client, settings.openai_extraction_model, prompt, schema, "OpenAI")


def _call_azure_openai(prompt: str, schema: type[T], settings: Settings) -> T:
    """Azure OpenAI needs its own client rather than just a base_url override on the plain OpenAI
    one: an "api-key" header instead of bearer auth, an api-version query param, and routing by
    deployment name (/deployments/{name}/...) rather than by model name - the AzureOpenAI client
    handles all of that. azure_openai_deployment is the name YOU gave the deployment in Azure AI
    Foundry/OpenAI Studio (e.g. "Luna"), not the underlying model's own name."""
    if not settings.azure_openai_api_key:
        raise LlmUnavailable("AZURE_OPENAI_API_KEY is not configured")
    if not settings.azure_openai_endpoint:
        raise LlmUnavailable("AZURE_OPENAI_ENDPOINT is not configured")
    if not settings.azure_openai_deployment:
        raise LlmUnavailable("AZURE_OPENAI_DEPLOYMENT is not configured")

    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    # Azure routes by deployment name, not model name - the "model" argument to chat.completions
    # is actually the deployment name here.
    return _run_openai_chat(
        client, settings.azure_openai_deployment, prompt, schema, "Azure OpenAI"
    )


def _run_openai_chat(client, model: str, prompt: str, schema: type[T], label: str) -> T:
    """Shared by _call_openai/_call_azure_openai, since both use the same openai SDK client
    shape. Tries the SDK's native structured-output parsing first (OpenAI's "strict JSON schema"
    mode) - many OpenAI-compatible providers don't support that mode, so on any failure this
    falls back to asking for a plain JSON object (with the schema spelled out in the prompt) and
    validating it by hand, the same fallback shape _call_gemini uses above."""
    from openai import APIError

    try:
        response = client.chat.completions.parse(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format=schema,
        )
        parsed = response.choices[0].message.parsed
        if parsed is not None:
            return parsed
    except Exception:  # noqa: BLE001 - structured-output mode is best-effort; fall through below
        pass

    schema_json = json.dumps(schema.model_json_schema())
    fallback_prompt = (
        f"{prompt}\n\nRespond with ONLY a single JSON object matching this JSON schema exactly - "
        f"no markdown fences, no commentary, no surrounding text:\n{schema_json}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": fallback_prompt}],
            response_format={"type": "json_object"},
        )
    except APIError as exc:
        raise LlmUnavailable(f"{label} call failed: {exc}") from exc

    content = response.choices[0].message.content
    if not content:
        raise LlmUnavailable(f"{label} returned an empty response")
    try:
        return schema.model_validate_json(content)
    except Exception as exc:  # noqa: BLE001 - any parse failure here means "treat as unavailable"
        raise LlmUnavailable(f"{label} response did not match the expected schema: {exc}") from exc
