from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import _ensure_sqlite_parent_dir, _make_async_url
from app.models import SyncJob
from app.time import utc_now


CONNECTOR_SYNC_JOB_TYPE = "connector_sync"
DUE_SYNC_JOB_STATUSES = ("pending", "retrying")
ACTIVE_SYNC_JOB_STATUSES = (*DUE_SYNC_JOB_STATUSES, "running")
DEAD_LETTER_STATUS = "dead_letter"


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
        }


async def run_pending_sync_jobs(
    *,
    database_url: str | None = None,
    limit: int = 10,
    worker_id: str | None = None,
    lease_seconds: int | None = None,
    retry_base_seconds: int | None = None,
    retry_max_seconds: int | None = None,
) -> SyncWorkerRunResult:
    db_url = _make_async_url(database_url or settings.database_url)
    _ensure_sqlite_parent_dir(db_url)
    engine = create_async_engine(db_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    worker_id = worker_id or _default_worker_id()
    lease = timedelta(seconds=max(1, lease_seconds or settings.sync_worker_lease_seconds))

    try:
        async with session_factory() as session:
            now = utc_now()
            stale_dead_letters = await _dead_letter_expired_exhausted_jobs(session, now=now)
            jobs = await _claim_due_jobs(
                session,
                limit=limit,
                worker_id=worker_id,
                lease=lease,
                now=now,
            )
            job_refs = [(job.id, job.connector_id) for job in jobs]
            await session.commit()

        started = len(job_refs)
        for job_id, connector_id in job_refs:
            from app.api.connectors import _run_sync_job

            await _run_sync_job(
                str(job_id),
                str(connector_id),
                db_url,
                worker_id=worker_id,
                lease_seconds=int(lease.total_seconds()),
                retry_base_seconds=retry_base_seconds,
                retry_max_seconds=retry_max_seconds,
            )

        completed = 0
        failed = 0
        retried = 0
        dead_lettered = stale_dead_letters
        if job_refs:
            async with session_factory() as session:
                job_ids = [job_id for job_id, _ in job_refs]
                refreshed = list(await session.scalars(
                    select(SyncJob).where(SyncJob.id.in_(job_ids))
                ))
                completed = sum(1 for job in refreshed if job.status == "completed")
                failed = sum(1 for job in refreshed if job.status == "failed")
                retried = sum(1 for job in refreshed if job.status == "retrying")
                dead_lettered += sum(
                    1 for job in refreshed if job.status == DEAD_LETTER_STATUS
                )

        return SyncWorkerRunResult(
            scanned=started,
            started=started,
            completed=completed,
            failed=failed,
            retried=retried,
            dead_lettered=dead_lettered,
            skipped=0,
            job_ids=[str(job_id) for job_id, _ in job_refs],
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
        job.lease_expires_at = None
        job.error_type = job.error_type or "lease_expired"
        job.error_message = job.error_message or "Worker lease expired after max attempts"
    return len(jobs)


def _default_worker_id() -> str:
    return f"ctxe-sync-worker-{os.getpid()}-{uuid4().hex[:8]}"
