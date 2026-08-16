from app.core.config import LOCAL_CORS_ORIGINS, Settings


def test_development_includes_local_cors_origins() -> None:
    settings = Settings(app_env="development", cors_origins="https://example.test")

    assert settings.cors_origin_list == ["https://example.test", *LOCAL_CORS_ORIGINS]
    assert settings.cors_origin_regex is not None


def test_production_has_no_implicit_cors_origins() -> None:
    settings = Settings(app_env="production", cors_origins="")

    assert settings.cors_origin_list == []
    assert settings.cors_origin_regex is None


def test_production_uses_only_explicit_cors_origins() -> None:
    settings = Settings(
        app_env="production",
        cors_origins="https://one.example, https://two.example,https://one.example",
    )

    assert settings.cors_origin_list == ["https://one.example", "https://two.example"]
