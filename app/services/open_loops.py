from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, ContextPack, OpenLoop
from app.services.founder_oversight import FounderOversightNotFoundError, FounderOversightService
from app.services.source_revisions import ingest_source_document_revision
from app.time import utc_now


SUPPORTED_RULES = frozenset({
    "verification.missing.v1",
    "verification.failed.v1",
    "blocker.unresolved.v1",
    "completion.evidence_missing.v1",
    "outcome.check_conflict.v1",
    "source.stale.v1",
})
AUTO_RESOLVABLE_RULES = frozenset({
    "verification.missing.v1",
    "verification.failed.v1",
    "blocker.unresolved.v1",
    "completion.evidence_missing.v1",
    "outcome.check_conflict.v1",
})
CLOSED_STATES = frozenset({"dismissed", "resolved", "superseded"})


class OpenLoopNotFoundError(LookupError):
    pass


class OpenLoopActionError(ValueError):
    pass


class OpenLoopService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reconcile_run(self, run_id: UUID) -> list[OpenLoop]:
        run = await self.session.get(AgentRun, run_id)
        if run is None or run.workspace_id is None or run.context_pack_id is None:
            return []
        pack = await self.session.get(ContextPack, run.context_pack_id)
        if pack is None or pack.focus_component_id is None:
            return []
        try:
            timeline = await FounderOversightService(self.session).build_timeline(
                workspace_id=run.workspace_id,
                focus_component_id=pack.focus_component_id,
            )
        except FounderOversightNotFoundError:
            return []
        return await self.reconcile_timeline(
            workspace_id=run.workspace_id,
            timeline=timeline,
        )

    async def reconcile_timeline(
        self,
        *,
        workspace_id: UUID,
        timeline: dict[str, Any],
    ) -> list[OpenLoop]:
        now = utc_now()
        findings = [
            item for item in (timeline.get("findings") or [])
            if isinstance(item, dict) and item.get("rule_id") in SUPPORTED_RULES
        ]
        current_keys = {str(item.get("id")) for item in findings if item.get("id")}
        pack_ids = {
            _uuid(item.get("context_pack_id"))
            for item in findings
            if _uuid(item.get("context_pack_id")) is not None
        }
        if not pack_ids:
            latest_pack_id = next(
                (
                    _uuid(item.get("context_pack_id"))
                    for item in timeline.get("runs") or []
                    if _uuid(item.get("context_pack_id")) is not None
                ),
                None,
            )
            if latest_pack_id is not None:
                pack_ids.add(latest_pack_id)
        focus_id = _uuid((timeline.get("focus") or {}).get("component_id"))
        persisted: list[OpenLoop] = []
        for finding in findings:
            persisted.append(await self._upsert_finding(workspace_id, finding, now))

        if pack_ids:
            resolution_source_id = _latest_resolution_source_id(timeline)
            existing = list(await self.session.scalars(
                select(OpenLoop).where(
                    OpenLoop.workspace_id == workspace_id,
                    OpenLoop.context_pack_id.in_(pack_ids),
                    OpenLoop.status == "open",
                )
            ))
            for loop in existing:
                if loop.natural_key in current_keys or loop.rule_id not in AUTO_RESOLVABLE_RULES:
                    continue
                loop.status = "resolved"
                loop.closed_at = now
                loop.resolution_reason = "Resolved by later structured run evidence."
                loop.resolution_source_document_id = resolution_source_id

        if focus_id is not None and pack_ids:
            older = list(await self.session.scalars(
                select(OpenLoop).where(
                    OpenLoop.workspace_id == workspace_id,
                    OpenLoop.focus_component_id == focus_id,
                    OpenLoop.status == "open",
                    OpenLoop.context_pack_id.not_in(pack_ids),
                )
            ))
            for loop in older:
                loop.status = "superseded"
                loop.closed_at = now
                loop.resolution_reason = "Superseded by a newer context pack for this focus."
        await self.session.flush()
        return persisted

    async def list(
        self,
        *,
        workspace_id: UUID,
        include_closed: bool = True,
    ) -> list[OpenLoop]:
        stmt = select(OpenLoop).where(OpenLoop.workspace_id == workspace_id)
        if not include_closed:
            stmt = stmt.where(OpenLoop.status == "open")
        return list(await self.session.scalars(
            stmt.order_by(OpenLoop.last_seen_at.desc(), OpenLoop.created_at.desc()).limit(200)
        ))

    async def apply_action(
        self,
        *,
        workspace_id: UUID,
        loop_id: UUID,
        action: str,
        reason: str,
        assignee: str | None = None,
    ) -> OpenLoop:
        normalized_action = str(action or "").strip().lower()
        normalized_reason = " ".join(str(reason or "").split())
        normalized_assignee = " ".join(str(assignee or "").split()) or None
        if normalized_action not in {"dismiss", "resolve", "reopen", "assign"}:
            raise OpenLoopActionError("action must be dismiss, resolve, reopen, or assign")
        if not normalized_reason:
            raise OpenLoopActionError("reason is required")
        if normalized_action == "assign" and not normalized_assignee:
            raise OpenLoopActionError("assignee is required for assign")
        loop = await self.session.scalar(
            select(OpenLoop).where(
                OpenLoop.id == loop_id,
                OpenLoop.workspace_id == workspace_id,
            ).with_for_update()
        )
        if loop is None:
            raise OpenLoopNotFoundError("open loop was not found")

        before = loop.status
        if normalized_action == "dismiss":
            loop.status = "dismissed"
        elif normalized_action == "resolve":
            loop.status = "resolved"
        elif normalized_action == "reopen":
            loop.status = "open"
        else:
            loop.assigned_to = normalized_assignee
        now = utc_now()
        if loop.status in CLOSED_STATES:
            loop.closed_at = now
        elif normalized_action == "reopen":
            loop.closed_at = None
        loop.resolution_reason = normalized_reason
        evidence = await ingest_source_document_revision(
            self.session,
            workspace_id=workspace_id,
            source_type="human_open_loop_action",
            external_id=(
                f"open-loop:{loop.id}:{normalized_action}:"
                f"{hashlib.sha256(normalized_reason.encode()).hexdigest()}"
            ),
            content=(
                f"Open loop action: {normalized_action}\n"
                f"Previous status: {before}\nCurrent status: {loop.status}\n"
                f"Assignee: {normalized_assignee or loop.assigned_to or 'unassigned'}\n"
                f"Reason: {normalized_reason}"
            ),
            author="human",
            metadata_json={
                "open_loop_id": str(loop.id),
                "action": normalized_action,
                "reason": normalized_reason,
                "assignee": normalized_assignee,
            },
            source_created_at=now,
            trust_zone="trusted_human",
        )
        loop.resolution_source_document_id = evidence.document.id
        await self.session.flush()
        return loop

    async def _upsert_finding(
        self,
        workspace_id: UUID,
        finding: dict[str, Any],
        now: datetime,
    ) -> OpenLoop:
        natural_key = str(finding.get("id") or "")
        if not natural_key:
            raise ValueError("supported finding is missing its deterministic id")
        existing = await self.session.scalar(
            select(OpenLoop).where(OpenLoop.natural_key == natural_key).with_for_update()
        )
        if existing is not None:
            if existing.workspace_id != workspace_id:
                raise ValueError("open-loop identity crossed workspace scope")
            existing.last_seen_at = now
            existing.severity = str(finding.get("severity") or existing.severity)
            existing.title = str(finding.get("title") or existing.title)
            existing.explanation = str(finding.get("explanation") or existing.explanation)
            existing.next_action = _text_or_none(finding.get("next_action"))
            existing.sources_json = _json(finding.get("sources") or [])
            return existing

        loop = OpenLoop(
            id=uuid4(),
            workspace_id=workspace_id,
            natural_key=natural_key,
            rule_id=str(finding["rule_id"]),
            rule_version=int(finding.get("rule_version") or 1),
            status="open",
            severity=str(finding.get("severity") or "warning"),
            title=str(finding.get("title") or "Project attention required"),
            explanation=str(finding.get("explanation") or ""),
            next_action=_text_or_none(finding.get("next_action")),
            context_pack_id=_uuid(finding.get("context_pack_id")),
            run_id=_uuid(finding.get("run_id")),
            focus_component_id=_uuid(finding.get("focus_component_id")),
            trigger_ids_json=_json(finding.get("trigger_ids") or []),
            sources_json=_json(finding.get("sources") or []),
            first_seen_at=now,
            last_seen_at=now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(loop)
                await self.session.flush()
            return loop
        except IntegrityError:
            existing = await self.session.scalar(
                select(OpenLoop).where(OpenLoop.natural_key == natural_key)
            )
            if existing is None:
                raise
            existing.last_seen_at = now
            return existing


def open_loop_to_dict(loop: OpenLoop) -> dict[str, Any]:
    return {
        "id": str(loop.id),
        "natural_key": loop.natural_key,
        "rule_id": loop.rule_id,
        "rule_version": loop.rule_version,
        "status": loop.status,
        "severity": loop.severity,
        "title": loop.title,
        "explanation": loop.explanation,
        "next_action": loop.next_action,
        "context_pack_id": str(loop.context_pack_id) if loop.context_pack_id else None,
        "run_id": str(loop.run_id) if loop.run_id else None,
        "focus_component_id": str(loop.focus_component_id) if loop.focus_component_id else None,
        "trigger_ids": _json_list(loop.trigger_ids_json),
        "sources": _json_list(loop.sources_json),
        "assigned_to": loop.assigned_to,
        "resolution_reason": loop.resolution_reason,
        "resolution_source_document_id": (
            str(loop.resolution_source_document_id)
            if loop.resolution_source_document_id else None
        ),
        "first_seen_at": _iso(loop.first_seen_at),
        "last_seen_at": _iso(loop.last_seen_at),
        "closed_at": _iso(loop.closed_at),
    }


def _uuid(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_list(value: str | None) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _text_or_none(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _latest_resolution_source_id(timeline: dict[str, Any]) -> UUID | None:
    events = [
        event
        for run in timeline.get("runs") or []
        for event in run.get("events") or []
        if event.get("event_type") in {"verification", "blocker_resolution", "outcome"}
        and event.get("source_document_id")
    ]
    if not events:
        return None
    events.sort(key=lambda item: str(item.get("observed_at") or ""))
    return _uuid(events[-1].get("source_document_id"))
