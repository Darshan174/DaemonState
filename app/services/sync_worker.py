from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import (
    _ensure_sqlite_parent_dir,
    _make_async_url,
    create_database_engine,
    database_wall_clock,
    database_wall_clock_expression,
)
from app.models import SourceIngestionJob, SyncJob
from app.time import utc_now


CONNECTOR_SYNC_JOB_TYPE = "connector_sync"
DUE_SYNC_JOB_STATUSES = ("pending", "retrying")
ACTIVE_SYNC_JOB_STATUSES = (*DUE_SYNC_JOB_STATUSES, "running")
DEAD_LETTER_STATUS = "dead_letter"


class SyncJobLeaseLost(RuntimeError):
    """Raised when a worker tries to commit after losing its database claim."""


class ClaimFencedAsyncSession(AsyncSession):
    """Fence every provider batch commit with the active sync-job claim.

    Provider sync and extraction services intentionally commit in bounded
    batches. Locking the job row in the same transaction makes each such batch
    atomic with the lease check, so a reclaimed worker cannot commit stale
    business rows after another worker owns the job.
    """

    def configure_claim_fence(
        self,
        *,
        job_id,
        worker_id: str,
        claim_token: str,
    ) -> None:
        self.info["_sync_job_claim"] = (job_id, worker_id, claim_token)

    def disable_claim_fence(self) -> None:
        self.info.pop("_sync_job_claim", None)
        self.info.pop("_source_ingestion_job_claim", None)

    def configure_source_claim_fence(
        self,
        *,
        job_id,
        worker_id: str,
        claim_token: str,
    ) -> None:
        self.info["_source_ingestion_job_claim"] = (
            job_id,
            worker_id,
            claim_token,
        )

    async def commit(self) -> None:
        claim = self.info.get("_sync_job_claim")
        claim_model = SyncJob
        if claim is None:
            claim = self.info.get("_source_ingestion_job_claim")
            claim_model = SourceIngestionJob
        if claim:
            job_id, worker_id, claim_token = claim
            statement = (
                select(claim_model.id)
                .where(
                    claim_model.id == job_id,
                    claim_model.status == "running",
                    claim_model.locked_by == worker_id,
                    claim_model.claim_token == claim_token,
                    claim_model.lease_expires_at
                    > database_wall_clock_expression(
                        self.get_bind().dialect.name
                    ),
                )
            )
            if self.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            active_job_id = await self.scalar(statement)
            if active_job_id is None:
                await self.rollback()
                raise SyncJobLeaseLost("Sync job lease was lost before commit")
        await super().commit()


@dataclass(frozen=True)
class SyncWorkerRunResult:
    scanned: int
    started: int
    completed: int
    failed: int
    retried: int
    dead_lettered: int
    skipped: int
    job_ids: list[str]
    source_scanned: int = 0
    source_completed: int = 0
    source_failed: int = 0
    source_retried: int = 0
    source_dead_lettered: int = 0
    source_enqueued: int = 0
    source_job_ids: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "started": self.started,
            "completed": self.completed,
            "failed": self.failed,
            "retried": self.retried,
            "dead_lettered": self.dead_lettered,
            "skipped": self.skipped,
            "job_ids": self.job_ids,
            "source_scanned": self.source_scanned,
            "source_completed": self.source_completed,
            "source_failed": self.source_failed,
            "source_retried": self.source_retried,
            "source_dead_lettered": self.source_dead_lettered,
            "source_enqueued": self.source_enqueued,
            "source_job_ids": self.source_job_ids or [],
        }


async def run_pending_sync_jobs(
    *,
    database_url: str | None = None,
    limit: int = 10,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    retry_base_seconds: int | None = None,
    retry_max_seconds: int | None = None,
    shutdown_event: asyncio.Event | None = None,
) -> SyncWorkerRunResult:
    db_url = _make_async_url(database_url or settings.database_url)
    _ensure_sqlite_parent_dir(db_url)
    engine = create_database_engine(
        db_url,
        application_name="daemonstate-sync-worker",
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    worker_id = worker_id or _default_worker_id()
    lease = timedelta(seconds=max(1, lease_seconds or settings.sync_worker_lease_seconds))

    try:
        from app.services.source_ingestion_worker import (
            claim_due_source_ingestion_jobs,
            dead_letter_expired_source_ingestion_jobs,
            enqueue_missing_source_ingestion_jobs,
            run_source_ingestion_job,
        )

        async with session_factory() as session:
            now = await _database_now(session)
            stale_dead_letters = await _dead_letter_expired_exhausted_jobs(session, now=now)
            source_enqueued = await enqueue_missing_source_ingestion_jobs(
                session,
                limit=settings.source_ingestion_sweep_limit,
            )
            stale_source_dead_letters = (
                await dead_letter_expired_source_ingestion_jobs(session, now=now)
            )
            jobs = await _claim_due_jobs(
                session,
                limit=limit,
                worker_id=worker_id,
                lease=lease,
                now=now,
            )
            job_refs = [
                (job.id, job.connector_id, str(job.claim_token))
                for job in jobs
                if job.claim_token
            ]
            source_jobs = await claim_due_source_ingestion_jobs(
                session,
                limit=settings.source_ingestion_sweep_limit,
                worker_id=worker_id,
                lease=lease,
                now=now,
            )
            source_job_refs = [
                (job.id, job.source_document_id, str(job.claim_token))
                for job in source_jobs
                if job.claim_token
            ]
            await session.commit()

        started = len(job_refs)
        async def _execute_connector(job_id, connector_id, claim_token):
            from app.api.connectors import _run_sync_job

            await _run_sync_job(
                str(job_id),
                str(connector_id),
                db_url,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=int(lease.total_seconds()),
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )

        async def _execute_source(job_id, document_id, claim_token):
            await run_source_ingestion_job(
                job_id=job_id,
                document_id=document_id,
                database_url=db_url,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=int(lease.total_seconds()),
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )

        execution_errors: list[BaseException] = []
        execution_tasks = [
            asyncio.create_task(
                _execute_connector(job_id, connector_id, claim_token),
                name=f"sync-job-{job_id}",
            )
            for job_id, connector_id, claim_token in job_refs
        ]
        execution_tasks.extend(
            [
                asyncio.create_task(
                    _execute_source(job_id, document_id, claim_token),
                    name=f"source-ingestion-job-{job_id}",
                )
                for job_id, document_id, claim_token in source_job_refs
            ]
        )
        if execution_tasks:
            gathered = asyncio.gather(*execution_tasks, return_exceptions=True)
            stop_waiter: asyncio.Task | None = None
            if shutdown_event is not None:
                stop_waiter = asyncio.create_task(
                    shutdown_event.wait(),
                    name="sync-worker-shutdown",
                )
                done, _ = await asyncio.wait(
                    {gathered, stop_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_waiter in done and not gathered.done():
                    for task in execution_tasks:
                        task.cancel()
            results = await gathered
            if stop_waiter is not None:
                stop_waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_waiter
            execution_errors = [
                result
                for result in results
                if isinstance(result, BaseException)
                and not (
                    isinstance(result, asyncio.CancelledError)
                    and shutdown_event is not None
                    and shutdown_event.is_set()
                )
            ]

        completed = 0
        failed = 0
        retried = 0
        dead_lettered = stale_dead_letters
        source_completed = 0
        source_retried = 0
        source_dead_lettered = stale_source_dead_letters
        if job_refs:
            async with session_factory() as session:
                job_ids = [job_id for job_id, _, _ in job_refs]
                refreshed = list(await session.scalars(
                    select(SyncJob).where(SyncJob.id.in_(job_ids))
                ))
                completed = sum(1 for job in refreshed if job.status == "completed")
                failed = sum(1 for job in refreshed if job.status == "failed")
                retried = sum(1 for job in refreshed if job.status == "retrying")
                dead_lettered += sum(
                    1 for job in refreshed if job.status == DEAD_LETTER_STATUS
                )
                claims_by_id = {
                    job_id: claim_token
                    for job_id, _, claim_token in job_refs
                }
                unresolved = [
                    job
                    for job in refreshed
                    if (
                        job.status == "running"
                        and job.locked_by == worker_id
                        and job.claim_token == claims_by_id.get(job.id)
                    )
                ]
                if unresolved:
                    execution_errors.append(RuntimeError(
                        "Sync executors returned without finalizing claimed jobs: "
                        + ",".join(str(job.id) for job in unresolved)
                    ))
        if source_job_refs:
            async with session_factory() as session:
                source_job_ids = [
                    job_id for job_id, _, _ in source_job_refs
                ]
                refreshed_sources = list(await session.scalars(
                    select(SourceIngestionJob).where(
                        SourceIngestionJob.id.in_(source_job_ids)
                    )
                ))
                source_completed = sum(
                    1 for job in refreshed_sources if job.status == "completed"
                )
                source_retried = sum(
                    1 for job in refreshed_sources if job.status == "retrying"
                )
                source_dead_lettered += sum(
                    1
                    for job in refreshed_sources
                    if job.status == DEAD_LETTER_STATUS
                )
                source_claims_by_id = {
                    job_id: claim_token
                    for job_id, _, claim_token in source_job_refs
                }
                unresolved_sources = [
                    job
                    for job in refreshed_sources
                    if (
                        job.status == "running"
                        and job.locked_by == worker_id
                        and job.claim_token == source_claims_by_id.get(job.id)
                    )
                ]
                if unresolved_sources:
                    execution_errors.append(RuntimeError(
                        "Source-ingestion executors returned without finalizing "
                        "claimed jobs: "
                        + ",".join(
                            str(job.id) for job in unresolved_sources
                        )
                    ))

        if execution_errors:
            raise RuntimeError(
                f"{len(execution_errors)} sync job executor(s) failed"
            ) from execution_errors[0]

        return SyncWorkerRunResult(
            scanned=started,
            started=started,
            completed=completed,
            failed=failed,
            retried=retried,
            dead_lettered=dead_lettered,
            skipped=0,
            job_ids=[str(job_id) for job_id, _, _ in job_refs],
            source_scanned=len(source_job_refs),
            source_completed=source_completed,
            source_failed=source_dead_lettered,
            source_retried=source_retried,
            source_dead_lettered=source_dead_lettered,
            source_enqueued=source_enqueued,
            source_job_ids=[
                str(job_id) for job_id, _, _ in source_job_refs
            ],
        )
    finally:
        await engine.dispose()


async def _claim_due_jobs(
    session: AsyncSession,
    *,
    limit: int,
    worker_id: str,
    lease: timedelta,
    now: datetime,
) -> list[SyncJob]:
    due_ready = and_(
        SyncJob.status.in_(DUE_SYNC_JOB_STATUSES),
        or_(SyncJob.available_at.is_(None), SyncJob.available_at <= now),
    )
    expired_lease = and_(
        SyncJob.status == "running",
        SyncJob.lease_expires_at.is_not(None),
        SyncJob.lease_expires_at <= now,
    )
    stmt = (
        select(SyncJob)
        .where(SyncJob.job_type == CONNECTOR_SYNC_JOB_TYPE)
        .where(or_(due_ready, expired_lease))
        .where(SyncJob.attempt_count < SyncJob.max_attempts)
        .order_by(SyncJob.available_at.asc(), SyncJob.created_at.asc())
        .limit(max(1, limit))
    )
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    result = await session.scalars(stmt)
    jobs = list(result)
    for job in jobs:
        if job.status == "running":
            job.error_type = "lease_expired"
            job.error_message = (
                f"Previous worker lease expired at {job.lease_expires_at.isoformat()}"
                if job.lease_expires_at
                else "Previous worker lease expired"
            )
        job.status = "running"
        job.locked_by = worker_id
        job.claim_token = uuid4().hex
        job.heartbeat_at = now
        job.lease_expires_at = now + lease
        job.available_at = None
        job.completed_at = None
        job.dead_lettered_at = None
        job.started_at = now
        job.attempt_count = int(job.attempt_count or 0) + 1
    return jobs


async def _dead_letter_expired_exhausted_jobs(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    result = await session.scalars(
        select(SyncJob)
        .where(SyncJob.job_type == CONNECTOR_SYNC_JOB_TYPE)
        .where(SyncJob.status == "running")
        .where(SyncJob.lease_expires_at.is_not(None))
        .where(SyncJob.lease_expires_at <= now)
        .where(SyncJob.attempt_count >= SyncJob.max_attempts)
    )
    jobs = list(result)
    for job in jobs:
        job.status = DEAD_LETTER_STATUS
        job.completed_at = now
        job.dead_lettered_at = now
        job.locked_by = None
        job.claim_token = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        job.error_type = job.error_type or "lease_expired"
        job.error_message = job.error_message or "Worker lease expired after max attempts"
    return len(jobs)


def _default_worker_id() -> str:
    return f"daemonstate-sync-worker-{os.getpid()}-{uuid4().hex[:8]}"


async def _database_now(session: AsyncSession) -> datetime:
    value = await database_wall_clock(session)
    return value if isinstance(value, datetime) else utc_now()
