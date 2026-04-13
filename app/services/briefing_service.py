from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.connector import Connector
from app.models.job import SyncJob, SyncJobStatus
from app.models.knowledge import Component, KnowledgeModel, Relationship
from app.models.review import ReviewDecision, ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace
from app.processing.extractor import extract_meeting_action_items, extract_meeting_outcomes
from app.schemas.briefing import (
    FounderBriefConflictRead,
    FounderBriefConnectorFailureRead,
    FounderBriefFactRead,
    FounderBriefRead,
    FounderBriefRiskRead,
    LaunchGuardClaimRead,
    LaunchGuardEvidenceRead,
    LaunchGuardRead,
    TimelineEventRead,
    TimelineRead,
)
from app.services.decision_service import DecisionService
from app.services.query_service import QueryService
from app.services.truth_visibility import (
    history_where,
    is_component_visible_in_current_truth,
)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "this",
    "to",
    "was",
    "we",
}
_NUMBER_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?(?:/[A-Za-z]+)?")


class BriefingServiceError(Exception):
    """Base founder-brief / launch-guard service error."""


class BriefingWorkspaceNotFoundError(BriefingServiceError):
    """Raised when the workspace does not exist."""


class BriefingService:
    _TIMELINE_EVENT_PRIORITY = {
        "decision_change": 0,
        "review_transition": 1,
        "source_ingest": 2,
        "connector_failure": 3,
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._query_service = QueryService(session)

    async def build_founder_brief(
        self,
        *,
        workspace_id: UUID,
        lookback_days: int = 7,
    ) -> FounderBriefRead:
        await self._require_workspace(workspace_id)
        since = datetime.now(UTC) - timedelta(days=lookback_days)
        current_components = await self._load_components(workspace_id=workspace_id, current_only=True)

        changed_facts = [
            self._serialize_fact(component)
            for component in current_components
            if component.valid_from >= since
        ][:10]
        new_blockers = [
            self._serialize_fact(component)
            for component in current_components
            if component.valid_from >= since and self._is_blocker(component)
        ][:10]

        conflict_items = [
            item
            for item in await self.session.scalars(
                select(ReviewItem)
                .join(Component, ReviewItem.component_id == Component.id)
                .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
                .options(selectinload(ReviewItem.component))
                .where(
                    KnowledgeModel.workspace_id == workspace_id,
                    ReviewItem.status == "needs_review",
                    ReviewItem.kind == "conflict",
                )
                .order_by(ReviewItem.updated_at.desc(), ReviewItem.created_at.desc())
            )
            if item.component is not None
            and is_component_visible_in_current_truth(item.component)
        ]

        stale_high_risk_items: list[FounderBriefRiskRead] = []
        for component in current_components:
            reason = self._risk_reason(component)
            if reason is None:
                continue
            stale_high_risk_items.append(
                FounderBriefRiskRead(
                    component_id=component.id,
                    name=component.name,
                    value=component.value,
                    reason=reason,
                    confidence=component.confidence,
                    review_status=component.review_status,
                    source_labels=self._source_labels(component),
                    source_document_ids=self._source_document_ids(component),
                )
            )
        stale_high_risk_items = stale_high_risk_items[:10]

        failures = list(
            await self.session.scalars(
                select(SyncJob)
                .join(Connector, SyncJob.connector_id == Connector.id)
                .options(selectinload(SyncJob.connector))
                .where(
                    Connector.workspace_id == workspace_id,
                    SyncJob.status == SyncJobStatus.FAILED,
                    SyncJob.created_at >= since,
                )
                .order_by(SyncJob.created_at.desc(), SyncJob.id.desc())
            )
        )

        return FounderBriefRead(
            workspace_id=workspace_id,
            generated_at=datetime.now(UTC),
            lookback_days=lookback_days,
            changed_facts=changed_facts,
            new_blockers=new_blockers,
            open_conflicts=[
                FounderBriefConflictRead(
                    review_item_id=item.id,
                    component_id=item.component_id,
                    component_name=item.component.name if item.component is not None else "",
                    status=item.status,
                    severity=item.severity,
                    kind=item.kind,
                    title=item.title,
                    summary=item.summary,
                    suggested_action=item.suggested_action,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in conflict_items[:10]
            ],
            stale_high_risk_items=stale_high_risk_items,
            recent_connector_failures=[
                FounderBriefConnectorFailureRead(
                    job_id=job.id,
                    connector_id=job.connector_id,
                    connector_type=job.connector.connector_type.value
                    if job.connector is not None
                    else "unknown",
                    job_type=job.job_type,
                    failed_at=job.completed_at or job.created_at,
                    error_type=job.error_type,
                    error_message=job.error_message,
                )
                for job in failures[:10]
            ],
        )

    async def run_launch_guard(
        self,
        *,
        workspace_id: UUID,
        draft: str,
    ) -> LaunchGuardRead:
        await self._require_workspace(workspace_id)
        all_components = await self._load_components(workspace_id=workspace_id, current_only=False)
        historical_components = [component for component in all_components if component.valid_to is not None]
        by_id = {component.id: component for component in all_components}

        claims: list[LaunchGuardClaimRead] = []
        for claim in self._split_claims(draft):
            query_result = await self._query_service.query(claim, workspace_id=workspace_id)
            current_match = None
            current_score = 0.0
            if query_result.components:
                current_match = by_id.get(query_result.components[0].id)
                if current_match is not None:
                    current_score = self._claim_match_score(claim, current_match)

            historical_match, historical_score = self._best_match(claim, historical_components)
            status = "unclear"
            reason = "No strong source-backed match was found in current truth."
            matched_component = current_match

            if (
                historical_match is not None
                and historical_score >= 0.55
                and historical_score > current_score + 0.15
            ):
                status = "stale"
                matched_component = historical_match
                reason = (
                    "This claim aligns more closely with a historical fact than the current "
                    "workspace truth."
                )
            elif current_match is not None and self._is_contradiction(claim, current_match, current_score):
                status = "contradicted"
                reason = "This claim conflicts with the strongest current source-backed fact."
            elif current_match is not None and current_score >= 0.30:
                status = "supported"
                reason = "This claim is consistent with current source-backed truth."

            claims.append(
                LaunchGuardClaimRead(
                    claim=claim,
                    status=status,
                    reason=reason,
                    matched_component_id=matched_component.id if matched_component is not None else None,
                    matched_component_name=matched_component.name if matched_component is not None else None,
                    matched_component_value=matched_component.value if matched_component is not None else None,
                    matched_component_valid_from=matched_component.valid_from
                    if matched_component is not None
                    else None,
                    matched_component_valid_to=matched_component.valid_to
                    if matched_component is not None
                    else None,
                    evidence=self._serialize_evidence(matched_component),
                )
            )

        return LaunchGuardRead(
            workspace_id=workspace_id,
            checked_at=datetime.now(UTC),
            supported_count=sum(1 for claim in claims if claim.status == "supported"),
            contradicted_count=sum(1 for claim in claims if claim.status == "contradicted"),
            stale_count=sum(1 for claim in claims if claim.status == "stale"),
            unclear_count=sum(1 for claim in claims if claim.status == "unclear"),
            claims=claims,
        )

    async def build_timeline(
        self,
        *,
        workspace_id: UUID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TimelineRead:
        await self._require_workspace(workspace_id)

        events: list[TimelineEventRead] = []

        decision_components = list(
            await self.session.scalars(
                select(Component)
                .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
                .options(
                    selectinload(Component.model),
                    selectinload(Component.review_item),
                    selectinload(Component.source_documents),
                    selectinload(Component.outgoing_relationships)
                    .selectinload(Relationship.target_component)
                    .selectinload(Component.review_item),
                    selectinload(Component.incoming_relationships)
                    .selectinload(Relationship.source_component)
                    .selectinload(Component.review_item),
                )
                .where(
                    KnowledgeModel.workspace_id == workspace_id,
                    func.lower(Component.name).like("%decision%"),
                )
                .order_by(Component.valid_from.desc(), Component.id.desc())
            )
        )
        for component in decision_components:
            if not is_component_visible_in_current_truth(component):
                continue
            primary_source = self._primary_source_document(component)
            events.append(
                TimelineEventRead(
                    event_id=f"decision_change:{component.id}",
                    event_type="decision_change",
                    occurred_at=component.valid_from,
                    title=f"Decision change: {component.name}",
                    summary=component.value,
                    component_id=component.id,
                    connector_type=primary_source.connector_type.value if primary_source else None,
                    source_document_id=primary_source.id if primary_source else None,
                    source_label=primary_source.label if primary_source else None,
                    model_name=component.model.name if component.model is not None else None,
                    status="current" if component.valid_to is None else "historical",
                    payload={
                        "value": component.value,
                        "confidence": component.confidence,
                        "authority_weight": component.authority_weight,
                        "review_status": component.review_status,
                        "is_current": component.valid_to is None,
                        "related_blocker": DecisionService._related_blocker(component),
                        "source_document_id": str(primary_source.id)
                        if primary_source is not None
                        else None,
                        **self._document_context_payload(primary_source),
                    },
                )
            )

        review_transitions = list(
            await self.session.scalars(
                select(ReviewDecision)
                .join(ReviewItem, ReviewDecision.review_item_id == ReviewItem.id)
                .join(Component, ReviewItem.component_id == Component.id)
                .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
                .options(
                    selectinload(ReviewDecision.review_item)
                    .selectinload(ReviewItem.component)
                    .selectinload(Component.model)
                )
                .where(KnowledgeModel.workspace_id == workspace_id)
                .order_by(ReviewDecision.created_at.desc(), ReviewDecision.id.desc())
            )
        )
        for transition in review_transitions:
            review_item = transition.review_item
            component = review_item.component if review_item is not None else None
            events.append(
                TimelineEventRead(
                    event_id=f"review_transition:{transition.id}",
                    event_type="review_transition",
                    occurred_at=transition.created_at,
                    title=(
                        f"Review transition: {component.name}"
                        if component is not None
                        else "Review transition"
                    ),
                    summary=(
                        f"{transition.previous_status or 'none'} -> {transition.new_status}"
                        + (f". {transition.note}" if transition.note else "")
                    ),
                    component_id=component.id if component is not None else None,
                    review_item_id=review_item.id if review_item is not None else None,
                    model_name=component.model.name
                    if component is not None and component.model is not None
                    else None,
                    status=transition.new_status,
                    payload={
                        "previous_status": transition.previous_status,
                        "new_status": transition.new_status,
                        "actor_type": transition.actor_type,
                        "note": transition.note,
                    },
                )
            )

        ingests = list(
            await self.session.scalars(
                select(SourceDocument)
                .join(Connector, SourceDocument.connector_id == Connector.id)
                .options(selectinload(SourceDocument.connector))
                .where(Connector.workspace_id == workspace_id)
                .order_by(SourceDocument.ingested_at.desc(), SourceDocument.id.desc())
            )
        )
        for document in ingests:
            events.append(
                TimelineEventRead(
                    event_id=f"source_ingest:{document.id}",
                    event_type="source_ingest",
                    occurred_at=document.ingested_at,
                    title=f"Source ingested: {document.label}",
                    summary=document.external_id,
                    source_document_id=document.id,
                    connector_id=document.connector_id,
                    connector_type=document.connector_type.value,
                    source_label=document.label,
                    payload=self._source_ingest_payload(document),
                )
            )

        failures = list(
            await self.session.scalars(
                select(SyncJob)
                .join(Connector, SyncJob.connector_id == Connector.id)
                .options(selectinload(SyncJob.connector))
                .where(
                    Connector.workspace_id == workspace_id,
                    SyncJob.status == SyncJobStatus.FAILED,
                )
                .order_by(SyncJob.completed_at.desc(), SyncJob.created_at.desc(), SyncJob.id.desc())
            )
        )
        for job in failures:
            occurred_at = job.completed_at or job.created_at
            events.append(
                TimelineEventRead(
                    event_id=f"connector_failure:{job.id}",
                    event_type="connector_failure",
                    occurred_at=occurred_at,
                    title=(
                        f"Connector failure: {job.connector.connector_type.value}"
                        if job.connector is not None
                        else "Connector failure"
                    ),
                    summary=job.error_message or job.error_type or "Connector job failed",
                    connector_id=job.connector_id,
                    connector_type=job.connector.connector_type.value
                    if job.connector is not None
                    else None,
                    status=job.status.value,
                    payload={
                        "job_id": str(job.id),
                        "job_type": job.job_type,
                        "error_type": job.error_type,
                        "error_message": job.error_message,
                    },
                )
            )

        total_events = len(events)
        ordered_events = sorted(events, key=self._timeline_sort_key)
        start_index = 0
        if cursor:
            cursor_state = self._decode_timeline_cursor(cursor)
            if cursor_state is not None:
                for index, event in enumerate(ordered_events):
                    if self._timeline_event_signature(event) == cursor_state:
                        start_index = index + 1
                        break
        paged = ordered_events[start_index : start_index + limit + 1]
        has_more = len(paged) > limit
        items = paged[:limit]
        next_cursor = (
            self._encode_timeline_cursor(items[-1])
            if has_more and items
            else None
        )
        return TimelineRead(
            workspace_id=workspace_id,
            generated_at=datetime.now(UTC),
            total_events=total_events,
            has_more=has_more,
            next_cursor=next_cursor,
            items=items,
        )

    async def _require_workspace(self, workspace_id: UUID) -> None:
        workspace = await self.session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id).limit(1)
        )
        if workspace is None:
            raise BriefingWorkspaceNotFoundError("Workspace not found")

    async def _load_components(
        self,
        *,
        workspace_id: UUID,
        current_only: bool,
    ) -> list[Component]:
        stmt = (
            select(Component)
            .join(KnowledgeModel, Component.model_id == KnowledgeModel.id)
            .options(
                selectinload(Component.model),
                selectinload(Component.review_item),
                selectinload(Component.source_documents),
            )
            .where(KnowledgeModel.workspace_id == workspace_id)
            .order_by(Component.valid_from.desc(), Component.id.desc())
        )

        # Push truth filtering into SQL — no Python-side double-filter needed.
        if current_only:
            stmt = stmt.where(Component.valid_to.is_(None))
            stmt = stmt.where(
                or_(
                    ~Component.review_item.has(),
                    ~Component.review_item.has(
                        ReviewItem.status.in_(("rejected", "superseded"))
                    ),
                )
            )
        else:
            stmt = history_where(stmt)

        rows = await self.session.scalars(stmt)
        return list(rows)

    @staticmethod
    def _serialize_fact(component: Component) -> FounderBriefFactRead:
        return FounderBriefFactRead(
            component_id=component.id,
            model_id=component.model_id,
            model_name=component.model.name if component.model is not None else "",
            name=component.name,
            value=component.value,
            confidence=component.confidence,
            authority_weight=component.authority_weight,
            valid_from=component.valid_from,
            review_status=component.review_status,
            review_item_id=component.review_item_id,
            source_labels=BriefingService._source_labels(component),
            source_document_ids=BriefingService._source_document_ids(component),
        )

    @staticmethod
    def _source_labels(component: Component) -> list[str]:
        labels: list[str] = []
        for document in component.source_documents:
            if document.deleted_at is not None:
                continue
            label = document.label
            if label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _source_document_ids(component: Component) -> list[UUID]:
        """Return IDs of non-deleted source documents for provenance."""
        return [
            document.id
            for document in component.source_documents
            if document.deleted_at is None
        ]

    @staticmethod
    def _primary_source_document(component: Component) -> SourceDocument | None:
        candidates = [
            document
            for document in component.source_documents
            if document.deleted_at is None
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda document: (
                document.ingested_at,
                document.id,
            ),
            reverse=True,
        )[0]

    @classmethod
    def _source_ingest_payload(cls, document: SourceDocument) -> dict[str, object]:
        payload: dict[str, object] = {
            "external_id": document.external_id,
            "processed": document.processed_at is not None,
            "deleted": document.deleted_at is not None,
        }
        payload.update(cls._document_context_payload(document))
        return payload

    @classmethod
    def _document_context_payload(
        cls,
        document: SourceDocument | None,
    ) -> dict[str, object]:
        if document is None:
            return {}

        metadata = document.metadata_json or {}
        payload: dict[str, object] = {}
        if workflow_key := cls._document_workflow_key(document):
            payload["workflow_key"] = workflow_key
        if source_type := metadata.get("source_type"):
            payload["source_type"] = source_type

        if document.connector_type == ConnectorType.ZOOM or metadata.get("meeting_topic"):
            payload.update(cls._meeting_payload(document))
        elif document.connector_type == ConnectorType.GITHUB or metadata.get("repo_full_name"):
            payload.update(cls._github_payload(metadata))

        return payload

    @staticmethod
    def _meeting_payload(document: SourceDocument) -> dict[str, object]:
        metadata = document.metadata_json or {}
        outcomes = extract_meeting_outcomes(document.content)
        action_items = extract_meeting_action_items(document.content)
        owners: list[str] = []
        for owner, _ in action_items:
            if owner and owner not in owners:
                owners.append(owner)

        payload: dict[str, object] = {
            "meeting_topic": metadata.get("meeting_topic"),
            "meeting_id": metadata.get("meeting_id"),
            "meeting_uuid": metadata.get("meeting_uuid"),
            "participants": metadata.get("participants") or [],
            "recording_date": metadata.get("recording_date"),
        }
        if outcomes:
            payload["meeting_outcome_summary"] = "; ".join(outcomes[:3])
        if owners:
            payload["action_owners"] = owners
        if action_items:
            payload["action_items"] = [
                {"owner": owner, "action": action}
                for owner, action in action_items[:10]
            ]
        return {key: value for key, value in payload.items() if value not in (None, [], "")}

    @staticmethod
    def _github_payload(metadata: dict[str, object]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key in (
            "repo_full_name",
            "item_type",
            "number",
            "parent_item_type",
            "parent_number",
            "parent_title",
            "parent_external_id",
            "review_state",
            "commit_id",
            "original_commit_id",
            "path",
            "line",
            "side",
            "pull_request_references",
            "issue_references",
            "commit_references",
        ):
            value = metadata.get(key)
            if value not in (None, [], ""):
                payload[key] = value
        return payload

    @staticmethod
    def _document_workflow_key(document: SourceDocument) -> str | None:
        metadata = document.metadata_json or {}
        if document.connector_type == ConnectorType.ZOOM or metadata.get("meeting_topic"):
            meeting_key = metadata.get("meeting_id") or metadata.get("meeting_uuid")
            if meeting_key:
                return f"zoom:{meeting_key}"
        if document.connector_type == ConnectorType.GITHUB or metadata.get("repo_full_name"):
            if parent_external_id := metadata.get("parent_external_id"):
                return str(parent_external_id)
            repo_full_name = metadata.get("repo_full_name")
            item_type = metadata.get("item_type")
            number = metadata.get("number")
            if repo_full_name and item_type and number is not None:
                return f"github:{repo_full_name}:{item_type}:{number}"
        if channel_name := metadata.get("channel_name"):
            return f"slack:{channel_name}"
        return None

    @classmethod
    def _timeline_sort_key(cls, item: TimelineEventRead) -> tuple[float, int, str, str]:
        return (
            -item.occurred_at.timestamp(),
            cls._TIMELINE_EVENT_PRIORITY.get(item.event_type, 99),
            item.title,
            item.event_id,
        )

    @staticmethod
    def _timeline_event_stable_id(item: TimelineEventRead) -> str:
        return item.event_id

    @classmethod
    def _timeline_event_signature(cls, item: TimelineEventRead) -> tuple[str, str, str, str]:
        return (
            item.occurred_at.isoformat(),
            item.event_type,
            item.title,
            cls._timeline_event_stable_id(item),
        )

    @classmethod
    def _encode_timeline_cursor(cls, item: TimelineEventRead) -> str:
        payload = {
            "occurred_at": item.occurred_at.isoformat(),
            "event_type": item.event_type,
            "title": item.title,
            "stable_id": cls._timeline_event_stable_id(item),
        }
        raw = json.dumps(payload, sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_timeline_cursor(cursor: str) -> tuple[str, str, str, str] | None:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode()).decode()
            payload = json.loads(raw)
            return (
                str(payload["occurred_at"]),
                str(payload["event_type"]),
                str(payload["title"]),
                str(payload["stable_id"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, binascii.Error):
            return None

    @staticmethod
    def _is_blocker(component: Component) -> bool:
        return component.name.lower().startswith("blocker")

    @staticmethod
    def _risk_reason(component: Component) -> str | None:
        if component.review_status == "needs_review":
            if component.review_item is not None and component.review_item.kind == "conflict":
                return "Current fact still has an open cross-source conflict."
            if component.review_item is not None and component.review_item.kind == "low_confidence":
                return "Current fact is still awaiting review because extraction confidence was low."
            return "Current fact still needs review."
        if component.is_stale:
            return "Current fact is marked stale and should be re-verified."
        if component.confidence < 0.60:
            return "Current fact remains below the confidence trust threshold."
        return None

    @staticmethod
    def _split_claims(draft: str) -> list[str]:
        lines = [segment.strip(" -\t") for segment in re.split(r"[\n\r]+", draft) if segment.strip()]
        claims: list[str] = []
        for line in lines:
            parts = re.split(r"(?<=[.!?])\s+", line)
            for part in parts:
                cleaned = part.strip()
                if cleaned:
                    claims.append(cleaned)
        return claims

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9$#/.-]+", text.lower())
            if token not in _STOPWORDS and len(token) > 1
        }

    @staticmethod
    def _extract_numbers(text: str) -> set[str]:
        return {match.group(0).lower() for match in _NUMBER_RE.finditer(text)}

    @classmethod
    def _claim_match_score(cls, claim: str, component: Component) -> float:
        claim_tokens = cls._tokenize(claim)
        if not claim_tokens:
            return 0.0
        name_tokens = cls._tokenize(component.name)
        value_tokens = cls._tokenize(component.value)
        name_overlap = len(claim_tokens & name_tokens) / max(1, len(name_tokens))
        value_overlap = len(claim_tokens & value_tokens) / max(1, len(value_tokens))
        claim_numbers = cls._extract_numbers(claim)
        value_numbers = cls._extract_numbers(component.value)
        numeric_overlap = 1.0 if claim_numbers and claim_numbers & value_numbers else 0.0
        return round((0.45 * name_overlap) + (0.45 * value_overlap) + (0.10 * numeric_overlap), 3)

    @classmethod
    def _best_match(
        cls,
        claim: str,
        components: list[Component],
    ) -> tuple[Component | None, float]:
        best_component: Component | None = None
        best_score = 0.0
        for component in components:
            score = cls._claim_match_score(claim, component)
            if score > best_score:
                best_score = score
                best_component = component
        return best_component, best_score

    @classmethod
    def _is_contradiction(
        cls,
        claim: str,
        component: Component,
        score: float,
    ) -> bool:
        if score < 0.25:
            return False
        claim_numbers = cls._extract_numbers(claim)
        value_numbers = cls._extract_numbers(component.value)
        if claim_numbers and value_numbers and claim_numbers != value_numbers:
            return True
        claim_tokens = cls._tokenize(claim)
        value_tokens = cls._tokenize(component.value)
        name_tokens = cls._tokenize(component.name)
        name_overlap = len(claim_tokens & name_tokens)
        value_overlap = len(claim_tokens & value_tokens)
        return name_overlap > 0 and value_overlap == 0

    @staticmethod
    def _serialize_evidence(component: Component | None) -> list[LaunchGuardEvidenceRead]:
        if component is None:
            return []
        evidence: list[LaunchGuardEvidenceRead] = []
        for document in component.source_documents:
            if document.deleted_at is not None:
                continue
            evidence.append(
                LaunchGuardEvidenceRead(
                    source_document_id=document.id,
                    label=document.label,
                    connector_type=document.connector_type.value,
                    source_url=document.source_url,
                )
            )
            if len(evidence) >= 3:
                break
        return evidence
