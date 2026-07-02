from __future__ import annotations

import json
from uuid import UUID
from uuid import uuid4

import pytest

from app.models import SourceDocument, Workspace


@pytest.mark.asyncio
async def test_bulk_source_create_sync_processes_documents_before_return(client, db_session):
    response = await client.post(
        "/api/sources/bulk?sync=true",
        json={
            "documents": [
                {
                    "source_type": "local",
                    "external_id": "cli-sync-1.md",
                    "content": "Decision: keep CLI sync source-backed.",
                    "metadata": {"file_name": "cli-sync-1.md"},
                },
                {
                    "source_type": "local",
                    "external_id": "cli-sync-2.md",
                    "content": "Task: document the synchronous ingest path.",
                    "metadata": {"file_name": "cli-sync-2.md"},
                },
            ]
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 2

    for raw_id in data["document_ids"]:
        doc = await db_session.get(SourceDocument, UUID(raw_id))
        assert doc is not None
        assert doc.processed_at is not None


@pytest.mark.asyncio
async def test_list_sources_filters_by_workspace_id(client, db_session):
    ws_a = Workspace(id=uuid4(), name="Workspace A", slug=f"source-a-{uuid4().hex}")
    ws_b = Workspace(id=uuid4(), name="Workspace B", slug=f"source-b-{uuid4().hex}")
    doc_a = SourceDocument(
        id=uuid4(),
        workspace_id=ws_a.id,
        source_type="local",
        external_id="workspace-a.md",
        content="Decision: workspace A only.",
        metadata_json=json.dumps({"workspace_id": str(ws_a.id)}),
    )
    doc_b = SourceDocument(
        id=uuid4(),
        workspace_id=ws_b.id,
        source_type="local",
        external_id="workspace-b.md",
        content="Decision: workspace B only.",
        metadata_json=json.dumps({"workspace_id": str(ws_b.id)}),
    )
    db_session.add_all([ws_a, ws_b, doc_a, doc_b])
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/sources", params={"workspace_id": str(ws_a.id)})

    assert response.status_code == 200
    external_ids = {item["external_id"] for item in response.json()}
    assert "workspace-a.md" in external_ids
    assert "workspace-b.md" not in external_ids


@pytest.mark.asyncio
async def test_get_source_hides_other_workspace_when_workspace_id_is_supplied(client, db_session):
    ws_a = Workspace(id=uuid4(), name="Detail A", slug=f"detail-a-{uuid4().hex}")
    ws_b = Workspace(id=uuid4(), name="Detail B", slug=f"detail-b-{uuid4().hex}")
    doc_b = SourceDocument(
        id=uuid4(),
        workspace_id=ws_b.id,
        source_type="local",
        external_id="detail-b.md",
        content="Decision: keep detail scoped.",
        metadata_json=json.dumps({"workspace_id": str(ws_b.id)}),
    )
    db_session.add_all([ws_a, ws_b, doc_b])
    await db_session.flush()
    await db_session.commit()

    hidden = await client.get(f"/api/sources/{doc_b.id}", params={"workspace_id": str(ws_a.id)})
    visible = await client.get(f"/api/sources/{doc_b.id}", params={"workspace_id": str(ws_b.id)})

    assert hidden.status_code == 404
    assert visible.status_code == 200
    assert visible.json()["workspace_id"] == str(ws_b.id)
