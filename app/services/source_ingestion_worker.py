from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
import logging
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import (
    _ensure_sqlite_parent_dir,
    _make_async_url,
    create_database_engine,
    database_wall_clock,
    database_wall_clock_expression,
)
from app.models import SourceDocument, SourceIngestionJob
from app.services.ingest import IngestionService
from app.services.redaction import redact_sensitive_text
from app.time import utc_now


logger = logging.getLogger("daemonstate.source-ingestion")
SOURCE_JOB_DUE_STATUSES = ("pending", "retrying")
SOURCE_JOB_DEAD_LETTER_STATUS = "dead_letter"


async def enqueue_source_ingestion_job(
    session: AsyncSession,
    document: SourceDocument,
) -> None:
    """Idempotently enqueue projection in the caller's source transaction."""
    values = {
        "id": uuid4(),
        "source_document_id": document.id,
        "workspace_id": document.workspace_id,
        "status": "pending",
        "attempt_count": 0,
        "max_attempts": max(1, settings.source_ingestion_max_attempts),
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        statement = insert(SourceIngestionJob).values(**values).on_conflict_do_nothing(
            index_elements=[SourceIngestionJob.source_document_id]
        )
        await session.execute(statement)
        return
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        statement = insert(SourceIngestionJob).values(**values).on_conflict_do_nothing(
            index_elements=[SourceIngestionJob.source_document_id]
        )
        await session.execute(statement)
        return

    existing = await session.scalar(
        select(SourceIngestionJob.id).where(
            SourceIngestionJob.source_document_id == document.id
        )
    )
    if existing is None:
        session.add(SourceIngestionJob(**values))


async def process_source_document_inline(
    session: AsyncSession,
    document_id: UUID,
) -> int:
    """Development-only synchronous projection that also closes its queue row."""
    async with asyncio.timeout(settings.source_ingestion_timeout_seconds):
        count = await IngestionService(
            session,
            release_provider_transactions=False,
        ).process_document(document_id)
    await session.execute(
        update(SourceIngestionJob)
        .where(SourceIngestionJob.source_document_id == document_id)
        .where(
            SourceIngestionJob.status.in_(("pending", "retrying", "running"))
        )
        .values(
            status="completed",
            completed_at=utc_now(),
            available_at=None,
            lease_expires_at=None,
            locked_by=None,
            claim_token=None,
            heartbeat_at=None,
            error_type=None,
            error_message=None,
        )
    )
    return count


async def claim_due_source_ingestion_jobs(
    session: AsyncSession,
    *,
    limit: int,
    worker_id: str,
    lease: timedelta,
    now: datetime,
    document_id: UUID | None = None,
) -> list[SourceIngestionJob]:
    due_ready = and_(
        SourceIngestionJob.status.in_(SOURCE_JOB_DUE_STATUSES),
        or_(
            SourceIngestionJob.available_at.is_(None),
            SourceIngestionJob.available_at <= now,
        ),
    )
    expired_lease = and_(
        SourceIngestionJob.status == "running",
        SourceIngestionJob.lease_expires_at.is_not(None),
        SourceIngestionJob.lease_expires_at <= now,
    )
    statement = (
        select(SourceIngestionJob)
        .where(or_(due_ready, expired_lease))
        .where(SourceIngestionJob.attempt_count < SourceIngestionJob.max_attempts)
        .order_by(
            SourceIngestionJob.available_at.asc(),
            SourceIngestionJob.created_at.asc(),
        )
        .limit(max(1, limit))
    )
    if document_id is not None:
        statement = statement.where(
            SourceIngestionJob.source_document_id == document_id
        )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    jobs = list(await session.scalars(statement))
    for job in jobs:
        if job.status == "running":
            job.error_type = "lease_expired"
            job.error_message = "Previous source-ingestion worker lease expired"
        job.status = "running"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.available_at = None
        job.started_at = now
        job.completed_at = None
        job.dead_lettered_at = None
        job.locked_by = worker_id
        job.claim_token = uuid4().hex
        job.heartbeat_at = now
        job.lease_expires_at = now + lease
    return jobs


async def enqueue_missing_source_ingestion_jobs(
    session: AsyncSession,
    *,
    limit: int,
) -> int:
    """Repair direct/legacy source writes without projecting in this transaction."""
    statement = (
        select(SourceDocument)
        .outerjoin(
            SourceIngestionJob,
            SourceIngestionJob.source_document_id == SourceDocument.id,
        )
        .where(SourceDocument.processed_at.is_(None))
        .where(SourceIngestionJob.id.is_(None))
        .order_by(SourceDocument.ingested_at.asc(), SourceDocument.id.asc())
        .limit(max(1, limit))
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True, of=SourceDocument)
    documents = list(await session.scalars(statement))
    for document in documents:
        await enqueue_source_ingestion_job(session, document)
    return len(documents)


async def run_enqueued_source_document(
    document_id: UUID,
    database_url: str,
) -> None:
    """Development fast path; the durable queue remains the source of truth."""
    db_url = _make_async_url(database_url)
    _ensure_sqlite_parent_dir(db_url)
    engine = create_database_engine(
        db_url,
        application_name="daemonstate-source-background-claim",
    )
    worker_id = f"api-background-{uuid4().hex}"
    lease_seconds = max(3, settings.sync_worker_lease_seconds)
    job_ref: tuple[UUID, UUID, str] | None = None
    try:
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with factory() as session:
            now = await _database_now(session)
            jobs = await claim_due_source_ingestion_jobs(
                session,
                limit=1,
                worker_id=worker_id,
                lease=timedelta(seconds=lease_seconds),
                now=now,
                document_id=document_id,
            )
            if jobs and jobs[0].claim_token:
                job_ref = (jobs[0].id, jobs[0].source_document_id, jobs[0].claim_token)
            await session.commit()
    finally:
        await engine.dispose()
    if job_ref is not None:
        await run_source_ingestion_job(
            job_id=job_ref[0],
            document_id=job_ref[1],
            database_url=db_url,
            worker_id=worker_id,
            claim_token=job_ref[2],
            lease_seconds=lease_seconds,
        )


async def dead_letter_expired_source_ingestion_jobs(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    statement = (
        select(SourceIngestionJob)
        .where(SourceIngestionJob.status == "running")
        .where(SourceIngestionJob.lease_expires_at.is_not(None))
        .where(SourceIngestionJob.lease_expires_at <= now)
        .where(
            SourceIngestionJob.attempt_count >= SourceIngestionJob.max_attempts
        )
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    jobs = list(await session.scalars(statement))
    for job in jobs:
        job.status = SOURCE_JOB_DEAD_LETTER_STATUS
        job.completed_at = now
        job.dead_lettered_at = now
        job.available_at = None
        job.lease_expires_at = None
        job.locked_by = None
        job.claim_token = None
        job.heartbeat_at = None
        job.error_type = job.error_type or "lease_expired"
        job.error_message = (
            job.error_message or "Source-ingestion lease expired after max attempts"
        )
    return len(jobs)


async def redrive_dead_letter_source_ingestion_jobs(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> int:
    """Safely return unfinished dead letters to the queue for operator retry."""
    jobs = list(await session.scalars(
        select(SourceIngestionJob)
        .join(
            SourceDocument,
            SourceDocument.id == SourceIngestionJob.source_document_id,
        )
        .where(SourceIngestionJob.status == SOURCE_JOB_DEAD_LETTER_STATUS)
        .where(SourceDocument.processed_at.is_(None))
        .order_by(SourceIngestionJob.created_at.asc())
        .limit(max(1, limit))
    ))
    now = await _database_now(session)
    for job in jobs:
        job.status = "retrying"
        job.attempt_count = 0
        job.available_at = now
        job.completed_at = None
        job.dead_lettered_at = None
        job.lease_expires_at = None
        job.locked_by = None
        job.claim_token = None
        job.heartbeat_at = None
        job.error_type = None
        job.error_message = None
    await session.flush()
    return len(jobs)


async def run_source_ingestion_job(
    *,
    job_id: UUID,
    document_id: UUID,
    database_url: str,
    worker_id: str,
    claim_token: str,
    lease_seconds: int,
    retry_base_seconds: int | None = None,
    retry_max_seconds: int | None = None,
) -> None:
    """Execute one leased projection with heartbeat, fencing, and retries."""
    from app.services.sync_worker import ClaimFencedAsyncSession

    db_url = _make_async_url(database_url)
    _ensure_sqlite_parent_dir(db_url)
    engine = create_database_engine(
        db_url,
        application_name="daemonstate-source-ingestion",
    )
    session_factory = async_sessionmaker(
        engine,
        class_=ClaimFencedAsyncSession,
        expire_on_commit=False,
    )
    control_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    lease_seconds = max(3, lease_seconds)
    heartbeat_stop = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    attempt_count = 0
    max_attempts = max(1, settings.source_ingestion_max_attempts)

    try:
        async with session_factory() as session:
            job = await session.get(SourceIngestionJob, job_id)
            if (
                job is None
                or job.source_document_id != document_id
                or job.status != "running"
                or job.locked_by != worker_id
                or job.claim_token != claim_token
            ):
                return
            document = await session.get(SourceDocument, document_id)
            if document is None:
                return
            source_identity = document.source_identity_sha256
            source_revision = int(document.revision_number or 1)
            attempt_count = int(job.attempt_count or 0)
            max_attempts = int(job.max_attempts or max_attempts)
            session.configure_source_claim_fence(
                job_id=job_id,
                worker_id=worker_id,
                claim_token=claim_token,
            )
            await session.commit()

            heartbeat_task = asyncio.create_task(
                _heartbeat_source_ingestion_job(
                    control_factory,
                    job_id=job_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_seconds=lease_seconds,
                    stop=heartbeat_stop,
                    lease_lost=lease_lost,
                ),
                name=f"source-ingestion-heartbeat-{job_id}",
            )

            async with asyncio.timeout(settings.source_ingestion_timeout_seconds):
                await IngestionService(
                    session,
                    release_provider_transactions=True,
                    claimed_source_job=True,
                ).process_document(document_id)

            heartbeat_stop.set()
            if heartbeat_task is not None:
                await heartbeat_task
                heartbeat_task = None
            if lease_lost.is_set():
                await session.rollback()
                return

            completed_at = await _database_now(session)
            if session.get_bind().dialect.name == "postgresql":
                from app.services.source_revisions import _lock_source_identity

                await _lock_source_identity(session, source_identity)
            newer_revision = await session.scalar(
                select(SourceDocument.id)
                .where(
                    SourceDocument.source_identity_sha256 == source_identity,
                    SourceDocument.revision_number > source_revision,
                )
                .limit(1)
            )
            if newer_revision is not None:
                # A newer immutable revision supersedes this work. Discard
                # staged projection rows and terminally coalesce this job so
                # an older worker cannot overwrite current truth.
                await session.rollback()
                session.disable_claim_fence()
                await session.execute(
                    update(SourceDocument)
                    .where(SourceDocument.id == document_id)
                    .where(SourceDocument.processed_at.is_(None))
                    .values(processed_at=completed_at)
                )
                await session.execute(
                    update(SourceIngestionJob)
                    .where(
                        SourceIngestionJob.id == job_id,
                        SourceIngestionJob.status == "running",
                        SourceIngestionJob.locked_by == worker_id,
                        SourceIngestionJob.claim_token == claim_token,
                        SourceIngestionJob.lease_expires_at
                        > database_wall_clock_expression(
                            session.get_bind().dialect.name
                        ),
                    )
                    .values(
                        status="completed",
                        completed_at=completed_at,
                        available_at=None,
                        lease_expires_at=None,
                        locked_by=None,
                        claim_token=None,
                        heartbeat_at=None,
                        error_type="superseded_revision",
                        error_message="Coalesced behind a newer source revision",
                    )
                )
                await session.commit()
                return
            session.disable_claim_fence()
            fenced = await session.execute(
                update(SourceIngestionJob)
                .where(
                    SourceIngestionJob.id == job_id,
                    SourceIngestionJob.status == "running",
                    SourceIngestionJob.locked_by == worker_id,
                    SourceIngestionJob.claim_token == claim_token,
                    SourceIngestionJob.lease_expires_at
                    > database_wall_clock_expression(
                        session.get_bind().dialect.name
                    ),
                )
                .values(
                    status="completed",
                    completed_at=completed_at,
                    available_at=None,
                    lease_expires_at=None,
                    locked_by=None,
                    claim_token=None,
                    heartbeat_at=None,
                    dead_lettered_at=None,
                    error_type=None,
                    error_message=None,
                )
                .execution_options(synchronize_session=False)
            )
            if fenced.rowcount != 1:
                await session.rollback()
                return
            await session.commit()
    except asyncio.CancelledError:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            with suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
            heartbeat_task = None
        await _release_source_claim_for_shutdown(
            control_factory,
            job_id=job_id,
            worker_id=worker_id,
            claim_token=claim_token,
            attempt_count=attempt_count,
        )
        raise
    except Exception as exc:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            with suppress(Exception):
                await heartbeat_task
            heartbeat_task = None
        if not lease_lost.is_set():
            await _finalize_source_ingestion_failure(
                control_factory,
                job_id=job_id,
                worker_id=worker_id,
                claim_token=claim_token,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                exc=exc,
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        await engine.dispose()


async def _heartbeat_source_ingestion_job(
    session_factory,
    *,
    job_id: UUID,
    worker_id: str,
    claim_token: str,
    lease_seconds: int,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    interval = max(1.0, lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            async with session_factory() as session:
                now = await _database_now(session)
                result = await session.execute(
                    update(SourceIngestionJob)
                    .where(
                        SourceIngestionJob.id == job_id,
                        SourceIngestionJob.status == "running",
                        SourceIngestionJob.locked_by == worker_id,
                        SourceIngestionJob.claim_token == claim_token,
                        SourceIngestionJob.lease_expires_at
                        > database_wall_clock_expression(
                            session.get_bind().dialect.name
                        ),
                    )
                    .values(
                        heartbeat_at=now,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                    )
                )
                if result.rowcount != 1:
                    await session.rollback()
                    lease_lost.set()
                    return
                await session.commit()
        except Exception:
            continue


async def _release_source_claim_for_shutdown(
    session_factory,
    *,
    job_id: UUID,
    worker_id: str,
    claim_token: str,
    attempt_count: int,
) -> None:
    try:
        async with session_factory() as session:
            now = await _database_now(session)
            released = await session.execute(
                update(SourceIngestionJob)
                .where(
                    SourceIngestionJob.id == job_id,
                    SourceIngestionJob.status == "running",
                    SourceIngestionJob.locked_by == worker_id,
                    SourceIngestionJob.claim_token == claim_token,
                    SourceIngestionJob.lease_expires_at
                    > database_wall_clock_expression(
                        session.get_bind().dialect.name
                    ),
                )
                .values(
                    status="retrying",
                    attempt_count=max(0, attempt_count - 1),
                    available_at=now,
                    completed_at=None,
                    dead_lettered_at=None,
                    lease_expires_at=None,
                    locked_by=None,
                    claim_token=None,
                    heartbeat_at=None,
                    error_type="worker_shutdown",
                    error_message="Worker stopped before source projection completed",
                )
            )
            if released.rowcount == 1:
                await session.commit()
            else:
                await session.rollback()
    except Exception:
        logger.warning(
            "source_ingestion_shutdown_release_failed",
            extra={"source_ingestion_job_id": str(job_id)},
        )


async def _finalize_source_ingestion_failure(
    session_factory,
    *,
    job_id: UUID,
    worker_id: str,
    claim_token: str,
    attempt_count: int,
    max_attempts: int,
    exc: Exception,
    retry_base_seconds: int | None,
    retry_max_seconds: int | None,
) -> None:
    error_message = redact_sensitive_text(str(exc)) or type(exc).__name__
    async with session_factory() as session:
        now = await _database_now(session)
        if attempt_count < max_attempts:
            next_status = "retrying"
            available_at = now + timedelta(
                seconds=_retry_delay_seconds(
                    attempt_count,
                    base_seconds=retry_base_seconds,
                    max_seconds=retry_max_seconds,
                )
            )
            completed_at = None
            dead_lettered_at = None
        else:
            next_status = SOURCE_JOB_DEAD_LETTER_STATUS
            available_at = None
            completed_at = now
            dead_lettered_at = now
        fenced = await session.execute(
            update(SourceIngestionJob)
            .where(
                SourceIngestionJob.id == job_id,
                SourceIngestionJob.status == "running",
                SourceIngestionJob.locked_by == worker_id,
                SourceIngestionJob.claim_token == claim_token,
                SourceIngestionJob.lease_expires_at
                > database_wall_clock_expression(
                    session.get_bind().dialect.name
                ),
            )
            .values(
                status=next_status,
                available_at=available_at,
                completed_at=completed_at,
                dead_lettered_at=dead_lettered_at,
                lease_expires_at=None,
                locked_by=None,
                claim_token=None,
                heartbeat_at=None,
                error_type=type(exc).__name__[:100],
                error_message=error_message[:16_384],
            )
        )
        if fenced.rowcount == 1:
            await session.commit()
        else:
            await session.rollback()


async def _database_now(session: AsyncSession) -> datetime:
    value = await database_wall_clock(session)
    return value if isinstance(value, datetime) else utc_now()


def _retry_delay_seconds(
    attempt_count: int,
    *,
    base_seconds: int | None,
    max_seconds: int | None,
) -> int:
    base = max(1, base_seconds or settings.sync_worker_retry_base_seconds)
    cap = max(base, max_seconds or settings.sync_worker_retry_max_seconds)
    return min(base * (2 ** max(0, attempt_count - 1)), cap)
