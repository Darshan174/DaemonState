from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import (
    CheckpointEvidence,
    CheckpointItem,
    CheckpointVerification,
    SessionEvent,
    SourceDocument,
    WorkCheckpoint,
    Workspace,
)
from app.services.checkpoints import (
    CHECKPOINT_CATEGORIES,
    capture_checkpoint,
    capture_checkpoint_schema_upgrades,
    capture_missing_compaction_checkpoints,
    checkpoint_to_dict,
    get_checkpoint,
    latest_checkpoint,
)
from app.services.checkpoint_verifier import (
    AUTOMATIC_REPLAY_DISABLED_REASON,
    _safe_replay_commands,
)
from app.services.local_harness import RepositorySnapshot
from app.services.session_events import NormalizedSessionEvent, persist_session_events


async def test_checkpoint_capture_is_structured_evidenced_and_idempotent(
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="checkpoint-session",
        events=_events(),
    )
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "app.services.checkpoints.capture_repository_snapshot",
        _async_value(snapshot),
    )

    first = await capture_missing_compaction_checkpoints(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="checkpoint-session",
    )
    second = await capture_missing_compaction_checkpoints(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="checkpoint-session",
    )

    assert len(first) == 1
    assert second[0].id == first[0].id
    assert await db_session.scalar(select(func.count()).select_from(WorkCheckpoint)) == 1
    loaded = await get_checkpoint(db_session, first[0].id)
    data = checkpoint_to_dict(loaded)
    assert data["schema_version"] == "work_checkpoint.v5"
    assert data["capture_status"] == "complete"
    assert data["continuation_status"] == "ready"
    assert data["boundary"]["snapshot_phase"] == "pre_compaction"
    assert data["boundary"]["snapshot_phase_label"] == "Pre-compaction snapshot"
    assert tuple(data["sections"]) == CHECKPOINT_CATEGORIES
    assert data["sections"]["goal"][0]["statement"] == "Implement durable checkpoints for session compaction."
    assert data["task_key"] == data["sections"]["goal"][0]["evidence"][0]["session_event_id"]
    assert "app/core.py" in {
        item["statement"] for item in data["sections"]["relevant_files"]
    }
    assert data["sections"]["verification"][0]["payload"]["passed"] is True
    assert data["sections"]["exact_next_action"][0]["statement"]
    assert all(
        item["evidence"]
        for category in CHECKPOINT_CATEGORIES
        for item in data["sections"][category]
    )
    assert await db_session.scalar(select(func.count()).select_from(CheckpointItem)) > 0
    assert await db_session.scalar(select(func.count()).select_from(CheckpointEvidence)) > 0


async def test_current_checkpoint_schema_backfills_from_unchanged_normalized_events(
    db_session,
    tmp_path,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="schema-upgrade",
        events=_events(),
    )
    legacy = (await capture_missing_compaction_checkpoints(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="schema-upgrade",
    ))[0]
    legacy.schema_version = "work_checkpoint.v1"
    await db_session.flush()

    assert await capture_checkpoint_schema_upgrades(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="schema-upgrade",
    ) == 1
    assert await capture_checkpoint_schema_upgrades(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="schema-upgrade",
    ) == 0
    versions = set(await db_session.scalars(
        select(WorkCheckpoint.schema_version).where(
            WorkCheckpoint.workspace_id == workspace.id,
            WorkCheckpoint.session_id == "schema-upgrade",
        )
    ))
    assert versions == {"work_checkpoint.v1", "work_checkpoint.v5"}


async def test_manual_tip_checkpoint_is_not_labeled_pre_compaction(
    db_session,
    tmp_path,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    events = [
        *_events(),
        NormalizedSessionEvent(
            provider_event_id="assistant-after-compaction",
            sequence_number=6,
            event_type="assistant_update",
            role="assistant",
            content="Continued working after the compaction boundary.",
        ),
    ]
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="manual-tip-session",
        events=events,
    )

    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="manual-tip-session",
        trigger="manual",
    )
    data = checkpoint_to_dict(await get_checkpoint(db_session, checkpoint.id))

    assert data["boundary"]["snapshot_phase"] == "session_tip"
    assert data["boundary"]["snapshot_phase_label"] == "Session-tip snapshot"


async def test_checkpoint_api_captures_verifies_and_builds_resume_bundle(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="checkpoint-session",
        events=_events(),
    )
    await db_session.commit()
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "app.services.checkpoints.capture_repository_snapshot",
        _async_value(snapshot),
    )
    monkeypatch.setattr(
        "app.services.checkpoint_verifier.capture_repository_snapshot",
        _async_value(snapshot),
    )

    captured = await client.post("/api/checkpoints/capture", json={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "checkpoint-session",
    })
    assert captured.status_code == 200
    checkpoint = captured.json()
    assert checkpoint["sections"]["goal"]
    assert checkpoint["sections"]["exact_next_action"]
    assert checkpoint["created_at"].endswith("Z")
    assert checkpoint["boundary"]["captured_at"].endswith("Z")

    compared = await client.get(
        f"/api/checkpoints/{checkpoint['id']}/compare?workspace_id={workspace.id}"
    )
    assert compared.status_code == 200
    assert compared.json()["status"] == "matched"
    assert compared.json()["current"]["changed_files"] == ["app/core.py"]

    changed_snapshot = replace(
        snapshot,
        head_commit="def456",
        status_fingerprint="fingerprint-2",
        changed_files=("app/core.py", "app/new.py"),
    )
    monkeypatch.setattr(
        "app.services.checkpoint_verifier.capture_repository_snapshot",
        _async_value(changed_snapshot),
    )
    changed = await client.get(
        f"/api/checkpoints/{checkpoint['id']}/compare?workspace_id={workspace.id}"
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "changed"
    assert changed.json()["captured"]["head_commit"] == "abc123"
    assert changed.json()["current"]["head_commit"] == "def456"

    monkeypatch.setattr(
        "app.services.checkpoint_verifier.capture_repository_snapshot",
        _async_value(snapshot),
    )
    verified = await client.post(
        f"/api/checkpoints/{checkpoint['id']}/verify",
        json={"workspace_id": str(workspace.id), "execute_commands": False},
    )
    assert verified.status_code == 200
    assert verified.json()["verification"]["status"] == "verified"
    assert await db_session.scalar(
        select(func.count()).select_from(CheckpointVerification)
    ) == 1

    repeated = await client.post(
        f"/api/checkpoints/{checkpoint['id']}/verify",
        json={"workspace_id": str(workspace.id), "execute_commands": False},
    )
    assert repeated.status_code == 200
    assert await db_session.scalar(
        select(func.count()).select_from(CheckpointVerification)
    ) == 1

    latest = await client.get(
        f"/api/checkpoints/latest?workspace_id={workspace.id}"
    )
    assert latest.status_code == 200
    assert latest.json()["id"] == checkpoint["id"]

    history = await client.get(f"/api/checkpoints?workspace_id={workspace.id}")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["checkpoints"]] == [checkpoint["id"]]

    launched: dict = {}

    def _launch(provider, session_id, *, cwd=None):
        launched.update({"provider": provider, "session_id": session_id, "cwd": cwd})
        return {"launched": True, "navigation": "session"}

    monkeypatch.setattr("app.api.checkpoints.launch_harness_session", _launch)
    resumed = await client.post(
        f"/api/checkpoints/{checkpoint['id']}/resume",
        json={"workspace_id": str(workspace.id), "launch_session": True},
    )
    assert resumed.status_code == 200
    assert resumed.json()["schema_version"] == "resume_bundle.v1"
    assert "## Exact next action" in resumed.json()["content"]
    assert "Snapshot phase: Pre-compaction snapshot" in resumed.json()["content"]
    assert "evidence:" in resumed.json()["content"]
    assert resumed.json()["launch"]["launched"] is True
    assert launched == {
        "provider": "codex",
        "session_id": "checkpoint-session",
        "cwd": str(tmp_path),
    }


async def test_explicit_verification_keeps_imported_commands_as_untrusted_evidence(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    recorded_command = "npm test -- --run\nnpm run build"
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="checkpoint-session",
        events=_events_with_verification_command(recorded_command),
    )
    await db_session.commit()
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "app.services.checkpoints.capture_repository_snapshot",
        _async_value(snapshot),
    )
    monkeypatch.setattr(
        "app.services.checkpoint_verifier.capture_repository_snapshot",
        _async_value(snapshot),
    )
    captured = await client.post("/api/checkpoints/capture", json={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "checkpoint-session",
    })
    response = await client.post(
        f"/api/checkpoints/{captured.json()['id']}/verify",
        json={"workspace_id": str(workspace.id), "execute_commands": True},
    )

    assert response.status_code == 200
    verification = response.json()["verification"]
    assert verification["status"] == "partial"
    assert verification["results"]["replay_results"] == []
    assert verification["results"]["replay_rejections"] == [{
        "command": recorded_command,
        "reason": AUTOMATIC_REPLAY_DISABLED_REASON,
    }]


async def test_historical_command_failure_is_context_not_a_launch_blocker(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    events = _events()
    events[3] = replace(
        events[3],
        content="1 failed",
        payload={
            **events[3].payload,
            "exit_code": 1,
            "passed": False,
        },
    )
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="failed-check-session",
        events=events,
    )
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "app.services.checkpoints.capture_repository_snapshot",
        _async_value(snapshot),
    )
    monkeypatch.setattr(
        "app.services.checkpoint_verifier.capture_repository_snapshot",
        _async_value(snapshot),
    )
    await db_session.commit()

    captured = await client.post("/api/checkpoints/capture", json={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "failed-check-session",
    })

    assert captured.status_code == 200
    checkpoint = captured.json()
    assert checkpoint["continuation_status"] == "ready"
    assert checkpoint["sections"]["blockers"] == []
    assert checkpoint["sections"]["failed_attempts"]
    assert checkpoint["sections"]["verification"][0]["payload"]["passed"] is False
    assert checkpoint["sections"]["exact_next_action"][0]["statement"] == (
        "run the focused tests."
    )

    response = await client.post(
        f"/api/checkpoints/{checkpoint['id']}/verify",
        json={"workspace_id": str(workspace.id), "execute_commands": False},
    )

    assert response.status_code == 200
    verification = response.json()["verification"]
    assert verification["status"] == "partial"
    assert verification["results"]["historical_verification_failures"] == 1
    observed = next(
        check
        for check in verification["results"]["checks"]
        if check["name"] == "observed_verification"
    )
    assert observed["status"] == "failed"


async def test_later_progress_supersedes_reported_intermediate_blocker(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="reported-blocker-session",
        events=[
            NormalizedSessionEvent(
                provider_event_id="reported-blocker:user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content="Finish the portable continuation workflow.",
            ),
            NormalizedSessionEvent(
                provider_event_id="reported-blocker:blocked",
                sequence_number=2,
                event_type="assistant_update",
                role="assistant",
                content="Blocker: the continuation endpoint still rejects historical runs.",
            ),
            NormalizedSessionEvent(
                provider_event_id="reported-blocker:fixed",
                sequence_number=3,
                event_type="assistant_update",
                role="assistant",
                content=(
                    "Implemented the fix and the focused tests passed. "
                    "Next action: verify the final Continue screen."
                ),
            ),
        ],
    )
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "app.services.checkpoints.capture_repository_snapshot",
        _async_value(snapshot),
    )
    await db_session.commit()

    captured = await client.post("/api/checkpoints/capture", json={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "reported-blocker-session",
    })

    assert captured.status_code == 200, captured.text
    checkpoint = captured.json()
    assert checkpoint["continuation_status"] == "ready"
    assert checkpoint["sections"]["blockers"][0]["state"] == "historical"
    assert checkpoint["sections"]["exact_next_action"][0]["statement"] == (
        "verify the final Continue screen."
    )


def test_safe_replay_commands_splits_cr_and_rejects_unsafe_input() -> None:
    assert _safe_replay_commands("npm test -- --run\rnpm run build") == (
        ("npm test -- --run", ("npm", "test", "--", "--run")),
        ("npm run build", ("npm", "run", "build")),
    )

    with pytest.raises(ValueError, match="NUL"):
        _safe_replay_commands("npm test -- --run\x00npm run build")

    with pytest.raises(ValueError, match="shell operators"):
        _safe_replay_commands("npm test -- --run\nnpm run build && npm publish")

    with pytest.raises(ValueError, match="allowlisted"):
        _safe_replay_commands("rm -rf . pytest")

    with pytest.raises(ValueError, match="allowlisted"):
        _safe_replay_commands("npm publish")


async def test_explicit_verification_never_executes_even_a_malformed_imported_command(
    client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    recorded_command = "npm test -- --run\x00npm run build"
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="checkpoint-session",
        events=_events_with_verification_command(recorded_command),
    )
    await db_session.commit()
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "app.services.checkpoints.capture_repository_snapshot",
        _async_value(snapshot),
    )
    monkeypatch.setattr(
        "app.services.checkpoint_verifier.capture_repository_snapshot",
        _async_value(snapshot),
    )
    captured = await client.post("/api/checkpoints/capture", json={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "checkpoint-session",
    })
    response = await client.post(
        f"/api/checkpoints/{captured.json()['id']}/verify",
        json={"workspace_id": str(workspace.id), "execute_commands": True},
    )

    assert response.status_code == 200
    verification = response.json()["verification"]
    assert verification["status"] == "partial"
    results = verification["results"]
    assert results["replay_results"] == []
    assert results["replay_rejections"] == [{
        "command": recorded_command,
        "reason": AUTOMATIC_REPLAY_DISABLED_REASON,
    }]
    fresh_execution = next(
        check
        for check in results["checks"]
        if check["name"] == "fresh_command_execution"
    )
    assert fresh_execution["status"] == "not_available"


async def test_checkpoint_without_repository_snapshot_is_only_partial(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace = Workspace(
        id=uuid4(),
        name="No repository",
        slug=f"no-repository-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:no-repo",
        content="session",
        metadata_json="{}",
    )
    db_session.add(document)
    await db_session.flush()
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="no-repo",
        events=_events(),
    )
    await db_session.commit()
    captured = await client.post("/api/checkpoints/capture", json={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "no-repo",
    })
    compared = await client.get(
        f"/api/checkpoints/{captured.json()['id']}/compare?workspace_id={workspace.id}"
    )
    assert compared.status_code == 200
    assert compared.json()["status"] == "unavailable"
    assert compared.json()["current"] is None
    response = await client.post(
        f"/api/checkpoints/{captured.json()['id']}/verify",
        json={"workspace_id": str(workspace.id), "execute_commands": False},
    )
    assert response.status_code == 200
    assert response.json()["verification"]["status"] == "partial"


async def test_session_event_identity_is_scoped_per_workspace(db_session, tmp_path) -> None:
    first_workspace, first_document = await _session_source(db_session, tmp_path / "first")
    second_workspace, second_document = await _session_source(db_session, tmp_path / "second")

    first = await persist_session_events(
        db_session,
        workspace_id=first_workspace.id,
        source_document=first_document,
        provider="codex",
        session_id="shared-provider-session",
        events=_events(),
    )
    second = await persist_session_events(
        db_session,
        workspace_id=second_workspace.id,
        source_document=second_document,
        provider="codex",
        session_id="shared-provider-session",
        events=_events(),
    )

    assert first["created"] == len(_events())
    assert second["created"] == len(_events())
    assert await db_session.scalar(select(func.count()).select_from(SessionEvent)) == 10


async def test_checkpoint_keeps_substantive_goal_across_continue_and_runtime_policy(
    db_session,
    tmp_path,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    offending = "Note that collaboration tools cannot be called from inside functions.exec"
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="continuation-session",
        events=[
            NormalizedSessionEvent(
                provider_event_id="old-user",
                sequence_number=1,
                event_type="user_request",
                role="user",
                content="Fix unsupported connector providers.",
            ),
            NormalizedSessionEvent(
                provider_event_id="old-update",
                sequence_number=2,
                event_type="assistant_update",
                role="assistant",
                content="Unsupported providers are blocked and need another fix.",
            ),
            NormalizedSessionEvent(
                provider_event_id="real-goal",
                sequence_number=3,
                event_type="user_request",
                role="user",
                content="Implement reliable checkpoint selection.",
            ),
            NormalizedSessionEvent(
                provider_event_id="real-update",
                sequence_number=4,
                event_type="assistant_update",
                role="assistant",
                content=(
                    "Implemented end to end. Now displays the latest checkpoint and exact "
                    "next action. Runs is the checkpoint history with blocker evidence."
                ),
            ),
            NormalizedSessionEvent(
                provider_event_id="continue",
                sequence_number=5,
                event_type="user_request",
                role="user",
                content="continue",
            ),
            NormalizedSessionEvent(
                provider_event_id="policy",
                sequence_number=6,
                event_type="user_request",
                role="user",
                content=offending,
            ),
            NormalizedSessionEvent(
                provider_event_id="boundary",
                sequence_number=7,
                event_type="compaction_boundary",
            ),
            NormalizedSessionEvent(
                provider_event_id="final-update",
                sequence_number=8,
                event_type="assistant_update",
                role="assistant",
                content=(
                    "Implemented end to end. Now displays the latest checkpoint and exact "
                    "next action. Runs is the checkpoint history."
                ),
            ),
            NormalizedSessionEvent(
                provider_event_id="final-boundary",
                sequence_number=9,
                event_type="compaction_boundary",
            ),
            NormalizedSessionEvent(
                provider_event_id="delegated-task",
                sequence_number=10,
                event_type="runtime_instruction",
                role="user",
                content=(
                    "<codex_delegation><input>Continue the existing checkpoint task; "
                    "the live product is wrong.\n\nObserved defect: "
                    f"{offending}</input></codex_delegation>"
                ),
            ),
            NormalizedSessionEvent(
                provider_event_id="delegated-update",
                sequence_number=11,
                event_type="assistant_update",
                role="assistant",
                content="I am tracing the stored checkpoint boundary.",
            ),
            NormalizedSessionEvent(
                provider_event_id="delegated-boundary",
                sequence_number=12,
                event_type="compaction_boundary",
            ),
        ],
    )

    captured = await capture_missing_compaction_checkpoints(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="continuation-session",
    )
    loaded = await get_checkpoint(db_session, captured[0].id)
    data = checkpoint_to_dict(loaded)

    assert data["sections"]["goal"][0]["statement"] == (
        "Implement reliable checkpoint selection."
    )
    assert data["sections"]["exact_next_action"][0]["statement"].startswith(
        "Continue the current request: Implement reliable checkpoint selection."
    )
    rendered = json.dumps(data["sections"]).lower()
    assert "collaboration tools cannot be called" not in rendered
    assert "unsupported providers" not in rendered
    assert data["activity"]["provider"] == "codex"
    assert data["activity"]["session_id"] == "continuation-session"

    completed = checkpoint_to_dict(await get_checkpoint(db_session, captured[1].id))
    assert completed["sections"]["exact_next_action"][0]["statement"].startswith(
        "Review the completed result"
    )
    assert "runs is" not in completed["sections"]["exact_next_action"][0]["statement"].lower()

    delegated = checkpoint_to_dict(await get_checkpoint(db_session, captured[2].id))
    assert delegated["sections"]["goal"][0]["statement"] == (
        "Continue the existing checkpoint task; the live product is wrong."
    )
    assert "collaboration tools" not in json.dumps(delegated["sections"]).lower()


async def test_latest_checkpoint_uses_boundary_time_not_import_or_insert_time(
    db_session,
    tmp_path,
) -> None:
    workspace, newer_document = await _session_source(db_session, tmp_path / "newer")
    older_document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="opencode:session:historical-import",
        content="historical session",
        metadata_json=json.dumps({"cwd": str(tmp_path)}),
    )
    db_session.add(older_document)
    await db_session.flush()

    async def persist_and_capture(document, provider, session_id, occurred_at):
        await persist_session_events(
            db_session,
            workspace_id=workspace.id,
            source_document=document,
            provider=provider,
            session_id=session_id,
            events=[
                NormalizedSessionEvent(
                    provider_event_id=f"{session_id}-goal",
                    sequence_number=1,
                    event_type="user_request",
                    role="user",
                    occurred_at=occurred_at,
                    content=f"Implement {session_id}.",
                ),
                NormalizedSessionEvent(
                    provider_event_id=f"{session_id}-boundary",
                    sequence_number=2,
                    event_type="compaction_boundary",
                    occurred_at=occurred_at,
                ),
            ],
        )
        return (await capture_missing_compaction_checkpoints(
            db_session,
            workspace_id=workspace.id,
            provider=provider,
            session_id=session_id,
        ))[0]

    newer = await persist_and_capture(
        newer_document, "codex", "new-work", "2026-07-21T09:30:00Z"
    )
    # Insert the historical import last: database creation recency must not win.
    await persist_and_capture(
        older_document, "opencode", "historical-import", "2026-05-01T16:00:00Z"
    )

    selected = await latest_checkpoint(db_session, workspace_id=workspace.id)
    assert selected.id == newer.id
    assert selected.provider == "codex"
    assert selected.session_id == "new-work"


async def test_latest_checkpoint_session_filter_does_not_fall_back_to_workspace_latest(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="opencode",
        session_id="older-task",
        events=[
            NormalizedSessionEvent(
                provider_event_id="older-task-goal",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-23T09:00:00Z",
                content="Finish the older task.",
            ),
            NormalizedSessionEvent(
                provider_event_id="older-task-boundary",
                sequence_number=2,
                event_type="compaction_boundary",
                occurred_at="2026-07-23T09:30:00Z",
            ),
        ],
    )
    workspace_latest = (await capture_missing_compaction_checkpoints(
        db_session,
        workspace_id=workspace.id,
        provider="opencode",
        session_id="older-task",
    ))[0]

    assert (
        await latest_checkpoint(db_session, workspace_id=workspace.id)
    ).id == workspace_latest.id
    assert await latest_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="active-task-without-checkpoint",
    ) is None

    response = await client.get("/api/checkpoints/latest", params={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "active-task-without-checkpoint",
    })

    assert response.status_code == 404
    assert response.json()["detail"] == "Checkpoint not found"


async def test_latest_checkpoint_session_filter_selects_matching_boundary_time(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace, document = await _session_source(db_session, tmp_path)
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="codex",
        session_id="active-task",
        events=[
            NormalizedSessionEvent(
                provider_event_id="active-task-goal",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at="2026-04-01T08:00:00Z",
                content="Finish the active task.",
            ),
            NormalizedSessionEvent(
                provider_event_id="active-task-newer-boundary",
                sequence_number=2,
                event_type="compaction_boundary",
                occurred_at="2026-07-20T09:30:00Z",
            ),
            NormalizedSessionEvent(
                provider_event_id="active-task-older-boundary",
                sequence_number=3,
                event_type="compaction_boundary",
                occurred_at="2026-05-01T16:00:00Z",
            ),
        ],
    )
    newer_boundary = await db_session.scalar(select(SessionEvent).where(
        SessionEvent.provider_event_id == "active-task-newer-boundary"
    ))
    older_boundary = await db_session.scalar(select(SessionEvent).where(
        SessionEvent.provider_event_id == "active-task-older-boundary"
    ))
    matching_newer = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="active-task",
        boundary_event_id=newer_boundary.id,
    )
    # Capture the older boundary last: insert order must not decide the result.
    matching_older = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="active-task",
        boundary_event_id=older_boundary.id,
    )
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=document,
        provider="opencode",
        session_id="workspace-latest-task",
        events=[
            NormalizedSessionEvent(
                provider_event_id="workspace-latest-goal",
                sequence_number=1,
                event_type="user_request",
                role="user",
                occurred_at="2026-07-21T09:00:00Z",
                content="Finish the workspace-latest task.",
            ),
            NormalizedSessionEvent(
                provider_event_id="workspace-latest-boundary",
                sequence_number=2,
                event_type="compaction_boundary",
                occurred_at="2026-07-21T09:30:00Z",
            ),
        ],
    )
    workspace_latest = (await capture_missing_compaction_checkpoints(
        db_session,
        workspace_id=workspace.id,
        provider="opencode",
        session_id="workspace-latest-task",
    ))[0]

    assert matching_older.id != matching_newer.id
    assert (
        await latest_checkpoint(db_session, workspace_id=workspace.id)
    ).id == workspace_latest.id
    selected = await latest_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider=" CODEX ",
        session_id="active-task",
    )
    assert selected.id == matching_newer.id

    response = await client.get("/api/checkpoints/latest", params={
        "workspace_id": str(workspace.id),
        "provider": "CODEX",
        "session_id": "active-task",
    })

    assert response.status_code == 200
    assert response.json()["id"] == str(matching_newer.id)
    assert response.json()["boundary"]["occurred_at"].startswith("2026-07-20T09:30:00")


async def test_latest_checkpoint_session_filter_requires_a_complete_pair(
    client,
    db_session,
    tmp_path,
) -> None:
    workspace, _ = await _session_source(db_session, tmp_path)

    with pytest.raises(
        ValueError,
        match="provider and session_id must be provided together",
    ):
        await latest_checkpoint(
            db_session,
            workspace_id=workspace.id,
            provider="codex",
        )

    response = await client.get("/api/checkpoints/latest", params={
        "workspace_id": str(workspace.id),
        "provider": "codex",
    })

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "provider and session_id must be provided together"
    )


async def _session_source(db_session, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "app" / "core.py").write_text("READY = True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_ready():\n    assert True\n",
        encoding="utf-8",
    )
    workspace = Workspace(
        id=uuid4(),
        name="Checkpoint workspace",
        slug=f"checkpoint-workspace-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:checkpoint-session",
        content="session",
        metadata_json=json.dumps({
            "cwd": str(tmp_path),
            "source_path": str(tmp_path / "session.jsonl"),
        }),
    )
    db_session.add(document)
    await db_session.flush()
    return workspace, document


def _events() -> list[NormalizedSessionEvent]:
    return [
        NormalizedSessionEvent(
            provider_event_id="user-1",
            sequence_number=1,
            event_type="user_request",
            role="user",
            content="Implement durable checkpoints for session compaction.",
        ),
        NormalizedSessionEvent(
            provider_event_id="assistant-1",
            sequence_number=2,
            event_type="assistant_update",
            role="assistant",
            content=(
                "Implemented the checkpoint schema in app/core.py. "
                "We will keep every item linked to event evidence. "
                "Next action: run the focused tests."
            ),
        ),
        NormalizedSessionEvent(
            provider_event_id="command-1",
            sequence_number=3,
            event_type="command_call",
            role="assistant",
            content="pytest -q tests/test_core.py",
            payload={
                "call_id": "call-1",
                "tool_name": "exec",
                "command": "pytest -q tests/test_core.py",
            },
        ),
        NormalizedSessionEvent(
            provider_event_id="result-1",
            sequence_number=4,
            event_type="command_result",
            role="tool",
            content="2 passed",
            payload={
                "call_id": "call-1",
                "tool_name": "exec",
                "command": "pytest -q tests/test_core.py",
                "exit_code": 0,
                "passed": True,
            },
        ),
        NormalizedSessionEvent(
            provider_event_id="compact-1",
            sequence_number=5,
            event_type="compaction_boundary",
            payload={"window_id": "window-2", "turn_count": 2},
        ),
    ]


def _events_with_verification_command(
    command: str,
) -> list[NormalizedSessionEvent]:
    events = _events()
    events[2] = replace(
        events[2],
        content=command,
        payload={**events[2].payload, "command": command},
    )
    events[3] = replace(
        events[3],
        payload={**events[3].payload, "command": command},
    )
    return events


def _snapshot(root) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=str(root),
        branch="codex/checkpoints",
        head_commit="abc123",
        dirty=True,
        changed_files=("app/core.py",),
        status_fingerprint="fingerprint-1",
        diff_summary="app/core.py | 1 +",
        status_truncated=False,
        _entries=((" M", "app/core.py", None),),
    )


def _async_value(value):
    async def _result(*_args, **_kwargs):
        return value

    return _result
