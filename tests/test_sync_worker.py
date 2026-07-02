from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.migrations import run_migrations
from app.models import Base, Connector, SyncJob, Workspace
from app.services.sync_worker import run_pending_sync_jobs
from app.time import utc_now


@pytest.fixture
async def worker_db_url():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)
    await engine.dispose()
    try:
        yield db_url
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def test_sync_worker_drains_pending_connector_job(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        workspace = Workspace(id=workspace_id, name="Worker", slug=f"worker-{workspace_id.hex}")
        connector = Connector(
            id=connector_id,
            workspace_id=workspace_id,
            connector_type="local",
            status="connected",
            config_json="{}",
        )
        job = SyncJob(
            id=job_id,
            workspace_id=workspace_id,
            connector_id=connector_id,
            job_type="connector_sync",
            idempotency_key=f"connector_sync:{workspace_id}:{connector_id}",
            status="pending",
            max_attempts=3,
        )
        session.add_all([workspace, connector, job])
        await session.commit()

    result = await run_pending_sync_jobs(database_url=worker_db_url, limit=5)

    assert result.started == 1
    assert result.completed == 1
    assert result.failed == 0
    assert result.job_ids == [str(job_id)]

    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        connector = await session.get(Connector, connector_id)
        assert job is not None
        assert job.status == "completed"
        assert job.attempt_count == 1
        assert job.completed_at is not None
        assert job.locked_by is None
        assert job.lease_expires_at is None
        assert connector is not None
        assert connector.last_sync_at is not None

    await engine.dispose()


async def test_sync_worker_retries_failed_job_after_backoff(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        workspace = Workspace(id=workspace_id, name="Retry", slug=f"retry-{workspace_id.hex}")
        connector = Connector(
            id=connector_id,
            workspace_id=workspace_id,
            connector_type="slack",
            status="connected",
            config_json="{}",
            credentials_json="{}",
        )
        job = SyncJob(
            id=job_id,
            workspace_id=workspace_id,
            connector_id=connector_id,
            job_type="connector_sync",
            idempotency_key=f"connector_sync:{workspace_id}:{connector_id}",
            status="pending",
            max_attempts=2,
        )
        session.add_all([workspace, connector, job])
        await session.commit()

    result = await run_pending_sync_jobs(
        database_url=worker_db_url,
        limit=5,
        worker_id="retry-worker",
        retry_base_seconds=60,
    )

    assert result.started == 1
    assert result.completed == 0
    assert result.retried == 1
    assert result.dead_lettered == 0

    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == "retrying"
        assert job.attempt_count == 1
        assert job.available_at is not None
        assert job.available_at > utc_now()
        assert job.locked_by is None
        assert job.lease_expires_at is None

    not_due = await run_pending_sync_jobs(database_url=worker_db_url, limit=5)
    assert not_due.started == 0

    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        assert job is not None
        job.available_at = utc_now() - timedelta(seconds=1)
        await session.commit()

    second = await run_pending_sync_jobs(
        database_url=worker_db_url,
        limit=5,
        worker_id="retry-worker",
        retry_base_seconds=60,
    )

    assert second.started == 1
    assert second.retried == 0
    assert second.dead_lettered == 1

    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == "dead_letter"
        assert job.attempt_count == 2
        assert job.dead_lettered_at is not None
        assert "No Slack access token" in (job.error_message or "")

    await engine.dispose()


async def test_sync_worker_reclaims_expired_lease(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        workspace = Workspace(id=workspace_id, name="Lease", slug=f"lease-{workspace_id.hex}")
        connector = Connector(
            id=connector_id,
            workspace_id=workspace_id,
            connector_type="local",
            status="connected",
            config_json="{}",
        )
        job = SyncJob(
            id=job_id,
            workspace_id=workspace_id,
            connector_id=connector_id,
            job_type="connector_sync",
            idempotency_key=f"connector_sync:{workspace_id}:{connector_id}",
            status="running",
            attempt_count=1,
            max_attempts=3,
            locked_by="dead-worker",
            lease_expires_at=utc_now() - timedelta(seconds=30),
        )
        session.add_all([workspace, connector, job])
        await session.commit()

    result = await run_pending_sync_jobs(
        database_url=worker_db_url,
        limit=5,
        worker_id="replacement-worker",
    )

    assert result.started == 1
    assert result.completed == 1

    async with session_factory() as session:
        job = await session.scalar(select(SyncJob).where(SyncJob.id == job_id))
        assert job is not None
        assert job.status == "completed"
        assert job.attempt_count == 2
        assert job.locked_by is None
        assert job.lease_expires_at is None

    await engine.dispose()


async def test_sync_worker_dead_letters_exhausted_expired_lease(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        workspace = Workspace(id=workspace_id, name="Dead", slug=f"dead-{workspace_id.hex}")
        connector = Connector(
            id=connector_id,
            workspace_id=workspace_id,
            connector_type="local",
            status="connected",
            config_json="{}",
        )
        job = SyncJob(
            id=job_id,
            workspace_id=workspace_id,
            connector_id=connector_id,
            job_type="connector_sync",
            status="running",
            attempt_count=3,
            max_attempts=3,
            locked_by="dead-worker",
            lease_expires_at=utc_now() - timedelta(seconds=30),
        )
        session.add_all([workspace, connector, job])
        await session.commit()

    result = await run_pending_sync_jobs(database_url=worker_db_url, limit=5)

    assert result.started == 0
    assert result.dead_lettered == 1

    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == "dead_letter"
        assert job.dead_lettered_at is not None
        assert job.locked_by is None

    await engine.dispose()
