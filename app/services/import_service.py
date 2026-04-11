"""Import service — orchestrates zero-auth file imports.

The import service takes files that a user has manually exported from
their tools, parses them via the appropriate importer, persists
``SourceDocument`` rows, and optionally triggers the ingestion pipeline
to extract structured facts.

This is the default MVP path — no OAuth, no API tokens, just files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import NormalizedDocument
from app.importers.base import BaseImporter
from app.importers.generic import GenericFileScanner
from app.importers.notion import NotionDirectoryImporter
from app.importers.slack import SlackExportImporter
from app.models.connector import Connector, ConnectorStatus, SyncState
from app.models.source import ConnectorType, SourceDocument
from app.models.user import Workspace
from app.schemas.imports import (
    ImportDocumentInput,
    ImportDocumentResult,
    ImportResponse,
)
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


class ImportType(str, Enum):
    NOTION_DIRECTORY = "notion_directory"
    SLACK_EXPORT = "slack_export"
    GENERIC_FILE = "generic_file"


class ImportStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ImportResult:
    """Result of a single import run."""

    import_type: ImportType
    status: ImportStatus
    source_path: str
    workspace_id: UUID
    connector_id: UUID | None = None
    documents_imported: int = 0
    documents_ingested: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_detail: str | None = None


class ImportServiceError(Exception):
    """Raised when an import operation fails."""


class ImportWorkspaceNotFoundError(ImportServiceError):
    """Raised when an import references a missing workspace."""


class ImportService:
    """Orchestrates file imports → SourceDocument → ingestion pipeline."""

    _IMPORTERS: dict[ImportType, type[BaseImporter]] = {
        ImportType.NOTION_DIRECTORY: NotionDirectoryImporter,
        ImportType.SLACK_EXPORT: SlackExportImporter,
        ImportType.GENERIC_FILE: GenericFileScanner,
    }
    _CONNECTOR_TYPE_MAP: dict[ImportType, ConnectorType] = {
        ImportType.NOTION_DIRECTORY: ConnectorType.NOTION,
        ImportType.SLACK_EXPORT: ConnectorType.SLACK,
        ImportType.GENERIC_FILE: ConnectorType.LOCAL,
    }
    _LOCAL_CONNECTOR_CONFIG: dict[str, object] = {
        "auth_mode": "none",
        "import_source": "manual",
        "import_type": ImportType.GENERIC_FILE.value,
        "ingestion_mode": "generic_file_import",
        "message": "Manual import connector — no OAuth required",
        "source_focus": "manual_local_files",
        "sync_delivery_mode": "push_via_api",
        "webhook_auto_sync": False,
    }
    _MODEL_NAME = "Imported Files"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_documents(
        self,
        *,
        workspace_id: UUID,
        documents: list[ImportDocumentInput],
    ) -> ImportResponse:
        await self._require_workspace(workspace_id)
        connector = await self._get_or_create_local_connector(workspace_id)
        existing_by_external_id = await self._load_existing_documents(
            connector_id=connector.id,
            external_ids=[document.external_id for document in documents],
        )
        ingestion = IngestionService(self.session)

        created_documents = 0
        updated_documents = 0
        unchanged_documents = 0
        processed_documents = 0
        failed_documents = 0
        results: list[ImportDocumentResult] = []

        for payload in documents:
            document = existing_by_external_id.get(payload.external_id)
            status: str

            if document is None:
                document = SourceDocument(
                    connector_id=connector.id,
                    connector_type=ConnectorType.LOCAL,
                    external_id=payload.external_id,
                    content=payload.content,
                    author=payload.author,
                    source_url=payload.source_url,
                    created_at_source=payload.created_at_source,
                    metadata_json=dict(payload.metadata),
                )
                self.session.add(document)
                await self.session.flush()
                existing_by_external_id[payload.external_id] = document
                created_documents += 1
                status = "created"
            else:
                changed = self._update_document(document, payload)
                if changed:
                    updated_documents += 1
                    status = "updated"
                else:
                    unchanged_documents += 1
                    status = "unchanged"

            error_message: str | None = None
            if document.processed_at is None:
                try:
                    processed_now = await ingestion.process_single_document(
                        workspace_id=workspace_id,
                        document=document,
                        connector_type=ConnectorType.LOCAL,
                    )
                except Exception as exc:
                    failed_documents += 1
                    error_message = str(exc)
                    logger.exception("Direct import ingestion failed for %s", document.external_id)
                else:
                    processed_documents += processed_now

            results.append(
                ImportDocumentResult(
                    document_id=document.id,
                    external_id=document.external_id,
                    label=document.label,
                    status=status,
                    processed_at=document.processed_at,
                    error=error_message,
                )
            )

        await self.session.commit()

        return ImportResponse(
            workspace_id=workspace_id,
            connector_id=connector.id,
            connector_type=ConnectorType.LOCAL.value,
            model_name=self._MODEL_NAME,
            total_documents=len(documents),
            created_documents=created_documents,
            updated_documents=updated_documents,
            unchanged_documents=unchanged_documents,
            processed_documents=processed_documents,
            failed_documents=failed_documents,
            documents=results,
            imported_at=datetime.now(timezone.utc),
        )

    async def run_import(
        self,
        import_type: ImportType,
        source_path: Path,
        workspace_id: UUID,
        *,
        run_ingestion: bool = True,
        options: dict[str, Any] | None = None,
    ) -> ImportResult:
        """Run a full import pipeline."""
        result = ImportResult(
            import_type=import_type,
            status=ImportStatus.RUNNING,
            source_path=str(source_path),
            workspace_id=workspace_id,
            started_at=datetime.now(timezone.utc),
        )

        importer_cls = self._IMPORTERS.get(import_type)
        if importer_cls is None:
            result.status = ImportStatus.FAILED
            result.error_detail = f"Unknown import type: {import_type}"
            return result

        importer = importer_cls()
        valid, error_msg = importer_cls.validate_source(source_path)
        if not valid:
            result.status = ImportStatus.FAILED
            result.error_detail = error_msg or "Invalid source"
            result.completed_at = datetime.now(timezone.utc)
            return result

        connector_type = self._CONNECTOR_TYPE_MAP.get(import_type, ConnectorType.LOCAL)
        if options and options.get("connector_type_hint"):
            hint = options["connector_type_hint"]
            try:
                connector_type = ConnectorType(hint)
            except ValueError:
                pass

        connector = await self._get_or_create_import_connector(
            workspace_id,
            connector_type,
            import_type,
        )
        result.connector_id = connector.id

        options = options or {}
        options["workspace_id"] = str(workspace_id)

        try:
            documents = list(importer.ingest(source_path, **options))
        except Exception as exc:
            result.status = ImportStatus.FAILED
            result.error_detail = f"Importer failed: {exc}"
            result.completed_at = datetime.now(timezone.utc)
            logger.exception("Import failed for %s: %s", source_path, exc)
            return result

        if not documents:
            result.status = ImportStatus.COMPLETED
            result.completed_at = datetime.now(timezone.utc)
            return result

        persisted = await self._persist_documents(connector.id, connector_type, documents)
        result.documents_imported = persisted

        connector.last_sync_at = datetime.now(timezone.utc)
        connector.config = {
            **(connector.config or {}),
            "import_type": import_type.value,
            "source_path": str(source_path),
            "last_import_documents": persisted,
            "last_import_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.session.flush()

        if run_ingestion and persisted > 0:
            try:
                ingestion = IngestionService(self.session)
                processed = await ingestion.process_connector_documents(
                    workspace_id=workspace_id,
                    connector_id=connector.id,
                    connector_type=connector_type,
                )
                result.documents_ingested = processed
            except Exception as exc:
                result.errors.append(f"Ingestion failed: {exc}")
                logger.exception("Ingestion failed after import: %s", exc)

        result.status = ImportStatus.COMPLETED
        result.completed_at = datetime.now(timezone.utc)
        return result

    async def _require_workspace(self, workspace_id: UUID) -> Workspace:
        workspace = await self.session.scalar(
            select(Workspace).where(Workspace.id == workspace_id).limit(1)
        )
        if workspace is None:
            raise ImportWorkspaceNotFoundError("Workspace not found")
        return workspace

    async def _get_or_create_local_connector(self, workspace_id: UUID) -> Connector:
        connector = await self._get_or_create_import_connector(
            workspace_id,
            ConnectorType.LOCAL,
            ImportType.GENERIC_FILE,
        )
        connector.status = ConnectorStatus.CONNECTED
        connector.config = {
            **(connector.config or {}),
            **self._LOCAL_CONNECTOR_CONFIG,
        }
        await self.session.flush()
        return connector

    async def _get_or_create_import_connector(
        self,
        workspace_id: UUID,
        connector_type: ConnectorType,
        import_type: ImportType,
    ) -> Connector:
        """Get or create a Connector row for manual imports."""
        existing = await self.session.scalar(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.connector_type == connector_type,
                Connector.config["import_source"].as_string() == "manual",
            )
        )
        if existing is not None:
            return existing

        connector = Connector(
            workspace_id=workspace_id,
            connector_type=connector_type,
            status=ConnectorStatus.CONNECTED,
            config={
                "import_source": "manual",
                "import_type": import_type.value,
                "message": "Manual import connector — no OAuth required",
            },
        )
        self.session.add(connector)
        await self.session.flush()

        sync_state = SyncState(connector_id=connector.id)
        self.session.add(sync_state)
        await self.session.flush()

        return connector

    async def _persist_documents(
        self,
        connector_id: UUID,
        connector_type: ConnectorType,
        documents: list[NormalizedDocument],
    ) -> int:
        """Upsert NormalizedDocuments as SourceDocument rows."""
        if not documents:
            return 0

        from sqlalchemy import case, literal_column, or_
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        rows = [
            {
                "connector_id": connector_id,
                "connector_type": connector_type.value,
                "external_id": doc.external_id,
                "content": doc.content,
                "author": doc.author,
                "source_url": doc.source_url,
                "created_at_source": doc.created_at,
                "metadata": doc.metadata or {},
                "deleted_at": None,
            }
            for doc in documents
        ]

        stmt = pg_insert(SourceDocument.__table__).values(rows)
        sd = SourceDocument.__table__.c
        stmt = stmt.on_conflict_do_update(
            index_elements=["connector_id", "external_id"],
            set_={
                "content": stmt.excluded.content,
                "author": stmt.excluded.author,
                "source_url": stmt.excluded.source_url,
                "created_at_source": stmt.excluded.created_at_source,
                "metadata": stmt.excluded.metadata,
                "deleted_at": None,
                "processed_at": case(
                    (
                        or_(
                            sd.content != stmt.excluded.content,
                            sd.deleted_at.is_not(None),
                        ),
                        None,
                    ),
                    else_=sd.processed_at,
                ),
            },
        )
        stmt = stmt.returning(literal_column("(xmax = 0)").label("inserted"))
        result = await self.session.execute(stmt)
        return sum(1 for row in result if row.inserted)

    async def _load_existing_documents(
        self,
        *,
        connector_id: UUID,
        external_ids: list[str],
    ) -> dict[str, SourceDocument]:
        if not external_ids:
            return {}

        result = await self.session.scalars(
            select(SourceDocument).where(
                SourceDocument.connector_id == connector_id,
                SourceDocument.external_id.in_(external_ids),
            )
        )
        return {document.external_id: document for document in result}

    def _update_document(
        self,
        document: SourceDocument,
        payload: ImportDocumentInput,
    ) -> bool:
        metadata = dict(payload.metadata)
        content_changed = document.content != payload.content
        metadata_changed = (document.metadata_json or {}) != metadata
        deleted_changed = document.deleted_at is not None

        changed = any(
            (
                content_changed,
                metadata_changed,
                deleted_changed,
                document.author != payload.author,
                document.source_url != payload.source_url,
                document.created_at_source != payload.created_at_source,
            )
        )
        if not changed:
            return False

        document.content = payload.content
        document.author = payload.author
        document.source_url = payload.source_url
        document.created_at_source = payload.created_at_source
        document.metadata_json = metadata
        document.deleted_at = None
        if content_changed or metadata_changed or deleted_changed:
            document.processed_at = None
        return True

    async def get_import_connectors(
        self,
        workspace_id: UUID,
    ) -> list[Connector]:
        """List all manual import connectors for a workspace."""
        result = await self.session.scalars(
            select(Connector).where(
                Connector.workspace_id == workspace_id,
                Connector.config["import_source"].as_string() == "manual",
            ).order_by(Connector.last_sync_at.desc().nulls_last())
        )
        return list(result)

    async def get_source_documents_for_connector(
        self,
        connector_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        processed: bool | None = None,
    ) -> list[SourceDocument]:
        """List SourceDocuments for a specific import connector."""
        query = (
            select(SourceDocument)
            .where(SourceDocument.connector_id == connector_id)
            .order_by(SourceDocument.ingested_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if processed is not None:
            if processed:
                query = query.where(SourceDocument.processed_at.isnot(None))
            else:
                query = query.where(SourceDocument.processed_at.is_(None))

        result = await self.session.scalars(query)
        return list(result)
