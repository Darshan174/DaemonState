"""Trust lifecycle hardening tests.

Covers:
- Repeated actions returning 409 for terminal states
- Explicit status transition validation
- Decision history ordering
- Empty result and not-found cases for provenance
- Trust-visibility invariants (is_actionable, review_state, is_safe_for_production)
- Seeded review items via ingestion pipeline
- Filter predictability and sort behavior
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy import select

from app.models.connector import Connector, ConnectorStatus
from app.models.job import SyncJob, SyncJobStatus
from app.models.knowledge import Component, ComponentSource, KnowledgeModel
from app.models.review import ReviewDecision, ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace
from app.processing.embedder import HashingEmbedder
from app.services.ingestion_service import IngestionService


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


async def _seed_review_graph(db_session, workspace, *, status="needs_review"):
    """Seed a component with a review item in a given status."""
    connector = _make_connector(workspace.id)
    db_session.add(connector)

    model = KnowledgeModel(
        workspace_id=workspace.id,
        name="Pricing",
        description="Pricing facts",
    )
    db_session.add(model)
    await db_session.flush()

    component = Component(
        model_id=model.id,
        name="Seat Price",
        value="$600/seat",
        confidence=0.55,
    )
    db_session.add(component)
    await db_session.flush()

    doc = _make_source_document(
        connector.id,
        ConnectorType.SLACK,
        "slack-price",
        location="#pricing",
        processed_at=datetime(2026, 3, 31, 10, 5, tzinfo=timezone.utc),
    )
    db_session.add(doc)
    await db_session.flush()

    db_session.add(
        ComponentSource(
            component_id=component.id,
            source_document_id=doc.id,
            extraction_context="Extracted from pricing thread",
            extractor_name="structured_llm",
            extractor_kind="llm_structured",
            extractor_schema_version="fact_extraction.v1",
        )
    )

    review_item = ReviewItem(
        component_id=component.id,
        status=status,
        severity="medium",
        kind="low_confidence",
        title="Low confidence pricing",
        summary="Needs review.",
        confidence=0.55,
    )
    db_session.add(review_item)
    await db_session.flush()

    return {
        "connector": connector,
        "model": model,
        "component": component,
        "doc": doc,
        "review_item": review_item,
    }


class TestRepeatedActionsReturn409:
    """Terminal states must reject repeated mutations with 409."""

    async def test_approve_already_approved_returns_409(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="approved")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/approve",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_reject_already_rejected_returns_409(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="rejected")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/reject",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_supersede_already_superseded_returns_409(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="superseded")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/supersede",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_approve_already_rejected_returns_409(
        self, client, workspace, db_session
    ):
        """Cannot approve a rejected item."""
        g = await _seed_review_graph(db_session, workspace, status="rejected")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/approve",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_reject_already_approved_returns_409(
        self, client, workspace, db_session
    ):
        """Cannot reject an approved item."""
        g = await _seed_review_graph(db_session, workspace, status="approved")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/reject",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_supersede_already_approved_returns_409(
        self, client, workspace, db_session
    ):
        """Cannot supersede an approved item."""
        g = await _seed_review_graph(db_session, workspace, status="approved")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/supersede",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_approve_already_superseded_returns_409(
        self, client, workspace, db_session
    ):
        """Cannot approve a superseded item."""
        g = await _seed_review_graph(db_session, workspace, status="superseded")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/approve",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409

    async def test_reject_already_superseded_returns_409(
        self, client, workspace, db_session
    ):
        """Cannot reject a superseded item."""
        g = await _seed_review_graph(db_session, workspace, status="superseded")
        resp = await client.post(
            f"/api/review-items/{g['review_item'].id}/reject",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 409


class TestDecisionHistoryOrdering:
    """Decision history must be ordered newest-first in API responses."""

    async def test_decision_history_ordered_newest_first(
        self, client, workspace, db_session
    ):
        """Decision history is ordered newest-first (created_at DESC, id DESC)."""
        g = await _seed_review_graph(db_session, workspace)

        await client.post(
            f"/api/review-items/{g['review_item'].id}/approve",
            params={"workspace_id": str(workspace.id)},
        )

        # Backdate the approved decision's created_at to guarantee ordering
        # (within the test savepoint, func.now() is the same for all decisions)
        approved_decision = await db_session.scalar(
            select(ReviewDecision)
            .where(ReviewDecision.review_item_id == g["review_item"].id)
            .where(ReviewDecision.new_status == "approved")
        )
        assert approved_decision is not None
        approved_decision.created_at = approved_decision.created_at - timedelta(hours=1)
        await db_session.flush()
        # Force the session to see the updated attribute
        from sqlalchemy.orm import attributes
        attributes.flag_modified(approved_decision, "created_at")

        # Reset to needs_review so the second action is valid
        g["review_item"].status = "needs_review"
        await db_session.flush()

        await client.post(
            f"/api/review-items/{g['review_item'].id}/reject",
            params={"workspace_id": str(workspace.id)},
        )

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        item = next(i for i in items if i["id"] == str(g["review_item"].id))
        history = item["decision_history"]
        assert len(history) == 2
        # Reject was the later mutation, so it must appear first
        assert history[0]["new_status"] == "rejected"
        assert history[0]["previous_status"] == "needs_review"
        assert history[1]["new_status"] == "approved"
        assert history[1]["previous_status"] == "needs_review"


class TestSoftDeletedProvenanceFiltered:
    """Soft-deleted source documents must not leak into review-item payloads."""

    async def test_deleted_source_excluded_from_review_item(
        self, client, workspace, db_session
    ):
        """A soft-deleted source document must not appear in review-item sources."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Del Model",
            description="For deletion tests",
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Del Fact",
            value="test value",
            confidence=0.5,
        )
        db_session.add(component)
        await db_session.flush()

        # Active document
        active_doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-active",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(active_doc)

        # Soft-deleted document
        deleted_doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-deleted",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        deleted_doc.deleted_at = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        db_session.add(deleted_doc)
        await db_session.flush()

        db_session.add_all([
            ComponentSource(
                component_id=component.id,
                source_document_id=active_doc.id,
                extraction_context="from active doc",
                extractor_name="test",
                extractor_kind="test",
                extractor_schema_version="v1",
            ),
            ComponentSource(
                component_id=component.id,
                source_document_id=deleted_doc.id,
                extraction_context="from deleted doc",
                extractor_name="test",
                extractor_kind="test",
                extractor_schema_version="v1",
            ),
        ])

        review_item = ReviewItem(
            component_id=component.id,
            status="needs_review",
            severity="medium",
            kind="low_confidence",
            title="Test",
            summary="Test summary",
            confidence=0.5,
        )
        db_session.add(review_item)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        item = items[0]
        # Only the active document should appear
        source_ids = {doc["id"] for doc in item["source_documents"]}
        assert str(active_doc.id) in source_ids
        assert str(deleted_doc.id) not in source_ids
        source_labels = set(item["sources"])
        assert "Source location" in source_labels  # active doc label

    async def test_deleted_source_excluded_from_source_document_filter(
        self, client, workspace, db_session
    ):
        """Filtering by a deleted source_document_id returns no review items."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Del2 Model",
            description="For deletion filter tests",
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Del2 Fact",
            value="test value",
            confidence=0.5,
        )
        db_session.add(component)
        await db_session.flush()

        deleted_doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-del2",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        deleted_doc.deleted_at = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        db_session.add(deleted_doc)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=deleted_doc.id,
                extraction_context="from deleted",
            )
        )

        review_item = ReviewItem(
            component_id=component.id,
            status="needs_review",
            severity="medium",
            kind="low_confidence",
            title="Test",
            summary="Test summary",
            confidence=0.5,
        )
        db_session.add(review_item)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "source_document_id": str(deleted_doc.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []


class TestProvenanceNotFoundAndEmpty:
    """Provenance endpoints must return 404 for missing resources and [] for empty."""

    async def test_component_sources_not_found_404(
        self, client, workspace
    ):
        resp = await client.get(
            f"/api/components/{uuid4()}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_source_document_components_not_found_404(
        self, client, workspace
    ):
        resp = await client.get(
            f"/api/source-documents/{uuid4()}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_component_sources_empty_for_component_without_sources(
        self, client, workspace, db_session
    ):
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Test Model",
            description="Test",
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Orphan Fact",
            value="no sources",
            confidence=0.9,
        )
        db_session.add(component)
        await db_session.flush()

        resp = await client.get(
            f"/api/components/{component.id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_source_document_components_empty_for_doc_without_components(
        self, client, workspace, db_session
    ):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        doc = _make_source_document(
            connector.id,
            ConnectorType.SLACK,
            "slack-empty",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestExtractorMetadataConsistency:
    """Extractor fields must be present and consistent across source metadata."""

    async def test_extractor_fields_propagated(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace)

        resp = await client.get(
            f"/api/components/{g['component'].id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        source = body[0]
        assert source["extractor_name"] == "structured_llm"
        assert source["extractor_kind"] == "llm_structured"
        assert source["extractor_schema_version"] == "fact_extraction.v1"
        assert source["extraction_context"] == "Extracted from pricing thread"
        assert source["connector_type"] == "slack"
        assert source["external_id"] == "slack-price"
        assert source["author"] == "Test Author"
        assert source["processed_at"] is not None

    async def test_extractor_fields_nullable_for_missing_metadata(
        self, client, workspace, db_session
    ):
        """ComponentSource without extractor metadata should return nulls."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Test Model",
            description="Test",
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Test Fact",
            value="test",
            confidence=0.9,
        )
        db_session.add(component)
        await db_session.flush()

        doc = _make_source_document(
            connector.id,
            ConnectorType.SLACK,
            "slack-minimal",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="manual link",
            )
        )
        await db_session.flush()

        resp = await client.get(
            f"/api/components/{component.id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        source = body[0]
        assert source["extractor_name"] is None
        assert source["extractor_kind"] is None
        assert source["extractor_schema_version"] is None


class TestTrustVisibilityInvariants:
    """Review state must never be ambiguous in API responses."""

    async def test_needs_review_is_actionable(self, client, workspace, db_session):
        g = await _seed_review_graph(db_session, workspace, status="needs_review")
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["is_actionable"] is True
        assert items[0]["status"] == "needs_review"

    async def test_approved_not_actionable(self, client, workspace, db_session):
        g = await _seed_review_graph(db_session, workspace, status="approved")
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["is_actionable"] is False
        assert items[0]["status"] == "approved"

    async def test_rejected_not_actionable(self, client, workspace, db_session):
        g = await _seed_review_graph(db_session, workspace, status="rejected")
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["is_actionable"] is False

    async def test_superseded_not_actionable(self, client, workspace, db_session):
        g = await _seed_review_graph(db_session, workspace, status="superseded")
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["is_actionable"] is False

    async def test_source_document_review_state_for_approved(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="approved")
        resp = await client.get(
            f"/api/source-documents/{g['doc'].id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["review_state"] == "approved"
        assert item["review_status"] == "approved"
        assert item["is_safe_for_production"] is True

    async def test_source_document_review_state_for_needs_review(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="needs_review")
        resp = await client.get(
            f"/api/source-documents/{g['doc'].id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["review_state"] == "needs_review"
        assert item["is_safe_for_production"] is False

    async def test_source_document_review_state_for_rejected(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="rejected")
        g["component"].is_stale = True
        await db_session.flush()
        resp = await client.get(
            f"/api/source-documents/{g['doc'].id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["review_state"] == "rejected"
        assert item["is_safe_for_production"] is False
        assert item["is_stale"] is True

    async def test_source_document_review_state_for_superseded(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="superseded")
        resp = await client.get(
            f"/api/source-documents/{g['doc'].id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["review_state"] == "superseded"
        assert item["is_safe_for_production"] is False


class TestFilterAndSortBehavior:
    """Review item list filters and sort must be predictable."""

    async def test_filter_by_status(self, client, workspace, db_session):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing facts",
        )
        db_session.add(model)
        await db_session.flush()

        comp1 = Component(model_id=model.id, name="Price1", value="$100", confidence=0.5)
        db_session.add(comp1)
        await db_session.flush()
        review1 = ReviewItem(
            component_id=comp1.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review1)
        await db_session.flush()

        comp2 = Component(model_id=model.id, name="Price2", value="$200", confidence=0.5)
        db_session.add(comp2)
        await db_session.flush()
        review2 = ReviewItem(
            component_id=comp2.id, status="approved", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review2)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "status": "needs_review"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(review1.id)

    async def test_filter_by_severity(self, client, workspace, db_session):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Filter Model",
            description="For filter tests",
        )
        db_session.add(model)
        await db_session.flush()

        comp1 = Component(model_id=model.id, name="High Sev", value="v1", confidence=0.5)
        db_session.add(comp1)
        await db_session.flush()
        review1 = ReviewItem(
            component_id=comp1.id, status="needs_review", severity="high",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review1)
        await db_session.flush()

        comp2 = Component(model_id=model.id, name="Low Sev", value="v2", confidence=0.4)
        db_session.add(comp2)
        await db_session.flush()
        review2 = ReviewItem(
            component_id=comp2.id, status="needs_review", severity="low",
            kind="low_confidence", title="t", summary="s", confidence=0.4,
        )
        db_session.add(review2)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "severity": "high"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(review1.id)

    async def test_filter_by_kind(self, client, workspace, db_session):
        g = await _seed_review_graph(db_session, workspace, status="needs_review")
        g["review_item"].kind = "conflict"
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "kind": "conflict"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(g["review_item"].id)

    async def test_list_review_items_search_by_title(
        self, client, workspace, db_session
    ):
        """Search filter matches review item title (case-insensitive)."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="Search Model", description="Search"
        )
        db_session.add(model)
        await db_session.flush()

        comp1 = Component(model_id=model.id, name="Price A", value="$100", confidence=0.5)
        db_session.add(comp1)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp1.id, status="needs_review", severity="high",
                kind="conflict", title="Pricing conflict detected",
                summary="Sources disagree on pricing", confidence=0.5,
            )
        )
        await db_session.flush()

        comp2 = Component(model_id=model.id, name="Roadmap B", value="Q3", confidence=0.5)
        db_session.add(comp2)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp2.id, status="needs_review", severity="low",
                kind="low_confidence", title="Low confidence roadmap fact",
                summary="Uncertain roadmap data", confidence=0.5,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "pricing"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Pricing conflict detected"

    async def test_list_review_items_search_by_model_name(
        self, client, workspace, db_session
    ):
        """Search filter matches model name."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="UniqueModelName", description="Unique"
        )
        db_session.add(model)
        await db_session.flush()

        comp = Component(model_id=model.id, name="Fact X", value="v", confidence=0.5)
        db_session.add(comp)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp.id, status="needs_review", severity="medium",
                kind="low_confidence", title="Some fact",
                summary="Some summary", confidence=0.5,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "UniqueModelName"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert items[0]["model_name"] == "UniqueModelName"

    async def test_list_review_items_search_no_matches(self, client, workspace, db_session):
        """Search that matches nothing returns empty items."""
        await _seed_review_graph(db_session, workspace)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "zzzznope"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_review_items_search_combined_with_filters(
        self, client, workspace, db_session
    ):
        """Search combined with status and kind filters narrows results."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="ComboSearch", description="Combo"
        )
        db_session.add(model)
        await db_session.flush()

        comp1 = Component(model_id=model.id, name="Fact A", value="a", confidence=0.3)
        db_session.add(comp1)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp1.id, status="needs_review", severity="high",
                kind="low_confidence", title="Low confidence pricing",
                summary="Pricing needs review", confidence=0.3,
            )
        )
        await db_session.flush()

        comp2 = Component(model_id=model.id, name="Fact B", value="b", confidence=0.9)
        db_session.add(comp2)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp2.id, status="approved", severity="low",
                kind="conflict", title="Resolved conflict",
                summary="Was a conflict", confidence=0.9,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "pricing", "status": "needs_review"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert "Low confidence pricing" in items[0]["title"]

    async def test_list_ordered_by_updated_desc(
        self, client, workspace, db_session
    ):
        """Newer review items should appear first in the list."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Order Model",
            description="For ordering tests",
        )
        db_session.add(model)
        await db_session.flush()

        comp1 = Component(model_id=model.id, name="First", value="v1", confidence=0.5)
        db_session.add(comp1)
        await db_session.flush()
        review1 = ReviewItem(
            component_id=comp1.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review1)
        await db_session.flush()

        comp2 = Component(model_id=model.id, name="Second", value="v2", confidence=0.5)
        db_session.add(comp2)
        await db_session.flush()
        review2 = ReviewItem(
            component_id=comp2.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review2)
        await db_session.flush()

        # Force review1 to have an earlier updated_at to guarantee ordering
        review1.updated_at = review1.updated_at - timedelta(hours=1)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 2
        # review2 has a later updated_at, so it should come first
        assert items[0]["id"] == str(review2.id)
        assert items[1]["id"] == str(review1.id)


class TestWorkspaceScopeReviewItems:
    """Review items must be strictly scoped to workspace."""

    async def test_review_item_not_visible_in_other_workspace(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace, status="needs_review")

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(other_ws.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 0

    async def test_list_review_items_missing_workspace_422(
        self, client, workspace, db_session
    ):
        await _seed_review_graph(db_session, workspace)
        resp = await client.get("/api/review-items")
        assert resp.status_code == 422


class TestIngestionSeedCreatesReviewItems:
    """Verify that ingestion pipeline creates review items that show up in trust APIs."""

    async def test_low_confidence_ingestion_creates_review(
        self, client, workspace, db_session
    ):
        """Processing a low-confidence doc creates a review item visible via API."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:lowconf",
            content="This is just a thread\n\nThread replies:\nBob: agreed",
            author="Alice",
            metadata_json={"channel_name": "ops", "reply_count": 1},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session, embedder=HashingEmbedder())
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
        )

        # Find the discussion component that was created
        comp = await db_session.scalar(
            select(Component).where(Component.name == "Discussion in #ops")
        )
        assert comp is not None

        review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == comp.id)
        )
        assert review is not None
        assert review.status == "needs_review"

        # Verify it shows up in the review items API
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        review_ids = {item["id"] for item in body["items"]}
        assert str(review.id) in review_ids

    async def test_ingestion_review_item_has_system_decision(
        self, client, workspace, db_session
    ):
        """Ingestion-created review items have a 'system' actor decision."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="C1:sysdec",
            content="This is a low-quality thread\n\nReplies:\nBob: yeah",
            author="Alice",
            metadata_json={"channel_name": "random", "reply_count": 2},
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session, embedder=HashingEmbedder())
        await svc.process_connector_documents(
            workspace_id=workspace.id,
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
        )

        comp = await db_session.scalar(
            select(Component).where(Component.name == "Discussion in #random")
        )
        assert comp is not None

        review = await db_session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == comp.id)
        )
        assert review is not None

        decisions = list(await db_session.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.review_item_id == review.id)
            .order_by(ReviewDecision.created_at.asc())
        ))
        assert len(decisions) >= 1
        assert decisions[0].actor_type == "system"
        assert decisions[0].new_status == "needs_review"


class TestStatusFieldTypedCorrectly:
    """Review item status and related fields should use typed literals."""

    async def test_review_item_read_status_is_typed(self, client, workspace, db_session):
        g = await _seed_review_graph(db_session, workspace)
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        item = body["items"][0]
        # These should be valid typed values, not None or empty
        assert item["status"] in {"needs_review", "approved", "rejected", "superseded"}
        assert item["severity"] in {"high", "medium", "low"}
        assert item["kind"] in {
            "review_item", "conflict", "low_confidence",
            "fact_update", "superseded_fact",
        }

    async def test_source_document_component_review_state_is_typed(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace)
        resp = await client.get(
            f"/api/source-documents/{g['doc'].id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        item = body[0]
        assert item["review_state"] in {
            "needs_review", "approved", "rejected", "superseded", "unreviewed",
        }


class TestReviewEdgeCases:
    """Hardened edge cases for review mutations, missing resources, and error handling."""

    async def test_approve_nonexistent_review_item_returns_404(
        self, client, workspace
    ):
        resp = await client.post(
            f"/api/review-items/{uuid4()}/approve",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_reject_nonexistent_review_item_returns_404(
        self, client, workspace
    ):
        resp = await client.post(
            f"/api/review-items/{uuid4()}/reject",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_supersede_nonexistent_review_item_returns_404(
        self, client, workspace
    ):
        resp = await client.post(
            f"/api/review-items/{uuid4()}/supersede",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_list_review_items_nonexistent_source_document_returns_empty(
        self, client, workspace
    ):
        """Filtering by a source_document_id that doesn't exist returns empty items."""
        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "source_document_id": str(uuid4()),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_list_review_items_nonexistent_model_returns_empty(
        self, client, workspace
    ):
        """Filtering by a model_id that doesn't exist returns empty items."""
        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "model_id": str(uuid4()),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_list_review_items_filter_by_model_id(
        self, client, workspace, db_session
    ):
        """model_id filter returns only items for that model."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model_a = KnowledgeModel(
            workspace_id=workspace.id, name="Model A", description="A"
        )
        db_session.add(model_a)
        await db_session.flush()

        comp_a = Component(model_id=model_a.id, name="Fact A", value="a", confidence=0.5)
        db_session.add(comp_a)
        await db_session.flush()

        review_a = ReviewItem(
            component_id=comp_a.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review_a)
        await db_session.flush()

        model_b = KnowledgeModel(
            workspace_id=workspace.id, name="Model B", description="B"
        )
        db_session.add(model_b)
        await db_session.flush()

        comp_b = Component(model_id=model_b.id, name="Fact B", value="b", confidence=0.5)
        db_session.add(comp_b)
        await db_session.flush()

        review_b = ReviewItem(
            component_id=comp_b.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review_b)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "model_id": str(model_a.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(review_a.id)

    async def test_source_document_deleted_returns_404_for_components(
        self, client, workspace, db_session
    ):
        """Accessing a soft-deleted source document returns 404."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-deleted-del",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        doc.deleted_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_source_document_deleted_returns_404_for_reprocess(
        self, client, workspace, db_session, monkeypatch
    ):
        """Reprocessing a soft-deleted source document returns 404."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-deleted-rep",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        doc.deleted_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        db_session.add(doc)
        await db_session.flush()

        mock_delay = MagicMock()
        mock_delay.return_value.id = "celery-task-id"
        monkeypatch.setattr("app.tasks.ingestion.run_ingestion.delay", mock_delay)

        resp = await client.post(
            f"/api/source-documents/{doc.id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404


class TestUnreviewedComponentDrilldown:
    """Source-document drilldowns for components with no review items."""

    async def test_source_document_with_unreviewed_component(
        self, client, workspace, db_session
    ):
        """A component with no review item should still appear in source-documents/components."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Unreviewed Model",
            description="For unreviewed tests",
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Unreviewed Fact",
            value="no review needed",
            confidence=0.95,
        )
        db_session.add(component)
        await db_session.flush()

        doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-unreviewed",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="from source",
                extractor_name="test",
                extractor_kind="test",
                extractor_schema_version="v1",
            )
        )
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        item = body[0]
        assert item["id"] == str(component.id)
        assert item["review_status"] is None
        assert item["review_item_id"] is None
        assert item["review_state"] == "unreviewed"
        assert item["is_safe_for_production"] is False
        assert item["is_stale"] is False
        assert item["decision_history"] == []
        assert item["temporal_state"] is None

    async def test_source_document_with_mixed_reviewed_and_unreviewed(
        self, client, workspace, db_session
    ):
        """A document with both reviewed and unreviewed components."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Mixed Model",
            description="For mixed tests",
        )
        db_session.add(model)
        await db_session.flush()

        # Reviewed component
        comp_reviewed = Component(
            model_id=model.id, name="Reviewed Fact", value="v1", confidence=0.5,
        )
        db_session.add(comp_reviewed)
        await db_session.flush()

        review = ReviewItem(
            component_id=comp_reviewed.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review)
        await db_session.flush()

        # Unreviewed component
        comp_unreviewed = Component(
            model_id=model.id, name="Unreviewed Fact", value="v2", confidence=0.95,
        )
        db_session.add(comp_unreviewed)
        await db_session.flush()

        doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-mixed",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        db_session.add_all([
            ComponentSource(
                component_id=comp_reviewed.id, source_document_id=doc.id,
                extraction_context="reviewed source",
            ),
            ComponentSource(
                component_id=comp_unreviewed.id, source_document_id=doc.id,
                extraction_context="unreviewed source",
            ),
        ])
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # Find each by id
        by_id = {item["id"]: item for item in body}
        reviewed = by_id[str(comp_reviewed.id)]
        assert reviewed["review_state"] == "needs_review"
        assert reviewed["is_safe_for_production"] is False
        unreviewed = by_id[str(comp_unreviewed.id)]
        assert unreviewed["review_state"] == "unreviewed"
        assert unreviewed["is_safe_for_production"] is False


class TestCrossWorkspaceSafety:
    """Ensure components, source documents, and reviews cannot leak across workspaces."""

    async def test_component_sources_cross_workspace_404(
        self, client, workspace, db_session
    ):
        """A component from workspace A cannot be accessed via workspace B."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id, name="WS Model", description="WS"
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id, name="WS Fact", value="v", confidence=0.9,
        )
        db_session.add(component)
        await db_session.flush()

        doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-ws",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id, source_document_id=doc.id,
                extraction_context="ws source",
            )
        )
        await db_session.flush()

        other_ws = Workspace(id=uuid4(), name="Other WS")
        db_session.add(other_ws)
        await db_session.flush()

        resp = await client.get(
            f"/api/components/{component.id}/sources",
            params={"workspace_id": str(other_ws.id)},
        )
        assert resp.status_code == 404

    async def test_source_document_components_cross_workspace_empty(
        self, client, workspace, db_session
    ):
        """A source document from workspace A should not return components via workspace B."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id, name="WS Model", description="WS"
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id, name="WS Fact", value="v", confidence=0.9,
        )
        db_session.add(component)
        await db_session.flush()

        doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-ws-cross",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id, source_document_id=doc.id,
                extraction_context="ws cross",
            )
        )
        await db_session.flush()

        other_ws = Workspace(id=uuid4(), name="Other WS")
        db_session.add(other_ws)
        await db_session.flush()

        # The document belongs to workspace A, so workspace B gets 404
        resp = await client.get(
            f"/api/source-documents/{doc.id}/components",
            params={"workspace_id": str(other_ws.id)},
        )
        assert resp.status_code == 404


class TestReviewPagination:
    """Paginated list_review_items endpoint behavior."""

    async def test_default_no_limit_returns_all(
        self, client, workspace, db_session
    ):
        """Without explicit limit, all items are returned."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="Pag Model", description="Pag"
        )
        db_session.add(model)
        await db_session.flush()

        for i in range(3):
            comp = Component(
                model_id=model.id, name=f"Pag Fact {i}", value=f"v{i}", confidence=0.5,
            )
            db_session.add(comp)
            await db_session.flush()
            db_session.add(
                ReviewItem(
                    component_id=comp.id, status="needs_review", severity="medium",
                    kind="low_confidence", title="t", summary="s", confidence=0.5,
                )
            )
            await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["limit"] is None
        assert body["offset"] is None
        assert body["has_more"] is False
        assert body["page_size"] == 3
        assert len(body["items"]) == 3

    async def test_pagination_with_limit_and_offset(
        self, client, workspace, db_session
    ):
        """Limit and offset correctly paginate results."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="Pag2 Model", description="Pag2"
        )
        db_session.add(model)
        await db_session.flush()

        review_ids = []
        for i in range(5):
            comp = Component(
                model_id=model.id, name=f"Pag2 Fact {i}", value=f"v{i}", confidence=0.5,
            )
            db_session.add(comp)
            await db_session.flush()
            review = ReviewItem(
                component_id=comp.id, status="needs_review", severity="medium",
                kind="low_confidence", title="t", summary="s", confidence=0.5,
            )
            db_session.add(review)
            await db_session.flush()
            review_ids.append(review.id)

        # First page: limit=2
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 2, "offset": 0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert body["has_more"] is True
        assert len(body["items"]) == 2

        # Second page: offset=2
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 2, "offset": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["offset"] == 2
        assert body["has_more"] is True
        assert len(body["items"]) == 2

        # Last page: offset=4
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 2, "offset": 4},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["offset"] == 4
        assert body["has_more"] is False
        assert len(body["items"]) == 1

    async def test_pagination_beyond_results_returns_empty(self, client, workspace, db_session):
        """Offset beyond total returns empty items list."""
        g = await _seed_review_graph(db_session, workspace)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 10, "offset": 999},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"] == []
        assert body["has_more"] is False


class TestReviewSummary:
    """Review state summary endpoint for operator dashboards."""

    async def test_summary_returns_zero_counts_for_empty_workspace(
        self, client, workspace
    ):
        resp = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["actionable"] == 0
        assert body["by_status"]["needs_review"] == 0
        assert body["by_severity"]["high"] == 0
        assert body["by_kind"]["conflict"] == 0

    async def test_summary_returns_correct_counts(
        self, client, workspace, db_session
    ):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="Sum Model", description="Sum"
        )
        db_session.add(model)
        await db_session.flush()

        # Create items in different states
        for i, status in enumerate(["needs_review", "needs_review", "approved", "rejected"]):
            comp = Component(
                model_id=model.id, name=f"Sum Fact {i}", value=f"v{i}", confidence=0.5,
            )
            db_session.add(comp)
            await db_session.flush()
            db_session.add(
                ReviewItem(
                    component_id=comp.id, status=status,
                    severity="high" if i < 2 else "low",
                    kind="conflict" if i == 0 else "low_confidence",
                    title="t", summary="s", confidence=0.5,
                )
            )
            await db_session.flush()

        resp = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        assert body["actionable"] == 2
        assert body["by_status"]["needs_review"] == 2
        assert body["by_status"]["approved"] == 1
        assert body["by_status"]["rejected"] == 1
        assert body["by_severity"]["high"] == 2
        assert body["by_severity"]["low"] == 2
        assert body["by_kind"]["conflict"] == 1
        assert body["by_kind"]["low_confidence"] == 3

    async def test_summary_missing_workspace_returns_404(
        self, client, workspace
    ):
        resp = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404

    async def test_summary_workspace_cross_check(
        self, client, workspace, db_session
    ):
        """Items in workspace A should not affect workspace B's summary."""
        await _seed_review_graph(db_session, workspace)

        other_ws = Workspace(id=uuid4(), name="Other WS")
        db_session.add(other_ws)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(other_ws.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0


class TestGetSingleReviewItem:
    """GET /review-items/{id} single-item endpoint."""

    async def test_get_review_item_returns_full_payload(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace)
        resp = await client.get(
            f"/api/review-items/{g['review_item'].id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(g["review_item"].id)
        assert body["status"] == "needs_review"
        assert body["is_actionable"] is True

    async def test_get_review_item_nonexistent_returns_404(
        self, client, workspace
    ):
        resp = await client.get(
            f"/api/review-items/{uuid4()}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_get_review_item_cross_workspace_returns_404(
        self, client, workspace, db_session
    ):
        g = await _seed_review_graph(db_session, workspace)
        other_ws = Workspace(id=uuid4(), name="Other WS")
        db_session.add(other_ws)
        await db_session.flush()

        resp = await client.get(
            f"/api/review-items/{g['review_item'].id}",
            params={"workspace_id": str(other_ws.id)},
        )
        assert resp.status_code == 404


class TestReviewItemSort:
    """Sort parameter behavior on list_review_items."""

    async def test_sort_by_updated_at_desc(self, client, workspace, db_session):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="Sort Model", description="Sort"
        )
        db_session.add(model)
        await db_session.flush()

        comp1 = Component(model_id=model.id, name="Sort1", value="v1", confidence=0.5)
        db_session.add(comp1)
        await db_session.flush()
        review1 = ReviewItem(
            component_id=comp1.id, status="needs_review", severity="medium",
            kind="low_confidence", title="t", summary="s", confidence=0.5,
        )
        db_session.add(review1)
        await db_session.flush()

        comp2 = Component(model_id=model.id, name="Sort2", value="v2", confidence=0.4)
        db_session.add(comp2)
        await db_session.flush()
        review2 = ReviewItem(
            component_id=comp2.id, status="needs_review", severity="high",
            kind="low_confidence", title="t", summary="s", confidence=0.4,
        )
        db_session.add(review2)
        await db_session.flush()

        # Force distinct updated_at
        review1.updated_at = review1.updated_at - timedelta(hours=1)
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "sort": "updated_at", "sort_dir": "desc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 2
        assert items[0]["id"] == str(review2.id)
        assert items[1]["id"] == str(review1.id)

    async def test_sort_by_confidence_asc(self, client, workspace, db_session):
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="SortC Model", description="SortC"
        )
        db_session.add(model)
        await db_session.flush()

        comp_lo = Component(model_id=model.id, name="SortC Lo", value="lo", confidence=0.3)
        db_session.add(comp_lo)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp_lo.id, status="needs_review", severity="high",
                kind="low_confidence", title="t", summary="s", confidence=0.3,
            )
        )
        await db_session.flush()

        comp_hi = Component(model_id=model.id, name="SortC Hi", value="hi", confidence=0.8)
        db_session.add(comp_hi)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=comp_hi.id, status="needs_review", severity="low",
                kind="low_confidence", title="t", summary="s", confidence=0.8,
            )
        )
        await db_session.flush()

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "sort": "confidence", "sort_dir": "asc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 2
        assert items[0]["confidence"] == 0.3
        assert items[1]["confidence"] == 0.8

    async def test_invalid_sort_param_returns_422(self, client, workspace):
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "sort": "invalid"},
        )
        assert resp.status_code == 422

    async def test_sort_by_severity_uses_operational_priority(
        self, client, workspace, db_session
    ):
        """severity sort orders high > medium > low, not alphabetically."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        model = KnowledgeModel(
            workspace_id=workspace.id, name="SevSort Model", description="SevSort"
        )
        db_session.add(model)
        await db_session.flush()

        severities = ["low", "high", "medium"]
        for i, sev in enumerate(severities):
            comp = Component(
                model_id=model.id, name=f"SevSort {sev}", value=f"v{i}", confidence=0.5,
            )
            db_session.add(comp)
            await db_session.flush()
            db_session.add(
                ReviewItem(
                    component_id=comp.id, status="needs_review", severity=sev,
                    kind="low_confidence", title="t", summary="s", confidence=0.5,
                )
            )
            await db_session.flush()

        # Descending: high first, then medium, then low
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "sort": "severity", "sort_dir": "desc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 3
        assert items[0]["severity"] == "high"
        assert items[1]["severity"] == "medium"
        assert items[2]["severity"] == "low"

        # Ascending: low first, then medium, then high
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "sort": "severity", "sort_dir": "asc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 3
        assert items[0]["severity"] == "low"
        assert items[1]["severity"] == "medium"
        assert items[2]["severity"] == "high"


class TestReprocessLifecycle:
    """Reprocess endpoint edge cases and lifecycle."""

    async def test_reprocess_completed_job_allows_new_job(
        self, client, workspace, db_session, monkeypatch
    ):
        """A connector with a completed job can still accept a new reprocess job."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        db_session.add(
            SyncJob(
                connector_id=connector.id, job_type="sync",
                status=SyncJobStatus.COMPLETED,
            )
        )
        await db_session.flush()

        document = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-reproc-done",
            processed_at=datetime(2026, 3, 31, 10, 5, tzinfo=timezone.utc),
        )
        db_session.add(document)
        await db_session.flush()

        mock_delay = MagicMock()
        mock_delay.return_value.id = "celery-new-reproc"
        monkeypatch.setattr("app.tasks.ingestion.run_ingestion.delay", mock_delay)

        resp = await client.post(
            f"/api/source-documents/{document.id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 202

    async def test_reprocess_failed_job_allows_new_job(
        self, client, workspace, db_session, monkeypatch
    ):
        """A connector with a failed job can accept a new reprocess job."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)
        await db_session.flush()

        db_session.add(
            SyncJob(
                connector_id=connector.id, job_type="sync",
                status=SyncJobStatus.FAILED,
            )
        )
        await db_session.flush()

        document = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-reproc-fail",
            processed_at=datetime(2026, 3, 31, 10, 5, tzinfo=timezone.utc),
        )
        db_session.add(document)
        await db_session.flush()

        mock_delay = MagicMock()
        mock_delay.return_value.id = "celery-new-reproc-fail"
        monkeypatch.setattr("app.tasks.ingestion.run_ingestion.delay", mock_delay)

        resp = await client.post(
            f"/api/source-documents/{document.id}/reprocess",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 202


class TestSoftDeletedProvenanceReject:
    """Additional soft-deletion edge cases."""

    async def test_list_component_sources_excludes_deleted(
        self, client, workspace, db_session
    ):
        """Component sources endpoint must exclude soft-deleted documents."""
        connector = _make_connector(workspace.id)
        db_session.add(connector)

        model = KnowledgeModel(
            workspace_id=workspace.id, name="CsDel Model", description="CsDel"
        )
        db_session.add(model)
        await db_session.flush()

        component = Component(
            model_id=model.id, name="CsDel Fact", value="v", confidence=0.9,
        )
        db_session.add(component)
        await db_session.flush()

        active_doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-csdel-active",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        db_session.add(active_doc)

        deleted_doc = _make_source_document(
            connector.id, ConnectorType.SLACK, "slack-csdel-deleted",
            processed_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        )
        deleted_doc.deleted_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        db_session.add(deleted_doc)
        await db_session.flush()

        db_session.add_all([
            ComponentSource(
                component_id=component.id, source_document_id=active_doc.id,
                extraction_context="active", extractor_name="test", extractor_kind="test",
                extractor_schema_version="v1",
            ),
            ComponentSource(
                component_id=component.id, source_document_id=deleted_doc.id,
                extraction_context="deleted", extractor_name="test", extractor_kind="test",
                extractor_schema_version="v1",
            ),
        ])
        await db_session.flush()

        resp = await client.get(
            f"/api/components/{component.id}/sources",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["external_id"] == "slack-csdel-active"
