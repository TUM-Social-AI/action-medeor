from functools import lru_cache

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
