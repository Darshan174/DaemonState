from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodeFile, CodeSymbol, RepoEvent
from app.time import utc_now


IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
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
ENV_FILE_RE = re.compile(r"(^|/)\.env($|[.\-])|\.env\.example$|config\.(?:py|js|ts|json|ya?ml)$")
RANKING_VERSION = "objective_file_rank.v2"
_GENERIC_GOAL_TERMS = {
    "add",
    "change",
    "code",
    "complete",
    "finish",
    "fix",
    "implement",
    "make",
    "repo",
    "run",
    "test",
    "tests",
    "the",
    "update",
    "verify",
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
class IndexedFile:
    path: str
    language: str | None
    sha256: str | None
    size: int
    symbols: list[IndexedSymbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    route_hints: list[str] = field(default_factory=list)
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
    persistence_available: bool = False
    persistence_reason: str | None = None

    def relevant_files_for_goal(self, keywords: set[str], file_hints: list[str]) -> list[dict[str, Any]]:
        hinted = {hint.strip("./") for hint in file_hints}
        normalized_keywords = set(_tokenize(" ".join(sorted(keywords))))
        retrieval_terms = normalized_keywords - _GENERIC_GOAL_TERMS
        requires_tests = bool({"test", "tests", "pytest", "verify"} & normalized_keywords)
        changed_paths = {item["path"] for item in self.changed_files}
        scored: list[tuple[float, str, str, list[str], list[dict[str, int]]]] = []
        for indexed in self.indexed_files:
            path_tokens = set(_tokenize(indexed.path))
            symbol_tokens = set(_tokenize(" ".join(symbol.name for symbol in indexed.symbols[:100])))
            import_tokens = set(_tokenize(" ".join(indexed.imports)))
            route_tokens = set(_tokenize(" ".join(indexed.route_hints)))
            matched_path = sorted(retrieval_terms & path_tokens)
            matched_symbols = sorted(retrieval_terms & symbol_tokens)
            matched_support = sorted(retrieval_terms & (import_tokens | route_tokens))
            matched_terms = sorted(set(matched_path + matched_symbols + matched_support))
            score = 0.0
            if indexed.path in hinted or Path(indexed.path).name in hinted:
                score += 5.0
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
            if indexed.path in changed_paths:
                score += 0.20
            if score <= 0:
                continue
            line_ranges = _matching_symbol_ranges(indexed, retrieval_terms)
            reason = (
                "explicit_goal_file_hint"
                if indexed.path in hinted or Path(indexed.path).name in hinted
                else _file_reason(indexed, normalized_keywords)
            )
            scored.append((
                round(score, 6),
                indexed.path,
                reason,
                matched_terms,
                line_ranges,
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
                (0.1, path, "repo_state_fallback", [], [])
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
                "line_ranges": line_ranges,
                "lane": "code_and_tests",
                "exists": path in indexed_by_path or (Path(self.repo_path) / path).exists(),
                "sha256": indexed_by_path[path].sha256 if path in indexed_by_path else _sha256_file(Path(self.repo_path) / path),
                "is_test": indexed_by_path[path].is_test if path in indexed_by_path else _is_test_file(path, ""),
            }
            for score, path, reason, matched_terms, line_ranges in top
        ]

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

        frame = _scan_repo(root)
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
        try:
            async with self.session.begin_nested():
                existing_ids = list(await self.session.scalars(
                    select(CodeFile.id).where(
                        CodeFile.repo_root == frame.repo_path,
                        CodeFile.workspace_id == workspace_uuid,
                    )
                ))
                if existing_ids:
                    await self.session.execute(
                        delete(CodeSymbol).where(CodeSymbol.code_file_id.in_(existing_ids))
                    )
                    await self.session.execute(
                        delete(CodeFile).where(CodeFile.id.in_(existing_ids))
                    )

                for indexed in frame.indexed_files:
                    code_file = CodeFile(
                        workspace_id=workspace_uuid,
                        repo_root=frame.repo_path,
                        path=indexed.path,
                        language=indexed.language,
                        sha256=indexed.sha256,
                        last_commit=frame.head_commit,
                        size=indexed.size,
                    )
                    self.session.add(code_file)
                    await self.session.flush()
                    for symbol in indexed.symbols[:300]:
                        self.session.add(CodeSymbol(
                            code_file_id=code_file.id,
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
            frame.persistence_available = True
            frame.persistence_reason = None
        except SQLAlchemyError as exc:
            frame.persistence_available = False
            frame.persistence_reason = f"repo_index_persistence_unavailable: {exc.__class__.__name__}"


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
    )


def _iter_interesting_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS for part in rel_parts):
            continue
        if path.name in MANIFEST_NAMES or path.suffix in INDEXED_SUFFIXES or ENV_FILE_RE.search(path.as_posix()):
            files.append(path)
    return sorted(files)


def _index_file(root: Path, path: Path) -> IndexedFile | None:
    rel = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > 400_000:
        return None
    sha = hashlib.sha256(raw).hexdigest()
    language = _language_for(path)
    text = _decode(raw)
    symbols: list[IndexedSymbol] = []
    imports: list[str] = []
    route_hints: list[str] = []
    if text is not None:
        if path.suffix == ".py":
            symbols, imports, route_hints = _python_symbols(text, rel)
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            symbols, imports, route_hints = _javascript_symbols(text, rel)
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
        route_hints=route_hints,
        is_test=is_test,
        is_config=is_config,
        is_manifest=is_manifest,
    )


def _python_symbols(text: str, rel_path: str) -> tuple[list[IndexedSymbol], list[str], list[str]]:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return [], [], []
    symbols: list[IndexedSymbol] = []
    imports: list[str] = []
    routes: list[str] = []
    module_name = rel_path.removesuffix(".py").replace("/", ".")

    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                symbols.append(IndexedSymbol(
                    symbol_type="import",
                    name=alias.asname or alias.name,
                    qualified_name=alias.name,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                ))
        elif isinstance(node, ast.ImportFrom):
            imported_from = "." * int(node.level or 0) + (node.module or "")
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
            for route in _route_decorators(node):
                routes.append(route)
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
    return _dedupe_symbols(symbols), sorted(set(imports)), sorted(set(routes))


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.posonlyargs + node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    args.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"


def _route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    routes: list[str] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        method = None
        if isinstance(func, ast.Attribute) and func.attr in {"get", "post", "put", "patch", "delete"}:
            method = func.attr.upper()
        if not method or not decorator.args:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            routes.append(f"{method} {first.value}")
    return routes


def _javascript_symbols(text: str, rel_path: str) -> tuple[list[IndexedSymbol], list[str], list[str]]:
    symbols: list[IndexedSymbol] = []
    imports = sorted(set(
        re.findall(r"import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]", text)
        + re.findall(r"require\(['\"]([^'\"]+)['\"]\)", text)
    ))
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
    for match in re.finditer(
        r"\b(?:router|app)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]",
        text,
    ):
        route = f"{match.group(1).upper()} {match.group(2)}"
        line = _line_number_at_offset(text, match.start())
        routes.append(route)
        symbols.append(IndexedSymbol(
            symbol_type="route",
            name=route,
            qualified_name=f"{rel_path}:{route}",
            start_line=line,
            end_line=line,
        ))
    return _dedupe_symbols(symbols), imports, sorted(set(routes))


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
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        item = {
            "path": path,
            "status": status,
            "sha256": _sha256_file(root / path),
        }
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
    for symbol in indexed.symbols:
        if not retrieval_terms & set(_tokenize(symbol.name)):
            continue
        if symbol.start_line is None:
            continue
        ranges.append({
            "start_line": int(symbol.start_line),
            "end_line": int(symbol.end_line or symbol.start_line),
        })
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
