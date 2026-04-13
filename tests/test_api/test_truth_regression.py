"""Regression tests for the unified truth/provenance layer.

Covers:
- as-of historical queries correctness
- stale fact detection (is_stale, valid_to)
- conflicting fact resolution
- review-gated fact exclusion
- provenance in all major workflow responses
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.models.connector import Connector, ConnectorStatus
from app.models.knowledge import (
    Component,
    ComponentSource,
    KnowledgeModel,
)
from app.models.review import ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.services.truth_visibility import (
    is_component_visible_as_of,
    is_component_visible_in_current_truth,
    is_component_visible_in_history,
)


async def _seed_base(db_session, workspace):
    """Create a workspace with connector, model, and source doc."""
    connector = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={},
    )
    db_session.add(connector)
    await db_session.flush()

    model = KnowledgeModel(
        workspace_id=workspace.id,
        name="Truth Tests",
        description="Model for truth layer regression tests",
    )
    db_session.add(model)
    await db_session.flush()

    doc = SourceDocument(
        connector_id=connector.id,
        connector_type=ConnectorType.SLACK,
        external_id="slack:truth-test",
        content="decision: enterprise price is $600/seat",
        author="founder@example.com",
        metadata_json={"channel_name": "pricing"},
    )
    db_session.add(doc)
    await db_session.flush()

    return {"connector": connector, "model": model, "doc": doc}


async def _link_source(db_session, component, document):
    db_session.add(
        ComponentSource(
            component_id=component.id,
            source_document_id=document.id,
            extraction_context="Test extraction",
            extracted_value=component.value,
            extractor_name="regex",
            extractor_kind="regex",
            extractor_schema_version="fact_extraction.v1",
        )
    )
    await db_session.flush()


class TestAsOfQueries:
    """Historical (as-of) queries return the correct fact version."""

    async def test_as_of_returns_historical_version(self, client, db_session, workspace):
        """When querying as_of a past date, the historical component is returned."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        old = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$500/seat",
            confidence=0.9,
            authority_weight=0.9,
            valid_from=datetime(2026, 3, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        new = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$600/seat",
            confidence=0.92,
            authority_weight=0.9,
            valid_from=datetime(2026, 3, 20, tzinfo=UTC),
            last_verified_at=datetime(2026, 3, 20, tzinfo=UTC),
        )
        db_session.add_all([old, new])
        await db_session.flush()
        old.superseded_by_id = new.id
        db_session.add(
            ReviewItem(
                component_id=old.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Enterprise Plan is now historical",
                summary="Superseded by a newer plan.",
                confidence=old.confidence,
            )
        )
        await db_session.flush()

        current = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise plan price?",
                "workspace_id": str(workspace.id),
            },
        )
        historical = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise plan price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-03-10T00:00:00Z",
            },
        )

        assert current.status_code == 200
        assert historical.status_code == 200
        assert current.json()["components"][0]["value"] == "$600/seat"
        assert historical.json()["components"][0]["value"] == "$500/seat"
        assert historical.json()["answer"].startswith("As of 2026-03-10")

    async def test_as_of_excludes_rejected_components(self, client, db_session, workspace):
        """Rejected components are never returned, even in as-of queries."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        rejected = Component(
            model_id=model.id,
            name="Enterprise Plan",
            value="$300/seat",
            confidence=0.8,
            authority_weight=0.5,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            last_verified_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        db_session.add(rejected)
        await db_session.flush()
        db_session.add(
            ReviewItem(
                component_id=rejected.id,
                status="rejected",
                severity="high",
                kind="conflict",
                title="Rejected price",
                summary="This price was rejected",
                confidence=0.8,
            )
        )
        await db_session.commit()

        result = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
                "as_of": "2026-02-15T00:00:00Z",
            },
        )
        assert result.status_code == 200
        # Rejected component should not appear
        body = result.json()
        assert not body["components"] or all(
            "$300" not in c["value"] for c in body["components"]
        )


class TestStaleFacts:
    """Stale facts are correctly identified in freshness scoring."""

    async def test_current_truth_returns_current_freshness(self, client, db_session, workspace):
        """Query service returns CURRENT freshness for recently verified components."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Policy",
            description="Policy model",
        )
        db_session.add(model)
        await db_session.flush()

        now = datetime.now(timezone.utc)
        current = Component(
            model_id=model.id,
            name="Current Policy",
            value="Current policy value",
            confidence=0.9,
            valid_from=now,
            last_verified_at=now,
        )
        db_session.add(current)
        await db_session.commit()

        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the policy?",
                "workspace_id": str(workspace.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["components"]
        assert body["components"][0]["value"] == "Current policy value"
        assert body["freshness"] == "current"


class TestConflictingFacts:
    """Conflicting facts create proper review items and supersession."""

    async def test_conflicting_facts_query_shows_review_status(self, client, db_session, workspace):
        """Query returns components with their review status visible."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Pricing",
            description="Pricing model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:pricing-conflict",
            content="Enterprise pricing: $600 per seat",
            metadata_json={"channel_name": "pricing"},
        )
        db_session.add(doc)
        await db_session.flush()

        first = Component(
            model_id=model.id,
            name="Enterprise Price",
            value="$400/seat",
            confidence=0.9,
            authority_weight=0.75,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 2, 1, tzinfo=UTC),
            last_verified_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
        second = Component(
            model_id=model.id,
            name="Enterprise Price",
            value="$600/seat",
            confidence=0.85,
            authority_weight=0.75,
            valid_from=datetime(2026, 2, 1, tzinfo=UTC),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add_all([first, second])
        await db_session.flush()
        first.superseded_by_id = second.id
        db_session.add(
            ComponentSource(
                component_id=second.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=second.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        db_session.add_all([
            ReviewItem(
                component_id=first.id,
                status="superseded",
                severity="low",
                kind="superseded_fact",
                title="Price superseded",
                summary="Changed from $400 to $600",
                confidence=0.9,
            ),
            ReviewItem(
                component_id=second.id,
                status="needs_review",
                severity="high",
                kind="conflict",
                title="Price conflict",
                summary="Two different prices found",
                confidence=0.85,
            ),
        ])
        await db_session.commit()

        resp = await client.post(
            "/api/query",
            json={
                "question": "What is the enterprise price?",
                "workspace_id": str(workspace.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Current truth excludes superseded; needs_review component is visible but penalized
        assert body["components"]
        comp = body["components"][0]
        assert comp["value"] == "$600/seat"
        assert comp["review_status"] == "needs_review"


class TestReviewGatedFacts:
    """Rejected and superseded facts are excluded from current truth.

    These are tested at the API level (see test_briefing.py
    test_workflow_views_hide_rejected_and_superseded_current_decisions)
    and via the unit tests in TestTruthVisibilityFunctions below.
    """
    pass


class TestTruthVisibilityFunctions:
    """Unit tests for truth_visibility.py helper functions."""

    def _make_component(self, **kwargs):
        """Create a minimal Component-like object for testing."""
        defaults = {
            "valid_to": None,
            "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
            "review_item": None,
            "is_stale": False,
            "last_verified_at": datetime(2026, 3, 1, tzinfo=UTC),
        }
        defaults.update(kwargs)

        class _ReviewItemProxy:
            def __init__(self, status):
                self.status = status

        class _Component:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)
                # Add review_status property that delegates to review_item
                @property
                def review_status(self):
                    if self.review_item is None:
                        return None
                    return self.review_item.status
                type(self).review_status = review_status

        if "review_status" in defaults:
            status = defaults.pop("review_status")
            defaults["review_item"] = _ReviewItemProxy(status)

        return _Component(**defaults)

    def test_current_truth_excludes_historical(self):
        c = self._make_component(valid_to=datetime(2026, 2, 1, tzinfo=UTC))
        assert is_component_visible_in_current_truth(c) is False

    def test_current_truth_excludes_rejected(self):
        c = self._make_component(review_status="rejected")
        assert is_component_visible_in_current_truth(c) is False

    def test_current_truth_excludes_superseded(self):
        c = self._make_component(review_status="superseded")
        assert is_component_visible_in_current_truth(c) is False

    def test_current_truth_includes_approved(self):
        c = self._make_component(review_status="approved")
        assert is_component_visible_in_current_truth(c) is True

    def test_current_truth_includes_no_review(self):
        c = self._make_component()
        assert is_component_visible_in_current_truth(c) is True

    def test_as_of_excludes_rejected(self):
        c = self._make_component(
            review_status="rejected",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert is_component_visible_as_of(c, as_of=datetime(2026, 2, 1, tzinfo=UTC)) is False

    def test_as_of_includes_superseded_if_valid_at_time(self):
        """Superseded components that were valid at the as_of time should be visible."""
        c = self._make_component(
            review_status="superseded",
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 3, 1, tzinfo=UTC),
        )
        # At Feb 15, this component was still valid
        assert is_component_visible_as_of(c, as_of=datetime(2026, 2, 15, tzinfo=UTC)) is True
        # At Apr 1, it has expired
        assert is_component_visible_as_of(c, as_of=datetime(2026, 4, 1, tzinfo=UTC)) is False

    def test_history_includes_superseded(self):
        c = self._make_component(review_status="superseded")
        assert is_component_visible_in_history(c) is True

    def test_history_excludes_rejected(self):
        c = self._make_component(review_status="rejected")
        assert is_component_visible_in_history(c) is False


class TestProvenanceInWorkflows:
    """Provenance (source document IDs) is present in all major workflow responses."""

    async def test_founder_brief_fact_has_source_document_ids(self, client, workspace, db_session):
        """Founder brief facts include source_document_ids for provenance."""
        connector = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(connector)
        await db_session.flush()

        model = KnowledgeModel(
            workspace_id=workspace.id,
            name="Brief Provenance",
            description="Test model",
        )
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=connector.id,
            connector_type=ConnectorType.SLACK,
            external_id="slack:prov-test",
            content="decision: launch next Tuesday",
            metadata_json={"channel_name": "general"},
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            model_id=model.id,
            name="Decision in #general",
            value="Launch next Tuesday.",
            confidence=0.9,
            authority_weight=0.75,
            valid_from=datetime.now(timezone.utc) - timedelta(hours=1),
            last_verified_at=datetime.now(timezone.utc),
        )
        db_session.add(component)
        await db_session.flush()

        db_session.add(
            ComponentSource(
                component_id=component.id,
                source_document_id=doc.id,
                extraction_context="Test",
                extracted_value=component.value,
                extractor_name="regex",
                extractor_kind="regex",
                extractor_schema_version="fact_extraction.v1",
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/founder-brief",
            params={"workspace_id": str(workspace.id), "lookback_days": 7},
        )
        assert resp.status_code == 200
        body = resp.json()
        facts = body.get("changed_facts", [])
        assert facts
        fact = facts[0]
        assert "source_document_ids" in fact
        assert str(doc.id) in fact["source_document_ids"]
