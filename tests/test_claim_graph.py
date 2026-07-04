from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    Claim,
    ClaimRevision,
    Component,
    EvidenceSpan,
    Relationship,
    SourceDocument,
    UnresolvedRelationship,
)
from app.processing.extractor import ExtractedFact, ExtractedRelationship
from app.services.claims import append_claim_revision
from app.services.evidence import create_evidence_span
from app.services.ingest import IngestionService
from app.services.query import QueryService


class _StaticExtractor:
    def __init__(self, facts):
        self.facts = facts
        self.last_error = None
        self.last_warnings = []
        self.last_report = None

    async def extract(self, content, metadata):
        return list(self.facts)


async def test_grounded_deterministic_claim_becomes_active(db_session):
    fact = ExtractedFact(
        model_name="Decision",
        name="Decision: Use Postgres",
        value="Use Postgres.",
        fact_type="decision",
        confidence=0.91,
        temporal="current",
        temporal_hint="current",
        excerpt="Use Postgres.",
        provenance="unit:test",
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="grounded-claim",
        content="Decision: Use Postgres.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    svc = IngestionService(db_session, extractor=_StaticExtractor([fact]))
    assert await svc.process_document(doc.id) == 1

    component = await db_session.scalar(
        select(Component).where(Component.source_document_id == doc.id)
    )
    assert component is not None
    assert component.status == "active"
    assert component.claim_id is not None
    assert component.provenance == "unit:test"
    assert component.excerpt == "Use Postgres."

    claim = await db_session.get(Claim, component.claim_id)
    assert claim is not None
    assert claim.status == "active"
    assert claim.current_revision_id is not None

    revision = await db_session.get(ClaimRevision, claim.current_revision_id)
    assert revision is not None
    assert revision.operation == "create"
    assert revision.status_after == "active"
    evidence = await db_session.get(EvidenceSpan, revision.evidence_span_id)
    assert evidence is not None
    assert evidence.start_char is not None
    assert evidence.end_char is not None
    assert evidence.evidence_type == "decision"


async def test_ungrounded_extracted_claim_becomes_needs_review(db_session):
    fact = ExtractedFact(
        model_name="Risk",
        name="Risk: Legal launch blocker",
        value="Launch is blocked by legal approval.",
        fact_type="risk",
        confidence=0.88,
        temporal="current",
        temporal_hint="current",
        excerpt="Launch is blocked by legal approval.",
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="gmail",
        external_id="ungrounded-claim",
        content="The email says the launch plan is still being discussed.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    svc = IngestionService(db_session, extractor=_StaticExtractor([fact]))
    assert await svc.process_document(doc.id) == 1

    component = await db_session.scalar(
        select(Component).where(Component.source_document_id == doc.id)
    )
    assert component is not None
    assert component.status == "needs_review"

    claim = await db_session.get(Claim, component.claim_id)
    assert claim is not None
    assert claim.status == "needs_review"
    revision = await db_session.get(ClaimRevision, claim.current_revision_id)
    evidence = await db_session.get(EvidenceSpan, revision.evidence_span_id)
    assert evidence.evidence_type == "risk"
    assert evidence.review_status == "needs_review"
    assert evidence.start_char is None
    assert evidence.end_char is None
    assert evidence.trust_zone == "untrusted_external"


async def test_claim_revisions_are_append_only(db_session):
    first = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider",
        value="Use OAuth2.",
        fact_type="decision",
        confidence=0.82,
        excerpt="Use OAuth2.",
    )
    second = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider",
        value="Use OIDC.",
        fact_type="decision",
        confidence=0.89,
        excerpt="Use OIDC.",
    )
    doc1 = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="claim-rev-1",
        content="Decision: Use OAuth2.",
        metadata_json="{}",
    )
    doc2 = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="claim-rev-2",
        content="Decision: Use OIDC.",
        metadata_json="{}",
    )
    db_session.add_all([doc1, doc2])
    await db_session.flush()

    assert (
        await IngestionService(db_session, extractor=_StaticExtractor([first])).process_document(
            doc1.id
        )
        == 1
    )
    assert (
        await IngestionService(db_session, extractor=_StaticExtractor([second])).process_document(
            doc2.id
        )
        == 1
    )

    claims = (
        await db_session.scalars(
            select(Claim).where(Claim.identity_key == "component:auth-provider")
        )
    ).all()
    assert len(claims) == 1
    claim = claims[0]
    revisions = (
        await db_session.scalars(
            select(ClaimRevision)
            .where(ClaimRevision.claim_id == claim.id)
            .order_by(ClaimRevision.created_at)
        )
    ).all()
    assert [revision.value for revision in revisions] == ["Use OAuth2.", "Use OIDC."]
    assert revisions[0].operation == "create"
    assert revisions[1].operation == "update"
    assert claim.current_revision_id == revisions[1].id


async def test_contradiction_revision_requires_explicit_target_and_preserves_target(db_session):
    first = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider OAuth2",
        value="Use OAuth2.",
        fact_type="decision",
        confidence=0.84,
        excerpt="Use OAuth2.",
    )
    second = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider OIDC",
        value="Use OIDC.",
        fact_type="decision",
        confidence=0.88,
        excerpt="Use OIDC.",
    )
    doc1 = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="contradict-1",
        content="Decision: Use OAuth2.",
        metadata_json="{}",
    )
    doc2 = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="contradict-2",
        content="Decision: Use OIDC.",
        metadata_json="{}",
    )
    evidence_doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="contradict-evidence",
        content="Use OIDC contradicts OAuth2.",
        metadata_json="{}",
    )
    db_session.add_all([doc1, doc2, evidence_doc])
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([first])).process_document(
        doc1.id
    )
    await IngestionService(db_session, extractor=_StaticExtractor([second])).process_document(
        doc2.id
    )
    oauth_claim = await db_session.scalar(
        select(Claim).where(Claim.identity_key == "component:auth-provider-oauth2")
    )
    oidc_claim = await db_session.scalar(
        select(Claim).where(Claim.identity_key == "component:auth-provider-oidc")
    )
    evidence = await create_evidence_span(
        db_session,
        source_document=evidence_doc,
        text="Use OIDC contradicts OAuth2.",
        evidence_type="human_note",
    )

    with pytest.raises(ValueError, match="contradicts_claim_id"):
        await append_claim_revision(
            db_session,
            claim=oidc_claim,
            evidence_span=evidence.span,
            value="Use OIDC contradicts OAuth2.",
            operation="contradict",
        )

    revision = await append_claim_revision(
        db_session,
        claim=oidc_claim,
        evidence_span=evidence.span,
        value="Use OIDC contradicts OAuth2.",
        operation="contradict",
        contradicts_claim=oauth_claim,
        created_by="unit:test",
    )
    await db_session.flush()

    assert revision.contradicts_claim_id == oauth_claim.id
    assert oidc_claim.current_revision_id == revision.id
    assert oauth_claim.status == "active"
    relationship = await db_session.scalar(
        select(Relationship).where(Relationship.relationship_type == "contradicts")
    )
    assert relationship is not None
    assert relationship.evidence == "Use OIDC contradicts OAuth2."


async def test_supersede_revision_marks_target_claim_and_projection(db_session):
    old_fact = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider legacy",
        value="Use OAuth2.",
        fact_type="decision",
        confidence=0.84,
        excerpt="Use OAuth2.",
    )
    new_fact = ExtractedFact(
        model_name="Decision",
        name="Decision: Auth provider current",
        value="Use OIDC.",
        fact_type="decision",
        confidence=0.9,
        excerpt="Use OIDC.",
    )
    old_doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="supersede-old",
        content="Decision: Use OAuth2.",
        metadata_json="{}",
    )
    new_doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="supersede-new",
        content="Decision: Use OIDC.",
        metadata_json="{}",
    )
    evidence_doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="supersede-evidence",
        content="Use OIDC supersedes OAuth2.",
        metadata_json="{}",
    )
    db_session.add_all([old_doc, new_doc, evidence_doc])
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([old_fact])).process_document(
        old_doc.id
    )
    await IngestionService(db_session, extractor=_StaticExtractor([new_fact])).process_document(
        new_doc.id
    )
    old_claim = await db_session.scalar(
        select(Claim).where(Claim.identity_key == "component:auth-provider-legacy")
    )
    new_claim = await db_session.scalar(
        select(Claim).where(Claim.identity_key == "component:auth-provider-current")
    )
    evidence = await create_evidence_span(
        db_session,
        source_document=evidence_doc,
        text="Use OIDC supersedes OAuth2.",
        evidence_type="human_note",
    )

    with pytest.raises(ValueError, match="supersedes_claim_id"):
        await append_claim_revision(
            db_session,
            claim=new_claim,
            evidence_span=evidence.span,
            value="Use OIDC supersedes OAuth2.",
            operation="supersede",
        )

    revision = await append_claim_revision(
        db_session,
        claim=new_claim,
        evidence_span=evidence.span,
        value="Use OIDC supersedes OAuth2.",
        operation="supersede",
        supersedes_claim=old_claim,
        status_after="active",
        created_by="unit:test",
    )
    await db_session.flush()

    old_component = await db_session.scalar(
        select(Component).where(Component.claim_id == old_claim.id)
    )
    relationship = await db_session.scalar(
        select(Relationship).where(Relationship.relationship_type == "supersedes")
    )
    assert revision.supersedes_claim_id == old_claim.id
    assert old_claim.status == "superseded"
    assert old_component.status == "superseded"
    assert relationship is not None
    assert relationship.evidence == "Use OIDC supersedes OAuth2."


async def test_claim_status_transitions_update_current_revision_and_projection(db_session):
    fact = ExtractedFact(
        model_name="Risk",
        name="Risk: flaky smoke",
        value="Smoke test is flaky.",
        fact_type="risk",
        confidence=0.83,
        excerpt="Smoke test is flaky.",
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="status-claim",
        content="Risk: Smoke test is flaky.",
        metadata_json="{}",
    )
    evidence_doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="status-evidence",
        content="Reject stale risk. Mark stale risk. Resolve risk.",
        metadata_json="{}",
    )
    db_session.add_all([doc, evidence_doc])
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([fact])).process_document(doc.id)
    claim = await db_session.scalar(
        select(Claim).where(Claim.identity_key == "component:flaky-smoke")
    )
    component = await db_session.scalar(select(Component).where(Component.claim_id == claim.id))
    reject_evidence = await create_evidence_span(
        db_session,
        source_document=evidence_doc,
        text="Reject stale risk.",
        evidence_type="human_note",
    )
    stale_evidence = await create_evidence_span(
        db_session,
        source_document=evidence_doc,
        text="Mark stale risk.",
        evidence_type="human_note",
    )
    resolve_evidence = await create_evidence_span(
        db_session,
        source_document=evidence_doc,
        text="Resolve risk.",
        evidence_type="human_note",
    )

    rejected = await append_claim_revision(
        db_session,
        claim=claim,
        evidence_span=reject_evidence.span,
        value="Reject stale risk.",
        operation="reject",
        status_after="rejected",
    )
    assert claim.status == "rejected"
    assert component.status == "rejected"
    assert claim.current_revision_id == rejected.id

    stale = await append_claim_revision(
        db_session,
        claim=claim,
        evidence_span=stale_evidence.span,
        value="Mark stale risk.",
        operation="mark_stale",
        status_after="stale",
    )
    assert claim.status == "stale"
    assert component.status == "stale"
    assert claim.current_revision_id == stale.id

    resolved = await append_claim_revision(
        db_session,
        claim=claim,
        evidence_span=resolve_evidence.span,
        value="Resolve risk.",
        operation="resolve",
        status_after="resolved",
    )
    assert claim.status == "resolved"
    assert component.status == "resolved"
    assert claim.current_revision_id == resolved.id


async def test_component_projection_preserves_graph_api_compatibility(client, db_session):
    fact = ExtractedFact(
        model_name="Task",
        name="Task: Add pagination tests",
        value="Add pagination tests.",
        fact_type="task",
        confidence=0.86,
        excerpt="Add pagination tests.",
        provenance=json.dumps({"source_type": "local", "external_id": "graph-compat"}),
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="graph-compat",
        content="Task: Add pagination tests.",
        source_url="file:///repo/TASKS.md",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([fact])).process_document(doc.id)

    response = await client.get("/api/graph")
    assert response.status_code == 200
    data = response.json()
    components = [
        item for item in data["components"] if item["name"] == "Task: Add pagination tests"
    ]
    assert len(components) == 1
    component = components[0]
    assert component["value"] == "Add pagination tests."
    assert component["provenance"] is not None
    assert component["excerpt"] == "Add pagination tests."
    assert component["source_type"] == "local"
    assert component["source_url"] == "file:///repo/TASKS.md"


async def test_legacy_component_without_claim_remains_in_graph_and_query(client, db_session):
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="legacy-component",
        content="Legacy launch decision remains readable.",
        metadata_json="{}",
    )
    model = await IngestionService(db_session)._get_or_create_model("Decision")
    component = Component(
        id=uuid4(),
        model_id=model.id,
        source_document_id=doc.id,
        name="Legacy launch decision",
        value="Legacy launch decision remains readable.",
        fact_type="decision",
        confidence=0.86,
        status="active",
        provenance="legacy:test",
        excerpt="Legacy launch decision remains readable.",
    )
    db_session.add_all([doc, component])
    await db_session.flush()

    response = await client.get("/api/graph")
    assert response.status_code == 200
    graph_component = next(
        item for item in response.json()["components"] if item["id"] == str(component.id)
    )
    assert graph_component["name"] == "Legacy launch decision"
    assert graph_component["provenance"] == "legacy:test"

    query_result = await QueryService(db_session).query("legacy launch decision", top_k=5)
    assert any(item.id == component.id for item in query_result.components)


async def test_relationships_still_require_confidence_and_evidence(db_session):
    source = ExtractedFact(
        model_name="Task",
        name="Task: Checkout",
        value="Checkout depends on Payments API.",
        fact_type="task",
        confidence=0.85,
        excerpt="Checkout depends on Payments API.",
        relationships=[
            ExtractedRelationship(
                target_name="Payments API",
                relationship_type="depends_on",
                confidence=0.55,
                evidence="Checkout depends on Payments API.",
            )
        ],
    )
    doc = SourceDocument(
        id=uuid4(),
        source_type="local",
        external_id="low-rel",
        content="Task: Checkout depends on Payments API.",
        metadata_json="{}",
    )
    db_session.add(doc)
    await db_session.flush()

    await IngestionService(db_session, extractor=_StaticExtractor([source])).process_document(
        doc.id
    )

    assert await db_session.scalar(select(Relationship)) is None
    assert await db_session.scalar(select(UnresolvedRelationship)) is None
