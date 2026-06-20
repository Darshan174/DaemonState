from __future__ import annotations

from uuid import UUID

import pytest

from app.models import SourceDocument


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
