from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeFile, Component, Connector


@dataclass(frozen=True)
class ProjectRelevance:
    status: str
    reasons: list[str]


async def workspace_references(
    session: AsyncSession,
    workspace_id: str | UUID | None,
) -> tuple[set[str], set[str], set[str]]:
    if not workspace_id:
        return set(), set(), set()
    workspace_uuid = workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
    connectors = list(await session.scalars(
        select(Connector).where(
            Connector.workspace_id == workspace_uuid,
            Connector.connector_type == "github",
        )
    ))
    repositories: set[str] = set()
    paths: set[str] = set()
    commits: set[str] = set()
    for connector in connectors:
        try:
            config = json.loads(connector.config_json or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        configured_repositories = config.get("repositories", [])
        if isinstance(configured_repositories, str):
            configured_repositories = [configured_repositories]
        if not isinstance(configured_repositories, list):
            configured_repositories = []
        for item in configured_repositories:
            normalized, _ = normalize_repository_identity(item)
            if normalized:
                repositories.add(normalized)

    code_rows = list(await session.execute(
        select(CodeFile.repo_root, CodeFile.last_commit)
        .where(CodeFile.workspace_id == workspace_uuid)
        .distinct()
    ))
    for repo_root, last_commit in code_rows:
        normalized_path = normalize_local_path(repo_root)
        if normalized_path:
            paths.add(normalized_path)
        normalized_commit = normalize_commit(last_commit)
        if normalized_commit:
            commits.add(normalized_commit)

    # A persisted root supplies only an unqualified basename alias. It cannot
    # rescue an explicit mismatch between fully qualified repositories.
    for path in paths:
        name = Path(path).name.strip().lower()
        if name:
            repositories.add(name)
    return repositories, paths, commits


def workspace_relevance(
    component: Component,
    metadata: dict,
    workspace_repositories: set[str],
    workspace_paths: set[str],
    workspace_commits: set[str],
) -> ProjectRelevance:
    if not is_agent_source(component):
        return ProjectRelevance(
            status="relevant",
            reasons=["Source is explicitly assigned to this workspace."],
        )

    repository_raw = (
        metadata.get("repository")
        or metadata.get("repo_full_name")
        or metadata.get("repo")
    )
    repository, repository_is_qualified = normalize_repository_identity(repository_raw)
    qualified_workspace_repositories = {
        value for value in workspace_repositories if "/" in value
    }

    if repository and repository_is_qualified and qualified_workspace_repositories:
        if repository in qualified_workspace_repositories:
            return ProjectRelevance(
                status="relevant",
                reasons=["Session repository matches a configured workspace repository."],
            )
        return ProjectRelevance(
            status="not_relevant",
            reasons=["Session repository conflicts with configured workspace repositories."],
        )

    if repository and repository in workspace_repositories:
        return ProjectRelevance(
            status="relevant",
            reasons=["Session repository matches a workspace repository identity."],
        )

    cwd = normalize_local_path(metadata.get("cwd") or metadata.get("working_directory"))
    cwd_is_inside = bool(
        cwd and workspace_paths
        and any(path_is_within(cwd, root) for root in workspace_paths)
    )
    cwd_is_ancestor = bool(
        cwd and workspace_paths
        and any(path_is_within(root, cwd) for root in workspace_paths)
    )
    cwd_is_outside = bool(
        cwd and workspace_paths and not cwd_is_inside and not cwd_is_ancestor
    )
    if cwd_is_inside:
        return ProjectRelevance(
            status="relevant",
            reasons=["Session working directory is inside an indexed workspace repository."],
        )

    commit = normalize_commit(metadata.get("commit") or metadata.get("head_commit"))
    if commit and any(commits_match(commit, candidate) for candidate in workspace_commits):
        return ProjectRelevance(
            status="relevant",
            reasons=["Session commit matches indexed workspace commit state."],
        )

    if cwd_is_ancestor:
        return ProjectRelevance(
            status="unknown",
            reasons=["Session working directory is an ancestor of the project, not a deterministic match."],
        )
    if cwd_is_outside:
        return ProjectRelevance(
            status="not_relevant",
            reasons=["Session working directory is outside indexed workspace repositories."],
        )
    if not (workspace_repositories or workspace_paths or workspace_commits):
        return ProjectRelevance(
            status="unknown",
            reasons=["No indexed path or configured repository identity is available."],
        )
    return ProjectRelevance(
        status="unknown",
        reasons=["Session metadata is insufficient for a deterministic project match."],
    )


def is_agent_source(component: Component) -> bool:
    source_type = (
        component.source_document.source_type if component.source_document else ""
    ).lower()
    return (
        source_type in {"agent_session", "codex", "claude", "opencode"}
        or source_type.startswith("ai_context")
    )


def normalize_repository_identity(value: object) -> tuple[str | None, bool]:
    raw = str(value or "").strip()
    if not raw:
        return None, False
    raw = raw.replace("\\", "/").rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]

    lowered = raw.lower()
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "ssh://git@github.com/",
        "git://github.com/",
        "git@github.com:",
    ):
        if lowered.startswith(prefix):
            candidate = raw[len(prefix):].strip("/").lower()
            parts = [part for part in candidate.split("/") if part]
            return ("/".join(parts[:2]), True) if len(parts) >= 2 else (None, False)

    if raw.startswith(("/", "./", "../", "~")):
        return Path(raw).name.lower() or None, False
    parts = [part for part in raw.strip("/").split("/") if part]
    if len(parts) == 2:
        return "/".join(part.lower() for part in parts), True
    if len(parts) == 1:
        return parts[0].lower(), False
    return None, False


def normalize_local_path(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        return None
    try:
        return str(expanded.resolve(strict=False))
    except (OSError, RuntimeError):
        return str(expanded)


def path_is_within(candidate: str, root: str) -> bool:
    try:
        Path(candidate).relative_to(Path(root))
        return True
    except ValueError:
        return False


def normalize_commit(value: object) -> str | None:
    commit = str(value or "").strip().lower()
    return commit if re.fullmatch(r"[0-9a-f]{7,64}", commit) else None


def commits_match(left: str, right: str) -> bool:
    return left == right or left.startswith(right) or right.startswith(left)
