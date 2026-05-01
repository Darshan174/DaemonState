from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import get_db_session
from app.main import app
from app.models import Base, Connector, SourceDocument
from app.processing.embedder import HashingEmbedder

TEST_DATABASE_URL = "sqlite+aiosqlite:///data/test_connectors.db"


@pytest.fixture(autouse=True)
def _force_local_providers(monkeypatch):
    monkeypatch.setattr("app.config.settings.litellm_api_key", None)
    monkeypatch.setattr("app.config.settings.extraction_model", None)
    monkeypatch.setattr("app.config.settings.embedding_model", None)
    monkeypatch.setattr("app.processing.embedder.settings.litellm_api_key", None)
    monkeypatch.setattr("app.processing.embedder.settings.embedding_model", None)
    monkeypatch.setattr("app.processing.extractor.settings.litellm_api_key", None)
    monkeypatch.setattr("app.processing.extractor.settings.extraction_model", None)
    monkeypatch.setattr("app.services.ingest.build_default_embedder", lambda: HashingEmbedder())
    monkeypatch.setattr("app.services.query.build_default_embedder", lambda: HashingEmbedder())


@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    async with engine.connect() as conn:
        outer = await conn.begin()
        await conn.begin_nested()
        session = AsyncSession(bind=conn, expire_on_commit=False)

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _reopen_savepoint(sync_session, transaction):
            if conn.closed or conn.invalidated:
                return
            if not conn.in_nested_transaction():
                conn.sync_connection.begin_nested()

        yield session
        await session.close()
        await outer.rollback()


@pytest.fixture
async def client(db_session):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestConnectorCatalog:
    async def test_list_connectors_returns_all_catalog_entries(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        assert "connectors" in data
        assert "setupStatus" in data
        types = [c["type"] for c in data["connectors"]]
        assert "slack" in types
        assert "discord" in types
        assert "gmail" in types
        assert "ai_context" in types
        assert "local" in types

    async def test_connector_response_has_frontend_shape(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        connectors = data["connectors"]
        setup_status = data["setupStatus"]

        for connector in connectors:
            assert "connector_type" in connector, f"Missing connector_type in {connector['type']}"
            assert connector["connector_type"] == connector["type"]
            assert "config" in connector, f"Missing config dict in {connector['type']}"
            assert isinstance(connector["config"], dict)

        for item in setup_status:
            assert "connector_type" in item, "Missing connector_type in setup status"
            assert item["connector_type"] == item["type"]

    async def test_connectors_have_required_fields(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        for connector in data["connectors"]:
            assert "connector_id" in connector
            assert "type" in connector
            assert "name" in connector
            assert "description" in connector
            assert "color" in connector
            assert "availability" in connector
            assert "status" in connector
            assert "provider" in connector
            assert "is_configured" in connector

    async def test_coming_soon_connectors_are_honest(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        discord = next(c for c in data["connectors"] if c["type"] == "discord")
        gmail = next(c for c in data["connectors"] if c["type"] == "gmail")
        assert discord["availability"] == "coming_soon"
        assert gmail["availability"] == "coming_soon"
        assert discord["status"] == "disconnected"
        assert gmail["status"] == "disconnected"

    async def test_ai_context_shows_as_connected(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        ai_ctx = next(c for c in data["connectors"] if c["type"] == "ai_context")
        assert ai_ctx["status"] == "connected"
        assert ai_ctx["availability"] == "available"
        assert ai_ctx["is_configured"] is True

    async def test_local_shows_as_connected(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        local = next(c for c in data["connectors"] if c["type"] == "local")
        assert local["status"] == "connected"
        assert local["availability"] == "available"

    async def test_slack_initially_disconnected_and_unsupported(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        slack = next(c for c in data["connectors"] if c["type"] == "slack")
        assert slack["status"] == "disconnected"
        assert slack["availability"] == "available"
        assert slack["is_configured"] is False
        assert slack["message"] is not None

    async def test_slack_connect_is_rejected_as_unsupported(self, client):
        response = await client.post(
            "/api/connectors/slack/connect",
            json={"config": {"team_name": "Should Fail"}},
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "not" in detail


class TestConnectorSetupStatus:
    async def test_setup_status_returns_all_types(self, client):
        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        types = [s["connector_type"] for s in data]
        assert "slack" in types
        assert "discord" in types
        assert "gmail" in types
        assert "ai_context" in types

    async def test_coming_soon_not_configured(self, client):
        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        discord = next(s for s in data if s["connector_type"] == "discord")
        assert discord["configured"] is False
        assert discord["status"] == "coming_soon"

    async def test_ai_context_configured(self, client):
        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        ai_ctx = next(s for s in data if s["connector_type"] == "ai_context")
        assert ai_ctx["configured"] is True

    async def test_slack_not_configured_unsupported(self, client):
        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        slack = next(s for s in data if s["connector_type"] == "slack")
        assert slack["configured"] is False
        assert slack["status"] == "disconnected"


class TestConnectorConnect:
    async def test_connect_slack_returns_400_unsupported(self, client):
        response = await client.post(
            "/api/connectors/slack/connect",
            json={"config": {"team_name": "Test Team", "bot_token": "xoxb-test"}},
        )
        assert response.status_code == 400
        assert "not" in response.json()["detail"].lower() or "unsupported" in response.json()["detail"].lower()

    async def test_connect_unknown_type_returns_404(self, client):
        response = await client.post(
            "/api/connectors/unknown_type/connect",
            json={"config": {}},
        )
        assert response.status_code == 404

    async def test_connect_coming_soon_returns_400(self, client):
        response = await client.post(
            "/api/connectors/discord/connect",
            json={"config": {}},
        )
        assert response.status_code == 400

    async def test_connect_gmail_returns_400(self, client):
        response = await client.post(
            "/api/connectors/gmail/connect",
            json={"config": {}},
        )
        assert response.status_code == 400

    async def test_connect_ai_context(self, client):
        response = await client.post(
            "/api/connectors/ai_context/connect",
            json={"config": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "ai_context"
        assert data["status"] == "connected"


class TestConnectorSyncAndDisconnect:
    async def test_sync_slack_returns_pending_job(self, client, db_session):
        connector = Connector(
            id=uuid4(),
            connector_type="local",
            status="connected",
            config_json="{}",
            items_synced=0,
        )
        db_session.add(connector)
        await db_session.flush()
        await db_session.commit()
        connector_id = connector.id

        sync_resp = await client.post(f"/api/connectors/{connector_id}/sync")
        assert sync_resp.status_code == 200
        data = sync_resp.json()
        assert data["status"] == "pending"
        assert data["job_id"] is not None
        assert data["connector_id"] == str(connector_id)

    async def test_sync_discord_fails_because_unsupported(self, client, db_session):
        connector = Connector(
            id=uuid4(),
            connector_type="discord",
            status="connected",
            config_json="{}",
            items_synced=0,
        )
        db_session.add(connector)
        await db_session.flush()
        await db_session.commit()

        sync_resp = await client.post(f"/api/connectors/{connector.id}/sync")
        assert sync_resp.status_code == 200
        data = sync_resp.json()
        assert data["status"] == "failed"
        assert data["error_type"] == "unsupported_connector"
        assert "not supported" in data["error_message"].lower() or "not yet" in data["error_message"].lower()

    async def test_sync_status_for_nonexistent_connector_returns_404(self, client):
        fake_id = str(uuid4())
        response = await client.get(f"/api/connectors/{fake_id}/sync-status")
        assert response.status_code == 404

    async def test_sync_jobs_empty_initially(self, client, db_session):
        connector = Connector(
            id=uuid4(),
            connector_type="slack",
            status="connected",
            config_json="{}",
            items_synced=0,
        )
        db_session.add(connector)
        await db_session.flush()
        await db_session.commit()

        response = await client.get(f"/api/connectors/{connector.id}/sync-jobs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_disconnect_connector(self, client):
        connect_resp = await client.post(
            "/api/connectors/ai_context/connect",
            json={"config": {}},
        )
        assert connect_resp.status_code == 200
        connector_id = connect_resp.json()["connector_id"]

        disconnect_resp = await client.delete(f"/api/connectors/{connector_id}")
        assert disconnect_resp.status_code == 200
        data = disconnect_resp.json()
        assert data["status"] == "disconnected"

        list_resp = await client.get("/api/connectors")
        ai_ctx = next(c for c in list_resp.json()["connectors"] if c["type"] == "ai_context")
        assert ai_ctx["status"] == "disconnected"

    async def test_disconnect_nonexistent_connector_returns_404(self, client):
        fake_id = str(uuid4())
        response = await client.delete(f"/api/connectors/{fake_id}")
        assert response.status_code == 404


class TestAIContextImport:
    async def test_import_single_ai_context_document(self, client, db_session):
        payload = {
            "documents": [
                {
                    "external_id": "codex-plan-2026-05-01",
                    "content": "Decision: use SQLite for local development. Action item: set up test DB.",
                    "author": "Codex",
                    "tool": "codex",
                    "session_type": "plan",
                    "session_id": "session-abc-123",
                    "started_at": "2026-05-01T10:00:00Z",
                    "ended_at": "2026-05-01T10:30:00Z",
                    "metadata": {
                        "branch": "agent/glm-connector-ai-context-implementation",
                        "files_changed": ["app/api/connectors.py"],
                    },
                },
            ],
        }

        response = await client.post("/api/connectors/ai-context/import", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["created"] == 1
        assert len(data["document_ids"]) == 1
        assert data["source_type"] == "ai_context"

        from sqlalchemy import select
        docs = list(await db_session.scalars(
            select(SourceDocument).where(SourceDocument.external_id == "codex-plan-2026-05-01")
        ))
        assert len(docs) == 1
        doc = docs[0]
        assert doc.source_type == "ai_context_codex"
        assert doc.author == "Codex"
        metadata = json.loads(doc.metadata_json)
        assert metadata["tool"] == "codex"
        assert metadata["session_type"] == "plan"
        assert metadata["session_id"] == "session-abc-123"
        assert metadata["ingested_via"] == "ai_context_import"
        assert metadata["branch"] == "agent/glm-connector-ai-context-implementation"

    async def test_import_multiple_ai_context_documents(self, client):
        payload = {
            "documents": [
                {
                    "external_id": "claude-code-review-001",
                    "content": "Blocker: API schema mismatch between frontend and backend.",
                    "tool": "claude_code",
                    "session_type": "review",
                },
                {
                    "external_id": "opencode-session-002",
                    "content": "Decision: implement connector catalog first, then sync jobs.",
                    "tool": "opencode",
                    "session_type": "implementation",
                },
                {
                    "external_id": "generic-diff-003",
                    "content": "Meeting outcome: Ship v0.2.0 this week.",
                    "tool": "generic",
                },
            ],
        }

        response = await client.post("/api/connectors/ai-context/import", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["created"] == 3

    async def test_import_with_unknown_tool_normalized_to_generic(self, client, db_session):
        payload = {
            "documents": [
                {
                    "external_id": "unknown-tool-doc",
                    "content": "Some AI session output",
                    "tool": "unknown_agent",
                },
            ],
        }

        response = await client.post("/api/connectors/ai-context/import", json=payload)
        assert response.status_code == 201

        from sqlalchemy import select
        docs = list(await db_session.scalars(
            select(SourceDocument).where(SourceDocument.external_id == "unknown-tool-doc")
        ))
        assert len(docs) == 1
        doc = docs[0]
        assert doc.source_type == "ai_context"
        metadata = json.loads(doc.metadata_json)
        assert metadata["tool"] == "generic"

    async def test_import_with_no_tool_uses_base_source_type(self, client, db_session):
        payload = {
            "documents": [
                {
                    "external_id": "no-tool-doc",
                    "content": "Some AI context without a tool",
                },
            ],
        }

        response = await client.post("/api/connectors/ai-context/import", json=payload)
        assert response.status_code == 201

        from sqlalchemy import select
        docs = list(await db_session.scalars(
            select(SourceDocument).where(SourceDocument.external_id == "no-tool-doc")
        ))
        assert len(docs) == 1
        assert docs[0].source_type == "ai_context"

    async def test_import_preserves_metadata_provenance(self, client, db_session):
        payload = {
            "documents": [
                {
                    "external_id": "provenance-doc",
                    "content": "Decision: pricing is $20/month.",
                    "author": "GLM 5.1",
                    "tool": "codex",
                    "metadata": {
                        "branch": "agent/glm-connector-ai-context-implementation",
                        "task_file": ".agent-runs/glm-task.md",
                    },
                },
            ],
        }

        response = await client.post("/api/connectors/ai-context/import", json=payload)
        assert response.status_code == 201

        from sqlalchemy import select
        docs = list(await db_session.scalars(
            select(SourceDocument).where(SourceDocument.external_id == "provenance-doc")
        ))
        assert len(docs) == 1
        metadata = json.loads(docs[0].metadata_json)
        assert metadata["tool"] == "codex"
        assert metadata["ingested_via"] == "ai_context_import"
        assert metadata["branch"] == "agent/glm-connector-ai-context-implementation"
        assert metadata["task_file"] == ".agent-runs/glm-task.md"

    async def test_import_empty_documents_returns_422(self, client):
        response = await client.post("/api/connectors/ai-context/import", json={"documents": []})
        assert response.status_code == 422


class TestProcessingSummary:
    async def test_processing_summary_counts_ai_context_documents(self, client, db_session):
        doc1 = SourceDocument(
            id=uuid4(),
            source_type="ai_context_codex",
            external_id="summary-doc-1",
            content="Test content 1",
            author="Codex",
            metadata_json=json.dumps({"tool": "codex", "ingested_via": "ai_context_import"}),
        )
        doc2 = SourceDocument(
            id=uuid4(),
            source_type="ai_context",
            external_id="summary-doc-2",
            content="Test content 2",
            metadata_json=json.dumps({"ingested_via": "ai_context_import"}),
        )
        doc3 = SourceDocument(
            id=uuid4(),
            source_type="ai_context_claude_code",
            external_id="summary-doc-3",
            content="Test content 3",
            metadata_json=json.dumps({"tool": "claude_code", "ingested_via": "ai_context_import"}),
        )
        doc4 = SourceDocument(
            id=uuid4(),
            source_type="local",
            external_id="local-doc-1",
            content="Local content",
            metadata_json="{}",
        )
        db_session.add_all([doc1, doc2, doc3, doc4])
        await db_session.flush()
        await db_session.commit()

        response = await client.get("/api/connectors/processing-summary")
        assert response.status_code == 200
        data = response.json()
        items = {item["connector_type"]: item for item in data["items"]}

        assert "ai_context" in items
        ai_ctx = items["ai_context"]
        assert ai_ctx["total_documents"] >= 3
        assert "local" in items

    async def test_processing_summary_counts_ai_context_subtypes_together(self, client, db_session):
        doc1 = SourceDocument(
            id=uuid4(),
            source_type="ai_context_codex",
            external_id="subtype-test-1",
            content="Codex output",
            metadata_json=json.dumps({"tool": "codex"}),
        )
        doc2 = SourceDocument(
            id=uuid4(),
            source_type="ai_context_opencode",
            external_id="subtype-test-2",
            content="OpenCode output",
            metadata_json=json.dumps({"tool": "opencode"}),
        )
        doc3 = SourceDocument(
            id=uuid4(),
            source_type="ai_context_claude_code",
            external_id="subtype-test-3",
            content="Claude Code output",
            metadata_json=json.dumps({"tool": "claude_code"}),
        )
        doc4 = SourceDocument(
            id=uuid4(),
            source_type="ai_context",
            external_id="subtype-test-4",
            content="Generic AI context",
            metadata_json=json.dumps({}),
        )
        db_session.add_all([doc1, doc2, doc3, doc4])
        await db_session.flush()
        await db_session.commit()

        response = await client.get("/api/connectors/processing-summary")
        assert response.status_code == 200
        data = response.json()
        ai_ctx = next(item for item in data["items"] if item["connector_type"] == "ai_context")
        assert ai_ctx["total_documents"] >= 4

    async def test_processing_summary_default_zeros(self, client):
        response = await client.get("/api/connectors/processing-summary")
        assert response.status_code == 200
        data = response.json()
        types_present = {item["connector_type"] for item in data["items"]}
        assert "slack" in types_present
        assert "discord" in types_present
        assert "ai_context" in types_present
        for item in data["items"]:
            if item["connector_type"] in ("discord", "gmail"):
                assert item["total_documents"] == 0


class TestSyncJobFlow:
    async def test_full_sync_job_lifecycle(self, client, db_session):
        connector = Connector(
            id=uuid4(),
            connector_type="local",
            status="connected",
            config_json="{}",
            items_synced=0,
        )
        db_session.add(connector)
        await db_session.flush()
        await db_session.commit()
        connector_id = connector.id

        sync_resp = await client.post(f"/api/connectors/{connector_id}/sync")
        assert sync_resp.status_code == 200
        job_id = sync_resp.json()["job_id"]

        status_resp = await client.get(f"/api/connectors/{connector_id}/sync-status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "pending"
        assert status_data["job_id"] == job_id

        jobs_resp = await client.get(f"/api/connectors/{connector_id}/sync-jobs")
        assert jobs_resp.status_code == 200
        jobs_data = jobs_resp.json()
        assert len(jobs_data) >= 1
        assert jobs_data[0]["job_id"] == job_id

    async def test_sync_nonexistent_connector_returns_404(self, client):
        fake_id = str(uuid4())
        response = await client.post(f"/api/connectors/{fake_id}/sync")
        assert response.status_code == 404

    async def test_slack_sync_returns_unsupported_error(self, client, db_session):
        connector = Connector(
            id=uuid4(),
            connector_type="slack",
            status="connected",
            config_json="{}",
            items_synced=0,
        )
        db_session.add(connector)
        await db_session.flush()
        await db_session.commit()

        sync_resp = await client.post(f"/api/connectors/{connector.id}/sync")
        assert sync_resp.status_code == 200
        data = sync_resp.json()
        assert data["status"] == "failed"
        assert data["error_type"] == "unsupported_connector"
        assert "Slack" in data["error_message"]

    async def test_slack_connect_returns_400_unsupported(self, client):
        response = await client.post(
            "/api/connectors/slack/connect",
            json={"config": {"team_name": "Test Team"}},
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "not" in detail or "unsupported" in detail