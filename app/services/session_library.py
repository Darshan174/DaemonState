from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connector, SourceDocument, Workspace
from app.services.ingest import IngestionService
from app.services.session_summary import derive_session_topic, derive_session_topics
from app.services.workspace_scope import current_source_documents
from app.sync.ai_session import ingest_ai_session
from app.sync.session_resolvers import discover_local_ai_sessions
from app.time import utc_now


SESSION_CONNECTOR_TYPES = ("codex", "claude", "opencode")
HARNESS_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "opencode": "OpenCode",
}


async def sync_local_session_library(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    connector_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Discover and incrementally ingest local sessions without manual IDs/uploads."""

    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")

    requested = tuple(dict.fromkeys(
        value.strip().lower()
        for value in (connector_types or SESSION_CONNECTOR_TYPES)
        if value and value.strip().lower() in SESSION_CONNECTOR_TYPES
    ))
    discovery = discover_local_ai_sessions(requested)
    existing_documents = list(await session.scalars(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.source_type == "agent_session",
        )
    ))
    existing_current, _ = current_source_documents(existing_documents)
    current_by_external_id = {document.external_id: document for document in existing_current}
    provider_results: list[dict[str, Any]] = []
    totals = {
        "discovered": 0,
        "imported": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
    }

    for result in discovery:
        connector = await _get_or_create_connector(session, workspace_id, result.connector_type)
        config = _loads_dict(connector.config_json)
        config.update({
            "automatic_discovery": True,
            "adapter_state": "unavailable" if result.error else "ready",
            "adapter_message": result.error or "Local session history detected.",
            "last_discovery_at": utc_now().isoformat(),
            "discovered_sessions": len(result.sessions),
        })

        provider_summary = {
            "connector_type": result.connector_type,
            "name": HARNESS_LABELS[result.connector_type],
            "available": result.error is None,
            "discovered": len(result.sessions),
            "imported": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "error": result.error,
        }
        totals["discovered"] += len(result.sessions)

        if result.error:
            connector.status = "disconnected"
            connector.config_json = json.dumps(config)
            provider_results.append(provider_summary)
            continue

        for resolved in result.sessions:
            try:
                external_id = f"{result.connector_type}:session:{resolved.session_id}"
                existing = current_by_external_id.get(external_id)
                if existing is not None and existing.content.strip() == resolved.content.strip():
                    provider_summary["unchanged"] += 1
                    totals["unchanged"] += 1
                    continue
                ingest_result = await ingest_ai_session(
                    result.connector_type,
                    session,
                    resolved.session_id,
                    resolved.content,
                    workspace_id=str(workspace_id),
                    metadata_extra=resolved.metadata,
                )
                revised = int(ingest_result.get("documents_updated") or 0)
                created = max(
                    int(ingest_result.get("documents_persisted") or 0) - revised,
                    0,
                )
                unchanged = int(
                    ingest_result.get("documents_skipped")
                    or ingest_result.get("unchanged")
                    or 0
                )
                provider_summary["imported"] += created
                provider_summary["updated"] += revised
                provider_summary["unchanged"] += unchanged
                totals["imported"] += created
                totals["updated"] += revised
                totals["unchanged"] += unchanged

                if created or revised:
                    document = await session.get(
                        SourceDocument,
                        UUID(str(ingest_result["document_id"])),
                    )
                    if document is not None and document.processed_at is None:
                        await IngestionService(session).process_document(document.id)
                        await session.commit()
                    if document is not None:
                        current_by_external_id[external_id] = document
            except Exception as exc:  # one corrupt session must not block the library
                provider_summary["failed"] += 1
                totals["failed"] += 1
                provider_summary.setdefault("session_errors", []).append({
                    "session_id": resolved.session_id,
                    "message": str(exc),
                })

        connector.status = "connected"
        connector.last_sync_at = utc_now()
        config["items_synced"] = len(result.sessions) - provider_summary["failed"]
        config["last_sync_summary"] = {
            key: provider_summary[key]
            for key in ("discovered", "imported", "updated", "unchanged", "failed")
        }
        connector.config_json = json.dumps(config)
        provider_results.append(provider_summary)

    await session.commit()
    return {
        "workspace_id": str(workspace_id),
        "automatic": True,
        "synced_at": utc_now().isoformat(),
        **totals,
        "providers": provider_results,
    }


async def build_session_library(
    session: AsyncSession,
    workspace_id: UUID,
) -> dict[str, Any]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")

    documents = list(await session.scalars(
        select(SourceDocument)
        .where(
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.source_type == "agent_session",
        )
        .order_by(SourceDocument.ingested_at.desc(), SourceDocument.id.desc())
    ))
    current, _ = current_source_documents(documents)

    sessions = [_session_entry(document) for document in current]
    sessions.sort(key=lambda item: item["updated_at"] or "", reverse=True)

    topic_sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    topic_labels: dict[str, str] = {}
    for item in sessions:
        for topic in item["topics"]:
            key = _topic_key(topic)
            if not key:
                continue
            topic_labels.setdefault(key, topic)
            topic_sessions[key].append(item)

    topics = []
    for key, linked in topic_sessions.items():
        topics.append({
            "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "name": topic_labels[key],
            "session_count": len(linked),
            "harnesses": sorted({item["connector_type"] for item in linked}),
            "session_ids": [item["session_id"] for item in linked],
            "last_discussed_at": max(item["updated_at"] or "" for item in linked) or None,
        })
    topics.sort(
        key=lambda item: (item["session_count"], item["last_discussed_at"] or ""),
        reverse=True,
    )

    connector_rows = list(await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type.in_(SESSION_CONNECTOR_TYPES),
        )
    ))
    connectors = {row.connector_type: row for row in connector_rows}
    harnesses = []
    for connector_type in SESSION_CONNECTOR_TYPES:
        connector = connectors.get(connector_type)
        config = _loads_dict(connector.config_json if connector else "{}")
        harnesses.append({
            "connector_type": connector_type,
            "name": HARNESS_LABELS[connector_type],
            "status": connector.status if connector else "not_scanned",
            "adapter_state": config.get("adapter_state", "not_scanned"),
            "message": config.get(
                "adapter_message",
                "The local adapter has not scanned this harness yet.",
            ),
            "session_count": sum(
                1 for item in sessions if item["connector_type"] == connector_type
            ),
            "last_sync_at": _datetime_iso(connector.last_sync_at) if connector else None,
        })

    return {
        "workspace_id": str(workspace_id),
        "generated_at": utc_now().isoformat(),
        "stats": {
            "sessions": len(sessions),
            "topics": len(topics),
            "harnesses": sum(1 for item in harnesses if item["adapter_state"] == "ready"),
            "live_sessions": sum(1 for item in sessions if item["live"]),
        },
        "harnesses": harnesses,
        "topics": topics,
        "sessions": sessions,
    }


async def _get_or_create_connector(
    session: AsyncSession,
    workspace_id: UUID,
    connector_type: str,
) -> Connector:
    connector = await session.scalar(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type == connector_type,
        )
    )
    if connector is None:
        connector = Connector(
            workspace_id=workspace_id,
            connector_type=connector_type,
            status="disconnected",
        )
        session.add(connector)
        await session.flush()
    return connector


def _session_entry(document: SourceDocument) -> dict[str, Any]:
    metadata = _loads_dict(document.metadata_json)
    connector_type = str(
        metadata.get("connector_type") or metadata.get("tool") or "unknown"
    ).strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    session_id = str(metadata.get("session_id") or document.external_id.rsplit(":", 1)[-1])
    title = derive_session_topic(
        document.content,
        explicit_title=metadata.get("title"),
        tool=connector_type,
        session_id=session_id,
    ) or "Untitled session"
    topics = derive_session_topics(
        document.content,
        explicit_title=title,
        cwd=metadata.get("cwd"),
        tool=connector_type,
        session_id=session_id,
    )
    updated_at = (
        metadata.get("ended_at")
        or metadata.get("source_modified_at")
        or metadata.get("started_at")
        or _datetime_iso(document.ingested_at)
    )
    return {
        "id": f"{connector_type}:{session_id}",
        "session_id": session_id,
        "source_document_id": str(document.id),
        "connector_type": connector_type,
        "harness": HARNESS_LABELS.get(connector_type, connector_type.title()),
        "title": title,
        "topics": topics or ([] if title == "Untitled session" else [title]),
        "model": metadata.get("model"),
        "cwd": metadata.get("cwd"),
        "branch": metadata.get("branch"),
        "message_count": int(metadata.get("message_count") or 0),
        "started_at": metadata.get("started_at"),
        "updated_at": updated_at,
        "ingested_at": _datetime_iso(document.ingested_at),
        "revision_number": int(document.revision_number or 1),
        "live": bool(metadata.get("source_path")),
        "provenance": {
            "external_id": document.external_id,
            "source_type": document.source_type,
            "linked_to_local_history": bool(metadata.get("source_path")),
        },
        "preview": _session_preview(document.content),
    }


def _session_preview(content: str, limit: int = 180) -> str:
    blocks = re.findall(
        r"(?ms)^\[(?:USER|HUMAN|YOU)\]\s*(.*?)(?=^\[[A-Z_ -]+\]\s*|\Z)",
        content or "",
    )
    noise_markers = (
        "request_user_input availability",
        "<skills_instructions>",
        "<permissions instructions>",
        "# agents.md instructions",
        "the following is the codex agent history",
        "at the start of your turn",
        "all agents in the team",
        "child agents can also spawn",
        "they may be addressed as to=/root",
        "permanent repository rules for codex",
    )
    value = next(
        (
            item for item in blocks
            if item.strip() and not any(marker in item.lower() for marker in noise_markers)
        ),
        "",
    )
    if not value:
        value = next((topic for topic in derive_session_topics(content) if topic), "")
    clean = re.sub(r"\s+", " ", value).strip()
    return clean if len(clean) <= limit else f"{clean[: limit - 1].rstrip()}…"


def _loads_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        loaded = json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _topic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _datetime_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
