"""Pydantic schemas for import endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class ImportTriggerRequest(BaseModel):
    """Request to trigger a file-based import."""

    workspace_id: UUID
    import_type: str  # "notion_directory", "slack_export", "generic_file"
    source_path: str
    run_ingestion: bool = True
    options: dict[str, Any] = {}

    @field_validator("source_path")
    @classmethod
    def source_path_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_path must not be empty")
        return v.strip()

    @field_validator("import_type")
    @classmethod
    def import_type_valid(cls, v: str) -> str:
        valid = {"notion_directory", "slack_export", "generic_file"}
        if v not in valid:
            raise ValueError(
                f"import_type must be one of {valid}, got {v!r}"
            )
        return v


class ImportTriggerResponse(BaseModel):
    """Response after triggering an import."""

    import_type: str
    status: str  # "running", "completed", "failed"
    source_path: str
    connector_id: UUID | None = None
    documents_imported: int = 0
    documents_ingested: int = 0
    errors: list[str] = []
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_detail: str | None = None


class ImportConnectorRead(BaseModel):
    """Summary of a manual import connector."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    connector_type: str
    status: str
    last_sync_at: datetime | None
    config: dict[str, Any]


class ImportSourceDocumentRead(BaseModel):
    """Source document from an import connector."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connector_id: UUID
    connector_type: str
    external_id: str
    content: str
    author: str | None
    source_url: str | None
    created_at_source: datetime | None
    ingested_at: datetime
    processed_at: datetime | None
    deleted_at: datetime | None
    metadata: dict[str, Any]


class ImportSourceDocumentList(BaseModel):
    items: list[ImportSourceDocumentRead]
    total: int


class ImportValidateRequest(BaseModel):
    """Request to validate a source path before importing."""

    import_type: str
    source_path: str

    @field_validator("source_path")
    @classmethod
    def source_path_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_path must not be empty")
        return v.strip()


class ImportValidateResponse(BaseModel):
    valid: bool
    error: str | None = None
    import_type: str
