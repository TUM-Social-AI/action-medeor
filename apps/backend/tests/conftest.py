import pytest


@pytest.fixture(autouse=True)
def _no_real_llm_calls(monkeypatch):
    """Table uploads now ask the configured model first, so a developer's local .env (with a real
    provider key) would otherwise make tests slow, paid and nondeterministic. Tests that need a
    model stub call_llm themselves; everything else exercises the keyword fallback, exactly like
    CI, which has no provider key."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
