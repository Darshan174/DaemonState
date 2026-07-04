from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}

PYTHON_SUFFIXES = {".py"}
JS_TS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
CONFIG_SUFFIXES = {".toml", ".yaml", ".yml", ".ini", ".cfg", ".env"}


@dataclass(frozen=True)
class CodeSymbol:
    path: str
    symbol_type: str
    name: str
    qualified_name: str
    line_start: int | None = None
    line_end: int | None = None
    signature: str | None = None
    docstring: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CodeFile:
    path: str
    language: str
    sha256: str
    size: int
    is_test: bool = False
    is_config: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RepoIndex:
    repo_path: str
    files: list[CodeFile] = field(default_factory=list)
    symbols: list[CodeSymbol] = field(default_factory=list)
    package_manifests: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    api_endpoints: list[dict[str, str]] = field(default_factory=list)
    imports: list[dict[str, str]] = field(default_factory=list)
    recent_commits: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repo_path": self.repo_path,
            "files": [item.to_dict() for item in self.files],
            "symbols": [item.to_dict() for item in self.symbols],
            "package_manifests": self.package_manifests,
            "test_files": self.test_files,
            "config_files": self.config_files,
            "api_endpoints": self.api_endpoints,
            "imports": self.imports,
            "recent_commits": self.recent_commits,
        }


class RepoIndexer:
    def __init__(self, max_file_size: int = 512_000) -> None:
        self.max_file_size = max_file_size

    def index(self, repo_path: str | Path) -> RepoIndex:
        root = Path(repo_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Repository path does not exist: {root}")

        result = RepoIndex(repo_path=str(root))
        for path in _iter_interesting_files(root):
            rel = path.relative_to(root).as_posix()
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > self.max_file_size:
                continue

            language = language_for_path(path)
            code_file = CodeFile(
                path=rel,
                language=language,
                sha256=_sha256_file(path),
                size=stat.st_size,
                is_test=is_test_file(path, rel),
                is_config=is_config_file(path),
            )
            result.files.append(code_file)

            if path.name in MANIFEST_NAMES:
                result.package_manifests.append(rel)
            if code_file.is_test:
                result.test_files.append(rel)
            if code_file.is_config:
                result.config_files.append(rel)

            if path.suffix in PYTHON_SUFFIXES:
                self._index_python(path, rel, result)
            elif path.suffix in JS_TS_SUFFIXES:
                self._index_js_ts(path, rel, result)

        result.recent_commits = recent_commits(root)
        result.package_manifests.sort()
        result.test_files.sort()
        result.config_files.sort()
        return result

    def _index_python(self, path: Path, rel: str, result: RepoIndex) -> None:
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append({
                        "path": rel,
                        "module": alias.name,
                        "name": alias.asname or alias.name,
                    })
                    result.symbols.append(CodeSymbol(
                        path=rel,
                        symbol_type="import",
                        name=alias.asname or alias.name,
                        qualified_name=alias.name,
                        line_start=getattr(node, "lineno", None),
                        line_end=getattr(node, "end_lineno", None),
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    qualified = f"{module}.{alias.name}" if module else alias.name
                    result.imports.append({
                        "path": rel,
                        "module": module,
                        "name": alias.name,
                    })
                    result.symbols.append(CodeSymbol(
                        path=rel,
                        symbol_type="import",
                        name=alias.asname or alias.name,
                        qualified_name=qualified,
                        line_start=getattr(node, "lineno", None),
                        line_end=getattr(node, "end_lineno", None),
                    ))
            elif isinstance(node, ast.ClassDef):
                result.symbols.append(CodeSymbol(
                    path=rel,
                    symbol_type="class",
                    name=node.name,
                    qualified_name=node.name,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", None),
                    signature=f"class {node.name}",
                    docstring=ast.get_docstring(node),
                ))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        result.symbols.append(_python_function_symbol(child, rel, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_nested_function(tree, node):
                    continue
                result.symbols.append(_python_function_symbol(node, rel, None))

                for method, route_path in _route_decorators(node):
                    result.api_endpoints.append({
                        "path": rel,
                        "method": method,
                        "route": route_path,
                        "handler": node.name,
                    })

    def _index_js_ts(self, path: Path, rel: str, result: RepoIndex) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        for match in re.finditer(r"\bimport\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]", text):
            module = match.group(1)
            result.imports.append({"path": rel, "module": module, "name": module})
            result.symbols.append(CodeSymbol(
                path=rel,
                symbol_type="import",
                name=module,
                qualified_name=module,
                line_start=_line_for_offset(text, match.start()),
            ))

        for match in re.finditer(r"\brequire\(['\"]([^'\"]+)['\"]\)", text):
            module = match.group(1)
            result.imports.append({"path": rel, "module": module, "name": module})

        function_patterns = [
            (r"\bexport\s+function\s+([A-Za-z_$][\w$]*)\s*\(", "function"),
            (r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", "function"),
            (r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", "function"),
        ]
        seen: set[tuple[str, int]] = set()
        for pattern, symbol_type in function_patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                line = _line_for_offset(text, match.start())
                key = (name, line)
                if key in seen:
                    continue
                seen.add(key)
                inferred_type = "component" if name[:1].isupper() else symbol_type
                result.symbols.append(CodeSymbol(
                    path=rel,
                    symbol_type=inferred_type,
                    name=name,
                    qualified_name=name,
                    line_start=line,
                ))

        for match in re.finditer(r"\b(app|router)\.(get|post|put|patch|delete)\(['\"]([^'\"]+)['\"]", text):
            result.api_endpoints.append({
                "path": rel,
                "method": match.group(2).upper(),
                "route": match.group(3),
                "handler": match.group(1),
            })


def inspect_repo_state(repo_path: str | Path) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    index = RepoIndexer().index(root)
    branch = _git_output(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    base_commit = _git_output(root, ["rev-parse", "HEAD"])
    status = _git_output(root, ["status", "--short"])
    changed_files = _parse_changed_files(status)

    return {
        "repo_path": str(root),
        "branch": branch or None,
        "base_commit": base_commit or None,
        "dirty": bool(status),
        "changed_files": changed_files,
        "package_manifests": index.package_manifests,
        "likely_test_commands": likely_test_commands(root, index),
        "test_files": index.test_files,
        "config_files": index.config_files,
        "api_endpoints": index.api_endpoints[:50],
        "recent_commits": index.recent_commits,
        "index_summary": {
            "file_count": len(index.files),
            "symbol_count": len(index.symbols),
            "python_symbol_count": sum(1 for item in index.symbols if item.path.endswith(".py")),
            "js_ts_symbol_count": sum(
                1 for item in index.symbols if Path(item.path).suffix in JS_TS_SUFFIXES
            ),
        },
        "index": index.to_dict(),
    }


def likely_test_commands(root: Path, index: RepoIndex) -> list[str]:
    commands: list[str] = []
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").exists():
        commands.append("pytest -q")

    package_json_paths = [root / path for path in index.package_manifests if path.endswith("package.json")]
    for package_json in package_json_paths:
        rel_dir = package_json.parent.relative_to(root).as_posix()
        prefix = "" if rel_dir == "." else f"cd {rel_dir} && "
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        if "test" in scripts:
            commands.append(f"{prefix}npm test")
        if "build" in scripts:
            commands.append(f"{prefix}npm run build")

    return _ordered_unique(commands)


def recent_commits(root: Path, limit: int = 5) -> list[dict[str, str]]:
    output = _git_output(root, ["log", f"--max-count={limit}", "--pretty=format:%H%x1f%an%x1f%ad%x1f%s", "--date=short"])
    commits = []
    for line in output.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        commits.append({
            "commit": parts[0],
            "author": parts[1],
            "date": parts[2],
            "message": parts[3],
        })
    return commits


def language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if suffix == ".md":
        return "markdown"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    if suffix == ".toml":
        return "toml"
    if suffix == ".json":
        return "json"
    if path.name == "Dockerfile":
        return "dockerfile"
    return suffix.removeprefix(".") or "text"


def is_test_file(path: Path, rel: str) -> bool:
    name = path.name.lower()
    return (
        rel.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def is_config_file(path: Path) -> bool:
    name = path.name
    suffix = path.suffix.lower()
    return (
        name.startswith(".env")
        or name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
        or suffix in CONFIG_SUFFIXES
    )


def _iter_interesting_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in MANIFEST_NAMES:
            yield path
            continue
        if path.suffix in PYTHON_SUFFIXES | JS_TS_SUFFIXES | {".md", ".json", ".toml", ".yaml", ".yml"}:
            yield path


def _python_function_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel: str,
    class_name: str | None,
) -> CodeSymbol:
    qualified = f"{class_name}.{node.name}" if class_name else node.name
    args = [arg.arg for arg in node.args.args]
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return CodeSymbol(
        path=rel,
        symbol_type="method" if class_name else "function",
        name=node.name,
        qualified_name=qualified,
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", None),
        signature=f"{prefix} {node.name}({', '.join(args)})",
        docstring=ast.get_docstring(node),
    )


def _is_nested_function(tree: ast.AST, target: ast.AST) -> bool:
    for node in ast.walk(tree):
        if node is target:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if target in ast.walk(node):
                return not isinstance(node, ast.Module)
    return False


def _route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        method = None
        if isinstance(func, ast.Attribute) and func.attr.lower() in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
        }:
            method = func.attr.upper()
        if method is None or not decorator.args:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            routes.append((method, first.value))
    return routes


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _git_output(root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _parse_changed_files(status: str) -> list[str]:
    changed: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:] if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path.strip())
    return changed


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
