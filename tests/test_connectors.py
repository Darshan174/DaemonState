from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import _ensure_sqlite_parent_dir, get_db_session
from app.main import app
from app.migrations import run_migrations
from app.models import Base, Component, Connector, Model, SourceDocument, Workspace
from app.processing.embedder import HashingEmbedder

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"sqlite+aiosqlite:///{Path(gettempdir()) / f'test_connectors_{uuid4().hex}.db'}",
)


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
    for key in (
        "SLACK_CLIENT_ID",
        "SLACK_CLIENT_SECRET",
        "SLACK_MANAGED_INSTALL_URL",
        "ZOOM_CLIENT_ID",
        "ZOOM_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("app.config.settings.slack_client_id", None, raising=False)
    monkeypatch.setattr("app.config.settings.slack_client_secret", None, raising=False)
    monkeypatch.setattr("app.config.settings.slack_managed_install_url", None, raising=False)
    monkeypatch.setattr("app.config.settings.zoom_client_id", None, raising=False)
    monkeypatch.setattr("app.config.settings.zoom_client_secret", None, raising=False)
    monkeypatch.setattr("app.config.settings.google_client_id", None, raising=False)
    monkeypatch.setattr("app.config.settings.google_client_secret", None, raising=False)
    monkeypatch.setattr("app.config.settings.database_url", TEST_DATABASE_URL, raising=False)


@pytest.fixture(scope="session")
async def engine():
    _ensure_sqlite_parent_dir(TEST_DATABASE_URL)
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)
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
        for expected in ["slack", "discord", "ai_context", "local", "zoom", "gdrive", "gmail", "wispr_flow"]:
            assert expected in types, f"Missing {expected} in connector catalog"

    async def test_catalog_matches_frontend_descriptions(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        by_type = {c["type"]: c for c in data["connectors"]}

        assert by_type["discord"]["description"] == "Server channels, threads, and community context"
        assert by_type["ai_context"]["description"] == "Codex, Claude Code, OpenCode, plans, diffs, and review notes"
        assert by_type["local"]["description"] == "Uploaded Markdown, text, JSON, CSV, and other local documents"
        assert by_type["zoom"]["name"] == "Zoom"
        assert by_type["gdrive"]["name"] == "Google Drive"
        assert by_type["wispr_flow"]["name"] == "Wispr Flow"

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

    async def test_connector_logo_background_colors_match_brand_surfaces(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        by_type = {c["type"]: c for c in data["connectors"]}

        assert by_type["gdrive"]["color"] == "#ffffff"
        assert by_type["gmail"]["color"] == "#ffffff"
        assert by_type["opencode"]["color"] == "#000000"

    async def test_coming_soon_connectors_are_honest(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        for t in ["discord", "zoom", "wispr_flow"]:
            entry = next(c for c in data["connectors"] if c["type"] == t)
            assert entry["availability"] == "coming_soon"
            assert entry["status"] == "disconnected"
            assert entry["is_configured"] is False

    async def test_google_connectors_show_missing_oauth_config_not_coming_soon(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        for t in ["gdrive", "gmail"]:
            entry = next(c for c in data["connectors"] if c["type"] == t)
            assert entry["availability"] == "available"
            assert entry["status"] == "disconnected"
            assert entry["is_configured"] is False
            assert "GOOGLE_CLIENT_ID" in entry["message"]

    async def test_ai_context_shows_as_available_but_not_connected_until_import(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        ai_ctx = next(c for c in data["connectors"] if c["type"] == "ai_context")
        assert ai_ctx["status"] == "disconnected"
        assert ai_ctx["availability"] == "available"
        assert ai_ctx["is_configured"] is True
        assert ai_ctx["connector_id"] is None

    async def test_local_shows_as_available_but_not_connected_until_upload(self, client):
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        local = next(c for c in data["connectors"] if c["type"] == "local")
        assert local["status"] == "disconnected"
        assert local["availability"] == "available"
        assert local["connector_id"] is None

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
        for expected in ["slack", "discord", "gmail", "ai_context", "local", "zoom", "gdrive", "wispr_flow"]:
            assert expected in types, f"Missing {expected} in setup status"

    async def test_coming_soon_not_configured(self, client):
        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        for t in ["discord", "zoom", "wispr_flow"]:
            entry = next(s for s in data if s["connector_type"] == t)
            assert entry["configured"] is False
            assert entry["status"] == "coming_soon"

    async def test_google_setup_status_reflects_oauth_env(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        for t in ["gdrive", "gmail"]:
            entry = next(s for s in data if s["connector_type"] == t)
            assert entry["configured"] is True
            assert entry["status"] == "disconnected"
            assert entry["managed_install_url"] == f"/api/connectors/{t}/install"
            assert entry["missing"] == []

    async def test_google_catalog_available_when_oauth_env_present(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        for t in ["gdrive", "gmail"]:
            entry = next(c for c in data["connectors"] if c["type"] == t)
            assert entry["availability"] == "available"
            assert entry["status"] == "disconnected"
            assert entry["is_configured"] is True
            assert entry["message"] is None

    async def test_google_setup_status_exposes_redirect_uri(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        for t in ["gdrive", "gmail"]:
            entry = next(s for s in data if s["connector_type"] == t)
            assert entry["redirect_uri"] is not None
            assert entry["redirect_uri"].endswith(f"/api/connectors/{t}/callback")

    async def test_google_redirect_uri_override_from_env(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
        monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://app.example.com/oauth/callback")

        response = await client.get("/api/connectors/setup-status")
        assert response.status_code == 200
        data = response.json()
        for t in ["gdrive", "gmail"]:
            entry = next(s for s in data if s["connector_type"] == t)
            assert entry["redirect_uri"] == "https://app.example.com/oauth/callback"

    async def test_google_catalog_includes_redirect_uri(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

        response = await client.get("/api/connectors")
        assert response.status_code == 200
        data = response.json()
        for t in ["gdrive", "gmail"]:
            entry = next(s for s in data["setupStatus"] if s["connector_type"] == t)
            assert entry["redirect_uri"] is not None
            assert entry["redirect_uri"].endswith(f"/api/connectors/{t}/callback")

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

    async def test_connect_zoom_returns_400_coming_soon(self, client):
        response = await client.post(
            "/api/connectors/zoom/connect",
            json={"config": {}},
        )
        assert response.status_code == 400

    async def test_connect_gdrive_returns_400_coming_soon(self, client):
        response = await client.post(
            "/api/connectors/gdrive/connect",
            json={"config": {}},
        )
        assert response.status_code == 400

    async def test_connect_wispr_flow_returns_400_coming_soon(self, client):
        response = await client.post(
            "/api/connectors/wispr_flow/connect",
            json={"config": {}},
        )
        assert response.status_code == 400

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

    async def test_sync_gdrive_queues_when_connected(self, client, db_session, monkeypatch):
        async def _noop_run_sync_job(*args, **kwargs):
            return None

        monkeypatch.setattr("app.api.connectors._run_sync_job", _noop_run_sync_job)
        connector = Connector(
            id=uuid4(),
            connector_type="gdrive",
            status="connected",
            config_json="{}",
            credentials_json=json.dumps({"access_token": "google-token"}),
            items_synced=0,
        )
        db_session.add(connector)
        await db_session.flush()
        await db_session.commit()

        sync_resp = await client.post(f"/api/connectors/{connector.id}/sync")
        assert sync_resp.status_code == 200
        data = sync_resp.json()
        assert data["status"] == "pending"
        assert data["error_type"] is None

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


class TestAISessionIngest:
    async def test_ai_session_ingest_processes_agent_session_document(self, client, db_session):
        workspace = Workspace(id=uuid4(), name="AI Sessions", slug=f"ai-sessions-{uuid4().hex}")
        db_session.add(workspace)
        await db_session.flush()
        await db_session.commit()

        response = await client.post(
            "/api/connectors/ai-session/ingest",
            json={
                "workspace_id": str(workspace.id),
                "connector_type": "codex",
                "session_id": "session-123",
                "content": "Decision: use source documents as the graph provenance layer.",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["extract"]["documents_processed"] == 1
        assert data["extract"]["components_created"] >= 1

        doc = await db_session.scalar(
            select(SourceDocument).where(SourceDocument.external_id == "codex:session:session-123")
        )
        assert doc is not None
        assert doc.source_type == "agent_session"
        assert doc.processed_at is not None

        components = list(await db_session.scalars(
            select(Component).where(Component.source_document_id == doc.id)
        ))
        assert components


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

    async def test_processing_summary_separates_processed_and_pending_documents(self, client, db_session):
        from datetime import datetime

        processed_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="processed-slack-doc",
            content="Processed Slack content",
            processed_at=datetime.utcnow(),
            metadata_json="{}",
        )
        pending_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="pending-slack-doc",
            content="Pending Slack content",
            metadata_json="{}",
        )
        db_session.add_all([processed_doc, pending_doc])
        await db_session.flush()
        await db_session.commit()

        response = await client.get("/api/connectors/processing-summary")
        assert response.status_code == 200
        data = response.json()
        slack = next(item for item in data["items"] if item["connector_type"] == "slack")

        assert slack["processedDocuments"] >= 1
        assert slack["unprocessedDocuments"] >= 1
        assert slack["total_documents"] >= 2

    async def test_processing_summary_filters_by_workspace(self, client, db_session):
        ws_a = Workspace(id=uuid4(), name="Workspace A", slug=f"workspace-a-{uuid4().hex}")
        ws_b = Workspace(id=uuid4(), name="Workspace B", slug=f"workspace-b-{uuid4().hex}")
        db_session.add_all([
            ws_a,
            ws_b,
            Connector(id=uuid4(), workspace_id=ws_a.id, connector_type="slack", status="connected"),
            Connector(id=uuid4(), workspace_id=ws_b.id, connector_type="slack", status="connected"),
            SourceDocument(
                id=uuid4(),
                source_type="slack",
                external_id="slack:workspace-a",
                content="Workspace A message",
                metadata_json=json.dumps({"workspace_id": str(ws_a.id)}),
            ),
            SourceDocument(
                id=uuid4(),
                source_type="slack",
                external_id="slack:workspace-b",
                content="Workspace B message",
                metadata_json=json.dumps({"workspace_id": str(ws_b.id)}),
            ),
        ])
        await db_session.flush()
        await db_session.commit()

        response = await client.get(f"/api/connectors/processing-summary?workspace_id={ws_a.id}")
        assert response.status_code == 200
        data = response.json()
        slack = next(item for item in data["items"] if item["connector_type"] == "slack")

        assert slack["total_documents"] == 1
        assert slack["unprocessedDocuments"] == 1

    async def test_connector_extraction_repairs_processed_docs_without_components(self, db_session):
        from app.extract.basic import extract_from_source_documents
        from datetime import datetime

        doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:C123:1",
            content="Plain status update without explicit graph keywords.",
            processed_at=datetime.utcnow(),
            metadata_json=json.dumps({"channel_name": "general"}),
        )
        db_session.add(doc)
        await db_session.flush()

        result = await extract_from_source_documents("slack", db_session)

        assert result["documents_processed"] == 1
        assert result["components_created"] >= 1
        rows = (await db_session.execute(
            select(Component, Model.name)
            .join(Model, Component.model_id == Model.id)
            .where(Component.source_document_id == doc.id)
        )).all()
        assert rows
        assert rows[0][1] == "Message"

    async def test_processing_summary_default_zeros(self, client):
        response = await client.get("/api/connectors/processing-summary")
        assert response.status_code == 200
        data = response.json()
        types_present = {item["connector_type"] for item in data["items"]}
        for expected in ["slack", "discord", "ai_context", "local", "zoom", "gdrive", "gmail", "wispr_flow"]:
            assert expected in types_present, f"Missing {expected} in processing summary"
        for item in data["items"]:
            if item["connector_type"] in ("discord", "gmail", "zoom", "gdrive", "wispr_flow"):
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

    async def test_slack_sync_queues_job(self, client, db_session):
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
        assert data["status"] == "pending"
        assert data["job_id"] is not None
        assert data["connector_id"] == str(connector.id)

    async def test_slack_connect_returns_400_unsupported(self, client):
        response = await client.post(
            "/api/connectors/slack/connect",
            json={"config": {"team_name": "Test Team"}},
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "not" in detail or "unsupported" in detail


class TestGoogleSync:
    async def test_sync_gmail_persists_messages(self, db_session, monkeypatch):
        from app.sync import google
        from sqlalchemy import select

        body = base64.urlsafe_b64encode(b"Decision: ship Gmail sync this week.").decode().rstrip("=")

        class FakeGoogleClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, headers=None, params=None):
                if url.endswith("/users/me/messages"):
                    return httpx.Response(200, json={"messages": [{"id": "msg-1"}]})
                if url.endswith("/users/me/messages/msg-1"):
                    return httpx.Response(
                        200,
                        json={
                            "id": "msg-1",
                            "threadId": "thread-1",
                            "snippet": "Decision snippet",
                            "labelIds": ["INBOX"],
                            "payload": {
                                "mimeType": "text/plain",
                                "headers": [
                                    {"name": "Subject", "value": "Launch plan"},
                                    {"name": "From", "value": "pm@example.com"},
                                    {"name": "To", "value": "team@example.com"},
                                    {"name": "Date", "value": "Thu, 7 May 2026 10:00:00 +0000"},
                                ],
                                "body": {"data": body},
                            },
                        },
                    )
                raise AssertionError(f"unexpected URL {url}")

        monkeypatch.setattr(google.httpx, "AsyncClient", FakeGoogleClient)
        connector = Connector(
            id=uuid4(),
            connector_type="gmail",
            status="connected",
            credentials_json=json.dumps({"access_token": "google-token"}),
            config_json="{}",
        )
        db_session.add(connector)
        await db_session.flush()

        result = await google.sync_gmail(connector, db_session)

        assert result["documents_fetched"] == 1
        assert result["documents_persisted"] == 1
        doc = await db_session.scalar(select(SourceDocument).where(SourceDocument.external_id == "gmail:msg-1"))
        assert doc is not None
        assert doc.source_type == "gmail"
        assert "Decision: ship Gmail sync this week." in doc.content
        metadata = json.loads(doc.metadata_json)
        assert metadata["subject"] == "Launch plan"
        assert metadata["workspace_id"] == str(connector.workspace_id)

    async def test_sync_gdrive_persists_exported_files(self, db_session, monkeypatch):
        from app.sync import google
        from sqlalchemy import select

        class FakeGoogleClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, headers=None, params=None):
                if url.endswith("/drive/v3/files"):
                    return httpx.Response(
                        200,
                        json={
                            "files": [
                                {
                                    "id": "file-1",
                                    "name": "Roadmap",
                                    "mimeType": "application/vnd.google-apps.document",
                                    "webViewLink": "https://docs.google.com/document/d/file-1",
                                    "modifiedTime": "2026-05-07T10:00:00Z",
                                    "owners": [{"displayName": "PM", "emailAddress": "pm@example.com"}],
                                }
                            ]
                        },
                    )
                if url.endswith("/drive/v3/files/file-1/export"):
                    return httpx.Response(200, text="Action item: launch Drive sync.")
                raise AssertionError(f"unexpected URL {url}")

        monkeypatch.setattr(google.httpx, "AsyncClient", FakeGoogleClient)
        connector = Connector(
            id=uuid4(),
            connector_type="gdrive",
            status="connected",
            credentials_json=json.dumps({"access_token": "google-token"}),
            config_json="{}",
        )
        db_session.add(connector)
        await db_session.flush()

        result = await google.sync_gdrive(connector, db_session)

        assert result["documents_fetched"] == 1
        assert result["documents_persisted"] == 1
        doc = await db_session.scalar(select(SourceDocument).where(SourceDocument.external_id == "gdrive:file-1"))
        assert doc is not None
        assert doc.source_type == "gdrive"
        assert "Action item: launch Drive sync." in doc.content
        metadata = json.loads(doc.metadata_json)
        assert metadata["name"] == "Roadmap"

    async def test_sync_gmail_without_credentials_errors(self, db_session):
        from app.sync.google import sync_gmail

        connector = Connector(
            id=uuid4(),
            connector_type="gmail",
            status="connected",
            credentials_json="{}",
            config_json="{}",
        )
        db_session.add(connector)
        await db_session.flush()

        with pytest.raises(ValueError, match="No Google access token"):
            await sync_gmail(connector, db_session)
