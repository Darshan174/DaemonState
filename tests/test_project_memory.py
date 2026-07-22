from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

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
    SessionEvent,
    SourceDocument,
    WorkCheckpoint,
    Workspace,
)
from app.services.context_compiler import ContextCompiler


async def _workspace(db_session, name: str = "Project memory") -> Workspace:
    workspace = Workspace(id=uuid4(), name=name, slug=f"memory-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    return workspace


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
        component_status="active",
        source_type="github",
        trust_zone="semi_trusted_tool",
    )
    source_document = await db_session.get(SourceDocument, component.source_document_id)
    source_document.metadata_json = json.dumps({
        "workspace_id": str(workspace.id),
        "item_type": "issue",
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
    stale = _section(payload, "stale")
    assert stale["total"] == 1
    assert stale["records"][0]["status"] == "stale"
    assert stale["records"][0]["source"]["freshness"] == "stale"


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
    assert await db_session.scalar(
        select(MemoryReviewEvent).where(MemoryReviewEvent.component_id == component.id)
    ) is None


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
