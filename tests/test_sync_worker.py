from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.migrations import run_migrations
from app.models import Base, Connector, SourceDocument, SyncJob, Workspace
from app.services.source_revisions import ingest_source_document_revision
from app.services.sync_worker import (
    ClaimFencedAsyncSession,
    SyncJobLeaseLost,
    run_pending_sync_jobs,
)
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


async def test_sync_worker_recovers_unprocessed_source_revision(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        revision = await ingest_source_document_revision(
            session,
            workspace_id=None,
            source_type="agent_run_observation",
            external_id=f"interrupted-{uuid4().hex}",
            content="Durable verification observation.",
            metadata_json={
                "event_type": "verification",
                "payload": {"command": "pytest", "exit_code": 0},
            },
        )
        document_id = revision.document.id
        await session.commit()

    result = await run_pending_sync_jobs(database_url=worker_db_url, limit=5)

    assert result.started == 0
    assert result.source_scanned == 1
    assert result.source_completed == 1
    assert result.source_failed == 0

    async with session_factory() as session:
        document = await session.get(SourceDocument, document_id)
        assert document is not None
        assert document.processed_at is not None

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


async def test_claim_fence_rolls_back_business_rows_after_lease_loss(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    fenced_factory = async_sessionmaker(
        engine,
        class_=ClaimFencedAsyncSession,
        expire_on_commit=False,
    )
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        session.add_all([
            Workspace(
                id=workspace_id,
                name="Fence",
                slug=f"fence-{workspace_id.hex}",
            ),
            Connector(
                id=connector_id,
                workspace_id=workspace_id,
                connector_type="local",
                status="connected",
                config_json="{}",
            ),
            SyncJob(
                id=job_id,
                workspace_id=workspace_id,
                connector_id=connector_id,
                job_type="connector_sync",
                status="running",
                locked_by="active-worker",
                claim_token="active-claim",
                lease_expires_at=utc_now() + timedelta(minutes=1),
            ),
        ])
        await session.commit()

    async with fenced_factory() as session:
        connector = await session.get(Connector, connector_id)
        assert connector is not None
        connector.config_json = '{"stale":true}'
        session.configure_claim_fence(
            job_id=job_id,
            worker_id="stale-worker",
            claim_token="stale-claim",
        )
        with pytest.raises(SyncJobLeaseLost):
            await session.commit()

    async with session_factory() as session:
        connector = await session.get(Connector, connector_id)
        assert connector is not None
        assert connector.config_json == "{}"

    async with fenced_factory() as session:
        connector = await session.get(Connector, connector_id)
        assert connector is not None
        connector.config_json = '{"active":true}'
        session.configure_claim_fence(
            job_id=job_id,
            worker_id="active-worker",
            claim_token="active-claim",
        )
        await session.commit()

    async with session_factory() as session:
        connector = await session.get(Connector, connector_id)
        assert connector is not None
        assert connector.config_json == '{"active":true}'

    await engine.dispose()


async def test_worker_shutdown_cancels_work_and_releases_claim(
    worker_db_url,
    monkeypatch,
):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        session.add_all([
            Workspace(
                id=workspace_id,
                name="Shutdown",
                slug=f"shutdown-{workspace_id.hex}",
            ),
            Connector(
                id=connector_id,
                workspace_id=workspace_id,
                connector_type="slack",
                status="connected",
                config_json="{}",
                credentials_json="{}",
            ),
            SyncJob(
                id=job_id,
                workspace_id=workspace_id,
                connector_id=connector_id,
                job_type="connector_sync",
                status="pending",
                max_attempts=3,
            ),
        ])
        await session.commit()

    started = asyncio.Event()

    async def slow_sync(connector, session, *, sync_job=None):
        assert sync_job is not None
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.sync.slack.sync_slack", slow_sync)
    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_pending_sync_jobs(
            database_url=worker_db_url,
            worker_id="shutdown-worker",
            shutdown_event=stop,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    stop.set()
    result = await asyncio.wait_for(worker, timeout=2)

    assert result.started == 1
    assert result.retried == 1
    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == "retrying"
        assert job.attempt_count == 0
        assert job.locked_by is None
        assert job.claim_token is None
        assert job.error_type == "worker_shutdown"

    await engine.dispose()


async def test_claim_fence_uses_statement_clock_not_transaction_start(worker_db_url):
    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    fenced_factory = async_sessionmaker(
        engine,
        class_=ClaimFencedAsyncSession,
        expire_on_commit=False,
    )
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()

    async with session_factory() as session:
        session.add_all([
            Workspace(
                id=workspace_id,
                name="Clock fence",
                slug=f"clock-fence-{workspace_id.hex}",
            ),
            Connector(
                id=connector_id,
                workspace_id=workspace_id,
                connector_type="local",
                status="connected",
                config_json="{}",
            ),
            SyncJob(
                id=job_id,
                workspace_id=workspace_id,
                connector_id=connector_id,
                job_type="connector_sync",
                status="running",
                locked_by="clock-worker",
                claim_token="clock-claim",
                lease_expires_at=utc_now() + timedelta(milliseconds=200),
            ),
        ])
        await session.commit()

    async with fenced_factory() as session:
        # Loading the connector begins the transaction before the lease expires.
        connector = await session.get(Connector, connector_id)
        assert connector is not None
        session.configure_claim_fence(
            job_id=job_id,
            worker_id="clock-worker",
            claim_token="clock-claim",
        )
        await asyncio.sleep(1.1)
        connector.config_json = '{"expired":true}'
        with pytest.raises(SyncJobLeaseLost):
            await session.commit()

    async with session_factory() as session:
        connector = await session.get(Connector, connector_id)
        assert connector is not None
        assert connector.config_json == "{}"

    await engine.dispose()


async def test_heartbeat_cannot_revive_an_expired_lease(worker_db_url):
    from app.api.connectors import _heartbeat_sync_job

    engine = create_async_engine(worker_db_url)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    workspace_id = uuid4()
    connector_id = uuid4()
    job_id = uuid4()
    expired_at = utc_now() - timedelta(seconds=1)

    async with session_factory() as session:
        session.add_all([
            Workspace(
                id=workspace_id,
                name="Expired heartbeat",
                slug=f"expired-heartbeat-{workspace_id.hex}",
            ),
            Connector(
                id=connector_id,
                workspace_id=workspace_id,
                connector_type="local",
                status="connected",
                config_json="{}",
            ),
            SyncJob(
                id=job_id,
                workspace_id=workspace_id,
                connector_id=connector_id,
                job_type="connector_sync",
                status="running",
                locked_by="late-worker",
                claim_token="late-claim",
                heartbeat_at=expired_at,
                lease_expires_at=expired_at,
            ),
        ])
        await session.commit()

    stop = asyncio.Event()
    lease_lost = asyncio.Event()
    await asyncio.wait_for(
        _heartbeat_sync_job(
            session_factory,
            job_id=job_id,
            worker_id="late-worker",
            claim_token="late-claim",
            lease_seconds=3,
            stop=stop,
            lease_lost=lease_lost,
        ),
        timeout=2,
    )

    assert lease_lost.is_set()
    async with session_factory() as session:
        job = await session.get(SyncJob, job_id)
        assert job is not None
        assert job.lease_expires_at == expired_at

    await engine.dispose()
