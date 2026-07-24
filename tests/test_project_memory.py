from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.models import (
    Claim,
    ClaimRevision,
    CheckpointEvidence,
    CheckpointItem,
    Component,
    Connector,
    EvidenceSpan,
    MemoryReviewEvent,
    Model,
    Relationship,
    SessionEvent,
    SourceDocument,
    SyncJob,
    WorkCheckpoint,
    Workspace,
)
from app.services.context_compiler import ContextCompiler
from app.services.provider_freshness import record_provider_observation
from app.time import utc_now


async def _workspace(db_session, name: str = "Project memory") -> Workspace:
    workspace = Workspace(id=uuid4(), name=name, slug=f"memory-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    return workspace


async def _observe_provider_source(
    db_session,
    workspace: Workspace,
    source: SourceDocument,
) -> None:
    observed_at = utc_now()
    connector = Connector(
        id=uuid4(),
        workspace_id=workspace.id,
        connector_type=source.source_type,
        status="connected",
        config_json=json.dumps({"scope": "project-memory-test"}),
        credentials_json=json.dumps({"account": "project-memory-test"}),
    )
    job = SyncJob(
        id=uuid4(),
        workspace_id=workspace.id,
        connector_id=connector.id,
        status="completed",
        attempt_count=1,
        started_at=observed_at - timedelta(minutes=1),
        completed_at=observed_at + timedelta(minutes=1),
    )
    db_session.add_all([connector, job])
    await db_session.flush()
    await record_provider_observation(
        db_session,
        connector=connector,
        source=source,
        sync_job=job,
        observed_at=observed_at,
    )
    await db_session.flush()


async def _memory_component(
    db_session,
    workspace: Workspace,
    *,
    fact_type: str,
    statement: str,
    review_status: str = "verified",
    component_status: str = "active",
    source_type: str = "local",
    trust_zone: str | None = None,
) -> tuple[Component, EvidenceSpan]:
    model = Model(id=uuid4(), name=f"Memory model {uuid4().hex}")
    content = f"{fact_type.replace('_', ' ').title()}: {statement}"
    document = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type=source_type,
        external_id=f"memory:{uuid4().hex}",
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    start = content.index(statement)
    evidence = EvidenceSpan(
        id=uuid4(),
        workspace_id=workspace.id,
        source_document_id=document.id,
        start_char=start,
        end_char=start + len(statement),
        text=statement,
        text_sha256=hashlib.sha256(statement.encode()).hexdigest(),
        review_status=review_status,
        trust_zone=trust_zone or (
            "trusted_human" if review_status == "verified" else "semi_trusted_tool"
        ),
        extraction_method="deterministic",
    )
    claim = Claim(
        id=uuid4(),
        workspace_id=workspace.id,
        identity_key=f"{fact_type}:{uuid4().hex}",
        scope_identity_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
        claim_type=fact_type,
        status="active" if review_status == "verified" else "needs_review",
        temporal="current",
    )
    db_session.add_all([model, document, evidence, claim])
    await db_session.flush()
    revision = ClaimRevision(
        id=uuid4(),
        claim_id=claim.id,
        evidence_span_id=evidence.id,
        value=statement,
        operation="create",
        status_after=claim.status,
    )
    db_session.add(revision)
    await db_session.flush()
    claim.current_revision_id = revision.id
    component = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=document.id,
        claim_id=claim.id,
        identity_key=claim.identity_key,
        name=statement,
        value=statement,
        fact_type=fact_type,
        temporal="current",
        confidence=0.91,
        authority_weight=0.8,
        status=component_status,
    )
    db_session.add(component)
    await db_session.flush()
    return component, evidence


def _section(payload: dict, section_id: str) -> dict:
    return next(item for item in payload["sections"] if item["id"] == section_id)


async def test_memory_is_not_crowded_out_by_session_roots(client, db_session):
    workspace = await _workspace(db_session, "Balanced memory")
    model = Model(id=uuid4(), name=f"Sessions {uuid4().hex}")
    db_session.add(model)
    for index in range(60):
        document = SourceDocument(
            workspace_id=workspace.id,
            source_type="local",
            external_id=f"session:{index}",
            content=f"Session {index}",
            metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
        )
        db_session.add(document)
        await db_session.flush()
        db_session.add(Component(
            workspace_id=workspace.id,
            model_id=model.id,
            source_document_id=document.id,
            name=f"Session {index}",
            value=f"Session {index}",
            fact_type="session_root",
            status="needs_review",
        ))
    decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use a dedicated typed Memory API",
    )
    await db_session.flush()

    response = await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    decisions = _section(payload, "decisions")
    assert decisions["total"] == 1
    assert decisions["records"][0]["component_id"] == str(decision.id)
    assert all(
        record["kind"] != "Agent session"
        for section in payload["sections"]
        for record in section["records"]
    )


async def test_confirm_is_audited_and_keeps_record_compiler_eligible(
    client,
    db_session,
    tmp_path,
):
    workspace = await _workspace(db_session, "Confirm memory")
    component, evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Compile source backed memory evidence",
        review_status="needs_review",
        component_status="needs_review",
    )

    before = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "unverified", "limit_per_section": 50},
    )).json()
    review_record = _section(before, "unverified")["records"][0]
    assert review_record["allowed_actions"][0] == "confirm"
    assert _section(before, "decisions")["total"] == 0

    reviewed = await client.patch(
        f"/api/context/memory/{component.id}",
        json={
            "workspace_id": str(workspace.id),
            "action": "confirm",
            "reason": "Checked against the exact source span",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["component_status"] == "active"
    await db_session.refresh(component)
    await db_session.refresh(evidence)
    assert component.status == "active"
    assert evidence.review_status == "verified"
    assert evidence.trust_zone == "trusted_human"
    event = await db_session.scalar(
        select(MemoryReviewEvent).where(MemoryReviewEvent.component_id == component.id)
    )
    assert event is not None
    assert event.action == "confirm"
    assert event.reason == "Checked against the exact source span"

    after = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "decisions", "limit_per_section": 50},
    )).json()
    trusted = _section(after, "decisions")["records"][0]
    assert trusted["verification"] == "verified"
    assert trusted["last_review"]["action"] == "confirm"

    result = await ContextCompiler(db_session).compile_context_pack(
        "compile source backed memory evidence",
        workspace_id=workspace.id,
        repo_path=str(tmp_path),
        target_model="qwen2.5-coder-7b",
        token_budget=3500,
        persist=False,
    )
    assert any(
        item.get("component_id") == str(component.id)
        for item in result.selected_items
    )


async def test_memory_confirmation_rejects_missing_exact_evidence(client, db_session):
    workspace = await _workspace(db_session, "Unconfirmable memory")
    model = Model(id=uuid4(), name=f"Unconfirmable {uuid4().hex}")
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="unconfirmable",
        content="Decision without a claim evidence span",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    db_session.add_all([model, document])
    await db_session.flush()
    component = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=document.id,
        name="Unconfirmable decision",
        value="Unconfirmable decision",
        fact_type="decision",
        status="needs_review",
    )
    db_session.add(component)
    await db_session.flush()

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={"workspace_id": str(workspace.id), "action": "confirm"},
    )
    assert response.status_code == 422
    await db_session.refresh(component)
    assert component.status == "needs_review"
    assert await db_session.scalar(
        select(MemoryReviewEvent).where(MemoryReviewEvent.component_id == component.id)
    ) is None


async def test_memory_confirmation_rejects_corrupt_source_revision_hash(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Corrupt source revision")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Only confirm evidence from an intact source revision",
        review_status="needs_review",
        component_status="needs_review",
    )
    source = await db_session.get(SourceDocument, component.source_document_id)
    await db_session.execute(
        update(SourceDocument)
        .where(SourceDocument.id == source.id)
        .values(
            content_sha256=hashlib.sha256(b"different revision").hexdigest()
        )
    )
    await db_session.flush()

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={"workspace_id": str(workspace.id), "action": "confirm"},
    )

    assert response.status_code == 422
    assert "exact source evidence" in response.json()["detail"]
    await db_session.refresh(component)
    assert component.status == "needs_review"
    assert await db_session.scalar(
        select(MemoryReviewEvent).where(
            MemoryReviewEvent.component_id == component.id
        )
    ) is None


async def test_agent_claim_is_not_trusted_until_a_human_confirms_exact_evidence(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Agent evidence policy")
    component, evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Treat this agent claim as reviewable, not verified",
        review_status="verified",
        component_status="active",
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
    )
    source_metadata = {
        "workspace_id": str(workspace.id),
        "repository": "example/agent-evidence-policy",
    }
    source_document = await db_session.get(SourceDocument, component.source_document_id)
    source_document.metadata_json = json.dumps(source_metadata)
    db_session.add(Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({"repositories": ["example/agent-evidence-policy"]}),
    ))
    await db_session.flush()

    before = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "unverified"},
    )).json()
    record = _section(before, "unverified")["records"][0]
    assert record["component_id"] == str(component.id)
    assert record["verification"] == "needs_review"
    assert record["evidence"]["stored_review_status"] == "verified"
    assert "confirm" in record["allowed_actions"]

    reviewed = await client.patch(
        f"/api/context/memory/{component.id}",
        json={"workspace_id": str(workspace.id), "action": "confirm"},
    )
    assert reviewed.status_code == 200
    await db_session.refresh(evidence)
    assert evidence.trust_zone == "trusted_human"

    after = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "decisions"},
    )).json()
    record = _section(after, "decisions")["records"][0]
    assert record["verification"] == "verified"


async def test_confirmation_rejects_evidence_from_a_different_source_revision(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Evidence revision policy")
    component, evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Evidence must belong to the component source",
        review_status="needs_review",
        component_status="needs_review",
    )
    component_source = await db_session.get(SourceDocument, component.source_document_id)
    other_source = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id=f"other:{uuid4().hex}",
        content=component_source.content,
        content_sha256=component_source.content_sha256,
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    db_session.add(other_source)
    await db_session.flush()
    evidence.source_document_id = other_source.id
    await db_session.flush()

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={"workspace_id": str(workspace.id), "action": "confirm"},
    )
    assert response.status_code == 422
    assert "exact source evidence" in response.json()["detail"]
    assert await db_session.scalar(
        select(MemoryReviewEvent).where(MemoryReviewEvent.component_id == component.id)
    ) is None


async def test_memory_hides_unconfirmable_agent_extraction(client, db_session):
    workspace = await _workspace(db_session, "Unconfirmable agent extraction")
    component, evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Publish the release checklist",
        review_status="verified",
        component_status="active",
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
    )
    source_document = await db_session.get(SourceDocument, component.source_document_id)
    source_document.metadata_json = json.dumps({
        "workspace_id": str(workspace.id),
        "repository": "example/unconfirmable-agent-extraction",
    })
    db_session.add(Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({
            "repositories": ["example/unconfirmable-agent-extraction"]
        }),
    ))
    evidence.start_char = None
    evidence.end_char = None
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id)},
    )).json()
    assert _section(payload, "work")["total"] == 0
    assert _section(payload, "unverified")["total"] == 0
    assert payload["scope"]["excluded_unconfirmable_agent_components"] == 1


async def test_memory_collapses_duplicate_current_components_for_one_claim(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Canonical current claim")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Represent each canonical claim once",
    )
    duplicate = Component(
        workspace_id=component.workspace_id,
        model_id=component.model_id,
        source_document_id=component.source_document_id,
        claim_id=component.claim_id,
        identity_key=component.identity_key,
        name=component.name,
        value=component.value,
        fact_type=component.fact_type,
        temporal=component.temporal,
        confidence=component.confidence,
        authority_weight=component.authority_weight,
        status="active",
    )
    db_session.add(duplicate)
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "decisions"},
    )).json()
    decisions = _section(payload, "decisions")
    assert decisions["total"] == 1
    assert decisions["records"][0]["occurrence_count"] == 2
    assert payload["scope"]["collapsed_duplicate_current_claims"] == 1


async def test_memory_prefers_stronger_evidence_over_newer_duplicate_claim(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Strongest canonical evidence")
    trusted_component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Keep the human-verified memory record",
    )
    trusted_claim = await db_session.get(Claim, trusted_component.claim_id)
    assert trusted_claim is not None
    weak_content = "Decision: Keep the human-verified memory record"
    weak_document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id=f"memory:{uuid4().hex}",
        content=weak_content,
        content_sha256=hashlib.sha256(weak_content.encode()).hexdigest(),
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "repository": "example/strongest-evidence",
        }),
    )
    db_session.add(weak_document)
    await db_session.flush()
    weak_evidence = EvidenceSpan(
        workspace_id=workspace.id,
        source_document_id=weak_document.id,
        start_char=10,
        end_char=len(weak_content),
        text="Keep the human-verified memory record",
        text_sha256=hashlib.sha256(
            b"Keep the human-verified memory record"
        ).hexdigest(),
        review_status="verified",
        trust_zone="semi_trusted_tool",
        extraction_method="deterministic",
    )
    db_session.add(weak_evidence)
    await db_session.flush()
    weak_revision = ClaimRevision(
        claim_id=trusted_claim.id,
        evidence_span_id=weak_evidence.id,
        value="Keep the human-verified memory record",
        operation="update",
        status_after="active",
    )
    db_session.add(weak_revision)
    await db_session.flush()
    trusted_claim.current_revision_id = weak_revision.id
    weak_component = Component(
        workspace_id=workspace.id,
        model_id=trusted_component.model_id,
        source_document_id=weak_document.id,
        claim_id=trusted_claim.id,
        identity_key=trusted_claim.identity_key,
        name=trusted_component.name,
        value=trusted_component.value,
        fact_type="decision",
        temporal="current",
        confidence=0.99,
        authority_weight=0.99,
        status="active",
    )
    db_session.add_all([
        Connector(
            workspace_id=workspace.id,
            connector_type="github",
            status="connected",
            config_json=json.dumps({"repositories": ["example/strongest-evidence"]}),
        ),
        weak_component,
    ])
    await db_session.flush()
    linked_task, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Ship the source-backed memory view",
    )
    db_session.add(Relationship(
        source_component_id=weak_component.id,
        target_component_id=linked_task.id,
        relationship_type="depends_on",
        evidence=(
            "The duplicate decision occurrence depends on the delivery task."
        ),
        origin="deterministic",
        status="active",
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "limit_per_section": 50,
        },
    )).json()

    decision = _section(payload, "decisions")["records"][0]
    assert decision["component_id"] == str(trusted_component.id)
    assert decision["verification"] == "verified"
    assert decision["occurrence_count"] == 2
    dependency = _section(payload, "blockers")
    assert dependency["total"] == 1
    assert dependency["records"][0]["summary"] == (
        "The duplicate decision occurrence depends on the delivery task."
    )

    reviewed = await client.patch(
        f"/api/context/memory/{trusted_component.id}",
        json={
            "workspace_id": str(workspace.id),
            "action": "dismiss",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["affected_components"] == 2


async def test_remote_snapshot_with_unknown_freshness_is_stale_not_current(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Remote freshness")
    component, evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="github_issue",
        statement="Issue 42 is open",
        review_status="needs_review",
        component_status="proposed",
        source_type="github",
        trust_zone="semi_trusted_tool",
    )
    source_document = await db_session.get(SourceDocument, component.source_document_id)
    source_document.metadata_json = json.dumps({
        "workspace_id": str(workspace.id),
        "item_type": "issue",
        "assignees": [{"login": "stale-owner"}],
        "milestone": {"title": "Stale milestone"},
    })
    evidence.start_char = None
    evidence.end_char = None
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id)},
    )).json()
    assert _section(payload, "work")["total"] == 0
    assert _section(payload, "unverified")["total"] == 0
    assert _section(payload, "owners")["total"] == 0
    assert _section(payload, "milestones")["total"] == 0
    stale = _section(payload, "stale")
    assert stale["total"] == 3
    assert all(record["status"] == "stale" for record in stale["records"])
    assert all(
        record["source"]["freshness"] == "stale"
        for record in stale["records"]
    )
    assert payload["facets"]["stale_semantic_sections"]["owners"] == 1
    assert payload["facets"]["stale_semantic_sections"]["milestones"] == 1
    assert payload["totals"]["needs_review"] == 0
    assert payload["totals"]["needs_refresh"] == 3


async def test_recent_provider_observation_promotes_only_structured_provider_facts(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Fresh provider observation")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="github_issue",
        statement="Issue 42 is open",
        source_type="github",
        trust_zone="semi_trusted_tool",
    )
    source = await db_session.get(SourceDocument, component.source_document_id)
    source.metadata_json = json.dumps({
        "workspace_id": str(workspace.id),
        "item_type": "issue",
        "assignees": [{"login": "current-owner"}],
        "milestone": {"title": "Current milestone"},
    })
    await _observe_provider_source(db_session, workspace, source)

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "limit_per_section": 50,
        },
    )).json()

    work = _section(payload, "work")["records"][0]
    assert work["component_id"] == str(component.id)
    assert work["verification"] == "observed"
    assert work["source"]["freshness"] == "observed"
    assert _section(payload, "owners")["records"][0]["title"] == "current-owner"
    assert _section(payload, "milestones")["records"][0]["title"] == (
        "Current milestone"
    )
    assert _section(payload, "stale")["total"] == 0
    assert payload["totals"]["needs_refresh"] == 0


async def test_fresh_remote_semantic_claim_can_be_human_confirmed(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Fresh provider claim")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the provider-backed launch plan",
        review_status="needs_review",
        component_status="needs_review",
        source_type="slack",
        trust_zone="semi_trusted_tool",
    )
    source = await db_session.get(SourceDocument, component.source_document_id)
    await _observe_provider_source(db_session, workspace, source)

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={
            "workspace_id": str(workspace.id),
            "action": "confirm",
        },
    )
    assert response.status_code == 200

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "section": "decisions",
        },
    )).json()
    current = _section(payload, "decisions")["records"][0]
    assert current["component_id"] == str(component.id)
    assert current["verification"] == "verified"
    assert current["source"]["freshness"] == "observed"


async def test_memory_collapses_mechanical_supersession_into_revision_history(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Collapsed projection history")
    replacement, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the current memory projection",
    )
    historical, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the previous memory projection",
        component_status="superseded",
    )
    historical.superseded_by_id = replacement.id
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "scope": "workspace"},
    )).json()

    assert _section(payload, "superseded")["total"] == 0
    assert payload["scope"]["collapsed_source_revision_components"] == 1


async def test_checkpoint_resume_state_never_leaks_into_durable_memory(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Checkpoint boundary")
    content = "Observed checkpoint payload"
    source = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id=f"checkpoint:{uuid4().hex}",
        content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    db_session.add(source)
    await db_session.flush()
    event = SessionEvent(
        workspace_id=workspace.id,
        source_document_id=source.id,
        provider="codex",
        session_id="checkpoint-boundary",
        provider_event_id=f"event:{uuid4().hex}",
        sequence_number=1,
        event_type="compaction",
        content=content,
        payload_json="{}",
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
    )
    db_session.add(event)
    await db_session.flush()
    checkpoint = WorkCheckpoint(
        workspace_id=workspace.id,
        source_document_id=source.id,
        provider="codex",
        session_id="checkpoint-boundary",
        boundary_event_id=event.id,
        trigger="compaction",
        payload_json="{}",
        payload_sha256=hashlib.sha256(b"{}").hexdigest(),
    )
    db_session.add(checkpoint)
    await db_session.flush()
    item = CheckpointItem(
        checkpoint_id=checkpoint.id,
        item_key="relevant-file:memory",
        category="relevant_files",
        statement="frontend/src/pages/ProjectMemory.jsx",
        state="active",
        truth_state="observed",
        payload_json="{}",
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(CheckpointEvidence(
        checkpoint_item_id=item.id,
        evidence_type="source_document",
        source_document_id=source.id,
        supports=True,
        locator_json="{}",
        evidence_sha256=hashlib.sha256(content.encode()).hexdigest(),
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id)},
    )).json()
    assert payload["scope"]["checkpoint_count"] == 1
    assert _section(payload, "work")["total"] == 0
    assert _section(payload, "deliveries")["total"] == 0
    assert all(
        record["origin"] != "checkpoint"
        for section in payload["sections"]
        for record in section["records"]
    )


async def test_unconfirmable_history_cannot_be_reopened(client, db_session):
    workspace = await _workspace(db_session, "Historical reopen policy")
    component, evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Old task without exact evidence",
        review_status="needs_review",
        component_status="superseded",
    )
    evidence.start_char = None
    evidence.end_char = None
    db_session.add(MemoryReviewEvent(
        workspace_id=workspace.id,
        component_id=component.id,
        action="supersede",
        previous_component_status="active",
        next_component_status="superseded",
        reviewed_by="local_user",
        reason="Preserve this human-reviewed history record",
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "superseded"},
    )).json()
    record = _section(payload, "superseded")["records"][0]
    assert record["allowed_actions"] == []

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={"workspace_id": str(workspace.id), "action": "reopen"},
    )
    assert response.status_code == 422
    assert "exact source evidence" in response.json()["detail"]
    events = list(await db_session.scalars(
        select(MemoryReviewEvent).where(
            MemoryReviewEvent.component_id == component.id
        )
    ))
    assert [event.action for event in events] == ["supersede"]


async def test_deprecated_memory_can_be_reopened_from_history(client, db_session):
    workspace = await _workspace(db_session, "Deprecated reopen policy")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Retain the typed memory endpoint",
        component_status="deprecated",
    )
    replacement, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Replace the typed memory endpoint",
    )
    component.valid_to = component.created_at
    component.superseded_by_id = replacement.id
    supersedes = Relationship(
        source_component_id=replacement.id,
        target_component_id=component.id,
        relationship_type="supersedes",
        evidence="The replacement made this record historical.",
        origin="human_verified",
        status="active",
    )
    db_session.add(supersedes)
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "section": "superseded"},
    )).json()
    record = _section(payload, "superseded")["records"][0]
    assert record["status"] == "deprecated"
    assert record["allowed_actions"] == ["reopen"]

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={"workspace_id": str(workspace.id), "action": "reopen"},
    )

    assert response.status_code == 200
    assert response.json()["component_status"] == "active"
    await db_session.refresh(component)
    await db_session.refresh(supersedes)
    assert component.status == "active"
    assert component.valid_to is None
    assert component.superseded_by_id is None
    assert supersedes.status == "superseded"
    assert (await db_session.get(Claim, component.claim_id)).status == "active"


async def test_memory_search_counts_and_pagination_are_truthful(client, db_session):
    workspace = await _workspace(db_session, "Search memory")
    for index in range(5):
        await _memory_component(
            db_session,
            workspace,
            fact_type="decision",
            statement=f"Decision number {index} for pagination",
        )

    paged = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "section": "decisions",
            "limit_per_section": 2,
        },
    )).json()
    decisions = _section(paged, "decisions")
    assert decisions["total"] == 5
    assert len(decisions["records"]) == 2
    assert decisions["has_more"] is True

    searched = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "query": "number 3",
            "section": "decisions",
            "limit_per_section": 50,
        },
    )).json()
    decisions = _section(searched, "decisions")
    assert decisions["total"] == 1
    assert decisions["records"][0]["title"] == "Decision number 3 for pagination"


async def test_memory_filters_and_facets_narrow_source_backed_records(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Faceted memory")
    decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Keep the filter contract explicit",
    )
    repository_task, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Build the repository-backed filter",
        source_type="local_repository",
    )
    review_task, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Confirm the extracted filter behavior",
        review_status="needs_review",
        component_status="needs_review",
    )
    future_risk, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="risk",
        statement="A future provider change may affect filtering",
    )
    future_risk.temporal = "future"
    await db_session.flush()

    repository = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "source_group": "repository",
            "limit_per_section": 50,
        },
    )).json()
    assert repository["matches"] == 1
    assert _section(repository, "work")["records"][0]["component_id"] == str(
        repository_task.id
    )
    assert repository["facets"]["kinds"] == {"Task": 1}

    needs_review = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "verification": "needs_review",
            "limit_per_section": 50,
        },
    )).json()
    assert _section(needs_review, "unverified")["records"][0][
        "component_id"
    ] == str(review_task.id)

    future = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "temporal": "future",
            "limit_per_section": 50,
        },
    )).json()
    assert _section(future, "risks")["records"][0]["component_id"] == str(
        future_risk.id
    )

    typed = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "kind": "Decision",
            "limit_per_section": 50,
        },
    )).json()
    assert typed["matches"] == 1
    assert _section(typed, "decisions")["records"][0]["component_id"] == str(
        decision.id
    )


@pytest.mark.parametrize(
    ("fact_type", "expected_section", "expected_kind"),
    [
        ("requirement", "requirements", "Requirement"),
        ("constraint", "requirements", "Constraint"),
        ("decision", "decisions", "Decision"),
        ("assumption", "decisions", "Assumption"),
        ("alternative", "decisions", "Alternative"),
        ("task", "work", "Task"),
        ("action_item", "work", "Task"),
        ("issue", "work", "Issue"),
        ("blocker", "blockers", "Blocker"),
        ("risk", "risks", "Risk"),
        ("open_question", "risks", "Open question"),
        ("lesson", "learnings", "Lesson"),
        ("failed_attempt", "learnings", "Failed attempt"),
        ("verification", "deliveries", "Verification"),
        ("outcome", "deliveries", "Outcome"),
    ],
)
async def test_memory_routes_supported_fact_types_to_truthful_sections(
    client,
    db_session,
    fact_type,
    expected_section,
    expected_kind,
):
    workspace = await _workspace(db_session, f"Route {fact_type}")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type=fact_type,
        statement=f"Canonical {fact_type} record",
    )

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "section": expected_section,
            "limit_per_section": 50,
        },
    )).json()

    record = _section(payload, expected_section)["records"][0]
    assert record["component_id"] == str(component.id)
    assert record["kind"] == expected_kind
    assert record["semantic_section"] == expected_section
    assert record["status"] == "active"
    assert record["verification"] == "verified"


async def test_memory_keeps_noncurrent_lifecycle_states_out_of_current_counts(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Lifecycle memory")
    resolved_task, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Completed migration checklist",
        component_status="resolved",
    )
    resolved_task.temporal = "past"
    proposed_task, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Potential follow-up task",
        component_status="proposed",
    )
    past_blocker, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="blocker",
        statement="Credentials were unavailable",
    )
    past_blocker.temporal = "past"
    future_blocker, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="blocker",
        statement="Vendor approval may block launch",
    )
    future_blocker.temporal = "future"
    deprecated_requirement, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="requirement",
        statement="Use the retired storage format",
        component_status="deprecated",
    )
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "limit_per_section": 50},
    )).json()

    assert _section(payload, "work")["total"] == 0
    assert _section(payload, "blockers")["total"] == 0
    assert _section(payload, "completed")["records"][0]["component_id"] == str(
        resolved_task.id
    )
    assert _section(payload, "unverified")["records"][0]["component_id"] == str(
        proposed_task.id
    )
    assert _section(payload, "stale")["records"][0]["component_id"] == str(
        past_blocker.id
    )
    potential = _section(payload, "risks")["records"][0]
    assert potential["component_id"] == str(future_blocker.id)
    assert potential["kind"] == "Potential blocker"
    deprecated = _section(payload, "superseded")["records"][0]
    assert deprecated["component_id"] == str(deprecated_requirement.id)
    assert deprecated["status"] == "deprecated"
    assert payload["facets"]["review_semantic_sections"]["work"] == 1
    assert payload["facets"]["stale_semantic_sections"]["blockers"] == 1


async def test_resolved_blocker_exposes_the_evidence_that_cleared_it(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Resolved blocker evidence")
    blocker, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="blocker",
        statement="Database credentials are missing",
        component_status="resolved",
    )
    blocker.temporal = "past"
    resolution, resolution_evidence = await _memory_component(
        db_session,
        workspace,
        fact_type="verification",
        statement="Database credentials were configured",
    )
    db_session.add(Relationship(
        source_component_id=blocker.id,
        target_component_id=resolution.id,
        relationship_type="resolved_by",
        evidence="Database credentials were configured.",
        origin="deterministic",
        status="active",
        confidence=0.99,
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "section": "resolved",
            "scope": "workspace",
        },
    )).json()

    record = _section(payload, "resolved")["records"][0]
    assert record["component_id"] == str(blocker.id)
    assert record["resolution"]["summary"] == (
        "Database credentials were configured."
    )
    assert record["resolution"]["source"]["document_id"] == str(
        resolution.source_document_id
    )
    assert record["resolution"]["evidence"]["evidence_span_id"] == str(
        resolution_evidence.id
    )
    assert record["resolution"]["evidence"]["excerpt"] == (
        "Database credentials were configured"
    )
    assert record["resolution"]["evidence"]["exact"] is True


async def test_agenda_scope_uses_explicit_component_links_and_can_expand_to_workspace(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Agenda memory")
    focus, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Ship agenda-scoped memory",
    )
    linked_decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use explicit graph links for agenda scope",
    )
    unrelated_requirement, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="requirement",
        statement="Export an unrelated archive",
    )
    db_session.add(Relationship(
        source_component_id=focus.id,
        target_component_id=linked_decision.id,
        relationship_type="depends_on",
        evidence="The task explicitly depends on this decision.",
        origin="deterministic",
        status="active",
    ))
    db_session.add(Relationship(
        source_component_id=focus.id,
        target_component_id=unrelated_requirement.id,
        relationship_type="depends_on",
        evidence="An extracted relationship must not expand agenda scope.",
        origin="extracted",
        status="active",
    ))
    await db_session.flush()

    selected = await client.put(
        f"/api/workspaces/{workspace.id}/current-goal",
        json={
            "title": focus.name,
            "component_id": str(focus.id),
            "source_kind": "suggested_card",
            "source_id": str(focus.source_document_id),
        },
    )
    assert selected.status_code == 200

    agenda_payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "agenda",
            "limit_per_section": 50,
        },
    )).json()
    assert agenda_payload["agenda"]["component_id"] == str(focus.id)
    assert agenda_payload["agenda"]["match_mode"] == "linked_component"
    assert agenda_payload["scope"]["effective_mode"] == "agenda"
    assert _section(agenda_payload, "work")["records"][0]["component_id"] == str(
        focus.id
    )
    assert _section(agenda_payload, "decisions")["records"][0]["component_id"] == str(
        linked_decision.id
    )
    assert _section(agenda_payload, "requirements")["total"] == 0
    assert "linked" in _section(agenda_payload, "decisions")["records"][0][
        "relevance"
    ].lower()

    workspace_payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "limit_per_section": 50,
        },
    )).json()
    assert workspace_payload["scope"]["effective_mode"] == "workspace"
    assert _section(workspace_payload, "requirements")["records"][0][
        "component_id"
    ] == str(unrelated_requirement.id)


@pytest.mark.parametrize(
    ("origin", "relationship_status"),
    [
        ("extracted", "active"),
        ("deterministic", "proposed"),
    ],
)
async def test_untrusted_dependency_does_not_become_current_blocker(
    client,
    db_session,
    origin,
    relationship_status,
):
    workspace = await _workspace(db_session, "Relationship trust")
    task, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Publish the release",
    )
    decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use a staged rollout",
    )
    db_session.add(Relationship(
        source_component_id=task.id,
        target_component_id=decision.id,
        relationship_type="depends_on",
        evidence="An extracted dependency without human confirmation.",
        origin=origin,
        status=relationship_status,
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "scope": "workspace"},
    )).json()

    assert _section(payload, "blockers")["total"] == 0
    assert payload["scope"]["excluded_untrusted_relationships"] == 1


@pytest.mark.parametrize(
    ("origin", "relationship_status"),
    [
        ("extracted", "active"),
        ("deterministic", "proposed"),
    ],
)
async def test_untrusted_conflict_does_not_demote_verified_decisions(
    client,
    db_session,
    origin,
    relationship_status,
):
    workspace = await _workspace(db_session, "Conflict relationship trust")
    first_decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the indexed context compiler",
    )
    second_decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Keep exact source evidence",
    )
    db_session.add(Relationship(
        source_component_id=first_decision.id,
        target_component_id=second_decision.id,
        relationship_type="contradicts",
        evidence="An untrusted contradiction that still requires review.",
        origin=origin,
        status=relationship_status,
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={"workspace_id": str(workspace.id), "scope": "workspace"},
    )).json()

    current_decisions = _section(payload, "decisions")
    assert current_decisions["total"] == 2
    assert {
        record["component_id"] for record in current_decisions["records"]
    } == {str(first_decision.id), str(second_decision.id)}

    conflict = _section(payload, "conflicts")
    assert conflict["total"] == 1
    assert conflict["records"][0]["origin"] == "relationship"
    assert conflict["records"][0]["verification"] == "needs_review"
    assert conflict["records"][0]["status"] == "conflict"


async def test_memory_review_cannot_cross_workspace_boundary(client, db_session):
    first = await _workspace(db_session, "First review workspace")
    second = await _workspace(db_session, "Second review workspace")
    second_component, _ = await _memory_component(
        db_session,
        second,
        fact_type="decision",
        statement="Keep this decision in the second workspace",
        review_status="needs_review",
        component_status="needs_review",
    )

    response = await client.patch(
        f"/api/context/memory/{second_component.id}",
        json={
            "workspace_id": str(first.id),
            "action": "confirm",
        },
    )

    assert response.status_code == 404
    await db_session.refresh(second_component)
    assert second_component.status == "needs_review"


async def test_reviewing_a_canonical_claim_updates_all_current_occurrences(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Claim-scoped review")
    representative, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the evidence ledger for project memory",
        review_status="needs_review",
        component_status="needs_review",
    )
    sibling, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the evidence ledger for project memory",
        review_status="needs_review",
        component_status="needs_review",
    )
    shared_claim = await db_session.get(Claim, representative.claim_id)
    sibling.claim_id = shared_claim.id
    sibling.identity_key = representative.identity_key
    await db_session.flush()

    before = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "section": "unverified",
            "scope": "workspace",
        },
    )).json()
    canonical = _section(before, "unverified")["records"][0]
    assert canonical["component_id"] == str(representative.id)
    assert canonical["occurrence_count"] == 2

    response = await client.patch(
        f"/api/context/memory/{representative.id}",
        json={
            "workspace_id": str(workspace.id),
            "action": "dismiss",
            "reason": "This claim is not correct.",
        },
    )

    assert response.status_code == 200
    assert response.json()["affected_components"] == 2
    await db_session.refresh(representative)
    await db_session.refresh(sibling)
    await db_session.refresh(shared_claim)
    assert representative.status == "rejected"
    assert sibling.status == "rejected"
    assert representative.valid_to is not None
    assert sibling.valid_to is not None
    assert shared_claim.status == "rejected"
    review_events = list(await db_session.scalars(
        select(MemoryReviewEvent).where(
            MemoryReviewEvent.component_id.in_([
                representative.id,
                sibling.id,
            ])
        )
    ))
    assert len(review_events) == 2

    after = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
        },
    )).json()
    assert _section(after, "decisions")["total"] == 0
    assert _section(after, "unverified")["total"] == 0
    assert _section(after, "dismissed")["total"] == 2


async def test_memory_review_rejects_a_cross_workspace_claim_link(
    client,
    db_session,
):
    first = await _workspace(db_session, "Corrupt component workspace")
    second = await _workspace(db_session, "Corrupt claim workspace")
    first_component, _ = await _memory_component(
        db_session,
        first,
        fact_type="decision",
        statement="Keep this component in the first workspace",
        review_status="needs_review",
        component_status="needs_review",
    )
    second_component, _ = await _memory_component(
        db_session,
        second,
        fact_type="decision",
        statement="Keep this claim in the second workspace",
        review_status="needs_review",
        component_status="needs_review",
    )
    second_claim = await db_session.get(Claim, second_component.claim_id)
    first_component.claim_id = second_claim.id
    await db_session.flush()

    response = await client.patch(
        f"/api/context/memory/{first_component.id}",
        json={
            "workspace_id": str(first.id),
            "action": "dismiss",
        },
    )

    assert response.status_code == 409
    assert "crosses workspace boundaries" in response.json()["detail"]
    await db_session.refresh(first_component)
    await db_session.refresh(second_claim)
    assert first_component.status == "needs_review"
    assert second_claim.status == "needs_review"
    assert await db_session.scalar(
        select(MemoryReviewEvent).where(
            MemoryReviewEvent.component_id == first_component.id
        )
    ) is None


async def test_agent_reported_activity_is_history_not_human_review_work(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Reported agent activity")
    verification, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="verification",
        statement="The focused suite passed with 27 tests",
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
    )
    failed_attempt, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="failed_attempt",
        statement="The first migration attempt failed before making changes",
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
    )
    decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Use the new review workflow",
        source_type="agent_session",
        trust_zone="semi_trusted_tool",
    )
    for component in (verification, failed_attempt, decision):
        source = await db_session.get(
            SourceDocument,
            component.source_document_id,
        )
        source.metadata_json = json.dumps({
            "workspace_id": str(workspace.id),
            "repository": "example/reported-agent-activity",
        })
    db_session.add(Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({
            "repositories": ["example/reported-agent-activity"],
        }),
    ))
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "limit_per_section": 50,
        },
    )).json()

    activities = _section(payload, "completed")["records"]
    assert {item["component_id"] for item in activities} == {
        str(verification.id),
        str(failed_attempt.id),
    }
    assert all(item["status"] == "reported" for item in activities)
    assert all(item["verification"] == "reported" for item in activities)
    assert all(item["allowed_actions"] == [] for item in activities)
    assert all(
        "point-in-time history" in item["explanation"]
        for item in activities
    )
    candidate = _section(payload, "unverified")["records"][0]
    assert candidate["component_id"] == str(decision.id)
    assert candidate["allowed_actions"][0] == "confirm"
    assert payload["totals"]["reported_activity"] == 2
    assert payload["totals"]["needs_review"] == 1
    assert payload["totals"]["ready_to_review"] == 1

    rejected_promotion = await client.patch(
        f"/api/context/memory/{verification.id}",
        json={"workspace_id": str(workspace.id), "action": "confirm"},
    )
    assert rejected_promotion.status_code == 409
    assert "retained as history" in rejected_promotion.json()["detail"]
    await db_session.refresh(verification)
    assert verification.status == "active"
    assert await db_session.scalar(
        select(MemoryReviewEvent).where(
            MemoryReviewEvent.component_id == verification.id
        )
    ) is None


async def test_semantic_section_filter_is_orthogonal_to_truth_lane(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Semantic memory filter")
    decision, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="decision",
        statement="Review decisions by project meaning",
        review_status="needs_review",
        component_status="needs_review",
    )
    await _memory_component(
        db_session,
        workspace,
        fact_type="task",
        statement="Keep work out of the decision queue",
        review_status="needs_review",
        component_status="needs_review",
    )

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "section": "unverified",
            "semantic_section": "decisions",
            "limit_per_section": 50,
        },
    )).json()

    records = _section(payload, "unverified")["records"]
    assert [record["component_id"] for record in records] == [str(decision.id)]
    assert payload["selected_section"] == "unverified"
    assert payload["selected_semantic_section"] == "decisions"
    assert payload["matches"] == 1
    assert payload["facets"]["reviewable_semantic_sections"] == {
        "decisions": 1,
    }


async def test_remote_snapshot_cannot_be_confirmed_as_current(
    client,
    db_session,
):
    workspace = await _workspace(db_session, "Remote confirmation guard")
    component, _ = await _memory_component(
        db_session,
        workspace,
        fact_type="github_issue",
        statement="Issue 42 is still open",
        review_status="needs_review",
        component_status="proposed",
        source_type="github",
        trust_zone="semi_trusted_tool",
    )
    source = await db_session.get(SourceDocument, component.source_document_id)
    source.metadata_json = json.dumps({
        "workspace_id": str(workspace.id),
        "item_type": "issue",
    })
    await db_session.flush()

    payload = (await client.get(
        "/api/context/memory",
        params={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "limit_per_section": 50,
        },
    )).json()
    record = _section(payload, "stale")["records"][0]
    assert record["component_id"] == str(component.id)
    assert "confirm" not in record["allowed_actions"]
    assert payload["totals"]["needs_review"] == 0
    assert payload["totals"]["needs_refresh"] == 1

    response = await client.patch(
        f"/api/context/memory/{component.id}",
        json={
            "workspace_id": str(workspace.id),
            "action": "confirm",
        },
    )
    assert response.status_code == 409
    assert "Refresh this provider source" in response.json()["detail"]
