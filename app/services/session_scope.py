from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent, SourceDocument
from app.services.project_scope import (
    normalize_local_path,
    normalize_repository_identity,
    path_is_within,
    source_workspace_relevance,
    workspace_references,
)
from app.services.session_events import NormalizedSessionEvent
from app.services.workspace_scope import metadata_dict


SESSION_CWD_FIELDS = ("cwd", "working_directory", "workdir")


@dataclass
class WorkspaceSessionScope:
    """Deterministic project boundary shared by Library and Resume."""

    repositories: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    commits: set[str] = field(default_factory=set)
    observed_matches: set[tuple[str, str]] = field(default_factory=set)

    @property
    def has_project_boundary(self) -> bool:
        return bool(self.repositories or self.paths or self.commits)

    def matches_document(self, document: SourceDocument) -> bool:
        metadata = metadata_dict(document)
        provider, session_id = session_reference(document, metadata=metadata)
        return self.matches_metadata(
            metadata,
            provider=provider,
            session_id=session_id,
        )

    def matches_metadata(
        self,
        metadata: dict[str, Any],
        *,
        provider: str | None = None,
        session_id: str | None = None,
        observed_cwds: Iterable[str] = (),
    ) -> bool:
        # A workspace without an indexed/configured project identity cannot
        # safely claim any local harness history. Failing closed avoids turning
        # a newly created workspace into a view of every session on the machine.
        if not self.has_project_boundary:
            return False

        if _qualified_repository_conflicts(metadata, self.repositories):
            return False

        relevance = source_workspace_relevance(
            "agent_session",
            metadata,
            self.repositories,
            self.paths,
            self.commits,
        )
        if relevance.status == "relevant":
            return True

        key = normalize_session_key(provider, session_id)
        if key and key in self.observed_matches:
            return True

        candidates = session_working_directories(metadata, observed_cwds)
        for cwd in candidates:
            scoped_metadata = {**metadata, "cwd": cwd}
            if source_workspace_relevance(
                "agent_session",
                scoped_metadata,
                self.repositories,
                self.paths,
                self.commits,
            ).status == "relevant":
                return True

        persisted_git_roots = _metadata_paths(
            metadata,
            "git_common_root",
            "git_common_roots",
            "repository_root",
            "repository_roots",
        )
        if any(root in self.paths for root in persisted_git_roots):
            return True
        return any(_git_common_root(cwd) in self.paths for cwd in candidates)


async def workspace_session_scope(
    session: AsyncSession,
    workspace_id: UUID,
) -> WorkspaceSessionScope:
    repositories, paths, commits = await workspace_references(session, workspace_id)
    observed_matches = await _observed_project_session_keys(
        session,
        workspace_id,
        paths,
    )
    return WorkspaceSessionScope(
        repositories=repositories,
        paths=paths,
        commits=commits,
        observed_matches=observed_matches,
    )


async def scoped_session_documents(
    session: AsyncSession,
    workspace_id: UUID,
    documents: Iterable[SourceDocument],
    *,
    scope: WorkspaceSessionScope | None = None,
) -> list[SourceDocument]:
    active_scope = scope or await workspace_session_scope(session, workspace_id)
    return [
        document
        for document in documents
        if active_scope.matches_document(document)
    ]


async def session_document_is_in_scope(
    session: AsyncSession,
    workspace_id: UUID,
    document: SourceDocument,
    *,
    allow_unbounded: bool = False,
) -> bool:
    scope = await workspace_session_scope(session, workspace_id)
    if allow_unbounded and not scope.has_project_boundary:
        return True
    return scope.matches_document(document)


def enrich_session_scope_metadata(
    metadata: dict[str, Any],
    events: Iterable[NormalizedSessionEvent],
) -> dict[str, Any]:
    """Persist compact project evidence so later reads avoid transcript heuristics."""

    result = dict(metadata)
    observed_cwds = normalized_event_working_directories(events)
    if observed_cwds:
        result["observed_cwds"] = sorted(observed_cwds)
    git_roots = {
        root
        for cwd in session_working_directories(result, observed_cwds)
        if (root := _git_common_root(cwd))
    }
    if git_roots:
        result["git_common_roots"] = sorted(git_roots)
    return result


def normalized_event_working_directories(
    events: Iterable[NormalizedSessionEvent],
) -> set[str]:
    values: set[str] = set()
    for event in events:
        values.update(_payload_working_directories(event.payload))
    return values


def session_working_directories(
    metadata: dict[str, Any],
    additional: Iterable[str] = (),
) -> set[str]:
    values: set[str] = set()
    for key in SESSION_CWD_FIELDS:
        normalized = normalize_local_path(metadata.get(key))
        if normalized:
            values.add(normalized)
    values.update(_metadata_paths(metadata, "observed_cwd", "observed_cwds"))
    for value in additional:
        normalized = normalize_local_path(value)
        if normalized:
            values.add(normalized)
    return values


def session_reference(
    document: SourceDocument,
    *,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    values = metadata if metadata is not None else metadata_dict(document)
    provider = str(
        values.get("connector_type")
        or values.get("tool")
        or document.external_id.split(":", 1)[0]
        or ""
    ).strip().lower()
    if provider == "claude_code":
        provider = "claude"
    session_id = str(
        values.get("session_id")
        or document.external_id.rsplit(":", 1)[-1]
        or ""
    ).strip()
    return provider, session_id


def normalize_session_key(
    provider: str | None,
    session_id: str | None,
) -> tuple[str, str] | None:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "claude_code":
        normalized_provider = "claude"
    normalized_session_id = str(session_id or "").strip()
    if not normalized_provider or not normalized_session_id:
        return None
    return normalized_provider, normalized_session_id


async def _observed_project_session_keys(
    session: AsyncSession,
    workspace_id: UUID,
    workspace_paths: set[str],
) -> set[tuple[str, str]]:
    if not workspace_paths:
        return set()

    predicates = [
        SessionEvent.payload_json.contains(f'"{field}"', autoescape=True)
        for field in SESSION_CWD_FIELDS
    ]
    rows = await session.execute(
        select(
            SessionEvent.provider,
            SessionEvent.session_id,
            SessionEvent.payload_json,
        )
        .where(
            SessionEvent.workspace_id == workspace_id,
            or_(*predicates),
        )
    )
    matches: set[tuple[str, str]] = set()
    for provider, session_id, payload_json in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        working_directories = _payload_working_directories(payload)
        if not any(
            any(path_is_within(cwd, root) for root in workspace_paths)
            or _git_common_root(cwd) in workspace_paths
            for cwd in working_directories
        ):
            continue
        key = normalize_session_key(provider, session_id)
        if key:
            matches.add(key)
    return matches


def _qualified_repository_conflicts(
    metadata: dict[str, Any],
    workspace_repositories: set[str],
) -> bool:
    raw = (
        metadata.get("repository")
        or metadata.get("repo_full_name")
        or metadata.get("repo")
    )
    repository, qualified = normalize_repository_identity(raw)
    qualified_workspace = {
        value for value in workspace_repositories if "/" in value
    }
    return bool(
        repository
        and qualified
        and qualified_workspace
        and repository not in qualified_workspace
    )


def _payload_working_directories(payload: object) -> set[str]:
    values: set[str] = set()
    if isinstance(payload, dict):
        for key, child in payload.items():
            if str(key).lower() in SESSION_CWD_FIELDS:
                normalized = normalize_local_path(child)
                if normalized:
                    values.add(normalized)
            if isinstance(child, (dict, list, tuple)):
                values.update(_payload_working_directories(child))
    elif isinstance(payload, (list, tuple)):
        for child in payload:
            values.update(_payload_working_directories(child))
    return values


def _metadata_paths(metadata: dict[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw = metadata.get(key)
        candidates = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for candidate in candidates:
            normalized = normalize_local_path(candidate)
            if normalized:
                values.add(normalized)
    return values


def _git_common_root(cwd: str) -> str | None:
    """Resolve a normal checkout or linked worktree to its primary repository root."""

    normalized = normalize_local_path(cwd)
    if not normalized:
        return None
    path = Path(normalized)
    for candidate in (path, *path.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return normalize_local_path(candidate)
        if not marker.is_file():
            continue
        try:
            with marker.open("r", encoding="utf-8", errors="replace") as handle:
                first_line = handle.readline(4096).strip()
        except OSError:
            return None
        if not first_line.lower().startswith("gitdir:"):
            return None
        git_dir = Path(first_line.split(":", 1)[1].strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = marker.parent / git_dir
        try:
            git_dir = git_dir.resolve(strict=False)
        except (OSError, RuntimeError):
            pass
        common_dir = git_dir
        common_marker = git_dir / "commondir"
        if common_marker.is_file():
            try:
                with common_marker.open("r", encoding="utf-8", errors="replace") as handle:
                    raw_common = handle.readline(4096).strip()
                common_dir = Path(raw_common).expanduser()
                if not common_dir.is_absolute():
                    common_dir = git_dir / common_dir
                common_dir = common_dir.resolve(strict=False)
            except (OSError, RuntimeError):
                return None
        repository_root = common_dir.parent if common_dir.name == ".git" else None
        return normalize_local_path(repository_root)
    return None
