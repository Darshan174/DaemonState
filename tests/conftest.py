"""Shared async fixtures for the Context Engine test suite.

Requires PostgreSQL (with pgvector) running — the same instance from
docker-compose is fine.  Override the URL via ``TEST_DATABASE_URL``.

Each test runs inside a SAVEPOINT that is rolled back at the end, so
tests never pollute each other and nothing persists to the real DB.
"""

from __future__ import annotations

import os
import subprocess
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import get_db_session
from app.main import app
from app.models.base import Base
from app.processing.embedder import HashingEmbedder
from app.processing.extractor import RegexExtractor

# ---------------------------------------------------------------------------
# Allow pointing at a dedicated test database; fall back to the dev one.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/context_engine",
)

_PARSED_DB_URL = urlparse(TEST_DATABASE_URL.replace("+asyncpg", ""))
_DB_NAME = _PARSED_DB_URL.path.lstrip("/")


def _db_cli_base_args() -> list[str]:
    args: list[str] = []
    if _PARSED_DB_URL.hostname:
        args.extend(["-h", _PARSED_DB_URL.hostname])
    if _PARSED_DB_URL.port:
        args.extend(["-p", str(_PARSED_DB_URL.port)])
    if _PARSED_DB_URL.username:
        args.extend(["-U", _PARSED_DB_URL.username])
    return args


def _db_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    if _PARSED_DB_URL.password:
        env["PGPASSWORD"] = _PARSED_DB_URL.password
    return env


def _reset_database() -> None:
    """Drop and recreate the test database via shell to guarantee a clean slate.

    asyncpg caches PostgreSQL enum type OIDs per-connection; the only
    reliable way to clear that is to destroy the database entirely so
    every OID starts fresh.
    """
    cli_args = _db_cli_base_args()
    cli_env = _db_cli_env()

    subprocess.run(["dropdb", *cli_args, "--if-exists", _DB_NAME], check=True, env=cli_env)
    subprocess.run(["createdb", *cli_args, _DB_NAME], check=True, env=cli_env)
    subprocess.run(
        [
            "psql",
            *cli_args,
            "-d",
            _DB_NAME,
            "-c",
            "CREATE EXTENSION IF NOT EXISTS vector",
        ],
        check=True,
        env=cli_env,
    )


# ---------------------------------------------------------------------------
# Force local embedder in all tests — prevents the dummy LITELLM_API_KEY in
# .env from triggering real API calls.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _force_local_providers(monkeypatch):
    """Force deterministic, offline embedder and extractor in all tests.

    The ``.env`` ships a placeholder ``LITELLM_API_KEY`` which causes the
    default builders to choose provider-backed implementations that fail
    with ``AuthenticationError``.  Patch every import site so the test
    suite stays fully offline.
    """
    monkeypatch.setattr("app.config.settings.litellm_api_key", None)
    monkeypatch.setattr("app.config.settings.enable_default_provider_models", False)
    monkeypatch.setattr("app.processing.embedder.settings.litellm_api_key", None)
    monkeypatch.setattr(
        "app.processing.embedder.settings.enable_default_provider_models",
        False,
    )
    monkeypatch.setattr("app.processing.extractor.settings.litellm_api_key", None)
    monkeypatch.setattr(
        "app.processing.extractor.settings.enable_default_provider_models",
        False,
    )
    monkeypatch.setattr("app.services.llm_service.settings.litellm_api_key", None)

    _hashing = lambda: HashingEmbedder()
    monkeypatch.setattr("app.processing.embedder.build_default_embedder", _hashing)
    monkeypatch.setattr("app.services.knowledge_service.build_default_embedder", _hashing)
    monkeypatch.setattr("app.services.ingestion_service.build_default_embedder", _hashing)
    monkeypatch.setattr("app.services.query_service.build_default_embedder", _hashing)

    _regex = lambda: RegexExtractor()
    monkeypatch.setattr("app.processing.extractor.build_default_extractor", _regex)
    monkeypatch.setattr("app.services.ingestion_service.build_default_extractor", _regex)


# ---------------------------------------------------------------------------
# Session-scoped engine & table creation
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def engine():
    _reset_database()

    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

    async with eng.begin() as conn:
        # SQLAlchemy Enum() uses Python .name (CONNECTED) for PG enum labels,
        # but several backend models have server_default using .value (connected).
        # Pre-create enum types with lowercase values so server_defaults work.
        await conn.execute(
            text(
                "CREATE TYPE connector_status_enum AS ENUM "
                "('connected', 'disconnected', 'error')"
            )
        )
        await conn.execute(
            text(
                "CREATE TYPE connector_type_enum AS ENUM "
                "('local', 'slack', 'notion', 'zoom', 'github', 'gdrive', 'gong')"
            )
        )
        await conn.execute(
            text(
                "CREATE TYPE knowledge_model_status_enum AS ENUM "
                "('active', 'archived')"
            )
        )
        await conn.execute(
            text(
                "CREATE TYPE relationship_type_enum AS ENUM "
                "('depends_on', 'blocked_by', 'enables', "
                "'contradicts', 'supersedes', 'related_to')"
            )
        )
        await conn.execute(
            text(
                "CREATE TYPE relationship_sentiment_enum AS ENUM "
                "('positive', 'negative', 'neutral')"
            )
        )
        await conn.execute(
            text(
                "CREATE TYPE sync_job_status_enum AS ENUM "
                "('pending', 'running', 'completed', 'failed')"
            )
        )

    # Now create_all on a fresh connection — it will skip enum creation
    # (checkfirst=True by default) and use the ones we just made.
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()


# ---------------------------------------------------------------------------
# Per-test session inside a rolled-back transaction (savepoint pattern)
# ---------------------------------------------------------------------------
@pytest.fixture
async def db_session(engine):
    async with engine.connect() as conn:
        outer = await conn.begin()
        await conn.begin_nested()

        session = AsyncSession(bind=conn, expire_on_commit=False)

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _reopen_savepoint(sync_session, transaction):
            """Re-open a nested savepoint after the service code commits."""
            if conn.closed or conn.invalidated:
                return
            if not conn.in_nested_transaction():
                conn.sync_connection.begin_nested()

        yield session

        await session.close()
        await outer.rollback()


# ---------------------------------------------------------------------------
# HTTPX async client wired to the test DB session
# ---------------------------------------------------------------------------
@pytest.fixture
async def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------
@pytest.fixture
async def workspace(db_session):
    """Insert a Workspace row and return its UUID."""
    from app.models.user import Workspace

    ws = Workspace(id=uuid4(), name="Test Workspace")
    db_session.add(ws)
    await db_session.flush()
    return ws


@pytest.fixture
async def model_payload(workspace):
    """Return a valid POST /api/models body."""
    return {
        "workspace_id": str(workspace.id),
        "name": "Pricing",
        "description": "All pricing info",
    }


@pytest.fixture
async def created_model(client, model_payload):
    """POST a model and return the response JSON."""
    resp = await client.post("/api/models", json=model_payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def component_payload():
    return {
        "name": "Enterprise Price",
        "value": "$600/seat",
        "confidence": 0.92,
    }


@pytest.fixture
async def created_component(client, created_model, component_payload):
    """POST a component on the created model and return the response JSON."""
    resp = await client.post(
        f"/api/models/{created_model['id']}/components",
        json=component_payload,
    )
    assert resp.status_code == 201
    return resp.json()
