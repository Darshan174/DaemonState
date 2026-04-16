"""Tests for operator/observability APIs.

TestReprocessDocument    — POST /source-documents/{id}/reprocess
TestDeleteRestoreDocument — DELETE/POST restore for /source-documents/{id}
TestComponentSources     — GET /components/{id}/sources
TestDocumentComponents   — GET /source-documents/{id}/components
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

import app.services.connector_service as connector_module
from app.models.connector import Connector, ConnectorStatus
from app.models.job import SyncJob, SyncJobStatus
from app.models.knowledge import Component, ComponentSource, KnowledgeModel
from app.models.review import ReviewDecision, ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace
from app.utils.crypto import encrypt_token

from cryptography.fernet import Fernet

from app.main import app

_TEST_FERNET_KEY = Fernet.generate_key().decode()


def _make_slack_connector(workspace, encrypted_token=None):
    return Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        oauth_token_encrypted=encrypted_token,
        config={"team_name": "Test"},
    )


def _make_source_doc(connector, *, processed=False):
    return SourceDocument(
        connector_id=connector.id,
        connector_type=ConnectorType.SLACK,
        external_id=f"slack:C123:{uuid4().hex}",
        content="Some meeting content with decision: do the thing.",
        author="user@example.com",
        source_url="https://slack.com/archives/C123/p1234",
        processed_at=datetime.now(timezone.utc) if processed else None,
        metadata_json={"channel_name": "general"},
    )


def _make_knowledge_model(workspace):
    return KnowledgeModel(
        workspace_id=workspace.id,
        name=f"model-{uuid4().hex[:8]}",
    )


def _make_component(model, *, name="decision:launch date", value="2026-04-15"):
    return Component(
        model_id=model.id,
        name=name,
        value=value,
        confidence=0.9,
        last_verified_at=datetime.now(timezone.utc),
    )


# ── Reprocess ────────────────────────────────────────────────────


class TestReprocessDocument:
    def test_route_registered_once(self):
        routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) == "/api/source-documents/{document_id}/reprocess"
            and "POST" in getattr(route, "methods", set())
        ]
        assert len(routes) == 1

    def _setup(self, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

    async def test_reprocess_returns_202_and_queues_job(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace, encrypt_token("xoxb-test"))
        db_session.add(conn)
        await db_session.flush()
        conn_id = conn.id

        doc = _make_source_doc(conn, processed=True)
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        mock_delay = MagicMock()
        mock_delay.return_value.id = "celery-ingestion-1"
        monkeypatch.setattr("app.tasks.ingestion.run_ingestion.delay", mock_delay)

        resp = await client.post(
            f"/api/source-documents/{doc_id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["job_type"] == "reprocess"
        assert body["status"] == "pending"
        assert "job_id" in body

        # Job row persisted
        db_session.expire_all()
        job = await db_session.scalar(
            select(SyncJob).where(SyncJob.connector_id == conn_id)
        )
        assert job is not None
        assert job.status == SyncJobStatus.PENDING
        assert job.job_type == "reprocess"
        assert job.result_metadata["trigger"] == "reprocess"
        assert job.result_metadata["document_id"] == str(doc_id)

        # processed_at cleared
        refreshed_doc = await db_session.scalar(
            select(SourceDocument).where(SourceDocument.id == doc_id)
        )
        assert refreshed_doc.processed_at is None

        mock_delay.assert_called_once()

    async def test_reprocess_dispatch_failure_returns_502_and_marks_failed(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace, encrypt_token("xoxb-test"))
        db_session.add(conn)
        await db_session.flush()
        conn_id = conn.id

        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        monkeypatch.setattr(
            "app.tasks.ingestion.run_ingestion.delay",
            MagicMock(side_effect=Exception("Redis unreachable")),
        )

        resp = await client.post(
            f"/api/source-documents/{doc_id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 502

        db_session.expire_all()
        job = await db_session.scalar(
            select(SyncJob).where(SyncJob.connector_id == conn_id)
        )
        assert job is not None
        assert job.status == SyncJobStatus.FAILED
        assert job.error_type == "DispatchError"

    async def test_reprocess_missing_document_returns_404(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        resp = await client.post(
            f"/api/source-documents/{uuid4()}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_reprocess_missing_workspace_returns_404(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()
        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        resp = await client.post(
            f"/api/source-documents/{doc_id}/reprocess",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404


class TestDeleteRestoreDocument:
    def test_delete_route_registered_once(self):
        routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) == "/api/source-documents/{document_id}"
            and "DELETE" in getattr(route, "methods", set())
        ]
        assert len(routes) == 1

    def test_restore_route_registered_once(self):
        routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) == "/api/source-documents/{document_id}/restore"
            and "POST" in getattr(route, "methods", set())
        ]
        assert len(routes) == 1

    async def test_delete_marks_document_deleted(
        self, client, workspace, db_session
    ):
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn, processed=True)
        db_session.add(doc)
        await db_session.flush()

        resp = await client.delete(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 204

        await db_session.refresh(doc)
        assert doc.deleted_at is not None

        hidden = await client.get(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert hidden.status_code == 404

    async def test_delete_missing_document_returns_404(self, client, workspace):
        resp = await client.delete(
            f"/api/source-documents/{uuid4()}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_restore_undeletes_document(
        self, client, workspace, db_session
    ):
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn, processed=True)
        doc.deleted_at = datetime.now(timezone.utc)
        db_session.add(doc)
        await db_session.flush()

        resp = await client.post(
            f"/api/source-documents/{doc.id}/restore",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(doc.id)
        assert body["deleted_at"] is None

        await db_session.refresh(doc)
        assert doc.deleted_at is None

        visible = await client.get(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert visible.status_code == 200

    async def test_restore_wrong_workspace_returns_404(
        self, client, workspace, db_session
    ):
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn)
        doc.deleted_at = datetime.now(timezone.utc)
        db_session.add(doc)
        await db_session.flush()

        resp = await client.post(
            f"/api/source-documents/{doc.id}/restore",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404


# ── Component sources ─────────────────────────────────────────────


class TestComponentSources:
    def test_route_registered_once(self):
        routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) == "/api/components/{component_id}/sources"
            and "GET" in getattr(route, "methods", set())
        ]
        assert len(routes) == 1

    async def test_returns_source_documents_for_component(
        self, client, workspace, db_session
    ):
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc1 = _make_source_doc(conn)
        doc2 = _make_source_doc(conn)
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        model = _make_knowledge_model(workspace)
        db_session.add(model)
        await db_session.flush()

        comp = _make_component(model)
        db_session.add(comp)
        await db_session.flush()

        # Link both docs to the component
        link1 = ComponentSource(
            component_id=comp.id,
            source_document_id=doc1.id,
            extraction_context="decision context from doc1",
        )
        link2 = ComponentSource(
            component_id=comp.id,
            source_document_id=doc2.id,
            extraction_context=None,
        )
        db_session.add_all([link1, link2])
        await db_session.flush()

        comp_id = comp.id

        resp = await client.get(
            f"/api/components/{comp_id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        sources = resp.json()
        assert len(sources) == 2

        source_doc_ids = {s["id"] for s in sources}
        assert str(doc1.id) in source_doc_ids
        assert str(doc2.id) in source_doc_ids

        doc1_source = next(s for s in sources if s["id"] == str(doc1.id))
        assert doc1_source["connector_type"] == "slack"
        assert doc1_source["extraction_context"] == "decision context from doc1"
        assert doc1_source["author"] == "user@example.com"
        assert doc1_source["source_url"] == "https://slack.com/archives/C123/p1234"
        assert doc1_source["processed_at"] is None

    async def test_returns_empty_list_when_no_sources(
        self, client, workspace, db_session
    ):
        model = _make_knowledge_model(workspace)
        db_session.add(model)
        await db_session.flush()

        comp = _make_component(model)
        db_session.add(comp)
        await db_session.flush()
        comp_id = comp.id

        resp = await client.get(
            f"/api/components/{comp_id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_missing_component_returns_404(self, client, workspace, db_session):
        resp = await client.get(
            f"/api/components/{uuid4()}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_wrong_workspace_returns_404(self, client, workspace, db_session):
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()

        model = _make_knowledge_model(workspace)
        db_session.add(model)
        await db_session.flush()

        comp = _make_component(model)
        db_session.add(comp)
        await db_session.flush()

        db_session.add(
            ComponentSource(component_id=comp.id, source_document_id=doc.id)
        )
        await db_session.flush()
        other_workspace = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_workspace)
        await db_session.flush()

        resp = await client.get(
            f"/api/components/{comp.id}/sources",
            params={"workspace_id": str(other_workspace.id)},
        )
        assert resp.status_code == 404


# ── Document components ───────────────────────────────────────────


class TestDocumentComponents:
    def test_route_registered_once(self):
        routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) == "/api/source-documents/{document_id}/components"
            and "GET" in getattr(route, "methods", set())
        ]
        assert len(routes) == 1

    def _setup(self, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

    async def test_returns_components_for_document(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()

        model = _make_knowledge_model(workspace)
        db_session.add(model)
        await db_session.flush()

        comp1 = _make_component(model, name="decision:launch", value="next Tuesday")
        comp2 = _make_component(model, name="blocker:legal", value="awaiting approval")
        db_session.add_all([comp1, comp2])
        await db_session.flush()

        link1 = ComponentSource(component_id=comp1.id, source_document_id=doc.id)
        link2 = ComponentSource(component_id=comp2.id, source_document_id=doc.id)
        db_session.add_all([link1, link2])
        await db_session.flush()

        doc_id = doc.id

        resp = await client.get(
            f"/api/source-documents/{doc_id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        components = resp.json()
        assert len(components) == 2

        names = {c["name"] for c in components}
        assert "decision:launch" in names
        assert "blocker:legal" in names
        assert "created_at" not in components[0]
        assert "source_documents" not in components[0]

    async def test_document_components_include_review_history(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()

        model = _make_knowledge_model(workspace)
        db_session.add(model)
        await db_session.flush()

        component = _make_component(model, name="decision:launch", value="next Tuesday")
        db_session.add(component)
        await db_session.flush()

        review_item = ReviewItem(
            component_id=component.id,
            status="approved",
            severity="low",
            kind="review_item",
            title="Approved launch fact",
            summary="Launch timing was confirmed.",
            confidence=0.9,
        )
        db_session.add(review_item)
        await db_session.flush()
        db_session.add(
            ReviewDecision(
                review_item_id=review_item.id,
                previous_status="needs_review",
                new_status="approved",
                actor_type="operator",
                note="Approved by test operator.",
            )
        )
        db_session.add(ComponentSource(component_id=component.id, source_document_id=doc.id))
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        assert resp.json()[0]["decision_history"][0]["new_status"] == "approved"

    async def test_returns_components_for_github_engineering_document(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.GITHUB,
            status=ConnectorStatus.CONNECTED,
            config={"repositories": ["acme/context-engine"]},
        )
        db_session.add(conn)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=conn.id,
            connector_type=ConnectorType.GITHUB,
            external_id="github:acme/context-engine:pull_request:77",
            content="Decision: use the new rollout path.",
            author="octocat",
            source_url="https://github.com/acme/context-engine/pull/77",
            metadata_json={
                "repo_full_name": "acme/context-engine",
                "title": "Rollout path",
                "item_type": "pull_request",
                "number": 77,
                "source_type": "github_pull_request",
            },
        )
        db_session.add(doc)
        await db_session.flush()

        model = _make_knowledge_model(workspace)
        db_session.add(model)
        await db_session.flush()

        component = _make_component(
            model,
            name="Rollout Decision",
            value="Use the new rollout path.",
        )
        db_session.add(component)
        await db_session.flush()

        review_item = ReviewItem(
            component_id=component.id,
            status="approved",
            severity="low",
            kind="fact_update",
            title="Approved rollout decision",
            summary="Engineering approved the rollout path.",
            confidence=0.93,
        )
        db_session.add(review_item)
        await db_session.flush()
        db_session.add(
            ReviewDecision(
                review_item_id=review_item.id,
                previous_status="needs_review",
                new_status="approved",
                actor_type="operator",
                note="Approved from GitHub source.",
            )
        )
        db_session.add(ComponentSource(component_id=component.id, source_document_id=doc.id))
        await db_session.commit()

        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "Rollout Decision"
        assert body[0]["review_status"] == "approved"
        assert body[0]["decision_history"][0]["new_status"] == "approved"

    async def test_returns_empty_list_when_no_components(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        resp = await client.get(
            f"/api/source-documents/{doc_id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_missing_document_returns_404(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        resp = await client.get(
            f"/api/source-documents/{uuid4()}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_wrong_workspace_returns_404(
        self, client, workspace, db_session, monkeypatch
    ):
        self._setup(monkeypatch)
        conn = _make_slack_connector(workspace)
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn)
        db_session.add(doc)
        await db_session.flush()
        doc_id = doc.id

        resp = await client.get(
            f"/api/source-documents/{doc_id}/components",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404
