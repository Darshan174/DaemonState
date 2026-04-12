"""Tests for trust/operator backend endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy import select

from app.models.connector import Connector, ConnectorStatus
from app.models.job import SyncJob, SyncJobStatus
from app.models.knowledge import Component, ComponentSource, KnowledgeModel
from app.models.review import ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace


def _make_connector(workspace_id, connector_type=ConnectorType.SLACK):
    return Connector(
        workspace_id=workspace_id,
        connector_type=connector_type,
        status=ConnectorStatus.CONNECTED,
        config={},
    )


def _make_source_document(
    connector_id,
    connector_type,
    external_id,
    *,
    content="decision: launch",
    location="Source location",
    processed_at=None,
):
    return SourceDocument(
        connector_id=connector_id,
        connector_type=connector_type,
        external_id=external_id,
        content=content,
        author="Test Author",
        ingested_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        processed_at=processed_at,
        metadata_json={"location": location},
    )


async def _seed_component_graph(db_session, workspace):
    connector = _make_connector(workspace.id)
    db_session.add(connector)

    model = KnowledgeModel(
        workspace_id=workspace.id,
        name="Pricing Strategy",
        description="Pricing facts",
    )
    db_session.add(model)
    await db_session.flush()

    component = Component(
        model_id=model.id,
        name="Enterprise Seat Price",
        value="$600/seat",
        confidence=0.58,
    )
    db_session.add(component)
    await db_session.flush()

    slack_doc = _make_source_document(
        connector.id,
        ConnectorType.SLACK,
        "slack-1",
        location="#pricing enterprise decision",
        processed_at=datetime(2026, 3, 31, 10, 5, tzinfo=timezone.utc),
    )
    notion_doc = _make_source_document(
        connector.id,
        ConnectorType.SLACK,
        "slack-2",
        location="Pricing strategy page",
        processed_at=datetime(2026, 3, 31, 10, 6, tzinfo=timezone.utc),
    )
    db_session.add_all([slack_doc, notion_doc])
    await db_session.flush()

    db_session.add_all([
        ComponentSource(
            component_id=component.id,
            source_document_id=slack_doc.id,
            extraction_context="Extracted from pricing thread",
            extractor_name="structured_llm",
            extractor_kind="llm_structured",
            extractor_schema_version="fact_extraction.v1",
        ),
        ComponentSource(
            component_id=component.id,
            source_document_id=notion_doc.id,
            extraction_context="Extracted from pricing page",
        ),
    ])

    review_item = ReviewItem(
        component_id=component.id,
        status="needs_review",
        severity="high",
        kind="conflict",
        title="Enterprise pricing changed across Slack and Notion",
        summary="Slack and docs disagree on the current seat price.",
        confidence=0.58,
        rationale="Two authoritative sources disagree.",
        suggested_action="Choose the approved value.",
    )
    db_session.add(review_item)
    await db_session.flush()

    return {
        "connector": connector,
        "model": model,
        "component": component,
        "slack_doc": slack_doc,
        "notion_doc": notion_doc,
        "review_item": review_item,
    }


class TestReviewItems:
    async def test_list_review_items(self, client, workspace, db_session):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["id"] == str(seeded["review_item"].id)
        assert item["status"] == "needs_review"
        assert item["severity"] == "high"
        assert item["kind"] == "conflict"
        assert item["model_id"] == str(seeded["model"].id)
        assert item["model_name"] == "Pricing Strategy"
        assert item["sources"] == [
            "#pricing enterprise decision",
            "Pricing strategy page",
        ]
        assert {doc["id"] for doc in item["source_documents"]} == {
            str(seeded["slack_doc"].id),
            str(seeded["notion_doc"].id),
        }

    async def test_list_review_items_filters_by_source_document(
        self, client, workspace, db_session
    ):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "source_document_id": str(seeded["slack_doc"].id),
                "status": "needs_review",
                "severity": "high",
                "kind": "conflict",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == str(seeded["review_item"].id)

    async def test_approve_review_item(self, client, workspace, db_session):
        seeded = await _seed_component_graph(db_session, workspace)
        seeded["component"].is_stale = True
        await db_session.flush()

        resp = await client.post(
            f"/api/review-items/{seeded['review_item'].id}/approve",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert len(body["decision_history"]) == 1
        assert body["decision_history"][0]["previous_status"] == "needs_review"
        assert body["decision_history"][0]["new_status"] == "approved"
        assert body["decision_history"][0]["actor_type"] == "operator"

        await db_session.refresh(seeded["review_item"])
        await db_session.refresh(seeded["component"])
        assert seeded["review_item"].status == "approved"
        assert seeded["component"].is_stale is False

    async def test_reject_review_item(self, client, workspace, db_session):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.post(
            f"/api/review-items/{seeded['review_item'].id}/reject",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        assert len(body["decision_history"]) == 1
        assert body["decision_history"][0]["new_status"] == "rejected"

        await db_session.refresh(seeded["review_item"])
        await db_session.refresh(seeded["component"])
        assert seeded["review_item"].status == "rejected"
        assert seeded["component"].is_stale is True

    async def test_supersede_review_item(self, client, workspace, db_session):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.post(
            f"/api/review-items/{seeded['review_item'].id}/supersede",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "superseded"
        assert len(body["decision_history"]) == 1
        assert body["decision_history"][0]["new_status"] == "superseded"

        await db_session.refresh(seeded["review_item"])
        await db_session.refresh(seeded["component"])
        assert seeded["review_item"].status == "superseded"
        assert seeded["component"].valid_to is not None

    async def test_review_mutation_wrong_workspace_returns_404(
        self, client, workspace, db_session
    ):
        seeded = await _seed_component_graph(db_session, workspace)
        other_workspace = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_workspace)
        await db_session.flush()

        resp = await client.post(
            f"/api/review-items/{seeded['review_item'].id}/approve",
            params={"workspace_id": str(other_workspace.id)},
        )
        assert resp.status_code == 404

    async def test_review_mutation_missing_workspace_returns_422(
        self, client, workspace, db_session
    ):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.post(f"/api/review-items/{seeded['review_item'].id}/approve")
        assert resp.status_code == 422


class TestProvenanceEndpoints:
    async def test_component_sources(self, client, workspace, db_session):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.get(
            f"/api/components/{seeded['component'].id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert {item["label"] for item in body} == {
            "#pricing enterprise decision",
            "Pricing strategy page",
        }
        contexts = {item["extraction_context"] for item in body}
        assert "Extracted from pricing thread" in contexts
        assert "Extracted from pricing page" in contexts
        assert all(item["id"] for item in body)
        schema_versions = {item["extractor_schema_version"] for item in body}
        assert "fact_extraction.v1" in schema_versions

    async def test_component_sources_wrong_workspace_returns_404(
        self, client, workspace, db_session
    ):
        seeded = await _seed_component_graph(db_session, workspace)
        other_workspace = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_workspace)
        await db_session.flush()

        resp = await client.get(
            f"/api/components/{seeded['component'].id}/sources",
            params={"workspace_id": str(other_workspace.id)},
        )
        assert resp.status_code == 404

    async def test_source_document_components(self, client, workspace, db_session):
        seeded = await _seed_component_graph(db_session, workspace)

        resp = await client.get(
            f"/api/source-documents/{seeded['slack_doc'].id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["id"] == str(seeded["component"].id)
        assert item["model_id"] == str(seeded["model"].id)
        assert item["model_name"] == "Pricing Strategy"
        assert item["review_status"] == "needs_review"
        assert item["review_item_id"] == str(seeded["review_item"].id)
        assert item["review_summary"] == seeded["review_item"].summary
        assert item["valid_from"] is not None
        assert item["valid_to"] is None
        assert item["superseded_by"] is None
        assert item["temporal_state"] is None

    async def test_source_document_components_cross_workspace_returns_404(
        self, client, workspace, db_session
    ):
        seeded = await _seed_component_graph(db_session, workspace)
        other_workspace = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_workspace)
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{seeded['slack_doc'].id}/components",
            params={"workspace_id": str(other_workspace.id)},
        )
        assert resp.status_code == 404


class TestReprocessEndpoint:
    async def test_reprocess_queues_background_job(
        self, client, workspace, db_session, monkeypatch
    ):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        document = _make_source_document(
            connector.id,
            ConnectorType.SLACK,
            "slack-doc-1",
            processed_at=datetime(2026, 3, 31, 10, 5, tzinfo=timezone.utc),
        )
        db_session.add(document)
        await db_session.flush()

        mock_delay = MagicMock()
        mock_delay.return_value.id = "celery-reprocess-1"
        monkeypatch.setattr("app.tasks.ingestion.run_ingestion.delay", mock_delay)

        resp = await client.post(
            f"/api/source-documents/{document.id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["job_type"] == "reprocess"
        assert body["connector_id"] == str(connector.id)
        assert body["status"] == "pending"

        job = await db_session.scalar(
            select(SyncJob).where(SyncJob.connector_id == connector.id)
        )
        assert job is not None
        assert job.job_type == "reprocess"
        assert job.status == SyncJobStatus.PENDING
        assert job.result_metadata["document_id"] == str(document.id)

        await db_session.refresh(document)
        assert document.processed_at is None
        assert mock_delay.called

    async def test_reprocess_returns_409_when_job_in_progress(
        self, client, workspace, db_session
    ):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        document = _make_source_document(connector.id, ConnectorType.SLACK, "slack-doc-1")
        db_session.add(document)
        await db_session.flush()

        db_session.add(
            SyncJob(
                connector_id=connector.id,
                job_type="sync",
                status=SyncJobStatus.RUNNING,
            )
        )
        await db_session.flush()

        resp = await client.post(
            f"/api/source-documents/{document.id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_reprocess_missing_document_returns_404(self, client, workspace):
        resp = await client.post(
            f"/api/source-documents/{uuid4()}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404
