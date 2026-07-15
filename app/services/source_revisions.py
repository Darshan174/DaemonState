from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceDocument, SourceReadGrant
from app.services.evidence import sha256_text
from app.source_identity import canonical_source_identity_sha256
from app.time import utc_now


@dataclass(frozen=True)
class SourceRevisionResult:
    document: SourceDocument
    created: bool
    unchanged: bool
    previous_document_id: UUID | None

    @property
    def revised(self) -> bool:
        return self.created and self.previous_document_id is not None


async def get_current_source_document(
    session: AsyncSession,
    *,
    workspace_id: UUID | None,
    source_type: str,
    external_id: str,
    source_identity_sha256: str | None = None,
) -> SourceDocument | None:
    """Return the deterministic current row for one workspace-scoped source object."""
    identity_sha256 = source_identity_sha256 or canonical_source_identity_sha256(
        workspace_id, source_type, external_id
    )
    stmt = select(SourceDocument).where(
        SourceDocument.source_identity_sha256 == identity_sha256,
    )
    return await session.scalar(
        stmt.order_by(
            SourceDocument.revision_number.desc(),
            SourceDocument.id.desc(),
        ).limit(1)
    )


async def ingest_source_document_revision(
    session: AsyncSession,
    *,
    workspace_id: UUID | None,
    source_type: str,
    external_id: str,
    content: str,
    author: str | None = None,
    source_url: str | None = None,
    metadata_json: dict[str, Any] | str | None = None,
    source_created_at: datetime | None = None,
    trust_zone: str | None = None,
    visibility_scope: str = "workspace",
    permission_source: str = "workspace_default",
    permission_observed_at: datetime | None = None,
    allowed_principal_ids: list[str] | tuple[str, ...] | None = None,
) -> SourceRevisionResult:
    """Insert immutable content revisions while making identical retries idempotent."""
    incoming_hash = sha256_text(content)
    if visibility_scope not in {"workspace", "restricted"}:
        raise ValueError("visibility_scope must be workspace or restricted")
    normalized_principals = sorted({
        str(value).strip() for value in (allowed_principal_ids or []) if str(value).strip()
    })
    if visibility_scope == "restricted" and not normalized_principals:
        raise ValueError("restricted sources require at least one allowed principal")
    observed_at = permission_observed_at or utc_now()
    permission_snapshot_sha256 = sha256_text(json.dumps({
        "visibility_scope": visibility_scope,
        "permission_source": permission_source,
        "allowed_principal_ids": normalized_principals,
    }, sort_keys=True, separators=(",", ":")))
    identity_sha256 = canonical_source_identity_sha256(workspace_id, source_type, external_id)

    for attempt in range(2):
        current = await get_current_source_document(
            session,
            workspace_id=workspace_id,
            source_type=source_type,
            external_id=external_id,
            source_identity_sha256=identity_sha256,
        )
        if (
            current is not None
            and current.content_sha256 == incoming_hash
            and current.content == content
            and current.permission_snapshot_sha256 == permission_snapshot_sha256
        ):
            return SourceRevisionResult(
                document=current,
                created=False,
                unchanged=True,
                previous_document_id=current.supersedes_source_document_id,
            )

        doc = SourceDocument(
            id=uuid4(),
            workspace_id=workspace_id,
            source_type=source_type,
            external_id=external_id,
            content=content,
            content_sha256=incoming_hash,
            source_identity_sha256=identity_sha256,
            revision_number=(current.revision_number + 1) if current is not None else 1,
            supersedes_source_document_id=current.id if current is not None else None,
            author=author,
            source_url=source_url,
            metadata_json=_serialize_metadata(metadata_json),
            source_created_at=source_created_at,
            trust_zone=trust_zone,
            visibility_scope=visibility_scope,
            permission_source=permission_source,
            permission_observed_at=observed_at,
            permission_snapshot_sha256=permission_snapshot_sha256,
        )
        try:
            async with session.begin_nested():
                session.add(doc)
                await session.flush()
                if workspace_id is not None:
                    for principal_id in normalized_principals:
                        session.add(SourceReadGrant(
                            workspace_id=workspace_id,
                            source_document_id=doc.id,
                            principal_id=principal_id,
                            grant_key=sha256_text(
                                f"{doc.id}:{principal_id}:{permission_snapshot_sha256}"
                            ),
                            permission_snapshot_sha256=permission_snapshot_sha256,
                        ))
                    await session.flush()
        except IntegrityError:
            if attempt == 0:
                continue
            raise
        return SourceRevisionResult(
            document=doc,
            created=True,
            unchanged=False,
            previous_document_id=current.id if current is not None else None,
        )

    raise RuntimeError("source revision allocation retry exhausted")


def _serialize_metadata(value: dict[str, Any] | str | None) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {})
