from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///data/context.db"
    extraction_model: str | None = None
    embedding_model: str | None = None
    litellm_api_key: str | None = None
    enable_local_embedder: bool = False
    data_dir: str = "./data"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
