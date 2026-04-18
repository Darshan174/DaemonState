"""Read-only operator status endpoints for self-hosted deployments."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from celery import Celery
from fastapi import APIRouter
from pydantic import BaseModel, Field
from redis import asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import settings
from app.database import engine
from app.processing.embedder import _resolved_embedding_model
from app.processing.extractor import _resolved_extraction_model
from app.services.llm_service import has_live_litellm_api_key
from app.tasks.celery_app import celery_app


CheckStatus = Literal["ok", "error", "unknown"]

router = APIRouter(prefix="/operator", tags=["operator"])


class StatusCheck(BaseModel):
    status: CheckStatus
    latency_ms: float | None = Field(default=None, serialization_alias="latencyMs")
    detail: str | None = None


class DatabaseStatus(StatusCheck):
    url_scheme: str = Field(serialization_alias="urlScheme")


class RedisStatus(StatusCheck):
    url_scheme: str = Field(serialization_alias="urlScheme")


class CeleryStatus(StatusCheck):
    queue_depth: int | None = Field(default=None, serialization_alias="queueDepth")
    workers_online: int | None = Field(default=None, serialization_alias="workersOnline")


class MigrationStatus(StatusCheck):
    current_revision: str | None = Field(default=None, serialization_alias="currentRevision")
    head_revision: str | None = Field(default=None, serialization_alias="headRevision")
    up_to_date: bool | None = Field(default=None, serialization_alias="upToDate")


class OperatorChecks(BaseModel):
    database: DatabaseStatus
    redis: RedisStatus
    celery: CeleryStatus
    migrations: MigrationStatus


class EmbeddingConfig(BaseModel):
    provider: str
    model: str | None = None
    dimensions: int
    batch_size: int = Field(serialization_alias="batchSize")
    local_embedder_enabled: bool = Field(serialization_alias="localEmbedderEnabled")


class ExtractionConfig(BaseModel):
    provider: str
    model: str | None = None
    regex_fallback_enabled: bool = Field(serialization_alias="regexFallbackEnabled")
    max_facts_per_document: int = Field(serialization_alias="maxFactsPerDocument")
    max_input_chars: int = Field(serialization_alias="maxInputChars")
    chunk_size_chars: int = Field(serialization_alias="chunkSizeChars")
    chunk_overlap_chars: int = Field(serialization_alias="chunkOverlapChars")


class ModelStatusConfig(BaseModel):
    provider_api_configured: bool = Field(serialization_alias="providerApiConfigured")
    default_provider_models_enabled: bool = Field(
        serialization_alias="defaultProviderModelsEnabled"
    )
    litellm_api_base_configured: bool = Field(serialization_alias="litellmApiBaseConfigured")
    litellm_timeout_seconds: int = Field(serialization_alias="litellmTimeoutSeconds")
    embedding: EmbeddingConfig
    extraction: ExtractionConfig


class OperatorStatusResponse(BaseModel):
    status: Literal["ok", "degraded"]
    project_name: str = Field(serialization_alias="projectName")
    environment: str
    checked_at: datetime = Field(serialization_alias="checkedAt")
    checks: OperatorChecks
    models: ModelStatusConfig


@router.get("/status", response_model=OperatorStatusResponse, response_model_by_alias=True)
async def get_operator_status() -> OperatorStatusResponse:
    database, redis_status, celery, migrations = await asyncio.gather(
        _check_database(engine),
        _check_redis(),
        _check_celery(),
        _check_migrations(engine),
    )
    overall_status: Literal["ok", "degraded"] = (
        "ok"
        if all(
            check.status == "ok"
            for check in (database, redis_status, migrations)
        )
        else "degraded"
    )
    return OperatorStatusResponse(
        status=overall_status,
        project_name=settings.project_name,
        environment=settings.environment,
        checked_at=datetime.now(UTC),
        checks=OperatorChecks(
            database=database,
            redis=redis_status,
            celery=celery,
            migrations=migrations,
        ),
        models=_model_status_config(),
    )


async def _check_database(db_engine: AsyncEngine) -> DatabaseStatus:
    start = perf_counter()
    try:
        async with db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        return DatabaseStatus(
            status="error",
            latency_ms=_elapsed_ms(start),
            detail=exc.__class__.__name__,
            url_scheme=_url_scheme(settings.database_url),
        )
    return DatabaseStatus(
        status="ok",
        latency_ms=_elapsed_ms(start),
        url_scheme=_url_scheme(settings.database_url),
    )


async def _check_redis() -> RedisStatus:
    start = perf_counter()
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    except Exception as exc:
        return RedisStatus(
            status="error",
            latency_ms=_elapsed_ms(start),
            detail=exc.__class__.__name__,
            url_scheme=_url_scheme(settings.redis_url),
        )
    finally:
        await redis_client.aclose()
    return RedisStatus(
        status="ok",
        latency_ms=_elapsed_ms(start),
        url_scheme=_url_scheme(settings.redis_url),
    )


async def _check_celery() -> CeleryStatus:
    start = perf_counter()
    try:
        queue_depth = await _celery_queue_depth()
        workers_online = await _celery_workers_online(celery_app)
    except Exception as exc:
        return CeleryStatus(
            status="unknown",
            latency_ms=_elapsed_ms(start),
            detail=exc.__class__.__name__,
        )

    return CeleryStatus(
        status="ok" if workers_online else "unknown",
        latency_ms=_elapsed_ms(start),
        queue_depth=queue_depth,
        workers_online=workers_online,
        detail=None if workers_online else "No Celery workers responded",
    )


async def _celery_queue_depth() -> int:
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        queue_name = str(celery_app.conf.task_default_queue or "celery")
        return int(await redis_client.llen(queue_name))
    finally:
        await redis_client.aclose()


async def _celery_workers_online(app: Celery) -> int:
    def _ping_workers() -> int:
        responses = app.control.inspect(timeout=0.5).ping() or {}
        return len(responses)

    return await asyncio.wait_for(asyncio.to_thread(_ping_workers), timeout=1.5)


async def _check_migrations(db_engine: AsyncEngine) -> MigrationStatus:
    start = perf_counter()
    head_revision = _alembic_head_revision()
    try:
        async with db_engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            current_revision = result.scalar_one_or_none()
    except Exception as exc:
        return MigrationStatus(
            status="unknown",
            latency_ms=_elapsed_ms(start),
            detail=exc.__class__.__name__,
            current_revision=None,
            head_revision=head_revision,
            up_to_date=None,
        )

    up_to_date = current_revision == head_revision
    return MigrationStatus(
        status="ok" if up_to_date else "error",
        latency_ms=_elapsed_ms(start),
        current_revision=current_revision,
        head_revision=head_revision,
        up_to_date=up_to_date,
        detail=None if up_to_date else "Database revision does not match Alembic head",
    )


def _alembic_head_revision() -> str | None:
    try:
        config = Config("alembic.ini")
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
    except Exception:
        return None
    if len(heads) == 1:
        return heads[0]
    return ",".join(sorted(heads)) if heads else None


def _model_status_config() -> ModelStatusConfig:
    embedding_model = _resolved_embedding_model()
    extraction_model = _resolved_extraction_model()
    live_api_key = has_live_litellm_api_key()
    return ModelStatusConfig(
        provider_api_configured=live_api_key,
        default_provider_models_enabled=settings.enable_default_provider_models,
        litellm_api_base_configured=bool(settings.litellm_api_base),
        litellm_timeout_seconds=settings.litellm_timeout_seconds,
        embedding=EmbeddingConfig(
            provider=_embedding_provider(embedding_model),
            model=embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
            local_embedder_enabled=settings.enable_local_embedder,
        ),
        extraction=ExtractionConfig(
            provider=_extraction_provider(extraction_model),
            model=extraction_model,
            regex_fallback_enabled=settings.enable_regex_extraction_fallback,
            max_facts_per_document=settings.extraction_max_facts_per_document,
            max_input_chars=settings.extraction_max_input_chars,
            chunk_size_chars=settings.extraction_chunk_size_chars,
            chunk_overlap_chars=settings.extraction_chunk_overlap_chars,
        ),
    )


def _embedding_provider(model: str | None) -> str:
    if model:
        return "litellm"
    if settings.enable_local_embedder:
        return "local"
    if settings.environment == "production":
        return "unconfigured"
    return "hashing"


def _extraction_provider(model: str | None) -> str:
    if model:
        return "structured_llm"
    if settings.environment == "production":
        return "unconfigured"
    return "regex"


def _url_scheme(url: str) -> str:
    return url.split(":", 1)[0]


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
