from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import connectors as connectors_api
from app.database import get_db_session
from app.main import app
from app.models.source import ConnectorType
from app.services.import_service import ImportWorkspaceNotFoundError


@pytest.fixture
async def connectors_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()


class FakeSession:
    def __init__(self, document=None):
        self.document = document

    async def get(self, model, document_id):
        return self.document


class TestSourceDocumentUploadAPI:
    async def test_upload_uses_import_service_contract(self, connectors_client, monkeypatch):
        expected_workspace_id = uuid4()
        connector_id = uuid4()
        document_id = uuid4()
        now = datetime.now(UTC)
        document = SimpleNamespace(
            id=document_id,
            connector_id=connector_id,
            connector_type=ConnectorType.LOCAL,
            external_id="browser-upload:pricing.md",
            content="Decision: enterprise stays at $600/seat.",
            author="Browser Upload",
            source_url=None,
            created_at_source=None,
            ingested_at=now,
            processed_at=now,
            deleted_at=None,
            metadata_json={
                "title": "pricing.md",
                "file_name": "pricing.md",
                "file_extension": ".md",
                "source_type": "browser_upload",
            },
        )
        session = FakeSession(document=document)

        class FakeImportService:
            def __init__(self, provided_session):
                assert provided_session is session

            async def import_documents(self, *, workspace_id, documents):
                assert workspace_id == expected_workspace_id
                assert len(documents) == 1
                payload = documents[0]
                assert payload.external_id == "browser-upload:pricing.md"
                assert payload.metadata["source_type"] == "browser_upload"
                return SimpleNamespace(
                    documents=[SimpleNamespace(document_id=document_id)],
                )

        app.dependency_overrides[get_db_session] = lambda: session
        monkeypatch.setattr(connectors_api, "ImportService", FakeImportService)

        response = await connectors_client.post(
            "/api/source-documents/upload",
            data={"workspace_id": str(expected_workspace_id)},
            files={"file": ("pricing.md", b"Decision: enterprise stays at $600/seat.", "text/markdown")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(document_id)
        assert body["connector_type"] == "local"
        assert body["processed_at"] is not None
        assert body["metadata"]["source_type"] == "browser_upload"

    async def test_upload_returns_404_for_missing_workspace(self, connectors_client, monkeypatch):
        class FakeImportService:
            def __init__(self, provided_session):
                assert provided_session is not None

            async def import_documents(self, *, workspace_id, documents):
                raise ImportWorkspaceNotFoundError("Workspace not found")

        app.dependency_overrides[get_db_session] = lambda: FakeSession()
        monkeypatch.setattr(connectors_api, "ImportService", FakeImportService)

        response = await connectors_client.post(
            "/api/source-documents/upload",
            data={"workspace_id": str(uuid4())},
            files={"file": ("notes.txt", b"Plain text notes", "text/plain")},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Workspace not found"
