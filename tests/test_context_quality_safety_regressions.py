from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.dependencies import get_access_scope
from app.main import app
from app.models import (
    ActiveContextPointer,
    SessionEvent,
    SourceDocument,
    SourceReadGrant,
    Workspace,
)
from app.schemas.context_quality import (
    ClaimCriticality,
    ContextClaimEnvelope,
    ContextDecision,
    ContextKind,
)
from app.services.access import AccessScope
from app.services.context_quality import (
    ContextActivationConflict,
    ContextRollbackUnsafe,
    access_scope_sha256,
    activate_reviewed_candidate,
    reconcile_context_candidate,
    record_active_context_outcome,
    rollback_active_context,
)
from app.services.context_quality_policies import compare_context_claims


ACCESS = access_scope_sha256(AccessScope.local())
DELIVERY = "8" * 64
SCOPE = "9" * 64


def _claim(
    statement: str = "The product preserves evidence history.",
) -> ContextClaimEnvelope:
    return ContextClaimEnvelope(
        stable_id="workspace.product:purpose",
        section="product",
        kind="product_fact",
        statement=statement,
        scope=ContextKind.WORKSPACE,
        authority="documentation",
        truth_state="current",
        criticality=ClaimCriticality.CRITICAL,
        evidence_refs=("README.md:1",),
    )


def _metadata(*, score: float = 100.0, snapshot_current: bool = True) -> dict:
    return {
        "objective_independent": True,
        "copy_ready": True,
        "hash_valid": True,
        "snapshot_current": snapshot_current,
        "permissions_current": True,
        "durable_fact_count": 1,
        "verification_complete": True,
        "semantic_coverage_score": score,
    }


async def _workspace(db_session) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        name="Context quality safety regression",
        slug=f"context-quality-safety-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    return workspace


async def _reconcile(
    db_session,
    workspace: Workspace,
    *,
    observation: dict,
    content: str,
    claim: ContextClaimEnvelope,
    metadata: dict | None = None,
):
    return await reconcile_context_candidate(
        db_session,
        workspace_id=workspace.id,
        context_kind=ContextKind.WORKSPACE,
        scope_key_sha256=SCOPE,
        access_scope_sha256_value=ACCESS,
        delivery_profile_sha256_value=DELIVERY,
        observation=observation,
        artifact={"content": content},
        content=content,
        claims=(claim,),
        evaluation_metadata=metadata or _metadata(),
        artifact_schema_version="workspace_foundation.v2",
        compiler_version="safety-regression-compiler.v1",
        renderer_version="safety-regression-renderer.v1",
        policy_name="workspace_foundation",
    )


async def _quarantine_active_candidate(db_session):
    workspace = await _workspace(db_session)
    active = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "quarantine-snapshot"},
        content="Workspace background later reported unsafe",
        claim=_claim(),
    )
    pointer = await db_session.scalar(
        select(ActiveContextPointer).where(
            ActiveContextPointer.workspace_id == workspace.id
        )
    )
    assert pointer is not None
    quarantined = await record_active_context_outcome(
        db_session,
        workspace_id=workspace.id,
        pointer_id=pointer.id,
        expected_generation=active.pointer_generation,
        access_scope_sha256_value=ACCESS,
        outcome="unsafe",
        actor="user",
        reason="This exact artifact produced an unsafe downstream result.",
    )
    assert quarantined.copy_allowed is False
    return workspace, active, pointer, quarantined


async def test_quarantined_candidate_cannot_auto_reactivate_from_identical_reconcile(
    db_session,
) -> None:
    workspace, active, pointer, quarantined = await _quarantine_active_candidate(
        db_session
    )

    repeated = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "quarantine-snapshot"},
        content="Workspace background later reported unsafe",
        claim=_claim(),
    )

    assert repeated.candidate_id == active.candidate_id
    assert repeated.copy_allowed is False
    assert repeated.status != "active"
    assert repeated.active_candidate_id is None
    assert repeated.pointer_generation == quarantined.pointer_generation
    await db_session.refresh(pointer)
    assert pointer.active_candidate_id is None


async def test_quarantined_candidate_cannot_use_normal_review_activation(
    db_session,
) -> None:
    workspace, active, _pointer, quarantined = await _quarantine_active_candidate(
        db_session
    )

    with pytest.raises(ContextRollbackUnsafe):
        await activate_reviewed_candidate(
            db_session,
            workspace_id=workspace.id,
            candidate_id=UUID(active.candidate_id),
            expected_generation=quarantined.pointer_generation,
            access_scope_sha256_value=ACCESS,
            actor="reviewer",
            reason="Normal review activation must not clear a harmful outcome.",
        )


async def test_hard_failure_on_same_active_candidate_revokes_copy_authority(
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    active = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "same-candidate"},
        content="Workspace background with a mutable currentness check",
        claim=_claim(),
    )
    assert active.copy_allowed is True

    rejected = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "same-candidate"},
        content="Workspace background with a mutable currentness check",
        claim=_claim(),
        metadata=_metadata(snapshot_current=False),
    )

    assert rejected.candidate_id == active.candidate_id
    assert rejected.decision is ContextDecision.REJECT
    assert rejected.copy_allowed is False
    assert rejected.status != "active"
    assert rejected.active_candidate_id is None
    pointer = await db_session.scalar(
        select(ActiveContextPointer).where(
            ActiveContextPointer.workspace_id == workspace.id
        )
    )
    assert pointer is not None
    assert pointer.active_candidate_id is None
    assert pointer.active_evaluation_id is None


async def test_review_evaluation_cannot_activate_after_baseline_changes(
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    first = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "baseline-a"},
        content="Workspace background A",
        claim=_claim("The product preserves evidence history."),
    )
    review = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "candidate-c"},
        content="Workspace background C requiring review",
        claim=_claim("The product preserves evidence history."),
        metadata=_metadata(score=60.0),
    )
    assert review.status == "review_required"
    assert review.pointer_generation == first.pointer_generation

    second = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "baseline-b"},
        content="Workspace background B",
        claim=_claim("The product preserves immutable evidence history."),
    )
    assert second.status == "active"
    assert second.candidate_id != first.candidate_id
    assert second.pointer_generation > review.pointer_generation

    with pytest.raises(ContextActivationConflict):
        await activate_reviewed_candidate(
            db_session,
            workspace_id=workspace.id,
            candidate_id=UUID(review.candidate_id),
            # This is intentionally the fresh generation. CAS alone is not
            # sufficient: the saved review diff was computed against A, not B.
            expected_generation=second.pointer_generation,
            access_scope_sha256_value=ACCESS,
            actor="reviewer",
            reason="A stale A-to-C review must be reevaluated against B.",
        )

    pointer = await db_session.scalar(
        select(ActiveContextPointer).where(
            ActiveContextPointer.workspace_id == workspace.id
        )
    )
    assert pointer is not None
    assert str(pointer.active_candidate_id) == second.candidate_id


async def test_review_activation_rejects_conflicting_same_baseline_evaluation(
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "baseline"},
        content="Workspace background baseline",
        claim=_claim(),
    )
    review = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "candidate"},
        content="Workspace background candidate",
        claim=_claim("The product preserves reviewed evidence history."),
        metadata=_metadata(score=60.0),
    )
    rejected_metadata = _metadata(score=60.0)
    rejected_metadata["copy_ready"] = False
    rejected = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "candidate"},
        content="Workspace background candidate",
        claim=_claim("The product preserves reviewed evidence history."),
        metadata=rejected_metadata,
    )
    assert rejected.candidate_id == review.candidate_id
    assert rejected.decision is ContextDecision.REJECT
    assert rejected.pointer_generation == review.pointer_generation

    with pytest.raises(ContextActivationConflict):
        await activate_reviewed_candidate(
            db_session,
            workspace_id=workspace.id,
            candidate_id=UUID(review.candidate_id),
            expected_generation=review.pointer_generation,
            expected_evaluation_id=UUID(review.evaluation_id),
            access_scope_sha256_value=ACCESS,
            actor="reviewer",
            reason="A superseded review evaluation must not be activatable.",
        )


async def test_rollback_cannot_ignore_rejected_target_reevaluation(db_session) -> None:
    workspace = await _workspace(db_session)
    target = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "shared"},
        content="Rollback target",
        claim=_claim(),
    )
    current = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "shared"},
        content="Current candidate",
        claim=_claim("The product preserves immutable evidence history."),
    )
    rejected = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "shared"},
        content="Rollback target",
        claim=_claim(),
        metadata=_metadata(snapshot_current=False),
    )
    assert rejected.candidate_id == target.candidate_id
    assert rejected.decision is ContextDecision.REJECT
    assert rejected.active_candidate_id == current.candidate_id

    pointer = await db_session.scalar(select(ActiveContextPointer).where(
        ActiveContextPointer.workspace_id == workspace.id
    ))
    assert pointer is not None
    with pytest.raises(ContextRollbackUnsafe):
        await rollback_active_context(
            db_session,
            workspace_id=workspace.id,
            pointer_id=pointer.id,
            target_candidate_id=UUID(target.candidate_id),
            expected_generation=rejected.pointer_generation,
            access_scope_sha256_value=ACCESS,
            actor="reviewer",
            reason="A rejected target cannot use its older promotion.",
        )


@pytest.mark.parametrize(
    "update",
    [
        {"repository_snapshot_sha256": "b" * 64},
        {"session_boundary_id": "boundary-b"},
    ],
)
def test_claim_diff_detects_lineage_change(update) -> None:
    before = _claim().model_copy(
        update={
            "repository_snapshot_sha256": "a" * 64,
            "session_boundary_id": "boundary-a",
        }
    )
    after = before.model_copy(update=update)

    diff = compare_context_claims((before,), (after,))

    assert diff.modified == (before.stable_id,)
    assert not diff.retained


async def test_permission_revocation_hides_content_and_blocks_review_activation(
    client,
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    alice = AccessScope("alice", frozenset({workspace.id}))
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="local",
        external_id=f"restricted-context-{uuid4().hex}",
        content="Restricted evidence: production signing uses the HSM key.",
        metadata_json="{}",
        visibility_scope="restricted",
        permission_source="explicit",
    )
    db_session.add(source)
    await db_session.flush()
    grant = SourceReadGrant(
        id=uuid4(),
        workspace_id=workspace.id,
        source_document_id=source.id,
        principal_id=alice.principal_id,
        grant_key=uuid4().hex + uuid4().hex,
        permission_snapshot_sha256=source.permission_snapshot_sha256,
    )
    db_session.add(grant)
    await db_session.flush()

    async def reconcile_restricted(
        *,
        observation_name: str,
        content: str,
        score: float,
    ):
        return await reconcile_context_candidate(
            db_session,
            workspace_id=workspace.id,
            context_kind=ContextKind.WORKSPACE,
            scope_key_sha256=SCOPE,
            access_scope_sha256_value=access_scope_sha256(alice),
            delivery_profile_sha256_value=DELIVERY,
            observation={
                "snapshot": observation_name,
                "source_document_id": str(source.id),
            },
            artifact={
                "content": content,
                "evidence": {"source_document_id": str(source.id)},
            },
            content=content,
            claims=(
                _claim().model_copy(
                    update={"evidence_refs": (f"source_document:{source.id}",)}
                ),
            ),
            evaluation_metadata=_metadata(score=score),
            artifact_schema_version="workspace_foundation.v2",
            compiler_version="permission-manifest-regression.v1",
            renderer_version="permission-manifest-renderer.v1",
            policy_name="workspace_foundation",
            access_scope=alice,
        )

    active = await reconcile_restricted(
        observation_name="restricted-active",
        content="Workspace background containing restricted HSM evidence.",
        score=100.0,
    )
    assert active.copy_allowed is True
    review = await reconcile_restricted(
        observation_name="restricted-review",
        content="Revised restricted background requiring explicit review.",
        score=60.0,
    )
    assert review.status == "review_required"
    assert review.pointer_generation == active.pointer_generation

    async def alice_scope() -> AccessScope:
        return alice

    app.dependency_overrides[get_access_scope] = alice_scope
    try:
        listed = await client.get(
            "/api/context-quality/candidates",
            params={
                "workspace_id": str(workspace.id),
                "context_kind": "workspace",
                "include_content": True,
            },
        )
        assert listed.status_code == 200, listed.text
        authorized_items = {
            item["candidate_id"]: item for item in listed.json()["candidates"]
        }
        active_item = authorized_items[active.candidate_id]
        assert active_item["permissions_current"] is True
        assert active_item["active"] is True
        assert active_item["copy_allowed"] is True
        assert active_item["content"] == (
            "Workspace background containing restricted HSM evidence."
        )

        await db_session.delete(grant)
        await db_session.flush()

        revoked = await client.get(
            "/api/context-quality/candidates",
            params={
                "workspace_id": str(workspace.id),
                "context_kind": "workspace",
                "include_content": True,
            },
        )
        assert revoked.status_code == 200, revoked.text
        revoked_items = {
            item["candidate_id"]: item for item in revoked.json()["candidates"]
        }
        for candidate_id in (active.candidate_id, review.candidate_id):
            item = revoked_items[candidate_id]
            assert item["permissions_current"] is False
            assert item["active"] is False
            assert item["copy_allowed"] is False
            assert "content" not in item

        activation = await client.post(
            f"/api/context-quality/candidates/{review.candidate_id}/activate",
            json={
                "workspace_id": str(workspace.id),
                "expected_generation": review.pointer_generation,
                "evaluation_id": review.evaluation_id,
                "reason": "Permission-revoked evidence must be regenerated.",
            },
        )
        assert activation.status_code == 409, activation.text
    finally:
        app.dependency_overrides.pop(get_access_scope, None)


async def test_candidate_list_revokes_copy_when_session_tip_moves(
    client,
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="codex",
        external_id=f"session-runtime-{uuid4().hex}",
        content="Session source",
        metadata_json="{}",
    )
    db_session.add(source)
    await db_session.flush()
    provider = "codex"
    session_id = f"runtime-{uuid4().hex}"
    boundary = SessionEvent(
        id=uuid4(),
        workspace_id=workspace.id,
        source_document_id=source.id,
        provider=provider,
        session_id=session_id,
        provider_event_id="event-1",
        sequence_number=1,
        event_type="user_request",
        role="user",
        content="Explain the current background.",
        content_sha256=hashlib.sha256(b"event-1").hexdigest(),
    )
    db_session.add(boundary)
    await db_session.flush()
    content = (
        "# Session Context\n\nPrior objective: explain the current background.\n\n"
        "## Awaiting user instruction\n"
    )
    claim = ContextClaimEnvelope(
        stable_id="session.goal:runtime",
        section="goal",
        kind="prior_user_objective",
        statement="Explain the current background.",
        scope=ContextKind.SESSION,
        authority="direct_user",
        truth_state="historical",
        criticality=ClaimCriticality.CRITICAL,
        evidence_refs=(str(boundary.id),),
        session_boundary_id=str(boundary.id),
    )
    active = await reconcile_context_candidate(
        db_session,
        workspace_id=workspace.id,
        context_kind=ContextKind.SESSION,
        scope_key_sha256="7" * 64,
        access_scope_sha256_value=ACCESS,
        delivery_profile_sha256_value=DELIVERY,
        observation={
            "source_document_id": str(source.id),
            "provider": provider,
            "session_id": session_id,
        },
        artifact={"source_document_id": str(source.id), "content": content},
        content=content,
        claims=(claim,),
        evaluation_metadata={
            "context_role": "background_only",
            "copy_ready": True,
            "hash_valid": True,
            "snapshot_current": True,
            "permissions_current": True,
            "required_dependencies_complete": True,
        },
        artifact_schema_version="session_context.v2",
        compiler_version="runtime-current-regression.v1",
        renderer_version="session_context_background.v1",
        policy_name="session_background",
        boundary_event_id=boundary.id,
        access_scope=AccessScope.local(),
    )
    assert active.copy_allowed is True

    before = await client.get(
        "/api/context-quality/candidates",
        params={
            "workspace_id": str(workspace.id),
            "context_kind": "session",
            "include_content": True,
        },
    )
    assert before.status_code == 200, before.text
    before_item = before.json()["candidates"][0]
    assert before_item["runtime_current"] is True
    assert before_item["copy_allowed"] is True

    db_session.add(SessionEvent(
        id=uuid4(),
        workspace_id=workspace.id,
        source_document_id=source.id,
        provider=provider,
        session_id=session_id,
        provider_event_id="event-2",
        sequence_number=2,
        event_type="assistant_update",
        role="assistant",
        content="Newer state.",
        content_sha256=hashlib.sha256(b"event-2").hexdigest(),
    ))
    await db_session.flush()

    after = await client.get(
        "/api/context-quality/candidates",
        params={
            "workspace_id": str(workspace.id),
            "context_kind": "session",
            "include_content": True,
        },
    )
    assert after.status_code == 200, after.text
    after_item = after.json()["candidates"][0]
    assert after_item["runtime_current"] is False
    assert after_item["active"] is False
    assert after_item["copy_allowed"] is False
