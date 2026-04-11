from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import imports as imports_api
from app.main import app
from app.schemas.imports import ImportDocumentResult, ImportResponse
from app.services.import_service import ImportWorkspaceNotFoundError


@pytest.fixture
async def contract_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()


class TestImportAPI:
    async def test_import_returns_contract_payload(self, contract_client):
        workspace_id = uuid4()
        connector_id = uuid4()
        document_id = uuid4()

        class FakeImportService:
            async def import_documents(self, *, workspace_id, documents):
                assert len(documents) == 1
                return ImportResponse(
                    workspace_id=workspace_id,
                    connector_id=connector_id,
                    connector_type="local",
                    model_name="Imported Files",
                    total_documents=1,
                    created_documents=1,
                    updated_documents=0,
                    unchanged_documents=0,
                    processed_documents=1,
                    failed_documents=0,
                    documents=[
                        ImportDocumentResult(
                            document_id=document_id,
                            external_id="local-file:pricing",
                            label="pricing.md",
                            status="created",
                            processed_at=datetime.now(UTC),
                            error=None,
                        )
                    ],
                    imported_at=datetime.now(UTC),
                )

        app.dependency_overrides[imports_api.get_import_service] = lambda: FakeImportService()

        response = await contract_client.post(
            "/api/imports",
            json={
                "workspace_id": str(workspace_id),
                "documents": [
                    {
                        "external_id": "local-file:pricing",
                        "content": "decision: enterprise plan is $999/mo",
                        "source_url": "file:///tmp/pricing.md",
                        "metadata": {
                            "title": "pricing.md",
                            "source_type": "local_file_import",
                        },
                    }
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["workspace_id"] == str(workspace_id)
        assert body["connector_id"] == str(connector_id)
        assert body["connector_type"] == "local"
        assert body["model_name"] == "Imported Files"
        assert body["created_documents"] == 1
        assert body["processed_documents"] == 1
        assert body["failed_documents"] == 0
        assert body["documents"][0]["document_id"] == str(document_id)
        assert body["documents"][0]["status"] == "created"
        assert body["documents"][0]["label"] == "pricing.md"

    async def test_import_returns_404_for_missing_workspace(self, contract_client):
        class FakeImportService:
            async def import_documents(self, *, workspace_id, documents):
                raise ImportWorkspaceNotFoundError("Workspace not found")

        app.dependency_overrides[imports_api.get_import_service] = lambda: FakeImportService()

        response = await contract_client.post(
            "/api/imports",
            json={
                "workspace_id": str(uuid4()),
                "documents": [
                    {
                        "external_id": "local-file:missing",
                        "content": "decision: this should fail",
                    }
                ],
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Workspace not found"

    async def test_import_rejects_duplicate_external_ids(self, contract_client):
        response = await contract_client.post(
            "/api/imports",
            json={
                "workspace_id": str(uuid4()),
                "documents": [
                    {
                        "external_id": "local-file:duplicate",
                        "content": "decision: one",
                    },
                    {
                        "external_id": "local-file:duplicate",
                        "content": "decision: two",
                    },
                ],
            },
        )

        assert response.status_code == 422
        assert "Duplicate external_id values are not allowed" in str(response.json())
