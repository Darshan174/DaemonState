from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Connector,
    SourceDocument,
    SourceSyncObservation,
    SyncJob,
)
from app.time import utc_now


DEFAULT_PROVIDER_FRESHNESS_TTL = timedelta(minutes=15)
MAX_PROVIDER_CLOCK_SKEW = timedelta(minutes=5)
REMOTE_SOURCE_TYPES = frozenset(
    {
        "discord",
        "gdrive",
        "github",
        "github_issue",
        "github_pr",
        "github_pull_request",
        "gmail",
        "google_drive",
        "notion",
        "slack",
        "zoom",
    }
)
VALID_OBSERVATION_KINDS = frozenset({"fetched", "not_modified"})
PROVIDER_SOURCE_TYPES_BY_CONNECTOR = {
    "discord": frozenset({"discord"}),
    "gdrive": frozenset({"gdrive", "google_drive"}),
    "github": frozenset(
        {
            "github",
            "github_issue",
            "github_pr",
            "github_pull_request",
        }
    ),
    "gmail": frozenset({"gmail"}),
    "notion": frozenset({"notion"}),
    "slack": frozenset({"slack"}),
    "zoom": frozenset({"zoom"}),
}
RUNTIME_CONNECTOR_CONFIG_KEYS = frozenset(
    {
        "items_synced",
        "last_sync_summary",
        "last_synced_at",
        "total_processed_count",
    }
)


@dataclass(frozen=True)
class ProviderFreshnessStatus:
    fresh: bool
    observed_at: datetime | None = None
    observation_id: str | None = None
    reason: str = "not_observed"


def is_provider_source(source: SourceDocument | None) -> bool:
    if source is None:
        return False
    source_type = str(source.source_type or "").strip().lower()
    metadata = _metadata(source.metadata_json)
    return source_type in REMOTE_SOURCE_TYPES or str(
        metadata.get("item_type") or ""
    ).strip().lower() in {"issue", "pull_request"}


async def record_provider_observation(
    session: AsyncSession,
    *,
    connector: Connector,
    source: SourceDocument,
    sync_job: SyncJob | None = None,
    observed_at: datetime | None = None,
    provider_version: str | None = None,
    observation_kind: str = "fetched",
) -> SourceSyncObservation:
    """Append proof that this exact provider object and revision were read."""

    if not is_provider_source(source):
        raise ValueError("provider observations require a remote provider source")
    if source.workspace_id is None or source.workspace_id != connector.workspace_id:
        raise ValueError("provider observation crosses workspace boundaries")
    connector_type = str(connector.connector_type or "").strip().lower()
    if not _connector_matches_source(connector, source):
        raise ValueError("provider observation source does not match its connector")
    if sync_job is not None and (
        sync_job.connector_id != connector.id or sync_job.workspace_id != connector.workspace_id
    ):
        raise ValueError("provider observation does not match its sync job")
    actual_hash = _sha256(source.content or "")
    if source.content_sha256 and source.content_sha256 != actual_hash:
        raise ValueError("provider observation source hash does not match content")
    kind = str(observation_kind or "").strip().lower()
    if kind not in VALID_OBSERVATION_KINDS:
        raise ValueError("unsupported provider observation kind")
    observed = _utc_naive(observed_at or utc_now())
    observation = SourceSyncObservation(
        workspace_id=connector.workspace_id,
        connector_id=connector.id,
        sync_job_id=sync_job.id if sync_job is not None else None,
        sync_attempt_count=(int(sync_job.attempt_count or 0) if sync_job is not None else None),
        source_document_id=source.id,
        source_identity_sha256=source.source_identity_sha256,
        content_sha256=actual_hash,
        provider=connector_type,
        provider_object_id=source.external_id,
        provider_version=(str(provider_version).strip()[:255] if provider_version else None),
        observed_at=observed,
        scope_snapshot_sha256=connector_scope_snapshot_sha256(connector),
        provider_account_fingerprint=provider_account_fingerprint(connector),
        observation_kind=kind,
    )
    session.add(observation)
    await session.flush()
    return observation


async def load_provider_freshness(
    session: AsyncSession,
    sources: Iterable[SourceDocument],
    *,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_PROVIDER_FRESHNESS_TTL,
) -> dict[Any, ProviderFreshnessStatus]:
    """Resolve recent completed observations for exact source revisions."""

    checked_at = _utc_naive(now or utc_now())
    provider_sources = {
        source.id: source
        for source in sources
        if source.id is not None and is_provider_source(source)
    }
    if not provider_sources or ttl.total_seconds() <= 0:
        return {}
    cutoff = checked_at - ttl
    observations = list(
        await session.scalars(
            select(SourceSyncObservation)
            .options(
                selectinload(SourceSyncObservation.connector),
                selectinload(SourceSyncObservation.sync_job),
            )
            .where(
                SourceSyncObservation.source_document_id.in_(tuple(provider_sources)),
                SourceSyncObservation.observed_at >= cutoff,
                SourceSyncObservation.observed_at <= checked_at + MAX_PROVIDER_CLOCK_SKEW,
            )
            .order_by(
                SourceSyncObservation.observed_at.desc(),
                SourceSyncObservation.id.desc(),
            )
        )
    )
    result: dict[Any, ProviderFreshnessStatus] = {}
    for observation in observations:
        if observation.source_document_id in result:
            continue
        source = provider_sources.get(observation.source_document_id)
        reason = _observation_rejection_reason(
            observation,
            source,
            checked_at=checked_at,
            ttl=ttl,
        )
        if reason is not None:
            continue
        result[observation.source_document_id] = ProviderFreshnessStatus(
            fresh=True,
            observed_at=observation.observed_at,
            observation_id=str(observation.id),
            reason="completed_exact_provider_observation",
        )
    return result


async def provider_source_is_fresh(
    session: AsyncSession,
    source: SourceDocument | None,
    *,
    now: datetime | None = None,
) -> bool:
    if source is None:
        return False
    status = (
        await load_provider_freshness(
            session,
            [source],
            now=now,
        )
    ).get(source.id)
    return bool(status is not None and status.fresh)


def connector_scope_snapshot_sha256(connector: Connector) -> str:
    config = _metadata(connector.config_json)
    stable_config = {
        key: value for key, value in config.items() if key not in RUNTIME_CONNECTOR_CONFIG_KEYS
    }
    return _sha256(
        json.dumps(
            {
                "workspace_id": str(connector.workspace_id),
                "connector_id": str(connector.id),
                "connector_type": str(connector.connector_type or "").strip().lower(),
                "config": stable_config,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )


def provider_account_fingerprint(connector: Connector) -> str:
    return _sha256(str(connector.credentials_json or ""))


def _observation_rejection_reason(
    observation: SourceSyncObservation,
    source: SourceDocument | None,
    *,
    checked_at: datetime,
    ttl: timedelta,
) -> str | None:
    if source is None:
        return "source_missing"
    connector = observation.connector
    sync_job = observation.sync_job
    actual_hash = _sha256(source.content or "")
    if (
        observation.workspace_id != source.workspace_id
        or observation.source_identity_sha256 != source.source_identity_sha256
        or observation.content_sha256 != actual_hash
        or (source.content_sha256 and source.content_sha256 != actual_hash)
        or observation.provider_object_id != source.external_id
    ):
        return "source_revision_mismatch"
    if connector is None or connector.status != "connected":
        return "connector_not_connected"
    if connector.workspace_id != source.workspace_id:
        return "connector_workspace_mismatch"
    if observation.provider != str(
        connector.connector_type or ""
    ).strip().lower() or not _connector_matches_source(connector, source):
        return "provider_source_mismatch"
    if observation.scope_snapshot_sha256 != connector_scope_snapshot_sha256(connector):
        return "connector_scope_changed"
    if observation.provider_account_fingerprint != provider_account_fingerprint(connector):
        return "provider_account_changed"
    observed_at = _utc_naive(observation.observed_at)
    if observed_at > checked_at + MAX_PROVIDER_CLOCK_SKEW or checked_at - observed_at > ttl:
        return "observation_expired"
    if sync_job is None:
        return "sync_job_missing"
    if sync_job.connector_id != connector.id or sync_job.workspace_id != source.workspace_id:
        return "sync_job_scope_mismatch"
    if (
        sync_job.status != "completed"
        or sync_job.completed_at is None
        or observation.sync_attempt_count != int(sync_job.attempt_count or 0)
    ):
        return "sync_attempt_not_completed"
    started_at = _utc_naive(sync_job.started_at or sync_job.created_at)
    completed_at = _utc_naive(sync_job.completed_at)
    if (
        # Do not allow the clock-skew allowance before the current attempt's
        # start. Graceful shutdown deliberately reuses an attempt count, so an
        # observation from the cancelled run could otherwise become valid when
        # the replacement run completes a few seconds later.
        observed_at < started_at or observed_at > completed_at + MAX_PROVIDER_CLOCK_SKEW
    ):
        return "observation_outside_completed_attempt"
    return None


def _metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _connector_matches_source(
    connector: Connector,
    source: SourceDocument,
) -> bool:
    connector_type = str(connector.connector_type or "").strip().lower()
    source_type = str(source.source_type or "").strip().lower()
    return source_type in PROVIDER_SOURCE_TYPES_BY_CONNECTOR.get(
        connector_type,
        frozenset(),
    )


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
