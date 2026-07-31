from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
import secrets
import time
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.api.router import api_router
from app.config import comma_separated, settings, validate_runtime_configuration
from app.database import engine, schema_is_current
from app.http_middleware import RequestBodyLimitMiddleware
from app.migrations import run_migrations
from app.models import Base
from app.observability import (
    HTTP_RATE_LIMITED,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    HTTP_REQUESTS_IN_PROGRESS,
    READINESS,
    configure_logging,
    normalized_http_method,
    request_id_context,
)
from app.services.auth import (
    RateLimitBackendUnavailable,
    api_auth_enabled,
    api_rate_limit_enabled,
    check_api_rate_limit_async,
    close_rate_limit_backend,
    rate_limit_backend_ready,
    request_has_valid_api_key,
    request_access_scope,
)
from app.services.credentials import (
    CredentialStoreError,
    validate_connector_credentials,
)
from app.services.oauth_state import close_oauth_state_backend
from app.telemetry import configure_telemetry, shutdown_telemetry

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
logger = logging.getLogger("daemonstate.api")
_startup_complete = False
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_OAUTH_CALLBACK_PATHS = {
    "/api/connectors/slack/callback",
    "/api/connectors/gdrive/callback",
    "/api/connectors/gmail/callback",
    "/api/connectors/google/callback",
    "/api/connectors/zoom/callback",
}
_PUBLIC_API_REQUESTS = {
    ("POST", "/api/waitlist"),
}

_NAIVE_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$"
)


def _serialize_utc_timestamps(value, *, field_name: str | None = None):
    """Mark UTC database timestamps as UTC instead of browser-local time."""
    if isinstance(value, dict):
        return {
            key: _serialize_utc_timestamps(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_serialize_utc_timestamps(item, field_name=field_name) for item in value]
    if (
        isinstance(value, str)
        and field_name
        and (field_name.endswith("_at") or field_name.endswith("At"))
        and _NAIVE_ISO_DATETIME.fullmatch(value)
    ):
        return f"{value}Z"
    return value


class UTCJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return super().render(_serialize_utc_timestamps(content))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_complete
    configure_logging()
    validate_runtime_configuration()
    configure_telemetry(settings)
    try:
        if settings.auto_migrate:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await run_migrations(conn)
        else:
            async with engine.connect() as conn:
                if not await schema_is_current(conn):
                    raise RuntimeError(
                        "Database schema is not at the expected Alembic revision; "
                        "run `daemonstate db deploy` before starting API replicas."
                    )
                if settings.environment.strip().lower() == "production":
                    await validate_connector_credentials(conn)
        _startup_complete = True
        logger.info(
            "api_started",
            extra={
                "environment": settings.environment,
                "release_sha": settings.release_sha,
            },
        )
        yield
    finally:
        _startup_complete = False
        try:
            await close_rate_limit_backend()
            await close_oauth_state_backend()
            await engine.dispose()
            logger.info("api_stopped")
        finally:
            shutdown_telemetry()


app = FastAPI(
    title="DaemonState",
    lifespan=lifespan,
    default_response_class=UTCJSONResponse,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

allowed_hosts = comma_separated(settings.allowed_hosts)
if allowed_hosts and "*" not in allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

cors_origins = comma_separated(settings.cors_allowed_origins)

app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.max_request_body_bytes,
)


@app.middleware("http")
async def request_controls(request: Request, call_next):
    started = time.perf_counter()
    supplied_request_id = request.headers.get("x-request-id", "").strip()
    request_id = (
        supplied_request_id
        if _REQUEST_ID.fullmatch(supplied_request_id)
        else uuid4().hex
    )
    request.state.request_id = request_id
    context_token = request_id_context.set(request_id)
    HTTP_REQUESTS_IN_PROGRESS.inc()
    response: Response | None = None
    rate_limit = 0
    rate_remaining: int | None = None
    status_code = 500

    if request.url.path.startswith("/api") and request.method != "OPTIONS":
        access_scope = request_access_scope(request)
        is_oauth_callback = request.url.path in _OAUTH_CALLBACK_PATHS
        is_public_api_request = (
            request.method.upper(),
            request.url.path,
        ) in _PUBLIC_API_REQUESTS
        if (
            api_auth_enabled()
            and not is_oauth_callback
            and not is_public_api_request
            and not request_has_valid_api_key(request)
        ):
            try:
                allowed, retry_after, remaining = await check_api_rate_limit_async(
                    request,
                    limit=settings.auth_failure_rate_limit_per_minute,
                    namespace="auth-failure",
                    key_by_ip=True,
                )
            except RateLimitBackendUnavailable:
                response = _service_unavailable_response(request_id)
            else:
                if not allowed:
                    HTTP_RATE_LIMITED.labels(kind="auth_failure").inc()
                    response = JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={"detail": "Too many failed authentication attempts."},
                        headers={
                            "Retry-After": str(retry_after),
                            "X-RateLimit-Limit": str(
                                settings.auth_failure_rate_limit_per_minute
                            ),
                            "X-RateLimit-Remaining": str(remaining),
                        },
                    )
                else:
                    response = JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Invalid or missing API key."},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        request.state.access_scope = access_scope
        if response is None and api_rate_limit_enabled():
            rate_limit = int(settings.api_rate_limit_per_minute)
            try:
                allowed, retry_after, rate_remaining = await check_api_rate_limit_async(
                    request
                )
            except RateLimitBackendUnavailable:
                response = _service_unavailable_response(request_id)
            else:
                if not allowed:
                    HTTP_RATE_LIMITED.labels(kind="api").inc()
                    response = JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={"detail": "API rate limit exceeded."},
                        headers={"Retry-After": str(retry_after)},
                    )

    try:
        if response is None:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "unhandled_request_exception",
                    extra={"request_id": request_id},
                )
                response = _internal_error_response(request_id)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        if settings.environment.strip().lower() == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        if rate_limit > 0:
            response.headers["X-RateLimit-Limit"] = str(rate_limit)
            response.headers["X-RateLimit-Remaining"] = str(rate_remaining or 0)
        return response
    finally:
        duration = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"
        metric_method = normalized_http_method(request.method)
        HTTP_REQUESTS.labels(
            method=metric_method,
            route=route,
            status=str(status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(
            method=metric_method,
            route=route,
        ).observe(duration)
        HTTP_REQUESTS_IN_PROGRESS.dec()
        logger.info(
            "http_request",
            extra={
                "http_method": request.method,
                "http_route": route,
                "http_status": status_code,
                "duration_ms": round(duration * 1000, 3),
                "request_id": request_id,
            },
        )
        request_id_context.reset(context_token)


# CORS must wrap request controls so middleware-generated 401/429/503 responses
# and sanitized 500s receive the same browser contract as normal API responses.
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "X-DaemonState-API-Key",
            "X-Request-ID",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
        ],
    )


app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/startup", tags=["health"])
async def startup_healthcheck() -> JSONResponse:
    if not _startup_complete:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "starting"},
        )
    return JSONResponse({"status": "started"})


@app.get("/health/ready", tags=["health"])
async def readiness() -> JSONResponse:
    credential_store_ready = True
    try:
        async with asyncio.timeout(max(1.0, settings.database_connect_timeout_seconds)):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                schema_current = (
                    True if settings.auto_migrate else await schema_is_current(conn)
                )
                if (
                    schema_current
                    and settings.environment.strip().lower() == "production"
                ):
                    try:
                        await validate_connector_credentials(conn)
                    except CredentialStoreError:
                        credential_store_ready = False
        redis_ready = await rate_limit_backend_ready()
    except Exception:
        logger.exception("readiness_check_failed")
        READINESS.set(0)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )
    if not schema_current or not redis_ready or not credential_store_ready:
        READINESS.set(0)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": "ready" if schema_current else "schema_mismatch",
                "rate_limit_backend": "ready" if redis_ready else "unavailable",
                "credential_store": (
                    "ready" if credential_store_ready else "invalid"
                ),
            },
        )

    database_backend = engine.url.get_backend_name()
    READINESS.set(1)
    return JSONResponse({
        "status": "ready",
        "database": database_backend,
        "api_auth_enabled": api_auth_enabled(),
        "api_rate_limit_per_minute": int(settings.api_rate_limit_per_minute or 0),
        "credential_encryption_enabled": bool(settings.encryption_key),
        "credential_store": "ready",
    })


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    if not settings.metrics_enabled:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    expected = settings.metrics_bearer_token
    if expected:
        authorization = request.headers.get("authorization", "")
        provided = (
            authorization[7:].strip()
            if authorization.lower().startswith("bearer ")
            else ""
        )
        if not provided or not secrets.compare_digest(provided, expected):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing metrics token."},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    logger.exception(
        "unhandled_request_exception",
        extra={"request_id": request_id},
    )
    return _internal_error_response(request_id)


def _internal_error_response(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "An internal error occurred.",
                "request_id": request_id,
            }
        },
        headers={"X-Request-ID": request_id},
    )


def _service_unavailable_response(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": {
                "code": "rate_limit_backend_unavailable",
                "message": "Request controls are temporarily unavailable.",
                "request_id": request_id,
            }
        },
        headers={"Retry-After": "5"},
    )


if settings.serve_frontend and FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend_route(path: str) -> FileResponse:
        protected_prefixes = ("api", "health", "docs", "redoc", "openapi.json")
        if path == "" or path.split("/", 1)[0] in protected_prefixes:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        return FileResponse(FRONTEND_DIST / "index.html")
