from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Connector, SourceDocument, Workspace


LEGACY_UNSCOPED_SOURCE_TYPES = {"local", "local_folder", "browser_upload", "paste"}


def normalize_workspace_id(workspace_id: str | UUID) -> tuple[str, UUID]:
    workspace_uuid = workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
    return str(workspace_uuid), workspace_uuid


async def workspace_connector_types(
    session: AsyncSession,
    workspace_id: str | UUID,
) -> tuple[str, set[str]]:
    workspace_id_str, workspace_uuid = normalize_workspace_id(workspace_id)
    connector_types = set(await session.scalars(
        select(Connector.connector_type).where(Connector.workspace_id == workspace_uuid)
    ))
    return workspace_id_str, connector_types


async def workspace_scope_exists(
    session: AsyncSession,
    workspace_id: str | UUID,
) -> bool:
    """Recognize persisted workspaces and explicit legacy workspace assignments."""
    workspace_id_str, workspace_uuid = normalize_workspace_id(workspace_id)
    if await session.get(Workspace, workspace_uuid) is not None:
        return True
    documents = list(await session.scalars(select(SourceDocument)))
    return any(
        source_explicitly_matches_workspace(document, workspace_id_str)
        for document in documents
    )


def metadata_dict(doc: SourceDocument) -> dict:
    md = doc.metadata_json
    if isinstance(md, dict):
        return md
    if isinstance(md, str):
        try:
            parsed = json.loads(md)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def source_matches_workspace(
    doc: SourceDocument,
    workspace_id: str,
    connector_types: set[str],
) -> bool:
    explicit_workspace_id = getattr(doc, "workspace_id", None)
    if explicit_workspace_id:
        return workspace_ids_equal(explicit_workspace_id, workspace_id)

    metadata = metadata_dict(doc)
    metadata_workspace_id = metadata.get("workspace_id")
    if metadata_workspace_id:
        return workspace_ids_equal(metadata_workspace_id, workspace_id)

    source_type = doc.source_type
    if source_type in connector_types:
        return True
    if source_type in {"github_issue", "github_pr"} and "github" in connector_types:
        return True
    if source_type.startswith("ai_context") and "ai_context" in connector_types:
        return True
    if source_type == "agent_session" and connector_types.intersection({
        "ai_context", "codex", "claude", "opencode",
        "ai_context_codex", "ai_context_claude_code", "ai_context_opencode",
    }):
        return True

    # Legacy uploads and pre-workspace connector rows were stored without a
    # document-level workspace id. Until SourceDocument has a real FK, keep
    # these visible in the active workspace instead of hiding processed graph
    # data from the UI.
    return source_type in LEGACY_UNSCOPED_SOURCE_TYPES


def filter_source_documents_for_workspace(
    docs: list[SourceDocument],
    workspace_id: str,
    connector_types: set[str],
) -> list[SourceDocument]:
    return [
        doc for doc in docs
        if source_matches_workspace(doc, workspace_id, connector_types)
    ]


def source_explicitly_matches_workspace(
    doc: SourceDocument,
    workspace_id: str,
) -> bool:
    """Return True only for an explicit document or legacy metadata assignment.

    Graph projections must never pull an unassigned row into a workspace merely
    because that workspace happens to have a connector of the same type.
    """
    explicit_workspace_id = getattr(doc, "workspace_id", None)
    if explicit_workspace_id:
        return workspace_ids_equal(explicit_workspace_id, workspace_id)
    metadata_workspace_id = metadata_dict(doc).get("workspace_id")
    return bool(
        metadata_workspace_id
        and workspace_ids_equal(metadata_workspace_id, workspace_id)
    )


def filter_explicit_source_documents_for_workspace(
    docs: list[SourceDocument],
    workspace_id: str,
) -> list[SourceDocument]:
    return [
        doc for doc in docs
        if source_explicitly_matches_workspace(doc, workspace_id)
    ]


def current_source_documents(
    docs: list[SourceDocument],
) -> tuple[list[SourceDocument], int]:
    """Select the highest immutable revision for each source identity."""
    current_by_identity: dict[str, SourceDocument] = {}
    for doc in docs:
        identity = str(getattr(doc, "source_identity_sha256", None) or doc.id)
        existing = current_by_identity.get(identity)
        if existing is None or (
            int(getattr(doc, "revision_number", 1) or 1), str(doc.id)
        ) > (
            int(getattr(existing, "revision_number", 1) or 1), str(existing.id)
        ):
            current_by_identity[identity] = doc
    current = list(current_by_identity.values())
    return current, max(0, len(docs) - len(current))


def filter_components_for_workspace(
    components: list[Component],
    workspace_id: str,
    connector_types: set[str],
) -> list[Component]:
    filtered: list[Component] = []
    for component in components:
        explicit_workspace_id = getattr(component, "workspace_id", None)
        if explicit_workspace_id:
            if workspace_ids_equal(explicit_workspace_id, workspace_id):
                filtered.append(component)
            continue
        if component.source_document and source_matches_workspace(
            component.source_document,
            workspace_id,
            connector_types,
        ):
            filtered.append(component)
    return filtered


def workspace_ids_equal(left: object, right: object) -> bool:
    try:
        return UUID(str(left)) == UUID(str(right))
    except (TypeError, ValueError):
        return str(left) == str(right)
