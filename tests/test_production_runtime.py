from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import (
    Settings,
    production_configuration_errors,
    settings,
    validate_runtime_configuration,
)
from app.database import (
    _make_async_url,
    current_schema_revisions,
    database_wall_clock,
    expected_schema_revisions,
    schema_is_current,
)
from app.http_middleware import RequestBodyLimitMiddleware
from app.main import app
from app.observability import normalized_http_method
from app.services import auth, oauth_state
from app.services.repo_paths import RepositoryPathNotAllowed, validated_repository_path


@pytest.fixture(autouse=True)
def _reset_runtime_singletons():
    auth.reset_api_rate_limits()
    oauth_state.reset_local_oauth_states()
    yield
    auth.reset_api_rate_limits()
    oauth_state.reset_local_oauth_states()


def _hardened_production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "database_url": (
            "postgresql+asyncpg://context:secret@database/context"
            "?sslmode=require"
        ),
        "auto_migrate": False,
        "server_api_key": "a" * 32,
        "principal_api_keys": None,
        "encryption_key": Fernet.generate_key().decode("ascii"),
        "api_rate_limit_per_minute": 120,
        "redis_url": "redis://redis:6379/0",
        "rate_limit_fail_open": False,
        "allowed_hosts": "context.example.com",
        "cors_allowed_origins": "https://app.example.com",
        "allowed_repo_roots": "/srv/repositories",
        "public_base_url": "https://context.example.com",
        "api_docs_enabled": False,
        "demo_endpoints_enabled": False,
        "serve_frontend": False,
        "metrics_bearer_token": "m" * 32,
        "log_format": "json",
        "max_request_body_bytes": 1024,
        "database_statement_timeout_ms": 5_000,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _request(*, api_key: str = "test-api-key", host: str = "203.0.113.7") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/workspaces",
            "raw_path": b"/api/workspaces",
            "query_string": b"",
            "headers": [(b"x-api-key", api_key.encode("ascii"))],
            "client": (host, 49152),
            "server": ("context.example.com", 443),
        }
    )


def test_production_configuration_fails_closed_for_insecure_defaults():
    insecure = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite+aiosqlite:///data/context.db",
        auto_migrate=True,
        server_api_key=None,
        principal_api_keys=None,
        encryption_key=None,
        api_rate_limit_per_minute=0,
        redis_url=None,
        rate_limit_fail_open=True,
        allowed_hosts="*",
        cors_allowed_origins="",
        allowed_repo_roots="",
        public_base_url=None,
        api_docs_enabled=True,
        demo_endpoints_enabled=True,
        serve_frontend=True,
        metrics_bearer_token=None,
        log_format="console",
    )

    errors = production_configuration_errors(insecure)

    assert "DATABASE_URL must use PostgreSQL in production" in errors
    assert "AUTO_MIGRATE must be false; run the migration job before API replicas" in errors
    assert "SERVER_API_KEY is required" in errors
    assert "ENCRYPTION_KEY is required" in errors
    assert "REDIS_URL is required for distributed rate limiting" in errors
    assert "RATE_LIMIT_FAIL_OPEN must be false" in errors
    assert "ALLOWED_HOSTS must explicitly list public hostnames" in errors
    assert "ALLOWED_REPO_ROOTS must list at least one mounted repository root" in errors
    assert "PUBLIC_BASE_URL is required" in errors
    assert "API_DOCS_ENABLED must be false" in errors
    assert "DEMO_ENDPOINTS_ENABLED must be false" in errors
    assert (
        "SERVE_FRONTEND must be false until browser session authentication is implemented"
        in errors
    )
    assert "LOG_FORMAT must be json" in errors

    with pytest.raises(RuntimeError, match="Invalid production configuration"):
        validate_runtime_configuration(insecure)


def test_hardened_production_configuration_is_accepted():
    hardened = _hardened_production_settings()

    assert production_configuration_errors(hardened) == []
    validate_runtime_configuration(hardened)


def test_empty_optional_numeric_environment_value_is_ignored(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSION", "")

    configured = Settings(_env_file=None)

    assert configured.embedding_dimension is None


def test_prometheus_http_method_labels_have_bounded_cardinality():
    assert normalized_http_method("get") == "GET"
    assert normalized_http_method("BREW-secret-attacker-value") == "OTHER"


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"server_api_key": "short"}, "SERVER_API_KEY must contain at least 32 characters"),
        ({"public_base_url": "http://context.example.com"}, "absolute https URL"),
        ({"allowed_hosts": "*"}, "explicitly list public hostnames"),
        ({"cors_allowed_origins": "*"}, "CORS_ALLOWED_ORIGINS cannot contain '*'"),
        ({"metrics_bearer_token": "short"}, "METRICS_BEARER_TOKEN"),
        ({"max_request_body_bytes": 0}, "MAX_REQUEST_BODY_BYTES"),
        (
            {"auth_failure_rate_limit_per_minute": 0},
            "AUTH_FAILURE_RATE_LIMIT_PER_MINUTE",
        ),
        (
            {"slack_managed_install_url": "http://installer.example.com/slack"},
            "SLACK_MANAGED_INSTALL_URL",
        ),
        ({"app_workers": 2}, "APP_WORKERS must be 1"),
    ],
)
def test_production_configuration_rejects_individual_unsafe_values(
    overrides,
    expected_error,
):
    config = _hardened_production_settings(**overrides)

    assert any(expected_error in error for error in production_configuration_errors(config))


def test_postgresql_sslmode_is_translated_for_asyncpg():
    translated = make_url(
        _make_async_url(
            "postgresql://context:secret@database/context"
            "?sslmode=verify-full&application_name=runtime-test"
        )
    )

    assert translated.drivername == "postgresql+asyncpg"
    assert "sslmode" not in translated.query
    assert translated.query["ssl"] == "verify-full"
    assert "application_name" not in translated.query


async def test_postgresql_wall_clock_advances_inside_one_transaction(engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL integration check")

    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine, expire_on_commit=False) as session:
        first = await database_wall_clock(session)
        await session.execute(text("SELECT pg_sleep(0.05)"))
        second = await database_wall_clock(session)
        await session.rollback()

    assert second > first


def test_repository_paths_are_confined_to_configured_roots(tmp_path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    repository = allowed_root / "project"
    outside = tmp_path / "outside"
    allowed_root.mkdir()
    repository.mkdir()
    outside.mkdir()
    escape = allowed_root / "escape"
    escape.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "allowed_repo_roots", str(allowed_root))

    assert validated_repository_path(repository) == repository.resolve()
    with pytest.raises(RepositoryPathNotAllowed, match="outside"):
        validated_repository_path(outside)
    with pytest.raises(RepositoryPathNotAllowed, match="outside"):
        validated_repository_path(escape)


def test_repository_paths_fail_closed_without_roots_in_production(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "allowed_repo_roots", "")

    with pytest.raises(RepositoryPathNotAllowed, match="No repository roots"):
        validated_repository_path(tmp_path)


async def test_request_ids_and_security_headers_are_applied(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://context.example.com") as client:
        response = await client.get("/health", headers={"X-Request-ID": "trace_123.valid"})
        invalid = await client.get("/health", headers={"X-Request-ID": "<invalid>"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace_123.valid"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    assert response.headers["Content-Security-Policy"] == (
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    )
    assert response.headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert invalid.headers["X-Request-ID"] != "<invalid>"
    assert len(invalid.headers["X-Request-ID"]) == 32


async def test_request_body_limit_rejects_declared_and_streamed_oversize_bodies():
    inner = FastAPI()

    @inner.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"size": len(body)}

    limited_app = RequestBodyLimitMiddleware(inner, max_bytes=4)
    transport = ASGITransport(app=limited_app)

    async def chunks():
        yield b"123"
        yield b"45"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post("/echo", content=b"1234")
        declared_oversize = await client.post("/echo", content=b"12345")
        streamed_oversize = await client.post("/echo", content=chunks())

    assert accepted.status_code == 200
    assert accepted.json() == {"size": 4}
    assert declared_oversize.status_code == 413
    assert declared_oversize.json()["error"]["code"] == "request_too_large"
    assert streamed_oversize.status_code == 413
    assert streamed_oversize.json()["error"]["code"] == "request_too_large"


async def test_metrics_require_the_dedicated_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_bearer_token", "metrics-secret")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/metrics")
        wrong = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong"},
        )
        allowed = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer metrics-secret"},
        )

    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert allowed.headers["content-type"].startswith("text/plain")
    assert "context_engine_http_requests_total" in allowed.text


class _FakeRateLimitRedis:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        return self.responses.popleft()


async def test_distributed_rate_limit_uses_redis_counter(monkeypatch):
    fake = _FakeRateLimitRedis([(1, 60), (2, 59), (3, 58)])
    get_client = AsyncMock(return_value=fake)
    monkeypatch.setattr(auth, "_get_redis_client", get_client)
    monkeypatch.setattr(settings, "redis_url", "redis://fake/0")
    monkeypatch.setattr(settings, "rate_limit_fail_open", False)
    request = _request(api_key="sensitive-api-key")

    first = await auth.check_api_rate_limit_async(request, limit=2, namespace="api")
    second = await auth.check_api_rate_limit_async(request, limit=2, namespace="api")
    limited = await auth.check_api_rate_limit_async(request, limit=2, namespace="api")

    assert first == (True, 60, 1)
    assert second == (True, 59, 0)
    assert limited == (False, 58, 0)
    assert get_client.await_count == 3
    assert all(call[1] == 1 and call[3] == 61 for call in fake.calls)
    assert all("context-engine:rate-limit:api:" in call[2] for call in fake.calls)
    assert all("sensitive-api-key" not in call[2] for call in fake.calls)


async def test_distributed_rate_limit_fails_closed_when_redis_is_unavailable(
    monkeypatch,
):
    fake = _FakeRateLimitRedis([])

    async def unavailable(*args):
        raise ConnectionError("redis unavailable")

    fake.eval = unavailable
    monkeypatch.setattr(auth, "_get_redis_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(settings, "redis_url", "redis://fake/0")
    monkeypatch.setattr(settings, "rate_limit_fail_open", False)

    with pytest.raises(auth.RateLimitBackendUnavailable):
        await auth.check_api_rate_limit_async(_request(), limit=1)


class _FakeOAuthRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def set(self, key, value, *, ex, nx):
        assert ex >= 60
        assert nx is True
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def getdel(self, key):
        return self.values.pop(key, None)


async def test_oauth_state_is_connector_bound_and_single_use(monkeypatch):
    fake = _FakeOAuthRedis()
    monkeypatch.setattr(
        oauth_state,
        "_get_redis_client",
        AsyncMock(return_value=fake),
    )
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "redis_url", "redis://fake/0")
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode("ascii"))
    workspace_id = uuid4()

    token, verifier = await oauth_state.issue_oauth_state(
        workspace_id=workspace_id,
        connector_type="gdrive",
        principal_id="principal-123",
        use_pkce=True,
    )

    with pytest.raises(oauth_state.OAuthStateError, match="does not match"):
        await oauth_state.consume_oauth_state(token, connector_type="slack")

    consumed = await oauth_state.consume_oauth_state(token, connector_type="gdrive")
    assert consumed.workspace_id == workspace_id
    assert consumed.connector_type == "gdrive"
    assert consumed.principal_id == "principal-123"
    assert consumed.code_verifier == verifier

    with pytest.raises(oauth_state.OAuthStateError, match="already used"):
        await oauth_state.consume_oauth_state(token, connector_type="gdrive")


async def test_schema_readiness_helpers_compare_database_to_all_heads():
    database = create_async_engine("sqlite+aiosqlite:///:memory:")
    expected = expected_schema_revisions()
    assert expected

    try:
        async with database.begin() as conn:
            await conn.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)")
            )
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                [{"revision": revision} for revision in expected],
            )

        async with database.connect() as conn:
            assert await current_schema_revisions(conn) == expected
            assert await schema_is_current(conn) is True

        async with database.begin() as conn:
            await conn.execute(text("DELETE FROM alembic_version"))
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('outdated')")
            )

        async with database.connect() as conn:
            assert await schema_is_current(conn) is False
    finally:
        await database.dispose()
