from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


class Settings(BaseSettings):
    app_env: str = "development"
    service_name: str = "allocura-backend"
    database_url: str = (
        "postgresql+asyncpg://allocura:allocura@localhost:5432/allocura"
    )
    cors_origins: str = ""
    embedding_provider: str = ""
    embedding_model_name: str = ""
    embedding_model_version: str = ""
    embedding_model_revision: str = "main"
    embedding_deployment: str = ""
    embedding_dimensions: int | None = None
    embedding_batch_size: int = 32
    azure_foundry_endpoint: str = ""
    azure_foundry_api_key: str = ""

    # Fallback extractor for documents whose layout isn't a clean, heuristically-parseable table
    # (free-form PDF pages, Word documents). Left unset in most environments; extraction
    # degrades to a lower-confidence naive parse. Same prompt/schema across every provider - see
    # app/parsing/llm_client.py for the dispatch and app/parsing/llm_extractor.py for the prompt.
    # - "gemini" is a free-tier option for testing this pipeline before committing to a paid key.
    # - "openai" is generic: it talks to OpenAI itself by default, or to anything else that speaks
    #   the same wire protocol (OpenRouter, Groq, Together, a self-hosted vLLM/Ollama endpoint...)
    #   when openai_base_url is set - the easiest way to try models from other companies without
    #   adding a provider per company.
    # - "azure_openai" is Azure OpenAI specifically: unlike plain "openai" with a base_url
    #   override, Azure needs its own request shape (api-key header, api-version query param,
    #   /deployments/{name}/ routing), which the SDK's dedicated AzureOpenAI client handles.
    llm_provider: Literal["anthropic", "gemini", "openai", "azure_openai"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_extraction_model: str = "claude-haiku-4-5"
    gemini_api_key: str | None = None
    gemini_extraction_model: str = "gemini-2.5-flash"

    openai_api_key: str | None = None
    openai_extraction_model: str = "gpt-4o-mini"
    # Leave unset to call OpenAI itself; set to try another OpenAI-wire-compatible provider, e.g.
    # https://openrouter.ai/api/v1 (in which case openai_extraction_model becomes that provider's
    # model id, e.g. "anthropic/claude-3.5-sonnet" or "meta-llama/llama-3.3-70b").
    openai_base_url: str | None = None

    azure_openai_api_key: str | None = None
    # Resource endpoint from the Azure portal, e.g. https://your-resource-name.openai.azure.com/
    azure_openai_endpoint: str | None = None
    # The deployment name you gave the model in Azure AI Foundry/OpenAI Studio (not the
    # underlying model name itself - e.g. a deployment named "Luna" pointing at gpt-4o).
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("embedding_dimensions", mode="before")
    @classmethod
    def empty_embedding_dimensions_are_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def cors_origin_list(self) -> list[str]:
        configured_origins = [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]
        if self.app_env.lower() == "production":
            return list(dict.fromkeys(configured_origins))

        return list(dict.fromkeys([*configured_origins, *LOCAL_CORS_ORIGINS]))

    @property
    def cors_origin_regex(self) -> str | None:
        if self.app_env.lower() == "production":
            return None

        return r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


@lru_cache
def get_settings() -> Settings:
    return Settings()
