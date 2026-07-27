from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AgentRun,
    Claim,
    ClaimRevision,
    ContextPack,
    ContextPackItem,
    EvidenceSpan,
    WorkspaceGoal,
)
from app.time import utc_now


ACTIVE_RUN_STATUSES = frozenset({"queued", "running", "in_progress"})
_MANIFEST_REFERENCE_FIELDS = {
    "source_document_id": "sources",
    "component_id": "components",
    "evidence_span_id": "evidence",
    "claim_id": "claims",
    "claim_revision_id": "revisions",
    "evidence_revision_id": "revisions",
}


@dataclass(frozen=True)
class ContextPackAccess:
    """One request-scoped, fail-closed provenance authorization snapshot."""

    source_document_ids: frozenset[UUID] | None = None
    component_ids: frozenset[UUID] | None = None
    evidence_span_ids: frozenset[UUID] | None = None
    claim_ids: frozenset[UUID] | None = None
    claim_revision_ids: frozenset[UUID] | None = None
    revision_claim_pairs: frozenset[tuple[UUID, UUID]] = frozenset()
    revision_evidence_pairs: frozenset[tuple[UUID, UUID]] = frozenset()

    @property
    def constrained(self) -> bool:
        return any(
            values is not None
            for values in (
                self.source_document_ids,
                self.component_ids,
                self.evidence_span_ids,
                self.claim_ids,
                self.claim_revision_ids,
            )
        )


async def build_context_pack_access(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    allowed_source_document_ids: set[UUID] | None,
    allowed_component_ids: set[UUID] | None,
) -> ContextPackAccess:
    """Resolve indirect evidence and claim lineage once for the whole request."""

    source_ids = (
        frozenset(allowed_source_document_ids)
        if allowed_source_document_ids is not None
        else None
    )
    component_ids = (
        frozenset(allowed_component_ids)
        if allowed_component_ids is not None
        else None
    )
    if source_ids is None:
        return ContextPackAccess(
            source_document_ids=None,
            component_ids=component_ids,
        )
    if not source_ids:
        return ContextPackAccess(
            source_document_ids=source_ids,
            component_ids=component_ids,
            evidence_span_ids=frozenset(),
            claim_ids=frozenset(),
            claim_revision_ids=frozenset(),
        )

    evidence_span_ids = frozenset(await session.scalars(
        select(EvidenceSpan.id).where(
            EvidenceSpan.source_document_id.in_(source_ids)
        )
    ))
    claim_rows = list((await session.execute(
        select(
            Claim.id.label("claim_id"),
            Claim.current_revision_id.label("current_revision_id"),
            ClaimRevision.id.label("revision_id"),
            ClaimRevision.evidence_span_id.label("evidence_span_id"),
        )
        .outerjoin(ClaimRevision, ClaimRevision.claim_id == Claim.id)
        .where(
            Claim.workspace_id == workspace_id,
            Claim.id.in_(
                select(ContextPackItem.claim_id)
                .join(
                    ContextPack,
                    ContextPack.id == ContextPackItem.context_pack_id,
                )
                .where(
                    ContextPack.workspace_id == workspace_id,
                    ContextPackItem.claim_id.is_not(None),
                )
            ),
        )
    )).all())
    current_revision_by_claim: dict[UUID, UUID | None] = {}
    revision_ids_by_claim: dict[UUID, set[UUID]] = {}
    allowed_revision_ids: set[UUID] = set()
    revision_claim_pairs: set[tuple[UUID, UUID]] = set()
    revision_evidence_pairs: set[tuple[UUID, UUID]] = set()
    for row in claim_rows:
        claim_id = row.claim_id
        current_revision_by_claim[claim_id] = row.current_revision_id
        if row.revision_id is None:
            continue
        revision_ids_by_claim.setdefault(claim_id, set()).add(row.revision_id)
        if row.evidence_span_id in evidence_span_ids:
            allowed_revision_ids.add(row.revision_id)
            revision_claim_pairs.add((row.revision_id, claim_id))
            revision_evidence_pairs.add((
                row.revision_id,
                row.evidence_span_id,
            ))
    allowed_claim_ids = {
        claim_id
        for claim_id, revision_ids in revision_ids_by_claim.items()
        if revision_ids
        and revision_ids <= allowed_revision_ids
        and current_revision_by_claim.get(claim_id) in allowed_revision_ids
    }
    return ContextPackAccess(
        source_document_ids=source_ids,
        component_ids=component_ids,
        evidence_span_ids=evidence_span_ids,
        claim_ids=frozenset(allowed_claim_ids),
        claim_revision_ids=frozenset(allowed_revision_ids),
        revision_claim_pairs=frozenset(revision_claim_pairs),
        revision_evidence_pairs=frozenset(revision_evidence_pairs),
    )


def goal_to_dict(goal: WorkspaceGoal) -> dict:
    return {
        "id": str(goal.id),
        "workspace_id": str(goal.workspace_id),
        "title": goal.title,
        "component_id": str(goal.component_id) if goal.component_id else None,
        "source_kind": goal.source_kind,
        "source_id": goal.source_id,
        "selected_by": goal.selected_by,
        "selected_at": goal.selected_at,
        "can_clear": True,
    }


async def resolve_current_goal(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    allowed_component_ids: set[UUID] | None = None,
    allowed_source_document_ids: set[UUID] | None = None,
    context_pack_access: ContextPackAccess | None = None,
) -> dict | None:
    """Return active work, never an objective inferred from an old context pack."""
    runs = list(await session.scalars(
        select(AgentRun)
        .options(
            selectinload(AgentRun.context_pack).selectinload(ContextPack.items)
        )
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            AgentRun.objective.is_not(None),
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
    ))
    pack_access = context_pack_access
    if pack_access is None:
        pack_access = (
            await build_context_pack_access(
                session,
                workspace_id=workspace_id,
                allowed_source_document_ids=allowed_source_document_ids,
                allowed_component_ids=allowed_component_ids,
            )
            if any(candidate.context_pack_id is not None for candidate in runs)
            else ContextPackAccess()
        )
    run = next(
        (
            candidate
            for candidate in runs
            if _run_pack_sources_accessible(
                candidate,
                pack_access,
            )
        ),
        None,
    )
    if run is not None and str(run.objective or "").strip():
        component_id = None
        if run.context_pack_id:
            pack = run.context_pack
            candidate = pack.focus_component_id if pack is not None else None
            if candidate and (
                allowed_component_ids is None or candidate in allowed_component_ids
            ):
                component_id = candidate
        return {
            "id": f"run:{run.id}",
            "workspace_id": str(workspace_id),
            "title": str(run.objective).strip(),
            "component_id": str(component_id) if component_id else None,
            "source_kind": "active_agent_run",
            "source_id": str(run.id),
            "selected_by": run.tool or "agent_harness",
            "selected_at": run.started_at,
            "can_clear": False,
        }

    goal = await session.scalar(
        select(WorkspaceGoal)
        .options(selectinload(WorkspaceGoal.component))
        .where(
            WorkspaceGoal.workspace_id == workspace_id,
            WorkspaceGoal.status == "active",
        )
        .order_by(WorkspaceGoal.selected_at.desc(), WorkspaceGoal.id.desc())
        .limit(1)
    )
    if goal is None:
        return None
    if (
        goal.component_id is not None
        and allowed_component_ids is not None
        and goal.component_id not in allowed_component_ids
    ):
        return None
    if (
        goal.component_id is not None
        and allowed_source_document_ids is not None
        and (
            goal.component is None
            or (
                goal.component.source_document_id is not None
                and goal.component.source_document_id
                not in allowed_source_document_ids
            )
        )
    ):
        return None
    return goal_to_dict(goal)


def context_pack_sources_accessible(
    context_pack: ContextPack | None,
    allowed_source_document_ids: set[UUID] | None,
    allowed_component_ids: set[UUID] | None = None,
    *,
    access: ContextPackAccess | None = None,
) -> bool:
    if context_pack is None:
        return True
    pack_access = access or ContextPackAccess(
        source_document_ids=(
            frozenset(allowed_source_document_ids)
            if allowed_source_document_ids is not None
            else None
        ),
        component_ids=(
            frozenset(allowed_component_ids)
            if allowed_component_ids is not None
            else None
        ),
        # Direct callers cannot safely authorize indirect legacy lineage
        # without resolving it through build_context_pack_access.
        evidence_span_ids=(
            frozenset() if allowed_source_document_ids is not None else None
        ),
        claim_ids=(
            frozenset() if allowed_source_document_ids is not None else None
        ),
        claim_revision_ids=(
            frozenset() if allowed_source_document_ids is not None else None
        ),
    )
    if not pack_access.constrained:
        return True
    if not _references_accessible(
        {
            "sources": _present_ids([
                context_pack.objective_source_document_id,
                *(item.source_document_id for item in context_pack.items),
            ]),
            "components": _present_ids([
                context_pack.focus_component_id,
                *(item.component_id for item in context_pack.items),
            ]),
            "evidence": _present_ids([
                context_pack.objective_evidence_span_id,
                *(item.evidence_span_id for item in context_pack.items),
            ]),
            "claims": _present_ids([
                item.claim_id for item in context_pack.items
            ]),
            "revisions": set(),
        },
        pack_access,
    ):
        return False
    return _manifest_accessible(context_pack, pack_access)


def _run_pack_sources_accessible(
    run: AgentRun,
    access: ContextPackAccess,
) -> bool:
    if not access.constrained:
        return True
    if run.context_pack_id is not None and run.context_pack is None:
        return False
    return context_pack_sources_accessible(
        run.context_pack,
        (
            set(access.source_document_ids)
            if access.source_document_ids is not None
            else None
        ),
        (
            set(access.component_ids)
            if access.component_ids is not None
            else None
        ),
        access=access,
    )


def _present_ids(values: list[UUID | None]) -> set[UUID]:
    return {value for value in values if value is not None}


def _references_accessible(
    references: dict[str, set[UUID]],
    access: ContextPackAccess,
) -> bool:
    allowed = {
        "sources": access.source_document_ids,
        "components": access.component_ids,
        "evidence": access.evidence_span_ids,
        "claims": access.claim_ids,
        "revisions": access.claim_revision_ids,
    }
    for kind, reference_ids in references.items():
        allowed_ids = allowed[kind]
        if allowed_ids is not None and not reference_ids <= allowed_ids:
            return False
    return True


def _manifest_accessible(
    context_pack: ContextPack,
    access: ContextPackAccess,
) -> bool:
    try:
        manifest = json.loads(context_pack.manifest or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    manifest_references, valid = _manifest_references(manifest)
    if (
        not valid
        or not _references_accessible(manifest_references, access)
    ):
        return False

    focus = manifest.get("focus")
    focus_references = {
        "sources": set(),
        "components": set(),
        "evidence": set(),
        "claims": set(),
        "revisions": set(),
    }
    if focus is not None:
        if not isinstance(focus, dict):
            return False
        focus_references, valid = _manifest_references(focus)
        if not valid:
            return False
    if context_pack.objective_origin == "source_component":
        objective_lineage = {
            context_pack.objective_source_document_id,
            context_pack.objective_evidence_span_id,
            context_pack.focus_component_id,
        }
        if not any(objective_lineage) and not any(
            focus_references.values()
        ):
            return False

    selected = manifest.get("selected_context")
    if selected is None:
        return True
    if not isinstance(selected, list):
        return False
    normalized_items = {
        str(item.manifest_item_id): item
        for item in context_pack.items
        if item.manifest_item_id
    }
    for raw_item in selected:
        if not isinstance(raw_item, dict):
            return False
        references, valid = _manifest_references(raw_item)
        if not valid or not _references_accessible(references, access):
            return False
        if not any(references.values()):
            continue
        manifest_item_id = str(raw_item.get("id") or "").strip()
        normalized = normalized_items.get(manifest_item_id)
        if normalized is None:
            return False
        for field_name in (
            "source_document_id",
            "component_id",
            "evidence_span_id",
            "claim_id",
        ):
            raw_value = raw_item.get(field_name)
            if raw_value is None:
                continue
            parsed = _uuid_value(raw_value)
            if parsed is None or getattr(normalized, field_name) != parsed:
                return False
        revision_ids = {
            parsed
            for field_name in ("claim_revision_id", "evidence_revision_id")
            if (raw_value := raw_item.get(field_name)) is not None
            if (parsed := _uuid_value(raw_value)) is not None
        }
        if revision_ids and access.claim_revision_ids is not None:
            if (
                normalized.claim_id is None
                and normalized.evidence_span_id is None
            ):
                return False
            for revision_id in revision_ids:
                if (
                    normalized.claim_id is not None
                    and (
                        revision_id,
                        normalized.claim_id,
                    ) not in access.revision_claim_pairs
                ):
                    return False
                if (
                    normalized.evidence_span_id is not None
                    and (
                        revision_id,
                        normalized.evidence_span_id,
                    ) not in access.revision_evidence_pairs
                ):
                    return False
    return True


def _manifest_references(
    value: object,
) -> tuple[dict[str, set[UUID]], bool]:
    references = {
        "sources": set(),
        "components": set(),
        "evidence": set(),
        "claims": set(),
        "revisions": set(),
    }
    valid = True

    def visit(node: object) -> None:
        nonlocal valid
        if not valid:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                reference_kind = _MANIFEST_REFERENCE_FIELDS.get(str(key))
                if reference_kind is not None and child is not None:
                    values = child if isinstance(child, list) else [child]
                    for raw_value in values:
                        parsed = _uuid_value(raw_value)
                        if parsed is None:
                            valid = False
                            return
                        references[reference_kind].add(parsed)
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return references, valid


def _uuid_value(value: object) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


async def select_workspace_goal(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    title: str,
    component_id: UUID | None,
    source_kind: str,
    source_id: str | None,
    selected_by: str,
    selected_at: datetime | None = None,
) -> WorkspaceGoal:
    now = selected_at or utc_now()
    active = list(await session.scalars(
        select(WorkspaceGoal).where(
            WorkspaceGoal.workspace_id == workspace_id,
            WorkspaceGoal.status == "active",
        )
    ))
    for previous in active:
        previous.status = "replaced"
        previous.ended_at = now
    goal = WorkspaceGoal(
        workspace_id=workspace_id,
        title=" ".join(title.split()),
        component_id=component_id,
        status="active",
        source_kind=source_kind,
        source_id=source_id,
        selected_by=selected_by,
        selected_at=now,
    )
    session.add(goal)
    await session.flush()
    return goal


async def clear_workspace_goal(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> WorkspaceGoal | None:
    goal = await session.scalar(
        select(WorkspaceGoal).where(
            WorkspaceGoal.workspace_id == workspace_id,
            WorkspaceGoal.status == "active",
        )
    )
    if goal is None:
        return None
    goal.status = "cleared"
    goal.ended_at = utc_now()
    await session.flush()
    return goal
