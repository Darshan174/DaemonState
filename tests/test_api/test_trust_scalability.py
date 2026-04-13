"""Scalability and product-facing tests for the trust/review API.

Covers:
- Search functionality (title, summary, model name)
- Pagination over 100+ items with predictable metadata
- Severity sort priority (high > medium > low)
- Deep-link filter combinations (search + status + severity + source + model)
- Cross-workspace safety under search/paging paths
- Default limit enforcement (no silent truncation)
- Summary endpoint with filters
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models.knowledge import Component, ComponentSource, KnowledgeModel
from app.models.review import ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace


def _make_source_document(connector_id, connector_type, external_id, *, location="Source"):
    return SourceDocument(
        connector_id=connector_id,
        connector_type=connector_type,
        external_id=external_id,
        content="test content",
        author="Test Author",
        ingested_at=datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc),
        processed_at=datetime(2026, 3, 31, 10, 5, tzinfo=timezone.utc),
        metadata_json={"location": location},
    )


async def _seed_workspace_graph(db_session, workspace, *, connector, doc_count=1):
    """Seed a workspace with a model, components, docs, and review items.

    Returns a dict with all created objects for assertion use.
    """
    from app.models.connector import Connector, ConnectorStatus

    db_session.add(connector)

    model = KnowledgeModel(
        workspace_id=workspace.id,
        name="Test Model",
        description="Test model for scalability tests",
    )
    db_session.add(model)
    await db_session.flush()

    documents = []
    review_items = []
    for i in range(doc_count):
        doc = _make_source_document(
            connector.id,
            ConnectorType.SLACK,
            f"doc-{i}",
            location=f"Source {i}",
        )
        db_session.add(doc)
        documents.append(doc)

    await db_session.flush()

    for i, doc in enumerate(documents):
        component = Component(
            model_id=model.id,
            name=f"Component {i:03d}",
            value=f"value-{i}",
            confidence=0.5 + (i % 50) / 100,
        )
        db_session.add(component)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context=f"Extracted from source {i}",
            )
        )

        severity_cycle = ["high", "medium", "low"][i % 3]
        status_cycle = ["needs_review", "approved", "rejected", "superseded"][i % 4]

        review_item = ReviewItem(
            component_id=component.id,
            status=status_cycle,
            severity=severity_cycle,
            kind="review_item",
            title=f"Review item {i}: {'critical' if severity_cycle == 'high' else 'minor'} issue",
            summary=f"Summary for item {i} about pricing and strategy",
            confidence=component.confidence,
            rationale=f"Rationale for item {i}",
        )
        db_session.add(review_item)
        review_items.append(review_item)

    await db_session.flush()

    return {
        "connector": connector,
        "model": model,
        "documents": documents,
        "review_items": review_items,
    }


# ===========================================================================
# Search tests
# ===========================================================================


class TestSearchFunctionality:
    """Verify that the ?search= param works end-to-end across title, summary, and model name."""

    async def test_search_by_title(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        seeded = await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=3)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "critical"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Items with "critical" in title (severity=high items)
        assert all("critical" in item["title"].lower() for item in body["items"])

    async def test_search_by_summary(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=3)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "pricing"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # All items have "pricing" in summary
        assert body["total"] > 0
        assert all("pricing" in item["summary"].lower() for item in body["items"])

    async def test_search_by_model_name(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        seeded = await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=3)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "test model"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should match all items via model name
        assert body["total"] == 3

    async def test_search_no_matches_returns_empty(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=3)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "nonexistent-xyz"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_search_is_case_insensitive(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=3)

        resp_lower = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "critical"},
        )
        resp_upper = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "CRITICAL"},
        )
        assert resp_lower.status_code == 200
        assert resp_upper.status_code == 200
        assert resp_lower.json()["total"] == resp_upper.json()["total"]


# ===========================================================================
# Pagination over 100+ items
# ===========================================================================


class TestPaginationOverLargeQueues:
    """Verify that pagination works correctly with 100+ items and metadata is accurate."""

    async def test_default_limit_is_50(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=75)

        # No limit specified — should use default of 50
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 75
        assert len(body["items"]) == 50  # default limit
        assert body["has_more"] is True

    async def test_pagination_page_2(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=120)

        # Page 1
        resp1 = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 50, "offset": 0},
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert len(body1["items"]) == 50
        assert body1["has_more"] is True
        assert body1["page"] == 1
        assert body1["total_pages"] == 3  # ceil(120/50)

        # Page 2
        resp2 = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 50, "offset": 50},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["items"]) == 50
        assert body2["has_more"] is True
        assert body2["page"] == 2

        # Page 3 (last page)
        resp3 = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 50, "offset": 100},
        )
        assert resp3.status_code == 200
        body3 = resp3.json()
        assert len(body3["items"]) == 20
        assert body3["has_more"] is False
        assert body3["page"] == 3

    async def test_no_duplicate_or_missing_items_across_pages(self, client, workspace, db_session):
        """All items should be retrievable exactly once across all pages."""
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=105)

        all_ids = set()
        offset = 0
        limit = 20
        while True:
            resp = await client.get(
                "/api/review-items",
                params={"workspace_id": str(workspace.id), "limit": limit, "offset": offset},
            )
            assert resp.status_code == 200
            body = resp.json()
            for item in body["items"]:
                assert item["id"] not in all_ids, f"Duplicate item {item['id']} on page {offset // limit + 1}"
                all_ids.add(item["id"])
            if not body["has_more"]:
                break
            offset += limit

        assert len(all_ids) == 105

    async def test_pagination_metadata_page_and_total_pages(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=10)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 3, "offset": 0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 10
        assert body["limit"] == 3
        assert body["offset"] == 0
        assert body["page"] == 1
        assert body["total_pages"] == 4  # ceil(10/3)
        assert body["page_size"] == 3
        assert body["has_more"] is True

    async def test_last_page_pagination_metadata(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=10)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 3, "offset": 9},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 4
        assert body["page_size"] == 1
        assert body["has_more"] is False


# ===========================================================================
# Severity sort priority
# ===========================================================================


class TestSeveritySortPriority:
    """Verify that severity sorting uses operational priority (high > medium > low), not lexical."""

    async def test_severity_sort_desc_puts_high_first(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=9)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "sort": "severity",
                "sort_dir": "desc",
                "limit": 100,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        severities = [item["severity"] for item in body["items"]]
        # Verify ordering: all "high" before "medium" before "low"
        seen_medium = False
        seen_low = False
        for s in severities:
            if s == "medium":
                seen_medium = True
            if s == "low":
                seen_low = True
            if s == "high":
                assert not seen_medium, f"Found 'high' after 'medium': {severities}"
                assert not seen_low, f"Found 'high' after 'low': {severities}"
            if s == "medium":
                assert not seen_low, f"Found 'medium' after 'low': {severities}"

    async def test_severity_sort_asc_puts_low_first(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=9)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "sort": "severity",
                "sort_dir": "asc",
                "limit": 100,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        severities = [item["severity"] for item in body["items"]]
        # Verify ordering: all "low" before "medium" before "high"
        seen_medium = False
        seen_high = False
        for s in severities:
            if s == "medium":
                seen_medium = True
            if s == "high":
                seen_high = True
            if s == "low":
                assert not seen_medium, f"Found 'low' after 'medium': {severities}"
                assert not seen_high, f"Found 'low' after 'high': {severities}"
            if s == "medium":
                assert not seen_high, f"Found 'medium' after 'high': {severities}"

    async def test_severity_sort_is_stable_with_tiebreaker(self, client, workspace, db_session):
        """Items with same severity should be ordered by id (deterministic)."""
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=30)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "sort": "severity",
                "sort_dir": "desc",
                "limit": 100,
            },
        )
        assert resp.status_code == 200
        body = resp.json()

        # Group by severity and verify ids are sorted within each group
        from itertools import groupby

        for severity, group in groupby(body["items"], key=lambda x: x["severity"]):
            ids = [item["id"] for item in group]
            # IDs within same severity should be sorted (desc by default)
            assert ids == sorted(ids, reverse=True), f"IDs not sorted for severity {severity}: {ids}"


# ===========================================================================
# Deep-link filter combinations
# ===========================================================================


class TestDeepLinkFilterCombinations:
    """Verify that combining multiple filter params works correctly."""

    async def test_search_plus_status_filter(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=12)

        # Search for "critical" (high severity items) + status=needs_review
        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "search": "critical",
                "status": "needs_review",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for item in body["items"]:
            assert "critical" in item["title"].lower()
            assert item["status"] == "needs_review"

    async def test_search_plus_severity_filter(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=12)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "search": "pricing",
                "severity": "high",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for item in body["items"]:
            assert "pricing" in item["summary"].lower()
            assert item["severity"] == "high"

    async def test_search_plus_status_plus_severity(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=12)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "search": "issue",
                "status": "needs_review",
                "severity": "high",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for item in body["items"]:
            assert "issue" in item["title"].lower()
            assert item["status"] == "needs_review"
            assert item["severity"] == "high"

    async def test_source_document_filter_plus_search(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        seeded = await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=6)

        # Filter by specific source document + search
        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "source_document_id": str(seeded["documents"][0].id),
                "search": "issue",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should match items from the specific document that also match search
        assert body["total"] >= 0
        for item in body["items"]:
            assert "issue" in item["title"].lower()

    async def test_model_filter_plus_search(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        seeded = await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=6)

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "model_id": str(seeded["model"].id),
                "search": "critical",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for item in body["items"]:
            assert item["model_id"] == str(seeded["model"].id)
            assert "critical" in item["title"].lower()

    async def test_summary_endpoint_with_filters(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=12)

        # Unfiltered summary
        resp_unfiltered = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp_unfiltered.status_code == 200
        unfiltered = resp_unfiltered.json()

        # Filtered summary (status=needs_review)
        resp_filtered = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(workspace.id), "status": "needs_review"},
        )
        assert resp_filtered.status_code == 200
        filtered = resp_filtered.json()

        # Filtered should have fewer or equal total
        assert filtered["total"] <= unfiltered["total"]
        # Filtered should only have needs_review items
        assert filtered["by_status"]["approved"] == 0
        assert filtered["by_status"]["rejected"] == 0
        assert filtered["by_status"]["superseded"] == 0

    async def test_summary_endpoint_with_search(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=12)

        resp = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(workspace.id), "search": "critical"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Only high severity items have "critical" in title
        assert body["by_severity"]["medium"] == 0
        assert body["by_severity"]["low"] == 0


# ===========================================================================
# Cross-workspace safety
# ===========================================================================


class TestCrossWorkspaceSafety:
    """Verify that search, pagination, and filters are workspace-scoped."""

    async def test_search_returns_only_own_workspace_items(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=5)

        # Create another workspace with different items
        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        other_connector = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, other_ws, connector=other_connector, doc_count=3)

        # Search from workspace A should not return workspace B items
        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "search": "issue"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5  # Only own workspace items

    async def test_pagination_offset_scoped_to_workspace(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=10)

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        other_connector = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, other_ws, connector=other_connector, doc_count=20)

        # Page through workspace A
        all_ids = set()
        offset = 0
        while True:
            resp = await client.get(
                "/api/review-items",
                params={"workspace_id": str(workspace.id), "limit": 3, "offset": offset},
            )
            assert resp.status_code == 200
            body = resp.json()
            for item in body["items"]:
                all_ids.add(item["id"])
            if not body["has_more"]:
                break
            offset += 3

        assert len(all_ids) == 10

    async def test_summary_scoped_to_workspace(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=5)

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        other_connector = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, other_ws, connector=other_connector, doc_count=15)

        resp = await client.get(
            "/api/review-items/summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5

    async def test_filter_by_source_document_cross_workspace_returns_empty(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=5)

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        other_connector = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        other_seeded = await _seed_workspace_graph(
            db_session, other_ws, connector=other_connector, doc_count=3
        )

        # Try to filter by other workspace's source document
        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "source_document_id": str(other_seeded["documents"][0].id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0

    async def test_filter_by_model_cross_workspace_returns_empty(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=5)

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        other_connector = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        other_seeded = await _seed_workspace_graph(
            db_session, other_ws, connector=other_connector, doc_count=3
        )

        resp = await client.get(
            "/api/review-items",
            params={
                "workspace_id": str(workspace.id),
                "model_id": str(other_seeded["model"].id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0


# ===========================================================================
# Default limit enforcement
# ===========================================================================


class TestDefaultLimitEnforcement:
    """Verify that no silent truncation occurs and defaults are predictable."""

    async def test_no_limit_param_uses_default_50(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=200)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 50
        assert len(body["items"]) == 50
        assert body["total"] == 200
        assert body["has_more"] is True

    async def test_explicit_limit_overrides_default(self, client, workspace, db_session):
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=200)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id), "limit": 100},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 100
        assert len(body["items"]) == 100
        assert body["has_more"] is True

    async def test_small_workspace_queue_returns_all(self, client, workspace, db_session):
        """When total < limit, has_more should be False and all items returned."""
        from app.models.connector import Connector, ConnectorStatus

        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        await _seed_workspace_graph(db_session, workspace, connector=connector, doc_count=10)

        resp = await client.get(
            "/api/review-items",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 10
        assert len(body["items"]) == 10
        assert body["has_more"] is False
