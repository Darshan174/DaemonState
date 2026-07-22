from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    CheckpointEvidence,
    CheckpointItem,
    CheckpointVerification,
    SessionEvent,
    SourceDocument,
    WorkCheckpoint,
)
from app.services.local_harness import RepositorySnapshot, capture_repository_snapshot
from app.services.session_events import event_payload
from app.services.session_summary import (
    extract_delegated_user_request,
    is_continuation_control,
    is_session_instruction_noise,
    is_substantive_user_request,
)
from app.time import utc_now


CHECKPOINT_SCHEMA_VERSION = "work_checkpoint.v5"
CHECKPOINT_CATEGORIES = (
    "goal",
    "progress",
    "decisions",
    "failed_attempts",
    "relevant_files",
    "blockers",
    "verification",
    "exact_next_action",
)
MAX_ITEMS_PER_CATEGORY = 12
MAX_STATEMENT_CHARS = 1_200

_DECISION_SIGNAL = re.compile(
    r"\b(?:decid(?:e|ed)|we(?:'ll| will)|will use|keep|remove|replace|exclude|"
    r"must|should|instead|except for|do not|don't)\b",
    re.IGNORECASE,
)
_PROGRESS_SIGNAL = re.compile(
    r"\b(?:added|built|captured|completed|confirmed|created|fixed|implemented|"
    r"in place|passed|removed|replaced|updated|wired|working)\b",
    re.IGNORECASE,
)
_BLOCKER_SIGNAL = re.compile(
    r"(?:\bblocker\s*:|\b(?:is|are|am|was|were|remain(?:s|ed)?)\s+blocked\b|"
    r"\bblocked\s+(?:by|on|because)\b|\bcannot continue\b|\bcan(?:not|'t) proceed\b|"
    r"\bneed user input\b|\bwaiting for\b|\bpermission required\b)",
    re.IGNORECASE,
)
_NEXT_SIGNAL = re.compile(
    r"(?:^|[\n.!?]\s+)\s*(?:[-*]\s*)?(?:exact next action|next action|next step|next)"
    r"\s*(?::|—|-|\bis\b)\s*([^\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
_COMPLETION_SIGNAL = re.compile(
    r"\b(?:implemented end to end|all remaining tasks are complete|requested work is complete|"
    r"work is fully implemented|finished end to end)\b",
    re.IGNORECASE,
)
_VERIFICATION_COMMAND = re.compile(
    r"(?:^|\s)(?:pytest|python\s+-m\s+pytest|npm\s+(?:test|run\s+(?:test|build|lint))|"
    r"pnpm\s+(?:test|build|lint)|yarn\s+(?:test|build|lint)|ruff|mypy|pyright|"
    r"cargo\s+test|go\s+test|vitest|jest|tsc)(?:\s|$)",
    re.IGNORECASE,
)
_PATH_PATTERN = re.compile(
    r"(?<![\w])("
    r"(?:/(?:[^\s:'\"`<>|]+/)*[^\s:'\"`<>|]+\.[A-Za-z0-9]{1,12})|"
    r"(?:(?:app|frontend|tests|scripts|docs|src|migrations|alembic)/"
    r"[A-Za-z0-9_@+./-]+)|"
    r"(?:[A-Za-z0-9_.@+-]+\.(?:py|tsx?|jsx?|md|json|ya?ml|sql|toml|css|scss|sh))"
    r")"
)


@dataclass
class DraftItem:
    category: str
    statement: str
    truth_state: str
    events: list[SessionEvent]
    state: str = "active"
    payload: dict[str, Any] = field(default_factory=dict)


async def capture_checkpoint(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
    boundary_event_id: UUID | None = None,
    trigger: str = "manual",
) -> WorkCheckpoint:
    """Build and persist one immutable checkpoint from observed session events."""

    boundary = await _resolve_boundary(
        session,
        workspace_id=workspace_id,
        provider=provider,
        session_id=session_id,
        boundary_event_id=boundary_event_id,
    )
    existing = await session.scalar(
        select(WorkCheckpoint).where(
            WorkCheckpoint.workspace_id == workspace_id,
            WorkCheckpoint.provider == provider,
            WorkCheckpoint.session_id == session_id,
            WorkCheckpoint.boundary_event_id == boundary.id,
            WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
        )
    )
    if existing is not None:
        return existing

    events = list(await session.scalars(
        select(SessionEvent)
        .where(
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.provider == provider,
            SessionEvent.session_id == session_id,
            SessionEvent.sequence_number <= boundary.sequence_number,
        )
        .order_by(SessionEvent.sequence_number, SessionEvent.id)
    ))
    if not events:
        raise ValueError("No session events are available for the checkpoint boundary")

    source_document = await session.get(SourceDocument, boundary.source_document_id)
    if source_document is None:
        raise ValueError("Checkpoint source document no longer exists")
    snapshot = await _capture_snapshot(events, source_document)
    sections = _build_sections(events, snapshot)
    goal_present = bool(sections["goal"])
    next_present = bool(sections["exact_next_action"])
    capture_status = "complete" if goal_present and next_present else "incomplete"
    continuation_status = (
        "blocked"
        if sections["blockers"]
        else "ready"
        if capture_status == "complete"
        else "review_required"
    )

    previous = await session.scalar(
        select(WorkCheckpoint)
        .where(
            WorkCheckpoint.workspace_id == workspace_id,
            WorkCheckpoint.provider == provider,
            WorkCheckpoint.session_id == session_id,
        )
        .order_by(WorkCheckpoint.created_at.desc(), WorkCheckpoint.id.desc())
        .limit(1)
    )
    checkpoint = WorkCheckpoint(
        workspace_id=workspace_id,
        source_document_id=boundary.source_document_id,
        provider=provider,
        session_id=session_id,
        boundary_event_id=boundary.id,
        trigger=trigger,
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        capture_status=capture_status,
        continuation_status=continuation_status,
        repo_root=snapshot.root if snapshot else None,
        branch=snapshot.branch if snapshot else None,
        head_commit=snapshot.head_commit if snapshot else None,
        worktree_fingerprint=snapshot.status_fingerprint if snapshot else None,
        payload_json="{}",
        payload_sha256="",
        supersedes_checkpoint_id=previous.id if previous else None,
    )
    try:
        async with session.begin_nested():
            session.add(checkpoint)
            await session.flush()
    except IntegrityError:
        winner = await session.scalar(
            select(WorkCheckpoint).where(
                WorkCheckpoint.workspace_id == workspace_id,
                WorkCheckpoint.provider == provider,
                WorkCheckpoint.session_id == session_id,
                WorkCheckpoint.boundary_event_id == boundary.id,
                WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
            )
        )
        if winner is None:
            raise
        return winner

    persisted_items: list[CheckpointItem] = []
    for category in CHECKPOINT_CATEGORIES:
        for ordinal, draft in enumerate(sections[category]):
            item_key = f"{category}:{ordinal + 1}"
            item = CheckpointItem(
                checkpoint_id=checkpoint.id,
                item_key=item_key,
                category=category,
                ordinal=ordinal,
                statement=draft.statement,
                state=draft.state,
                truth_state=draft.truth_state,
                payload_json=_canonical_json(draft.payload),
            )
            session.add(item)
            await session.flush()
            persisted_items.append(item)
            for evidence_event in _unique_events(draft.events):
                locator = {
                    "provider_event_id": evidence_event.provider_event_id,
                    "sequence_number": evidence_event.sequence_number,
                    "event_type": evidence_event.event_type,
                    "source_cursor": evidence_event.source_cursor,
                }
                digest_material = {
                    "item_key": item_key,
                    "event_sha256": evidence_event.content_sha256,
                    "locator": locator,
                }
                session.add(CheckpointEvidence(
                    checkpoint_item_id=item.id,
                    evidence_type="session_event",
                    session_event_id=evidence_event.id,
                    source_document_id=evidence_event.source_document_id,
                    supports=True,
                    locator_json=_canonical_json(locator),
                    evidence_sha256=_sha256(_canonical_json(digest_material)),
                    observed_at=evidence_event.occurred_at,
                ))

    await session.flush()
    payload = _checkpoint_payload(
        checkpoint,
        boundary=boundary,
        sections=sections,
        snapshot=snapshot,
    )
    checkpoint.payload_json = _canonical_json(payload)
    checkpoint.payload_sha256 = _sha256(checkpoint.payload_json)
    await session.flush()
    return checkpoint


async def capture_missing_compaction_checkpoints(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
) -> list[WorkCheckpoint]:
    boundaries = list(await session.scalars(
        select(SessionEvent)
        .where(
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.provider == provider,
            SessionEvent.session_id == session_id,
            SessionEvent.event_type == "compaction_boundary",
        )
        .order_by(SessionEvent.sequence_number, SessionEvent.id)
    ))
    captured: list[WorkCheckpoint] = []
    for boundary in boundaries:
        captured.append(await capture_checkpoint(
            session,
            workspace_id=workspace_id,
            provider=provider,
            session_id=session_id,
            boundary_event_id=boundary.id,
            trigger="compaction",
        ))
    return captured


async def capture_checkpoint_schema_upgrades(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
) -> int:
    """Backfill the current schema from already-normalized compaction events."""

    conditions = (
        WorkCheckpoint.workspace_id == workspace_id,
        WorkCheckpoint.provider == provider,
        WorkCheckpoint.session_id == session_id,
        WorkCheckpoint.schema_version == CHECKPOINT_SCHEMA_VERSION,
    )
    before = int(await session.scalar(
        select(func.count()).select_from(WorkCheckpoint).where(*conditions)
    ) or 0)
    await capture_missing_compaction_checkpoints(
        session,
        workspace_id=workspace_id,
        provider=provider,
        session_id=session_id,
    )
    after = int(await session.scalar(
        select(func.count()).select_from(WorkCheckpoint).where(*conditions)
    ) or 0)
    return max(0, after - before)


async def get_checkpoint(
    session: AsyncSession,
    checkpoint_id: UUID,
) -> WorkCheckpoint | None:
    return await session.scalar(
        select(WorkCheckpoint)
        .where(WorkCheckpoint.id == checkpoint_id)
        .options(
            selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence),
            selectinload(WorkCheckpoint.verifications),
            selectinload(WorkCheckpoint.boundary_event),
            selectinload(WorkCheckpoint.source_document),
        )
    )


async def latest_checkpoint(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> WorkCheckpoint | None:
    return await session.scalar(
        select(WorkCheckpoint)
        .join(SessionEvent, WorkCheckpoint.boundary_event_id == SessionEvent.id)
        .where(WorkCheckpoint.workspace_id == workspace_id)
        .order_by(
            SessionEvent.occurred_at.desc().nulls_last(),
            SessionEvent.sequence_number.desc(),
            WorkCheckpoint.schema_version.desc(),
            WorkCheckpoint.created_at.desc(),
            WorkCheckpoint.id.desc(),
        )
        .options(
            selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence),
            selectinload(WorkCheckpoint.verifications),
            selectinload(WorkCheckpoint.boundary_event),
            selectinload(WorkCheckpoint.source_document),
        )
        .limit(1)
    )


async def list_checkpoints(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int = 50,
) -> list[WorkCheckpoint]:
    requested = max(1, min(limit, 100))
    values = list(await session.scalars(
        select(WorkCheckpoint)
        .join(SessionEvent, WorkCheckpoint.boundary_event_id == SessionEvent.id)
        .where(WorkCheckpoint.workspace_id == workspace_id)
        .order_by(
            SessionEvent.occurred_at.desc().nulls_last(),
            SessionEvent.sequence_number.desc(),
            WorkCheckpoint.schema_version.desc(),
            WorkCheckpoint.created_at.desc(),
            WorkCheckpoint.id.desc(),
        )
        .options(
            selectinload(WorkCheckpoint.items).selectinload(CheckpointItem.evidence),
            selectinload(WorkCheckpoint.verifications),
            selectinload(WorkCheckpoint.boundary_event),
            selectinload(WorkCheckpoint.source_document),
        )
        .limit(min(300, requested * 3))
    ))
    result: list[WorkCheckpoint] = []
    seen_boundaries: set[tuple[str, str, UUID]] = set()
    for checkpoint in values:
        key = (
            checkpoint.provider,
            checkpoint.session_id,
            checkpoint.boundary_event_id,
        )
        if key in seen_boundaries:
            continue
        seen_boundaries.add(key)
        result.append(checkpoint)
        if len(result) >= requested:
            break
    return result


async def checkpoints_to_dicts(
    session: AsyncSession,
    checkpoints: Iterable[WorkCheckpoint],
) -> list[dict[str, Any]]:
    """Serialize checkpoints with one coherent session-tip lookup."""

    values = list(checkpoints)
    pairs = {(item.provider, item.session_id) for item in values}
    tips: dict[tuple[str, str], dict[str, Any]] = {}
    if values and pairs:
        rows = await session.execute(
            select(
                SessionEvent.provider,
                SessionEvent.session_id,
                func.max(SessionEvent.sequence_number),
                func.max(SessionEvent.occurred_at),
            )
            .where(
                SessionEvent.workspace_id == values[0].workspace_id,
                tuple_(SessionEvent.provider, SessionEvent.session_id).in_(pairs),
            )
            .group_by(SessionEvent.provider, SessionEvent.session_id)
        )
        for provider, session_id, sequence_number, occurred_at in rows:
            tips[(provider, session_id)] = {
                "sequence_number": sequence_number,
                "occurred_at": occurred_at,
            }
    return [
        checkpoint_to_dict(
            item,
            session_tip=tips.get((item.provider, item.session_id)),
        )
        for item in values
    ]


def checkpoint_to_dict(
    checkpoint: WorkCheckpoint,
    *,
    session_tip: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(checkpoint.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    sections: dict[str, list[dict[str, Any]]] = {
        category: [] for category in CHECKPOINT_CATEGORIES
    }
    for item in sorted(checkpoint.items, key=lambda value: (value.category, value.ordinal)):
        try:
            item_payload = json.loads(item.payload_json or "{}")
        except (TypeError, json.JSONDecodeError):
            item_payload = {}
        sections.setdefault(item.category, []).append({
            "id": str(item.id),
            "item_key": item.item_key,
            "statement": item.statement,
            "state": item.state,
            "truth_state": item.truth_state,
            "payload": item_payload,
            "evidence": [
                {
                    "id": str(evidence.id),
                    "type": evidence.evidence_type,
                    "session_event_id": (
                        str(evidence.session_event_id) if evidence.session_event_id else None
                    ),
                    "source_document_id": (
                        str(evidence.source_document_id) if evidence.source_document_id else None
                    ),
                    "supports": evidence.supports,
                    "observed_at": evidence.observed_at,
                    "locator": _json_object(evidence.locator_json),
                }
                for evidence in item.evidence
            ],
        })
    sections, projection = _safe_checkpoint_projection(checkpoint, sections)
    payload = dict(payload)
    payload["sections"] = {
        category: [
            {
                "item_key": item["item_key"],
                "statement": item["statement"],
                "state": item["state"],
                "truth_state": item["truth_state"],
                "payload": item["payload"],
                "evidence_event_ids": [
                    evidence["session_event_id"]
                    for evidence in item["evidence"]
                    if evidence["session_event_id"]
                ],
            }
            for item in sections[category]
        ]
        for category in CHECKPOINT_CATEGORIES
    }
    verifications = sorted(
        checkpoint.verifications,
        key=lambda value: (value.verified_at, value.id),
        reverse=True,
    )
    boundary = _boundary_context(checkpoint, payload, session_tip=session_tip)
    activity = _checkpoint_activity(checkpoint, sections, boundary)
    return {
        "id": str(checkpoint.id),
        "workspace_id": str(checkpoint.workspace_id),
        "provider": checkpoint.provider,
        "session_id": checkpoint.session_id,
        "source_document_id": str(checkpoint.source_document_id),
        "boundary_event_id": str(checkpoint.boundary_event_id),
        "trigger": checkpoint.trigger,
        "schema_version": checkpoint.schema_version,
        "capture_status": (
            checkpoint.capture_status if projection["valid"] else "incomplete"
        ),
        "continuation_status": (
            checkpoint.continuation_status if projection["valid"] else "review_required"
        ),
        "projection": projection,
        "boundary": boundary,
        "currentness": boundary["currentness"],
        "activity": activity,
        "repo": {
            "root": checkpoint.repo_root,
            "branch": checkpoint.branch,
            "head_commit": checkpoint.head_commit,
            "worktree_fingerprint": checkpoint.worktree_fingerprint,
        },
        "sections": sections,
        "verification": _verification_to_dict(verifications[0]) if verifications else None,
        "verification_history": [_verification_to_dict(item) for item in verifications],
        "payload_sha256": checkpoint.payload_sha256,
        "payload": payload,
        "supersedes_checkpoint_id": (
            str(checkpoint.supersedes_checkpoint_id)
            if checkpoint.supersedes_checkpoint_id
            else None
        ),
        "created_at": checkpoint.created_at,
    }


def _boundary_context(
    checkpoint: WorkCheckpoint,
    payload: dict[str, Any],
    *,
    session_tip: dict[str, Any] | None,
) -> dict[str, Any]:
    payload_boundary = payload.get("boundary")
    payload_boundary = payload_boundary if isinstance(payload_boundary, dict) else {}
    boundary_event = checkpoint.__dict__.get("boundary_event")
    source_document = checkpoint.__dict__.get("source_document")
    boundary_event_type = (
        getattr(boundary_event, "event_type", None)
        or payload_boundary.get("event_type")
    )
    pre_compaction = boundary_event_type == "compaction_boundary"
    boundary_at = (
        getattr(boundary_event, "occurred_at", None)
        or _parse_datetime(payload_boundary.get("occurred_at"))
    )
    sequence_number = (
        getattr(boundary_event, "sequence_number", None)
        or payload_boundary.get("sequence_number")
    )
    latest_sequence = (session_tip or {}).get("sequence_number")
    has_newer_events = bool(
        isinstance(sequence_number, int)
        and isinstance(latest_sequence, int)
        and latest_sequence > sequence_number
    )
    if has_newer_events:
        state = "superseded"
        label = "Superseded checkpoint"
        reason = "This session has events after the captured boundary."
    elif boundary_at is None:
        state = "unknown"
        label = "Checkpoint boundary"
        reason = "The source did not provide a trustworthy boundary time."
    elif utc_now() - boundary_at > timedelta(hours=24):
        state = "historical"
        label = "Historical checkpoint"
        reason = "This is an older immutable session boundary, not live session state."
    else:
        state = "captured"
        label = "Recent checkpoint boundary"
        reason = "This is immutable state at the captured boundary, not a live goal."

    metadata = _json_object(
        getattr(source_document, "metadata_json", None) if source_document else None
    )
    source_activity_at = _first_datetime(
        metadata.get("ended_at"),
        metadata.get("updated_at"),
        metadata.get("source_modified_at"),
        metadata.get("started_at"),
    )
    return {
        "event_id": str(checkpoint.boundary_event_id),
        "event_type": boundary_event_type,
        "snapshot_phase": "pre_compaction" if pre_compaction else "session_tip",
        "snapshot_phase_label": (
            "Pre-compaction snapshot" if pre_compaction else "Session-tip snapshot"
        ),
        "snapshot_phase_description": (
            "Captures session state immediately before context compaction and excludes "
            "all events after the boundary."
            if pre_compaction else
            "Captures session state through the selected latest event."
        ),
        "sequence_number": sequence_number,
        "occurred_at": boundary_at,
        "captured_at": checkpoint.created_at,
        "source_ingested_at": (
            getattr(source_document, "ingested_at", None) if source_document else None
        ),
        "source_activity_at": source_activity_at,
        "session_tip_sequence": latest_sequence,
        "session_tip_at": (session_tip or {}).get("occurred_at"),
        "has_newer_events": has_newer_events,
        "currentness": {
            "state": state,
            "label": label,
            "is_live": False,
            "reason": reason,
        },
    }


def _safe_checkpoint_projection(
    checkpoint: WorkCheckpoint,
    sections: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Make legacy checkpoints safe to display without mutating audit records."""

    projected = {category: list(sections.get(category) or []) for category in CHECKPOINT_CATEGORIES}
    goals = [
        item for item in projected["goal"]
        if is_substantive_user_request(str(item.get("statement") or ""))
    ]
    if not goals:
        return (
            {category: [] for category in CHECKPOINT_CATEGORIES},
            {
                "valid": False,
                "state": "missing_substantive_goal",
                "reason": (
                    "The stored checkpoint had no substantive user goal; continuation "
                    "controls and runtime instructions were excluded."
                ),
                "stored_schema_version": checkpoint.schema_version,
            },
        )

    goal = goals[-1]
    projected["goal"] = [goal]
    goal_sequence = _item_sequence(goal)
    for category in CHECKPOINT_CATEGORIES:
        if category == "goal":
            continue
        safe_items: list[dict[str, Any]] = []
        for item in projected[category]:
            statement = str(item.get("statement") or "")
            if is_session_instruction_noise(statement):
                continue
            sequence = _item_sequence(item)
            if (
                checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION
                and goal_sequence is not None
                and (sequence is None or sequence < goal_sequence)
            ):
                continue
            safe_items.append(item)
        projected[category] = safe_items

    valid = bool(projected["exact_next_action"])
    return projected, {
        "valid": valid,
        "state": "safe" if valid else "missing_scoped_next_action",
        "reason": (
            "All displayed items belong to the substantive goal at this boundary."
            if valid
            else "No evidence-linked next action belongs to the displayed goal."
        ),
        "stored_schema_version": checkpoint.schema_version,
    }


def _checkpoint_activity(
    checkpoint: WorkCheckpoint,
    sections: dict[str, list[dict[str, Any]]],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    goals = sections.get("goal") or []
    raw_goal = goals[0].get("statement") if goals else None
    request = str(raw_goal or "").strip() if is_substantive_user_request(raw_goal) else None
    goal_sequence = _item_sequence(goals[0]) if goals else None
    boundary_sequence = boundary.get("sequence_number")

    def in_goal_scope(item: dict[str, Any]) -> bool:
        sequence = _item_sequence(item)
        if goal_sequence is None or sequence is None:
            return checkpoint.schema_version == CHECKPOINT_SCHEMA_VERSION
        if sequence < goal_sequence:
            return False
        return not isinstance(boundary_sequence, int) or sequence <= boundary_sequence

    progress = [
        item for item in sections.get("progress") or []
        if in_goal_scope(item)
        and not is_session_instruction_noise(str(item.get("statement") or ""))
    ]
    latest_progress = max(progress, key=lambda item: _item_sequence(item) or -1, default=None)
    latest_update = (
        str(latest_progress.get("statement") or "").strip()
        if latest_progress else None
    )
    files = [
        str(item.get("statement") or "").strip()
        for item in sections.get("relevant_files") or []
        if in_goal_scope(item) and str(item.get("statement") or "").strip()
    ]
    checks = [
        item for item in sections.get("verification") or [] if in_goal_scope(item)
    ]
    passed = sum(item.get("payload", {}).get("passed") is True for item in checks)
    failed = sum(item.get("payload", {}).get("passed") is False for item in checks)
    return {
        "id": f"checkpoint:{checkpoint.id}",
        "kind": "checkpoint_boundary",
        "state": boundary["currentness"]["state"],
        "live": False,
        "evidence_level": "checkpoint_boundary",
        "title": request or "No substantive goal captured at this checkpoint",
        "request": request,
        "latest_update": latest_update,
        "rationale": None,
        "provider": checkpoint.provider,
        "session_id": checkpoint.session_id,
        "tool": checkpoint.provider,
        "model": None,
        "branch": checkpoint.branch,
        "started_at": None,
        "updated_at": boundary.get("occurred_at"),
        "ended_at": boundary.get("occurred_at"),
        "boundary": boundary,
        "currentness": boundary["currentness"],
        "changed_files": files,
        "verification": {
            "observed": len(checks),
            "passed": passed,
            "failed": failed,
        },
        "outcome": None,
        "source_card_id": None,
        "source_document_id": str(checkpoint.source_document_id),
    }


def _item_sequence(item: dict[str, Any]) -> int | None:
    values = [
        evidence.get("locator", {}).get("sequence_number")
        for evidence in item.get("evidence") or []
    ]
    values = [value for value in values if isinstance(value, int)]
    return max(values) if values else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if hasattr(value, "year"):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _first_datetime(*values: Any) -> datetime | None:
    return next((parsed for value in values if (parsed := _parse_datetime(value))), None)


def render_resume_bundle(checkpoint: WorkCheckpoint) -> str:
    data = checkpoint_to_dict(checkpoint)
    sections = data["sections"]
    lines = [
        "# Resume from verified work checkpoint",
        "",
        f"Checkpoint: {data['id']}",
        f"Session: {data['provider']} / {data['session_id']}",
        f"Boundary time: {data['boundary']['occurred_at'] or 'unavailable'}",
        f"Snapshot phase: {data['boundary']['snapshot_phase_label']}",
        f"Boundary state: {data['currentness']['label']}",
        f"Capture status: {data['capture_status']}",
        f"Continuation status: {data['continuation_status']}",
        f"Verification status: {(data['verification'] or {}).get('status', 'not_run')}",
        "",
    ]
    titles = {
        "goal": "Goal",
        "progress": "Progress",
        "decisions": "Decisions",
        "failed_attempts": "Failed attempts",
        "relevant_files": "Relevant files",
        "blockers": "Blockers",
        "verification": "Verification evidence",
        "exact_next_action": "Exact next action",
    }
    for category in CHECKPOINT_CATEGORIES:
        lines.extend([f"## {titles[category]}", ""])
        items = sections[category]
        if not items:
            lines.extend(["- None captured.", ""])
            continue
        for item in items:
            evidence_ids = ", ".join(
                str(entry["locator"].get("provider_event_id") or entry["session_event_id"])
                for entry in item["evidence"]
            )
            lines.append(
                f"- [{item['truth_state']}] {item['statement']} (evidence: {evidence_ids})"
            )
        lines.append("")
    lines.extend([
        "Continue only from the exact next action. Re-check repository freshness before "
        "claiming any item is still true.",
        "",
    ])
    return "\n".join(lines)


async def _resolve_boundary(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
    boundary_event_id: UUID | None,
) -> SessionEvent:
    conditions = (
        SessionEvent.workspace_id == workspace_id,
        SessionEvent.provider == provider,
        SessionEvent.session_id == session_id,
    )
    if boundary_event_id is not None:
        boundary = await session.scalar(
            select(SessionEvent).where(SessionEvent.id == boundary_event_id, *conditions)
        )
    else:
        boundary = await session.scalar(
            select(SessionEvent)
            .where(*conditions)
            .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
            .limit(1)
        )
    if boundary is None:
        raise ValueError("Session boundary not found")
    return boundary


def _build_sections(
    events: list[SessionEvent],
    snapshot: RepositorySnapshot | None,
) -> dict[str, list[DraftItem]]:
    sections: dict[str, list[DraftItem]] = {
        category: [] for category in CHECKPOINT_CATEGORIES
    }
    substantive_users = [
        (event, text)
        for event in events
        if (text := _checkpoint_user_request(event)) is not None
    ]
    goal_event, goal_statement = substantive_users[-1] if substantive_users else (None, None)
    continuation_events = [
        event for event in events
        if event.event_type == "user_request"
        and is_continuation_control(event.content)
        and (goal_event is None or event.sequence_number > goal_event.sequence_number)
    ]
    # Every derived section belongs to the latest substantive request. Long
    # sessions commonly contain several unrelated tasks; a checkpoint must not
    # pull blockers, progress, or next actions from an older task segment.
    events = (
        [event for event in events if event.sequence_number >= goal_event.sequence_number]
        if goal_event is not None
        else []
    )
    if goal_event is not None:
        sections["goal"] = [DraftItem(
            category="goal",
            statement=_statement(goal_statement),
            truth_state="reported",
            events=[goal_event],
        )]

    progress: list[DraftItem] = []
    for event in events:
        if (
            event.event_type != "assistant_update"
            or not event.content
            or is_session_instruction_noise(event.content)
        ):
            continue
        for sentence in _sentences(event.content):
            if _PROGRESS_SIGNAL.search(sentence):
                progress.append(DraftItem(
                    category="progress",
                    statement=_statement(sentence),
                    truth_state="reported",
                    events=[event],
                ))
    sections["progress"] = _dedupe_drafts(progress)[-MAX_ITEMS_PER_CATEGORY:]

    decisions: list[DraftItem] = []
    for event in events:
        if (
            event.event_type not in {"user_request", "assistant_update"}
            or not event.content
            or is_session_instruction_noise(event.content)
            or (
                event.event_type == "user_request"
                and is_continuation_control(event.content)
            )
        ):
            continue
        for sentence in _sentences(event.content):
            if _DECISION_SIGNAL.search(sentence):
                decisions.append(DraftItem(
                    category="decisions",
                    statement=_statement(sentence),
                    truth_state="reported",
                    events=[event],
                ))
    sections["decisions"] = _dedupe_drafts(decisions)[-MAX_ITEMS_PER_CATEGORY:]

    result_events = [
        event for event in events if event.event_type in {"command_result", "tool_result"}
    ]
    command_results = [event for event in result_events if event.event_type == "command_result"]
    failures: list[DraftItem] = []
    for event in result_events:
        payload = event_payload(event)
        exit_code = payload.get("exit_code")
        passed = payload.get("passed")
        if exit_code not in (None, 0) or passed is False:
            command = str(
                payload.get("command")
                or payload.get("tool_name")
                or "unknown tool operation"
            )
            failures.append(DraftItem(
                category="failed_attempts",
                statement=f"`{_single_line(command, 500)}` failed with exit code {exit_code}.",
                truth_state="observed",
                events=[event],
                state="historical",
                payload={"command": command, "cwd": payload.get("cwd"), "exit_code": exit_code},
            ))
    sections["failed_attempts"] = failures[-MAX_ITEMS_PER_CATEGORY:]

    file_evidence: dict[str, list[SessionEvent]] = {}
    for event in events:
        if event.event_type not in {
            "command_call", "command_result", "tool_call", "tool_result", "assistant_update"
        }:
            continue
        payload = event_payload(event)
        corpus_values = [payload.get("command")]
        if event.event_type in {"command_call", "tool_call", "assistant_update"}:
            corpus_values.append(event.content)
        if event.event_type in {"command_call", "tool_call"} and payload.get("input"):
            corpus_values.append(_canonical_json(payload["input"]))
        corpus = "\n".join(str(value) for value in corpus_values if value)
        for path in _extract_paths(corpus):
            file_evidence.setdefault(path, []).append(event)
    normalized_files: dict[str, tuple[list[SessionEvent], dict[str, Any]]] = {}
    for path, evidence in file_evidence.items():
        payload: dict[str, Any] = {"path": path}
        display_path = path
        if snapshot is not None:
            candidate = Path(path)
            absolute = candidate if candidate.is_absolute() else Path(snapshot.root) / candidate
            try:
                root = Path(snapshot.root).resolve()
                resolved = absolute.resolve()
                if resolved == root or root not in resolved.parents:
                    continue
                display_path = resolved.relative_to(root).as_posix()
                exists = resolved.is_file()
                tracked = display_path in snapshot.changed_files
                if not exists and not tracked:
                    continue
                payload = {
                    "path": display_path,
                    "exists_at_capture": exists,
                    "changed_at_capture": tracked,
                }
            except OSError:
                continue
        existing = normalized_files.get(display_path)
        if existing is None:
            normalized_files[display_path] = (list(evidence), payload)
        else:
            existing[0].extend(evidence)
    for display_path, (evidence, payload) in list(normalized_files.items())[-30:]:
        truth = "observed" if any(
            event.event_type in {"command_call", "command_result", "tool_call", "tool_result"}
            for event in evidence
        ) else "reported"
        sections["relevant_files"].append(DraftItem(
            category="relevant_files",
            statement=display_path,
            truth_state=truth,
            events=evidence[-3:],
            payload=payload,
        ))

    latest_by_command: dict[tuple[str, str], SessionEvent] = {}
    for event in result_events:
        payload = event_payload(event)
        command = str(
            payload.get("command")
            or (
                f"tool:{payload.get('tool_name')}"
                if payload.get("tool_name")
                else ""
            )
        ).strip()
        if command:
            latest_by_command[(str(payload.get("cwd") or ""), command)] = event
    blockers: list[DraftItem] = []
    for (_, command), event in latest_by_command.items():
        payload = event_payload(event)
        if payload.get("exit_code") not in (None, 0) or payload.get("passed") is False:
            blockers.append(DraftItem(
                category="blockers",
                statement=f"Latest run of `{_single_line(command, 500)}` is failing.",
                truth_state="observed",
                events=[event],
                payload={
                    "command": command,
                    "cwd": payload.get("cwd"),
                    "exit_code": payload.get("exit_code"),
                },
            ))
    for event in events:
        if (
            event.event_type == "assistant_update"
            and event.content
            and not is_session_instruction_noise(event.content)
        ):
            for sentence in _sentences(event.content):
                if _BLOCKER_SIGNAL.search(sentence):
                    blockers.append(DraftItem(
                        category="blockers",
                        statement=_statement(sentence),
                        truth_state="reported",
                        events=[event],
                    ))
    sections["blockers"] = _dedupe_drafts(blockers)[-MAX_ITEMS_PER_CATEGORY:]

    latest_verification_by_command: dict[tuple[str, str], DraftItem] = {}
    for event in command_results:
        payload = event_payload(event)
        command = str(payload.get("command") or "").strip()
        if not command or not _VERIFICATION_COMMAND.search(command):
            continue
        exit_code = payload.get("exit_code")
        label = "passed" if exit_code == 0 else "failed" if exit_code is not None else "completed"
        draft = DraftItem(
            category="verification",
            statement=f"`{_single_line(command, 500)}` {label}"
            + (f" (exit {exit_code})." if exit_code is not None else "."),
            truth_state="observed",
            events=[event],
            state=label,
            payload={
                "command": command,
                "cwd": payload.get("cwd"),
                "exit_code": exit_code,
                "passed": exit_code == 0 if exit_code is not None else None,
            },
        )
        latest_verification_by_command[(str(payload.get("cwd") or ""), command)] = draft
    sections["verification"] = list(latest_verification_by_command.values())[
        -MAX_ITEMS_PER_CATEGORY:
    ]

    next_item = _derive_next_action(
        events,
        goal_event,
        goal_statement,
        sections["blockers"],
        continuation_events[-1] if continuation_events else None,
    )
    if next_item is not None:
        sections["exact_next_action"] = [next_item]
    return sections


def _derive_next_action(
    events: list[SessionEvent],
    goal_event: SessionEvent | None,
    goal_statement: str | None,
    blockers: list[DraftItem],
    continuation_event: SessionEvent | None,
) -> DraftItem | None:
    if blockers:
        blocker = blockers[-1]
        command = blocker.payload.get("command")
        statement = (
            f"Fix the failure from `{_single_line(str(command), 500)}` and rerun that command."
            if command
            else f"Resolve this blocker: {blocker.statement}"
        )
        return DraftItem(
            category="exact_next_action",
            statement=statement,
            truth_state=blocker.truth_state,
            events=blocker.events,
        )
    for event in reversed(events):
        if (
            event.event_type != "assistant_update"
            or not event.content
            or is_session_instruction_noise(event.content)
        ):
            continue
        match = _NEXT_SIGNAL.search(event.content)
        if match:
            candidate = _sentences(match.group(1))
            if candidate:
                return DraftItem(
                    category="exact_next_action",
                    statement=_statement(candidate[0]),
                    truth_state="reported",
                    events=[event],
                )
    latest_assistant = next(
        (
            event for event in reversed(events)
            if event.event_type == "assistant_update"
            and event.content
            and not is_session_instruction_noise(event.content)
        ),
        None,
    )
    if (
        latest_assistant is not None
        and _COMPLETION_SIGNAL.search(latest_assistant.content or "")
        and (
            continuation_event is None
            or continuation_event.sequence_number < latest_assistant.sequence_number
        )
    ):
        return DraftItem(
            category="exact_next_action",
            statement=(
                "Review the completed result and start a new request only if more work is needed."
            ),
            truth_state="reported",
            events=[latest_assistant],
        )
    if goal_event is not None:
        return DraftItem(
            category="exact_next_action",
            statement=f"Continue the current request: {_statement(goal_statement, 900)}",
            truth_state="reported",
            events=[goal_event, *([continuation_event] if continuation_event else [])],
        )
    return None


def _checkpoint_user_request(event: SessionEvent) -> str | None:
    if event.event_type == "user_request" and is_substantive_user_request(event.content):
        return str(event.content).strip()
    if event.event_type == "runtime_instruction" and event.role == "user":
        return extract_delegated_user_request(event.content)
    return None


async def _capture_snapshot(
    events: list[SessionEvent],
    source_document: SourceDocument,
) -> RepositorySnapshot | None:
    candidates: list[str] = []
    for event in reversed(events):
        cwd = event_payload(event).get("cwd")
        if cwd:
            candidates.append(str(cwd))
    metadata = _json_object(source_document.metadata_json)
    for key in ("cwd", "workdir", "repo_path"):
        if metadata.get(key):
            candidates.append(str(metadata[key]))
    for raw in candidates:
        try:
            path = Path(raw).expanduser()
            if path.exists():
                return await capture_repository_snapshot(path)
        except (OSError, ValueError):
            continue
    return None


def _checkpoint_payload(
    checkpoint: WorkCheckpoint,
    *,
    boundary: SessionEvent,
    sections: dict[str, list[DraftItem]],
    snapshot: RepositorySnapshot | None,
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "workspace_id": str(checkpoint.workspace_id),
        "provider": checkpoint.provider,
        "session_id": checkpoint.session_id,
        "boundary": {
            "session_event_id": str(boundary.id),
            "provider_event_id": boundary.provider_event_id,
            "sequence_number": boundary.sequence_number,
            "event_type": boundary.event_type,
            "occurred_at": boundary.occurred_at.isoformat() if boundary.occurred_at else None,
            "source_document_id": str(boundary.source_document_id),
        },
        "trigger": checkpoint.trigger,
        "capture_status": checkpoint.capture_status,
        "continuation_status": checkpoint.continuation_status,
        "repo": snapshot.to_dict() if snapshot else None,
        "sections": {
            category: [
                {
                    "item_key": f"{category}:{index + 1}",
                    "statement": item.statement,
                    "state": item.state,
                    "truth_state": item.truth_state,
                    "payload": item.payload,
                    "evidence_event_ids": [str(event.id) for event in _unique_events(item.events)],
                }
                for index, item in enumerate(sections[category])
            ]
            for category in CHECKPOINT_CATEGORIES
        },
    }


def _verification_to_dict(value: CheckpointVerification) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "status": value.status,
        "worktree_fingerprint": value.worktree_fingerprint,
        "policy_version": value.policy_version,
        "results": _json_object(value.results_json),
        "verified_at": value.verified_at,
    }


def _sentences(value: str) -> list[str]:
    cleaned = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    return [
        part.strip(" -•\t")
        for part in re.split(r"(?<=[.!?])\s+|\s*[\r\n]+\s*", cleaned)
        if len(part.strip(" -•\t")) >= 4
    ]


def _statement(value: str | None, limit: int = MAX_STATEMENT_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _single_line(value: str, limit: int) -> str:
    return _statement(value, limit).replace("`", "'")


def _extract_paths(value: str) -> list[str]:
    paths: list[str] = []
    for match in _PATH_PATTERN.finditer(value):
        path = match.group(1).rstrip(".,);]}")
        lowered = path.lower()
        if any(part in lowered for part in ("node_modules/", ".git/objects/", "__pycache__/")):
            continue
        if path not in paths:
            paths.append(path)
    return paths[:100]


def _dedupe_drafts(values: Iterable[DraftItem]) -> list[DraftItem]:
    result: list[DraftItem] = []
    by_statement: dict[str, DraftItem] = {}
    for value in values:
        key = re.sub(r"\W+", " ", value.statement.lower()).strip()
        if not key:
            continue
        if key in by_statement:
            by_statement[key].events.extend(value.events)
            continue
        by_statement[key] = value
        result.append(value)
    return result


def _unique_events(values: Iterable[SessionEvent]) -> list[SessionEvent]:
    result: list[SessionEvent] = []
    seen: set[UUID] = set()
    for value in values:
        if value.id not in seen:
            result.append(value)
            seen.add(value.id)
    return result


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
