"""Shared helpers for replaying frozen session captures in offline evaluations.

Extracted from the retired semantic-enrichment experiment runner so the
retrieval evaluations keep working without that feature.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Uuid, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent, SourceDocument, Workspace
from app.services.checkpoints import ResolvedSessionRequest
from app.services.objective_resolution import (
    ObjectiveClassification,
    ObjectiveResolution,
    ObjectiveResolutionStatus,
)


def _sha256(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=_json_default) + "\n")


def _typed_row(table, row: dict[str, Any]) -> dict[str, Any]:
    result = {column.name: row[column.name] for column in table.columns if column.name in row}
    for column in table.columns:
        value = result.get(column.name)
        if value is not None and isinstance(column.type, Uuid):
            result[column.name] = UUID(str(value))
        elif value is not None and isinstance(column.type, DateTime):
            result[column.name] = datetime.fromisoformat(value) if isinstance(value, str) else value
    return result


def _request_provenance(request: str) -> dict[str, Any]:
    if not isinstance(request, ResolvedSessionRequest):
        return {"type": "plain_string"}
    return {
        "type": "resolved_session_request",
        "objective_resolution": request.objective_resolution.to_dict() if request.objective_resolution else None,
        "source_provider_event_ids": list(request.source_provider_event_ids),
        "source_session_event_ids": list(request.source_session_event_ids),
    }


def _restore_request(frozen: dict) -> str:
    provenance = frozen["request_provenance"]
    if provenance["type"] == "plain_string":
        return frozen["request_verbatim"]
    raw = provenance["objective_resolution"]
    resolution = None
    if raw is not None:
        values = {field.name: raw[field.name] for field in fields(ObjectiveResolution)}
        values["classification"] = ObjectiveClassification(values["classification"])
        values["status"] = ObjectiveResolutionStatus(values["status"])
        for name in ("source_event_ids", "source_provider_event_ids", "source_session_event_ids"):
            values[name] = tuple(values[name])
        resolution = ObjectiveResolution(**values)
        if resolution.to_dict() != raw:
            raise ValueError("Frozen objective resolution failed lossless reconstruction")
    return ResolvedSessionRequest(
        frozen["request_verbatim"], objective_resolution=resolution,
        source_provider_event_ids=provenance["source_provider_event_ids"],
        source_session_event_ids=provenance["source_session_event_ids"],
    )


async def _seed(session: AsyncSession, frozen: dict) -> None:
    await session.execute(insert(Workspace.__table__), [_typed_row(Workspace.__table__, frozen["workspace"])])
    for raw in frozen["sources"]:
        row = _typed_row(SourceDocument.__table__, raw)
        metadata = json.loads(row.get("metadata") or "{}")
        # Derived state is intentionally absent in both fresh experiment arms.
        metadata.pop("semantic_extraction", None)
        row.update(metadata=json.dumps(metadata), processed_at=None)
        await session.execute(insert(SourceDocument.__table__), [row])
    await session.execute(insert(SessionEvent.__table__), [
        _typed_row(SessionEvent.__table__, row) for row in frozen["events"]
    ])
    await session.commit()
