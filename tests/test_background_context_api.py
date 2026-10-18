"""Public background-context regressions through real capture and admission."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.models import SessionEvent, SourceDocument, Workspace
from app.services.checkpoints import (
    _checkpoint_is_materialized, capture_checkpoint, get_checkpoint,
)
from app.services.session_events import NormalizedSessionEvent, persist_session_events


async def _captured_session(db_session, tmp_path, *, request: str | None):
    workspace = Workspace(
        id=uuid4(), name="Background API workspace", slug=f"background-{uuid4().hex}"
    )
    db_session.add(workspace)
    await db_session.flush()
    session_id = f"background-{uuid4().hex}"
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{session_id}",
        content="Captured session evidence for user-led background.",
        metadata_json=json.dumps({"cwd": str(tmp_path)}),
    )
    db_session.add(document)
    await db_session.flush()
    events = []
    if request is not None:
        events.append(NormalizedSessionEvent(
            provider_event_id="request", sequence_number=1,
            event_type="user_request", role="user", content=request,
            occurred_at="2026-09-01T10:00:00Z",
        ))
    events.extend([
        NormalizedSessionEvent(
            provider_event_id="progress", sequence_number=2,
            event_type="assistant_update", role="assistant",
            content="Implemented a bounded cache in app/cache.py.",
            occurred_at="2026-09-01T10:01:00Z",
        ),
        NormalizedSessionEvent(
            provider_event_id="compact-1", sequence_number=3,
            event_type="compaction_boundary", payload={"window_id": "window-2"},
            occurred_at="2026-09-01T10:02:00Z",
        ),
        NormalizedSessionEvent(
            provider_event_id="decision", sequence_number=4,
            event_type="assistant_update", role="assistant",
            content="We decided to preserve the existing cache expiry behavior.",
            occurred_at="2026-09-01T10:03:00Z",
        ),
        NormalizedSessionEvent(
            provider_event_id="compact-2", sequence_number=5,
            event_type="compaction_boundary", payload={"window_id": "window-3"},
            occurred_at="2026-09-01T10:04:00Z",
        ),
        NormalizedSessionEvent(
            provider_event_id="capture-tip", sequence_number=6,
            event_type="assistant_update", role="assistant",
            content="The cache key includes the workspace identifier.",
            occurred_at="2026-09-01T10:05:00Z",
        ),
    ])
    await persist_session_events(
        db_session, workspace_id=workspace.id, source_document=document,
        provider="codex", session_id=session_id, events=events,
    )
    checkpoint = await capture_checkpoint(
        db_session, workspace_id=workspace.id, provider="codex",
        session_id=session_id, trigger="manual",
    )
    checkpoint = await get_checkpoint(db_session, checkpoint.id)
    assert checkpoint is not None
    assert _checkpoint_is_materialized(checkpoint)
    await db_session.commit()
    return workspace, document, checkpoint


async def _background(client, workspace, checkpoint):
    response = await client.post(
        f"/api/checkpoints/{checkpoint.id}/handoff",
        json={"workspace_id": str(workspace.id), "handoff_origin": "selected"},
    )
    assert response.status_code == 200, response.text
    artifact = response.json()
    assert artifact["schema_version"] == "session_background.v1"
    assert artifact["context_role"] == "background_only"
    assert artifact["quality_report"]["copy_ready"] is True, artifact["quality_evaluation"]
    assert artifact["operation_capabilities"]["clipboard_copy"]["allowed"] is True
    assert artifact["quality_control"]["status"] == "active", artifact["quality_control"]
    assert artifact["quality_control"]["copy_allowed"] is True
    assert artifact["delivery"]["ready_for_execution"] is False
    assert artifact["sha256"] == hashlib.sha256(artifact["content"].encode()).hexdigest()
    return artifact


async def test_background_api_preserves_assistant_state_without_inventing_a_user_goal(
    client, db_session, tmp_path,
):
    workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path, request=None,
    )
    assert not any(item.category == "goal" for item in checkpoint.items)

    artifact = await _background(client, workspace, checkpoint)

    assert not artifact["current_goal"].get("text")
    assert not artifact["current_goal"].get("request_verbatim")
    assert "No unambiguous prior user objective was recovered" in artifact["content"]
    assert "Implemented a bounded cache" in artifact["content"], artifact["content"]
    assert not any(claim["kind"] == "prior_user_objective" for claim in artifact["claim_manifest"])
    assert "prior_user_objective_unresolved" in {
        warning["code"] for warning in artifact["quality_report"]["warnings"]
    }


async def test_background_api_copies_selected_history_and_labels_its_capture_boundary(
    client, db_session, tmp_path,
):
    workspace, document, checkpoint = await _captured_session(
        db_session, tmp_path, request="Explain how the workspace cache is organized.",
    )
    await persist_session_events(
        db_session, workspace_id=workspace.id, source_document=document,
        provider="codex", session_id=checkpoint.session_id,
        events=[NormalizedSessionEvent(
            provider_event_id="later-update", sequence_number=7,
            event_type="assistant_update", role="assistant",
            content="POST_CAPTURE_ONLY: removed the cache implementation.",
            occurred_at="2026-09-01T10:06:00Z",
        )],
    )
    await db_session.commit()

    artifact = await _background(client, workspace, checkpoint)

    assert artifact["boundary"]["has_newer_events"] is True
    assert artifact["boundary"]["sequence_number"] == 6
    assert "[older snapshot]" in artifact["content"]
    assert "Session event boundary time: 2026-09-01 10:05:00" in artifact["content"]
    assert "POST_CAPTURE_ONLY" not in artifact["content"]
    assert "session_snapshot_historical" in {
        warning["code"] for warning in artifact["quality_report"]["warnings"]
    }


async def test_background_api_copies_text_with_an_honest_missing_image_notice(
    client, db_session, tmp_path,
):
    workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path,
        request="Explain the cache panel shown in the attached screenshot.",
    )

    artifact = await _background(client, workspace, checkpoint)

    assert artifact["quality_report"]["status"] == "ready_with_limitations"
    discovery = artifact["readiness_dimensions"]["dependency_discovery"]
    assert discovery["complete"] is False
    assert any(item["kind"] == "image" for item in discovery["unresolved_dependencies"])
    assert "unresolved" in artifact["content"].casefold()
    assert "image" in artifact["content"].casefold()
    assert artifact["quality_report"]["warnings"]
    assert artifact["operation_capabilities"]["automatic_execution"]["allowed"] is False


async def test_background_api_keeps_wrong_workspace_inaccessible(
    client, db_session, tmp_path,
):
    _workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path, request="Explain how the workspace cache is organized.",
    )
    other_workspace = Workspace(
        id=uuid4(), name="Other workspace", slug=f"other-{uuid4().hex}"
    )
    db_session.add(other_workspace)
    await db_session.commit()

    response = await client.post(
        f"/api/checkpoints/{checkpoint.id}/handoff",
        json={"workspace_id": str(other_workspace.id), "handoff_origin": "selected"},
    )

    assert response.status_code == 404


async def test_background_api_rejects_corrupted_checkpoint_bytes(
    client, db_session, tmp_path,
):
    workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path, request="Explain how the workspace cache is organized.",
    )
    checkpoint.payload_json += " "
    await db_session.commit()

    response = await client.post(
        f"/api/checkpoints/{checkpoint.id}/handoff",
        json={"workspace_id": str(workspace.id), "handoff_origin": "selected"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Checkpoint content failed integrity validation."


async def test_background_api_can_select_earlier_goal_free_history_after_a_later_task(
    client, db_session, tmp_path,
):
    workspace, document, earlier = await _captured_session(
        db_session, tmp_path, request=None,
    )
    await persist_session_events(
        db_session, workspace_id=workspace.id, source_document=document,
        provider="codex", session_id=earlier.session_id,
        events=[NormalizedSessionEvent(
            provider_event_id="new-task", sequence_number=7,
            event_type="user_request", role="user",
            content="Explain how cache expiry works.",
        )],
    )
    later = await capture_checkpoint(
        db_session, workspace_id=workspace.id, provider="codex",
        session_id=earlier.session_id, trigger="manual",
    )
    later = await get_checkpoint(db_session, later.id)
    await db_session.commit()
    assert later is not None
    await _background(client, workspace, later)

    artifact = await _background(client, workspace, earlier)

    assert "[older snapshot]" in artifact["content"]
    assert "Explain how cache expiry works" not in artifact["content"]
    assert "Implemented a bounded cache" in artifact["content"]


async def test_background_api_labels_bounded_history_instead_of_silent_omission(
    client, db_session, tmp_path, monkeypatch,
):
    workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path, request=None,
    )
    monkeypatch.setattr("app.services.checkpoints.SESSION_BACKGROUND_MAX_SOURCE_EVENTS", 1)

    artifact = await _background(client, workspace, checkpoint)

    projection = artifact["source_projection"]
    assert projection["source_event_limit"] == 1
    assert projection["total_source_event_count"] == 3
    assert projection["omitted_source_event_count"] == 2
    assert projection["first_source_sequence"] == 6
    assert projection["last_source_sequence"] == 6
    assert "[limited history]" in artifact["content"]
    assert "Implemented a bounded cache" not in artifact["content"]
    assert artifact["quality_report"]["status"] == "ready_with_limitations"


async def test_background_api_rejects_changed_source_event_without_a_matching_hash(
    client, db_session, tmp_path,
):
    workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path, request=None,
    )
    event = await db_session.scalar(select(SessionEvent).where(
        SessionEvent.workspace_id == workspace.id,
        SessionEvent.session_id == checkpoint.session_id,
        SessionEvent.provider_event_id == "progress",
    ))
    assert event is not None
    original_hash = event.content_sha256
    event.content = "FABRICATED_REPLACEMENT: all checks passed."
    await db_session.commit()
    assert event.content_sha256 == original_hash

    response = await client.post(
        f"/api/checkpoints/{checkpoint.id}/handoff",
        json={"workspace_id": str(workspace.id), "handoff_origin": "selected"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Background source event integrity is invalid."
    assert "FABRICATED_REPLACEMENT" not in response.text


async def test_background_api_retains_an_unresolved_yes_as_history_only(
    client, db_session, tmp_path,
):
    workspace, _document, checkpoint = await _captured_session(
        db_session, tmp_path, request="yes",
    )
    assert not any(item.category == "goal" for item in checkpoint.items)

    artifact = await _background(client, workspace, checkpoint)

    assert not artifact["current_goal"].get("request_verbatim")
    assert not any(claim["kind"] == "prior_user_objective" for claim in artifact["claim_manifest"])
    assert any(
        item["role"] == "user" and item["text"] == "yes"
        for item in artifact["supporting_context"]
    )
    assert "yes" in artifact["content"]
    assert "No unambiguous prior user objective was recovered" in artifact["content"]
    assert artifact["delivery"]["ready_for_execution"] is False
