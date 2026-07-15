from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models import (
    AgentRun,
    Component,
    ContextPack,
    ContextPackItem,
    Model,
    OpenLoop,
    RunObservation,
    SourceDocument,
    VerifiedPlaybook,
    Workspace,
)
from app.services.founder_oversight import FounderOversightService
from app.services.open_loops import OpenLoopService
from app.services.playbooks import PlaybookService


NOW = datetime(2026, 7, 15, 8, 0, 0)
COMMAND = "pytest -q tests/test_learning_loop.py"


async def _project(session):
    workspace = Workspace(id=uuid4(), name=f"Learning {uuid4()}", slug=f"learning-{uuid4()}")
    model = Model(id=uuid4(), name=f"Task {uuid4()}")
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="local",
        external_id=f"task-{uuid4()}",
        content="Task: make agent verification durable.",
        metadata_json="{}",
    )
    session.add_all([workspace, model, source])
    await session.flush()
    focus = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.id,
        name="Durable agent verification",
        value="Make agent verification durable",
        fact_type="task",
        status="active",
    )
    session.add(focus)
    await session.flush()
    return workspace, focus, source


async def _pack_and_run(session, workspace, focus, source, *, run_key, minute=0):
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        objective="Make agent verification durable",
        objective_origin="source_component",
        objective_source_document_id=source.id,
        markdown="# Task",
        manifest=json.dumps({
            "schema_version": "context_pack.v2",
            "selected_context": [{"id": "component:focus", "mandatory": True}],
            "verification": {"commands": [{
                "id": "V1", "command": COMMAND, "required": True,
            }]},
        }),
        repo_state_json=json.dumps({
            "repo_path": "/project/context-engine",
            "head_commit": "verified-head",
            "snapshot_fingerprint": "snapshot-1",
        }),
        created_at=NOW + timedelta(minutes=minute),
    )
    session.add(pack)
    await session.flush()
    session.add(ContextPackItem(
        context_pack_id=pack.id,
        manifest_item_id="component:focus",
        component_id=focus.id,
        source_document_id=source.id,
        inclusion_reason="explicit_focus_source_component",
    ))
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        run_key=run_key,
        objective=pack.objective,
        status="completed",
        head_commit="verified-head",
        started_at=NOW + timedelta(minutes=minute + 1),
        ended_at=NOW + timedelta(minutes=minute + 5),
    )
    session.add(run)
    await session.flush()
    return pack, run


async def _observation(session, workspace_id, run, event_type, payload, minute):
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace_id,
        source_type="agent_run_observation",
        external_id=f"agent:{run.id}:{event_type}:{minute}",
        content=json.dumps(payload, sort_keys=True),
        metadata_json="{}",
    )
    session.add(source)
    await session.flush()
    observation = RunObservation(
        id=uuid4(),
        agent_run_id=run.id,
        source_document_id=source.id,
        event_type=event_type,
        event_key=f"{event_type}-{minute}",
        payload_json=json.dumps(payload, sort_keys=True),
        observed_at=NOW + timedelta(minutes=minute),
        content=payload.get("summary") or payload.get("content"),
        command=payload.get("command"),
        exit_code=payload.get("exit_code"),
    )
    session.add(observation)
    await session.flush()
    return observation


async def test_open_loops_are_idempotent_assignable_and_auto_resolved(db_session):
    workspace, focus, source = await _project(db_session)
    _, run = await _pack_and_run(db_session, workspace, focus, source, run_key="failed")
    await _observation(db_session, workspace.id, run, "patch_summary", {
        "summary": "Implemented durable verification.",
        "addresses_context_item_ids": ["component:focus"],
    }, 2)
    await _observation(db_session, workspace.id, run, "verification", {
        "command": COMMAND,
        "exit_code": 1,
    }, 3)
    await _observation(db_session, workspace.id, run, "outcome", {
        "status": "completed",
        "summary": "Claimed complete.",
        "completed_context_item_ids": ["component:focus"],
    }, 4)
    timeline = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
    )
    service = OpenLoopService(db_session)
    first = await service.reconcile_timeline(workspace_id=workspace.id, timeline=timeline)
    second = await service.reconcile_timeline(workspace_id=workspace.id, timeline=timeline)

    assert len(first) == len(second) == 2  # failed verification + conflicting completion
    assert len(list(await db_session.scalars(
        select(OpenLoop).where(OpenLoop.workspace_id == workspace.id)
    ))) == 2
    loop = next(item for item in first if item.rule_id == "verification.failed.v1")
    assigned = await service.apply_action(
        workspace_id=workspace.id,
        loop_id=loop.id,
        action="assign",
        reason="Darshan owns the failing check.",
        assignee="darshan",
    )
    assert assigned.assigned_to == "darshan"
    assert assigned.resolution_source_document_id is not None

    await _observation(db_session, workspace.id, run, "verification", {
        "command": COMMAND,
        "exit_code": 0,
    }, 5)
    calm = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
    )
    assert calm["findings"] == []
    await service.reconcile_timeline(workspace_id=workspace.id, timeline=calm)
    await db_session.refresh(loop)
    assert loop.status == "resolved"
    assert loop.resolution_reason == "Resolved by later structured run evidence."


async def test_playbook_requires_verified_run_and_second_run_approves(db_session):
    workspace, focus, source = await _project(db_session)
    _, first_run = await _pack_and_run(db_session, workspace, focus, source, run_key="one")
    await _observation(db_session, workspace.id, first_run, "patch_summary", {
        "summary": "Add the durable event, then reconcile project attention.",
    }, 2)
    await _observation(db_session, workspace.id, first_run, "verification", {
        "command": COMMAND,
        "exit_code": 0,
    }, 3)
    await _observation(db_session, workspace.id, first_run, "outcome", {
        "status": "completed",
        "summary": "Verified implementation.",
    }, 4)
    service = PlaybookService(db_session)
    candidate = await service.extract_from_run(first_run.id)
    duplicate = await service.extract_from_run(first_run.id)
    assert candidate is not None
    assert duplicate.id == candidate.id
    assert candidate.status == "pending_review"
    assert candidate.successful_run_count == 1

    _, second_run = await _pack_and_run(
        db_session, workspace, focus, source, run_key="two", minute=10
    )
    await _observation(db_session, workspace.id, second_run, "decision", {
        "decision": "Reuse the source-first reconciliation order.",
        "content": "Reuse the source-first reconciliation order.",
    }, 12)
    await _observation(db_session, workspace.id, second_run, "verification", {
        "command": COMMAND,
        "exit_code": 0,
    }, 13)
    await _observation(db_session, workspace.id, second_run, "outcome", {
        "status": "completed",
        "summary": "Verified again.",
    }, 14)
    approved = await service.extract_from_run(second_run.id)
    assert approved is not None
    assert approved.id == candidate.id
    assert approved.status == "approved"
    assert approved.successful_run_count == 2

    compatible = await service.compatible_playbook(
        workspace_id=workspace.id,
        objective="Make agent verification durable",
        repo_state={"repo_path": "/project/context-engine", "head_commit": "verified-head"},
    )
    assert compatible is not None
    assert compatible["compatible"] is True
    assert compatible["verification_commands"] == [COMMAND]


async def test_unverified_run_never_creates_playbook(db_session):
    workspace, focus, source = await _project(db_session)
    _, run = await _pack_and_run(db_session, workspace, focus, source, run_key="unverified")
    await _observation(db_session, workspace.id, run, "patch_summary", {
        "summary": "A patch exists but verification failed.",
    }, 2)
    await _observation(db_session, workspace.id, run, "verification", {
        "command": COMMAND,
        "exit_code": 1,
    }, 3)
    await _observation(db_session, workspace.id, run, "outcome", {
        "status": "completed",
        "summary": "Incorrect completion claim.",
    }, 4)

    assert await PlaybookService(db_session).extract_from_run(run.id) is None
    assert await db_session.scalar(select(VerifiedPlaybook.id)) is None


async def test_open_loop_and_playbook_actions_are_available_in_context_api(
    db_session, client
):
    workspace, focus, source = await _project(db_session)
    _, run = await _pack_and_run(db_session, workspace, focus, source, run_key="api")
    await _observation(db_session, workspace.id, run, "patch_summary", {
        "summary": "Implemented the verified workflow.",
    }, 2)
    await _observation(db_session, workspace.id, run, "verification", {
        "command": COMMAND,
        "exit_code": 0,
    }, 3)
    await _observation(db_session, workspace.id, run, "outcome", {
        "status": "completed", "summary": "Verified workflow complete.",
    }, 4)
    playbook = await PlaybookService(db_session).extract_from_run(run.id)
    assert playbook is not None
    loop = OpenLoop(
        workspace_id=workspace.id,
        natural_key=f"api-{uuid4().hex}",
        rule_id="verification.failed.v1",
        severity="warning",
        title="Required check needs an owner.",
        explanation="A required check is still unresolved.",
        focus_component_id=focus.id,
        context_pack_id=run.context_pack_id,
        run_id=run.id,
        sources_json=json.dumps([{"source_document_id": str(source.id)}]),
    )
    db_session.add(loop)
    await db_session.flush()

    loops = await client.get(f"/api/context/open-loops?workspace_id={workspace.id}")
    assert loops.status_code == 200
    assert loops.json()["open_count"] == 1
    assignment = await client.patch(f"/api/context/open-loops/{loop.id}", json={
        "workspace_id": str(workspace.id),
        "action": "assign",
        "reason": "Darshan owns the required check.",
        "assignee": "darshan",
    })
    assert assignment.status_code == 200
    assert assignment.json()["assigned_to"] == "darshan"

    response = await client.get(f"/api/context/playbooks?workspace_id={workspace.id}")
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "pending_review"
    review = await client.patch(f"/api/context/playbooks/{playbook.id}", json={
        "workspace_id": str(workspace.id),
        "action": "approve",
        "reason": "The steps match the accepted implementation.",
    })
    assert review.status_code == 200
    assert review.json()["status"] == "approved"
