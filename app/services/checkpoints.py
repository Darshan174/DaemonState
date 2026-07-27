from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import (
    CheckpointEvidence,
    CheckpointItem,
    CheckpointVerification,
    SessionEvent,
    SourceDocument,
    WorkCheckpoint,
)
from app.schemas.continuation_execution import (
    ArtifactReference,
    is_non_verifiable_execution_guidance,
)
from app.services.access import AccessScope, source_access_predicate
from app.services.local_harness import RepositorySnapshot, capture_repository_snapshot
from app.services.request_artifacts import (
    TrustedRequestImageDescriptor,
    materialize_trusted_request_image_descriptor,
    recover_codex_request_image_descriptors,
    resolve_trusted_request_image_artifacts,
    trusted_request_image_descriptors_from_payload,
)
from app.services.session_events import event_payload
from app.services.session_scope import (
    normalize_optional_session_key,
    normalize_session_key,
    session_provider_values,
)
from app.services.session_summary import (
    extract_delegated_user_request,
    extract_user_authored_request,
    is_continuation_control,
    is_session_instruction_noise,
    is_substantive_user_request,
    normalize_substantive_user_request,
)
from app.time import utc_now


CHECKPOINT_SCHEMA_VERSION = "work_checkpoint.v7"
SESSION_HANDOFF_SCHEMA_VERSION = "session_handoff.v1"
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
SESSION_HANDOFF_RENDERED_FILE_LIMIT = 30

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
_DERIVED_COMMAND_BLOCKER = re.compile(
    r"^Latest run of `[^`]+` is failing\.$",
    re.IGNORECASE,
)
_INTERNAL_TOOL_NEXT_ACTION = re.compile(
    r"^Fix the failure from `tool:[^`]+` and rerun that command\.$",
    re.IGNORECASE,
)
_DERIVED_BLOCKER_NEXT_ACTION = re.compile(
    r"^Resolve this blocker:\s+",
    re.IGNORECASE,
)
_INACTIVE_BLOCKER_STATES = {
    "cancelled",
    "completed",
    "dismissed",
    "historical",
    "rejected",
    "resolved",
    "superseded",
}
_PATH_PATTERN = re.compile(
    r"(?<![\w])("
    r"(?:/(?:[^\s:'\"`<>|]+/)*[^\s:'\"`<>|]+\.[A-Za-z0-9]{1,12})|"
    r"(?:(?:app|frontend|tests|scripts|docs|src|migrations|alembic)/"
    r"[A-Za-z0-9_@+./-]+)|"
    r"(?:[A-Za-z0-9_.@+-]+\.(?:py|tsx?|jsx?|md|json|ya?ml|sql|toml|css|scss|sh))"
    r")"
)
_SESSION_USER_TURN_RE = re.compile(
    r"(?ms)^\[(?:USER|HUMAN|YOU)\]\r?\n"
    r"(.*?)(?=^\[[A-Z][A-Z_ -]*\]\r?\n|\Z)"
)
_TRUNCATED_OUTPUT_SUFFIXES = (
    "\r\n[output truncated]",
    "\n[output truncated]",
    "[output truncated]",
)
_MIN_RECOVERY_PREFIX_CHARS = 256
_READ_ONLY_INSPECTION_COMMANDS = {
    "cat",
    "command",
    "env",
    "find",
    "grep",
    "head",
    "ls",
    "printenv",
    "pwd",
    "rg",
    "sed",
    "tail",
    "test",
    "type",
    "which",
}
_EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE = re.compile(
    r"(?:chatgpt-conversation://|https?://(?:www\.)?chatgpt\.com/)",
    re.IGNORECASE,
)
_DEICTIC_SESSION_CONTEXT_DEPENDENCY_RE = re.compile(
    r"(?:"
    r"\b(?:the\s+)?last\s+(?:prompt|message|response)\b|"
    r"\b(?:the\s+)?(?:above|previous|referenced)\s+"
    r"(?:idea|proposal|conversation)\b|"
    r"\bidea\s+discussed\b|"
    r"\b(?:idea|proposal|approach)\s+(?:described|discussed)\s+"
    r"(?:above|before|previously)\b|"
    r"\bas\s+(?:discussed|described)\s+(?:above|before|previously)\b"
    r")",
    re.IGNORECASE,
)
_REFERENCED_CONVERSATION_MARKER_RE = re.compile(
    r"^#{1,6}\s*Referenced ChatGPT conversation:\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CURRENT_CODEX_REQUEST_MARKER_RE = re.compile(
    r"^#{1,6}\s*My request for Codex:\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CHATGPT_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\("
    r"(?:chatgpt-conversation://[^)]+|https?://(?:www\.)?chatgpt\.com/[^)]+)"
    r"\)",
    re.IGNORECASE,
)
_CHATGPT_CONVERSATION_ID_RE = re.compile(
    r"(?:chatgpt-conversation://|https?://(?:www\.)?chatgpt\.com/"
    r"(?:share|c)/)([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_SESSION_IMAGE_TAG_RE = re.compile(
    r"(?is)<image\b(?P<attributes>[^>]*)>"
    r"(?P<body>.*?)</image\s*>|"
    r"<image\b(?P<self_closing_attributes>[^>]*)/\s*>"
)
_SESSION_IMAGE_ATTRIBUTE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))"
)
_SESSION_IMAGE_BRACKET_ATTRIBUTE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.:-]*)\s*=\s*(\[[^\]\r\n]{1,300}\])"
)
_REQUIREMENT_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
_REQUIREMENT_ACTION_RE = re.compile(
    r"\b(?:add|allow|build|carry|change|check|confirm|copy|create|determine|"
    r"disable|display|divide|document|enable|ensure|expose|finish|fix|hide|"
    r"get|honor|implement|include|keep|make|move|must|need|paste|power|preserve|"
    r"prevent|reject|remove|rename|replace|restore|retain|route|separate|"
    r"send|should|show|split|support|surface|use|verify|wire|work|remember|"
    r"prioritize|failed)\b",
    re.IGNORECASE,
)
_HISTORICAL_QUOTED_REPORT_RE = re.compile(
    r"\b(?:the\s+)?(?:prior|previous|historical|earlier|other)\s+"
    r"(?:agent|assistant|user|model)\s+"
    r"(?:previously\s+|earlier\s+)?"
    r"(?:said|wrote|reported|claimed|asked|instructed|suggested|stated)"
    r"\s*(?:that\s+|[:,-]\s*)?"
    r"(?:\"[^\"\n]*\"|“[^”\n]*”|'[^'\n]*'|‘[^’\n]*’)",
    re.IGNORECASE,
)
_POSITIVE_REFERENCE_ADOPTION_RE = re.compile(
    r"\b(?:adopt|address|apply|build|fix|implement|ship|use)\s+(?:the\s+)?"
    r"(?:idea|proposal|approach|it|this|that)\b|"
    r"\b(?:idea|proposal|approach)\b[\s\S]{0,80}"
    r"\b(?:is\s+the\s+way\s+to\s+go|should\s+be\s+implemented)\b",
    re.IGNORECASE,
)
_NEGATED_REFERENCE_ADOPTION_RE = re.compile(
    r"\b(?:do\s+not|don't|never|not\s+going\s+to|without)\b[\s\S]{0,48}"
    r"\b(?:adopt|address|apply|build|fix|implement|ship|use)\b",
    re.IGNORECASE,
)
_HISTORICAL_QUOTED_SPEECH_RE = re.compile(
    r"^(?:the\s+)?(?:prior|previous|historical)\s+"
    r"(?:agent|assistant|user|transcript|message)\s+"
    r"(?:said|says|wrote|asked|claimed|reported)\b",
    re.IGNORECASE,
)
_GENERIC_CONTINUATION_RE = re.compile(
    r"^(?:continue|complete|finish|resume)\b[\s\S]*"
    r"(?:current|complete|recovered|carried)?\s*(?:request|task|work)\b",
    re.IGNORECASE,
)
_GENERIC_COMPLETION_CLAIM_RE = re.compile(
    r"^(?:implemented|completed|done|finished|fixed)"
    r"(?:\s+(?:it|everything|end[\s-]*to[\s-]*end|the\s+(?:task|work|request)))?[.!]?$",
    re.IGNORECASE,
)
_COMPLETION_CLAIM_RE = re.compile(
    r"\b(?:added|built|created|done|finished|fixed|implemented|removed|"
    r"replaced|updated|wired)\b",
    re.IGNORECASE,
)
_NEGATED_COMPLETION_RE = re.compile(
    r"\b(?:not|never|isn't|isnt|wasn't|wasnt|aren't|arent|unfinished|"
    r"incomplete|still\s+needs?|failed\s+to)\b[\s\S]{0,64}"
    r"\b(?:added|built|created|done|finished|fixed|implemented|removed|"
    r"replaced|updated|wired)\b|"
    r"\b(?:added|built|created|done|finished|fixed|implemented|removed|"
    r"replaced|updated|wired)\b[\s\S]{0,32}"
    r"\b(?:not|never|incomplete|incorrect|wrong)\b",
    re.IGNORECASE,
)
_STATUS_TOKEN_ALIASES = {
    "added": "add",
    "built": "build",
    "created": "create",
    "finished": "finish",
    "fixed": "fix",
    "implemented": "implement",
    "removed": "remove",
    "replaced": "replace",
    "updated": "update",
    "wired": "wire",
}
_STATUS_MATCH_STOPWORDS = frozenset({
    "about",
    "after",
    "against",
    "also",
    "and",
    "before",
    "build",
    "change",
    "complete",
    "continue",
    "create",
    "current",
    "from",
    "have",
    "implement",
    "into",
    "must",
    "only",
    "request",
    "should",
    "that",
    "the",
    "their",
    "then",
    "this",
    "through",
    "user",
    "verify",
    "when",
    "with",
    "work",
})
_CHANGE_TASK_RE = re.compile(
    r"\b(?:add|build|change|create|edit|fix|implement|modify|remove|repair|"
    r"replace|ship|update|write)\b|"
    r"\bwork\s+on\s+this\b|"
    r"\bget\s+this\s+done\b",
    re.IGNORECASE,
)
_DIAGNOSE_TASK_RE = re.compile(
    r"\b(?:debug|diagnose|investigate|reproduce|root cause|why)\b",
    re.IGNORECASE,
)
_REVIEW_TASK_RE = re.compile(
    r"\b(?:audit|assess|inspect|rate|review|critique|evaluate)\b",
    re.IGNORECASE,
)
_REPORT_TASK_RE = re.compile(
    r"\b(?:explain|report|summarize|describe|answer)\b",
    re.IGNORECASE,
)
_NO_EDIT_TASK_RE = re.compile(
    r"\b(?:do\s+not|don't|never|without)\s+(?:edit|change|implement|modify|write)\b|"
    r"\bread[\s-]*only\b|"
    r"\bno\s+(?:edits?|changes?|implementation)\b",
    re.IGNORECASE,
)
_NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE = re.compile(
    r"\b(?:background|context only|example|for reference|historical|history|"
    r"non[- ]?goals?|out of scope|prior (?:conversation|prompt|response)|"
    r"quoted|transcript)\b",
    re.IGNORECASE,
)
_TOOL_SELECTION_DECISION_RE = re.compile(
    r"\b(?:i|we)\s*(?:(?:'ll|’ll|will|would|should|can)\s+|"
    r"(?:am|are|'m|’m|'re|’re)\s+(?:now\s+)?)"
    r"(?:call|inspect\s+with|open|run|use|using)\s+"
    r"(?:the\s+)?(?:browser|command|exec|git|js|node|playwright|pytest|"
    r"python|rg|shell|terminal|tool)\b",
    re.IGNORECASE,
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
    _bind_checkpoint_goal_artifacts(
        sections,
        source_document=source_document,
        provider=provider,
    )
    goal_present = bool(sections["goal"])
    next_present = bool(sections["exact_next_action"])
    capture_status = "complete" if goal_present and next_present else "incomplete"
    active_blockers = [
        item
        for item in sections["blockers"]
        if item.state.strip().lower() not in _INACTIVE_BLOCKER_STATES
    ]
    continuation_status = (
        "blocked"
        if active_blockers
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
    provider: str | None = None,
    session_id: str | None = None,
    access_scope: AccessScope | None = None,
) -> WorkCheckpoint | None:
    conditions = [WorkCheckpoint.workspace_id == workspace_id]
    normalized_session = normalize_optional_session_key(provider, session_id)
    if normalized_session is not None:
        normalized_provider, normalized_session_id = normalized_session
        conditions.extend((
            WorkCheckpoint.provider.in_(session_provider_values(normalized_provider)),
            WorkCheckpoint.session_id == normalized_session_id,
        ))
    conditions.extend(_checkpoint_access_conditions(
        workspace_id=workspace_id,
        access_scope=access_scope,
    ))

    return await session.scalar(
        select(WorkCheckpoint)
        .join(SessionEvent, WorkCheckpoint.boundary_event_id == SessionEvent.id)
        .where(*conditions)
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
    provider: str | None = None,
    session_id: str | None = None,
    access_scope: AccessScope | None = None,
) -> list[WorkCheckpoint]:
    requested = max(1, min(limit, 100))
    conditions = [WorkCheckpoint.workspace_id == workspace_id]
    normalized_session = normalize_optional_session_key(provider, session_id)
    if normalized_session is not None:
        normalized_provider, normalized_session_id = normalized_session
        conditions.extend((
            WorkCheckpoint.provider.in_(session_provider_values(normalized_provider)),
            WorkCheckpoint.session_id == normalized_session_id,
        ))
    conditions.extend(_checkpoint_access_conditions(
        workspace_id=workspace_id,
        access_scope=access_scope,
    ))
    values = list(await session.scalars(
        select(WorkCheckpoint)
        .join(SessionEvent, WorkCheckpoint.boundary_event_id == SessionEvent.id)
        .where(*conditions)
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
    *,
    access_scope: AccessScope | None = None,
) -> list[dict[str, Any]]:
    """Serialize checkpoints with one coherent session-tip lookup."""

    values = list(checkpoints)
    pairs = {
        key
        for item in values
        if (key := normalize_session_key(item.provider, item.session_id)) is not None
    }
    tips: dict[tuple[str, str], dict[str, Any]] = {}
    if values and pairs:
        pair_predicates = [
            and_(
                SessionEvent.provider.in_(session_provider_values(provider)),
                SessionEvent.session_id == session_id,
            )
            for provider, session_id in pairs
        ]
        tip_conditions = [
            SessionEvent.workspace_id == values[0].workspace_id,
            or_(*pair_predicates),
        ]
        if access_scope is not None:
            tip_conditions.append(source_access_predicate(
                access_scope,
                workspace_id=values[0].workspace_id,
            ))
        rows = await session.execute(
            select(
                SessionEvent.provider,
                SessionEvent.session_id,
                func.max(SessionEvent.sequence_number),
                func.max(SessionEvent.occurred_at),
            )
            .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
            .where(*tip_conditions)
            .group_by(SessionEvent.provider, SessionEvent.session_id)
        )
        for provider, session_id, sequence_number, occurred_at in rows:
            key = normalize_session_key(provider, session_id)
            if key is None or key not in pairs:
                continue
            current = tips.setdefault(key, {
                "sequence_number": None,
                "occurred_at": None,
            })
            if sequence_number is not None:
                current["sequence_number"] = max(
                    sequence_number,
                    current["sequence_number"] or sequence_number,
                )
            if occurred_at is not None:
                current["occurred_at"] = max(
                    occurred_at,
                    current["occurred_at"] or occurred_at,
                )
    serialized: list[dict[str, Any]] = []
    for item in values:
        # The list/latest endpoints drive which immutable checkpoint the UI
        # offers for copying. Historical rows can contain a capped goal even
        # though the lossless turn remains recoverable from their bound source
        # revision. Apply the same source-scoped recovery used by the handoff
        # endpoint here so selection never skips the newest checkpoint and
        # silently routes the user to an older, unrelated task.
        recovered_goal = await resolve_session_handoff_request_verbatim(
            session,
            item,
            access_scope=access_scope,
        )
        serialized.append(checkpoint_to_dict(
            item,
            session_tip=tips.get(normalize_session_key(
                item.provider,
                item.session_id,
            )),
            recovered_goal=recovered_goal,
        ))
    return serialized


def _checkpoint_access_conditions(
    *,
    workspace_id: UUID,
    access_scope: AccessScope | None,
) -> tuple:
    """Keep hidden checkpoint and evidence sources out of result pagination."""

    if access_scope is None:
        return ()
    checkpoint_source_is_visible = exists(
        select(SourceDocument.id)
        .where(
            SourceDocument.id == WorkCheckpoint.source_document_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
        .correlate(WorkCheckpoint)
    )
    evidence_source_is_visible = exists(
        select(SourceDocument.id)
        .where(
            SourceDocument.id == CheckpointEvidence.source_document_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
        .correlate(CheckpointEvidence)
    )
    hidden_evidence_source = exists(
        select(CheckpointEvidence.id)
        .join(
            CheckpointItem,
            CheckpointEvidence.checkpoint_item_id == CheckpointItem.id,
        )
        .where(
            CheckpointItem.checkpoint_id == WorkCheckpoint.id,
            CheckpointEvidence.source_document_id.is_not(None),
            ~evidence_source_is_visible,
        )
        .correlate(WorkCheckpoint)
    )
    return checkpoint_source_is_visible, ~hidden_evidence_source


def checkpoint_to_dict(
    checkpoint: WorkCheckpoint,
    *,
    session_tip: dict[str, Any] | None = None,
    recovered_goal: str | None = None,
    filter_presentation_noise: bool = False,
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
    sections, projection = _safe_checkpoint_projection(
        checkpoint,
        sections,
        recovered_goal=recovered_goal,
        filter_presentation_noise=filter_presentation_noise,
    )
    projected_continuation_status = checkpoint.continuation_status
    if (
        projected_continuation_status == "blocked"
        and not any(
            str(item.get("state") or "active").strip().lower()
            not in _INACTIVE_BLOCKER_STATES
            for item in sections["blockers"]
        )
    ):
        projected_continuation_status = "review_required"
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
    task_key = next(
        (
            evidence["session_event_id"]
            for evidence in (sections.get("goal") or [{}])[0].get("evidence", [])
            if evidence.get("session_event_id")
        ),
        None,
    )
    return {
        "id": str(checkpoint.id),
        "task_key": task_key,
        "workspace_id": str(checkpoint.workspace_id),
        "provider": (
            normalize_session_key(checkpoint.provider, checkpoint.session_id)
            or (checkpoint.provider, checkpoint.session_id)
        )[0],
        "session_id": checkpoint.session_id,
        "source_document_id": str(checkpoint.source_document_id),
        "boundary_event_id": str(checkpoint.boundary_event_id),
        "trigger": checkpoint.trigger,
        "schema_version": checkpoint.schema_version,
        "capture_status": (
            checkpoint.capture_status if projection["valid"] else "incomplete"
        ),
        "continuation_status": (
            projected_continuation_status if projection["valid"] else "review_required"
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
    *,
    recovered_goal: str | None = None,
    filter_presentation_noise: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Make stored checkpoints safe to consume without mutating audit records."""

    projected = {category: list(sections.get(category) or []) for category in CHECKPOINT_CATEGORIES}
    goals = [
        item for item in projected["goal"]
        if is_substantive_user_request(str(item.get("statement") or ""))
    ]
    validated_recovery = _validated_session_request(recovered_goal)
    recovered_goal_projection = (
        not goals
        and validated_recovery is not None
        and len(projected["goal"]) <= 1
    )
    synthesized_missing_goal = bool(
        recovered_goal_projection and not projected["goal"]
    )
    recovered_goal_evidence: set[tuple[str, ...]] = set()
    if recovered_goal_projection:
        recovered_item = (
            dict(projected["goal"][0])
            if projected["goal"]
            else {
                "id": None,
                "item_key": "goal:recovered-at-boundary",
                "state": "active",
                "truth_state": "recovered",
                "evidence": [],
            }
        )
        recovered_payload = dict(recovered_item.get("payload") or {})
        recovered_payload.update({
            "request_verbatim": validated_recovery,
            "request_sha256": _sha256(validated_recovery),
            "derived_from_same_session_boundary": True,
        })
        recovered_item.update({
            "statement": validated_recovery,
            "payload": recovered_payload,
        })
        goals = [recovered_item]
        recovered_goal_evidence = _item_evidence_keys(recovered_item)
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
    latest_progress_sequence = max(
        (
            sequence
            for item in projected["progress"]
            if (sequence := _item_sequence(item)) is not None
        ),
        default=None,
    )
    latest_completion_sequence = max(
        (
            sequence
            for item in projected["progress"]
            if _positive_completion_claim(
                str(item.get("statement") or "")
            )
            and (sequence := _item_sequence(item)) is not None
        ),
        default=None,
    )
    derived_fallback_superseded = False
    for category in CHECKPOINT_CATEGORIES:
        if category == "goal":
            continue
        safe_items: list[dict[str, Any]] = []
        for item in projected[category]:
            statement = str(item.get("statement") or "")
            sequence = _item_sequence(item)
            if (
                synthesized_missing_goal
                and category == "exact_next_action"
                and _GENERIC_CONTINUATION_RE.match(statement.strip())
            ):
                item = {
                    **item,
                    "payload": {
                        **(item.get("payload") or {}),
                        "derived_from_recovered_goal": True,
                    },
                }
            sourced_only_from_recovered_goal = (
                recovered_goal_projection
                and _item_is_sourced_only_from(item, recovered_goal_evidence)
            )
            if (
                category == "decisions"
                and sourced_only_from_recovered_goal
            ):
                # Historical checkpoint releases derived decisions from the raw
                # user transport. If that transport was truncated, referenced
                # conversation text cannot be distinguished from user authority.
                # Keep later assistant-sourced decisions, but drop this unsafe
                # goal-event projection.
                continue
            if (
                category == "exact_next_action"
                and sourced_only_from_recovered_goal
                and "[output truncated]" in statement.casefold()
            ):
                item = {
                    **item,
                    "statement": (
                        "Continue the complete recovered request shown under "
                        "“Carried goal from this session.”"
                    ),
                    "payload": {
                        **(item.get("payload") or {}),
                        "derived_from_recovered_goal": True,
                    },
                }
                statement = str(item["statement"])
            if (
                category == "exact_next_action"
                and bool(
                    (item.get("payload") or {}).get(
                        "derived_from_recovered_goal"
                    )
                )
                and latest_completion_sequence is not None
                and sequence is not None
                and sequence < latest_completion_sequence
            ):
                # A fallback copied from the original lead is not a later
                # instruction to reopen work. Newer scoped completion
                # evidence supersedes it.
                derived_fallback_superseded = True
                continue
            if is_session_instruction_noise(statement):
                continue
            if (
                category == "blockers"
                and str(item.get("truth_state") or "").strip().lower() == "reported"
                and latest_progress_sequence is not None
                and sequence is not None
                and sequence < latest_progress_sequence
            ):
                # Intermediate agent commentary often announces a blocker and
                # later reports successful progress. Preserve the earlier
                # statement as history, but never present it as live authority.
                item = {**item, "state": "historical"}
            if (
                filter_presentation_noise
                and
                category == "blockers"
                and _DERIVED_COMMAND_BLOCKER.fullmatch(statement.strip())
                and str(item.get("payload", {}).get("command") or "").strip()
            ):
                # A failed command is execution history, not proof that a new
                # agent cannot start. It remains available under failed_attempts
                # and verification evidence.
                continue
            if (
                filter_presentation_noise
                and
                category == "failed_attempts"
                and _is_low_signal_failed_attempt(item)
            ):
                # Read-only discovery failures and harness transport errors do
                # not describe a failed implementation approach. Keep genuine
                # test, build, lint, and mutation failures.
                continue
            if (
                filter_presentation_noise
                and category == "verification"
                and _is_low_signal_failed_attempt(item)
            ):
                # Environment probes are not task verification even when the
                # harness recorded them in a verification-shaped event.
                continue
            if (
                filter_presentation_noise
                and
                category == "exact_next_action"
                and _INTERNAL_TOOL_NEXT_ACTION.fullmatch(statement.strip())
            ):
                # Harness plumbing failures such as tool:write_stdin are not a
                # user task and must never become the next agent's instruction.
                continue
            if (
                filter_presentation_noise
                and
                category == "exact_next_action"
                and _DERIVED_BLOCKER_NEXT_ACTION.match(statement.strip())
                and latest_progress_sequence is not None
                and sequence is not None
                and sequence < latest_progress_sequence
            ):
                # This instruction was synthesized from a reported blocker that
                # newer progress has already superseded.
                continue
            if (
                checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION
                and goal_sequence is not None
                and (sequence is None or sequence < goal_sequence)
            ):
                continue
            safe_items.append(item)
        projected[category] = safe_items

    if derived_fallback_superseded and not projected["exact_next_action"]:
        # Historical compaction rows sometimes contain only an original
        # "continue the request" fallback. Once later completion evidence
        # supersedes that fallback, leaving the projection empty makes list
        # consumers skip this newest boundary and copy an older task. Preserve
        # chronology without trusting the completion claim by deriving a
        # read-safe reconciliation action for either stored or recovered goals.
        projected["exact_next_action"] = [{
            "id": None,
            "item_key": "exact_next_action:reconcile-goal",
            "statement": (
                "Inspect the current repository and verify the carried goal's "
                "current status before acting on any historical completion claim."
            ),
            "state": "active",
            "truth_state": "derived",
            "payload": {
                "derived_from_reconciliation": True,
                "source_completion_sequence": latest_completion_sequence,
            },
            "evidence": [],
        }]
    elif recovered_goal_projection and not projected["exact_next_action"]:
        projected["exact_next_action"] = [{
            "id": None,
            "item_key": "exact_next_action:continue-recovered-goal",
            "statement": (
                "Continue the complete recovered request shown under "
                "“Carried goal from this session.”"
            ),
            "state": "active",
            "truth_state": "derived",
            "payload": {
                "derived_from_recovered_goal": True,
            },
            "evidence": [],
        }]

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
    request = normalize_substantive_user_request(raw_goal)
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


def _item_evidence_keys(item: dict[str, Any]) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    for evidence in item.get("evidence") or []:
        session_event_id = str(evidence.get("session_event_id") or "").strip()
        if session_event_id:
            keys.add(("session_event_id", session_event_id))
        locator = evidence.get("locator")
        locator = locator if isinstance(locator, dict) else {}
        provider_event_id = str(locator.get("provider_event_id") or "").strip()
        if provider_event_id:
            keys.add((
                "provider_event_id",
                str(evidence.get("source_document_id") or ""),
                provider_event_id,
            ))
    return keys


def _item_is_sourced_only_from(
    item: dict[str, Any],
    source_keys: set[tuple[str, ...]],
) -> bool:
    evidence = [
        entry
        for entry in item.get("evidence") or []
        if entry.get("supports") is not False
    ]
    return bool(
        evidence
        and source_keys
        and all(_item_evidence_keys({"evidence": [entry]}) & source_keys for entry in evidence)
    )


def _is_low_signal_failed_attempt(item: dict[str, Any]) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    command = str(payload.get("command") or "").strip()
    if not command:
        statement = str(item.get("statement") or "").strip()
        match = re.match(r"^`([^`]+)`\s+failed\b", statement, re.IGNORECASE)
        command = match.group(1).strip() if match is not None else ""
    if not command:
        return False
    lowered = command.casefold()
    if lowered in {
        "js",
        "node_repl.js",
        "write_stdin",
    } or lowered.startswith((
        "tool:",
        "functions.",
        "mcp__",
    )):
        return True
    if re.fullmatch(
        r"(?:python\d*(?:\.\d+)?|node|npm|pnpm|yarn|git|ruff)"
        r"\s+(?:--version|-v|version)",
        lowered,
    ):
        return True
    if _is_compound_discovery_command(command):
        return True
    return _is_read_only_inspection_command(command)


def _is_tool_selection_statement(statement: str) -> bool:
    return bool(_TOOL_SELECTION_DECISION_RE.search(statement))


def _is_compound_discovery_command(command: str) -> bool:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in command.splitlines()
        if line.strip()
    ]
    if len(lines) >= 2:
        version_probe = re.compile(
            r"(?:which|command\s+-v)\s+[A-Za-z0-9_.+-]+|"
            r"(?:python\d*(?:\.\d+)?|node|npm|pnpm|yarn|git|ruff|pytest)"
            r"\s+(?:--version|-v|version)",
            re.IGNORECASE,
        )
        if all(version_probe.fullmatch(line) for line in lines):
            return True

        heredoc = re.fullmatch(
            r"sqlite3\s+[^\s;&|<>]+\s+<<-?\s*"
            r"['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?",
            lines[0],
            re.IGNORECASE,
        )
        sqlite_lines = lines
        if heredoc is not None:
            terminator = heredoc.group(1)
            if len(lines) < 3 or lines[-1] != terminator:
                return False
            sqlite_lines = lines[1:-1]
        if all(
            _is_read_only_sqlite_probe(line)
            for line in sqlite_lines
        ):
            return True

    segments = _shell_command_segments(command)
    return bool(
        segments is not None
        and len(segments) >= 2
        and all(_is_read_only_discovery_segment(segment) for segment in segments)
    )


def _shell_command_segments(command: str) -> list[list[str]] | None:
    if not command.strip() or "$(" in command or "`" in command:
        return None
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", "||", ";", "|"}:
            if not segments[-1]:
                return None
            segments.append([])
            continue
        if token and set(token) <= set(";&|<>"):
            # Redirection, background execution, and malformed compound
            # operators are not safe discovery.
            return None
        segments[-1].append(token)
    if not segments or any(not segment for segment in segments):
        return None
    return segments


def _is_read_only_discovery_segment(segment: list[str]) -> bool:
    executable = Path(segment[0]).name.casefold()
    arguments = [value.casefold() for value in segment[1:]]
    if executable == "node":
        return _is_safe_package_script_probe(segment)
    if executable.startswith("python"):
        return bool(
            len(arguments) >= 3
            and arguments[:2] == ["-m", "pytest"]
            and "--collect-only" in arguments[2:]
        )
    if executable in {"pytest", "py.test"}:
        return "--collect-only" in arguments
    if executable in {"npm", "pnpm"}:
        return arguments in (["run"], ["pkg", "get", "scripts"])
    if executable == "yarn":
        return arguments == ["run"]
    return _is_read_only_inspection_command(shlex.join(segment))


def _is_safe_package_script_probe(segment: list[str]) -> bool:
    if (
        len(segment) != 3
        or segment[1].casefold() not in {"-e", "--eval"}
    ):
        return False
    script = segment[2]
    lowered = script.casefold()
    if "package.json" not in lowered or "scripts" not in lowered:
        return False
    if re.search(
        r"\b(?:child_process|exec|spawn|fork|eval|function|fetch|"
        r"https?|write|append|unlink|rename|mkdir|rmdir|chmod|chown|"
        r"truncate|rm)\b|process\s*\.",
        lowered,
    ):
        return False
    required_modules = re.findall(
        r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        script,
        re.IGNORECASE,
    )
    return bool(required_modules) and all(
        _is_safe_relative_package_json_path(module)
        for module in required_modules
    )


def _is_safe_relative_package_json_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if (
        not normalized
        or normalized.startswith(("/", "~"))
        or "\x00" in normalized
        or ":" in normalized
    ):
        return False
    parts = normalized.split("/")
    return bool(
        parts[-1] == "package.json"
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _has_definitive_verification_outcome(item: dict[str, Any]) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    passed = payload.get("passed")
    exit_code = payload.get("exit_code")
    if isinstance(passed, bool):
        return True
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return True
    states = {
        str(item.get("state") or "").strip().casefold(),
        str(payload.get("status") or "").strip().casefold(),
        str(payload.get("state") or "").strip().casefold(),
    }
    return bool(
        states
        & {
            "pass",
            "passed",
            "success",
            "succeeded",
            "fail",
            "failed",
            "failure",
            "error",
        }
    )


def _is_read_only_sqlite_probe(line: str) -> bool:
    candidate = line.strip()
    if candidate.casefold().startswith("sqlite3 "):
        if any(
            token in candidate.casefold()
            for token in (
                "--init",
                "-init",
                ".read",
                ".import",
                ".restore",
                ".dump",
            )
        ):
            return False
        try:
            arguments = shlex.split(candidate)
        except ValueError:
            return False
        if len(arguments) < 3 or arguments[0].casefold() != "sqlite3":
            return False
        candidate = arguments[-1].strip()
    return bool(
        re.match(
            r"^(?:\.schema(?:\s|$)|\.tables(?:\s|$)|select\b)",
            candidate,
            re.IGNORECASE,
        )
        or re.fullmatch(
            r"pragma\s+[A-Za-z0-9_.]+(?:\s*\([^;]*\))?\s*;?",
            candidate,
            re.IGNORECASE,
        )
    )


def _command_observation_key(
    item: dict[str, Any],
) -> tuple[str, str] | None:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    command = re.sub(
        r"\s+",
        " ",
        str(payload.get("command") or "").strip(),
    )
    if not command:
        return None
    cwd = str(payload.get("cwd") or "").strip()
    return cwd, command


def _dedupe_command_observations(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the newest observation for each command/cwd pair."""

    values = list(items)
    seen: set[tuple[str, str] | tuple[str, str, str]] = set()
    retained: list[dict[str, Any]] = []
    for item in reversed(values):
        command_key = _command_observation_key(item)
        key: tuple[str, str] | tuple[str, str, str] = (
            command_key
            if command_key is not None
            else (
                "statement",
                re.sub(
                    r"\W+",
                    " ",
                    str(item.get("statement") or "").casefold(),
                ).strip(),
                str(item.get("truth_state") or ""),
            )
        )
        if key in seen:
            continue
        seen.add(key)
        retained.append(item)
    return list(reversed(retained))


def _dedupe_presentation_items(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    values = list(items)
    seen: set[str] = set()
    retained: list[dict[str, Any]] = []
    for item in reversed(values):
        key = re.sub(
            r"\W+",
            " ",
            str(item.get("statement") or "").casefold(),
        ).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        retained.append(item)
    return list(reversed(retained))


def _is_read_only_inspection_command(command: str) -> bool:
    if not command.strip() or "$(" in command or "`" in command or "\n" in command:
        return False
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", "||", ";", "|"}:
            if not segments[-1]:
                return False
            segments.append([])
            continue
        if token and set(token) <= set(";&|<>"):
            # Redirection and background execution can write or launch work.
            return False
        segments[-1].append(token)
    if not segments or any(not segment for segment in segments):
        return False

    for segment in segments:
        executable = Path(segment[0]).name.casefold()
        if executable == "git":
            subcommand = next(
                (
                    value.casefold()
                    for value in segment[1:]
                    if not value.startswith("-")
                ),
                "",
            )
            if subcommand in {
                "branch",
                "diff",
                "log",
                "ls-files",
                "rev-parse",
                "show",
                "status",
            }:
                continue
            return False
        if executable not in _READ_ONLY_INSPECTION_COMMANDS:
            return False
        arguments = {value.casefold() for value in segment[1:]}
        if executable == "sed" and any(
            argument == "--in-place"
            or argument.startswith("--in-place=")
            or (
                argument.startswith("-")
                and not argument.startswith("--")
                and "i" in argument[1:]
            )
            for argument in arguments
        ):
            return False
        if executable == "find" and any(
            argument == "-delete"
            or argument.startswith("-exec")
            or argument.startswith("-ok")
            or argument.startswith("-fprint")
            or argument == "-fls"
            for argument in arguments
        ):
            return False
    return True


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
    sections = _handoff_presentation_sections(data["sections"])
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


async def resolve_session_handoff_request_verbatim(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    access_scope: AccessScope | None = None,
) -> str | None:
    """Resolve the lossless goal, including for historical v5 checkpoints."""

    data = checkpoint_to_dict(checkpoint)
    goals = data["sections"]["goal"]
    goal = goals[0] if goals else {}
    projected_goal_key = goal.get("item_key")
    raw_goal_items = sorted(
        (item for item in checkpoint.items if item.category == "goal"),
        key=lambda item: (item.ordinal, item.id),
    )
    goal_item = next(
        (
            item
            for item in raw_goal_items
            if projected_goal_key and item.item_key == projected_goal_key
        ),
        raw_goal_items[0] if len(raw_goal_items) == 1 else None,
    )
    if goal_item is None:
        return await _nearest_authoritative_session_request(
            session,
            checkpoint,
            boundary_sequence=data["boundary"].get("sequence_number"),
            access_scope=access_scope,
        )
    goal_payload = _json_object(goal_item.payload_json)
    stored_verbatim = goal_payload.get("request_verbatim")
    if isinstance(stored_verbatim, str) and stored_verbatim.strip():
        expected_sha256 = str(goal_payload.get("request_sha256") or "").strip()
        stored_is_intact = (
            not expected_sha256 or _sha256(stored_verbatim) == expected_sha256
        )
        if stored_is_intact:
            request = _validated_session_request(stored_verbatim)
            if request is not None:
                return request

    goal_evidence = [
        evidence
        for evidence in goal_item.evidence
        if evidence.supports and evidence.evidence_type == "session_event"
    ]
    evidence_event_ids = {
        evidence.session_event_id
        for evidence in goal_evidence
        if evidence.session_event_id is not None
    }
    evidence_source_ids = {
        evidence.source_document_id
        for evidence in goal_evidence
        if evidence.source_document_id is not None
    }
    reference_predicates = [
        SessionEvent.id == event_id
        for event_id in evidence_event_ids
    ]
    for evidence in goal_evidence:
        locator = _json_object(evidence.locator_json)
        provider_event_id = str(locator.get("provider_event_id") or "").strip()
        if not provider_event_id:
            continue
        predicate = SessionEvent.provider_event_id == provider_event_id
        if evidence.source_document_id is not None:
            predicate = and_(
                predicate,
                SessionEvent.source_document_id == evidence.source_document_id,
            )
        reference_predicates.append(predicate)

    normalized_session = (
        normalize_session_key(checkpoint.provider, checkpoint.session_id)
        or (checkpoint.provider, checkpoint.session_id)
    )
    provider, session_id = normalized_session
    boundary_sequence = data["boundary"].get("sequence_number")
    effective_scope = access_scope or AccessScope.local()
    events: list[SessionEvent] = []
    if reference_predicates:
        conditions = [
            or_(*reference_predicates),
            SessionEvent.workspace_id == checkpoint.workspace_id,
            SessionEvent.provider.in_(session_provider_values(provider)),
            SessionEvent.session_id == session_id,
            source_access_predicate(
                effective_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        ]
        if isinstance(boundary_sequence, int):
            conditions.append(SessionEvent.sequence_number <= boundary_sequence)
        events = list(await session.scalars(
            select(SessionEvent)
            .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
            .where(*conditions)
            .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
        ))

    recovery_prefixes: set[tuple[str, str]] = set()
    if (
        isinstance(stored_verbatim, str)
        and (
            not str(goal_payload.get("request_sha256") or "").strip()
            or _sha256(stored_verbatim)
            == str(goal_payload.get("request_sha256") or "").strip()
        )
    ):
        prefix = _truncated_request_prefix(stored_verbatim)
        if prefix is not None:
            recovery_prefixes.add((prefix, "user_request"))

    for event in events:
        request_verbatim = _checkpoint_request_verbatim(event)
        if request_verbatim:
            request = _validated_session_request(request_verbatim)
            if request is not None:
                return request
        prefix = _truncated_request_prefix(event.content)
        if prefix is not None:
            recovery_prefixes.add((prefix, event.event_type))
        evidence_source_ids.add(event.source_document_id)

    if not recovery_prefixes:
        return None

    # Historical releases capped normalized events, but the immutable source
    # transcript still contains the complete turn. Search only source revisions
    # attached to this checkpoint/evidence and require an exact, long prefix
    # match. Never select the "latest" turn: the source can include later work.
    source_ids = {*evidence_source_ids, checkpoint.source_document_id}
    source_documents = list(await session.scalars(
        select(SourceDocument).where(
            SourceDocument.id.in_(source_ids),
            source_access_predicate(
                effective_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        )
    ))
    recovered = _recover_truncated_request_from_sources(
        source_documents,
        recovery_prefixes=recovery_prefixes,
    )
    if len(recovered) == 1:
        return next(iter(recovered))
    return None


async def _nearest_authoritative_session_request(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    boundary_sequence: Any,
    access_scope: AccessScope | None,
) -> str | None:
    """Recover a missing goal only from this session at/before its boundary."""

    if not isinstance(boundary_sequence, int):
        return None
    normalized_session = (
        normalize_session_key(checkpoint.provider, checkpoint.session_id)
        or (checkpoint.provider, checkpoint.session_id)
    )
    provider, session_id = normalized_session
    effective_scope = access_scope or AccessScope.local()
    events = list(await session.scalars(
        select(SessionEvent)
        .join(
            SourceDocument,
            SessionEvent.source_document_id == SourceDocument.id,
        )
        .where(
            SessionEvent.workspace_id == checkpoint.workspace_id,
            SessionEvent.provider.in_(session_provider_values(provider)),
            SessionEvent.session_id == session_id,
            SessionEvent.sequence_number <= boundary_sequence,
            or_(
                SessionEvent.event_type == "user_request",
                and_(
                    SessionEvent.event_type == "runtime_instruction",
                    SessionEvent.role == "user",
                ),
            ),
            source_access_predicate(
                effective_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        )
        .order_by(
            SessionEvent.sequence_number.desc(),
            SessionEvent.id.desc(),
        )
    ))
    for event in events:
        raw_request = _checkpoint_request_verbatim(event)
        request = _validated_session_request(raw_request)
        if request is not None:
            return request

        # A recognized historical truncation is the nearest authoritative
        # turn, but it does not authorize silently falling back to older work.
        # Recover it from that event's access-checked source revision or fail
        # closed when the prefix is ambiguous/unavailable.
        if _truncated_request_prefix(event.content) is not None:
            source = await session.get(SourceDocument, event.source_document_id)
            if source is None:
                return None
            recognized, recovered = recover_truncated_session_request_from_source(
                source,
                event_content=event.content,
                event_type=event.event_type,
            )
            if recognized:
                return _validated_session_request(recovered)
    return None


async def resolve_session_handoff_supporting_context(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    access_scope: AccessScope | None = None,
) -> list[dict[str, str]]:
    """Materialize referenced conversation context when the goal depends on it.

    A self-contained request needs no historical background. When the request
    explicitly points at a previous prompt or a ChatGPT conversation, carry the
    relevant embedded turns into the checkpoint handoff instead of leaving the
    receiving harness dependent on an app-specific link.
    """

    if not _request_requires_materialized_context(request_verbatim):
        return []

    data = checkpoint_to_dict(checkpoint)
    goals = data["sections"]["goal"]
    projected_goal_key = goals[0].get("item_key") if goals else None
    raw_goal_items = sorted(
        (item for item in checkpoint.items if item.category == "goal"),
        key=lambda item: (item.ordinal, item.id),
    )
    goal_item = next(
        (
            item
            for item in raw_goal_items
            if projected_goal_key and item.item_key == projected_goal_key
        ),
        raw_goal_items[0] if len(raw_goal_items) == 1 else None,
    )
    if goal_item is None:
        return []

    goal_payload = _json_object(goal_item.payload_json)
    stored = _normalize_supporting_context(goal_payload.get("supporting_context"))
    expected_sha256 = str(
        goal_payload.get("supporting_context_sha256") or ""
    ).strip()
    if stored and (
        not expected_sha256
        or _sha256(_canonical_json(stored)) == expected_sha256
    ):
        return stored

    effective_scope = access_scope or AccessScope.local()
    normalized_session = (
        normalize_session_key(checkpoint.provider, checkpoint.session_id)
        or (checkpoint.provider, checkpoint.session_id)
    )
    provider, session_id = normalized_session
    boundary_sequence = data["boundary"].get("sequence_number")
    event_ids = {
        evidence.session_event_id
        for evidence in goal_item.evidence
        if evidence.supports and evidence.session_event_id is not None
    }
    reference_predicates = [
        SessionEvent.id == event_id for event_id in event_ids
    ]
    for evidence in goal_item.evidence:
        if not evidence.supports:
            continue
        locator = _json_object(evidence.locator_json)
        provider_event_id = str(locator.get("provider_event_id") or "").strip()
        if provider_event_id:
            reference_predicates.append(
                SessionEvent.provider_event_id == provider_event_id
            )
    conditions = [
        SessionEvent.workspace_id == checkpoint.workspace_id,
        SessionEvent.provider.in_(session_provider_values(provider)),
        SessionEvent.session_id == session_id,
        source_access_predicate(
            effective_scope,
            workspace_id=checkpoint.workspace_id,
        ),
    ]
    if reference_predicates:
        conditions.append(
            or_(*reference_predicates),
        )
    if isinstance(boundary_sequence, int):
        conditions.append(SessionEvent.sequence_number <= boundary_sequence)
    events = list(await session.scalars(
        select(SessionEvent)
        .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
        .where(*conditions)
        .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
    ))
    candidates: dict[str, list[dict[str, str]]] = {}
    for event in events:
        materialized = _materialized_referenced_context(
            event.content,
            request_verbatim=request_verbatim,
        )
        if materialized:
            candidates[_canonical_json(materialized)] = materialized

    source_ids = {
        checkpoint.source_document_id,
        *(
            evidence.source_document_id
            for evidence in goal_item.evidence
            if evidence.supports and evidence.source_document_id is not None
        ),
    }
    sources = list(await session.scalars(
        select(SourceDocument).where(
            SourceDocument.id.in_(source_ids),
            source_access_predicate(
                effective_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        )
    ))
    for source in sources:
        materialized = _materialized_referenced_context(
            source.content,
            request_verbatim=request_verbatim,
        )
        if materialized:
            candidates[_canonical_json(materialized)] = materialized
    external_dependency = bool(
        _EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
    )
    if not external_dependency:
        goal_sequences = [
            value
            for evidence in goal_item.evidence
            if evidence.supports
            for value in [_json_object(
                evidence.locator_json
            ).get("sequence_number")]
            if isinstance(value, int)
        ]
        goal_sequence = max(goal_sequences) if goal_sequences else None
        if goal_sequence is not None:
            prior_events = list(await session.scalars(
                select(SessionEvent)
                .join(
                    SourceDocument,
                    SessionEvent.source_document_id == SourceDocument.id,
                )
                .where(
                    SessionEvent.workspace_id == checkpoint.workspace_id,
                    SessionEvent.provider.in_(session_provider_values(provider)),
                    SessionEvent.session_id == session_id,
                    SessionEvent.sequence_number < goal_sequence,
                    SessionEvent.event_type.in_((
                        "user_request",
                        "assistant_update",
                    )),
                    source_access_predicate(
                        effective_scope,
                        workspace_id=checkpoint.workspace_id,
                    ),
                )
                .order_by(
                    SessionEvent.sequence_number.desc(),
                    SessionEvent.id.desc(),
                )
                .limit(12)
            ))
            materialized = _materialized_prior_session_context(prior_events)
            if materialized:
                candidates[_canonical_json(materialized)] = materialized
    return next(iter(candidates.values())) if len(candidates) == 1 else []


def _validated_session_request(value: str | None) -> str | None:
    request = extract_user_authored_request(value)
    if request is None or not is_substantive_user_request(request):
        return None
    return request


def _truncated_request_prefix(value: str | None) -> str | None:
    text = str(value or "")
    for suffix in _TRUNCATED_OUTPUT_SUFFIXES:
        if not text.endswith(suffix):
            continue
        prefix = text[: -len(suffix)] if suffix else text
        if len(prefix) >= _MIN_RECOVERY_PREFIX_CHARS:
            return prefix
    return None


def recover_truncated_session_request_from_source(
    source_document: SourceDocument,
    *,
    event_content: str | None,
    event_type: str,
) -> tuple[bool, str | None]:
    """Recover one historical truncated request from its exact source revision.

    The boolean distinguishes ordinary event content from a recognized
    historical truncation. A recognized truncation with no unique exact-prefix
    match must fail closed instead of allowing callers to select older work.
    """

    prefix = _truncated_request_prefix(event_content)
    if prefix is None:
        return False, None
    recovered = _recover_truncated_request_from_sources(
        (source_document,),
        recovery_prefixes={(prefix, event_type)},
    )
    if len(recovered) != 1:
        return True, None
    return True, next(iter(recovered))


def _recover_truncated_request_from_sources(
    source_documents: Iterable[SourceDocument],
    *,
    recovery_prefixes: set[tuple[str, str]],
) -> set[str]:
    recovered: set[str] = set()
    for source_document in source_documents:
        turns = [
            match.group(1).rstrip("\r\n")
            for match in _SESSION_USER_TURN_RE.finditer(
                source_document.content or ""
            )
        ]
        for turn in turns:
            for prefix, event_type in recovery_prefixes:
                if not turn.startswith(prefix):
                    continue
                request = (
                    extract_delegated_user_request(turn)
                    if event_type == "runtime_instruction"
                    else extract_user_authored_request(turn)
                )
                if request is not None and is_substantive_user_request(request):
                    recovered.add(request)
    return recovered


def _request_requires_materialized_context(request_verbatim: str) -> bool:
    return bool(
        _EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
        or _DEICTIC_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
    )


def session_request_requires_materialized_context(request_verbatim: str) -> bool:
    """Return whether a portable handoff must embed referenced session material."""

    return _request_requires_materialized_context(request_verbatim)


def _request_accepts_materialized_reference(request_verbatim: str) -> bool:
    if _NEGATED_REFERENCE_ADOPTION_RE.search(request_verbatim):
        return False
    return bool(_POSITIVE_REFERENCE_ADOPTION_RE.search(request_verbatim))


def _materialized_referenced_context(
    value: str | None,
    *,
    request_verbatim: str | None,
) -> list[dict[str, str]]:
    """Extract the final relevant turns from an embedded ChatGPT export."""

    if not request_verbatim or not _request_requires_materialized_context(
        request_verbatim
    ):
        return []
    text = str(value or "")
    marker = _REFERENCED_CONVERSATION_MARKER_RE.search(text)
    if marker is None:
        return []
    request_marker = _CURRENT_CODEX_REQUEST_MARKER_RE.search(text, marker.end())
    payload_region = text[marker.end():request_marker.start() if request_marker else None]
    parsed: dict[str, Any] | None = None
    decoder = json.JSONDecoder()
    requested_conversation_ids = set(
        _CHATGPT_CONVERSATION_ID_RE.findall(request_verbatim)
    )
    if (
        _EXTERNAL_SESSION_CONTEXT_DEPENDENCY_RE.search(request_verbatim)
        and not requested_conversation_ids
    ):
        # Never bind an unqualified external reference to the first embedded
        # conversation found in a larger source document.
        return []
    for candidate in re.finditer(r"\{", payload_region):
        try:
            value, _ = decoder.raw_decode(payload_region[candidate.start():])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or not isinstance(
            value.get("conversation"), list
        ):
            continue
        embedded_conversation_id = str(value.get("conversationId") or "").strip()
        if (
            requested_conversation_ids
            and embedded_conversation_id not in requested_conversation_ids
        ):
            continue
        if embedded_conversation_id or not requested_conversation_ids:
            parsed = value
            break
    if parsed is None:
        return []

    turns: list[dict[str, str]] = []
    for raw_turn in parsed.get("conversation") or []:
        if not isinstance(raw_turn, dict):
            continue
        role = str(raw_turn.get("role") or "").strip().lower()
        if role not in {"assistant", "user"}:
            continue
        turn_text = _conversation_turn_text(raw_turn.get("content"))
        if not turn_text:
            continue
        turns.append({
            "role": role,
            "text": turn_text,
            "source": "embedded_referenced_conversation",
            "truth_state": "historical_data",
        })
    if not turns:
        return []

    final_assistant_index = next(
        (
            index
            for index in range(len(turns) - 1, -1, -1)
            if turns[index]["role"] == "assistant"
        ),
        len(turns) - 1,
    )
    selected = [turns[final_assistant_index]]
    preceding_user = next(
        (
            turns[index]
            for index in range(final_assistant_index - 1, -1, -1)
            if turns[index]["role"] == "user"
        ),
        None,
    )
    if preceding_user is not None:
        selected.insert(0, preceding_user)
    return selected


def _conversation_turn_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            candidate = item.get("text")
            if not isinstance(candidate, str):
                candidate = item.get("content")
            if isinstance(candidate, str):
                parts.append(candidate)
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    if isinstance(value, dict):
        candidate = value.get("text")
        if not isinstance(candidate, str):
            candidate = value.get("content")
        return str(candidate or "").strip()
    return ""


def _materialized_prior_session_context(
    events: Iterable[SessionEvent],
) -> list[dict[str, str]]:
    ordered = sorted(events, key=lambda item: (item.sequence_number, item.id))
    final_assistant_index = next(
        (
            index
            for index in range(len(ordered) - 1, -1, -1)
            if ordered[index].event_type == "assistant_update"
            and str(ordered[index].content or "").strip()
        ),
        None,
    )
    if final_assistant_index is None:
        return []
    selected = [ordered[final_assistant_index]]
    preceding_user = next(
        (
            ordered[index]
            for index in range(final_assistant_index - 1, -1, -1)
            if ordered[index].event_type == "user_request"
            and extract_user_authored_request(ordered[index].content)
        ),
        None,
    )
    if preceding_user is not None:
        selected.insert(0, preceding_user)
    result: list[dict[str, str]] = []
    for event in selected:
        role = "user" if event.event_type == "user_request" else "assistant"
        text = (
            extract_user_authored_request(event.content)
            if role == "user"
            else str(event.content or "").strip()
        )
        if not text:
            continue
        result.append({
            "role": role,
            "text": text,
            "source": "prior_session_turn",
            "truth_state": "historical_data",
        })
    return result


def _normalize_supporting_context(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            return []
        role = str(raw.get("role") or "").strip().lower()
        text = str(raw.get("text") or "").strip()
        source = str(raw.get("source") or "").strip()
        if role not in {"assistant", "user"} or not text:
            return []
        if source not in {
            "embedded_referenced_conversation",
            "prior_session_turn",
        }:
            return []
        result.append({
            "role": role,
            "text": text,
            "source": source,
            "truth_state": "historical_data",
        })
    return result


def _self_contained_goal(request_verbatim: str) -> str:
    without_links = _CHATGPT_MARKDOWN_LINK_RE.sub(
        lambda match: f"{match.group(1)} (materialized below)",
        request_verbatim,
    )
    return re.sub(
        r"[ \t]+\n",
        "\n",
        _SESSION_IMAGE_TAG_RE.sub(" ", without_links),
    ).strip()


def _session_attachment_dependencies(
    request_verbatim: str,
    *,
    trusted_descriptors: Iterable[TrustedRequestImageDescriptor] = (),
    allow_local_files: bool = False,
) -> list[dict[str, Any]]:
    """Describe exact-turn images without treating request markup as authority."""

    descriptor_values = tuple(trusted_descriptors)
    descriptors_by_path = {
        descriptor.path: descriptor
        for descriptor in descriptor_values
        if descriptor.path
    }
    declarations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    request_tag_paths: set[str] = set()
    for match in _SESSION_IMAGE_TAG_RE.finditer(str(request_verbatim or "")):
        attributes_text = (
            match.group("attributes")
            if match.group("attributes") is not None
            else match.group("self_closing_attributes")
            or ""
        )
        attributes: dict[str, str] = {}
        for attribute in _SESSION_IMAGE_ATTRIBUTE_RE.finditer(attributes_text):
            key = attribute.group(1).casefold()
            value = next(
                (
                    group
                    for group in attribute.groups()[1:]
                    if group is not None
                ),
                "",
            ).strip()
            attributes[key] = value
        for attribute in _SESSION_IMAGE_BRACKET_ATTRIBUTE_RE.finditer(
            attributes_text
        ):
            attributes[attribute.group(1).casefold()] = (
                attribute.group(2).strip()
            )
        path = str(
            attributes.get("path")
            or attributes.get("src")
            or ""
        ).strip()
        name = str(
            attributes.get("name")
            or attributes.get("alt")
            or f"Image {len(declarations) + 1}"
        ).strip()
        identity = (path, name)
        if identity in seen:
            continue
        seen.add(identity)
        if path:
            request_tag_paths.add(path)
        declarations.append({
            "name": name,
            "path": path or None,
            "source": "user_request_attachment_markup",
            "declaration_sha256": _sha256(match.group(0)),
        })

    declared_paths = {
        str(item.get("path") or "")
        for item in declarations
        if item.get("path")
    }
    for descriptor in descriptor_values:
        if not descriptor.path or descriptor.path in declared_paths:
            continue
        declarations.append({
            "name": f"[Image #{len(declarations) + 1}]",
            "path": descriptor.path,
            "source": "structured_provider_attachment",
            "declaration_sha256": None,
        })
        declared_paths.add(descriptor.path)

    resolver_request = str(request_verbatim or "")
    synthetic_tags = [
        tag
        for path in descriptors_by_path
        if path not in request_tag_paths
        if (tag := _trusted_image_resolver_tag(path)) is not None
    ]
    if synthetic_tags:
        resolver_request = "\n".join((resolver_request, *synthetic_tags))
    resolved = resolve_trusted_request_image_artifacts(
        resolver_request,
        trusted_descriptors=descriptor_values,
        allow_local_files=allow_local_files,
    )
    artifacts_by_path: dict[str, ArtifactReference] = {}
    for artifact in resolved:
        artifacts_by_path[artifact.path] = artifact
        if artifact.source_path:
            artifacts_by_path[artifact.source_path] = artifact

    dependencies: list[dict[str, Any]] = []
    for declaration in declarations:
        path = str(declaration.get("path") or "")
        artifact = artifacts_by_path.get(path)
        trusted = path in descriptors_by_path
        available = bool(artifact and artifact.available and artifact.sha256)
        resolution = (
            "hash_verified_exact_provider_attachment"
            if available
            else "trusted_provider_attachment_unavailable"
            if trusted
            else "trusted_attachment_descriptor_required"
        )
        resolved_path = (
            artifact.path
            if available and artifact is not None
            else path or None
        )
        dependencies.append({
            "id": f"A{len(dependencies) + 1}",
            "kind": "image",
            "name": declaration["name"],
            "path": resolved_path,
            "source_path": (
                path
                if resolved_path is not None and resolved_path != path
                else None
            ),
            "required": True,
            "available": available,
            "sha256": artifact.sha256 if artifact else None,
            "mime_type": artifact.mime_type if artifact else None,
            "source": (
                "exact_provider_event"
                if trusted
                else declaration["source"]
            ),
            "resolution": resolution,
            "unavailable_reason": (
                artifact.visual_summary
                if artifact is not None and not available
                else None
            ),
            "declaration_sha256": declaration["declaration_sha256"],
            "requirement_ids": [],
        })
    return dependencies


def _session_attachment_requirements(
    attachments: list[dict[str, Any]],
    *,
    start_index: int,
) -> list[dict[str, Any]]:
    """Give every required artifact a distinct requirement/proof lineage."""

    result: list[dict[str, Any]] = []
    for offset, attachment in enumerate(attachments, start=1):
        requirement_id = f"R{start_index + offset}"
        attachment["requirement_ids"] = [requirement_id]
        result.append({
            "id": requirement_id,
            "text": (
                f"Use required attachment {attachment['id']} "
                f"({_single_line(str(attachment['name']), 200)}) as a task "
                "input; do not claim attachment-dependent work complete unless "
                "this exact artifact was inspected."
            ),
            "source": "attachment_dependency",
            "authority": "derived_from_user_attachment",
            "source_heading": None,
            "source_attachment_id": attachment["id"],
            "explicit_acceptance": False,
        })
    return result


def _trusted_image_resolver_tag(path: str) -> str | None:
    """Create internal-only resolver markup for structured provider images."""

    if "<" in path or ">" in path:
        return None
    if '"' not in path:
        return f'<image path="{path}"></image>'
    if "'" not in path:
        return f"<image path='{path}'></image>"
    return None


async def resolve_session_handoff_attachment_descriptors(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    access_scope: AccessScope | None = None,
) -> tuple[TrustedRequestImageDescriptor, ...]:
    """Resolve images only from the exact authoritative local provider turn.

    Request markup is never filesystem authority. New imports retain structured
    provider attachment metadata on the normalized user event. For legacy Codex
    imports, recover the same metadata from a bounded window of the immutable
    raw rollout only when both provider records match this exact request.
    """

    if access_scope is None or access_scope.principal_id != "local":
        return ()
    checkpoint_bound, checkpoint_descriptors = (
        _checkpoint_bound_image_descriptors(
            checkpoint,
            request_verbatim=request_verbatim,
        )
    )
    if checkpoint_bound:
        return checkpoint_descriptors
    effective_scope = access_scope
    data = checkpoint_to_dict(checkpoint)
    boundary_sequence = data["boundary"].get("sequence_number")
    if not isinstance(boundary_sequence, int):
        return ()
    normalized_session = (
        normalize_session_key(checkpoint.provider, checkpoint.session_id)
        or (checkpoint.provider, checkpoint.session_id)
    )
    provider, session_id = normalized_session
    expected_request = " ".join(str(request_verbatim or "").split())
    if not expected_request:
        return ()
    events = list(await session.scalars(
        select(SessionEvent)
        .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
        .where(
            SessionEvent.workspace_id == checkpoint.workspace_id,
            SessionEvent.provider.in_(session_provider_values(provider)),
            SessionEvent.session_id == session_id,
            SessionEvent.sequence_number <= boundary_sequence,
            or_(
                SessionEvent.event_type == "user_request",
                and_(
                    SessionEvent.event_type == "runtime_instruction",
                    SessionEvent.role == "user",
                ),
            ),
            source_access_predicate(
                effective_scope,
                workspace_id=checkpoint.workspace_id,
            ),
        )
        .order_by(SessionEvent.sequence_number.desc(), SessionEvent.id.desc())
    ))
    for event in events:
        candidate = _checkpoint_request_verbatim(event)
        candidate_request = _validated_session_request(candidate)
        exact_match = (
            candidate_request is not None
            and " ".join(candidate_request.split()) == expected_request
        )
        prefix = _truncated_request_prefix(event.content)
        prefix_match = bool(
            prefix
            and str(request_verbatim).startswith(prefix)
        )
        if not exact_match and not prefix_match:
            continue

        descriptors = trusted_request_image_descriptors_from_payload(
            event_payload(event)
        )
        if descriptors and all(
            descriptor.resolved_path
            or not descriptor.binding_valid
            for descriptor in descriptors
        ):
            return tuple(
                materialize_trusted_request_image_descriptor(
                    descriptor,
                    data_dir=settings.data_dir,
                )
                for descriptor in descriptors
            )
        if provider != "codex":
            return tuple(
                materialize_trusted_request_image_descriptor(
                    descriptor,
                    data_dir=settings.data_dir,
                )
                for descriptor in descriptors
            )

        source = await session.get(SourceDocument, event.source_document_id)
        metadata = _json_object(source.metadata_json if source else None)
        source_path = str(metadata.get("source_path") or "").strip()
        if not source_path:
            return ()
        configured_root = (
            Path(settings.codex_home).expanduser()
            if settings.codex_home
            else Path.home() / ".codex"
        )
        recovered = recover_codex_request_image_descriptors(
            source_path=source_path,
            source_sequence_number=event.sequence_number,
            request_verbatim=request_verbatim,
            codex_sessions_root=configured_root / "sessions",
            artifact_data_dir=settings.data_dir,
        )
        if recovered and (
            not descriptors
            or _same_descriptor_binding(descriptors, recovered)
        ):
            return recovered
        return tuple(
            materialize_trusted_request_image_descriptor(
                descriptor,
                data_dir=settings.data_dir,
            )
            for descriptor in descriptors
        )
    return ()


def _checkpoint_bound_image_descriptors(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
) -> tuple[bool, tuple[TrustedRequestImageDescriptor, ...]]:
    """Read only integrity-checked descriptors frozen into current checkpoints."""

    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        return False, ()
    raw_payload = str(checkpoint.payload_json or "")
    if (
        not raw_payload
        or not checkpoint.payload_sha256
        or _sha256(raw_payload) != checkpoint.payload_sha256
    ):
        return True, ()
    payload = _json_object(raw_payload)
    sections = payload.get("sections")
    goals = (
        sections.get("goal")
        if isinstance(sections, dict)
        else None
    )
    if not isinstance(goals, list) or len(goals) != 1:
        return True, ()
    goal_payload = goals[0].get("payload")
    if not isinstance(goal_payload, dict):
        return True, ()
    if (
        str(goal_payload.get("request_sha256") or "")
        != _sha256(request_verbatim)
    ):
        return True, ()
    raw_descriptors = goal_payload.get("trusted_image_descriptors")
    expected_digest = str(
        goal_payload.get("trusted_image_descriptors_sha256") or ""
    )
    if (
        not isinstance(raw_descriptors, list)
        or not expected_digest
        or _sha256(_canonical_json(raw_descriptors)) != expected_digest
    ):
        return True, ()
    descriptors: list[TrustedRequestImageDescriptor] = []
    for raw in raw_descriptors:
        if not isinstance(raw, dict):
            return True, ()
        path = str(raw.get("path") or "").strip()
        if not path:
            return True, ()
        ordinal = raw.get("ordinal")
        size_bytes = raw.get("size_bytes")
        descriptors.append(TrustedRequestImageDescriptor(
            path=path,
            sha256=str(raw.get("sha256") or "").strip() or None,
            mime_type=str(raw.get("mime_type") or "").strip() or None,
            resolved_path=(
                str(
                    raw.get("resolved_path")
                    or raw.get("stored_path")
                    or ""
                ).strip()
                or None
            ),
            ordinal=(
                ordinal
                if isinstance(ordinal, int)
                and not isinstance(ordinal, bool)
                else None
            ),
            size_bytes=(
                size_bytes
                if isinstance(size_bytes, int)
                and not isinstance(size_bytes, bool)
                else None
            ),
            binding_valid=raw.get("binding_valid") is not False,
            binding_error=(
                str(raw.get("binding_error") or "").strip() or None
            ),
        ))
    return True, tuple(descriptors)


def _derive_session_requirements(
    request_verbatim: str,
    *,
    supporting_context: Iterable[dict[str, str]] = (),
) -> list[dict[str, Any]]:
    candidates = _requirement_candidates(
        _self_contained_goal(request_verbatim),
        source="user_request",
        authority="user_authored",
    )
    if (
        _request_accepts_materialized_reference(request_verbatim)
        and _request_requires_materialized_context(request_verbatim)
    ):
        for item in supporting_context:
            if str(item.get("role") or "") != "assistant":
                continue
            candidates.extend(_requirement_candidates(
                str(item.get("text") or ""),
                source="materialized_reference",
                authority="accepted_by_user_reference",
            ))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = re.sub(r"\s+", " ", str(candidate["text"])).strip()
        key = re.sub(r"\W+", " ", text.casefold()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        explicit_acceptance = bool(candidate.get("explicit_acceptance"))
        execution_guidance = (
            not explicit_acceptance
            and is_non_verifiable_execution_guidance(text)
        )
        deduped.append({
            "id": f"R{len(deduped) + 1}",
            "text": text,
            "source": candidate["source"],
            "authority": candidate["authority"],
            "source_heading": candidate.get("source_heading"),
            "explicit_acceptance": explicit_acceptance,
            "kind": (
                "execution_guidance"
                if execution_guidance
                else "requirement"
            ),
            "completion_relevant": not execution_guidance,
        })
    if deduped:
        return deduped
    fallback_text = re.sub(
        r"\s+",
        " ",
        _self_contained_goal(request_verbatim),
    ).strip()
    execution_guidance = is_non_verifiable_execution_guidance(fallback_text)
    return [{
        "id": "R1",
        "text": fallback_text,
        "source": "user_request",
        "authority": "user_authored",
        "source_heading": None,
        "explicit_acceptance": False,
        "kind": (
            "execution_guidance"
            if execution_guidance
            else "requirement"
        ),
        "completion_relevant": not execution_guidance,
    }]


def derive_session_handoff_requirements(
    request_verbatim: str,
    *,
    supporting_context: Iterable[dict[str, str]] = (),
) -> list[dict[str, Any]]:
    """Expose the authority-aware requirement projection to both context products."""

    return _derive_session_requirements(
        request_verbatim,
        supporting_context=supporting_context,
    )


def _requirement_candidates(
    value: str,
    *,
    source: str,
    authority: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    heading: str | None = None
    ignore_section = False
    fence_marker: str | None = None
    prose_lines: list[str] = []
    quoted_acceptance_list = False
    for raw_line in value.splitlines():
        stripped = raw_line.strip()
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            quoted_acceptance_list = False
            continue
        if fence_marker is not None:
            continue
        quoted_item = stripped.startswith(">")
        if quoted_item:
            if authority != "accepted_by_user_reference":
                continue
            raw_line = re.sub(r"^\s*>\s?", "", raw_line, count=1)
            stripped = raw_line.strip()
        raw_line = _strip_historical_quoted_report(raw_line)
        stripped = raw_line.strip()
        if not stripped:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading_match:
            heading = heading_match.group(1).strip()
            ignore_section = bool(
                _NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE.search(heading)
            )
            quoted_acceptance_list = False
            continue
        if ignore_section:
            continue
        if _HISTORICAL_QUOTED_SPEECH_RE.search(stripped):
            continue
        bullet_match = _REQUIREMENT_BULLET_RE.match(raw_line)
        if quoted_item and not quoted_acceptance_list:
            continue
        if bullet_match is None:
            if quoted_item and quoted_acceptance_list and len(stripped) >= 4:
                candidates.append({
                    "text": stripped,
                    "source": source,
                    "authority": authority,
                    "source_heading": heading,
                    "explicit_acceptance": True,
                })
                continue
            if stripped.endswith(":") and re.search(
                r"\b(?:contain|include|carry|have|consist of)\b",
                stripped,
                re.IGNORECASE,
            ):
                lead_in = re.search(
                    r"\b(?:it|this|the\s+(?:handoff|context))\s+"
                    r"(?:should|must|will)\s+"
                    r"(?:contain|include|carry|have|consist of)\b[^:]*:$",
                    stripped,
                    re.IGNORECASE,
                )
                if lead_in is not None:
                    prefix = stripped[:lead_in.start()].strip()
                    if prefix:
                        prose_lines.append(prefix)
                quoted_acceptance_list = True
                continue
            if stripped.endswith(":"):
                quoted_acceptance_list = False
                continue
            if stripped and not stripped.endswith(":"):
                prose_lines.append(re.sub(r"`[^`\n]*`", " ", stripped))
                quoted_acceptance_list = False
            continue
        statement = bullet_match.group(1).strip()
        if len(statement) < 4:
            continue
        candidates.append({
            "text": statement,
            "source": source,
            "authority": authority,
            "source_heading": heading,
            "explicit_acceptance": bool(
                heading
                and re.search(
                    r"\b(?:acceptance|definition of done|requirements?|must have)\b",
                    heading,
                    re.IGNORECASE,
                )
            ),
        })

    # Keep pure working-style directives as their own source-backed clauses.
    # Joining them to a preceding line would turn urgency or "quality over
    # quantity" into part of that outcome's proof contract.
    statements: list[str] = []
    prose_group: list[str] = []
    for prose_line in prose_lines:
        if is_non_verifiable_execution_guidance(prose_line):
            if prose_group:
                statements.extend(_sentences("\n".join(prose_group)))
                prose_group = []
            statements.extend(_sentences(prose_line))
        else:
            prose_group.append(prose_line)
    if prose_group:
        statements.extend(_sentences("\n".join(prose_group)))
    actionable = [
        statement
        for statement in statements
        if (
            _REQUIREMENT_ACTION_RE.search(statement)
            or statement.rstrip().endswith("?")
        )
    ]
    prose_candidates = [
        {
            "text": statement,
            "source": source,
            "authority": authority,
            "source_heading": None,
            "explicit_acceptance": False,
        }
        for statement in actionable
    ]
    if prose_candidates:
        return [*prose_candidates, *candidates]
    if candidates:
        return candidates
    if statements:
        return [{
            "text": statements[0],
            "source": source,
            "authority": authority,
            "source_heading": None,
            "explicit_acceptance": False,
        }]
    return []


def _strip_historical_quoted_report(value: str) -> str:
    cleaned = _HISTORICAL_QUOTED_REPORT_RE.sub(" ", value)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    # Preserve Markdown bullets and acceptance-list punctuation. This helper
    # removes a provenance-marked quoted report, not the line's structure.
    return cleaned.strip()


def _infer_session_task_mode(request_verbatim: str) -> str:
    directive = _session_task_directive_text(request_verbatim)
    no_edit = bool(_NO_EDIT_TASK_RE.search(directive))
    if _REVIEW_TASK_RE.search(directive) and (
        no_edit or not _CHANGE_TASK_RE.search(directive)
    ):
        return "review"
    if _DIAGNOSE_TASK_RE.search(directive) and (
        no_edit or not _CHANGE_TASK_RE.search(directive)
    ):
        return "diagnose"
    if _REPORT_TASK_RE.search(directive) and (
        no_edit or not _CHANGE_TASK_RE.search(directive)
    ):
        return "report"
    if _CHANGE_TASK_RE.search(directive) and not no_edit:
        return "change"
    return "report"


def _session_task_directive_text(request_verbatim: str) -> str:
    """Return only user directive text that may grant task authority."""

    value = str(request_verbatim or "")
    marker = _CURRENT_CODEX_REQUEST_MARKER_RE.search(value)
    if marker is not None:
        value = value[marker.end():]
    lines: list[str] = []
    fence_marker: str | None = None
    ignore_section = False
    for raw_line in value.splitlines():
        stripped = raw_line.strip()
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            marker_char = fence_match.group(1)[0]
            if fence_marker is None:
                fence_marker = marker_char
            elif marker_char == fence_marker:
                fence_marker = None
            continue
        if fence_marker is not None or stripped.startswith(">"):
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading_match:
            heading = heading_match.group(1).strip()
            ignore_section = bool(
                _NON_AUTHORITATIVE_REQUIREMENT_HEADING_RE.search(heading)
            )
            continue
        if ignore_section:
            continue
        without_inline_code = _strip_historical_quoted_report(
            re.sub(r"`[^`\n]*`", " ", raw_line)
        )
        # Quoted transcript snippets describe text to inspect; they do not
        # independently grant write authority.
        without_quoted_history = re.sub(
            r'"[^"\n]{1,500}"|“[^”\n]{1,500}”|'
            r"(?<!\w)'[^'\n]{1,500}'(?!\w)|‘[^’\n]{1,500}’",
            " ",
            without_inline_code,
        )
        if without_quoted_history.strip():
            lines.append(without_quoted_history)
    return "\n".join(lines)


def build_session_handoff_contract(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str,
    supporting_context: Iterable[dict[str, str]] = (),
    trusted_attachment_descriptors: Iterable[
        TrustedRequestImageDescriptor
    ] = (),
    allow_local_artifacts: bool = False,
    checkpoint_data: dict[str, Any] | None = None,
    repository_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the typed, reconciled contract used by the copyable rendering."""

    normalized_supporting = _normalize_supporting_context(list(supporting_context))
    dependency_required = _request_requires_materialized_context(request_verbatim)
    if dependency_required and not normalized_supporting:
        raise ValueError(
            "The session goal depends on referenced conversation context that "
            "could not be materialized into a self-contained handoff."
        )

    data = checkpoint_data or checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    sections = _handoff_presentation_sections(data["sections"])
    derived_requirements = _derive_session_requirements(
        request_verbatim,
        supporting_context=normalized_supporting,
    )
    requirements: list[dict[str, Any]] = []
    execution_guidance: list[dict[str, Any]] = []
    for item in derived_requirements:
        if item.get("completion_relevant") is False:
            execution_guidance.append({
                **item,
                "id": f"C{len(execution_guidance) + 1}",
            })
            continue
        requirements.append({
            **item,
            "id": f"R{len(requirements) + 1}",
        })
    attachment_dependencies = _session_attachment_dependencies(
        request_verbatim,
        trusted_descriptors=trusted_attachment_descriptors,
        allow_local_files=allow_local_artifacts,
    )
    requirements.extend(_session_attachment_requirements(
        attachment_dependencies,
        start_index=len(requirements),
    ))
    task_mode = _infer_session_task_mode(request_verbatim)
    verification = _session_handoff_verification(
        sections["verification"],
        requirements=requirements,
        progress=sections["progress"],
    )
    reconciliation = _reconcile_session_handoff(
        requirements=requirements,
        progress=sections["progress"],
        next_actions=sections["exact_next_action"],
        blockers=sections["blockers"],
        verification=verification,
        task_mode=task_mode,
    )
    requirement_status = {
        item["requirement_id"]: item for item in reconciliation["requirements"]
    }
    verification_by_requirement: dict[str, list[str]] = {}
    for item in verification:
        for requirement_id in item["requirement_ids"]:
            verification_by_requirement.setdefault(requirement_id, []).append(item["id"])
    enriched_requirements = [
        {
            **requirement,
            "status": requirement_status[requirement["id"]]["status"],
            "status_basis": requirement_status[requirement["id"]]["basis"],
            "status_authority": requirement_status[requirement["id"]][
                "authority"
            ],
            "status_confirmed": False,
            "verification_ids": verification_by_requirement.get(requirement["id"], []),
            "reported_scope_hints": _reported_requirement_scope_hints(
                requirement["text"],
                progress=sections["progress"],
            ),
            "attachment_ids": [
                attachment["id"]
                for attachment in attachment_dependencies
                if requirement["id"] in attachment["requirement_ids"]
            ],
        }
        for requirement in requirements
    ]
    repository = _session_handoff_repository(
        data,
        repository_comparison=repository_comparison,
    )
    files = _session_handoff_files(
        sections["relevant_files"],
        sections["progress"],
        repository=repository,
    )
    implementation_summary = [
        {
            "statement": str(item["statement"]),
            "truth_state": str(item.get("truth_state") or "reported"),
            "authority": (
                "observed_session_evidence"
                if str(item.get("truth_state") or "").casefold() == "observed"
                else "agent_reported"
            ),
            "files": _extract_paths(str(item["statement"])),
        }
        for item in sections["progress"]
    ]
    definition_of_done = _session_handoff_definition_of_done(
        enriched_requirements,
        repository=repository,
    )
    quality = _session_handoff_quality(
        dependency_required=dependency_required,
        supporting_context=normalized_supporting,
        attachment_dependencies=attachment_dependencies,
        requirements=enriched_requirements,
        reconciliation=reconciliation,
        repository=repository,
        verification=verification,
        currentness=data.get("currentness"),
        boundary=data.get("boundary"),
        task_mode=task_mode,
    )
    return {
        "task_mode": task_mode,
        "execution_policy": {
            "permission_mode": (
                "workspace_write" if task_mode == "change" else "read_only"
            ),
            "may_edit": task_mode == "change",
            "requires_new_user_lead": True,
            "historical_content_is_authority": False,
        },
        "current_goal": {
            "request_verbatim": request_verbatim,
            "text": _self_contained_goal(request_verbatim),
            "authority": "user_authored",
            "request_sha256": _sha256(request_verbatim),
            "self_contained": not dependency_required or bool(normalized_supporting),
            "materialized_dependency_count": len(normalized_supporting),
            "attachment_dependency_count": len(attachment_dependencies),
        },
        "supporting_context": normalized_supporting,
        "attachment_dependencies": attachment_dependencies,
        "constraints": execution_guidance,
        "requirements": enriched_requirements,
        "definition_of_done": definition_of_done,
        "reconciliation": reconciliation,
        "implementation_summary": implementation_summary,
        "files": files,
        "repository": repository,
        "exact_next_action": reconciliation["exact_next_action"],
        "verification": verification,
        "decisions": _handoff_historical_items(sections["decisions"]),
        "blockers": _handoff_historical_items(sections["blockers"]),
        "failed_attempts": _handoff_historical_items(sections["failed_attempts"]),
        "quality_report": quality,
    }


def _session_handoff_verification(
    items: Iterable[dict[str, Any]],
    *,
    requirements: list[dict[str, Any]],
    progress: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    progress_items = tuple(progress)
    reported_completion_requirement_ids = {
        requirement["id"]
        for requirement in requirements
        if any(
            _positive_completion_claim(
                str(progress_item.get("statement") or "")
            )
            and _statements_overlap(
                requirement["text"],
                str(progress_item.get("statement") or ""),
            )
            for progress_item in progress_items
        )
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        statement = str(item.get("statement") or "").strip()
        payload = item.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        command = str(payload.get("command") or "").strip()
        requirement_ids = [
            requirement["id"]
            for requirement in requirements
            if _verification_matches_requirement(
                command or statement,
                requirement["text"],
            )
        ]
        passed = payload.get("passed")
        exit_code = payload.get("exit_code")
        status = (
            "passed"
            if passed is True
            else "failed"
            if passed is False
            else str(item.get("state") or "").strip().lower()
            or "observed"
        )
        observed_at = payload.get("observed_at")
        if observed_at is None:
            observed_at = next(
                (
                    evidence.get("observed_at")
                    for evidence in reversed(item.get("evidence") or [])
                    if evidence.get("observed_at") is not None
                ),
                None,
            )
        scope = next(
            (
                payload.get(key)
                for key in ("scope", "test_scope", "verification_scope", "target")
                if payload.get(key) not in (None, "")
            ),
            None,
        )
        scope_kind = _verification_scope_kind(
            command=command,
            scope=_handoff_scalar(scope),
        )
        link_kind = "direct" if requirement_ids else "unmapped"
        if (
            not requirement_ids
            and len(reported_completion_requirement_ids) == 1
            and scope_kind in {"focused", "regression_safety"}
        ):
            # A component test or broad regression check can support the one
            # reported implementation scope without becoming direct proof of
            # the original user wording. Keep that distinction explicit.
            requirement_ids = sorted(reported_completion_requirement_ids)
            link_kind = (
                "reported_scope_support"
                if scope_kind == "focused"
                else "regression_safety"
            )
        result.append({
            "id": f"V{index}",
            "statement": statement,
            "command": command or None,
            "cwd": payload.get("cwd"),
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "passed": passed if isinstance(passed, bool) else None,
            "status": status,
            "observed_at": _handoff_scalar(observed_at),
            "scope": _handoff_scalar(scope),
            "truth_state": str(item.get("truth_state") or "observed"),
            "requirement_ids": requirement_ids,
            "link_kind": link_kind,
            "scope_kind": scope_kind,
        })
    return result


def _verification_scope_kind(
    *,
    command: str,
    scope: str | None,
) -> str:
    """Classify check breadth without pretending it proves a requirement."""

    if scope:
        return "focused"
    normalized = re.sub(r"\s+", " ", command.casefold()).strip()
    if not normalized:
        return "observed"
    if (
        "::" in normalized
        or re.search(
            r"(?:^|\s)(?:[^ ]+/)?(?:test_[^ ]+|[^ ]+\.test\.[^ ]+|"
            r"[^ ]+\.spec\.[^ ]+)(?:$|\s)",
            normalized,
        )
        or re.search(r"\s--\s+\S+", normalized)
    ):
        return "focused"
    if re.fullmatch(
        r"(?:(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:build|lint|test)|"
        r"(?:python3?\s+-m\s+)?pytest(?:\s+-[a-z]+)*)",
        normalized,
    ):
        return "regression_safety"
    return "focused"


def _handoff_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return _canonical_json(value)
    rendered = str(value).strip()
    return rendered or None


def _verification_matches_requirement(
    verification_text: str,
    requirement_text: str,
) -> bool:
    verification_tokens = _status_tokens(verification_text)
    requirement_tokens = _status_tokens(requirement_text)
    shared = verification_tokens & requirement_tokens
    if len(shared) >= 2:
        return True
    requirement_paths = set(_extract_paths(requirement_text))
    verification_paths = set(_extract_paths(verification_text))
    if requirement_paths & verification_paths:
        return True
    return bool(
        shared
        and re.search(r"\b(?:test|tests|verify|verification|lint|build)\b", requirement_text, re.I)
    )


def _reconcile_session_handoff(
    *,
    requirements: list[dict[str, Any]],
    progress: Iterable[dict[str, Any]],
    next_actions: Iterable[dict[str, Any]],
    blockers: Iterable[dict[str, Any]],
    verification: list[dict[str, Any]],
    task_mode: str,
) -> dict[str, Any]:
    progress_items = list(progress)
    all_next_items = list(next_actions)
    next_items = [
        item
        for item in all_next_items
        if not _recovered_next_action_superseded_by_progress(
            item,
            progress_items=progress_items,
        )
    ]
    status_next_items = [
        item
        for item in next_items
        if (item.get("payload") or {}).get(
            "derived_from_reconciliation"
        ) is not True
    ]
    superseded_next_items = [
        item for item in all_next_items if item not in next_items
    ]
    blocker_items = [
        item
        for item in blockers
        if str(item.get("state") or "active").casefold()
        not in _INACTIVE_BLOCKER_STATES
    ]
    generic_completion = any(
        _GENERIC_COMPLETION_CLAIM_RE.fullmatch(
            str(item.get("statement") or "").strip()
        )
        and _positive_completion_claim(str(item.get("statement") or ""))
        for item in progress_items
    )
    generic_next_items = [
        item
        for item in status_next_items
        if _GENERIC_CONTINUATION_RE.match(
            str(item.get("statement") or "").strip()
        )
    ]
    generic_continuation = bool(generic_next_items)
    statuses: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    if generic_completion and generic_continuation:
        conflicts.append({
            "code": "generic_completion_continuation_conflict",
            "requirement_id": None,
            "done_claims": [
                str(item.get("statement") or "")
                for item in progress_items
                if _GENERIC_COMPLETION_CLAIM_RE.fullmatch(
                    str(item.get("statement") or "").strip()
                )
            ],
            "remaining_claims": [
                str(item.get("statement") or "")
                for item in next_items
                if _GENERIC_CONTINUATION_RE.match(
                    str(item.get("statement") or "").strip()
                )
            ],
            "failed_verification_ids": [],
        })
    for requirement in requirements:
        done_claims = [
            item for item in progress_items
            if (
                _positive_completion_claim(str(item.get("statement") or ""))
                and _statements_overlap(
                    str(item.get("statement") or ""),
                    requirement["text"],
                )
            )
        ]
        scoped_remaining_claims = [
            item for item in status_next_items
            if (
                item not in generic_next_items
                and _statements_overlap(
                str(item.get("statement") or ""),
                requirement["text"],
                )
            )
        ]
        failed_verifiers = [
            item
            for item in verification
            if requirement["id"] in item["requirement_ids"]
            and item["passed"] is False
        ]
        if generic_completion and generic_continuation and not done_claims:
            status = "unknown"
            authority = "conflicting_agent_report"
            basis = (
                "A generic completion claim conflicts with a generic continuation "
                "instruction; neither is scoped enough to classify this requirement."
            )
        elif done_claims and (scoped_remaining_claims or failed_verifiers):
            status = "contradicted"
            authority = "mixed_reported_and_observed"
            basis = (
                "Agent-reported completion conflicts with a continuation action "
                "or failed observed check."
            )
            conflicts.append({
                "code": "completion_continuation_conflict",
                "requirement_id": requirement["id"],
                "done_claims": [
                    str(item.get("statement") or "") for item in done_claims
                ],
                "remaining_claims": [
                    str(item.get("statement") or "")
                    for item in scoped_remaining_claims
                ],
                "failed_verification_ids": [
                    item["id"] for item in failed_verifiers
                ],
            })
        elif failed_verifiers or scoped_remaining_claims:
            status = "remaining"
            authority = (
                "observed_verification"
                if failed_verifiers
                else "agent_reported"
            )
            basis = (
                "A scoped continuation action or failed observed check remains."
            )
        elif done_claims:
            status = "reported_done"
            authority = "agent_reported"
            basis = (
                "Reported complete by the prior agent; repository confirmation "
                "is still required."
            )
        elif generic_continuation:
            status = "remaining"
            authority = "agent_reported"
            basis = (
                "A generic continuation fallback applies because no scoped "
                "completion evidence was captured for this requirement."
            )
        else:
            status = "unknown"
            authority = "none"
            basis = "No captured evidence proves completion or remaining work."
        statuses.append({
            "requirement_id": requirement["id"],
            "status": status,
            "basis": basis,
            "authority": authority,
        })

    counts = {
        state: sum(item["status"] == state for item in statuses)
        for state in (
            "done",
            "reported_done",
            "remaining",
            "unknown",
            "contradicted",
        )
    }
    if conflicts:
        state = "needs_reconciliation"
        affected_requirement_ids = [
            item["requirement_id"]
            for item in statuses
            if item["status"] == "contradicted"
        ] or [item["requirement_id"] for item in statuses]
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Inspect the current repository and reconcile the conflicting "
                    "completion and continuation claims against "
                    f"{', '.join(affected_requirement_ids)}. "
                    "Then implement and verify only the requirements still unmet."
                ),
                read_only_text=(
                    "Inspect the current repository and reconcile the conflicting "
                    "completion and continuation claims against "
                    f"{', '.join(affected_requirement_ids)}. Complete the requested "
                    f"{task_mode} without editing files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    elif blocker_items:
        state = "blocked_reported"
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Confirm whether the reported blocker still exists in the current "
                    "runtime; resolve it if possible, then continue the unmet requirements."
                ),
                read_only_text=(
                    "Confirm whether the reported blocker still affects the requested "
                    f"{task_mode}; document the evidence without editing files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    elif counts["remaining"]:
        state = "in_progress"
        reported_done_ids = [
            item["requirement_id"]
            for item in statuses
            if item["status"] == "reported_done"
        ]
        remaining_ids = [
            item["requirement_id"]
            for item in statuses
            if item["status"] == "remaining"
        ]
        unknown_ids = [
            item["requirement_id"]
            for item in statuses
            if item["status"] == "unknown"
        ]
        reported_done_text = ", ".join(reported_done_ids)
        remaining_text = ", ".join(remaining_ids)
        unknown_suffix = (
            f" Classify {', '.join(unknown_ids)} from current evidence as well."
            if unknown_ids
            else ""
        )
        if reported_done_ids:
            change_text = (
                f"Verify {reported_done_text} against the current repository, "
                f"then complete and verify {remaining_text}."
                f"{unknown_suffix}"
            )
            read_only_text = (
                f"Validate {reported_done_text} against the current repository, "
                f"then complete the requested {task_mode} for {remaining_text} "
                f"without editing files.{unknown_suffix}"
            )
        else:
            change_text = (
                f"Complete and verify {remaining_text}.{unknown_suffix}"
            )
            read_only_text = (
                f"Complete the requested {task_mode} for {remaining_text} "
                f"without editing files.{unknown_suffix}"
            )
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=change_text,
                read_only_text=read_only_text,
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    elif counts["unknown"]:
        state = "unknown"
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Inspect the current repository, verify every reported-done "
                    "requirement, classify every unknown requirement as done or "
                    "remaining using observed evidence, then complete and verify "
                    "the unmet work."
                ),
                read_only_text=(
                    "Inspect the current repository, validate every reported-done "
                    "conclusion, and classify every unknown requirement using "
                    f"observed evidence. Complete the requested {task_mode} without "
                    "editing files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    else:
        state = "complete_reported"
        next_action = {
            "text": _mode_safe_next_action(
                task_mode,
                change_text=(
                    "Verify every reported-complete requirement against the current "
                    "repository and linked checks before declaring the task complete."
                ),
                read_only_text=(
                    "Validate every reported conclusion against the current repository "
                    f"before completing the requested {task_mode}; do not edit files."
                ),
            ),
            "source": "reconciliation_policy",
            "truth_state": "derived",
        }
    return {
        "state": state,
        "counts": counts,
        "requirements": statuses,
        "conflicts": conflicts,
        "superseded_next_actions": _handoff_historical_items(
            superseded_next_items
        ),
        "active_reported_blockers": _handoff_historical_items(blocker_items),
        "exact_next_action": next_action,
    }


def _recovered_next_action_superseded_by_progress(
    item: dict[str, Any],
    *,
    progress_items: Iterable[dict[str, Any]],
) -> bool:
    payload = item.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("derived_from_recovered_goal") is not True:
        return False
    next_sequence = _item_sequence(item)
    if next_sequence is None:
        return False
    return any(
        progress_sequence > next_sequence
        and _positive_completion_claim(
            str(progress_item.get("statement") or "")
        )
        for progress_item in progress_items
        if (progress_sequence := _item_sequence(progress_item)) is not None
    )


def _mode_safe_next_action(
    task_mode: str,
    *,
    change_text: str,
    read_only_text: str,
) -> str:
    return change_text if task_mode == "change" else read_only_text


def _positive_completion_claim(statement: str) -> bool:
    return bool(
        _COMPLETION_CLAIM_RE.search(statement)
        and not _NEGATED_COMPLETION_RE.search(statement)
    )


def _statements_overlap(first: str, second: str) -> bool:
    first_tokens = _status_tokens(first)
    second_tokens = _status_tokens(second)
    shared = first_tokens & second_tokens
    if len(shared) >= 2:
        return True
    if shared and set(_extract_paths(first)) & set(_extract_paths(second)):
        return True
    # A single distinctive token is enough only when one side has no other
    # semantic token. Otherwise broad words such as "context", "preview", or
    # "session" can falsely promote a sibling requirement to done.
    return bool(
        len(shared) == 1
        and min(len(first_tokens), len(second_tokens)) == 1
    )


def _status_tokens(value: str) -> set[str]:
    tokens = {
        _STATUS_TOKEN_ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9][a-z0-9_]{2,}", value.casefold())
    }
    return {token for token in tokens if token not in _STATUS_MATCH_STOPWORDS}


def _reported_requirement_scope_hints(
    requirement_text: str,
    *,
    progress: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep prior-agent scope interpretations visible without promoting them."""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in progress:
        statement = str(item.get("statement") or "").strip()
        if (
            not statement
            or not _positive_completion_claim(statement)
            or not _statements_overlap(statement, requirement_text)
        ):
            continue
        key = re.sub(r"\W+", " ", statement.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "text": statement,
            "authority": "agent_reported",
            "verified": False,
        })
    return result


def _session_handoff_repository(
    data: dict[str, Any],
    *,
    repository_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = data.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    payload_repo = payload.get("repo")
    payload_repo = payload_repo if isinstance(payload_repo, dict) else {}
    stable_repo = data.get("repo")
    stable_repo = stable_repo if isinstance(stable_repo, dict) else {}
    captured = {
        "root": stable_repo.get("root") or payload_repo.get("root"),
        "branch": stable_repo.get("branch") or payload_repo.get("branch"),
        "head_commit": (
            stable_repo.get("head_commit") or payload_repo.get("head_commit")
        ),
        "status_fingerprint": (
            stable_repo.get("worktree_fingerprint")
            or payload_repo.get("status_fingerprint")
        ),
        "dirty": payload_repo.get("dirty"),
        "changed_files": list(payload_repo.get("changed_files") or []),
        "diff_summary": payload_repo.get("diff_summary"),
        "status_truncated": payload_repo.get("status_truncated"),
        "snapshot_authority": "observed_at_checkpoint",
    }
    comparison = (
        repository_comparison
        if isinstance(repository_comparison, dict)
        else {}
    )
    current = comparison.get("current")
    current = current if isinstance(current, dict) else None
    freshness_status = str(
        comparison.get("status") or "unavailable"
    ).strip().lower()
    active = current or captured
    return {
        **active,
        "snapshot_authority": (
            "observed_at_handoff" if current is not None
            else "observed_at_checkpoint"
        ),
        "freshness": {
            "status": freshness_status,
            "reason": str(comparison.get("reason") or "").strip() or None,
            "checked_at": comparison.get("checked_at"),
            "captured_head_commit": captured.get("head_commit"),
            "current_head_commit": (
                current.get("head_commit") if current is not None else None
            ),
        },
        "captured_snapshot": captured,
    }


def _session_handoff_files(
    relevant_items: Iterable[dict[str, Any]],
    progress_items: Iterable[dict[str, Any]],
    *,
    repository: dict[str, Any],
) -> dict[str, Any]:
    relevant_entries = list(relevant_items)
    progress_paths = {
        path
        for item in progress_items
        for path in _extract_paths(str(item.get("statement") or ""))
    }
    changed_paths = {
        str(path) for path in repository.get("changed_files") or [] if str(path).strip()
    }
    modified = sorted(progress_paths & changed_paths)
    relevant = sorted({
        str(item.get("payload", {}).get("path") or item.get("statement") or "").strip()
        for item in relevant_entries
        if str(item.get("payload", {}).get("path") or item.get("statement") or "").strip()
    } - set(modified))
    return {
        "modified": [
            {
                "path": path,
                "truth_state": "reported_plus_dirty_snapshot",
                "note": (
                    "The prior agent reported implementation work here and the "
                    "file was changed at capture; authorship is not independently proven."
                ),
            }
            for path in modified
        ],
        "relevant": [
            {
                "path": path,
                "truth_state": next(
                    (
                        str(item.get("truth_state") or "reported")
                        for item in relevant_entries
                        if str(
                            item.get("payload", {}).get("path")
                            or item.get("statement")
                            or ""
                        ).strip() == path
                    ),
                    "reported",
                ),
            }
            for path in relevant
        ],
        "pre_existing_at_handoff": [
            {
                "path": path,
                "truth_state": "observed",
                "preservation_rule": "Preserve unless the carried task requires editing it.",
            }
            for path in sorted(changed_paths)
        ],
        "classification_note": (
            "Pre-existing means changed before the receiving session starts. It "
            "does not prove whether the prior session or the user authored the change."
        ),
    }


def _session_handoff_rendered_files(
    files: dict[str, Any],
    *,
    limit: int = SESSION_HANDOFF_RENDERED_FILE_LIMIT,
) -> dict[str, Any]:
    """Build a compact view without mutating or truncating the typed contract."""

    records: dict[str, dict[str, Any]] = {}

    def include(
        item: dict[str, Any],
        *,
        classification: str,
        preserve: bool = False,
    ) -> None:
        path = str(item.get("path") or "").strip()
        if not path:
            return
        record = records.setdefault(
            path,
            {
                "path": path,
                "classifications": [],
                "preserve": False,
            },
        )
        if classification not in record["classifications"]:
            record["classifications"].append(classification)
        record["preserve"] = bool(record["preserve"] or preserve)

    for item in files.get("modified") or []:
        include(
            item,
            classification=(
                "reported modified + observed dirty"
                if item.get("truth_state") == "reported_plus_dirty_snapshot"
                else f"modified ({item.get('truth_state') or 'reported'})"
            ),
        )
    for item in files.get("relevant") or []:
        include(
            item,
            classification=f"relevant ({item.get('truth_state') or 'reported'})",
        )
    for item in files.get("pre_existing_at_handoff") or []:
        include(
            item,
            classification="observed dirty at handoff",
            preserve=True,
        )

    bounded_limit = max(1, int(limit))
    materialized = list(records.values())
    return {
        "items": materialized[:bounded_limit],
        "unique_count": len(materialized),
        "shown_count": min(len(materialized), bounded_limit),
        "omitted_count": max(0, len(materialized) - bounded_limit),
    }


def _session_handoff_definition_of_done(
    requirements: list[dict[str, Any]],
    *,
    repository: dict[str, Any],
) -> dict[str, Any]:
    explicit = [
        {
            "text": requirement["text"],
            "requirement_ids": [requirement["id"]],
            "source": requirement["source"],
            "authority": requirement["authority"],
        }
        for requirement in requirements
        if requirement.get("explicit_acceptance")
    ]
    operational = [{
        "text": (
            "Every accepted requirement is observed complete or has an explicit "
            "non-recoverable blocker, with requirement-linked verification where applicable."
        ),
        "requirement_ids": [item["id"] for item in requirements],
        "source": "session_handoff_policy",
        "authority": "derived_policy",
    }]
    if repository.get("changed_files"):
        operational.append({
            "text": "All pre-existing changes at the handoff boundary remain preserved.",
            "requirement_ids": [],
            "source": "session_handoff_policy",
            "authority": "derived_policy",
        })
    return {
        "explicit": explicit,
        "operational": operational,
        "explicitly_provided": bool(explicit),
    }


def _session_handoff_quality(
    *,
    dependency_required: bool,
    supporting_context: list[dict[str, str]],
    attachment_dependencies: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    repository: dict[str, Any],
    verification: list[dict[str, Any]],
    currentness: dict[str, Any] | None,
    boundary: dict[str, Any] | None,
    task_mode: str,
) -> dict[str, Any]:
    currentness = currentness if isinstance(currentness, dict) else {}
    boundary = boundary if isinstance(boundary, dict) else {}
    requirement_ids = {
        str(item.get("id") or "") for item in requirements if item.get("id")
    }
    verified_requirement_ids = {
        requirement_id
        for item in verification
        for requirement_id in item["requirement_ids"]
    }
    missing_verification_ids = sorted(
        requirement_ids - verified_requirement_ids
    )
    unavailable_required_attachments = [
        item
        for item in attachment_dependencies
        if item.get("required") is True
        and (
            item.get("available") is not True
            or not item.get("sha256")
        )
    ]
    checks = [
        {
            "code": "goal_self_contained",
            "status": (
                "pass"
                if not dependency_required or supporting_context
                else "fail"
            ),
        },
        {
            "code": "requirements_present",
            "status": "pass" if requirements else "fail",
        },
        {
            "code": "required_attachments_resolved",
            "status": (
                "fail"
                if unavailable_required_attachments
                else "pass"
            ),
            "missing_attachment_ids": [
                str(item.get("id") or "")
                for item in unavailable_required_attachments
            ],
            "message": (
                "One or more user-declared attachments have no trusted, "
                "hash-verified descriptor; Session Context cannot safely "
                "carry the visual dependency."
                if unavailable_required_attachments
                else "All required attachments are resolved."
            ),
        },
        {
            "code": "status_reconciled",
            "status": "pass",
        },
        {
            "code": "exact_next_action_present",
            "status": (
                "pass"
                if reconciliation.get("exact_next_action", {}).get("text")
                else "fail"
            ),
        },
        {
            "code": "repository_snapshot_present",
            "status": (
                "pass"
                if repository.get("root")
                else "fail"
                if task_mode == "change"
                else "warning"
            ),
        },
        {
            "code": "repository_status_capture_complete",
            "status": (
                "warning"
                if not repository.get("root")
                else "fail"
                if repository.get("status_truncated") is True
                else "pass"
            ),
        },
        {
            "code": "repository_current_at_handoff",
            "status": (
                "pass"
                if repository.get("snapshot_authority") == "observed_at_handoff"
                else "warning"
            ),
            "freshness": repository.get("freshness", {}).get("status"),
        },
        {
            "code": "session_boundary_current",
            "status": (
                "fail"
                if boundary.get("has_newer_events") is True
                or currentness.get("state") == "superseded"
                else "pass"
            ),
        },
        {
            "code": "requirement_verification_linkage",
            "status": (
                "pass"
                if requirement_ids and not missing_verification_ids
                else "warning"
            ),
            "covered_requirement_ids": sorted(verified_requirement_ids),
            "missing_requirement_ids": missing_verification_ids,
        },
    ]
    blocking = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warning"]
    if reconciliation["conflicts"]:
        blocking.append({
            "code": "completion_continuation_conflict_reconciled",
            "status": "fail",
            "count": len(reconciliation["conflicts"]),
            "message": (
                "Reported completion conflicts with a continuation instruction; "
                "inspect the preview and recapture after the conflict is resolved."
            ),
        })
    if repository.get("freshness", {}).get("status") == "changed":
        warnings.append({
            "code": "repository_changed_since_checkpoint",
            "status": "warning",
            "message": (
                "The handoff includes the current repository snapshot, but "
                "prior session completion claims require fresh confirmation."
            ),
        })
    copy_ready = not blocking
    automatic_execution_ready = bool(
        copy_ready
        and not reconciliation["conflicts"]
        and reconciliation["counts"]["unknown"] == 0
        and reconciliation["counts"]["reported_done"] == 0
        and repository.get("root")
        and not warnings
        and task_mode in {"change", "diagnose", "review", "report"}
    )
    return {
        "status": (
            "blocked"
            if blocking
            else "review_required"
            if warnings
            else "ready"
        ),
        "copy_ready": copy_ready,
        "automatic_execution_ready": automatic_execution_ready,
        "checks": checks,
        "blocking_issues": blocking,
        "warnings": warnings,
    }


def _handoff_historical_items(
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "statement": str(item.get("statement") or ""),
            "state": str(item.get("state") or "active"),
            "truth_state": str(item.get("truth_state") or "reported"),
        }
        for item in items
    ]


def _handoff_presentation_sections(
    sections: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    projected = {
        category: list(sections.get(category) or [])
        for category in CHECKPOINT_CATEGORIES
    }
    projected["blockers"] = [
        item
        for item in projected["blockers"]
        if not (
            _DERIVED_COMMAND_BLOCKER.fullmatch(
                str(item.get("statement") or "").strip()
            )
            and str(item.get("payload", {}).get("command") or "").strip()
        )
    ]
    projected["decisions"] = _dedupe_presentation_items([
        item
        for item in projected["decisions"]
        if not _is_tool_selection_statement(
            str(item.get("statement") or "")
        )
    ])
    projected["verification"] = _dedupe_command_observations([
        item
        for item in projected["verification"]
        if not _is_low_signal_failed_attempt(item)
        and _has_definitive_verification_outcome(item)
    ])
    passing_verification_sequences: dict[tuple[str, str], int] = {}
    for item in projected["verification"]:
        key = _command_observation_key(item)
        sequence = _item_sequence(item)
        if (
            key is None
            or sequence is None
            or not (
                (item.get("payload") or {}).get("passed") is True
                or str(item.get("state") or "").casefold() == "passed"
                or (item.get("payload") or {}).get("exit_code") == 0
            )
        ):
            continue
        passing_verification_sequences[key] = max(
            sequence,
            passing_verification_sequences.get(key, sequence),
        )
    projected["failed_attempts"] = _dedupe_command_observations([
        item
        for item in projected["failed_attempts"]
        if not _is_low_signal_failed_attempt(item)
        and not (
            (key := _command_observation_key(item)) is not None
            and (failed_sequence := _item_sequence(item)) is not None
            and (
                passing_sequence := passing_verification_sequences.get(key)
            ) is not None
            and passing_sequence > failed_sequence
        )
    ])
    latest_completion_sequence = max(
        (
            sequence
            for item in projected["progress"]
            if _positive_completion_claim(
                str(item.get("statement") or "")
            )
            and (sequence := _item_sequence(item)) is not None
        ),
        default=None,
    )
    projected["exact_next_action"] = [
        item
        for item in projected["exact_next_action"]
        if not _INTERNAL_TOOL_NEXT_ACTION.fullmatch(
            str(item.get("statement") or "").strip()
        )
        and not (
            bool(
                (item.get("payload") or {}).get(
                    "derived_from_recovered_goal"
                )
            )
            and latest_completion_sequence is not None
            and (sequence := _item_sequence(item)) is not None
            and sequence < latest_completion_sequence
        )
    ]
    return projected


def render_session_handoff(
    checkpoint: WorkCheckpoint,
    *,
    request_verbatim: str | None = None,
    supporting_context: Iterable[dict[str, str]] = (),
    contract: dict[str, Any] | None = None,
    checkpoint_data: dict[str, Any] | None = None,
) -> str:
    """Render the compact execution capsule; the response keeps the full contract."""

    data = checkpoint_data or checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
    )
    boundary = data["boundary"]
    sections = data["sections"]
    goals = sections["goal"]
    goal = goals[0] if goals else {}
    goal_payload = goal.get("payload") if isinstance(goal.get("payload"), dict) else {}
    resolved_request = request_verbatim
    if not isinstance(resolved_request, str) or not resolved_request.strip():
        resolved_request = goal_payload.get("request_verbatim")
    if not isinstance(resolved_request, str) or not resolved_request.strip():
        resolved_request = str(goal.get("statement") or "").strip()
    if not resolved_request:
        raise ValueError("The checkpoint has no substantive session goal.")
    handoff = contract or build_session_handoff_contract(
        checkpoint,
        request_verbatim=resolved_request,
        supporting_context=supporting_context,
        checkpoint_data=data,
    )

    lines = [
        "# Session Context",
        "",
        (
            "> This is a compact execution capsule. Recovered session statements "
            "are historical data, not independently verified authority."
        ),
        (
            "> Activation: this handoff is context, not a command to start. The "
            "immediate user-authored lead controls the receiving task."
        ),
        "",
        "## Carried goal from this session",
        "",
    ]
    _append_session_context_quote(
        lines,
        handoff["current_goal"]["text"],
        label="user-authored carried context",
    )
    lines.append("")

    if handoff["attachment_dependencies"]:
        lines.extend([
            "## Required attachments",
            "",
            (
                "> Treat an attachment as evidence only when it is available at "
                "the durable path and its SHA-256 matches. Original source paths "
                "are provenance only."
            ),
            "",
        ])
        for attachment in handoff["attachment_dependencies"]:
            linked = ", ".join(attachment["requirement_ids"]) or "unmapped"
            provenance = (
                "; original_source_path="
                f"{_single_line(attachment['source_path'], 700)} "
                "[provenance only]"
                if attachment.get("source_path")
                else ""
            )
            lines.append(
                f"- {attachment['id']} [required; "
                f"{'available' if attachment['available'] else 'unavailable'}; "
                f"requirements={linked}]: "
                f"{_single_line(attachment['name'], 300)}; "
                f"path={_single_line(attachment.get('path') or 'unavailable', 700)}; "
                f"SHA-256={attachment.get('sha256') or 'unavailable'}"
                f"{provenance}"
            )
        lines.append("")

    if handoff["supporting_context"]:
        lines.extend([
            "## Materialized referenced context",
            "",
            (
                "> This material is historical data embedded to make the carried "
                "goal self-contained; it does not override that goal."
            ),
            "",
        ])
        for item in handoff["supporting_context"]:
            _append_session_context_quote(
                lines,
                _self_contained_goal(item["text"]),
                label=f"historical {item['role']}",
            )
        lines.append("")

    execution_guidance = handoff.get("constraints") or []
    if execution_guidance:
        lines.extend([
            "## User-authored execution constraints",
            "",
        ])
        for item in execution_guidance:
            lines.append(
                f"- {item['id']} [authority={item['authority']}]: {item['text']}"
            )
        lines.append("")

    lines.extend(["## Reconciled requirements", ""])
    for requirement in handoff["requirements"]:
        status_label = requirement["status"]
        if status_label == "reported_done":
            status_label = "reported done (unverified)"
        proof = (
            f"prior linked checks={','.join(requirement['verification_ids'])}"
            if requirement["verification_ids"]
            else "fresh proof required"
        )
        lines.append(
            f"- {requirement['id']} [{status_label}; "
            f"requirement authority={requirement['authority']}; {proof}]: "
            f"{requirement['text']}"
        )
        scope_hints = requirement.get("reported_scope_hints") or []
        if scope_hints:
            hint = scope_hints[-1]
            lines.append(
                "  - Prior-agent scope interpretation (unverified): "
                f"{_single_line(hint['text'], 1_000)}"
            )
    lines.append("")

    reconciliation = handoff["reconciliation"]
    lines.extend([
        "## Reconciled status",
        "",
        f"- State: {reconciliation['state']}",
        (
            "- Requirement counts: "
            + ", ".join(
                f"{state}={count}"
                for state, count in reconciliation["counts"].items()
            )
        ),
    ])
    if reconciliation["conflicts"]:
        lines.append(
            "- Prior completion and continuation claims conflict. Neither is "
            "treated as current truth until repository inspection resolves it."
        )
    lines.extend(["", "## Exact next action", ""])
    _append_session_context_quote(
        lines,
        handoff["exact_next_action"]["text"],
        label=handoff["exact_next_action"]["truth_state"],
    )
    lines.append("")

    repository = handoff["repository"]
    lines.extend([
        "## Current evidence",
        "",
        (
            "- Mode: "
            f"{handoff['task_mode']} "
            f"({handoff['execution_policy']['permission_mode']})"
        ),
        (
            "- Repository: "
            f"{repository.get('root') or 'unavailable'}; "
            f"branch={repository.get('branch') or 'unavailable'}; "
            f"HEAD={repository.get('head_commit') or 'unavailable'}; "
            "relation="
            f"{repository.get('freshness', {}).get('status') or 'unavailable'}"
        ),
        (
            "- Boundary currentness: "
            f"{data.get('currentness', {}).get('state') or 'unknown'}; "
            "newer session events="
            f"{'yes' if boundary.get('has_newer_events') else 'no'}"
        ),
    ])
    protected_count = len(
        handoff["files"].get("pre_existing_at_handoff") or []
    )
    lines.append(
        f"- Protected baseline: {protected_count} pre-existing change"
        f"{'' if protected_count == 1 else 's'}. Treat all pre-existing changes "
        "as protected baseline state regardless of authorship; inspect live "
        "`git status --short` before editing."
    )

    relevant_paths: list[str] = []
    for category in ("modified", "relevant"):
        for item in handoff["files"].get(category) or []:
            path = str(item.get("path") or "").strip()
            if path and path not in relevant_paths:
                relevant_paths.append(path)
    if relevant_paths:
        lines.extend(["", "### Relevant files", ""])
        for path in relevant_paths[:8]:
            lines.append(f"- {_single_line(path, 500)}")
        if len(relevant_paths) > 8:
            lines.append(
                f"- … {len(relevant_paths) - 8} more task-relevant paths remain "
                "in the structured handoff."
            )

    lines.extend(["", "### Prior verification", ""])
    if handoff["verification"]:
        for item in handoff["verification"][:8]:
            linked = ", ".join(item["requirement_ids"]) or "unmapped"
            details: list[str] = []
            if item.get("command"):
                details.append(
                    f"command=`{_single_line(item['command'], 1_000)}`"
                )
            elif item.get("statement"):
                details.append(
                    f"evidence={_single_line(item['statement'], 1_000)}"
                )
            if item.get("cwd"):
                details.append(
                    f"cwd=`{_single_line(str(item['cwd']), 500)}`"
                )
            if item.get("exit_code") is not None:
                details.append(f"exit={item['exit_code']}")
            if item.get("scope"):
                details.append(f"scope={_single_line(item['scope'], 500)}")
            lines.append(
                f"- {item['id']} [{item['status']}; "
                f"scope={item.get('scope_kind') or 'observed'}; "
                f"link={item.get('link_kind') or 'unmapped'}; "
                f"requirements={linked}]: "
                + "; ".join(details)
            )
        if len(handoff["verification"]) > 8:
            lines.append(
                f"- … {len(handoff['verification']) - 8} more verification "
                "records remain in the structured handoff."
            )
    else:
        lines.append("- None captured.")

    if reconciliation["active_reported_blockers"]:
        lines.extend(["", "### Reported blockers", ""])
        for item in reconciliation["active_reported_blockers"][:3]:
            lines.append(
                f"- [unverified] {_single_line(item['statement'], 1_000)}"
            )
    if handoff["failed_attempts"]:
        lines.extend(["", "### Failed attempts", ""])
        for item in handoff["failed_attempts"][:3]:
            lines.append(
                f"- [{item['truth_state']}] "
                f"{_single_line(item['statement'], 1_000)}"
            )

    verification_notes: list[str] = []
    reported_done = [
        requirement["id"]
        for requirement in handoff["requirements"]
        if requirement["status"] == "reported_done"
    ]
    if reported_done:
        verification_notes.append(
            f"{', '.join(reported_done)} is reported complete but still needs "
            "current repository verification."
        )
    unmapped_verification = [
        item["id"]
        for item in handoff["verification"]
        if not item["requirement_ids"]
    ]
    if unmapped_verification:
        verification_notes.append(
            f"{', '.join(unmapped_verification)} is not mapped to a requirement; "
            "its focused or regression-safety scope is recorded separately."
        )
    if verification_notes:
        lines.extend(["", "## Verification notes", ""])
        lines.extend(f"- {note}" for note in verification_notes)

    return "\n".join(lines)


def _append_session_context_quote(
    lines: list[str],
    statement: str,
    *,
    label: str,
) -> None:
    statement_lines = statement.splitlines() or [""]
    lines.append(f"> [{label}] {statement_lines[0]}")
    lines.extend(
        f"> {line}" if line else ">"
        for line in statement_lines[1:]
    )


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


def _bind_checkpoint_goal_artifacts(
    sections: dict[str, list[DraftItem]],
    *,
    source_document: SourceDocument,
    provider: str,
) -> None:
    """Freeze exact-turn image descriptors into the immutable checkpoint."""

    goals = sections.get("goal") or []
    if not goals or not goals[0].events:
        return
    goal = goals[0]
    goal_event = goal.events[0]
    request_verbatim = str(
        goal.payload.get("request_verbatim") or ""
    ).strip()
    if not request_verbatim:
        return

    descriptors = trusted_request_image_descriptors_from_payload(
        event_payload(goal_event)
    )
    needs_durable_resolution = (
        not descriptors
        or any(
            not descriptor.resolved_path
            for descriptor in descriptors
            if descriptor.binding_valid
        )
    )
    recovered: tuple[TrustedRequestImageDescriptor, ...] = ()
    if provider == "codex" and needs_durable_resolution:
        metadata = _json_object(source_document.metadata_json)
        source_path = str(metadata.get("source_path") or "").strip()
        if source_path:
            configured_root = (
                Path(settings.codex_home).expanduser()
                if settings.codex_home
                else Path.home() / ".codex"
            )
            recovered = recover_codex_request_image_descriptors(
                source_path=source_path,
                source_sequence_number=goal_event.sequence_number,
                request_verbatim=request_verbatim,
                codex_sessions_root=configured_root / "sessions",
                artifact_data_dir=settings.data_dir,
            )
    if recovered:
        if not descriptors:
            descriptors = recovered
        elif _same_descriptor_binding(descriptors, recovered):
            descriptors = recovered
        else:
            descriptors = tuple(
                TrustedRequestImageDescriptor(
                    path=descriptor.path,
                    sha256=descriptor.sha256,
                    mime_type=descriptor.mime_type,
                    resolved_path=None,
                    ordinal=descriptor.ordinal,
                    size_bytes=descriptor.size_bytes,
                    binding_valid=False,
                    binding_error=(
                        "The normalized provider metadata conflicts with the "
                        "immutable raw turn."
                    ),
                )
                for descriptor in descriptors
            )

    descriptors = tuple(
        materialize_trusted_request_image_descriptor(
            descriptor,
            data_dir=settings.data_dir,
        )
        for descriptor in descriptors
    )
    serialized = [
        _trusted_image_descriptor_to_dict(descriptor)
        for descriptor in descriptors
    ]
    goal.payload.update({
        "trusted_image_descriptors": serialized,
        "trusted_image_descriptors_sha256": _sha256(
            _canonical_json(serialized)
        ),
    })


def _same_descriptor_binding(
    left: Iterable[TrustedRequestImageDescriptor],
    right: Iterable[TrustedRequestImageDescriptor],
) -> bool:
    left_values = tuple(left)
    right_values = tuple(right)
    if len(left_values) != len(right_values):
        return False
    return all(
        left_item.path == right_item.path
        and left_item.ordinal == right_item.ordinal
        and (
            left_item.sha256 is None
            or right_item.sha256 is None
            or left_item.sha256.casefold() == right_item.sha256.casefold()
        )
        for left_item, right_item in zip(
            left_values,
            right_values,
            strict=True,
        )
    )


def _trusted_image_descriptor_to_dict(
    descriptor: TrustedRequestImageDescriptor,
) -> dict[str, Any]:
    return {
        "path": descriptor.path,
        "sha256": descriptor.sha256,
        "mime_type": descriptor.mime_type,
        "resolved_path": descriptor.resolved_path,
        "stored_path": descriptor.resolved_path,
        "ordinal": descriptor.ordinal,
        "size_bytes": descriptor.size_bytes,
        "binding_valid": descriptor.binding_valid,
        "binding_error": descriptor.binding_error,
    }


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
        request_verbatim = _checkpoint_request_verbatim(goal_event)
        supporting_context = _materialized_referenced_context(
            goal_event.content,
            request_verbatim=request_verbatim,
        )
        stored_requirements = _derive_session_requirements(
            request_verbatim or str(goal_statement or ""),
            supporting_context=supporting_context,
        )
        goal_payload: dict[str, Any] = {}
        if request_verbatim:
            goal_payload.update({
                "request_verbatim": request_verbatim,
                "request_sha256": _sha256(request_verbatim),
                "task_mode": _infer_session_task_mode(request_verbatim),
            })
        trusted_images = trusted_request_image_descriptors_from_payload(
            event_payload(goal_event)
        )
        if trusted_images:
            image_descriptors = [
                {
                    "path": descriptor.path,
                    "sha256": descriptor.sha256,
                    "mime_type": descriptor.mime_type,
                }
                for descriptor in trusted_images
            ]
            goal_payload.update({
                "trusted_image_descriptors": image_descriptors,
                "trusted_image_descriptors_sha256": _sha256(
                    _canonical_json(image_descriptors)
                ),
            })
        if supporting_context:
            goal_payload.update({
                "supporting_context": supporting_context,
                "supporting_context_sha256": _sha256(
                    _canonical_json(supporting_context)
                ),
            })
        if stored_requirements:
            goal_payload["requirements"] = stored_requirements
        sections["goal"] = [DraftItem(
            category="goal",
            statement=str(goal_statement or "").strip(),
            truth_state="reported",
            events=[goal_event],
            payload=goal_payload,
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
        if event.event_type not in {"user_request", "assistant_update"}:
            continue
        decision_content = (
            extract_user_authored_request(event.content)
            if event.event_type == "user_request"
            else event.content
        )
        if (
            not decision_content
            or is_session_instruction_noise(decision_content)
            or (
                event.event_type == "user_request"
                and is_continuation_control(decision_content)
            )
        ):
            continue
        for sentence in _sentences(decision_content):
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

    blockers: list[DraftItem] = []
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
    latest_progress_sequence = max(
        (
            item.events[-1].sequence_number
            for item in progress
            if item.events
        ),
        default=None,
    )
    if latest_progress_sequence is not None:
        for blocker in blockers:
            if (
                blocker.events
                and blocker.events[-1].sequence_number < latest_progress_sequence
            ):
                blocker.state = "historical"
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
                "scope": next(
                    (
                        payload.get(key)
                        for key in (
                            "scope",
                            "test_scope",
                            "verification_scope",
                            "target",
                        )
                        if payload.get(key) not in (None, "")
                    ),
                    None,
                ),
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
    active_blockers = [
        blocker
        for blocker in blockers
        if blocker.state.strip().lower() not in _INACTIVE_BLOCKER_STATES
    ]
    if active_blockers:
        blocker = active_blockers[-1]
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
            truth_state=(
                "reported" if continuation_event is not None else "derived"
            ),
            events=[goal_event, *([continuation_event] if continuation_event else [])],
            payload=(
                {"source": "explicit_continuation_control"}
                if continuation_event is not None
                else {"derived_from_recovered_goal": True}
            ),
        )
    return None


def _checkpoint_user_request(event: SessionEvent) -> str | None:
    if event.event_type == "user_request":
        return normalize_substantive_user_request(event.content)
    if event.event_type == "runtime_instruction" and event.role == "user":
        return extract_delegated_user_request(event.content)
    return None


def _checkpoint_request_verbatim(event: SessionEvent) -> str | None:
    if event.event_type == "user_request":
        return extract_user_authored_request(event.content)
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
