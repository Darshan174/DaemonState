from __future__ import annotations

import asyncio
import ast
import hashlib
import json
import os
import posixpath
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, text as sql_text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeEdge, CodeFile, CodeSymbol, RepoEvent
from app.time import utc_now


IGNORED_DIRS = {
    ".git",
    ".gradle",
    ".mypy_cache",
    ".next",
    ".nox",
    ".nuxt",
    ".output",
    ".parcel-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".tox",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "out",
    "target",
    "venv",
}
INDEXED_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".md",
    ".sh",
}
MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
PROJECT_ROOT_MARKERS = {
    ".git",
    "Cargo.toml",
    "Gemfile",
    "build.gradle",
    "composer.json",
    "deno.json",
    "docker-compose.yml",
    "docker-compose.yaml",
    "go.mod",
    "mix.exs",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
}
MAX_INDEXED_FILES = 5_000
MAX_INDEXED_BYTES = 50_000_000
MAX_INDEXED_FILE_BYTES = 400_000
ENV_FILE_RE = re.compile(r"(^|/)\.env($|[.\-])|\.env\.example$|config\.(?:py|js|ts|json|ya?ml)$")
RANKING_VERSION = "objective_file_rank.v3"
_REPO_INDEX_LOCKS: dict[str, asyncio.Lock] = {}
_GENERIC_GOAL_TERMS = {
    "a",
    "add",
    "acceptance",
    "agent",
    "agents",
    "ai",
    "all",
    "also",
    "an",
    "and",
    "are",
    "about",
    "at",
    "be",
    "been",
    "build",
    "builder",
    "builders",
    "but",
    "change",
    "code",
    "complete",
    "context",
    "could",
    "current",
    "criteria",
    "data",
    "do",
    "does",
    "define",
    "doc",
    "docs",
    "document",
    "documentation",
    "engine",
    "enough",
    "ensure",
    "eval",
    "evaluation",
    "evaluations",
    "existing",
    "explicit",
    "feature",
    "file",
    "files",
    "finish",
    "fix",
    "for",
    "founder",
    "founders",
    "from",
    "good",
    "has",
    "have",
    "implement",
    "information",
    "in",
    "into",
    "is",
    "issue",
    "issues",
    "it",
    "its",
    "make",
    "label",
    "labels",
    "need",
    "needs",
    "no",
    "none",
    "not",
    "of",
    "on",
    "or",
    "our",
    "open",
    "phase",
    "product",
    "progress",
    "project",
    "provide",
    "publish",
    "published",
    "repo",
    "run",
    "should",
    "state",
    "support",
    "system",
    "task",
    "test",
    "tests",
    "that",
    "the",
    "there",
    "their",
    "these",
    "this",
    "those",
    "through",
    "update",
    "use",
    "used",
    "user",
    "users",
    "using",
    "verify",
    "was",
    "want",
    "were",
    "what",
    "when",
    "where",
    "which",
    "will",
    "with",
    "without",
    "work",
    "working",
    "would",
    "your",
}


@dataclass(frozen=True)
class IndexedSymbol:
    symbol_type: str
    name: str
    qualified_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    docstring: str | None = None
    signature: str | None = None


@dataclass(frozen=True)
class IndexedImport:
    specifier: str
    start_line: int
    end_line: int
    python_level: int = 0
    python_module: str | None = None


@dataclass(frozen=True)
class IndexedRouteOwner:
    route: str
    handler_name: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class IndexedTestReference:
    test_symbol_name: str
    test_symbol_start_line: int
    target_name: str
    target_specifier: str
    binding_line: int
    reference_line: int


@dataclass(frozen=True)
class PersistedEdgeSpec:
    source_symbol_id: UUID
    target_symbol_id: UUID
    source_path: str
    target_path: str
    edge_type: str
    rule_id: str
    rule_version: str
    evidence_path: str
    evidence_start_line: int | None
    evidence_end_line: int | None
    evidence_json: str
    edge_key: str


@dataclass(frozen=True)
class IndexedFile:
    path: str
    language: str | None
    sha256: str | None
    size: int
    symbols: list[IndexedSymbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    import_hints: list[IndexedImport] = field(default_factory=list)
    route_hints: list[str] = field(default_factory=list)
    route_owners: list[IndexedRouteOwner] = field(default_factory=list)
    test_references: list[IndexedTestReference] = field(default_factory=list)
    is_test: bool = False
    is_config: bool = False
    is_manifest: bool = False


@dataclass
class RepoFrame:
    repo_path: str
    branch: str | None
    base_commit: str | None
    head_commit: str | None
    dirty: bool
    changed_files: list[dict[str, Any]]
    untracked_files: list[str]
    indexed_files: list[IndexedFile]
    package_manifests: dict[str, dict[str, Any]]
    recent_commits: list[dict[str, Any]]
    test_files: list[str]
    manifest_files: list[str]
    env_files: list[str]
    last_indexed_at: str
    snapshot_fingerprint: str = ""
    persistence_available: bool = False
    persistence_reason: str | None = None
    files_added: int = 0
    files_changed: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    edges_indexed: int = 0
    exact_edges: list[dict[str, Any]] = field(default_factory=list)

    def relevant_files_for_goal(self, keywords: set[str], file_hints: list[str]) -> list[dict[str, Any]]:
        hinted = {hint.strip("./") for hint in file_hints}
        normalized_keywords = set(_tokenize(" ".join(sorted(keywords))))
        retrieval_terms = normalized_keywords - _GENERIC_GOAL_TERMS
        requires_tests = bool({"test", "tests", "pytest", "verify"} & normalized_keywords)
        changed_paths = {item["path"] for item in self.changed_files}
        scored: list[
            tuple[
                float,
                str,
                str,
                list[str],
                list[dict[str, int]],
                dict[str, list[str]],
            ]
        ] = []
        for indexed in self.indexed_files:
            explicit_hint = _matches_file_hint(indexed.path, hinted)
            path_tokens = set(_tokenize(indexed.path))
            file_identity = {
                Path(indexed.path).name.lower(),
                Path(indexed.path).stem.lower(),
            }
            symbol_tokens = set(_tokenize(" ".join(symbol.name for symbol in indexed.symbols[:100])))
            import_tokens = set(_tokenize(" ".join(indexed.imports)))
            route_tokens = set(_tokenize(" ".join(indexed.route_hints)))
            matched_path = sorted(retrieval_terms & path_tokens)
            matched_file_name = sorted(retrieval_terms & file_identity)
            matched_symbols = sorted(retrieval_terms & symbol_tokens)
            matched_imports = sorted(retrieval_terms & import_tokens)
            matched_routes = sorted(retrieval_terms & route_tokens)
            matched_support = sorted(set(matched_imports + matched_routes))
            matched_terms = sorted(set(matched_path + matched_symbols + matched_support))
            score = 0.0
            if explicit_hint:
                score += 5.0
            score += 4.0 * len(matched_file_name)
            score += 1.20 * len(matched_path)
            score += 0.80 * len(matched_symbols)
            score += 0.35 * len(matched_support)
            if matched_terms and not indexed.is_test:
                # Core implementation should beat a test file that only repeats
                # the same broad nouns from the objective.
                score += 0.75
            if indexed.is_test and requires_tests and matched_terms:
                score += 0.30
            if "api" in retrieval_terms and "/api/" in f"/{indexed.path}":
                score += 0.40
            if "cli" in retrieval_terms and "/cli/" in f"/{indexed.path}":
                score += 0.40
            # Dirty working-tree state is only a tie-breaker. An unrelated local
            # edit must never become "affected code" without objective evidence.
            if indexed.path in changed_paths and (matched_terms or score >= 5.0):
                score += 0.20
            if score <= 0:
                continue
            line_ranges = _matching_symbol_ranges(indexed, retrieval_terms)
            reason = (
                "explicit_goal_file_hint"
                if explicit_hint
                else _file_reason(indexed, normalized_keywords)
            )
            scored.append((
                round(score, 6),
                indexed.path,
                reason,
                matched_terms,
                line_ranges,
                {
                    "file_name": matched_file_name,
                    "path": matched_path,
                    "symbols": matched_symbols,
                    "imports": matched_imports,
                    "routes": matched_routes,
                },
            ))

        scored.sort(key=lambda item: (-item[0], item[1]))
        top = scored[:16]
        if not top:
            fallback_paths = [
                *[item["path"] for item in self.changed_files[:8]],
                *self.test_files[:4],
                *self.manifest_files[:3],
            ]
            top = [
                (0.1, path, "repo_state_fallback", [], [], {})
                for path in dict.fromkeys(fallback_paths)
            ]

        indexed_by_path = {item.path: item for item in self.indexed_files}
        return [
            {
                "path": path,
                "reason": reason,
                "ranking_score": score,
                "ranking_version": RANKING_VERSION,
                "matched_terms": matched_terms,
                "match_basis": match_basis,
                "line_ranges": line_ranges,
                "lane": "code_and_tests",
                "exists": path in indexed_by_path or (Path(self.repo_path) / path).exists(),
                "sha256": indexed_by_path[path].sha256 if path in indexed_by_path else _sha256_file(Path(self.repo_path) / path),
                "is_test": indexed_by_path[path].is_test if path in indexed_by_path else _is_test_file(path, ""),
            }
            for score, path, reason, matched_terms, line_ranges, match_basis in top
        ]

    def affected_code_for_goal(
        self,
        keywords: set[str],
        file_hints: list[str],
    ) -> dict[str, Any] | None:
        """Build the bounded UI contract from objective matches and exact current edges."""
        if not self.persistence_available:
            return None
        normalized_hints = {hint.strip("./") for hint in file_hints}
        objective_matches = [
            item for item in self.relevant_files_for_goal(keywords, file_hints)
            if item.get("reason") != "repo_state_fallback" and item.get("sha256")
            and (
                item.get("reason") == "explicit_goal_file_hint"
                or _eligible_affected_path(str(item.get("path") or ""))
            )
            and (
                not item.get("is_test")
                or (
                    item.get("reason") == "explicit_goal_file_hint"
                    and _matches_file_hint(
                        str(item.get("path") or ""), normalized_hints
                    )
                )
            )
        ]
        explicit_matches = [
            item for item in objective_matches
            if item.get("reason") == "explicit_goal_file_hint"
        ]
        exact_name_matches = [
            item for item in objective_matches
            if (item.get("match_basis") or {}).get("file_name")
        ]
        relevant = (explicit_matches or exact_name_matches or objective_matches)[:12]
        if not relevant:
            return None
        current_edges = [
            edge for edge in self.exact_edges
            if edge.get("snapshot_fingerprint") == self.snapshot_fingerprint
            and edge.get("rule_id") != "legacy.unspecified"
        ]
        files: list[dict[str, Any]] = []
        for item in relevant:
            path = str(item["path"])
            test_edges = sorted(
                (
                    edge for edge in current_edges
                    if edge.get("rule_id") == "test_path_match.v1"
                    and edge.get("target_path") == path
                ),
                key=lambda edge: str(edge.get("source_path") or ""),
            )[:4]
            related_tests = [
                {
                    "path": edge["source_path"],
                    "why": "Linked by the repository's exact test path.",
                    "edge_key": edge["edge_key"],
                    "rule_id": edge["rule_id"],
                }
                for edge in test_edges
            ]
            impact_paths = [
                {
                    "paths": [edge["source_path"], path],
                    "why": "Exact test path link.",
                }
                for edge in test_edges[:3]
            ]
            structural_edges = sorted(
                (
                    edge for edge in current_edges
                    if edge.get("rule_id") in {
                        "local_module_import.v1", "route_handler_owner.v1"
                    }
                    and path in {edge.get("source_path"), edge.get("target_path")}
                ),
                key=lambda edge: (
                    str(edge.get("rule_id") or ""),
                    str(edge.get("source_path") or ""),
                    str(edge.get("target_path") or ""),
                ),
            )
            for edge in structural_edges:
                if len(impact_paths) >= 3:
                    break
                source_path = str(edge.get("source_path") or path)
                target_path = str(edge.get("target_path") or path)
                paths = [source_path]
                if target_path != source_path:
                    paths.append(target_path)
                impact_paths.append({
                    "paths": paths,
                    "why": (
                        "Exact local import link."
                        if edge.get("rule_id") == "local_module_import.v1"
                        else "Exact route-to-handler ownership in this file."
                    ),
                })
            matched_terms = list(item.get("matched_terms") or [])
            files.append({
                "path": path,
                "role": "related_test" if item.get("is_test") else "likely_implementation",
                "match_strength": _file_match_strength(item),
                "match_basis": item.get("match_basis") or {},
                "why": _human_file_reason(item),
                "sha256": item["sha256"],
                "line_ranges": list(item.get("line_ranges") or []),
                "evidence": [{
                    "kind": (
                        "explicit_file"
                        if item.get("reason") == "explicit_goal_file_hint"
                        else "objective_match"
                    ),
                    "terms": matched_terms,
                }],
                "related_tests": related_tests,
                "impact_paths": impact_paths,
            })
        return {
            "schema_version": "affected_code.v1",
            "snapshot": {
                "head_commit": self.head_commit,
                "dirty": self.dirty,
                "snapshot_fingerprint": self.snapshot_fingerprint,
                "indexed_at": self.last_indexed_at,
            },
            "files": files,
            "truncated": len(objective_matches) > 12,
        }

    def to_manifest(self, keywords: set[str] | None = None, file_hints: list[str] | None = None) -> dict[str, Any]:
        relevant_files = self.relevant_files_for_goal(keywords or set(), file_hints or [])
        manifest = {
            "repo_path": self.repo_path,
            "branch": self.branch,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "dirty": self.dirty,
            "changed_files": self.changed_files,
            "untracked_files": self.untracked_files,
            "relevant_files": relevant_files,
            "test_files": self.test_files,
            "manifest_files": self.manifest_files,
            "env_files": self.env_files,
            "last_indexed_at": self.last_indexed_at,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "ranking_version": RANKING_VERSION,
            "persistence": {
                "available": self.persistence_available,
                "reason": self.persistence_reason,
            },
        }
        fingerprint_state = {
            key: manifest[key]
            for key in (
                "repo_path",
                "branch",
                "base_commit",
                "head_commit",
                "dirty",
                "changed_files",
                "untracked_files",
                "relevant_files",
                "test_files",
                "manifest_files",
                "env_files",
            )
        }
        manifest["state_fingerprint"] = hashlib.sha256(json.dumps(
            fingerprint_state,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return manifest


class RepoIndexer:
    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def inspect_repo(
        self,
        repo_path: str | Path,
        *,
        workspace_id: str | UUID | None = None,
        persist: bool = True,
    ) -> RepoFrame:
        root = Path(repo_path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"repo path does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"repo path is not a directory: {root}")
        # Filesystem traversal, parsing, and git subprocesses are synchronous.
        # Keep them off the API event loop so one large repository cannot stall
        # health checks and unrelated requests.
        frame = await asyncio.to_thread(_scan_repo, root)
        if persist and self.session is not None:
            await self._persist_frame(frame, workspace_id)
        elif persist:
            frame.persistence_available = False
            frame.persistence_reason = "no_async_session"
        else:
            frame.persistence_available = False
            frame.persistence_reason = "file_output_only"
        return frame

    async def _persist_frame(
        self,
        frame: RepoFrame,
        workspace_id: str | UUID | None,
    ) -> None:
        workspace_uuid = _uuid_or_none(workspace_id)
        if workspace_uuid is None:
            frame.persistence_available = False
            frame.persistence_reason = "workspace_required_for_persistence"
            return
        lock_key = f"{workspace_uuid}:{frame.repo_path}"
        process_lock = _REPO_INDEX_LOCKS.setdefault(lock_key, asyncio.Lock())
        await process_lock.acquire()
        try:
            if self.session.get_bind().dialect.name == "postgresql":
                await self.session.execute(
                    sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": lock_key},
                )
            async with self.session.begin_nested():
                await self._delete_inactive_roots(workspace_uuid, frame.repo_path)
                existing_files = list(await self.session.scalars(
                    select(CodeFile).where(
                        CodeFile.repo_root == frame.repo_path,
                        CodeFile.workspace_id == workspace_uuid,
                    )
                ))
                existing_by_path: dict[str, CodeFile] = {}
                for code_file in existing_files:
                    if code_file.path in existing_by_path:
                        raise ValueError(
                            "duplicate repository file identities; re-index this workspace "
                            "after resolving duplicate code_files rows"
                        )
                    existing_by_path[code_file.path] = code_file
                indexed_by_path = {item.path: item for item in frame.indexed_files}
                unchanged_paths = {
                    path for path, indexed in indexed_by_path.items()
                    if path in existing_by_path
                    and existing_by_path[path].sha256 == indexed.sha256
                }
                changed_paths = set(indexed_by_path) & set(existing_by_path) - unchanged_paths
                added_paths = set(indexed_by_path) - set(existing_by_path)
                deleted_paths = set(existing_by_path) - set(indexed_by_path)

                replaced_file_ids = [
                    existing_by_path[path].id
                    for path in sorted(changed_paths | deleted_paths)
                ]
                replaced_symbol_ids: list[UUID] = []
                if replaced_file_ids:
                    replaced_symbol_ids = list(await self.session.scalars(
                        select(CodeSymbol.id).where(
                            CodeSymbol.code_file_id.in_(replaced_file_ids)
                        )
                    ))
                if replaced_symbol_ids:
                    await self.session.execute(
                        delete(CodeEdge).where(or_(
                            CodeEdge.source_symbol_id.in_(replaced_symbol_ids),
                            CodeEdge.target_symbol_id.in_(replaced_symbol_ids),
                        ))
                    )
                    await self.session.execute(
                        delete(CodeSymbol).where(
                            CodeSymbol.code_file_id.in_(replaced_file_ids)
                        )
                    )
                deleted_file_ids = [
                    existing_by_path[path].id for path in sorted(deleted_paths)
                ]
                if deleted_file_ids:
                    await self.session.execute(
                        delete(CodeFile).where(CodeFile.id.in_(deleted_file_ids))
                    )

                for path in sorted(unchanged_paths):
                    code_file = existing_by_path[path]
                    indexed = indexed_by_path[path]
                    code_file.last_commit = frame.head_commit
                    code_file.language = indexed.language
                    code_file.size = indexed.size
                    code_file.is_test = indexed.is_test

                for path in sorted(changed_paths):
                    code_file = existing_by_path[path]
                    indexed = indexed_by_path[path]
                    code_file.language = indexed.language
                    code_file.sha256 = indexed.sha256
                    code_file.last_commit = frame.head_commit
                    code_file.size = indexed.size
                    code_file.is_test = indexed.is_test
                    await self.session.flush()
                    self._add_symbols(code_file, indexed)

                for path in sorted(added_paths):
                    indexed = indexed_by_path[path]
                    code_file = CodeFile(
                        workspace_id=workspace_uuid,
                        repo_root=frame.repo_path,
                        path=indexed.path,
                        identity_key=_file_identity_key(
                            workspace_uuid, frame.repo_path, indexed.path
                        ),
                        language=indexed.language,
                        sha256=indexed.sha256,
                        last_commit=frame.head_commit,
                        size=indexed.size,
                        is_test=indexed.is_test,
                    )
                    self.session.add(code_file)
                    await self.session.flush()
                    self._add_symbols(code_file, indexed)

                await self.session.flush()
                final_files = list(await self.session.scalars(
                    select(CodeFile).where(
                        CodeFile.repo_root == frame.repo_path,
                        CodeFile.workspace_id == workspace_uuid,
                    )
                ))
                final_file_by_path = {item.path: item for item in final_files}
                final_file_ids = [item.id for item in final_files]
                final_symbols = list(await self.session.scalars(
                    select(CodeSymbol).where(
                        CodeSymbol.code_file_id.in_(final_file_ids)
                    )
                )) if final_file_ids else []
                symbols_by_file: dict[UUID, list[CodeSymbol]] = {}
                for symbol in final_symbols:
                    symbols_by_file.setdefault(symbol.code_file_id, []).append(symbol)

                desired_edges = _resolve_exact_edges(
                    frame,
                    final_file_by_path,
                    symbols_by_file,
                )
                supported_rules = {
                    "local_module_import.v1",
                    "route_handler_owner.v1",
                    "test_path_match.v1",
                    "test_symbol_match.v1",
                }
                existing_edges = list(await self.session.scalars(
                    select(CodeEdge).where(
                        CodeEdge.rule_id.in_(supported_rules),
                        or_(
                            CodeEdge.source_symbol_id.in_([item.id for item in final_symbols]),
                            CodeEdge.target_symbol_id.in_([item.id for item in final_symbols]),
                        ),
                    )
                )) if final_symbols else []
                existing_edge_by_key = {item.edge_key: item for item in existing_edges}
                desired_by_key = {item.edge_key: item for item in desired_edges}
                stale_edge_ids = [
                    edge.id for key, edge in existing_edge_by_key.items()
                    if key not in desired_by_key
                ]
                if stale_edge_ids:
                    await self.session.execute(
                        delete(CodeEdge).where(CodeEdge.id.in_(stale_edge_ids))
                    )
                for edge_key, spec in desired_by_key.items():
                    edge = existing_edge_by_key.get(edge_key)
                    if edge is None:
                        edge = CodeEdge(
                            source_symbol_id=spec.source_symbol_id,
                            target_symbol_id=spec.target_symbol_id,
                            edge_type=spec.edge_type,
                            edge_key=spec.edge_key,
                            rule_id=spec.rule_id,
                            rule_version=spec.rule_version,
                            evidence_path=spec.evidence_path,
                            evidence_start_line=spec.evidence_start_line,
                            evidence_end_line=spec.evidence_end_line,
                            evidence_json=spec.evidence_json,
                            evidence_sha256=_sha256_text(spec.evidence_json),
                        )
                        self.session.add(edge)
                    edge.snapshot_commit = frame.head_commit
                    edge.snapshot_dirty = frame.dirty
                    edge.snapshot_fingerprint = frame.snapshot_fingerprint

                known_commits = set(await self.session.scalars(
                    select(RepoEvent.commit_sha).where(
                        RepoEvent.workspace_id == workspace_uuid,
                        RepoEvent.commit_sha.is_not(None),
                    )
                ))
                for commit in frame.recent_commits:
                    commit_sha = commit.get("commit_sha")
                    if commit_sha and commit_sha in known_commits:
                        continue
                    self.session.add(RepoEvent(
                        workspace_id=workspace_uuid,
                        commit_sha=commit_sha,
                        branch=frame.branch,
                        author=commit.get("author"),
                        message=commit.get("message"),
                        changed_files_json=json.dumps(
                            commit.get("changed_files", []),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        created_at=_datetime_from_iso(commit.get("created_at")) or utc_now(),
                    ))
                await self.session.flush()
                frame.files_added = len(added_paths)
                frame.files_changed = len(changed_paths)
                frame.files_unchanged = len(unchanged_paths)
                frame.files_deleted = len(deleted_paths)
                frame.edges_indexed = len(desired_edges)
                frame.exact_edges = [
                    {
                        "source_path": spec.source_path,
                        "target_path": spec.target_path,
                        "edge_type": spec.edge_type,
                        "edge_key": spec.edge_key,
                        "rule_id": spec.rule_id,
                        "rule_version": spec.rule_version,
                        "evidence_path": spec.evidence_path,
                        "evidence_start_line": spec.evidence_start_line,
                        "evidence_end_line": spec.evidence_end_line,
                        "evidence": json.loads(spec.evidence_json),
                        "snapshot_fingerprint": frame.snapshot_fingerprint,
                    }
                    for spec in desired_edges
                ]
            frame.persistence_available = True
            frame.persistence_reason = None
        except (SQLAlchemyError, ValueError) as exc:
            frame.persistence_available = False
            frame.persistence_reason = f"repo_index_persistence_unavailable: {exc.__class__.__name__}"
        finally:
            process_lock.release()

    def _add_symbols(self, code_file: CodeFile, indexed: IndexedFile) -> None:
        for symbol in indexed.symbols[:300]:
            self.session.add(CodeSymbol(
                code_file_id=code_file.id,
                identity_key=_symbol_identity_key(code_file.id, symbol),
                symbol_type=symbol.symbol_type,
                name=symbol.name[:255],
                qualified_name=(
                    symbol.qualified_name[:512]
                    if symbol.qualified_name else None
                ),
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                docstring=symbol.docstring,
                signature=symbol.signature,
            ))

    async def _delete_inactive_roots(
        self,
        workspace_id: UUID,
        active_repo_root: str,
    ) -> None:
        inactive_file_ids = list(await self.session.scalars(
            select(CodeFile.id).where(
                CodeFile.workspace_id == workspace_id,
                or_(
                    CodeFile.repo_root != active_repo_root,
                    CodeFile.repo_root.is_(None),
                ),
            )
        ))
        if not inactive_file_ids:
            return
        inactive_symbol_ids = list(await self.session.scalars(
            select(CodeSymbol.id).where(
                CodeSymbol.code_file_id.in_(inactive_file_ids)
            )
        ))
        if inactive_symbol_ids:
            await self.session.execute(delete(CodeEdge).where(or_(
                CodeEdge.source_symbol_id.in_(inactive_symbol_ids),
                CodeEdge.target_symbol_id.in_(inactive_symbol_ids),
            )))
            await self.session.execute(delete(CodeSymbol).where(
                CodeSymbol.id.in_(inactive_symbol_ids)
            ))
        await self.session.execute(delete(CodeFile).where(
            CodeFile.id.in_(inactive_file_ids)
        ))


async def inspect_repo(
    repo_path: str | Path,
    *,
    session: AsyncSession | None = None,
    workspace_id: str | UUID | None = None,
    persist: bool = True,
) -> RepoFrame:
    return await RepoIndexer(session).inspect_repo(
        repo_path,
        workspace_id=workspace_id,
        persist=persist,
    )


def _scan_repo(root: Path) -> RepoFrame:
    git_state = _git_state(root)
    indexed_files = [_index_file(root, path) for path in _iter_interesting_files(root)]
    indexed_files = [item for item in indexed_files if item is not None]
    package_manifests = _package_manifests(root, indexed_files)
    test_files = sorted(item.path for item in indexed_files if item.is_test)
    manifest_files = sorted(item.path for item in indexed_files if item.is_manifest)
    env_files = sorted(item.path for item in indexed_files if item.is_config)
    snapshot_fingerprint = _snapshot_fingerprint(
        str(root),
        git_state["head_commit"],
        indexed_files,
        git_state["changed_files"],
    )
    return RepoFrame(
        repo_path=str(root),
        branch=git_state["branch"],
        base_commit=git_state["base_commit"],
        head_commit=git_state["head_commit"],
        dirty=git_state["dirty"],
        changed_files=git_state["changed_files"],
        untracked_files=git_state["untracked_files"],
        indexed_files=sorted(indexed_files, key=lambda item: item.path),
        package_manifests=package_manifests,
        recent_commits=git_state["recent_commits"],
        test_files=test_files,
        manifest_files=manifest_files,
        env_files=env_files,
        last_indexed_at=utc_now().isoformat(timespec="seconds") + "Z",
        snapshot_fingerprint=snapshot_fingerprint,
    )


def _resolve_exact_edges(
    frame: RepoFrame,
    files_by_path: dict[str, CodeFile],
    symbols_by_file: dict[UUID, list[CodeSymbol]],
) -> list[PersistedEdgeSpec]:
    indexed_by_path = {item.path: item for item in frame.indexed_files}
    module_symbol_by_path: dict[str, CodeSymbol] = {}
    for path, code_file in files_by_path.items():
        modules = [
            symbol for symbol in symbols_by_file.get(code_file.id, [])
            if symbol.symbol_type == "module" and symbol.qualified_name == path
        ]
        if len(modules) == 1:
            module_symbol_by_path[path] = modules[0]

    python_modules: dict[str, list[str]] = {}
    for path in indexed_by_path:
        module_name = _python_module_for_path(path)
        if module_name is not None:
            python_modules.setdefault(module_name, []).append(path)

    specs: list[PersistedEdgeSpec] = []
    for path, indexed in indexed_by_path.items():
        source_module = module_symbol_by_path.get(path)
        if source_module is None:
            continue
        for hint in indexed.import_hints:
            target_path: str | None = None
            if indexed.language == "python":
                module_name = _resolve_python_import_module(path, hint)
                candidates = python_modules.get(module_name or "", [])
                if len(candidates) == 1:
                    target_path = candidates[0]
            elif indexed.language in {"javascript", "javascript-react", "typescript", "typescript-react"}:
                target_path = _resolve_javascript_import_path(
                    path, hint.specifier, indexed_by_path
                )
            if not target_path or target_path == path:
                continue
            target_module = module_symbol_by_path.get(target_path)
            if target_module is None:
                continue
            evidence = {
                "importer": path,
                "specifier": hint.specifier,
                "target": target_path,
            }
            specs.append(_edge_spec(
                source_module,
                target_module,
                source_path=path,
                target_path=target_path,
                edge_type="imports",
                rule_id="local_module_import.v1",
                evidence_path=path,
                start_line=hint.start_line,
                end_line=hint.end_line,
                evidence=evidence,
            ))

        file_symbols = symbols_by_file.get(files_by_path[path].id, [])
        for owner in indexed.route_owners:
            routes = [
                symbol for symbol in file_symbols
                if symbol.symbol_type == "route" and symbol.name == owner.route
            ]
            handlers = [
                symbol for symbol in file_symbols
                if symbol.symbol_type in {"function", "async_function"}
                and symbol.name == owner.handler_name
            ]
            if len(routes) != 1 or len(handlers) != 1:
                continue
            evidence = {
                "file": path,
                "route": owner.route,
                "handler": owner.handler_name,
            }
            specs.append(_edge_spec(
                routes[0],
                handlers[0],
                source_path=path,
                target_path=path,
                edge_type="owned_by",
                rule_id="route_handler_owner.v1",
                evidence_path=path,
                start_line=owner.start_line,
                end_line=owner.end_line,
                evidence=evidence,
            ))

    for test_path, test_file in indexed_by_path.items():
        if not test_file.is_test:
            continue
        candidates = _test_target_candidates(test_path, indexed_by_path)
        if len(candidates) != 1:
            continue
        target_path = candidates[0]
        source_module = module_symbol_by_path.get(test_path)
        target_module = module_symbol_by_path.get(target_path)
        if source_module is None or target_module is None:
            continue
        evidence = {
            "test_path": test_path,
            "target_path": target_path,
            "test_sha256": test_file.sha256,
            "target_sha256": indexed_by_path[target_path].sha256,
            "transformation": "exact_test_path",
        }
        pair_spec = _edge_spec(
            source_module,
            target_module,
            source_path=test_path,
            target_path=target_path,
            edge_type="tests",
            rule_id="test_path_match.v1",
            evidence_path=test_path,
            start_line=None,
            end_line=None,
            evidence=evidence,
        )
        specs.append(pair_spec)

        source_symbols = symbols_by_file.get(files_by_path[test_path].id, [])
        target_symbols = symbols_by_file.get(files_by_path[target_path].id, [])
        for reference in test_file.test_references:
            if not _test_reference_resolves_to_target(
                test_path,
                target_path,
                test_file,
                reference,
                indexed_by_path,
            ):
                continue
            source_matches = [
                symbol for symbol in source_symbols
                if symbol.name == reference.test_symbol_name
                and symbol.start_line == reference.test_symbol_start_line
                and symbol.symbol_type in {"function", "async_function", "test"}
            ]
            target_matches = [
                symbol for symbol in target_symbols
                if symbol.name == reference.target_name
                and symbol.symbol_type not in {"module", "import", "route", "test"}
            ]
            if len(source_matches) != 1 or len(target_matches) != 1:
                continue
            symbol_evidence = {
                "pairing_edge_key": pair_spec.edge_key,
                "test_path": test_path,
                "target_path": target_path,
                "test_symbol": source_matches[0].qualified_name,
                "target_symbol": target_matches[0].qualified_name,
                "binding_specifier": reference.target_specifier,
                "binding_line": reference.binding_line,
                "reference_line": reference.reference_line,
                "test_sha256": test_file.sha256,
                "target_sha256": indexed_by_path[target_path].sha256,
            }
            specs.append(_edge_spec(
                source_matches[0],
                target_matches[0],
                source_path=test_path,
                target_path=target_path,
                edge_type="tests",
                rule_id="test_symbol_match.v1",
                evidence_path=test_path,
                start_line=reference.reference_line,
                end_line=reference.reference_line,
                evidence=symbol_evidence,
            ))

    unique = {spec.edge_key: spec for spec in specs}
    return [unique[key] for key in sorted(unique)]


def _edge_spec(
    source: CodeSymbol,
    target: CodeSymbol,
    *,
    source_path: str,
    target_path: str,
    edge_type: str,
    rule_id: str,
    evidence_path: str,
    start_line: int | None,
    end_line: int | None,
    evidence: dict[str, Any],
) -> PersistedEdgeSpec:
    rule_version = "1"
    edge_key = _canonical_hash([
        rule_id,
        rule_version,
        str(source.id),
        str(target.id),
        evidence_path,
        start_line,
        end_line,
    ])
    return PersistedEdgeSpec(
        source_symbol_id=source.id,
        target_symbol_id=target.id,
        source_path=source_path,
        target_path=target_path,
        edge_type=edge_type,
        rule_id=rule_id,
        rule_version=rule_version,
        evidence_path=evidence_path,
        evidence_start_line=start_line,
        evidence_end_line=end_line,
        evidence_json=json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        edge_key=edge_key,
    )


def _python_module_for_path(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    without_suffix = path[:-3]
    if without_suffix == "__init__":
        return ""
    if without_suffix.endswith("/__init__"):
        without_suffix = without_suffix[:-9]
    return without_suffix.replace("/", ".")


def _resolve_python_import_module(path: str, hint: IndexedImport) -> str | None:
    if hint.python_level <= 0:
        return hint.python_module
    source_module = _python_module_for_path(path)
    if source_module is None:
        return None
    if path.endswith("/__init__.py") or path == "__init__.py":
        package_parts = [part for part in source_module.split(".") if part]
    else:
        package_parts = [part for part in source_module.split(".")[:-1] if part]
    levels_up = hint.python_level - 1
    if levels_up > len(package_parts):
        return None
    if levels_up:
        package_parts = package_parts[:-levels_up]
    if hint.python_module:
        package_parts.extend(hint.python_module.split("."))
    return ".".join(package_parts)


def _resolve_javascript_import_path(
    source_path: str,
    specifier: str,
    indexed_by_path: dict[str, IndexedFile],
) -> str | None:
    if not specifier.startswith(("./", "../")):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), specifier))
    supported = (".js", ".jsx", ".ts", ".tsx")
    suffix = Path(base).suffix
    if suffix:
        return base if suffix in supported and base in indexed_by_path else None
    candidates = [
        candidate
        for candidate in [
            *(base + extension for extension in supported),
            *(posixpath.join(base, "index" + extension) for extension in supported),
        ]
        if candidate in indexed_by_path
    ]
    return candidates[0] if len(candidates) == 1 else None


def _test_target_candidates(
    test_path: str,
    indexed_by_path: dict[str, IndexedFile],
) -> list[str]:
    path = Path(test_path)
    candidates: set[str] = set()
    if path.suffix == ".py" and path.name.startswith("test_"):
        production_name = path.name[5:]
        candidates.add((path.parent / production_name).as_posix())
        parts = list(path.parts)
        if "tests" in parts:
            test_index = parts.index("tests")
            relative_parent = parts[test_index + 1:-1]
            for prefix in ((), ("app",), ("src",)):
                candidates.add(Path(*prefix, *relative_parent, production_name).as_posix())
    match = re.match(r"^(.+)\.(?:test|spec)\.(js|jsx|ts|tsx)$", path.name)
    if match:
        stem = match.group(1)
        parent_parts = list(path.parent.parts)
        if "__tests__" in parent_parts:
            parent_parts.remove("__tests__")
        parent = Path(*parent_parts)
        for extension in ("js", "jsx", "ts", "tsx"):
            candidates.add((parent / f"{stem}.{extension}").as_posix())
    return sorted(
        candidate for candidate in candidates
        if candidate in indexed_by_path and not indexed_by_path[candidate].is_test
    )


def _test_reference_resolves_to_target(
    test_path: str,
    target_path: str,
    test_file: IndexedFile,
    reference: IndexedTestReference,
    indexed_by_path: dict[str, IndexedFile],
) -> bool:
    if test_file.language == "python":
        specifier = reference.target_specifier
        level = len(specifier) - len(specifier.lstrip("."))
        module = specifier[level:]
        resolved = _resolve_python_import_module(
            test_path,
            IndexedImport(
                specifier=specifier,
                start_line=reference.binding_line,
                end_line=reference.binding_line,
                python_level=level,
                python_module=module or None,
            ),
        )
        return resolved == _python_module_for_path(target_path)
    if test_file.language in {
        "javascript", "javascript-react", "typescript", "typescript-react"
    }:
        return _resolve_javascript_import_path(
            test_path, reference.target_specifier, indexed_by_path
        ) == target_path
    return False


def _iter_interesting_files(root: Path) -> list[Path]:
    candidates = _git_visible_files(root)
    if candidates is None:
        candidates = _filesystem_visible_files(root)

    files: list[Path] = []
    total_bytes = 0
    for path in candidates:
        if path.is_symlink() or _is_in_ignored_directory(root, path):
            continue
        if not (
            path.name in MANIFEST_NAMES
            or path.suffix in INDEXED_SUFFIXES
            or ENV_FILE_RE.search(path.as_posix())
        ):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_INDEXED_FILE_BYTES:
            continue
        files.append(path)
        total_bytes += size
        if len(files) > MAX_INDEXED_FILES:
            raise ValueError(
                f"project exceeds the {MAX_INDEXED_FILES:,} indexed-file safety limit"
            )
        if total_bytes > MAX_INDEXED_BYTES:
            raise ValueError(
                f"project exceeds the {MAX_INDEXED_BYTES // 1_000_000} MB indexing safety limit"
            )
    return sorted(files)


def _git_visible_files(root: Path) -> list[Path] | None:
    """Return tracked and non-ignored untracked files, or None outside a Git worktree."""
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None

    files: list[Path] = []
    for raw_path in proc.stdout.split(b"\0"):
        if not raw_path:
            continue
        candidate = root / os.fsdecode(raw_path)
        if candidate.is_symlink():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_relative_to(root) or not resolved.is_file():
            continue
        files.append(resolved)
    return sorted(set(files))


def _filesystem_visible_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current_root, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names[:] = sorted(
            name for name in dir_names
            if name not in IGNORED_DIRS
            and not (Path(current_root) / name).is_symlink()
        )
        for file_name in sorted(file_names):
            path = Path(current_root) / file_name
            if not path.is_symlink():
                files.append(path)
    return sorted(files)


def _is_in_ignored_directory(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in IGNORED_DIRS for part in relative.parts[:-1])


def _index_file(root: Path, path: Path) -> IndexedFile | None:
    rel = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_INDEXED_FILE_BYTES:
        return None
    sha = hashlib.sha256(raw).hexdigest()
    language = _language_for(path)
    text = _decode(raw)
    symbols: list[IndexedSymbol] = []
    imports: list[str] = []
    import_hints: list[IndexedImport] = []
    route_hints: list[str] = []
    route_owners: list[IndexedRouteOwner] = []
    test_references: list[IndexedTestReference] = []
    test_symbols: list[IndexedSymbol] = []
    if text is not None:
        if path.suffix == ".py":
            symbols, imports, route_hints, import_hints, route_owners = _python_symbols(
                text, rel
            )
            test_references = _python_test_references(text, rel)
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            symbols, imports, route_hints, import_hints, route_owners = _javascript_symbols(
                text, rel
            )
            test_references, test_symbols = _javascript_test_references(text, rel)
    module_symbol = IndexedSymbol(
        symbol_type="module",
        name=rel,
        qualified_name=rel,
    )
    symbols = [module_symbol, *_dedupe_symbols([*symbols, *test_symbols])[:299]]
    is_test = _is_test_file(rel, text or "")
    is_config = bool(ENV_FILE_RE.search(rel))
    is_manifest = path.name in MANIFEST_NAMES
    return IndexedFile(
        path=rel,
        language=language,
        sha256=sha,
        size=len(raw),
        symbols=symbols,
        imports=imports,
        import_hints=import_hints,
        route_hints=route_hints,
        route_owners=route_owners,
        test_references=test_references,
        is_test=is_test,
        is_config=is_config,
        is_manifest=is_manifest,
    )


def _python_symbols(
    text: str,
    rel_path: str,
) -> tuple[
    list[IndexedSymbol],
    list[str],
    list[str],
    list[IndexedImport],
    list[IndexedRouteOwner],
]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return [], [], [], [], []
    symbols: list[IndexedSymbol] = []
    imports: list[str] = []
    import_hints: list[IndexedImport] = []
    routes: list[str] = []
    route_owners: list[IndexedRouteOwner] = []
    module_name = rel_path.removesuffix(".py").replace("/", ".")
    route_bindings = _python_route_bindings(module)

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                import_hints.append(IndexedImport(
                    specifier=alias.name,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    python_module=alias.name,
                ))
                symbols.append(IndexedSymbol(
                    symbol_type="import",
                    name=alias.asname or alias.name,
                    qualified_name=alias.name,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                ))
        elif isinstance(node, ast.ImportFrom):
            imported_from = "." * int(node.level or 0) + (node.module or "")
            import_hints.append(IndexedImport(
                specifier=imported_from,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                python_level=int(node.level or 0),
                python_module=node.module,
            ))
            for alias in node.names:
                name = f"{imported_from}.{alias.name}".strip(".")
                imports.append(name)
                symbols.append(IndexedSymbol(
                    symbol_type="import",
                    name=alias.asname or alias.name,
                    qualified_name=name,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(IndexedSymbol(
                symbol_type="function" if isinstance(node, ast.FunctionDef) else "async_function",
                name=node.name,
                qualified_name=f"{module_name}.{node.name}",
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                docstring=ast.get_docstring(node),
                signature=_python_signature(node),
            ))
            for route, start_line, end_line in _route_decorators(node, route_bindings):
                routes.append(route)
                route_owners.append(IndexedRouteOwner(
                    route=route,
                    handler_name=node.name,
                    start_line=start_line,
                    end_line=end_line,
                ))
                symbols.append(IndexedSymbol(
                    symbol_type="route",
                    name=route,
                    qualified_name=f"{module_name}.{node.name}:{route}",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                ))
        elif isinstance(node, ast.ClassDef):
            symbols.append(IndexedSymbol(
                symbol_type="class",
                name=node.name,
                qualified_name=f"{module_name}.{node.name}",
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                docstring=ast.get_docstring(node),
            ))
    return (
        _dedupe_symbols(symbols),
        sorted(set(imports)),
        sorted(set(routes)),
        import_hints,
        route_owners,
    )


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.posonlyargs + node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    args.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"


def _python_test_references(text: str, rel_path: str) -> list[IndexedTestReference]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return []
    direct: dict[str, tuple[str, str, int]] = {}
    namespaces: dict[str, tuple[str, int]] = {}
    for statement in module.body:
        if isinstance(statement, ast.ImportFrom) and all(
            alias.name != "*" for alias in statement.names
        ):
            specifier = "." * int(statement.level or 0) + (statement.module or "")
            for alias in statement.names:
                direct[alias.asname or alias.name] = (
                    specifier,
                    alias.name,
                    statement.lineno,
                )
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                namespaces[alias.asname or alias.name.split(".")[0]] = (
                    alias.name,
                    statement.lineno,
                )
    references: list[IndexedTestReference] = []
    for function in module.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not function.name.startswith("test_"):
            continue
        for node in ast.walk(function):
            expression = node.func if isinstance(node, ast.Call) else None
            if isinstance(expression, ast.Name) and expression.id in direct:
                specifier, target_name, binding_line = direct[expression.id]
            elif (
                isinstance(expression, ast.Attribute)
                and isinstance(expression.value, ast.Name)
                and expression.value.id in namespaces
            ):
                specifier, binding_line = namespaces[expression.value.id]
                target_name = expression.attr
            else:
                continue
            references.append(IndexedTestReference(
                test_symbol_name=function.name,
                test_symbol_start_line=function.lineno,
                target_name=target_name,
                target_specifier=specifier,
                binding_line=binding_line,
                reference_line=node.lineno,
            ))
    unique = {
        (item.test_symbol_name, item.target_name, item.reference_line): item
        for item in references
    }
    return [unique[key] for key in sorted(unique)]


def _javascript_test_references(
    text: str,
    rel_path: str,
) -> tuple[list[IndexedTestReference], list[IndexedSymbol]]:
    mask = _javascript_code_mask(text)
    direct: dict[str, tuple[str, str, int]] = {}
    namespaces: dict[str, tuple[str, int]] = {}
    for match in re.finditer(
        r"\bimport\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
        text,
    ):
        if not mask[match.start()]:
            continue
        line = _line_number_at_offset(text, match.start())
        for raw_binding in match.group(1).split(","):
            parts = re.split(r"\s+as\s+", raw_binding.strip())
            if not parts or not re.fullmatch(r"[A-Za-z_$][\w$]*", parts[0]):
                continue
            local = parts[-1]
            if re.fullmatch(r"[A-Za-z_$][\w$]*", local):
                direct[local] = (match.group(2), parts[0], line)
    for match in re.finditer(
        r"\bimport\s*\*\s*as\s*([A-Za-z_$][\w$]*)\s*from\s*['\"]([^'\"]+)['\"]",
        text,
    ):
        if mask[match.start()]:
            namespaces[match.group(1)] = (
                match.group(2), _line_number_at_offset(text, match.start())
            )

    references: list[IndexedTestReference] = []
    symbols: list[IndexedSymbol] = []
    callback_pattern = re.compile(
        r"\b(test|it)\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"
    )
    for match in callback_pattern.finditer(text):
        if not mask[match.start()]:
            continue
        open_brace = match.end() - 1
        close_brace = _matching_javascript_brace(text, mask, open_brace)
        if close_brace is None:
            continue
        start_line = _line_number_at_offset(text, match.start())
        end_line = _line_number_at_offset(text, close_brace)
        symbol_name = f"{match.group(1)}@{start_line}"
        symbols.append(IndexedSymbol(
            symbol_type="test",
            name=symbol_name,
            qualified_name=f"{rel_path}:{symbol_name}",
            start_line=start_line,
            end_line=end_line,
        ))
        body = text[open_brace + 1:close_brace]
        body_offset = open_brace + 1
        for local, (specifier, target_name, binding_line) in direct.items():
            for ref in re.finditer(rf"\b{re.escape(local)}\s*\(", body):
                absolute = body_offset + ref.start()
                if mask[absolute]:
                    references.append(IndexedTestReference(
                        test_symbol_name=symbol_name,
                        test_symbol_start_line=start_line,
                        target_name=target_name,
                        target_specifier=specifier,
                        binding_line=binding_line,
                        reference_line=_line_number_at_offset(text, absolute),
                    ))
        for local, (specifier, binding_line) in namespaces.items():
            for ref in re.finditer(
                rf"\b{re.escape(local)}\.([A-Za-z_$][\w$]*)\s*\(", body
            ):
                absolute = body_offset + ref.start()
                if mask[absolute]:
                    references.append(IndexedTestReference(
                        test_symbol_name=symbol_name,
                        test_symbol_start_line=start_line,
                        target_name=ref.group(1),
                        target_specifier=specifier,
                        binding_line=binding_line,
                        reference_line=_line_number_at_offset(text, absolute),
                    ))
    return references, symbols


def _matching_javascript_brace(
    text: str,
    mask: list[bool],
    open_brace: int,
) -> int | None:
    depth = 0
    for offset in range(open_brace, len(text)):
        if not mask[offset]:
            continue
        if text[offset] == "{":
            depth += 1
        elif text[offset] == "}":
            depth -= 1
            if depth == 0:
                return offset
    return None


def _route_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    route_bindings: set[str],
) -> list[tuple[str, int, int]]:
    routes: list[tuple[str, int, int]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        method = None
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in route_bindings
            and func.attr in {"get", "post", "put", "patch", "delete"}
        ):
            method = func.attr.upper()
        if not method or not decorator.args:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            routes.append((
                f"{method} {first.value}",
                decorator.lineno,
                getattr(decorator, "end_lineno", decorator.lineno),
            ))
    return routes


def _python_route_bindings(module: ast.Module) -> set[str]:
    direct_constructors: dict[str, int] = {}
    module_aliases: dict[str, int] = {}
    for statement in module.body:
        if (
            isinstance(statement, ast.ImportFrom)
            and statement.level == 0
            and statement.module == "fastapi"
        ):
            for alias in statement.names:
                if alias.name in {"APIRouter", "FastAPI"}:
                    direct_constructors[alias.asname or alias.name] = statement.lineno
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == "fastapi":
                    module_aliases[alias.asname or "fastapi"] = statement.lineno

    assignments: dict[str, list[ast.expr | None]] = {}
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            assignments.setdefault(statement.target.id, []).append(statement.value)
    bindings: set[str] = set()
    for name, values in assignments.items():
        if len(values) != 1 or not isinstance(values[0], ast.Call):
            continue
        constructor = values[0].func
        assignment_line = getattr(values[0], "lineno", 0)
        proven_direct = (
            isinstance(constructor, ast.Name)
            and direct_constructors.get(constructor.id, assignment_line + 1)
            < assignment_line
        )
        proven_module = (
            isinstance(constructor, ast.Attribute)
            and isinstance(constructor.value, ast.Name)
            and constructor.attr in {"APIRouter", "FastAPI"}
            and module_aliases.get(constructor.value.id, assignment_line + 1)
            < assignment_line
        )
        if proven_direct or proven_module:
            bindings.add(name)
    return bindings


def _javascript_symbols(
    text: str,
    rel_path: str,
) -> tuple[
    list[IndexedSymbol],
    list[str],
    list[str],
    list[IndexedImport],
    list[IndexedRouteOwner],
]:
    symbols: list[IndexedSymbol] = []
    code_mask = _javascript_code_mask(text)
    import_matches = [
        match for match in list(re.finditer(
        r"import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]",
        text,
    )) + list(re.finditer(r"require\(['\"]([^'\"]+)['\"]\)", text))
        if code_mask[match.start()]
    ]
    imports = sorted({match.group(1) for match in import_matches})
    import_hints = [
        IndexedImport(
            specifier=match.group(1),
            start_line=_line_number_at_offset(text, match.start()),
            end_line=_line_number_at_offset(text, match.end()),
        )
        for match in import_matches
    ]
    for name in imports:
        line = _line_number(text, name)
        symbols.append(IndexedSymbol(
            symbol_type="import",
            name=name,
            qualified_name=name,
            start_line=line,
            end_line=line,
        ))

    for match in re.finditer(
        r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        name = match.group(1)
        line = _line_number_at_offset(text, match.start())
        symbols.append(IndexedSymbol(
            symbol_type="component" if name[:1].isupper() else "function",
            name=name,
            qualified_name=f"{rel_path}:{name}",
            start_line=line,
            end_line=line,
            signature=f"{name}(...)",
        ))
    for match in re.finditer(
        r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        name = match.group(1)
        line = _line_number_at_offset(text, match.start())
        symbols.append(IndexedSymbol(
            symbol_type="component" if name[:1].isupper() else "function",
            name=name,
            qualified_name=f"{rel_path}:{name}",
            start_line=line,
            end_line=line,
            signature=f"{name}(...) =>",
        ))
    for match in re.finditer(r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", text):
        if not code_mask[match.start()]:
            continue
        name = match.group(1)
        line = _line_number_at_offset(text, match.start())
        symbols.append(IndexedSymbol(
            symbol_type="class",
            name=name,
            qualified_name=f"{rel_path}:{name}",
            start_line=line,
            end_line=line,
        ))

    routes = []
    route_owners: list[IndexedRouteOwner] = []
    route_bindings = _javascript_route_bindings(text, code_mask)
    for match in re.finditer(
        r"\b(router|app)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]",
        text,
    ):
        if not code_mask[match.start()] or match.group(1) not in route_bindings:
            continue
        route = f"{match.group(2).upper()} {match.group(3)}"
        line = _line_number_at_offset(text, match.start())
        routes.append(route)
        symbols.append(IndexedSymbol(
            symbol_type="route",
            name=route,
            qualified_name=f"{rel_path}:{route}",
            start_line=line,
            end_line=line,
        ))
    for match in re.finditer(
        r"\b(router|app)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_$][\w$]*)\s*\)",
        text,
    ):
        if not code_mask[match.start()] or match.group(1) not in route_bindings:
            continue
        route_owners.append(IndexedRouteOwner(
            route=f"{match.group(2).upper()} {match.group(3)}",
            handler_name=match.group(4),
            start_line=_line_number_at_offset(text, match.start()),
            end_line=_line_number_at_offset(text, match.end()),
        ))
    return _dedupe_symbols(symbols), imports, sorted(set(routes)), import_hints, route_owners


def _javascript_code_mask(text: str) -> list[bool]:
    """Mark code offsets while conservatively excluding comments and strings."""
    mask = [True] * len(text)
    index = 0
    while index < len(text):
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            end = len(text) if end < 0 else end
            for offset in range(index, end):
                mask[offset] = False
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            for offset in range(index, end):
                mask[offset] = False
            index = end
            continue
        if text[index] in {"'", '"', "`"}:
            quote = text[index]
            mask[index] = False
            index += 1
            while index < len(text):
                mask[index] = False
                if text[index] == "\\":
                    index += 1
                    if index < len(text):
                        mask[index] = False
                        index += 1
                    continue
                if text[index] == quote:
                    index += 1
                    break
                index += 1
            continue
        index += 1
    return mask


def _javascript_route_bindings(text: str, code_mask: list[bool]) -> set[str]:
    assignments: dict[str, list[str]] = {}
    for match in re.finditer(
        r"\b(?:(?:const|let|var)\s+)?(app|router)\s*=\s*([^;\n]+)",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        assignments.setdefault(match.group(1), []).append(
            re.sub(r"\s+", "", match.group(2))
        )
    allowed = _javascript_proven_route_constructors(text, code_mask)
    return {
        name for name, values in assignments.items()
        if len(values) == 1 and values[0] in allowed
    }


def _javascript_proven_route_constructors(
    text: str,
    code_mask: list[bool],
) -> set[str]:
    """Return constructor calls backed by an exact framework import."""
    allowed: set[str] = set()

    for match in re.finditer(
        r"\bimport\s+([A-Za-z_$][\w$]*)\s+from\s+['\"](express|fastify)['\"]",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        alias, package = match.groups()
        allowed.add(f"{alias}()")
        if package == "express":
            allowed.add(f"{alias}.Router()")

    for match in re.finditer(
        r"\bimport\s*\{([^}]+)\}\s*from\s*['\"]express['\"]",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        for imported in match.group(1).split(","):
            parts = re.split(r"\s+as\s+", imported.strip())
            if parts[0] != "Router":
                continue
            alias = parts[-1]
            if re.fullmatch(r"[A-Za-z_$][\w$]*", alias):
                allowed.update({f"{alias}()", f"new{alias}()"})

    for match in re.finditer(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
        r"require\(['\"](express|fastify)['\"]\)",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        alias, package = match.groups()
        allowed.add(f"{alias}()")
        if package == "express":
            allowed.add(f"{alias}.Router()")

    for match in re.finditer(
        r"\b(?:const|let|var)\s*\{\s*Router(?:\s*:\s*([A-Za-z_$][\w$]*))?\s*\}"
        r"\s*=\s*require\(['\"]express['\"]\)",
        text,
    ):
        if not code_mask[match.start()]:
            continue
        alias = match.group(1) or "Router"
        allowed.update({f"{alias}()", f"new{alias}()"})

    return allowed


def _dedupe_symbols(symbols: list[IndexedSymbol]) -> list[IndexedSymbol]:
    seen: set[tuple[str, str, str | None, int | None]] = set()
    deduped: list[IndexedSymbol] = []
    for symbol in symbols:
        key = (symbol.symbol_type, symbol.name, symbol.qualified_name, symbol.start_line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return deduped


def _git_state(root: Path) -> dict[str, Any]:
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.strip() != "true":
        return {
            "branch": None,
            "base_commit": None,
            "head_commit": None,
            "dirty": False,
            "changed_files": [],
            "untracked_files": [],
            "recent_commits": [],
        }
    status_lines = [line for line in _git(root, "status", "--short").splitlines() if line.strip()]
    changed_files = []
    untracked_files = []
    for line in status_lines:
        status = line[:2].strip() or line[:2]
        raw_path = line[3:].strip()
        old_path = None
        path = raw_path
        if " -> " in raw_path:
            old_path, path = raw_path.rsplit(" -> ", 1)
        item = {
            "path": path,
            "status": status,
            "sha256": _sha256_file(root / path),
        }
        if old_path:
            item["old_path"] = old_path
        if status == "??":
            untracked_files.append(path)
        changed_files.append(item)
    return {
        "branch": _none_if_blank(_git(root, "rev-parse", "--abbrev-ref", "HEAD")),
        "base_commit": _none_if_blank(_git(root, "rev-parse", "HEAD~1")),
        "head_commit": _none_if_blank(_git(root, "rev-parse", "HEAD")),
        "dirty": bool(status_lines),
        "changed_files": changed_files,
        "untracked_files": sorted(untracked_files),
        "recent_commits": _recent_commits(root),
    }


def _recent_commits(root: Path) -> list[dict[str, Any]]:
    raw = _git(root, "log", "-n", "5", "--pretty=format:%H%x1f%an%x1f%cI%x1f%s")
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        commits.append({
            "commit_sha": parts[0],
            "author": parts[1],
            "created_at": parts[2],
            "message": parts[3],
            "changed_files": [],
        })
    return commits


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    # Porcelain status uses the first two columns for staged/unstaged state.
    # Preserve a leading space on the first row or ` M app.py` becomes
    # `M app.py` and the path parser silently drops its first character.
    return proc.stdout.rstrip()


def _package_manifests(root: Path, indexed_files: list[IndexedFile]) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for indexed in indexed_files:
        if not indexed.is_manifest:
            continue
        path = root / indexed.path
        try:
            if path.name == "package.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                manifests[indexed.path] = {
                    "name": data.get("name"),
                    "scripts": data.get("scripts", {}),
                    "dependencies": sorted((data.get("dependencies") or {}).keys()),
                    "dev_dependencies": sorted((data.get("devDependencies") or {}).keys()),
                }
            elif path.name == "pyproject.toml":
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                manifests[indexed.path] = {
                    "project": (data.get("project") or {}).get("name"),
                    "dependencies": (data.get("project") or {}).get("dependencies", []),
                    "optional_dependencies": sorted(((data.get("project") or {}).get("optional-dependencies") or {}).keys()),
                }
            else:
                manifests[indexed.path] = {"type": path.name}
        except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError):
            manifests[indexed.path] = {"type": path.name, "parse_error": True}
    return manifests


def _language_for(path: Path) -> str | None:
    if path.suffix == ".py":
        return "python"
    if path.suffix in {".js", ".jsx"}:
        return "javascript" if path.suffix == ".js" else "javascript-react"
    if path.suffix in {".ts", ".tsx"}:
        return "typescript" if path.suffix == ".ts" else "typescript-react"
    if path.suffix == ".md":
        return "markdown"
    if path.suffix == ".toml":
        return "toml"
    if path.suffix == ".json":
        return "json"
    if path.suffix in {".yml", ".yaml"}:
        return "yaml"
    if path.suffix == ".sh":
        return "shell"
    if path.name == "Dockerfile":
        return "dockerfile"
    return None


def _is_test_file(rel: str, text: str) -> bool:
    path = rel.lower()
    return (
        "/tests/" in f"/{path}"
        or path.startswith("tests/")
        or path.endswith(".test.js")
        or path.endswith(".test.jsx")
        or path.endswith(".test.ts")
        or path.endswith(".test.tsx")
        or path.startswith("test_")
        or bool(re.search(r"\b(pytest|describe|it|test)\s*\(", text))
    )


def _decode(raw: bytes) -> str | None:
    for encoding in ("utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _sha256_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 1
    ]


def _matching_symbol_ranges(
    indexed: IndexedFile,
    retrieval_terms: set[str],
) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for symbol in indexed.symbols:
        if not retrieval_terms & set(_tokenize(symbol.name)):
            continue
        if symbol.start_line is None:
            continue
        start_line = int(symbol.start_line)
        end_line = int(symbol.end_line or symbol.start_line)
        if (start_line, end_line) in seen:
            continue
        seen.add((start_line, end_line))
        ranges.append({"start_line": start_line, "end_line": end_line})
    return ranges[:12]


def _file_reason(indexed: IndexedFile, keywords: set[str]) -> str:
    if indexed.is_test:
        return "goal_related_test_file"
    if indexed.route_hints and "api" in keywords:
        return "goal_related_api_route"
    if "cli" in keywords and "/cli/" in f"/{indexed.path}":
        return "goal_related_cli_file"
    if indexed.symbols:
        return "goal_related_symbols"
    return "goal_path_or_keyword_match"


def _human_file_reason(item: dict[str, Any]) -> str:
    path = str(item.get("path") or "This file")
    if item.get("reason") == "explicit_goal_file_hint":
        return "The task names this file."
    basis = item.get("match_basis") or {}
    for key, label in (
        ("file_name", "File name matches"),
        ("path", "File name matches"),
        ("routes", "API route matches"),
        ("symbols", "Names inside this file match"),
        ("imports", "A connected file name matches"),
    ):
        terms = [str(term) for term in basis.get(key) or []][:4]
        if terms:
            return f"{label}: {', '.join(terms)}."
    return f"{path} uses wording from the task."


def _matches_file_hint(path: str, hints: set[str]) -> bool:
    normalized = path.strip("./")
    identities = {
        normalized.lower(),
        Path(normalized).name.lower(),
        Path(normalized).stem.lower(),
    }
    return bool(identities & {hint.strip("./").lower() for hint in hints})


def _file_match_strength(item: dict[str, Any]) -> str:
    if item.get("is_test"):
        return "linked_test"
    if item.get("reason") == "explicit_goal_file_hint":
        return "named_in_task"
    basis = item.get("match_basis") or {}
    if basis.get("file_name") or basis.get("path") or basis.get("routes"):
        return "strong_match"
    return "possible_match"


def _eligible_affected_path(path: str) -> bool:
    normalized = path.removeprefix("./")
    return not (
        normalized.startswith(".agent-runs/")
        or normalized.startswith(".github/ISSUE_TEMPLATE/")
        or "/fixture_project/sources/" in f"/{normalized}"
    )


def _snapshot_fingerprint(
    repo_root: str,
    head_commit: str | None,
    indexed_files: list[IndexedFile],
    changed_files: list[dict[str, Any]],
) -> str:
    payload = {
        "repo_root": repo_root,
        "head_commit": head_commit,
        "files": sorted(
            (item.path, item.sha256) for item in indexed_files
        ),
        "dirty": sorted(
            (
                str(item.get("status") or ""),
                item.get("old_path"),
                str(item.get("path") or ""),
                item.get("sha256"),
            )
            for item in changed_files
        ),
    }
    return _canonical_hash(payload)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_identity_key(workspace_id: UUID, repo_root: str, path: str) -> str:
    return _canonical_hash([str(workspace_id), repo_root, path])


def _symbol_identity_key(code_file_id: UUID, symbol: IndexedSymbol) -> str:
    return _canonical_hash([
        str(code_file_id),
        symbol.symbol_type,
        symbol.qualified_name or symbol.name,
        symbol.start_line,
        symbol.end_line,
    ])


def _line_number(text: str, needle: str) -> int | None:
    index = text.find(needle)
    return _line_number_at_offset(text, index) if index >= 0 else None


def _line_number_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _uuid_or_none(value: str | UUID | None) -> UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _none_if_blank(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


def _datetime_from_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
