from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import (
    Connector,
    SourceSyncObservation,
    SyncJob,
    Workspace,
)
from app.services.provider_freshness import (
    load_provider_freshness,
    provider_source_is_fresh,
    record_provider_observation,
)
from app.services.source_revisions import ingest_source_document_revision


async def _workspace_and_connector(
    db_session,
    *,
    name: str,
) -> tuple[Workspace, Connector]:
    workspace = Workspace(
        id=uuid4(),
        name=name,
        slug=f"provider-freshness-{uuid4().hex}",
    )
    connector = Connector(
        id=uuid4(),
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({"repositories": ["acme/daemonstate"]}),
        credentials_json=json.dumps({"access_token": "test-token"}),
    )
    db_session.add_all([workspace, connector])
    await db_session.flush()
    return workspace, connector


async def _completed_job(
    db_session,
    *,
    connector: Connector,
    observed_at: datetime,
    status: str = "completed",
) -> SyncJob:
    job = SyncJob(
        id=uuid4(),
        workspace_id=connector.workspace_id,
        connector_id=connector.id,
        status=status,
        attempt_count=1,
        started_at=observed_at - timedelta(minutes=1),
        completed_at=(observed_at + timedelta(minutes=1) if status == "completed" else None),
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def _provider_source(
    db_session,
    *,
    workspace: Workspace,
    content: str = "State: open",
    metadata_json: dict | None = None,
):
    return await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="github",
        external_id="github:acme/daemonstate:issue:7",
        content=content,
        metadata_json=metadata_json
        or {
            "item_type": "issue",
            "state": "open",
        },
    )


async def test_completed_observation_is_exact_revision_bound_and_expires(
    db_session,
):
    workspace, connector = await _workspace_and_connector(
        db_session,
        name="Exact provider observation",
    )
    source_result = await _provider_source(db_session, workspace=workspace)
    observed_at = datetime(2026, 7, 24, 12, 0, 0)
    job = await _completed_job(
        db_session,
        connector=connector,
        observed_at=observed_at,
    )
    observation = await record_provider_observation(
        db_session,
        connector=connector,
        source=source_result.document,
        sync_job=job,
        observed_at=observed_at,
        provider_version="etag-7",
    )
    await db_session.flush()

    status = (
        await load_provider_freshness(
            db_session,
            [source_result.document],
            now=observed_at + timedelta(minutes=2),
        )
    )[source_result.document.id]
    assert status.fresh is True
    assert status.observed_at == observed_at
    assert status.observation_id == str(observation.id)
    assert await provider_source_is_fresh(
        db_session,
        source_result.document,
        now=observed_at + timedelta(minutes=2),
    )
    assert not await provider_source_is_fresh(
        db_session,
        source_result.document,
        now=observed_at + timedelta(minutes=16),
    )

    revised = await _provider_source(
        db_session,
        workspace=workspace,
        content="State: closed",
        metadata_json={"item_type": "issue", "state": "closed"},
    )
    assert revised.document.id != source_result.document.id
    assert not await provider_source_is_fresh(
        db_session,
        revised.document,
        now=observed_at + timedelta(minutes=2),
    )


async def test_uncompleted_or_unattributed_observations_are_never_fresh(
    db_session,
):
    workspace, connector = await _workspace_and_connector(
        db_session,
        name="Incomplete provider observation",
    )
    source = (await _provider_source(db_session, workspace=workspace)).document
    observed_at = datetime(2026, 7, 24, 12, 0, 0)
    running_job = await _completed_job(
        db_session,
        connector=connector,
        observed_at=observed_at,
        status="running",
    )
    await record_provider_observation(
        db_session,
        connector=connector,
        source=source,
        sync_job=running_job,
        observed_at=observed_at,
    )
    await record_provider_observation(
        db_session,
        connector=connector,
        source=source,
        observed_at=observed_at,
    )
    await db_session.flush()

    assert not await provider_source_is_fresh(
        db_session,
        source,
        now=observed_at + timedelta(minutes=2),
    )
    assert (
        await db_session.scalar(
            select(func.count(SourceSyncObservation.id)).where(
                SourceSyncObservation.source_document_id == source.id
            )
        )
        == 2
    )


async def test_observation_from_cancelled_reused_attempt_is_not_resurrected(
    db_session,
):
    workspace, connector = await _workspace_and_connector(
        db_session,
        name="Reused provider attempt",
    )
    source = (await _provider_source(db_session, workspace=workspace)).document
    observed_at = datetime(2026, 7, 24, 12, 0, 0)
    job = await _completed_job(
        db_session,
        connector=connector,
        observed_at=observed_at,
        status="running",
    )
    await record_provider_observation(
        db_session,
        connector=connector,
        source=source,
        sync_job=job,
        observed_at=observed_at,
    )

    # Graceful shutdown decrements the attempt count, so the replacement run
    # can complete with the same number. Its later started_at must still fence
    # off observations persisted by the cancelled run.
    job.status = "completed"
    job.started_at = observed_at + timedelta(seconds=10)
    job.completed_at = observed_at + timedelta(seconds=20)
    await db_session.flush()

    assert not await provider_source_is_fresh(
        db_session,
        source,
        now=observed_at + timedelta(minutes=1),
    )


async def test_observation_requires_a_workspace_bound_sync_job(db_session):
    workspace, connector = await _workspace_and_connector(
        db_session,
        name="Provider job workspace",
    )
    source = (await _provider_source(db_session, workspace=workspace)).document
    observed_at = datetime(2026, 7, 24, 12, 0, 0)
    job = await _completed_job(
        db_session,
        connector=connector,
        observed_at=observed_at,
    )
    job.workspace_id = None
    await db_session.flush()

    with pytest.raises(
        ValueError,
        match="does not match its sync job",
    ):
        await record_provider_observation(
            db_session,
            connector=connector,
            source=source,
            sync_job=job,
            observed_at=observed_at,
        )


async def test_observation_rejects_a_different_provider_connector(db_session):
    workspace, connector = await _workspace_and_connector(
        db_session,
        name="Mismatched provider observation",
    )
    source = (await _provider_source(db_session, workspace=workspace)).document
    connector.connector_type = "slack"
    await db_session.flush()

    with pytest.raises(
        ValueError,
        match="source does not match its connector",
    ):
        await record_provider_observation(
            db_session,
            connector=connector,
            source=source,
        )


async def test_connector_scope_or_account_change_invalidates_observation(
    db_session,
):
    workspace, connector = await _workspace_and_connector(
        db_session,
        name="Provider scope snapshot",
    )
    source = (await _provider_source(db_session, workspace=workspace)).document
    observed_at = datetime(2026, 7, 24, 12, 0, 0)
    job = await _completed_job(
        db_session,
        connector=connector,
        observed_at=observed_at,
    )
    await record_provider_observation(
        db_session,
        connector=connector,
        source=source,
        sync_job=job,
        observed_at=observed_at,
    )
    await db_session.flush()

    connector.config_json = json.dumps(
        {
            "repositories": ["acme/daemonstate"],
            "items_synced": 42,
            "total_processed_count": 42,
        }
    )
    await db_session.flush()
    assert await provider_source_is_fresh(
        db_session,
        source,
        now=observed_at + timedelta(minutes=2),
    )

    connector.config_json = json.dumps({"repositories": ["acme/other-repo"]})
    await db_session.flush()
    assert not await provider_source_is_fresh(
        db_session,
        source,
        now=observed_at + timedelta(minutes=2),
    )

    connector.config_json = json.dumps({"repositories": ["acme/daemonstate"]})
    connector.credentials_json = json.dumps({"access_token": "rotated-token"})
    await db_session.flush()
    assert not await provider_source_is_fresh(
        db_session,
        source,
        now=observed_at + timedelta(minutes=2),
    )
