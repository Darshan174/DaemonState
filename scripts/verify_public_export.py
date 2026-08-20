"""Fail closed when the staged public export differs from its reviewed allowlist."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daemonstate_public.cli import SCHEMA_VERSION, load_bundle  # noqa: E402


IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
FORBIDDEN_PATH_PARTS = {
    ".agent-runs",
    "alembic",
    "app",
    "attached_assets",
    "data",
    "deploy",
    "desktop",
    "frontend",
}
FORBIDDEN_SUFFIXES = {
    ".crt",
    ".db",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".sqlite",
    ".sqlite3",
}
MAX_FILE_BYTES = 512_000

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "OpenAI-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "credential assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|access[_-]?token)\b"
        r"\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    ),
    "credential-bearing database URL": re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|redis)://[^\s/:]+:[^\s/@]+@"
    ),
    "macOS user path": re.compile("/" + r"Users/[^/\s]+"),
    "Windows user path": re.compile(r"[A-Za-z]:\\" + r"Users\\[^\\\s]+"),
}

PRIVATE_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:app|frontend|desktop)(?:\.|\s|$)",
    re.MULTILINE,
)


def _ignored(path: Path) -> bool:
    relative_parts = path.relative_to(ROOT).parts
    return any(
        part in IGNORED_DIRECTORY_NAMES or part.endswith(".egg-info")
        for part in relative_parts
    )


def _listed_files() -> set[str]:
    return {
        line.strip()
        for line in (ROOT / "PUBLIC_FILES.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _actual_files() -> tuple[set[str], list[str]]:
    files: set[str] = set()
    errors: list[str] = []
    for path in ROOT.rglob("*"):
        if _ignored(path):
            continue
        relative = path.relative_to(ROOT)
        if path.is_symlink():
            errors.append(f"symlink is not allowed: {relative.as_posix()}")
            continue
        if path.is_file():
            files.add(relative.as_posix())
    return files, errors


def _check_paths(files: set[str]) -> list[str]:
    errors: list[str] = []
    for relative_text in sorted(files):
        relative = Path(relative_text)
        if FORBIDDEN_PATH_PARTS.intersection(relative.parts):
            errors.append(f"private path component: {relative_text}")
        if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"sensitive file type: {relative_text}")
        path = ROOT / relative
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"file exceeds {MAX_FILE_BYTES} bytes: {relative_text}")
    return errors


def _check_contents(files: set[str]) -> list[str]:
    errors: list[str] = []
    for relative_text in sorted(files):
        path = ROOT / relative_text
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"non-UTF-8 or binary file: {relative_text}")
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{label} signature: {relative_text}")
        if relative_text != "scripts/verify_public_export.py" and PRIVATE_IMPORT.search(text):
            errors.append(f"private package import: {relative_text}")
    return errors


def _check_contract() -> list[str]:
    errors: list[str] = []
    fixture_path = ROOT / "daemonstate_public" / "examples" / "synthetic_context.json"
    try:
        fixture = load_bundle(fixture_path)
    except Exception as exc:  # The verifier reports the complete failure set.
        errors.append(f"fixture validation failed: {exc}")
        fixture = None

    schema_path = ROOT / "schemas" / "context-bundle.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"schema JSON failed: {exc}")
        schema = None

    if fixture and fixture["schema_version"] != SCHEMA_VERSION:
        errors.append("fixture and CLI schema versions differ")
    if schema and schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        errors.append("schema file and CLI schema versions differ")
    if fixture and fixture.get("provenance", {}).get("synthetic") is not True:
        errors.append("fixture is not explicitly synthetic")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())
    disclosures = (
        "not the DaemonState engine",
        "not the complete Free product",
        "synthetic",
        "private",
    )
    for disclosure in disclosures:
        if disclosure.lower() not in normalized_readme.lower():
            errors.append(f"README missing required disclosure: {disclosure}")
    return errors


def main() -> int:
    expected = _listed_files()
    actual, errors = _actual_files()

    for missing in sorted(expected - actual):
        errors.append(f"allowlisted file is missing: {missing}")
    for unexpected in sorted(actual - expected):
        errors.append(f"file is not allowlisted: {unexpected}")

    errors.extend(_check_paths(actual))
    errors.extend(_check_contents(actual))
    errors.extend(_check_contract())

    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1

    print(f"PASS public export: {len(actual)} allowlisted UTF-8 files")
    print(f"PASS synthetic contract: {SCHEMA_VERSION}")
    print("PASS no symlinks, sensitive file types, private imports, or secret signatures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
