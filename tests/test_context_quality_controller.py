from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models import (
    ActiveContextPointer,
    ContextActivationEvent,
    ContextArtifactCandidate,
    ContextCandidateEvaluation,
    ContextObservationBundle,
    Workspace,
)
from app.schemas.context_quality import (
    ClaimCriticality,
    ContextClaimEnvelope,
    ContextKind,
)
from app.services.access import AccessScope
from app.services.context_quality import (
    ContextRollbackUnsafe,
    access_scope_sha256,
    activate_reviewed_candidate,
    reconcile_context_candidate,
    record_active_context_outcome,
    rollback_active_context,
)


ACCESS = access_scope_sha256(AccessScope.local())
DELIVERY = "b" * 64
SCOPE = "c" * 64


def _claim(statement: str = "The product preserves evidence history.") -> ContextClaimEnvelope:
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


def _metadata(*, score: float = 100.0) -> dict:
    return {
        "objective_independent": True,
        "copy_ready": True,
        "hash_valid": True,
        "snapshot_current": True,
        "permissions_current": True,
        "durable_fact_count": 1,
        "verification_complete": True,
        "semantic_coverage_score": score,
    }


async def _workspace(db_session) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        name="Context quality controller",
        slug=f"context-quality-{uuid4().hex}",
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
    claims: tuple[ContextClaimEnvelope, ...],
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
        claims=claims,
        evaluation_metadata=metadata or _metadata(),
        artifact_schema_version="workspace_foundation.v2",
        compiler_version="test-compiler.v1",
        renderer_version="test-renderer.v1",
        policy_name="workspace_foundation",
        access_scope=AccessScope.local(),
    )


async def test_reject_preserves_active_pointer_and_review_requires_cas(db_session):
    workspace = await _workspace(db_session)
    first = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "one"},
        content="Workspace background one",
        claims=(_claim(),),
    )
    assert first.status == "active"
    assert first.copy_allowed is True

    rejected = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "two"},
        content="Workspace background missing its purpose",
        claims=(),
    )
    assert rejected.status == "rejected"
    assert rejected.copy_allowed is False
    assert rejected.active_candidate_id == first.candidate_id

    review = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "three"},
        content="Workspace background with incomplete verification",
        claims=(_claim(),),
        metadata=_metadata(score=60.0),
    )
    assert review.status == "review_required"
    assert review.active_candidate_id == first.candidate_id

    with pytest.raises(LookupError):
        await activate_reviewed_candidate(
            db_session,
            workspace_id=workspace.id,
            candidate_id=UUID(review.candidate_id),
            expected_generation=review.pointer_generation,
            access_scope_sha256_value="d" * 64,
            actor="wrong-principal",
            reason="Must not cross an evidence access scope.",
        )

    activated = await activate_reviewed_candidate(
        db_session,
        workspace_id=workspace.id,
        candidate_id=UUID(review.candidate_id),
        expected_generation=review.pointer_generation,
        access_scope_sha256_value=ACCESS,
        actor="reviewer",
        reason="Reviewed the explicit coverage gaps for this frozen snapshot.",
    )
    assert activated.status == "active"
    assert activated.candidate_id == review.candidate_id
    assert activated.pointer_generation == review.pointer_generation + 1

    pointer = await db_session.scalar(select(ActiveContextPointer).where(
        ActiveContextPointer.workspace_id == workspace.id
    ))
    assert pointer is not None
    assert str(pointer.active_candidate_id) == review.candidate_id
    assert await db_session.scalar(select(ContextObservationBundle.id)) is not None
    assert await db_session.scalar(select(ContextArtifactCandidate.id)) is not None
    assert await db_session.scalar(select(ContextCandidateEvaluation.id)) is not None

    refreshed = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "three"},
        content="Workspace background with incomplete verification",
        claims=(_claim(),),
        metadata=_metadata(score=60.0),
    )
    assert refreshed.candidate_id == review.candidate_id
    assert refreshed.decision.value == "review"
    assert refreshed.status == "active"
    assert refreshed.copy_allowed is True
    assert refreshed.pointer_generation == activated.pointer_generation


async def test_identical_candidate_preserves_lineage_and_does_not_bump_pointer(
    db_session,
):
    workspace = await _workspace(db_session)
    claim = _claim().model_copy(update={
        "repository_snapshot_sha256": "d" * 64,
        "session_boundary_id": str(uuid4()),
    })
    first = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "stable"},
        content="Workspace background with stable lineage",
        claims=(claim,),
    )

    repeated = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "stable"},
        content="Workspace background with stable lineage",
        claims=(claim,),
    )

    assert repeated.candidate_id == first.candidate_id
    assert repeated.decision.value == "no_change"
    assert repeated.pointer_generation == first.pointer_generation


async def test_rollback_requires_same_observation_snapshot(db_session):
    workspace = await _workspace(db_session)
    first = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "same"},
        content="Workspace background version one",
        claims=(_claim(),),
    )
    second = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "same"},
        content="Workspace background version two",
        claims=(_claim("The product preserves immutable evidence history."),),
    )
    pointer = await db_session.scalar(select(ActiveContextPointer).where(
        ActiveContextPointer.workspace_id == workspace.id
    ))
    assert pointer is not None
    rolled_back = await rollback_active_context(
        db_session,
        workspace_id=workspace.id,
        pointer_id=pointer.id,
        target_candidate_id=UUID(first.candidate_id),
        expected_generation=second.pointer_generation,
        access_scope_sha256_value=ACCESS,
        actor="reviewer",
        reason="The new renderer obscured a critical fact.",
    )
    assert rolled_back.candidate_id == first.candidate_id
    assert rolled_back.status == "active"

    changed_snapshot = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "new"},
        content="Workspace background on a new snapshot",
        claims=(_claim("The product preserves evidence history on a new snapshot."),),
    )
    with pytest.raises(ContextRollbackUnsafe):
        await rollback_active_context(
            db_session,
            workspace_id=workspace.id,
            pointer_id=pointer.id,
            target_candidate_id=UUID(first.candidate_id),
            expected_generation=changed_snapshot.pointer_generation,
            access_scope_sha256_value=ACCESS,
            actor="reviewer",
            reason="Cross-snapshot rollback must fail closed.",
        )


async def test_rollback_cannot_bypass_review_for_never_active_candidate(db_session):
    workspace = await _workspace(db_session)
    active = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "same"},
        content="Active Workspace background",
        claims=(_claim(),),
    )
    review = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "same"},
        content="Never-active Workspace background requiring review",
        claims=(_claim("The product preserves reviewed evidence history."),),
        metadata=_metadata(score=60.0),
    )
    pointer = await db_session.scalar(select(ActiveContextPointer).where(
        ActiveContextPointer.workspace_id == workspace.id
    ))
    assert pointer is not None
    assert str(pointer.active_candidate_id) == active.candidate_id

    with pytest.raises(ContextRollbackUnsafe):
        await rollback_active_context(
            db_session,
            workspace_id=workspace.id,
            pointer_id=pointer.id,
            target_candidate_id=UUID(review.candidate_id),
            expected_generation=review.pointer_generation,
            access_scope_sha256_value=ACCESS,
            actor="reviewer",
            reason="Rollback must not serve as an unreviewed activation path.",
        )


async def test_harmful_outcome_quarantines_and_revokes_copy(db_session):
    workspace = await _workspace(db_session)
    active = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "one"},
        content="Workspace background",
        claims=(_claim(),),
    )
    pointer = await db_session.scalar(select(ActiveContextPointer).where(
        ActiveContextPointer.workspace_id == workspace.id
    ))
    assert pointer is not None

    quarantined = await record_active_context_outcome(
        db_session,
        workspace_id=workspace.id,
        pointer_id=pointer.id,
        expected_generation=active.pointer_generation,
        access_scope_sha256_value=ACCESS,
        outcome="unsafe",
        actor="user",
        reason="The context caused an unsafe edit suggestion.",
    )
    assert quarantined.status == "quarantined"
    assert quarantined.copy_allowed is False
    assert quarantined.active_candidate_id is None
    await db_session.refresh(pointer)
    assert pointer.active_candidate_id is None
    event = await db_session.scalar(
        select(ContextActivationEvent)
        .where(ContextActivationEvent.pointer_id == pointer.id)
        .order_by(ContextActivationEvent.generation.desc())
        .limit(1)
    )
    assert event is not None
    assert event.action == "quarantine"


async def test_review_and_outcome_api_expose_the_control_loop(client, db_session):
    workspace = await _workspace(db_session)
    review = await _reconcile(
        db_session,
        workspace,
        observation={"snapshot": "review"},
        content="Workspace background requiring review",
        claims=(_claim(),),
        metadata=_metadata(score=60.0),
    )
    assert review.status == "review_required"

    listed = await client.get(
        "/api/context-quality/candidates",
        params={
            "workspace_id": str(workspace.id),
            "context_kind": "workspace",
            "include_content": True,
        },
    )
    assert listed.status_code == 200
    candidate = listed.json()["candidates"][0]
    assert candidate["candidate_id"] == review.candidate_id
    assert candidate["decision"] == "review"
    assert candidate["copy_allowed"] is False
    assert candidate["content"] == "Workspace background requiring review"

    activated = await client.post(
        f"/api/context-quality/candidates/{review.candidate_id}/activate",
        json={
            "workspace_id": str(workspace.id),
            "expected_generation": review.pointer_generation,
            "evaluation_id": review.evaluation_id,
            "reason": "Reviewed the bounded coverage warning.",
        },
    )
    assert activated.status_code == 200, activated.text
    active_control = activated.json()["quality_control"]
    assert active_control["status"] == "active"
    assert active_control["copy_allowed"] is True

    quarantined = await client.post(
        f"/api/context-quality/pointers/{candidate['pointer_id']}/outcome",
        json={
            "workspace_id": str(workspace.id),
            "expected_generation": active_control["pointer_generation"],
            "outcome": "incorrect",
            "reason": "The context omitted a reviewed product boundary.",
        },
    )
    assert quarantined.status_code == 200, quarantined.text
    quarantine_control = quarantined.json()["quality_control"]
    assert quarantine_control["status"] == "quarantined"
    assert quarantine_control["copy_allowed"] is False


async def test_workspace_prepare_returns_hash_bound_non_active_candidate_for_gaps(
    client, db_session
):
    workspace = await _workspace(db_session)
    response = await client.post(
        "/api/context/prepare",
        json={
            "workspace_id": str(workspace.id),
            "mode": "project_snapshot",
            "objective_origin": "project_snapshot",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    control = payload["quality_control"]
    assert control["schema_version"] == "context_quality_activation.v1"
    assert control["status"] in {"review_required", "rejected"}
    assert control["copy_allowed"] is False
    assert control["artifact_sha256"] == payload["manifest"]["rendering"][
        "markdown_sha256"
    ]
    assert control["candidate_id"] != control["active_candidate_id"]
