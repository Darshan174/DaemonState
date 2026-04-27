from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "Context Engine"
    environment: str = "development"
    api_prefix: str = "/api"
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine"
    )
    redis_url: str = "redis://localhost:6379/0"
    litellm_api_key: str | None = None
    litellm_api_base: str | None = None
    litellm_timeout_seconds: int = 45
    enable_default_provider_models: bool = False
    encryption_key: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_redirect_uri: str | None = None
    slack_managed_install_url: str | None = None
    zoom_client_id: str | None = None
    zoom_client_secret: str | None = None
    zoom_redirect_uri: str | None = None
    zoom_webhook_secret: str | None = None
    zoom_webhook_tolerance_seconds: int = 300
    zoom_api_base_url: str = "https://api.zoom.us/v2"
    zoom_oauth_base_url: str = "https://zoom.us"
    zoom_oauth_scopes: str = "recording:read:user"
    github_api_base_url: str = "https://api.github.com"
    oauth_state_ttl_seconds: int = 600
    celery_task_time_limit: int = 600  # 10 min hard kill per task
    eval_admin_token: str | None = None
    eval_allow_local_requests: bool = True
    extraction_model: str | None = None
    default_extraction_model: str = "openai/gpt-4.1-mini"
    extraction_temperature: float = 0.0
    extraction_max_facts_per_document: int = 12
    enable_regex_extraction_fallback: bool = True
    embedding_model: str | None = None
    default_embedding_model: str = "openai/text-embedding-3-large"
    embedding_dimensions: int = 1024
    enable_reranking: bool = True
    retrieval_semantic_weight: float = 2.25
    retrieval_authority_weight: float = 1.0
    retrieval_source_support_bonus: float = 0.12
    retrieval_current_truth_bonus: float = 0.35
    retrieval_approved_bonus: float = 0.15
    retrieval_needs_review_penalty: float = 0.45
    retrieval_stale_penalty: float = 0.15
    retrieval_min_semantic_score: float = 0.16
    authority_conflict_auto_resolve_margin: float = 0.15

    # Document truncation / chunking for extraction
    extraction_max_input_chars: int = 16_000
    extraction_chunk_size_chars: int = 8_000
    extraction_chunk_overlap_chars: int = 500

    # Batch embedding settings
    embedding_batch_size: int = 64

    # Dev / local embedder flag
    enable_local_embedder: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
