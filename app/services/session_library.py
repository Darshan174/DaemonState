from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models import Connector, SourceDocument, Workspace
from app.services.access import AccessScope, source_access_predicate
from app.services.ingest import IngestionService
from app.services.session_checkpoints import list_session_checkpoints
from app.services.session_scope import (
    enrich_session_scope_metadata,
    scoped_session_documents,
    workspace_session_scope,
)
from app.services.session_summary import (
    SESSION_LIBRARY_SUMMARY_VERSION,
    build_session_library_summary,
    is_internal_session_content,
)
from app.services.workspace_scope import current_source_documents
from app.sync.ai_session import ingest_ai_session
from app.sync.session_resolvers import discover_local_ai_sessions
from app.time import utc_now


SESSION_CONNECTOR_TYPES = ("codex", "claude", "opencode")
SESSION_SELECTION_KEYS = (
    "selected_session_external_id",
    "selected_session_id",
    "selected_session_topic",
    "selected_session_at",
    "selected_session_by",
)
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
    commit: bool = True,
) -> dict[str, Any]:
    """Discover and incrementally ingest local sessions without manual IDs/uploads."""

    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")
    if workspace.kind == "demo":
        return {
            "workspace_id": str(workspace_id),
            "automatic": True,
            "skipped_reason": "sample_workspace",
            "synced_at": utc_now().isoformat(),
            "discovered": 0,
            "imported": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "providers": [],
        }

    requested = tuple(dict.fromkeys(
        value.strip().lower()
        for value in (connector_types or SESSION_CONNECTOR_TYPES)
        if value and value.strip().lower() in SESSION_CONNECTOR_TYPES
    ))
    project_scope = await workspace_session_scope(session, workspace_id)
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
        "scanned": 0,
        "discovered": 0,
        "excluded": 0,
        "imported": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
    }

    for result in discovery:
        scanned_sessions = []
        for item in result.sessions:
            item.metadata = enrich_session_scope_metadata(item.metadata, item.events)
            library_summary = build_session_library_summary(
                item.content,
                explicit_title=item.metadata.get("title"),
                cwd=item.metadata.get("cwd"),
                tool=result.connector_type,
                session_id=item.session_id,
            )
            library_summary["compaction_checkpoints"] = list_session_checkpoints(
                item.content,
                item.metadata,
                session_title=str(library_summary["title"]),
            )
            item.metadata["session_library_summary"] = library_summary
            if not library_summary["internal"]:
                scanned_sessions.append(item)
        user_sessions = [
            item
            for item in scanned_sessions
            if project_scope.matches_metadata(
                item.metadata,
                provider=result.connector_type,
                session_id=item.session_id,
            )
        ]
        connector = await _get_or_create_connector(session, workspace_id, result.connector_type)
        config = _loads_dict(connector.config_json)
        config.update({
            "automatic_discovery": True,
            "adapter_state": "unavailable" if result.error else "ready",
            "adapter_message": result.error or "Local session history detected.",
            "last_discovery_at": utc_now().isoformat(),
            "discovered_sessions": len(user_sessions),
            "scanned_sessions": len(scanned_sessions),
            "excluded_outside_project": len(scanned_sessions) - len(user_sessions),
        })
        config["session_lineage"] = {
            item.session_id: {
                "forked_from_session_id": item.metadata.get("forked_from_session_id"),
                "forked_from_title": item.metadata.get("forked_from_title"),
            }
            for item in user_sessions
            if item.metadata.get("forked_from_session_id")
        }

        provider_summary = {
            "connector_type": result.connector_type,
            "name": HARNESS_LABELS[result.connector_type],
            "available": result.error is None,
            "scanned": len(scanned_sessions),
            "discovered": len(user_sessions),
            "excluded": len(scanned_sessions) - len(user_sessions),
            "imported": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "error": result.error,
        }
        totals["scanned"] += len(scanned_sessions)
        totals["discovered"] += len(user_sessions)
        totals["excluded"] += len(scanned_sessions) - len(user_sessions)

        if result.error:
            connector.status = "disconnected"
            connector.config_json = json.dumps(config)
            provider_results.append(provider_summary)
            continue

        for resolved in user_sessions:
            try:
                external_id = f"{result.connector_type}:session:{resolved.session_id}"
                existing = current_by_external_id.get(external_id)
                if (
                    existing is not None
                    and existing.content.strip() == resolved.content.strip()
                    and not resolved.events
                ):
                    current_metadata = _loads_dict(existing.metadata_json)
                    refreshed_metadata = {
                        **current_metadata,
                        **{
                            key: value
                            for key, value in resolved.metadata.items()
                            if value not in (None, "", [])
                        },
                        "connector_type": result.connector_type,
                        "tool": result.connector_type,
                        "session_id": resolved.session_id,
                    }
                    if refreshed_metadata != current_metadata:
                        existing.metadata_json = json.dumps(refreshed_metadata)
                        await session.flush()
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
                    normalized_events=resolved.events,
                    commit=commit,
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
                        if commit:
                            await session.commit()
                        else:
                            await session.flush()
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
        config["items_synced"] = len(user_sessions) - provider_summary["failed"]
        config["last_sync_summary"] = {
            key: provider_summary[key]
            for key in (
                "scanned",
                "discovered",
                "excluded",
                "imported",
                "updated",
                "unchanged",
                "failed",
            )
        }
        # A library selection can be saved while a long local scan is running.
        # Reload only the config column and preserve that later user choice.
        await session.refresh(connector, attribute_names=["config_json"])
        latest_config = _loads_dict(connector.config_json)
        for key in SESSION_SELECTION_KEYS:
            if key in latest_config:
                config[key] = latest_config[key]
        connector.config_json = json.dumps(config)
        provider_results.append(provider_summary)

    if commit:
        await session.commit()
    else:
        await session.flush()
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
    *,
    access_scope: AccessScope | None = None,
) -> dict[str, Any]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")

    active_access_scope = access_scope or AccessScope.local()
    documents = [] if workspace.kind == "demo" else list(await session.scalars(
        select(SourceDocument)
        .options(defer(SourceDocument.content, raiseload=True))
        .where(
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.source_type == "agent_session",
            source_access_predicate(active_access_scope, workspace_id=workspace_id),
        )
        .order_by(SourceDocument.ingested_at.desc(), SourceDocument.id.desc())
    ))
    current, _ = current_source_documents(documents)
    current = await scoped_session_documents(session, workspace_id, current)

    summaries = {
        document.id: _session_library_summary(document)
        for document in current
    }
    legacy_ids = {
        document.id
        for document in current
        if summaries[document.id] is None
    }
    legacy_contents = (
        await _load_legacy_session_contents(session, legacy_ids)
        if legacy_ids
        else {}
    )
    sessions = []
    for document in current:
        summary = summaries[document.id]
        content = legacy_contents.get(document.id)
        if summary is not None:
            if summary["internal"]:
                continue
        elif is_internal_session_content(content):
            continue
        sessions.append(
            _session_entry(
                document,
                content=content,
                summary=summary,
            )
        )
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
    connector_configs = {
        connector_type: _loads_dict(row.config_json)
        for connector_type, row in connectors.items()
    }
    sessions_by_provider_id = {
        (item["connector_type"], item["session_id"]): item
        for item in sessions
    }
    for item in sessions:
        lineage = connector_configs.get(item["connector_type"], {}).get(
            "session_lineage", {}
        )
        relation = lineage.get(item["session_id"], {}) if isinstance(lineage, dict) else {}
        if not isinstance(relation, dict):
            relation = {"forked_from_session_id": relation}
        parent_session_id = str(
            relation.get("forked_from_session_id")
            or item.get("forked_from_session_id")
            or ""
        ).strip()
        if not parent_session_id:
            item["forked_from"] = None
            continue
        parent = sessions_by_provider_id.get(
            (item["connector_type"], parent_session_id)
        )
        item["forked_from"] = {
            "session_id": parent_session_id,
            "title": (
                parent["title"] if parent
                else relation.get("forked_from_title")
                or item.get("forked_from_title")
                or "Earlier task"
            ),
            "source_document_id": parent["source_document_id"] if parent else None,
        }
    selection_reference = _selected_session_reference(connector_rows)
    selected_external_id = selection_reference.get("external_id")
    selected_session = next(
        (
            item for item in sessions
            if item["provenance"]["external_id"] == selected_external_id
        ),
        None,
    )
    for item in sessions:
        item["selected_for_now"] = bool(
            selected_session
            and item["source_document_id"] == selected_session["source_document_id"]
        )
        item["selected_topic"] = (
            selection_reference.get("topic") if item["selected_for_now"] else None
        )
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
        "selection": ({
            "source_document_id": selected_session["source_document_id"],
            "session_id": selected_session["session_id"],
            "title": selected_session["title"],
            "harness": selected_session["harness"],
            "topic": selection_reference.get("topic"),
        } if selected_session else None),
        "stats": {
            "sessions": len(sessions),
            "topics": len(topics),
            "harnesses": sum(1 for item in harnesses if item["adapter_state"] == "ready"),
            "live_sessions": sum(1 for item in sessions if item["live"]),
            "checkpoints": sum(
                len(item.get("compaction_checkpoints") or []) for item in sessions
            ),
        },
        "harnesses": harnesses,
        "topics": topics,
        "sessions": sessions,
    }


async def select_session_for_now(
    session: AsyncSession,
    workspace_id: UUID,
    document: SourceDocument,
    *,
    topic: str | None,
    selected_by: str,
) -> dict[str, Any]:
    """Persist one explicit session-topic choice without mutating evidence."""

    connector_type = _connector_type_for_document(document)
    if connector_type not in SESSION_CONNECTOR_TYPES:
        raise ValueError("Session harness is not supported")
    selected_topic = _matching_session_topic(document, topic)
    if selected_topic is None:
        raise ValueError("Selected topic does not belong to this session")

    connector_rows = list(await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type.in_(SESSION_CONNECTOR_TYPES),
        ).with_for_update()
    ))
    target = next(
        (row for row in connector_rows if row.connector_type == connector_type),
        None,
    )
    if target is None:
        target = await _get_or_create_connector(session, workspace_id, connector_type)
        connector_rows.append(target)

    for connector in connector_rows:
        config = _loads_dict(connector.config_json)
        for key in SESSION_SELECTION_KEYS:
            config.pop(key, None)
        if connector is target:
            metadata = _loads_dict(document.metadata_json)
            config.update({
                "selected_session_external_id": document.external_id,
                "selected_session_id": str(
                    metadata.get("session_id")
                    or document.external_id.rsplit(":", 1)[-1]
                ),
                "selected_session_topic": selected_topic,
                "selected_session_at": utc_now().isoformat(),
                "selected_session_by": selected_by,
            })
        connector.config_json = json.dumps(config)

    await session.flush()
    return {
        "source_document_id": str(document.id),
        "external_id": document.external_id,
        "connector_type": connector_type,
        "topic": selected_topic,
    }


async def clear_session_selection(
    session: AsyncSession,
    workspace_id: UUID,
) -> dict[str, bool]:
    """Remove the explicit Now pin while preserving imported session evidence."""

    connector_rows = list(await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type.in_(SESSION_CONNECTOR_TYPES),
        ).with_for_update()
    ))
    cleared = False
    for connector in connector_rows:
        config = _loads_dict(connector.config_json)
        connector_changed = False
        for key in SESSION_SELECTION_KEYS:
            if key in config:
                config.pop(key, None)
                connector_changed = True
        if connector_changed:
            connector.config_json = json.dumps(config)
            cleared = True

    await session.flush()
    return {"cleared": cleared}


async def selected_session_selection(
    session: AsyncSession,
    workspace_id: UUID | None,
) -> dict[str, str | None]:
    if workspace_id is None:
        return {"external_id": None, "topic": None}
    connectors = list(await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_id,
            Connector.connector_type.in_(SESSION_CONNECTOR_TYPES),
        )
    ))
    return _selected_session_reference(connectors)


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


async def _load_legacy_session_contents(
    session: AsyncSession,
    document_ids: set[UUID],
) -> dict[UUID, str]:
    if not document_ids:
        return {}
    rows = await session.execute(
        select(SourceDocument.id, SourceDocument.content).where(
            SourceDocument.id.in_(document_ids)
        )
    )
    return {document_id: content for document_id, content in rows}


def _session_library_summary(
    document: SourceDocument,
) -> dict[str, Any] | None:
    metadata = _loads_dict(document.metadata_json)
    raw = metadata.get("session_library_summary")
    try:
        schema_version = (
            int(raw.get("schema_version") or 0)
            if isinstance(raw, dict)
            else 0
        )
    except (TypeError, ValueError):
        schema_version = 0
    if isinstance(raw, dict) and schema_version == SESSION_LIBRARY_SUMMARY_VERSION:
        checkpoints = raw.get("compaction_checkpoints")
        if (
            document.content_sha256
            and raw.get("content_sha256") == document.content_sha256
            and isinstance(raw.get("internal"), bool)
            and isinstance(raw.get("title"), str)
            and isinstance(raw.get("topics"), list)
            and all(isinstance(item, str) for item in raw["topics"])
            and (
                raw.get("latest_topic") is None
                or isinstance(raw.get("latest_topic"), str)
            )
            and isinstance(raw.get("preview"), str)
            and isinstance(checkpoints, list)
            and all(isinstance(item, dict) for item in checkpoints)
        ):
            return {
                "internal": raw["internal"],
                "title": raw["title"],
                "topics": list(raw["topics"]),
                "latest_topic": raw.get("latest_topic"),
                "preview": raw["preview"],
                "compaction_checkpoints": [
                    dict(item) for item in checkpoints
                ],
            }

    # Sessions imported before summary metadata was introduced already carry
    # resolver-derived title/topics/checkpoint descriptors. They are safe to
    # render without the transcript; the exact transcript remains available to
    # detail and checkpoint-restore endpoints. Ambiguous hand-authored legacy
    # rows still take the content fallback below.
    title = metadata.get("title")
    topics = metadata.get("topics")
    source_path = str(metadata.get("source_path") or "").strip()
    if (
        not source_path
        or not isinstance(title, str)
        or not title.strip()
        or not isinstance(topics, list)
        or not topics
        or not all(isinstance(item, str) and item.strip() for item in topics)
    ):
        return None
    normalized_topics = [item.strip() for item in topics]
    summary_text = " ".join([title, *normalized_topics]).lower()
    internal = (
        "the following is the codex agent history whose request action you are assessing"
        in summary_text
        and "transcript start" in summary_text
    )
    latest_topic = metadata.get("latest_topic")
    if not isinstance(latest_topic, str) or not latest_topic.strip():
        latest_topic = normalized_topics[-1]
    preview = metadata.get("preview")
    if not isinstance(preview, str) or not preview.strip():
        preview = title.strip()
    return {
        "internal": internal,
        "title": title.strip(),
        "topics": normalized_topics,
        "latest_topic": latest_topic.strip(),
        "preview": preview.strip(),
        "compaction_checkpoints": None,
    }


def _session_entry(
    document: SourceDocument,
    *,
    content: str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = _loads_dict(document.metadata_json)
    connector_type = str(
        metadata.get("connector_type") or metadata.get("tool") or "unknown"
    ).strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    session_id = str(metadata.get("session_id") or document.external_id.rsplit(":", 1)[-1])
    resolved_summary = summary or _session_library_summary(document)
    transcript = content
    if resolved_summary is None:
        transcript = document.content if content is None else content
        resolved_summary = build_session_library_summary(
            transcript,
            explicit_title=metadata.get("title"),
            cwd=metadata.get("cwd"),
            tool=connector_type,
            session_id=session_id,
        )
    title = str(resolved_summary["title"])
    topics = list(resolved_summary["topics"])
    latest_topic = resolved_summary.get("latest_topic")
    persisted_checkpoints = resolved_summary.get("compaction_checkpoints")
    compaction_checkpoints = (
        [dict(item) for item in persisted_checkpoints]
        if isinstance(persisted_checkpoints, list)
        else list_session_checkpoints(
            transcript or "",
            metadata,
            session_title=title,
        )
    )
    updated_at = _latest_datetime_iso(
        metadata.get("updated_at"),
        metadata.get("ended_at"),
        metadata.get("source_modified_at"),
        metadata.get("started_at"),
    ) or _latest_datetime_iso(metadata.get("ingested_at"), document.ingested_at)
    return {
        "id": f"{connector_type}:{session_id}",
        "session_id": session_id,
        "source_document_id": str(document.id),
        "connector_type": connector_type,
        "harness": HARNESS_LABELS.get(connector_type, connector_type.title()),
        "title": title,
        "topics": topics or ([] if title == "Untitled session" else [title]),
        "latest_topic": latest_topic or (None if title == "Untitled session" else title),
        "model": metadata.get("model"),
        "cwd": metadata.get("cwd"),
        "branch": metadata.get("branch"),
        "forked_from_session_id": metadata.get("forked_from_session_id"),
        "forked_from_title": metadata.get("forked_from_title"),
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
        "preview": resolved_summary["preview"],
        "compaction_checkpoints": compaction_checkpoints,
    }


def _selected_session_reference(
    connectors: Iterable[Connector],
) -> dict[str, str | None]:
    for connector in connectors:
        config = _loads_dict(connector.config_json)
        external_id = str(
            config.get("selected_session_external_id")
            or ""
        ).strip()
        if external_id:
            return {
                "external_id": external_id,
                "topic": str(config.get("selected_session_topic") or "").strip() or None,
            }
    return {"external_id": None, "topic": None}


def _matching_session_topic(
    document: SourceDocument,
    requested_topic: str | None,
) -> str | None:
    entry = _session_entry(document)
    if requested_topic is None:
        return entry.get("latest_topic") or next(iter(entry["topics"]), None)
    requested_key = _topic_key(requested_topic)
    if not requested_key:
        return None
    return next(
        (topic for topic in entry["topics"] if _topic_key(topic) == requested_key),
        None,
    )


def _connector_type_for_document(document: SourceDocument) -> str:
    metadata = _loads_dict(document.metadata_json)
    connector_type = str(
        metadata.get("connector_type")
        or metadata.get("tool")
        or document.external_id.split(":", 1)[0]
        or ""
    ).strip().lower()
    return "claude" if connector_type == "claude_code" else connector_type


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


def _latest_datetime_iso(*values: object) -> str | None:
    parsed: list[datetime] = []
    for value in values:
        candidate: datetime | None = None
        if isinstance(value, datetime):
            candidate = value
        elif isinstance(value, str) and value.strip():
            try:
                candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        if candidate is None:
            continue
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=timezone.utc)
        else:
            candidate = candidate.astimezone(timezone.utc)
        parsed.append(candidate)
    return max(parsed).isoformat() if parsed else None
