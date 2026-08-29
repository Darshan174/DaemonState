from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActiveContextPointer,
    ContextActivationEvent,
    ContextArtifactCandidate,
    ContextArtifactClaim,
    ContextCandidateEvaluation,
    ContextObservationBundle,
    SessionEvent,
    SourceDocument,
    SourceReadGrant,
)
from app.schemas.context_quality import (
    CONTEXT_QUALITY_POLICY_VERSION,
    ContextClaimEnvelope,
    ContextDecision,
    ContextKind,
    ContextQualityActivation,
    ContextQualityEvaluation,
    canonical_json,
    canonical_sha256,
)
from app.services.access import AccessScope, source_access_predicate
from app.services.context_quality_policies import (
    evaluate_context_candidate,
    semantic_claim_hash,
)
from app.time import utc_now


CONTEXT_QUALITY_GENERATOR_VERSION = "context_quality_controller.v1"


class ContextActivationConflict(RuntimeError):
    pass


class ContextRollbackUnsafe(RuntimeError):
    pass


class ContextEvidenceStale(ContextRollbackUnsafe):
    """The evidence or permission boundary no longer matches a candidate."""


def collect_source_document_ids(*values: Any) -> tuple[UUID, ...]:
    """Collect exact source revision IDs named by a compiled artifact."""

    found: set[UUID] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key == "source_document_id" and child not in (None, ""):
                    try:
                        found.add(UUID(str(child)))
                    except (TypeError, ValueError):
                        pass
                else:
                    visit(child)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for child in value:
                visit(child)

    for value in values:
        visit(value)
    return tuple(sorted(found, key=str))


async def _permission_manifest_sha256(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    access_scope: AccessScope,
    source_document_ids: Iterable[UUID],
) -> str:
    source_ids = tuple(sorted(set(source_document_ids), key=str))
    rows = list(await session.scalars(
        select(SourceDocument)
        .where(
            SourceDocument.id.in_(source_ids),
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
        .order_by(SourceDocument.id)
        .with_for_update()
    )) if source_ids else []
    if len(rows) != len(source_ids):
        raise ContextEvidenceStale(
            "Context evidence is no longer readable under the current permission snapshot."
        )

    identities = {row.source_identity_sha256 for row in rows}
    latest_revisions = {
        str(identity): int(revision or 0)
        for identity, revision in (
            await session.execute(
                select(
                    SourceDocument.source_identity_sha256,
                    func.max(SourceDocument.revision_number),
                )
                .where(SourceDocument.source_identity_sha256.in_(identities))
                .group_by(SourceDocument.source_identity_sha256)
            )
        ).all()
    } if identities else {}
    grants_by_source: dict[str, list[str]] = {}
    if rows and not access_scope.unrestricted:
        grants = list(await session.scalars(
            select(SourceReadGrant).where(
                SourceReadGrant.source_document_id.in_([row.id for row in rows]),
                SourceReadGrant.workspace_id == workspace_id,
                SourceReadGrant.principal_id == access_scope.principal_id,
            ).with_for_update()
        ))
        for grant in grants:
            grants_by_source.setdefault(str(grant.source_document_id), []).append(
                canonical_sha256({
                    "grant_key": grant.grant_key,
                    "permission_snapshot_sha256": grant.permission_snapshot_sha256,
                })
            )
        for row in rows:
            if (
                row.visibility_scope == "restricted"
                and not any(
                    grant.source_document_id == row.id
                    and grant.permission_snapshot_sha256
                    == row.permission_snapshot_sha256
                    for grant in grants
                )
            ):
                raise ContextEvidenceStale(
                    "A restricted Context source grant was revoked during evaluation."
                )

    return canonical_sha256({
        "schema_version": "context_permission_manifest.v1",
        "workspace_id": str(workspace_id),
        "principal_id": access_scope.principal_id,
        "unrestricted": access_scope.unrestricted,
        "sources": [
            {
                "source_document_id": str(row.id),
                "source_identity_sha256": row.source_identity_sha256,
                "revision_number": row.revision_number,
                "latest_revision_number": latest_revisions.get(
                    row.source_identity_sha256, row.revision_number
                ),
                "content_sha256": row.content_sha256,
                "visibility_scope": row.visibility_scope,
                "permission_source": row.permission_source,
                "permission_snapshot_sha256": row.permission_snapshot_sha256,
                "grant_snapshots": sorted(grants_by_source.get(str(row.id), [])),
            }
            for row in rows
        ],
    })


def access_scope_sha256(access_scope: AccessScope) -> str:
    return canonical_sha256({
        "principal_id": access_scope.principal_id,
        "unrestricted": access_scope.unrestricted,
        "workspace_ids": sorted(str(item) for item in access_scope.workspace_ids),
    })


def context_scope_key_sha256(
    *,
    workspace_id: UUID,
    context_kind: ContextKind,
    repository_identity: str | None = None,
    provider: str | None = None,
    session_id: str | None = None,
) -> str:
    if context_kind is ContextKind.SESSION:
        if not provider or not session_id:
            raise ValueError("session context scope requires provider and session_id")
        identity: dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "context_kind": context_kind.value,
            "provider": str(provider).strip().casefold(),
            "session_id": str(session_id).strip(),
        }
    else:
        identity = {
            "workspace_id": str(workspace_id),
            "context_kind": context_kind.value,
            "repository_identity": str(repository_identity or "workspace_only").strip(),
        }
    return canonical_sha256(identity)


def delivery_profile_sha256(
    *,
    artifact_schema_version: str,
    renderer_version: str,
    target_model: str | None,
    token_budget: int | None,
) -> str:
    budget_class = (
        "default"
        if token_budget is None
        else "small"
        if token_budget < 4_000
        else "medium"
        if token_budget < 16_000
        else "large"
    )
    return canonical_sha256({
        "artifact_schema_version": artifact_schema_version,
        "renderer_version": renderer_version,
        "target_model": str(target_model or "default").strip().casefold(),
        "token_budget_class": budget_class,
    })


async def reconcile_context_candidate(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    context_kind: ContextKind,
    scope_key_sha256: str,
    access_scope_sha256_value: str,
    delivery_profile_sha256_value: str,
    observation: Mapping[str, Any],
    artifact: Mapping[str, Any],
    content: str,
    claims: Iterable[ContextClaimEnvelope],
    evaluation_metadata: Mapping[str, Any],
    artifact_schema_version: str,
    compiler_version: str,
    renderer_version: str,
    policy_name: str,
    checkpoint_id: UUID | None = None,
    boundary_event_id: UUID | None = None,
    context_pack_id: UUID | None = None,
    repository_identity_sha256: str | None = None,
    repository_snapshot_sha256: str | None = None,
    evidence_source_document_ids: Iterable[UUID] = (),
    access_scope: AccessScope | None = None,
    actor: str = "system",
) -> ContextQualityActivation:
    """Persist, evaluate, and conditionally activate one immutable candidate."""

    claim_values = tuple(claims)
    observation_payload = dict(observation)
    if access_scope is not None:
        if access_scope_sha256(access_scope) != access_scope_sha256_value:
            raise ContextEvidenceStale(
                "The authenticated evidence scope does not match the Context candidate."
            )
        evidence_source_ids = tuple(sorted(
            {
                *collect_source_document_ids(observation_payload, artifact),
                *evidence_source_document_ids,
            },
            key=str,
        ))
        observation_payload["evidence_source_document_ids"] = [
            str(item) for item in evidence_source_ids
        ]
        observation_payload["permission_manifest_sha256"] = (
            await _permission_manifest_sha256(
                session,
                workspace_id=workspace_id,
                access_scope=access_scope,
                source_document_ids=evidence_source_ids,
            )
        )
    observation_sha = canonical_sha256(observation_payload)
    observation_key = canonical_sha256({
        "workspace_id": str(workspace_id),
        "context_kind": context_kind.value,
        "scope_key_sha256": scope_key_sha256,
        "access_scope_sha256": access_scope_sha256_value,
        "delivery_profile_sha256": delivery_profile_sha256_value,
        "observation_sha256": observation_sha,
    })
    bundle = await _observation_bundle(
        session,
        workspace_id=workspace_id,
        context_kind=context_kind,
        scope_key_sha256=scope_key_sha256,
        access_scope_sha256_value=access_scope_sha256_value,
        delivery_profile_sha256_value=delivery_profile_sha256_value,
        checkpoint_id=checkpoint_id,
        boundary_event_id=boundary_event_id,
        repository_identity_sha256=repository_identity_sha256,
        repository_snapshot_sha256=repository_snapshot_sha256,
        observation_payload=observation_payload,
        observation_sha=observation_sha,
        idempotency_key=observation_key,
    )

    content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    artifact_payload = dict(artifact)
    artifact_sha = canonical_sha256(artifact_payload)
    semantic_sha = semantic_claim_hash(claim_values)
    candidate_key = canonical_sha256({
        "observation_bundle_id": str(bundle.id),
        "artifact_schema_version": artifact_schema_version,
        "compiler_version": compiler_version,
        "renderer_version": renderer_version,
        "policy_version": CONTEXT_QUALITY_POLICY_VERSION,
        "artifact_sha256": artifact_sha,
        "content_sha256": content_sha,
        "semantic_sha256": semantic_sha,
    })
    candidate, created = await _artifact_candidate(
        session,
        observation_bundle=bundle,
        workspace_id=workspace_id,
        context_kind=context_kind,
        scope_key_sha256=scope_key_sha256,
        access_scope_sha256_value=access_scope_sha256_value,
        delivery_profile_sha256_value=delivery_profile_sha256_value,
        context_pack_id=context_pack_id,
        checkpoint_id=checkpoint_id,
        artifact_schema_version=artifact_schema_version,
        compiler_version=compiler_version,
        renderer_version=renderer_version,
        artifact_payload=artifact_payload,
        content=content,
        artifact_sha=artifact_sha,
        content_sha=content_sha,
        semantic_sha=semantic_sha,
        idempotency_key=candidate_key,
    )
    if created:
        session.add_all([
            ContextArtifactClaim(
                candidate_id=candidate.id,
                claim_key=claim.stable_id,
                section=claim.section,
                claim_kind=claim.kind,
                ordinal=index,
                statement=claim.statement,
                statement_sha256=claim.statement_sha256,
                authority=claim.authority,
                truth_state=claim.truth_state,
                criticality=claim.criticality.value,
                selection_decision=claim.selection.value,
                exclusion_reason=claim.exclusion_reason,
                exclusion_detail=None,
                evidence_refs_json=canonical_json(list(claim.evidence_refs)),
                evidence_refs_sha256=claim.evidence_sha256,
                repository_snapshot_sha256=claim.repository_snapshot_sha256,
                session_boundary_id=claim.session_boundary_id,
            )
            for index, claim in enumerate(claim_values)
        ])
        await session.flush()

    pointer = await _active_pointer(
        session,
        workspace_id=workspace_id,
        context_kind=context_kind,
        scope_key_sha256=scope_key_sha256,
        access_scope_sha256_value=access_scope_sha256_value,
        delivery_profile_sha256_value=delivery_profile_sha256_value,
    )
    baseline_id = pointer.active_candidate_id
    active_claims = (
        await _claims_for_candidate(session, baseline_id, context_kind=context_kind)
        if baseline_id is not None
        else ()
    )
    candidate_quarantined = await _candidate_is_quarantined(
        session,
        pointer_id=pointer.id,
        candidate_id=candidate.id,
    )
    evaluation = evaluate_context_candidate(
        context_kind=context_kind,
        candidate_claims=claim_values,
        active_claims=active_claims,
        rendered_text=content,
        metadata={
            **dict(evaluation_metadata),
            "candidate_quarantined": candidate_quarantined,
        },
    )
    evaluation_row = await _candidate_evaluation(
        session,
        candidate_id=candidate.id,
        baseline_candidate_id=baseline_id,
        baseline_generation=pointer.generation,
        policy_name=policy_name,
        evaluation=evaluation,
    )
    review_approval_carried = (
        evaluation.decision is ContextDecision.REVIEW
        and pointer.active_candidate_id == candidate.id
        and await _candidate_review_approval_is_current(
            session,
            pointer_id=pointer.id,
            candidate_id=candidate.id,
            evaluation=evaluation_row,
        )
    )

    if (
        (
            evaluation.decision is ContextDecision.NO_CHANGE
            or review_approval_carried
        )
        and pointer.active_candidate_id == candidate.id
    ):
        await _bind_active_evaluation(
            session,
            pointer=pointer,
            candidate=candidate,
            evaluation=evaluation_row,
        )
        await session.refresh(pointer)
    elif evaluation.decision in {ContextDecision.PROMOTE, ContextDecision.NO_CHANGE}:
        await _activate_candidate(
            session,
            pointer=pointer,
            candidate=candidate,
            evaluation=evaluation_row,
            actor=actor,
            action=(
                "no_change"
                if evaluation.decision is ContextDecision.NO_CHANGE
                else "activate"
            ),
            reason="Candidate passed deterministic context-quality policy.",
        )
    elif pointer.active_candidate_id == candidate.id:
        await _deactivate_candidate(
            session,
            pointer=pointer,
            candidate=candidate,
            evaluation=evaluation_row,
            actor=actor,
            reason=(
                "The active Context failed its latest evaluation and copy authority "
                "was revoked."
            ),
        )
    else:
        await session.refresh(pointer)

    active = (
        pointer.active_candidate_id == candidate.id
        and pointer.active_evaluation_id == evaluation_row.id
        and (
            evaluation.decision in {
                ContextDecision.PROMOTE,
                ContextDecision.NO_CHANGE,
            }
            or review_approval_carried
        )
    )
    status = (
        "active"
        if active
        else "review_required"
        if evaluation.decision is ContextDecision.REVIEW
        else "rejected"
    )
    return ContextQualityActivation(
        status=status,
        copy_allowed=active,
        candidate_id=str(candidate.id),
        active_candidate_id=(
            str(pointer.active_candidate_id) if pointer.active_candidate_id else None
        ),
        observation_sha256=observation_sha,
        artifact_sha256=content_sha,
        semantic_sha256=semantic_sha,
        evaluation_id=str(evaluation_row.id),
        pointer_generation=pointer.generation,
        decision=evaluation.decision,
    )


async def _observation_bundle(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    context_kind: ContextKind,
    scope_key_sha256: str,
    access_scope_sha256_value: str,
    delivery_profile_sha256_value: str,
    checkpoint_id: UUID | None,
    boundary_event_id: UUID | None,
    repository_identity_sha256: str | None,
    repository_snapshot_sha256: str | None,
    observation_payload: Mapping[str, Any],
    observation_sha: str,
    idempotency_key: str,
) -> ContextObservationBundle:
    existing = await session.scalar(select(ContextObservationBundle).where(
        ContextObservationBundle.idempotency_key == idempotency_key
    ))
    if existing is not None:
        return existing
    row = ContextObservationBundle(
        workspace_id=workspace_id,
        context_kind=context_kind.value,
        scope_key_sha256=scope_key_sha256,
        access_scope_sha256=access_scope_sha256_value,
        delivery_profile_sha256=delivery_profile_sha256_value,
        checkpoint_id=checkpoint_id,
        boundary_event_id=boundary_event_id,
        repository_identity_sha256=repository_identity_sha256,
        repository_snapshot_sha256=repository_snapshot_sha256,
        observation_json=canonical_json(observation_payload),
        observation_sha256=observation_sha,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(ContextObservationBundle).where(
            ContextObservationBundle.idempotency_key == idempotency_key
        ))
        if existing is None:
            raise
        return existing
    return row


async def _artifact_candidate(
    session: AsyncSession,
    *,
    observation_bundle: ContextObservationBundle,
    workspace_id: UUID,
    context_kind: ContextKind,
    scope_key_sha256: str,
    access_scope_sha256_value: str,
    delivery_profile_sha256_value: str,
    context_pack_id: UUID | None,
    checkpoint_id: UUID | None,
    artifact_schema_version: str,
    compiler_version: str,
    renderer_version: str,
    artifact_payload: Mapping[str, Any],
    content: str,
    artifact_sha: str,
    content_sha: str,
    semantic_sha: str,
    idempotency_key: str,
) -> tuple[ContextArtifactCandidate, bool]:
    existing = await session.scalar(select(ContextArtifactCandidate).where(
        ContextArtifactCandidate.idempotency_key == idempotency_key
    ))
    if existing is not None:
        return existing, False
    row = ContextArtifactCandidate(
        observation_bundle_id=observation_bundle.id,
        workspace_id=workspace_id,
        context_kind=context_kind.value,
        scope_key_sha256=scope_key_sha256,
        access_scope_sha256=access_scope_sha256_value,
        delivery_profile_sha256=delivery_profile_sha256_value,
        context_pack_id=context_pack_id,
        checkpoint_id=checkpoint_id,
        artifact_schema_version=artifact_schema_version,
        generator_version=CONTEXT_QUALITY_GENERATOR_VERSION,
        compiler_version=compiler_version,
        renderer_version=renderer_version,
        policy_version=CONTEXT_QUALITY_POLICY_VERSION,
        artifact_json=canonical_json(artifact_payload),
        content=content,
        artifact_sha256=artifact_sha,
        content_sha256=content_sha,
        semantic_sha256=semantic_sha,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(ContextArtifactCandidate).where(
            ContextArtifactCandidate.idempotency_key == idempotency_key
        ))
        if existing is None:
            raise
        return existing, False
    return row, True


async def _active_pointer(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    context_kind: ContextKind,
    scope_key_sha256: str,
    access_scope_sha256_value: str,
    delivery_profile_sha256_value: str,
) -> ActiveContextPointer:
    predicate = (
        ActiveContextPointer.workspace_id == workspace_id,
        ActiveContextPointer.context_kind == context_kind.value,
        ActiveContextPointer.scope_key_sha256 == scope_key_sha256,
        ActiveContextPointer.access_scope_sha256 == access_scope_sha256_value,
        ActiveContextPointer.delivery_profile_sha256 == delivery_profile_sha256_value,
    )
    existing = await session.scalar(
        select(ActiveContextPointer).where(*predicate).with_for_update()
    )
    if existing is not None:
        return existing
    row = ActiveContextPointer(
        workspace_id=workspace_id,
        context_kind=context_kind.value,
        scope_key_sha256=scope_key_sha256,
        access_scope_sha256=access_scope_sha256_value,
        delivery_profile_sha256=delivery_profile_sha256_value,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(ActiveContextPointer).where(*predicate).with_for_update()
        )
        if existing is None:
            raise
        return existing
    return row


async def _claims_for_candidate(
    session: AsyncSession,
    candidate_id: UUID,
    *,
    context_kind: ContextKind,
) -> tuple[ContextClaimEnvelope, ...]:
    rows = list(await session.scalars(
        select(ContextArtifactClaim)
        .where(ContextArtifactClaim.candidate_id == candidate_id)
        .order_by(ContextArtifactClaim.ordinal, ContextArtifactClaim.claim_key)
    ))
    result: list[ContextClaimEnvelope] = []
    for row in rows:
        try:
            refs = json.loads(row.evidence_refs_json or "[]")
        except (TypeError, json.JSONDecodeError):
            refs = []
        result.append(ContextClaimEnvelope(
            stable_id=row.claim_key,
            section=row.section,
            kind=row.claim_kind,
            statement=row.statement,
            scope=context_kind,
            authority=row.authority,
            truth_state=row.truth_state,
            criticality=row.criticality,
            selection=row.selection_decision,
            exclusion_reason=row.exclusion_reason,
            evidence_refs=tuple(str(item) for item in refs),
            repository_snapshot_sha256=row.repository_snapshot_sha256,
            session_boundary_id=row.session_boundary_id,
        ))
    return tuple(result)


async def _candidate_evaluation(
    session: AsyncSession,
    *,
    candidate_id: UUID,
    baseline_candidate_id: UUID | None,
    baseline_generation: int,
    policy_name: str,
    evaluation: ContextQualityEvaluation,
) -> ContextCandidateEvaluation:
    idempotency_key = canonical_sha256({
        "candidate_id": str(candidate_id),
        "baseline_candidate_id": str(baseline_candidate_id) if baseline_candidate_id else None,
        "baseline_generation": baseline_generation,
        "policy_name": policy_name,
        "evaluation_sha256": evaluation.sha256,
    })
    existing = await session.scalar(select(ContextCandidateEvaluation).where(
        ContextCandidateEvaluation.idempotency_key == idempotency_key
    ))
    if existing is not None:
        return existing
    row = ContextCandidateEvaluation(
        candidate_id=candidate_id,
        baseline_candidate_id=baseline_candidate_id,
        baseline_generation=baseline_generation,
        policy_name=policy_name,
        policy_version=evaluation.policy_version,
        decision=evaluation.decision.value,
        diff_json=canonical_json(evaluation.diff.model_dump(mode="json")),
        hard_failures_json=canonical_json(list(evaluation.hard_failures)),
        warnings_json=canonical_json(list(evaluation.warnings)),
        metrics_json=canonical_json(evaluation.quality_vector),
        evaluation_sha256=evaluation.sha256,
        idempotency_key=idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(ContextCandidateEvaluation).where(
            ContextCandidateEvaluation.idempotency_key == idempotency_key
        ))
        if existing is None:
            raise
        return existing
    return row


async def _candidate_is_quarantined(
    session: AsyncSession,
    *,
    pointer_id: UUID,
    candidate_id: UUID,
) -> bool:
    event_id = await session.scalar(
        select(ContextActivationEvent.id)
        .where(
            ContextActivationEvent.pointer_id == pointer_id,
            ContextActivationEvent.action == "quarantine",
            ContextActivationEvent.from_candidate_id == candidate_id,
        )
        .limit(1)
    )
    return event_id is not None


async def _candidate_review_approval_is_current(
    session: AsyncSession,
    *,
    pointer_id: UUID,
    candidate_id: UUID,
    evaluation: ContextCandidateEvaluation,
) -> bool:
    """Carry an explicit review only for the same immutable candidate/warnings."""

    approval = await session.scalar(
        select(ContextActivationEvent)
        .where(
            ContextActivationEvent.pointer_id == pointer_id,
            ContextActivationEvent.action == "activate_reviewed",
            ContextActivationEvent.to_candidate_id == candidate_id,
        )
        .order_by(
            ContextActivationEvent.generation.desc(),
            ContextActivationEvent.created_at.desc(),
            ContextActivationEvent.id.desc(),
        )
        .limit(1)
    )
    if approval is None or approval.evaluation_id is None:
        return False
    invalidating_event = await session.scalar(
        select(ContextActivationEvent.id)
        .where(
            ContextActivationEvent.pointer_id == pointer_id,
            ContextActivationEvent.from_candidate_id == candidate_id,
            ContextActivationEvent.action.in_(["invalidate", "quarantine"]),
            ContextActivationEvent.generation > approval.generation,
        )
        .limit(1)
    )
    if invalidating_event is not None:
        return False
    approved_evaluation = await session.get(
        ContextCandidateEvaluation, approval.evaluation_id
    )
    if (
        approved_evaluation is None
        or approved_evaluation.decision != ContextDecision.REVIEW.value
        or approved_evaluation.policy_name != evaluation.policy_name
        or approved_evaluation.policy_version != evaluation.policy_version
    ):
        return False
    try:
        approved_warnings = sorted(json.loads(approved_evaluation.warnings_json or "[]"))
        current_warnings = sorted(json.loads(evaluation.warnings_json or "[]"))
        current_hard_failures = json.loads(evaluation.hard_failures_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return False
    return (
        approved_warnings == current_warnings
        and not current_hard_failures
    )


async def _bind_active_evaluation(
    session: AsyncSession,
    *,
    pointer: ActiveContextPointer,
    candidate: ContextArtifactCandidate,
    evaluation: ContextCandidateEvaluation,
) -> None:
    """Bind a no-change reevaluation without creating pointer churn."""

    result = await session.execute(
        update(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer.id,
            ActiveContextPointer.generation == pointer.generation,
            ActiveContextPointer.active_candidate_id == candidate.id,
        )
        .values(
            active_evaluation_id=evaluation.id,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ContextActivationConflict(
            "Active Context changed while its evaluation was being refreshed."
        )
    await session.flush()


async def _deactivate_candidate(
    session: AsyncSession,
    *,
    pointer: ActiveContextPointer,
    candidate: ContextArtifactCandidate,
    evaluation: ContextCandidateEvaluation,
    actor: str,
    reason: str,
) -> None:
    expected_generation = int(pointer.generation)
    result = await session.execute(
        update(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer.id,
            ActiveContextPointer.generation == expected_generation,
            ActiveContextPointer.active_candidate_id == candidate.id,
        )
        .values(
            active_candidate_id=None,
            active_evaluation_id=None,
            generation=expected_generation + 1,
            activated_at=None,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ContextActivationConflict(
            "Active Context changed while unsafe copy authority was being revoked."
        )
    event_key = canonical_sha256({
        "pointer_id": str(pointer.id),
        "generation": expected_generation + 1,
        "from_candidate_id": str(candidate.id),
        "evaluation_id": str(evaluation.id),
        "action": "invalidate",
    })
    session.add(ContextActivationEvent(
        pointer_id=pointer.id,
        workspace_id=pointer.workspace_id,
        context_kind=pointer.context_kind,
        action="invalidate",
        from_candidate_id=candidate.id,
        to_candidate_id=None,
        evaluation_id=evaluation.id,
        generation=expected_generation + 1,
        actor=actor,
        reason=reason,
        idempotency_key=event_key,
    ))
    await session.flush()
    await session.refresh(pointer)


async def _activate_candidate(
    session: AsyncSession,
    *,
    pointer: ActiveContextPointer,
    candidate: ContextArtifactCandidate,
    evaluation: ContextCandidateEvaluation,
    actor: str,
    action: str,
    reason: str,
) -> None:
    expected_generation = int(pointer.generation)
    previous_id = pointer.active_candidate_id
    result = await session.execute(
        update(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer.id,
            ActiveContextPointer.generation == expected_generation,
            (
                ActiveContextPointer.active_candidate_id.is_(None)
                if previous_id is None
                else ActiveContextPointer.active_candidate_id == previous_id
            ),
        )
        .values(
            active_candidate_id=candidate.id,
            active_evaluation_id=evaluation.id,
            generation=expected_generation + 1,
            activated_at=utc_now(),
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ContextActivationConflict(
            "Active Context changed while the candidate was being promoted; reevaluate it."
        )
    event_key = canonical_sha256({
        "pointer_id": str(pointer.id),
        "generation": expected_generation + 1,
        "from_candidate_id": str(previous_id) if previous_id else None,
        "to_candidate_id": str(candidate.id),
        "action": action,
    })
    session.add(ContextActivationEvent(
        pointer_id=pointer.id,
        workspace_id=pointer.workspace_id,
        context_kind=pointer.context_kind,
        action=action,
        from_candidate_id=previous_id,
        to_candidate_id=candidate.id,
        evaluation_id=evaluation.id,
        generation=expected_generation + 1,
        actor=actor,
        reason=reason,
        idempotency_key=event_key,
    ))
    await session.flush()
    await session.refresh(pointer)


async def assert_candidate_evidence_current(
    session: AsyncSession,
    *,
    candidate: ContextArtifactCandidate,
    access_scope: AccessScope,
    validate_runtime_snapshot: bool,
) -> None:
    """Revalidate exact evidence permissions and mutable observation boundaries."""

    bundle = await session.get(ContextObservationBundle, candidate.observation_bundle_id)
    if bundle is None:
        raise ContextEvidenceStale("Context observation evidence is unavailable.")
    try:
        observation = json.loads(bundle.observation_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContextEvidenceStale("Context observation evidence is malformed.") from exc
    expected_permission_sha = str(
        observation.get("permission_manifest_sha256") or ""
    ).strip()
    raw_source_ids = observation.get("evidence_source_document_ids")
    if len(expected_permission_sha) != 64 or not isinstance(raw_source_ids, list):
        raise ContextEvidenceStale(
            "Context predates permission-manifest binding and must be regenerated."
        )
    source_ids: list[UUID] = []
    try:
        source_ids = [UUID(str(item)) for item in raw_source_ids]
    except (TypeError, ValueError) as exc:
        raise ContextEvidenceStale("Context permission evidence is malformed.") from exc
    actual_permission_sha = await _permission_manifest_sha256(
        session,
        workspace_id=candidate.workspace_id,
        access_scope=access_scope,
        source_document_ids=source_ids,
    )
    if actual_permission_sha != expected_permission_sha:
        raise ContextEvidenceStale(
            "Context source permissions or source revisions changed; regenerate it."
        )
    if not validate_runtime_snapshot:
        return

    if candidate.context_kind == ContextKind.SESSION.value:
        boundary = (
            await session.get(SessionEvent, bundle.boundary_event_id)
            if bundle.boundary_event_id is not None
            else None
        )
        if boundary is None:
            raise ContextEvidenceStale("Session Context boundary is unavailable.")
        latest_sequence = await session.scalar(
            select(func.max(SessionEvent.sequence_number))
            .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
            .where(
                SessionEvent.workspace_id == candidate.workspace_id,
                SessionEvent.provider == boundary.provider,
                SessionEvent.session_id == boundary.session_id,
                source_access_predicate(
                    access_scope,
                    workspace_id=candidate.workspace_id,
                ),
            )
        )
        if latest_sequence is None or int(latest_sequence) != boundary.sequence_number:
            raise ContextEvidenceStale(
                "The Session Context boundary changed; regenerate it before review."
            )

    expected_repository_sha = str(
        bundle.repository_snapshot_sha256 or ""
    ).strip()
    if len(expected_repository_sha) != 64:
        return
    repository_path = str(
        observation.get("repository_root")
        or observation.get("repository_identity")
        or ""
    ).strip()
    if not repository_path:
        try:
            artifact = json.loads(candidate.artifact_json or "{}")
        except (TypeError, json.JSONDecodeError):
            artifact = {}
        repository = artifact.get("repository") if isinstance(artifact, dict) else None
        if isinstance(repository, dict):
            repository_path = str(
                repository.get("root") or repository.get("path") or ""
            ).strip()
    if not repository_path or not Path(repository_path).is_absolute():
        raise ContextEvidenceStale(
            "The repository snapshot cannot be re-observed; regenerate this Context."
        )
    try:
        if candidate.context_kind == ContextKind.WORKSPACE.value:
            from app.services.repo_indexer import inspect_repo

            current_repository_sha = (
                await inspect_repo(repository_path, persist=False)
            ).snapshot_fingerprint
        else:
            from app.services.local_harness import capture_repository_snapshot

            current_repository_sha = (
                await capture_repository_snapshot(repository_path)
            ).status_fingerprint
    except (OSError, RuntimeError, ValueError) as exc:
        raise ContextEvidenceStale(
            "The repository snapshot could not be re-observed; regenerate this Context."
        ) from exc
    if current_repository_sha != expected_repository_sha:
        raise ContextEvidenceStale(
            "The repository changed after evaluation; regenerate this Context."
        )


async def candidate_permissions_current(
    session: AsyncSession,
    *,
    candidate: ContextArtifactCandidate,
    access_scope: AccessScope,
) -> bool:
    try:
        await assert_candidate_evidence_current(
            session,
            candidate=candidate,
            access_scope=access_scope,
            validate_runtime_snapshot=False,
        )
    except ContextEvidenceStale:
        return False
    return True


async def activate_reviewed_candidate(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    candidate_id: UUID,
    expected_generation: int,
    expected_evaluation_id: UUID | None = None,
    access_scope_sha256_value: str,
    access_scope: AccessScope | None = None,
    actor: str,
    reason: str,
) -> ContextQualityActivation:
    candidate = await session.scalar(select(ContextArtifactCandidate).where(
        ContextArtifactCandidate.id == candidate_id,
        ContextArtifactCandidate.workspace_id == workspace_id,
    ))
    if candidate is None:
        raise LookupError("Context candidate not found")
    if candidate.access_scope_sha256 != access_scope_sha256_value:
        raise LookupError("Context candidate not found")
    pointer = await session.scalar(
        select(ActiveContextPointer)
        .where(
            ActiveContextPointer.workspace_id == workspace_id,
            ActiveContextPointer.context_kind == candidate.context_kind,
            ActiveContextPointer.scope_key_sha256 == candidate.scope_key_sha256,
            ActiveContextPointer.access_scope_sha256 == candidate.access_scope_sha256,
            ActiveContextPointer.delivery_profile_sha256 == candidate.delivery_profile_sha256,
        )
        .with_for_update()
    )
    if pointer is None or pointer.generation != expected_generation:
        raise ContextActivationConflict("Active Context generation changed; refresh review.")
    if await _candidate_is_quarantined(
        session,
        pointer_id=pointer.id,
        candidate_id=candidate.id,
    ):
        raise ContextRollbackUnsafe(
            "This Context candidate was quarantined and cannot be reactivated; regenerate it."
        )
    evaluation_statement = select(ContextCandidateEvaluation).where(
        ContextCandidateEvaluation.candidate_id == candidate.id
    )
    if expected_evaluation_id is not None:
        evaluation_statement = evaluation_statement.where(
            ContextCandidateEvaluation.id == expected_evaluation_id
        )
    else:
        evaluation_statement = evaluation_statement.order_by(
            ContextCandidateEvaluation.created_at.desc(),
            ContextCandidateEvaluation.id.desc(),
        ).limit(1)
    evaluation = await session.scalar(evaluation_statement)
    if evaluation is None or evaluation.decision not in {
        ContextDecision.REVIEW.value,
        ContextDecision.PROMOTE.value,
        ContextDecision.NO_CHANGE.value,
    }:
        raise ValueError("Rejected candidates cannot be activated")
    if (
        evaluation.baseline_candidate_id != pointer.active_candidate_id
        or evaluation.baseline_generation != pointer.generation
    ):
        raise ContextActivationConflict(
            "The reviewed Context was evaluated against an older active baseline; "
            "regenerate and review it again."
        )
    same_baseline_evaluation_ids = list(await session.scalars(
        select(ContextCandidateEvaluation.id).where(
            ContextCandidateEvaluation.candidate_id == candidate.id,
            (
                ContextCandidateEvaluation.baseline_candidate_id.is_(None)
                if pointer.active_candidate_id is None
                else ContextCandidateEvaluation.baseline_candidate_id
                == pointer.active_candidate_id
            ),
            ContextCandidateEvaluation.baseline_generation == pointer.generation,
        )
    ))
    if same_baseline_evaluation_ids != [evaluation.id]:
        raise ContextActivationConflict(
            "This candidate has conflicting evaluations for the active baseline; "
            "regenerate it before review."
        )
    if access_scope is not None:
        await assert_candidate_evidence_current(
            session,
            candidate=candidate,
            access_scope=access_scope,
            validate_runtime_snapshot=True,
        )
    await _activate_candidate(
        session,
        pointer=pointer,
        candidate=candidate,
        evaluation=evaluation,
        actor=actor,
        action="activate_reviewed",
        reason=reason,
    )
    bundle = await session.get(ContextObservationBundle, candidate.observation_bundle_id)
    assert bundle is not None
    return ContextQualityActivation(
        status="active",
        copy_allowed=True,
        candidate_id=str(candidate.id),
        active_candidate_id=str(candidate.id),
        observation_sha256=bundle.observation_sha256,
        artifact_sha256=candidate.content_sha256,
        semantic_sha256=candidate.semantic_sha256,
        evaluation_id=str(evaluation.id),
        pointer_generation=pointer.generation,
        decision=ContextDecision(evaluation.decision),
    )


async def rollback_active_context(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pointer_id: UUID,
    target_candidate_id: UUID,
    expected_generation: int,
    access_scope_sha256_value: str,
    access_scope: AccessScope | None = None,
    actor: str,
    reason: str,
) -> ContextQualityActivation:
    pointer = await session.scalar(
        select(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer_id,
            ActiveContextPointer.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if pointer is None:
        raise LookupError("Active Context pointer not found")
    if pointer.access_scope_sha256 != access_scope_sha256_value:
        raise LookupError("Active Context pointer not found")
    if pointer.generation != expected_generation:
        raise ContextActivationConflict("Active Context generation changed; refresh rollback.")
    if pointer.active_candidate_id is None:
        raise ContextRollbackUnsafe("There is no active Context to roll back")
    target = await session.scalar(select(ContextArtifactCandidate).where(
        ContextArtifactCandidate.id == target_candidate_id,
        ContextArtifactCandidate.workspace_id == workspace_id,
        ContextArtifactCandidate.context_kind == pointer.context_kind,
        ContextArtifactCandidate.scope_key_sha256 == pointer.scope_key_sha256,
        ContextArtifactCandidate.access_scope_sha256 == pointer.access_scope_sha256,
        ContextArtifactCandidate.delivery_profile_sha256 == pointer.delivery_profile_sha256,
    ))
    if target is None:
        raise LookupError("Rollback Context candidate not found")
    prior_activation = await session.scalar(
        select(ContextActivationEvent.id)
        .where(
            ContextActivationEvent.pointer_id == pointer.id,
            ContextActivationEvent.to_candidate_id == target.id,
            ContextActivationEvent.action.in_([
                "activate",
                "activate_reviewed",
                "no_change",
                "rollback",
            ]),
        )
        .limit(1)
    )
    if prior_activation is None:
        raise ContextRollbackUnsafe(
            "Rollback can target only a previously active Context candidate."
        )
    if await _candidate_is_quarantined(
        session,
        pointer_id=pointer.id,
        candidate_id=target.id,
    ):
        raise ContextRollbackUnsafe(
            "The rollback candidate was quarantined and cannot be reactivated."
        )
    current = await session.get(ContextArtifactCandidate, pointer.active_candidate_id)
    if current is None:
        raise ContextRollbackUnsafe("Active Context artifact is unavailable")
    current_bundle = await session.get(ContextObservationBundle, current.observation_bundle_id)
    target_bundle = await session.get(ContextObservationBundle, target.observation_bundle_id)
    if current_bundle is None or target_bundle is None:
        raise ContextRollbackUnsafe("Rollback observation evidence is unavailable")
    if target_bundle.observation_sha256 != current_bundle.observation_sha256:
        raise ContextRollbackUnsafe(
            "Rollback candidate was compiled from a different observation snapshot; regenerate it."
        )
    if access_scope is not None:
        await assert_candidate_evidence_current(
            session,
            candidate=target,
            access_scope=access_scope,
            validate_runtime_snapshot=True,
        )
    evaluation = await session.scalar(
        select(ContextCandidateEvaluation)
        .where(ContextCandidateEvaluation.candidate_id == target.id)
        .order_by(ContextCandidateEvaluation.created_at.desc(), ContextCandidateEvaluation.id.desc())
        .limit(1)
    )
    rejected_evaluation_id = await session.scalar(
        select(ContextCandidateEvaluation.id)
        .where(
            ContextCandidateEvaluation.candidate_id == target.id,
            ContextCandidateEvaluation.decision == ContextDecision.REJECT.value,
        )
        .limit(1)
    )
    if (
        evaluation is None
        or evaluation.decision not in {
            ContextDecision.PROMOTE.value,
            ContextDecision.NO_CHANGE.value,
            ContextDecision.REVIEW.value,
        }
        or rejected_evaluation_id is not None
    ):
        raise ContextRollbackUnsafe("Rollback candidate has no acceptable evaluation")
    await _activate_candidate(
        session,
        pointer=pointer,
        candidate=target,
        evaluation=evaluation,
        actor=actor,
        action="rollback",
        reason=reason,
    )
    return ContextQualityActivation(
        status="active",
        copy_allowed=True,
        candidate_id=str(target.id),
        active_candidate_id=str(target.id),
        observation_sha256=target_bundle.observation_sha256,
        artifact_sha256=target.content_sha256,
        semantic_sha256=target.semantic_sha256,
        evaluation_id=str(evaluation.id),
        pointer_generation=pointer.generation,
        decision=ContextDecision(evaluation.decision),
    )


async def quarantine_active_context(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pointer_id: UUID,
    expected_generation: int,
    access_scope_sha256_value: str,
    actor: str,
    reason: str,
) -> ContextQualityActivation:
    """Fail closed after a harmful, stale, or misleading outcome signal."""

    pointer = await session.scalar(
        select(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer_id,
            ActiveContextPointer.workspace_id == workspace_id,
            ActiveContextPointer.access_scope_sha256 == access_scope_sha256_value,
        )
        .with_for_update()
    )
    if pointer is None:
        raise LookupError("Active Context pointer not found")
    if pointer.generation != expected_generation:
        raise ContextActivationConflict("Active Context generation changed; refresh outcome.")
    if pointer.active_candidate_id is None:
        raise ContextRollbackUnsafe("There is no active Context to quarantine")
    candidate = await session.get(ContextArtifactCandidate, pointer.active_candidate_id)
    bundle = (
        await session.get(ContextObservationBundle, candidate.observation_bundle_id)
        if candidate is not None
        else None
    )
    if candidate is None or bundle is None:
        raise ContextRollbackUnsafe("Active Context evidence is unavailable")
    previous_id = pointer.active_candidate_id
    evaluation_id = pointer.active_evaluation_id
    expected = int(pointer.generation)
    result = await session.execute(
        update(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer.id,
            ActiveContextPointer.generation == expected,
            ActiveContextPointer.active_candidate_id == previous_id,
        )
        .values(
            active_candidate_id=None,
            active_evaluation_id=None,
            generation=expected + 1,
            activated_at=None,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise ContextActivationConflict("Active Context changed; refresh outcome.")
    event_key = canonical_sha256({
        "pointer_id": str(pointer.id),
        "generation": expected + 1,
        "from_candidate_id": str(previous_id),
        "action": "quarantine",
        "reason": reason,
    })
    session.add(ContextActivationEvent(
        pointer_id=pointer.id,
        workspace_id=pointer.workspace_id,
        context_kind=pointer.context_kind,
        action="quarantine",
        from_candidate_id=previous_id,
        to_candidate_id=None,
        evaluation_id=evaluation_id,
        generation=expected + 1,
        actor=actor,
        reason=reason,
        idempotency_key=event_key,
    ))
    await session.flush()
    await session.refresh(pointer)
    evaluation = (
        await session.get(ContextCandidateEvaluation, evaluation_id)
        if evaluation_id is not None
        else None
    )
    return ContextQualityActivation(
        status="quarantined",
        copy_allowed=False,
        candidate_id=str(candidate.id),
        active_candidate_id=None,
        observation_sha256=bundle.observation_sha256,
        artifact_sha256=candidate.content_sha256,
        semantic_sha256=candidate.semantic_sha256,
        evaluation_id=str(evaluation.id) if evaluation is not None else None,
        pointer_generation=pointer.generation,
        decision=(
            ContextDecision(evaluation.decision)
            if evaluation is not None
            else ContextDecision.REJECT
        ),
    )


async def record_active_context_outcome(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pointer_id: UUID,
    expected_generation: int,
    access_scope_sha256_value: str,
    access_scope: AccessScope | None = None,
    outcome: str,
    actor: str,
    reason: str,
) -> ContextQualityActivation:
    """Record downstream usefulness; unsafe signals immediately revoke copy authority."""

    normalized_outcome = str(outcome or "").strip().casefold()
    if normalized_outcome not in {
        "helpful",
        "incomplete",
        "incorrect",
        "unsafe",
        "stale",
    }:
        raise ValueError("Unsupported Context outcome")
    if normalized_outcome != "helpful":
        return await quarantine_active_context(
            session,
            workspace_id=workspace_id,
            pointer_id=pointer_id,
            expected_generation=expected_generation,
            access_scope_sha256_value=access_scope_sha256_value,
            actor=actor,
            reason=f"{normalized_outcome}: {reason}",
        )

    pointer = await session.scalar(
        select(ActiveContextPointer)
        .where(
            ActiveContextPointer.id == pointer_id,
            ActiveContextPointer.workspace_id == workspace_id,
            ActiveContextPointer.access_scope_sha256 == access_scope_sha256_value,
        )
        .with_for_update()
    )
    if pointer is None or pointer.active_candidate_id is None:
        raise LookupError("Active Context pointer not found")
    if pointer.generation != expected_generation:
        raise ContextActivationConflict("Active Context generation changed; refresh outcome.")
    candidate = await session.get(ContextArtifactCandidate, pointer.active_candidate_id)
    bundle = (
        await session.get(ContextObservationBundle, candidate.observation_bundle_id)
        if candidate is not None
        else None
    )
    if candidate is None or bundle is None:
        raise ContextRollbackUnsafe("Active Context evidence is unavailable")
    if access_scope is not None:
        await assert_candidate_evidence_current(
            session,
            candidate=candidate,
            access_scope=access_scope,
            validate_runtime_snapshot=True,
        )
    event_key = canonical_sha256({
        "pointer_id": str(pointer.id),
        "generation": pointer.generation,
        "candidate_id": str(candidate.id),
        "action": "outcome_helpful",
        "reason": reason,
    })
    existing = await session.scalar(select(ContextActivationEvent).where(
        ContextActivationEvent.idempotency_key == event_key
    ))
    if existing is None:
        session.add(ContextActivationEvent(
            pointer_id=pointer.id,
            workspace_id=pointer.workspace_id,
            context_kind=pointer.context_kind,
            action="outcome_helpful",
            from_candidate_id=candidate.id,
            to_candidate_id=candidate.id,
            evaluation_id=pointer.active_evaluation_id,
            generation=pointer.generation,
            actor=actor,
            reason=reason,
            idempotency_key=event_key,
        ))
        await session.flush()
    evaluation = (
        await session.get(ContextCandidateEvaluation, pointer.active_evaluation_id)
        if pointer.active_evaluation_id is not None
        else None
    )
    return ContextQualityActivation(
        status="active",
        copy_allowed=True,
        candidate_id=str(candidate.id),
        active_candidate_id=str(candidate.id),
        observation_sha256=bundle.observation_sha256,
        artifact_sha256=candidate.content_sha256,
        semantic_sha256=candidate.semantic_sha256,
        evaluation_id=str(evaluation.id) if evaluation is not None else None,
        pointer_generation=pointer.generation,
        decision=(
            ContextDecision(evaluation.decision)
            if evaluation is not None
            else ContextDecision.PROMOTE
        ),
    )


def apply_quality_control(
    artifact: dict[str, Any],
    activation: ContextQualityActivation,
) -> dict[str, Any]:
    artifact["quality_control"] = activation.model_dump(mode="json")
    if not activation.copy_allowed:
        quality = artifact.get("quality_report")
        if isinstance(quality, dict):
            quality["copy_ready"] = False
            quality["automatic_execution_ready"] = False
            quality["status"] = "blocked"
        dimensions = artifact.get("readiness_dimensions")
        if isinstance(dimensions, dict):
            semantic = dimensions.get("semantic_readiness")
            if isinstance(semantic, dict):
                semantic["copy_ready"] = False
                semantic["status"] = "blocked"
                semantic.setdefault("blocking_issue_codes", []).append(
                    "context_candidate_not_active"
                )
    return artifact
