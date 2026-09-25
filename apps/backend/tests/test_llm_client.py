"""Tests for provider selection and the OpenAI-family fallback parsing in llm_client.py.

No network calls here: missing-config checks are exercised through call_llm() directly, and the
structured-output/fallback-to-json_object logic in _run_openai_chat() (shared by the "openai" and
"azure_openai" providers) is exercised against a hand-rolled fake client shaped like the real
openai SDK's chat.completions resource, rather than the SDK itself.
"""

import pytest
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.parsing.llm_client import LlmUnavailable, _call_azure_openai, _run_openai_chat, call_llm


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """get_settings() is process-wide lru_cache'd - tests in this file mutate provider env vars,
    so the cache has to be cleared both before (pick up this test's env) and after (don't leak a
    test-only Settings object into whatever runs next)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Sample(BaseModel):
    value: str


def test_call_llm_requires_openai_api_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    # Explicitly blank rather than delenv: a developer's local .env may carry a real
    # OPENAI_API_KEY (e.g. while trying out a provider), and pydantic-settings falls back to the
    # .env file's value whenever the process environment has no key of that name at all - deleting
    # a var that was never set at the OS level wouldn't shadow that fallback. Setting it to ""
    # here does, since pydantic-settings takes any OS-level value over the .env file's.
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(LlmUnavailable, match="OPENAI_API_KEY"):
        call_llm("prompt", _Sample)


def test_call_llm_requires_azure_openai_api_key(monkeypatch) -> None:
    # See test_call_llm_requires_openai_api_key for why these are blanked via setenv rather than
    # delenv - it shadows a real value in a developer's local .env the same way.
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "")

    with pytest.raises(LlmUnavailable, match="AZURE_OPENAI_API_KEY"):
        call_llm("prompt", _Sample)


def test_call_llm_requires_azure_openai_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "")

    with pytest.raises(LlmUnavailable, match="AZURE_OPENAI_ENDPOINT"):
        call_llm("prompt", _Sample)


def test_call_llm_requires_azure_openai_deployment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "")

    with pytest.raises(LlmUnavailable, match="AZURE_OPENAI_DEPLOYMENT"):
        call_llm("prompt", _Sample)


# --- _run_openai_chat: shared by the "openai" and "azure_openai" providers, since both use the
# same openai SDK client shape. ---


class _FakeMessage:
    def __init__(self, parsed: object = None, content: str | None = None) -> None:
        self.parsed = parsed
        self.content = content


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [type("Choice", (), {"message": message})()]


class _FakeCompletions:
    """Stands in for client.chat.completions. parse_error, if given, is raised by parse() to
    simulate a provider that doesn't support structured-output mode - the real code treats ANY
    exception from parse() as "fall through to plain JSON", not just openai's own error types."""

    def __init__(
        self,
        *,
        parse_result: object = None,
        parse_error: Exception | None = None,
        create_content: str | None = None,
    ) -> None:
        self._parse_result = parse_result
        self._parse_error = parse_error
        self._create_content = create_content
        self.parse_called = False
        self.create_called = False
        self.parse_kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> _FakeResponse:
        self.parse_called = True
        self.parse_kwargs = kwargs
        if self._parse_error is not None:
            raise self._parse_error
        return _FakeResponse(_FakeMessage(parsed=self._parse_result))

    def create(self, **_kwargs: object) -> _FakeResponse:
        self.create_called = True
        return _FakeResponse(_FakeMessage(content=self._create_content))


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


def test_run_openai_chat_uses_native_structured_output_when_available() -> None:
    parsed = _Sample(value="ok")
    completions = _FakeCompletions(parse_result=parsed)
    client = _FakeClient(completions)

    result = _run_openai_chat(client, "some-model", "prompt", _Sample, "Test")

    assert result is parsed
    assert completions.create_called is False  # no need to fall back


def test_run_openai_chat_falls_back_to_json_object_mode_when_parse_unsupported() -> None:
    completions = _FakeCompletions(
        parse_error=RuntimeError("this provider doesn't support response_format=schema"),
        create_content='{"value": "fallback"}',
    )
    client = _FakeClient(completions)

    result = _run_openai_chat(client, "some-model", "prompt", _Sample, "Test")

    assert result == _Sample(value="fallback")
    assert completions.parse_called and completions.create_called


def test_run_openai_chat_raises_on_empty_fallback_content() -> None:
    completions = _FakeCompletions(parse_error=RuntimeError("x"), create_content=None)
    client = _FakeClient(completions)

    with pytest.raises(LlmUnavailable, match="empty response"):
        _run_openai_chat(client, "some-model", "prompt", _Sample, "Test")


def test_run_openai_chat_raises_on_malformed_fallback_content() -> None:
    completions = _FakeCompletions(parse_error=RuntimeError("x"), create_content="not json")
    client = _FakeClient(completions)

    with pytest.raises(LlmUnavailable, match="did not match the expected schema"):
        _run_openai_chat(client, "some-model", "prompt", _Sample, "Test")


@pytest.mark.parametrize(
    ("endpoint", "expected_base_url"),
    [
        ("https://foundry.example.test/", "https://foundry.example.test/openai/v1/"),
        ("https://foundry.example.test/openai/v1/", "https://foundry.example.test/openai/v1/"),
    ],
)
def test_azure_extraction_reuses_foundry_resource_and_chat_deployment(
    monkeypatch, endpoint: str, expected_base_url: str
) -> None:
    import openai

    parsed = _Sample(value="from Foundry")
    completions = _FakeCompletions(parse_result=parsed)
    client = _FakeClient(completions)
    client_options: dict[str, str] = {}

    def fake_openai(**kwargs: str) -> _FakeClient:
        client_options.update(kwargs)
        return client

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    settings = Settings(
        _env_file=None,
        azure_foundry_api_key="test-key",
        azure_foundry_endpoint=endpoint,
        azure_openai_api_key=None,
        azure_openai_endpoint=None,
        azure_openai_deployment="luna-chat",
    )

    result = _call_azure_openai("prompt", _Sample, settings)

    assert result is parsed
    assert client_options == {"api_key": "test-key", "base_url": expected_base_url}
    assert completions.parse_kwargs["model"] == "luna-chat"
