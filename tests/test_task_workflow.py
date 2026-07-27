from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest

from app.models import (
    Component,
    Model,
    Relationship,
    SessionEvent,
    SourceDocument,
    Workspace,
    WorkspaceGoal,
)
from app.services.access import AccessScope
from app.services.checkpoints import capture_checkpoint
from app.services.continuation import (
    ContinuationService,
    _checkpoint_blocking_issues,
)
from app.services.task_workflow import (
    TaskWorkflowService,
    complete_verified_execution_task,
)
from app.time import utc_now


async def test_five_feature_workflow_executes_shared_prerequisite_then_selected_task(
    db_session,
) -> None:
    workspace, features = await _seed_features(
        db_session,
        statuses={
            1: "paused",
            2: "dropped",
            3: "active",
            4: "active",
            5: "active",
        },
    )
    decision_content = "Decision: keep the existing harness protocol."
    decision_source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="local",
        external_id=f"decision:{uuid4().hex}",
        content=decision_content,
        content_sha256=hashlib.sha256(
            decision_content.encode("utf-8")
        ).hexdigest(),
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    unrelated_decision = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=features[4].model_id,
        source_document_id=decision_source.id,
        name="Harness protocol",
        value="Keep the existing harness protocol.",
        fact_type="decision",
        temporal="current",
        status="active",
    )
    db_session.add_all([decision_source, unrelated_decision])
    await db_session.flush()
    db_session.add_all([
        Relationship(
            source_component_id=features[4].id,
            target_component_id=features[3].id,
            relationship_type="depends_on",
            status="active",
            origin="human_verified",
            evidence="Feature 4 requires Feature 3.",
        ),
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[5].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
            evidence="Feature 3 blocks Feature 5.",
        ),
        # Proposed graph noise must not make an unrelated paused item block work.
        Relationship(
            source_component_id=features[1].id,
            target_component_id=features[4].id,
            relationship_type="blocks",
            status="active",
            origin="proposed",
            evidence="Untrusted inferred relationship.",
        ),
        # A trusted relationship to a non-task record is context, not an
        # executable task dependency.
        Relationship(
            source_component_id=unrelated_decision.id,
            target_component_id=features[4].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
            evidence="The decision is relevant but is not an executable task.",
        ),
    ])
    await db_session.flush()

    service = TaskWorkflowService(db_session)
    feature_four = await service.resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )
    feature_five = await service.resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 5",
    )
    component_selected_goal = await service.resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Ship the user-selected workflow.",
        selected_component_id=features[4].id,
    )

    for resolution in (
        feature_four,
        feature_five,
        component_selected_goal,
    ):
        workflow = resolution.workflow
        assert resolution.execution_component_id == features[3].id
        assert workflow["execution_reason"] == "unfinished_prerequisite"
        assert [item["title"] for item in workflow["now"]] == ["Feature 3"]
        assert {item["title"] for item in workflow["blocked"]} == {
            "Feature 4",
            "Feature 5",
        }
        assert {item["title"] for item in workflow["paused"]} >= {
            "Feature 1",
            "Feature 2",
        }
        assert {item["title"] for item in workflow["affected_tasks"]} >= {
            "Feature 4",
            "Feature 5",
        }
        assert workflow["blocking_issues"] == []
        assert workflow["relationship_count"] == 2

    features[3].status = "completed"
    await db_session.flush()

    after_prerequisite = await service.resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )

    assert after_prerequisite.execution_component_id == features[4].id
    assert after_prerequisite.workflow["execution_reason"] == "selected_task"
    assert [
        item["title"] for item in after_prerequisite.workflow["now"]
    ] == ["Feature 4"]
    assert [
        item["title"] for item in after_prerequisite.workflow["next"]
    ] == ["Feature 5"]
    assert after_prerequisite.workflow["blocked"] == []


@pytest.mark.parametrize(
    "prerequisite_status",
    ["paused", "dropped", "cancelled"],
)
async def test_non_actionable_prerequisite_blocks_with_exact_affected_tasks(
    db_session,
    prerequisite_status,
) -> None:
    workspace, features = await _seed_features(
        db_session,
        statuses={3: prerequisite_status, 4: "active", 5: "active"},
    )
    db_session.add_all([
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[4].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
        ),
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[5].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
        ),
    ])
    await db_session.flush()

    result = await TaskWorkflowService(db_session).resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )

    assert result.execution_component_id is None
    assert result.workflow["now"] == []
    issue = result.blocking_issues[0]
    assert issue["code"] == "dependency_prerequisite_not_actionable"
    assert issue["blocker"]["title"] == "Feature 3"
    assert f'"Feature 3" is {prerequisite_status}' in issue["message"]
    assert {item["title"] for item in result.workflow["affected_tasks"]} >= {
        "Feature 4",
        "Feature 5",
    }
    assert {item["title"] for item in issue["affected_tasks"]} == {
        "Feature 4",
        "Feature 5",
    }


async def test_dependency_cycle_and_ambiguous_prerequisites_fail_closed(
    db_session,
) -> None:
    cycle_workspace, cycle_features = await _seed_features(
        db_session,
        statuses={3: "active", 4: "active"},
    )
    db_session.add_all([
        Relationship(
            source_component_id=cycle_features[3].id,
            target_component_id=cycle_features[4].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
        ),
        Relationship(
            source_component_id=cycle_features[4].id,
            target_component_id=cycle_features[3].id,
            relationship_type="blocks",
            status="active",
            origin="human_verified",
        ),
    ])
    await db_session.flush()

    cycle = await TaskWorkflowService(db_session).resolve(
        workspace_id=cycle_workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )

    assert cycle.execution_component_id is None
    assert cycle.blocking_issues[0]["code"] == "dependency_cycle"
    assert "Feature 4" in cycle.blocking_issues[0]["message"]
    assert "Feature 3" in cycle.blocking_issues[0]["message"]

    ambiguous_workspace, ambiguous_features = await _seed_features(
        db_session,
        statuses={2: "active", 3: "active", 4: "active"},
    )
    db_session.add_all([
        Relationship(
            source_component_id=ambiguous_features[4].id,
            target_component_id=ambiguous_features[2].id,
            relationship_type="blocked_by",
            status="active",
            origin="deterministic",
        ),
        Relationship(
            source_component_id=ambiguous_features[4].id,
            target_component_id=ambiguous_features[3].id,
            relationship_type="depends_on",
            status="active",
            origin="human_verified",
        ),
    ])
    await db_session.flush()

    ambiguous = await TaskWorkflowService(db_session).resolve(
        workspace_id=ambiguous_workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )

    assert ambiguous.execution_component_id is None
    issue = ambiguous.blocking_issues[0]
    assert issue["code"] == "dependency_execution_ambiguous"
    assert {item["title"] for item in issue["blocking_tasks"]} == {
        "Feature 2",
        "Feature 3",
    }


async def test_continuation_pack_preserves_intent_and_executes_prerequisite(
    db_session,
    tmp_path,
) -> None:
    (tmp_path / "app.py").write_text(
        "def continue_feature():\n    return True\n",
        encoding="utf-8",
    )
    workspace, features = await _seed_features(
        db_session,
        statuses={3: "active", 4: "active", 5: "active"},
    )
    db_session.add_all([
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[4].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
        ),
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[5].id,
            relationship_type="blocks",
            status="active",
            origin="human_verified",
        ),
    ])
    # An unrelated persisted current goal must not override an explicit
    # continuation objective.
    db_session.add(WorkspaceGoal(
        workspace_id=workspace.id,
        title="Feature 5",
        component_id=features[5].id,
        status="active",
        source_kind="user_selected",
        selected_by="local_user",
    ))
    await db_session.flush()

    result = await ContinuationService(db_session).prepare(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        repo_path=str(tmp_path),
        objective="Feature 4",
        token_budget=3_000,
    )

    assert result.objective == features[3].value
    assert result.task["selected_intent"]["title"] == "Feature 4"
    assert result.task["execution_task"]["title"] == "Feature 3"
    workflow = result.manifest["continuation"]["workflow"]
    assert workflow["selected_intent"]["title"] == "Feature 4"
    assert workflow["execution_task"]["title"] == "Feature 3"
    assert "Desired outcome: Feature 4" in result.markdown
    assert "Immediate execution target: Implement Feature 3." in result.markdown
    assert result.readiness["blocking_issues"] == []


async def test_verified_execution_advances_prerequisite_and_unlocks_dependents(
    db_session,
) -> None:
    workspace, features = await _seed_features(
        db_session,
        statuses={3: "active", 4: "active", 5: "active"},
    )
    db_session.add_all([
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[4].id,
            relationship_type="blocks",
            status="active",
            origin="deterministic",
        ),
        Relationship(
            source_component_id=features[3].id,
            target_component_id=features[5].id,
            relationship_type="blocks",
            status="active",
            origin="human_verified",
        ),
    ])
    await db_session.flush()
    before = await TaskWorkflowService(db_session).resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )

    transition = await complete_verified_execution_task(
        db_session,
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        workflow=before.workflow,
    )
    after = await TaskWorkflowService(db_session).resolve(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        selected_objective="Feature 4",
    )

    assert transition == {
        "status": "completed",
        "component_id": str(features[3].id),
        "title": "Feature 3",
        "previous_status": "active",
        "new_status": "completed",
    }
    assert features[3].status == "completed"
    assert after.execution_component_id == features[4].id
    assert [item["title"] for item in after.workflow["now"]] == ["Feature 4"]
    assert [item["title"] for item in after.workflow["next"]] == ["Feature 5"]


async def test_continuation_uses_the_prerequisite_session_and_checkpoint(
    db_session,
    tmp_path,
) -> None:
    (tmp_path / "app.py").write_text(
        "def dependency_order():\n    return True\n",
        encoding="utf-8",
    )
    workspace, features = await _seed_features(
        db_session,
        statuses={3: "active", 4: "active"},
    )
    db_session.add(Relationship(
        source_component_id=features[3].id,
        target_component_id=features[4].id,
        relationship_type="blocks",
        status="active",
        origin="human_verified",
    ))
    now = utc_now()
    await _seed_task_session(
        db_session,
        workspace=workspace,
        repo_path=str(tmp_path),
        objective=features[3].value,
        session_id="feature-3-session",
        occurred_at=now - timedelta(minutes=5),
    )
    await _seed_task_session(
        db_session,
        workspace=workspace,
        repo_path=str(tmp_path),
        objective=features[4].value,
        session_id="feature-4-session",
        occurred_at=now,
    )

    result = await ContinuationService(db_session).prepare(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        repo_path=str(tmp_path),
        objective=features[4].value,
        token_budget=3_000,
    )

    assert result.objective == features[3].value
    assert result.source_session is not None
    assert result.source_session["session_id"] == "feature-3-session"
    assert result.checkpoint is not None
    assert result.checkpoint["goal"] == features[3].value
    assert result.manifest["continuation"]["workflow"][
        "selected_intent"
    ]["title"] == "Feature 4"
    assert "feature-4-session" not in result.markdown


async def test_reported_claude_auth_blocker_does_not_globally_block_continuation(
    db_session,
    tmp_path,
) -> None:
    (tmp_path / "app.py").write_text(
        "def authenticate():\n    return True\n",
        encoding="utf-8",
    )
    workspace = Workspace(
        id=uuid4(),
        name="Checkpoint blocker",
        slug=f"checkpoint-blocker-{uuid4().hex}",
    )
    goal = "Validate the Claude continuation adapter."
    blocker = (
        "Claude authentication failed — its OAuth token has been revoked (401)."
    )
    source_content = f"[USER]\n{goal}\n[ASSISTANT]\nBlocker: {blocker}"
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{uuid4().hex}",
        content=source_content,
        content_sha256=hashlib.sha256(
            source_content.encode("utf-8")
        ).hexdigest(),
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "provider": "codex",
            "session_id": "checkpoint-blocker",
            "cwd": str(tmp_path),
        }),
    )
    db_session.add_all([workspace, source])
    await db_session.flush()
    occurred_at = utc_now()
    events = [
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace.id,
            source_document_id=source.id,
            provider="codex",
            session_id="checkpoint-blocker",
            provider_event_id="request-1",
            sequence_number=1,
            event_type="user_request",
            role="user",
            occurred_at=occurred_at,
            content=goal,
            payload_json="{}",
            content_sha256=hashlib.sha256(goal.encode("utf-8")).hexdigest(),
        ),
        SessionEvent(
            id=uuid4(),
            workspace_id=workspace.id,
            source_document_id=source.id,
            provider="codex",
            session_id="checkpoint-blocker",
            provider_event_id="update-2",
            sequence_number=2,
            event_type="assistant_update",
            role="assistant",
            occurred_at=occurred_at,
            content=f"Blocker: {blocker}",
            payload_json="{}",
            content_sha256=hashlib.sha256(
                f"Blocker: {blocker}".encode("utf-8")
            ).hexdigest(),
        ),
    ]
    db_session.add_all(events)
    await db_session.flush()
    checkpoint = await capture_checkpoint(
        db_session,
        workspace_id=workspace.id,
        provider="codex",
        session_id="checkpoint-blocker",
        boundary_event_id=events[-1].id,
    )
    checkpoint.repo_root = str(tmp_path)
    await db_session.flush()

    result = await ContinuationService(db_session).prepare(
        workspace_id=workspace.id,
        access_scope=AccessScope.local(),
        repo_path=str(tmp_path),
        objective=goal,
        checkpoint_id=checkpoint.id,
        token_budget=3_000,
    )

    assert result.readiness["status"] != "blocked"
    issue = result.readiness["blocking_issues"][0]
    assert issue["code"] == "checkpoint_provider_auth_reported"
    assert issue["message"] == f"Blocker: {blocker}"
    assert issue["blocks_current_execution"] is False
    assert issue["applicability"] == {
        "kind": "provider",
        "providers": ["claude"],
        "authority": "live_provider_readiness",
    }
    assert issue["affected_tasks"][0]["objective"] == goal
    assert result.checkpoint is not None
    assert result.checkpoint["continuation_status"] == "review_required"
    assert result.checkpoint["reported_continuation_status"] == "blocked"
    assert result.checkpoint["sections"]["blockers"][0]["statement"] == (
        f"Blocker: {blocker}"
    )


def test_checkpoint_blocker_statement_is_structured_with_workflow_impact() -> None:
    workflow = {
        "selected_intent": {
            "id": "feature-4",
            "title": "Feature 4",
        },
        "execution_task": {
            "id": "feature-3",
            "title": "Feature 3",
        },
        "affected_tasks": [{
            "id": "feature-5",
            "title": "Feature 5",
        }],
    }
    checkpoint = {
        "id": "checkpoint-1",
        "sections": {
            "blockers": [{
                "id": "blocker-1",
                "statement": (
                    "Claude authentication failed — its OAuth token has been "
                    "revoked (401)."
                ),
                "state": "active",
                "truth_state": "reported",
            }],
        },
    }

    issues = _checkpoint_blocking_issues(checkpoint, workflow=workflow)

    assert issues[0]["message"] == (
        "Claude authentication failed — its OAuth token has been revoked (401)."
    )
    assert issues[0]["blocker"]["checkpoint_id"] == "checkpoint-1"
    assert issues[0]["blocks_current_execution"] is False
    assert [item["title"] for item in issues[0]["affected_tasks"]] == [
        "Feature 3",
        "Feature 4",
        "Feature 5",
    ]

    task_blocker = {
        **checkpoint,
        "sections": {
            "blockers": [{
                "id": "blocker-2",
                "statement": "The database migration plan still requires approval.",
                "state": "active",
                "truth_state": "reported",
            }],
        },
    }
    task_issues = _checkpoint_blocking_issues(
        task_blocker,
        workflow=workflow,
    )
    assert task_issues[0]["code"] == "checkpoint_blocker"
    assert task_issues[0]["blocks_current_execution"] is False

    observed_hard_blocker = {
        **checkpoint,
        "sections": {
            "blockers": [{
                "id": "blocker-3",
                "statement": "The repository cannot be accessed safely.",
                "state": "active",
                "truth_state": "observed",
                "payload": {"blocks_current_execution": True},
            }],
        },
    }
    hard_issues = _checkpoint_blocking_issues(
        observed_hard_blocker,
        workflow=workflow,
    )
    assert hard_issues[0]["blocks_current_execution"] is True


async def _seed_features(
    db_session,
    *,
    statuses: dict[int, str],
) -> tuple[Workspace, dict[int, Component]]:
    workspace = Workspace(
        id=uuid4(),
        name="Task workflow",
        slug=f"task-workflow-{uuid4().hex}",
    )
    model = Model(
        id=uuid4(),
        name=f"Features {uuid4().hex}",
    )
    db_session.add_all([workspace, model])
    await db_session.flush()

    features: dict[int, Component] = {}
    for number, status in statuses.items():
        content = f"Feature {number}: Implement Feature {number}."
        source = SourceDocument(
            id=uuid4(),
            workspace_id=workspace.id,
            source_type="local",
            external_id=f"feature:{number}:{uuid4().hex}",
            content=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
        )
        component = Component(
            id=uuid4(),
            workspace_id=workspace.id,
            model_id=model.id,
            source_document_id=source.id,
            name=f"Feature {number}",
            value=f"Implement Feature {number}.",
            fact_type="feature",
            temporal="current",
            confidence=0.95,
            authority_weight=0.9,
            status=status,
        )
        db_session.add_all([source, component])
        features[number] = component
    await db_session.flush()
    return workspace, features


async def _seed_task_session(
    db_session,
    *,
    workspace: Workspace,
    repo_path: str,
    objective: str,
    session_id: str,
    occurred_at,
) -> None:
    content = (
        f"[USER]\n{objective}\n"
        "[ASSISTANT]\nI inspected the task and preserved its current state."
    )
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"codex:session:{session_id}",
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "provider": "codex",
            "session_id": session_id,
            "cwd": repo_path,
        }),
    )
    db_session.add(source)
    await db_session.flush()
    updates = [
        (
            "request",
            1,
            "user_request",
            "user",
            objective,
        ),
        (
            "update",
            2,
            "assistant_update",
            "assistant",
            "I inspected the task and preserved its current state.",
        ),
    ]
    for suffix, sequence, event_type, role, event_content in updates:
        db_session.add(SessionEvent(
            id=uuid4(),
            workspace_id=workspace.id,
            source_document_id=source.id,
            provider="codex",
            session_id=session_id,
            provider_event_id=f"{session_id}:{suffix}",
            sequence_number=sequence,
            event_type=event_type,
            role=role,
            occurred_at=occurred_at,
            content=event_content,
            payload_json="{}",
            content_sha256=hashlib.sha256(
                event_content.encode("utf-8")
            ).hexdigest(),
        ))
    await db_session.flush()
