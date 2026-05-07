from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import get_db_session
from app.main import app
from app.migrations import run_migrations
from app.models import Base
from app.processing.embedder import HashingEmbedder

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///data/test_context.db",
)


@pytest.fixture(autouse=True)
def _force_local_providers(monkeypatch):
    monkeypatch.setattr("app.config.settings.litellm_api_key", None)
    monkeypatch.setattr("app.config.settings.extraction_model", None)
    monkeypatch.setattr("app.config.settings.embedding_model", None)
    monkeypatch.setattr("app.processing.embedder.settings.litellm_api_key", None)
    monkeypatch.setattr("app.processing.embedder.settings.embedding_model", None)
    monkeypatch.setattr("app.processing.extractor.settings.litellm_api_key", None)
    monkeypatch.setattr("app.processing.extractor.settings.extraction_model", None)
    monkeypatch.setattr("app.services.ingest.build_default_embedder", lambda: HashingEmbedder())
    monkeypatch.setattr("app.services.query.build_default_embedder", lambda: HashingEmbedder())


@pytest.fixture(scope="session")
async def engine():
    if TEST_DATABASE_URL.startswith("sqlite+aiosqlite:///"):
        db_path = TEST_DATABASE_URL.removeprefix("sqlite+aiosqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    async with engine.connect() as conn:
        outer = await conn.begin()
        await conn.begin_nested()
        session = AsyncSession(bind=conn, expire_on_commit=False)

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _reopen_savepoint(sync_session, transaction):
            if conn.closed or conn.invalidated:
                return
            if not conn.in_nested_transaction():
                conn.sync_connection.begin_nested()

        yield session
        await session.close()
        await outer.rollback()


@pytest.fixture
async def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def sample_model(db_session):
    from app.models import Model
    model = Model(id=uuid4(), name="Pricing", description="Pricing info")
    db_session.add(model)
    await db_session.flush()
    return model


@pytest.fixture
async def sample_source(db_session):
    from app.models import SourceDocument
    doc = SourceDocument(
        id=uuid4(), source_type="local", external_id="test-doc",
        content="Decision: pricing will be $20/month for basic tier.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()
    return doc
