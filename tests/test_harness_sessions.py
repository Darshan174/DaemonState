from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AgentRun, ContextPack, RunObservation, Workspace
from app.services.continuation_runtime import (
    active_continuation_run,
    active_continuation_run_payload,
)
from app.services.harness_sessions import (
    HarnessSessionBridge,
    harness_session_payload,
)
from app.services.harness_outcomes import HarnessOutcomeService
from app.time import utc_now


async def _running_continuation(db_session) -> tuple[Workspace, AgentRun]:
    workspace = Workspace(
        id=uuid4(),
        name=f"Visible harness {uuid4()}",
        slug=f"visible-harness-{uuid4().hex}",
    )
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective="Run this task in a visible Codex harness.",
        markdown="# Visible harness\n",
        manifest=json.dumps({"schema_version": "context_pack.v2"}),
        repo_state_json="{}",
        idempotency_key=f"visible-harness-{uuid4()}",
    )
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        run_key=f"continuation:{uuid4().hex}",
        tool="daemonstate:codex",
        model="codex",
        objective=pack.objective,
        started_at=utc_now(),
        status="running",
    )
    db_session.add_all([workspace, pack, run])
    await db_session.commit()
    return workspace, run


@pytest.mark.asyncio
async def test_codex_bridge_waits_for_renderable_activity_before_requesting_navigation(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    workspace, run = await _running_continuation(db_session)
    launches: list[tuple[str, str, str | None]] = []

    def launch(provider: str, session_id: str, *, cwd: str | None = None):
        launches.append((provider, session_id, cwd))
        return {
            "launched": True,
            "connector_type": provider,
            "harness": "Codex",
            "session_id": session_id,
            "mode": "desktop_app",
            "navigation": "session",
            "exact_session_supported": True,
            "topic_anchor_supported": False,
        }

    monkeypatch.setattr(
        "app.services.harness_sessions.launch_harness_session",
        launch,
    )
    monkeypatch.setattr(
        "app.api.continuations.launch_harness_session",
        launch,
    )
    thread_id = "019f9a4d-f586-79d3-b305-4844518003bd"
    bridge = HarnessSessionBridge(
        db_session,
        run=run,
        provider="codex",
        repo_path=str(tmp_path),
    )

    await bridge.observe_stdout_chunk(b'{"type":"thread.')
    assert bridge.state is None
    await bridge.observe_stdout_chunk(
        f'started","thread_id":"{thread_id}"}}\n'.encode()
    )

    captured_state = bridge.state
    assert captured_state is not None
    assert captured_state["provider"] == "codex"
    assert captured_state["session_id"] == thread_id
    assert captured_state["launched"] is False
    assert captured_state["navigation_requested"] is False
    assert captured_state["navigation_verified"] is False
    assert launches == []

    await bridge.observe_stdout_chunk(
        b'{"type":"turn.started"}\n'
    )
    assert launches == []

    await bridge.observe_stdout_chunk(
        b'{"type":"item.completed","item":{"id":"item-1",'
        b'"type":"agent_message","text":"Starting the visible task."}}\n'
    )

    assert bridge.state == {
        "provider": "codex",
        "session_id": thread_id,
        "launched": True,
        "mode": "desktop_app",
        "navigation": "session",
        "exact_session_supported": True,
        "navigation_requested": True,
        "navigation_verified": False,
        "renderable_activity_observed": True,
    }
    assert launches == [("codex", thread_id, str(tmp_path))]
    await bridge.finish()
    assert launches == [("codex", thread_id, str(tmp_path))]

    observations = list(await db_session.scalars(
        select(RunObservation).where(RunObservation.agent_run_id == run.id)
    ))
    provider_events = [
        item for item in observations if item.event_type == "provider_event"
    ]
    assert len(provider_events) == 3
    last_event = json.loads(provider_events[-1].payload_json)["provider_event"]
    assert last_event["type"] == "item.completed"
    assert last_event["item_type"] == "agent_message"
    assert last_event["text"] == "Starting the visible task."
    assert len(last_event["raw_sha256"]) == 64
    assert harness_session_payload(observations) == bridge.state

    active = await active_continuation_run(
        db_session,
        workspace_id=workspace.id,
    )
    assert active is not None
    active_payload = active_continuation_run_payload(active)
    assert active_payload is not None
    assert active_payload["phase"] == "agent_running"
    assert active_payload["harness_session"] == bridge.state

    response = await client.post(
        f"/api/continuations/{run.id}/open",
        json={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == thread_id
    assert response.json()["launch"]["launched"] is True
    assert launches == [
        ("codex", thread_id, str(tmp_path)),
        ("codex", thread_id, str(tmp_path)),
    ]

    run.status = "failed"
    run.ended_at = utc_now()
    await db_session.commit()
    latest = await HarnessOutcomeService(db_session).latest_continuation(
        workspace_id=workspace.id,
    )
    assert latest is not None
    assert latest["harness_session"] == bridge.state


@pytest.mark.asyncio
async def test_codex_bridge_finish_before_renderable_activity_persists_without_navigation(
    client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    workspace, run = await _running_continuation(db_session)
    launches: list[tuple[str, str, str | None]] = []

    def launch(provider: str, session_id: str, *, cwd: str | None = None):
        launches.append((provider, session_id, cwd))
        return {
            "launched": True,
            "navigation_requested": True,
            "navigation_verified": False,
            "mode": "desktop_app",
            "navigation": "session",
            "exact_session_supported": True,
        }

    monkeypatch.setattr(
        "app.services.harness_sessions.launch_harness_session",
        launch,
    )
    monkeypatch.setattr(
        "app.api.continuations.launch_harness_session",
        launch,
    )
    thread_id = "019f9a4d-f586-79d3-b305-4844518003be"
    bridge = HarnessSessionBridge(
        db_session,
        run=run,
        provider="codex",
        repo_path=str(tmp_path),
    )

    # A child can fail immediately after announcing its thread, before it
    # produces any item that the desktop app can render.
    await bridge.observe_stdout_chunk(
        (
            f'{{"type":"thread.started","thread_id":"{thread_id}"}}'
        ).encode()
    )
    await bridge.finish()

    assert launches == []
    assert bridge.state == {
        "provider": "codex",
        "session_id": thread_id,
        "launched": False,
        "navigation_requested": False,
        "navigation_verified": False,
        "mode": "desktop_app",
        "navigation": "session",
        "exact_session_supported": True,
        "renderable_activity_observed": False,
        "code": "navigation_deferred",
        "message": (
            "Captured the Codex thread before any renderable activity; "
            "automatic navigation was not requested."
        ),
    }

    observations = list(await db_session.scalars(
        select(RunObservation).where(RunObservation.agent_run_id == run.id)
    ))
    session_observation = next(
        item for item in observations if item.event_key == "harness:session"
    )
    assert len([
        item for item in observations if item.event_type == "provider_event"
    ]) == 1
    assert session_observation.content == (
        f"Captured codex harness session {thread_id}."
    )
    assert harness_session_payload(observations) == bridge.state

    active = await active_continuation_run(
        db_session,
        workspace_id=workspace.id,
    )
    assert active is not None
    active_payload = active_continuation_run_payload(active)
    assert active_payload is not None
    assert active_payload["harness_session"] == bridge.state

    # The persisted exact-thread link remains manually openable; only the
    # unsafe automatic launch is deferred.
    response = await client.post(
        f"/api/continuations/{run.id}/open",
        json={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == thread_id
    assert launches == [("codex", thread_id, str(tmp_path))]


@pytest.mark.asyncio
async def test_open_harness_waits_for_a_provider_session(
    client,
    db_session,
) -> None:
    workspace, run = await _running_continuation(db_session)

    response = await client.post(
        f"/api/continuations/{run.id}/open",
        json={"workspace_id": str(workspace.id)},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "harness_session_pending"
