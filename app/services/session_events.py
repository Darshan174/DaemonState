from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent, SourceDocument
from app.services.redaction import redact_sensitive, redact_sensitive_text


MAX_EVENT_CONTENT_CHARS = 24_000
MAX_PAYLOAD_STRING_CHARS = 24_000
MAX_PAYLOAD_LIST_ITEMS = 200


@dataclass(frozen=True)
class NormalizedSessionEvent:
    provider_event_id: str
    sequence_number: int
    event_type: str
    role: str | None = None
    occurred_at: str | datetime | None = None
    content: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    source_cursor: int | None = None


async def persist_session_events(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    source_document: SourceDocument,
    provider: str,
    session_id: str,
    events: Iterable[NormalizedSessionEvent],
) -> dict[str, int]:
    """Persist new normalized events without rewriting earlier event evidence."""

    materialized = list(events)
    if not materialized:
        return {"created": 0, "unchanged": 0}

    existing = set(await session.scalars(
        select(SessionEvent.provider_event_id).where(
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.provider == provider,
            SessionEvent.session_id == session_id,
        )
    ))
    created = 0
    unchanged = 0
    seen: set[str] = set()
    for raw in sorted(materialized, key=lambda item: item.sequence_number):
        event_id = str(raw.provider_event_id or "").strip()
        if not event_id or event_id in seen or event_id in existing:
            unchanged += 1
            continue
        seen.add(event_id)
        content = _bounded_text(redact_sensitive_text(raw.content), MAX_EVENT_CONTENT_CHARS)
        payload = _sanitize_payload(raw.payload)
        canonical = _canonical_json({
            "provider_event_id": event_id,
            "sequence_number": int(raw.sequence_number),
            "event_type": str(raw.event_type),
            "role": raw.role,
            "occurred_at": _datetime_iso(_coerce_datetime(raw.occurred_at)),
            "content": content,
            "payload": payload,
            "source_cursor": raw.source_cursor,
        })
        session.add(SessionEvent(
            workspace_id=workspace_id,
            source_document_id=source_document.id,
            provider=provider,
            session_id=session_id,
            provider_event_id=event_id,
            sequence_number=int(raw.sequence_number),
            event_type=str(raw.event_type),
            role=str(raw.role) if raw.role else None,
            occurred_at=_coerce_datetime(raw.occurred_at),
            content=content,
            payload_json=_canonical_json(payload),
            source_cursor=raw.source_cursor,
            content_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ))
        created += 1
    await session.flush()
    return {"created": created, "unchanged": unchanged}


def event_payload(event: SessionEvent) -> dict[str, Any]:
    try:
        value = json.loads(event.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sanitize_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    value = redact_sensitive(value)
    if isinstance(value, dict):
        return {
            str(key): _sanitize_payload(child, depth=depth + 1)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        items = value[:MAX_PAYLOAD_LIST_ITEMS]
        sanitized = [_sanitize_payload(child, depth=depth + 1) for child in items]
        if len(value) > len(items):
            sanitized.append(f"[truncated {len(value) - len(items)} items]")
        return sanitized
    if isinstance(value, tuple):
        return _sanitize_payload(list(value), depth=depth)
    if isinstance(value, str):
        return _bounded_text(value, MAX_PAYLOAD_STRING_CHARS)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bounded_text(str(value), MAX_PAYLOAD_STRING_CHARS)


def _bounded_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return f"{value[: limit - 24]}\n[output truncated]"


def _coerce_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _datetime_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
