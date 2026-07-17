from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import AgentRun, Workspace


async def test_workspace_list_is_read_only_and_create_derives_unique_slugs(client, db_session):
    existing_ids = set(await db_session.scalars(select(Workspace.id)))
    before = await client.get("/api/workspaces")
    assert before.status_code == 200
    assert set(await db_session.scalars(select(Workspace.id))) == existing_ids

    first = await client.post("/api/workspaces", json={"name": "Real Project"})
    second = await client.post("/api/workspaces", json={"name": "Real Project"})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["slug"] == "real-project"
    assert second.json()["slug"] == "real-project-2"
    assert first.json()["kind"] == "project"
    assert first.json()["status"] == "active"


async def test_workspace_rename_archive_restore_and_list_filter(client):
    created = await client.post("/api/workspaces", json={"name": "Lifecycle Project"})
    workspace_id = created.json()["id"]

    renamed = await client.patch(
        f"/api/workspaces/{workspace_id}", json={"name": "Renamed Project"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Project"
    assert renamed.json()["slug"] == "lifecycle-project"

    archived = await client.patch(
        f"/api/workspaces/{workspace_id}", json={"status": "archived"}
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"]
    active = await client.get("/api/workspaces")
    all_workspaces = await client.get("/api/workspaces", params={"include_archived": True})
    assert all(item["id"] != workspace_id for item in active.json())
    assert any(item["id"] == workspace_id for item in all_workspaces.json())

    restored = await client.patch(
        f"/api/workspaces/{workspace_id}", json={"status": "active"}
    )
    assert restored.json()["status"] == "active"
    assert restored.json()["archived_at"] is None


async def test_permanent_delete_requires_archive_confirmation_and_removes_graph(client):
    created = await client.post("/api/workspaces", json={"name": "Disposable Demo"})
    workspace_id = created.json()["id"]
    kept = await client.post("/api/workspaces", json={"name": "Keep Me"})

    seeded = await client.post("/api/seed-demo", json={"workspace_id": workspace_id})
    assert seeded.status_code == 200

    not_archived = await client.delete(
        f"/api/workspaces/{workspace_id}", params={"confirm_name": "Disposable Demo"}
    )
    assert not_archived.status_code == 409

    await client.patch(f"/api/workspaces/{workspace_id}", json={"status": "archived"})
    wrong_name = await client.delete(
        f"/api/workspaces/{workspace_id}", params={"confirm_name": "wrong"}
    )
    assert wrong_name.status_code == 422

    deleted = await client.delete(
        f"/api/workspaces/{workspace_id}", params={"confirm_name": "Disposable Demo"}
    )
    assert deleted.status_code == 204
    remaining = await client.get("/api/workspaces", params={"include_archived": True})
    assert all(item["id"] != workspace_id for item in remaining.json())
    assert any(item["id"] == kept.json()["id"] for item in remaining.json())


async def test_delete_refuses_workspace_with_active_run(client, db_session):
    created = await client.post("/api/workspaces", json={"name": "Running Project"})
    workspace_id = created.json()["id"]
    db_session.add(AgentRun(
        id=uuid4(),
        workspace_id=UUID(workspace_id),
        objective="Finish the active change",
        status="running",
    ))
    await db_session.flush()
    archive = await client.patch(
        f"/api/workspaces/{workspace_id}", json={"status": "archived"}
    )
    assert archive.status_code == 409
    assert "active agent run" in archive.json()["detail"].lower()

    run = await db_session.scalar(
        select(AgentRun).where(AgentRun.workspace_id == UUID(workspace_id))
    )
    run.status = "succeeded"
    await db_session.flush()
    await client.patch(f"/api/workspaces/{workspace_id}", json={"status": "archived"})
    run.status = "running"
    await db_session.flush()

    response = await client.delete(
        f"/api/workspaces/{workspace_id}", params={"confirm_name": "Running Project"}
    )
    assert response.status_code == 409
    assert "active agent run" in response.json()["detail"].lower()
