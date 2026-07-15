from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.models import SourceDocument, SourceReadGrant


@dataclass(frozen=True)
class AccessScope:
    """Server-authenticated evidence access context.

    `local` and `admin` are trusted server modes. Configured principals are
    restricted to their server-side workspace memberships and source grants.
    """

    principal_id: str
    workspace_ids: frozenset[UUID] = frozenset()
    unrestricted: bool = False

    @classmethod
    def local(cls) -> "AccessScope":
        return cls(principal_id="local", unrestricted=True)

    @classmethod
    def admin(cls) -> "AccessScope":
        return cls(principal_id="admin", unrestricted=True)

    def allows_workspace(self, workspace_id: UUID | None) -> bool:
        if self.unrestricted:
            return True
        return workspace_id is not None and workspace_id in self.workspace_ids


def source_access_predicate(
    access_scope: AccessScope,
    *,
    workspace_id: UUID | None,
) -> ColumnElement[bool]:
    """SQL predicate that excludes unauthorized sources before candidacy."""
    if not access_scope.allows_workspace(workspace_id):
        return false()
    workspace_predicate = _source_workspace_predicate(workspace_id)
    if access_scope.unrestricted:
        return workspace_predicate
    grant_exists = exists(select(SourceReadGrant.id).where(
        SourceReadGrant.source_document_id == SourceDocument.id,
        SourceReadGrant.workspace_id == workspace_id,
        SourceReadGrant.principal_id == access_scope.principal_id,
        SourceReadGrant.permission_snapshot_sha256
        == SourceDocument.permission_snapshot_sha256,
    ))
    return and_(
        workspace_predicate,
        or_(
            SourceDocument.visibility_scope == "workspace",
            and_(SourceDocument.visibility_scope == "restricted", grant_exists),
        ),
    )


def _source_workspace_predicate(workspace_id: UUID | None) -> ColumnElement[bool]:
    if workspace_id is None:
        return SourceDocument.workspace_id.is_(None)
    # Releases before SourceDocument gained a workspace FK stored the boundary
    # in metadata. Keep that exact legacy representation readable without
    # widening a workspace query to unrelated unscoped rows.
    workspace_value = str(workspace_id)
    legacy_workspace = and_(
        SourceDocument.workspace_id.is_(None),
        or_(
            SourceDocument.metadata_json.like(
                f'%"workspace_id": "{workspace_value}"%'
            ),
            SourceDocument.metadata_json.like(
                f'%"workspace_id":"{workspace_value}"%'
            ),
        ),
    )
    return or_(SourceDocument.workspace_id == workspace_id, legacy_workspace)


def source_is_accessible(
    source: SourceDocument,
    access_scope: AccessScope,
    *,
    granted_principals: set[str] | None = None,
) -> bool:
    if not access_scope.allows_workspace(source.workspace_id):
        return False
    if access_scope.unrestricted:
        return True
    if source.visibility_scope == "workspace":
        return True
    return bool(
        source.visibility_scope == "restricted"
        and granted_principals
        and access_scope.principal_id in granted_principals
    )
