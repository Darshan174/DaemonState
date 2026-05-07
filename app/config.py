from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///data/context.db"
    extraction_model: str | None = None
    embedding_model: str | None = None
    litellm_api_key: str | None = None
    enable_local_embedder: bool = False
    data_dir: str = "./data"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_redirect_uri: str | None = None
    slack_managed_install_url: str | None = None
    encryption_key: str | None = None
    zoom_client_id: str | None = None
    zoom_client_secret: str | None = None
    zoom_redirect_uri: str | None = None
    public_base_url: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
