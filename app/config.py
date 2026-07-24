from __future__ import annotations

import json
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    release_sha: str = "dev"
    database_url: str = "sqlite+aiosqlite:///data/context.db"
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout_seconds: float = 30.0
    database_pool_recycle_seconds: int = 1800
    database_connect_timeout_seconds: float = 10.0
    database_statement_timeout_ms: int = 30_000
    migration_statement_timeout_ms: int = 0
    migration_lock_timeout_ms: int = 30_000
    auto_migrate: bool = True
    app_workers: int = 1
    extraction_model: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    pgvector_index_dimension: int | None = None
    pgvector_candidate_limit: int = 200
    allow_hashing_embedder: bool = False
    api_rate_limit_per_minute: int = 0
    auth_failure_rate_limit_per_minute: int = 20
    redis_url: str | None = None
    rate_limit_fail_open: bool = True
    sync_worker_lease_seconds: int = 300
    sync_worker_retry_base_seconds: int = 30
    sync_worker_retry_max_seconds: int = 900
    sync_worker_poll_interval_seconds: float = 2.0
    sync_worker_job_timeout_seconds: float = 1800.0
    sync_worker_metrics_port: int = 0
    sync_worker_health_file: str = "/tmp/context-engine-sync-worker.ready"
    sync_worker_health_interval_seconds: float = 15.0
    source_ingestion_sweep_limit: int = 10
    source_ingestion_timeout_seconds: float = 300.0
    source_ingestion_max_attempts: int = 5
    context_digest_cache_ttl_seconds: float = 30.0
    context_digest_cache_max_entries: int = 32
    litellm_api_key: str | None = None
    enable_local_embedder: bool = False
    data_dir: str = "./data"
    server_api_key: str | None = None
    # JSON object keyed by API token. Values are objects containing a stable
    # ``principal_id`` and a list of ``workspace_ids``. Tokens are resolved on
    # the server and are never accepted as caller-authored principal claims.
    principal_api_keys: str | None = None
    allowed_hosts: str = "*"
    cors_allowed_origins: str = ""
    trust_proxy_headers: bool = False
    allowed_repo_roots: str = ""
    max_request_body_bytes: int = 16 * 1024 * 1024
    api_docs_enabled: bool = True
    demo_endpoints_enabled: bool = True
    serve_frontend: bool = True
    metrics_enabled: bool = True
    metrics_bearer_token: str | None = None
    oauth_state_ttl_seconds: int = 600
    log_level: str = "INFO"
    log_format: str = "console"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_redirect_uri: str | None = None
    slack_managed_install_url: str | None = None
    encryption_key: str | None = None
    previous_encryption_keys: str | None = None
    zoom_client_id: str | None = None
    zoom_client_secret: str | None = None
    zoom_redirect_uri: str | None = None
    public_base_url: str | None = None
    codex_home: str | None = None
    claude_home: str | None = None
    opencode_home: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()


def comma_separated(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def production_configuration_errors(config: Settings = settings) -> list[str]:
    """Return fail-closed configuration errors for a production process."""
    if config.environment.strip().lower() != "production":
        return []

    errors: list[str] = []
    database_url = config.database_url.lower()
    if not database_url.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://")):
        errors.append("DATABASE_URL must use PostgreSQL in production")
    if config.auto_migrate:
        errors.append("AUTO_MIGRATE must be false; run the migration job before API replicas")
    if config.app_workers != 1:
        errors.append(
            "APP_WORKERS must be 1 until Prometheus multiprocess collection is configured"
        )
    if not config.server_api_key:
        errors.append("SERVER_API_KEY is required")
    if config.server_api_key and len(config.server_api_key) < 32:
        errors.append("SERVER_API_KEY must contain at least 32 characters")
    if config.principal_api_keys:
        errors.append(
            "PRINCIPAL_API_KEYS is not supported in production until every "
            "API and MCP operation has action-level tenant authorization"
        )
        try:
            bindings = json.loads(config.principal_api_keys)
        except (TypeError, json.JSONDecodeError):
            bindings = None
        if not isinstance(bindings, dict) or not bindings:
            errors.append("PRINCIPAL_API_KEYS must be a non-empty JSON object")
        elif any(len(str(token)) < 32 for token in bindings):
            errors.append("every PRINCIPAL_API_KEYS token must contain at least 32 characters")
    if not config.encryption_key:
        errors.append("ENCRYPTION_KEY is required")
    else:
        try:
            Fernet(config.encryption_key.encode("utf-8"))
        except (TypeError, ValueError):
            errors.append("ENCRYPTION_KEY must be a valid Fernet key")
    for previous_key in comma_separated(config.previous_encryption_keys):
        try:
            Fernet(previous_key.encode("utf-8"))
        except (TypeError, ValueError):
            errors.append(
                "PREVIOUS_ENCRYPTION_KEYS must contain only valid Fernet keys"
            )
            break
    if config.api_rate_limit_per_minute <= 0:
        errors.append("API_RATE_LIMIT_PER_MINUTE must be greater than zero")
    if config.auth_failure_rate_limit_per_minute <= 0:
        errors.append("AUTH_FAILURE_RATE_LIMIT_PER_MINUTE must be greater than zero")
    if not config.redis_url:
        errors.append("REDIS_URL is required for distributed rate limiting")
    if config.rate_limit_fail_open:
        errors.append("RATE_LIMIT_FAIL_OPEN must be false")
    hosts = comma_separated(config.allowed_hosts)
    if not hosts or "*" in hosts:
        errors.append("ALLOWED_HOSTS must explicitly list public hostnames")
    origins = comma_separated(config.cors_allowed_origins)
    if "*" in origins:
        errors.append("CORS_ALLOWED_ORIGINS cannot contain '*'")
    if not comma_separated(config.allowed_repo_roots):
        errors.append("ALLOWED_REPO_ROOTS must list at least one mounted repository root")
    if not config.public_base_url:
        errors.append("PUBLIC_BASE_URL is required")
    else:
        parsed = urlparse(config.public_base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            errors.append("PUBLIC_BASE_URL must be an absolute https URL")
    provider_settings = (
        (
            "GOOGLE",
            config.google_client_id,
            config.google_client_secret,
            config.google_redirect_uri,
        ),
        (
            "SLACK",
            config.slack_client_id,
            config.slack_client_secret,
            config.slack_redirect_uri,
        ),
        (
            "ZOOM",
            config.zoom_client_id,
            config.zoom_client_secret,
            config.zoom_redirect_uri,
        ),
    )
    for provider, client_id, client_secret, redirect_uri in provider_settings:
        configured = tuple(bool(str(value or "").strip()) for value in (
            client_id,
            client_secret,
            redirect_uri,
        ))
        if any(configured) and not all(configured):
            errors.append(
                f"{provider}_CLIENT_ID, {provider}_CLIENT_SECRET, and "
                f"{provider}_REDIRECT_URI must be configured together"
            )
        if redirect_uri:
            parsed = urlparse(redirect_uri)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username
                or parsed.password
            ):
                errors.append(f"{provider}_REDIRECT_URI must be an absolute https URL")
    if config.slack_managed_install_url:
        parsed = urlparse(config.slack_managed_install_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            errors.append("SLACK_MANAGED_INSTALL_URL must be an absolute https URL")
    if config.api_docs_enabled:
        errors.append("API_DOCS_ENABLED must be false")
    if config.demo_endpoints_enabled:
        errors.append("DEMO_ENDPOINTS_ENABLED must be false")
    if config.serve_frontend:
        errors.append(
            "SERVE_FRONTEND must be false until browser session authentication is implemented"
        )
    if not config.metrics_bearer_token or len(config.metrics_bearer_token) < 32:
        errors.append("METRICS_BEARER_TOKEN must contain at least 32 characters")
    if config.log_format.strip().lower() != "json":
        errors.append("LOG_FORMAT must be json")
    if config.max_request_body_bytes <= 0:
        errors.append("MAX_REQUEST_BODY_BYTES must be greater than zero")
    if config.database_statement_timeout_ms <= 0:
        errors.append("DATABASE_STATEMENT_TIMEOUT_MS must be greater than zero")
    if config.migration_statement_timeout_ms < 0:
        errors.append("MIGRATION_STATEMENT_TIMEOUT_MS cannot be negative")
    if config.migration_lock_timeout_ms <= 0:
        errors.append("MIGRATION_LOCK_TIMEOUT_MS must be greater than zero")
    if config.sync_worker_health_interval_seconds <= 0:
        errors.append("SYNC_WORKER_HEALTH_INTERVAL_SECONDS must be greater than zero")
    if config.source_ingestion_sweep_limit <= 0:
        errors.append("SOURCE_INGESTION_SWEEP_LIMIT must be greater than zero")
    if config.source_ingestion_timeout_seconds <= 0:
        errors.append("SOURCE_INGESTION_TIMEOUT_SECONDS must be greater than zero")
    if config.source_ingestion_max_attempts <= 0:
        errors.append("SOURCE_INGESTION_MAX_ATTEMPTS must be greater than zero")
    return errors


def validate_runtime_configuration(config: Settings = settings) -> None:
    errors = production_configuration_errors(config)
    if errors:
        formatted = "; ".join(errors)
        raise RuntimeError(f"Invalid production configuration: {formatted}")
