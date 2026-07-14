from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select

from app.models import Component, Connector, Relationship, SourceDocument


async def test_seed_demo_creates_source_backed_workspace(client, db_session):
    response = await client.post("/api/seed-demo", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert data["workspaceId"]
    assert data["createdDocuments"] == 6
    assert data["processedDocuments"] == 6
    assert data["componentsCreated"] > 0
    assert set(data["sourceTypes"]) == {
        "ai_context_codex",
        "github_issue",
        "github_pr",
        "gmail",
        "gdrive",
        "slack",
    }
    assert "notion" not in data["message"].lower()
    assert "zoom" not in data["message"].lower()
    assert data["projectBoundaryCreated"] is True

    docs = list(await db_session.scalars(
        select(SourceDocument).where(SourceDocument.external_id.like("demo:%"))
    ))
    assert len(docs) == 6
    for doc in docs:
        metadata = json.loads(doc.metadata_json)
        assert metadata["demo_seed"] is True
        assert metadata["workspace_id"] == data["workspaceId"]
        assert doc.processed_at is not None

    components = list(await db_session.scalars(select(Component)))
    assert components
    assert all(component.provenance for component in components)

    relationships = list(await db_session.scalars(select(Relationship)))
    assert relationships
    assert all(rel.evidence for rel in relationships)
    assert any(
        rel.relationship_type in {"fixes", "solves"} and rel.origin == "deterministic"
        for rel in relationships
    )

    connector = await db_session.scalar(select(Connector).where(
        Connector.workspace_id == UUID(data["workspaceId"]),
        Connector.connector_type == "github",
    ))
    assert connector is not None
    assert connector.status == "disconnected"
    assert connector.credentials_json == "{}"
    assert json.loads(connector.config_json)["repositories"] == ["your-org/context-engine"]

    digest = await client.get(
        "/api/context/digest", params={"workspace_id": data["workspaceId"]}
    )
    assert digest.status_code == 200
    digest_data = digest.json()
    assert digest_data["scope"]["project_repositories"] == ["your-org/context-engine"]
    assert digest_data["cards"]


async def test_seed_demo_is_idempotent_for_workspace(client, db_session):
    first_response = await client.post("/api/seed-demo", json={})
    workspace_id = first_response.json()["workspaceId"]

    second_response = await client.post("/api/seed-demo", json={"workspace_id": workspace_id})

    assert second_response.status_code == 200
    data = second_response.json()
    assert data["status"] == "ready"
    assert data["workspaceId"] == workspace_id
    assert data["createdDocuments"] == 0
    assert data["existingDocuments"] == 6
    assert data["processedDocuments"] == 0
    assert data["componentsCreated"] == 0
    assert data["projectBoundaryCreated"] is False

    docs = list(await db_session.scalars(
        select(SourceDocument).where(SourceDocument.external_id.like("demo:%"))
    ))
    assert len(docs) == 6
    demo_connectors = list(await db_session.scalars(select(Connector).where(
        Connector.workspace_id == UUID(workspace_id),
        Connector.connector_type == "github",
    )))
    assert len(demo_connectors) == 1
