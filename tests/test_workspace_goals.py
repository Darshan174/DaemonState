import json
from uuid import uuid4

from sqlalchemy import select

from app.models import (
    AgentRun,
    Component,
    ContextPack,
    Model,
    SourceDocument,
    Workspace,
    WorkspaceGoal,
)


async def _project(db_session):
    workspace = Workspace(id=uuid4(), name="Goal project", slug=f"goal-{uuid4().hex}")
    model = Model(id=uuid4(), name=f"Tasks {uuid4().hex}")
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="github_issue",
        external_id="issue-12",
        source_url="https://github.example/acme/project/issues/12",
        content="Issue #12: Fix workspace onboarding.",
        metadata_json=json.dumps({
            "item_type": "issue",
            "repo_full_name": "acme/project",
            "number": 12,
            "state": "open",
        }),
    )
    task = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.id,
        name="Issue #12: Fix workspace onboarding",
        value="Make project selection explicit.",
        fact_type="issue",
        status="active",
        confidence=0.9,
    )
    db_session.add_all([workspace, model, source, task])
    await db_session.flush()
    return workspace, task


async def test_select_replace_and_clear_current_goal(client, db_session):
    workspace, task = await _project(db_session)

    selected = await client.put(
        f"/api/workspaces/{workspace.id}/current-goal",
        json={
            "title": task.name,
            "component_id": str(task.id),
            "source_kind": "suggested_card",
            "source_id": str(task.source_document_id),
        },
    )
    assert selected.status_code == 200
    assert selected.json()["component_id"] == str(task.id)
    assert selected.json()["selected_by"] == "local"

    digest = await client.get("/api/context/digest", params={"workspace_id": str(workspace.id)})
    assert digest.status_code == 200
    assert digest.json()["current_goal"]["title"] == task.name
    assert digest.json()["oversight"]["current_focus"]["component_id"] == str(task.id)

    replacement = await client.put(
        f"/api/workspaces/{workspace.id}/current-goal",
        json={"title": "Ship the repo-first onboarding"},
    )
    assert replacement.status_code == 200
    assert replacement.json()["component_id"] is None

    goals = list(await db_session.scalars(
        select(WorkspaceGoal)
        .where(WorkspaceGoal.workspace_id == workspace.id)
        .order_by(WorkspaceGoal.selected_at, WorkspaceGoal.id)
    ))
    assert [goal.status for goal in goals] == ["replaced", "active"]

    cleared = await client.delete(f"/api/workspaces/{workspace.id}/current-goal")
    assert cleared.status_code == 204
    digest = await client.get("/api/context/digest", params={"workspace_id": str(workspace.id)})
    assert digest.json()["current_goal"] is None
    assert digest.json()["oversight"]["current_focus"] is None


async def test_old_context_pack_is_not_inferred_as_current_goal(client, db_session):
    workspace, task = await _project(db_session)
    db_session.add(ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective=task.name,
        focus_component_id=task.id,
        objective_origin="source_component",
        markdown="# Old brief",
        manifest="{}",
    ))
    await db_session.flush()

    digest = await client.get("/api/context/digest", params={"workspace_id": str(workspace.id)})
    assert digest.status_code == 200
    assert digest.json()["objective"]["status"] == "supplied"
    assert digest.json()["current_goal"] is None
    assert digest.json()["oversight"]["current_focus"] is None


async def test_new_workspace_starts_without_another_workspaces_goal(client):
    first = await client.post("/api/workspaces", json={"name": "Configured Project"})
    first_id = first.json()["id"]
    selected = await client.put(
        f"/api/workspaces/{first_id}/current-goal",
        json={"title": "Keep this project's goal"},
    )
    assert selected.status_code == 200

    fresh = await client.post("/api/workspaces", json={"name": "Fresh Project"})
    fresh_id = fresh.json()["id"]
    fresh_digest = await client.get(
        "/api/context/digest", params={"workspace_id": fresh_id}
    )
    configured_digest = await client.get(
        "/api/context/digest", params={"workspace_id": first_id}
    )

    assert fresh_digest.status_code == 200
    assert fresh_digest.json()["current_goal"] is None
    assert configured_digest.json()["current_goal"]["title"] == (
        "Keep this project's goal"
    )


async def test_active_run_temporarily_overrides_selected_goal(client, db_session):
    workspace, task = await _project(db_session)
    response = await client.put(
        f"/api/workspaces/{workspace.id}/current-goal",
        json={"title": "Review the backlog"},
    )
    assert response.status_code == 200
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective=task.name,
        focus_component_id=task.id,
        objective_origin="trusted_human",
        markdown="# Active brief",
        manifest="{}",
    )
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        objective="Implement the active task",
        tool="codex",
        status="running",
    )
    db_session.add_all([pack, run])
    await db_session.flush()

    digest = await client.get("/api/context/digest", params={"workspace_id": str(workspace.id)})
    goal = digest.json()["current_goal"]
    assert goal["title"] == "Implement the active task"
    assert goal["source_kind"] == "active_agent_run"
    assert goal["can_clear"] is False


async def test_rejects_ineligible_goal_component(client, db_session):
    workspace, task = await _project(db_session)
    task.fact_type = "github_pr"
    await db_session.flush()

    response = await client.put(
        f"/api/workspaces/{workspace.id}/current-goal",
        json={"title": task.name, "component_id": str(task.id)},
    )
    assert response.status_code == 422
    assert "delivery evidence" in response.json()["detail"]


async def test_open_issue_is_backlog_not_attention(client, db_session):
    workspace, task = await _project(db_session)

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert response.status_code == 200
    data = response.json()
    card = next(item for item in data["cards"] if item["id"] == f"component:{task.id}")
    assert card["category"] == "issue"
    assert card["attention_required"] is False
    clusters = {cluster["id"]: cluster for cluster in data["clusters"]}
    assert card["id"] in clusters["backlog"]["card_ids"]
    assert card["id"] not in clusters["needs_attention"]["card_ids"]
