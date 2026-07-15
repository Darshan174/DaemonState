from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeFile, SourceDocument, Workspace
from app.services.redaction import redact_sensitive, redact_sensitive_text
from app.services.repo_indexer import PROJECT_ROOT_MARKERS, RepoFrame, RepoIndexer
from app.services.source_revisions import ingest_source_document_revision
from app.time import utc_now


WATCH_SOURCE_TYPE = "local_repository"
WATCH_EXTERNAL_ID_PREFIX = "repo-watch"
WATCH_EVENT_SCHEMA_VERSION = "repository_event.v1"
MAX_EVENT_PATHS = 200


class RepositoryWatchError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RepositoryWatchEvent:
    source_document_id: str
    snapshot_fingerprint: str
    event_type: str
    created: bool
    files_added: int
    files_changed: int
    files_deleted: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_document_id": self.source_document_id,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "event_type": self.event_type,
            "created": self.created,
            "files_added": self.files_added,
            "files_changed": self.files_changed,
            "files_deleted": self.files_deleted,
        }


@dataclass(frozen=True)
class RepositoryWatchResult:
    workspace_id: str
    cycles: int
    changes_detected: int
    events_created: int
    last_snapshot_fingerprint: str | None
    stopped_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "cycles": self.cycles,
            "changes_detected": self.changes_detected,
            "events_created": self.events_created,
            "last_snapshot_fingerprint": self.last_snapshot_fingerprint,
            "stopped_reason": self.stopped_reason,
        }


Sleep = Callable[[float], Awaitable[None]]
EventCallback = Callable[[RepositoryWatchEvent], Awaitable[None] | None]


async def watch_repository(
    session: AsyncSession,
    *,
    repo_path: str | Path,
    workspace_id: str | UUID,
    poll_interval_seconds: float = 2.0,
    debounce_seconds: float = 0.5,
    once: bool = False,
    max_cycles: int | None = None,
    sleep: Sleep = asyncio.sleep,
    on_event: EventCallback | None = None,
) -> RepositoryWatchResult:
    """Watch one bounded local repository and persist source-first change events.

    The watcher stores paths and repository state only. It never stores file
    contents, terminal output, commands, or environment values.
    """
    workspace_uuid = _workspace_uuid(workspace_id)
    root = _validated_repo_root(repo_path)
    if poll_interval_seconds < 0:
        raise RepositoryWatchError(
            "invalid_poll_interval", "poll_interval_seconds must be zero or greater"
        )
    if debounce_seconds < 0:
        raise RepositoryWatchError(
            "invalid_debounce", "debounce_seconds must be zero or greater"
        )
    if max_cycles is not None and max_cycles < 1:
        raise RepositoryWatchError("invalid_max_cycles", "max_cycles must be at least 1")
    if await session.get(Workspace, workspace_uuid) is None:
        raise RepositoryWatchError("workspace_not_found", "workspace was not found")

    root_hash = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    last_fingerprint = await _latest_watch_fingerprint(
        session,
        workspace_id=workspace_uuid,
        root_hash=root_hash,
    )
    indexer = RepoIndexer(session)
    cycles = 0
    changes_detected = 0
    events_created = 0
    stopped_reason = "once" if once else "max_cycles"

    try:
        while True:
            frame = await indexer.inspect_repo(
                root,
                workspace_id=workspace_uuid,
                persist=False,
            )
            cycles += 1
            if not frame.indexed_files:
                raise RepositoryWatchError(
                    "repo_not_indexable",
                    "No supported project files were found in the repository path",
                )

            if frame.snapshot_fingerprint != last_fingerprint:
                if debounce_seconds:
                    await sleep(debounce_seconds)
                    frame = await indexer.inspect_repo(
                        root,
                        workspace_id=workspace_uuid,
                        persist=False,
                    )
                    if not frame.indexed_files:
                        raise RepositoryWatchError(
                            "repo_not_indexable",
                            "No supported project files were found in the repository path",
                        )

                previous_files = await _persisted_file_hashes(
                    session,
                    workspace_id=workspace_uuid,
                    repo_root=str(root),
                )
                # Persist through the public incremental-index contract. The
                # second bounded scan happens only after a changed fingerprint
                # survives the debounce window, and captures any final burst.
                frame = await indexer.inspect_repo(
                    root,
                    workspace_id=workspace_uuid,
                    persist=True,
                )
                if not frame.persistence_available:
                    raise RepositoryWatchError(
                        "persistence_unavailable",
                        frame.persistence_reason or "repository index could not be persisted",
                    )
                changes = _file_changes(previous_files, frame)

                event_type = (
                    "repository_snapshot"
                    if last_fingerprint is None
                    else "repository_change"
                )
                event = await _persist_watch_event(
                    session,
                    workspace_id=workspace_uuid,
                    root_hash=root_hash,
                    frame=frame,
                    event_type=event_type,
                    previous_fingerprint=last_fingerprint,
                    changes=changes,
                )
                await session.commit()
                changes_detected += 1
                events_created += int(event.created)
                last_fingerprint = frame.snapshot_fingerprint
                if on_event is not None:
                    callback_result = on_event(event)
                    if inspect.isawaitable(callback_result):
                        await callback_result

            if once:
                stopped_reason = "once"
                break
            if max_cycles is not None and cycles >= max_cycles:
                stopped_reason = "max_cycles"
                break
            await sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise

    return RepositoryWatchResult(
        workspace_id=str(workspace_uuid),
        cycles=cycles,
        changes_detected=changes_detected,
        events_created=events_created,
        last_snapshot_fingerprint=last_fingerprint,
        stopped_reason=stopped_reason,
    )


def _workspace_uuid(value: str | UUID | None) -> UUID:
    if value in (None, ""):
        raise RepositoryWatchError(
            "workspace_required", "workspace_id is required for repository watching"
        )
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RepositoryWatchError(
            "invalid_workspace_id", "workspace_id must be a UUID"
        ) from exc


def _validated_repo_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.exists():
        raise RepositoryWatchError("repo_not_found", f"repo path does not exist: {root}")
    if not root.is_dir():
        raise RepositoryWatchError(
            "repo_not_directory", f"repo path is not a directory: {root}"
        )
    if not any((root / marker).exists() for marker in PROJECT_ROOT_MARKERS):
        raise RepositoryWatchError(
            "repo_not_project_root",
            "repo path is not a project root: expected .git or a supported project manifest",
        )
    return root


async def _latest_watch_fingerprint(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    root_hash: str,
) -> str | None:
    prefix = f"{WATCH_EXTERNAL_ID_PREFIX}:{root_hash}:"
    documents = list(
        await session.scalars(
            select(SourceDocument)
            .where(
                SourceDocument.workspace_id == workspace_id,
                SourceDocument.source_type == WATCH_SOURCE_TYPE,
                SourceDocument.external_id.like(f"{prefix}%"),
            )
            .order_by(
                SourceDocument.source_created_at.desc(),
                SourceDocument.ingested_at.desc(),
                SourceDocument.id.desc(),
            )
            .limit(1)
        )
    )
    if not documents:
        return None
    metadata = _json_object(documents[0].metadata_json)
    fingerprint = metadata.get("snapshot_fingerprint")
    return str(fingerprint) if isinstance(fingerprint, str) and fingerprint else None


async def _persisted_file_hashes(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    repo_root: str,
) -> dict[str, str | None]:
    files = list(
        await session.scalars(
            select(CodeFile).where(
                CodeFile.workspace_id == workspace_id,
                CodeFile.repo_root == repo_root,
            )
        )
    )
    return {item.path: item.sha256 for item in files}


def _file_changes(
    previous: dict[str, str | None],
    frame: RepoFrame,
) -> dict[str, list[str]]:
    current = {item.path: item.sha256 for item in frame.indexed_files}
    return {
        "added": sorted(set(current) - set(previous)),
        "changed": sorted(
            path
            for path in set(current) & set(previous)
            if current[path] != previous[path]
        ),
        "deleted": sorted(set(previous) - set(current)),
    }


async def _persist_watch_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    root_hash: str,
    frame: RepoFrame,
    event_type: str,
    previous_fingerprint: str | None,
    changes: dict[str, list[str]],
) -> RepositoryWatchEvent:
    safe_changes, redacted_count, truncated = _safe_changes(changes)
    payload = redact_sensitive(
        {
            "schema_version": WATCH_EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "branch": frame.branch,
            "head_commit": frame.head_commit,
            "dirty": frame.dirty,
            "snapshot_fingerprint": frame.snapshot_fingerprint,
            "changes": {
                name: {
                    "count": len(paths),
                    "paths": safe_changes[name],
                }
                for name, paths in changes.items()
            },
            "paths_redacted": redacted_count,
            "paths_truncated": truncated,
        }
    )
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    previous_identity = previous_fingerprint or "initial"
    external_id = (
        f"{WATCH_EXTERNAL_ID_PREFIX}:{root_hash}:"
        f"{previous_identity}:{frame.snapshot_fingerprint}"
    )
    result = await ingest_source_document_revision(
        session,
        workspace_id=workspace_id,
        source_type=WATCH_SOURCE_TYPE,
        external_id=external_id,
        content=content,
        author="Context Engine repository watcher",
        source_url=None,
        metadata_json={
            **payload,
            "ingested_via": "ctxe_repo_watch",
            "repo_root_sha256": root_hash,
        },
        source_created_at=utc_now(),
        trust_zone="trusted_repo",
    )
    return RepositoryWatchEvent(
        source_document_id=str(result.document.id),
        snapshot_fingerprint=frame.snapshot_fingerprint,
        event_type=event_type,
        created=result.created,
        files_added=len(changes["added"]),
        files_changed=len(changes["changed"]),
        files_deleted=len(changes["deleted"]),
    )


def _safe_changes(
    changes: dict[str, list[str]],
) -> tuple[dict[str, list[str]], int, bool]:
    safe: dict[str, list[str]] = {"added": [], "changed": [], "deleted": []}
    redacted_count = 0
    remaining = MAX_EVENT_PATHS
    total_safe = 0
    for name in ("added", "changed", "deleted"):
        for path in changes.get(name, []):
            sanitized = _safe_relative_path(path)
            if sanitized is None:
                redacted_count += 1
                continue
            total_safe += 1
            if remaining > 0:
                safe[name].append(sanitized)
                remaining -= 1
    return safe, redacted_count, total_safe > MAX_EVENT_PATHS


def _safe_relative_path(value: str) -> str | None:
    normalized = str(value or "").replace("\\", "/").removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None
    lowered = [part.lower() for part in path.parts]
    basename = lowered[-1]
    stem = PurePosixPath(basename).stem
    if (
        any(part in {".aws", ".ssh", ".gnupg"} for part in lowered)
        or basename == ".netrc"
        or basename == ".npmrc"
        or basename == ".pypirc"
        or basename == "id_rsa"
        or basename == "id_ed25519"
        or basename.startswith(".env")
        or stem in {"credential", "credentials", "private_key", "secret", "secrets"}
        or PurePosixPath(basename).suffix in {".key", ".pem", ".p12", ".pfx"}
    ):
        return None
    redacted = redact_sensitive_text(normalized)
    if redacted != normalized:
        return None
    return normalized


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
