"""Generic file scanner importer.

Walks a directory or reads individual files and creates a
``NormalizedDocument`` per file. Supports common text-based formats:

- ``.txt``, ``.md``, ``.rst`` — plain text / markdown
- ``.csv`` — each row becomes a separate document
- ``.json`` — top-level objects or arrays of objects
- ``.log`` — log files

Binary files (``.pdf``, ``.docx``, images, etc.) are **skipped** — they
require an extraction service (unstructured, etc.) which is out of scope
for the zero-auth MVP.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Iterator

from app.connectors.base import NormalizedDocument
from app.importers.base import BaseImporter, ImporterError

# Supported text extensions
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".json",
    ".jsonl",
    ".jsonlines",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".sh",
    ".bash",
    ".zsh",
}

# Skip these common binary / non-parseable extensions
_SKIP_EXTENSIONS = {
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".svg",
    ".webp",
    ".ico",
    ".tiff",
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    # Binary / compiled
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".o",
    ".pyc",
    ".class",
    # Database
    ".db",
    ".sqlite",
    ".sqlite3",
    # Other
    ".lock",
    ".DS_Store",
    ".git",
}
_IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

# Maximum file size to read (10 MB)
_MAX_FILE_SIZE = 10 * 1024 * 1024


class GenericFileScanner(BaseImporter):
    """Scan files and create SourceDocument-ready documents."""

    @classmethod
    def validate_source(cls, source_path: Path) -> tuple[bool, str | None]:
        if not source_path.exists():
            return False, f"Path does not exist: {source_path}"
        if source_path.is_file():
            ext = source_path.suffix.lower()
            if ext in _SKIP_EXTENSIONS:
                return False, f"Unsupported file type: {ext}"
        return True, None

    def ingest(
        self,
        source_path: Path,
        *,
        workspace_id: str = "unknown",
        connector_type_hint: str = "generic",
    ) -> Iterator[NormalizedDocument]:
        """Walk *source_path* and yield documents.

        Parameters
        ----------
        source_path : Path
            File or directory to scan.
        workspace_id : str
            Workspace identifier for provenance.
        connector_type_hint : str
            Hint for what connector type to associate with (used for
            authority weight in the ingestion pipeline).
        """
        if source_path.is_file():
            yield from self._process_file(source_path, workspace_id, connector_type_hint)
        elif source_path.is_dir():
            yield from self._walk_directory(source_path, workspace_id, connector_type_hint)
        else:
            raise ImporterError(f"Not a file or directory: {source_path}")

    # ── Directory walking ──────────────────────────────────────────────

    def _walk_directory(
        self,
        dir_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> Iterator[NormalizedDocument]:
        for entry in sorted(dir_path.rglob("*")):
            if not entry.is_file():
                continue
            if entry.name.startswith("."):
                continue
            if any(part in _IGNORED_DIR_NAMES for part in entry.parts):
                continue
            ext = entry.suffix.lower()
            if ext in _SKIP_EXTENSIONS:
                continue
            if ext not in _TEXT_EXTENSIONS:
                continue
            try:
                yield from self._process_file(entry, workspace_id, connector_type_hint)
            except ImporterError:
                raise
            except Exception:
                # Skip unparseable files silently — logged by service
                continue

    # ── File processing ────────────────────────────────────────────────

    def _process_file(
        self,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> Iterator[NormalizedDocument]:
        if file_path.stat().st_size > _MAX_FILE_SIZE:
            raise ImporterError(f"File too large to import safely: {file_path}")

        ext = file_path.suffix.lower()

        if ext == ".csv" or ext == ".tsv":
            yield from self._process_csv(file_path, workspace_id, connector_type_hint)
        elif ext in (".json", ".jsonl", ".jsonlines"):
            yield from self._process_json(file_path, workspace_id, connector_type_hint)
        elif ext in (".html", ".htm"):
            yield from self._process_html(file_path, workspace_id, connector_type_hint)
        else:
            doc = self._process_text_file(file_path, workspace_id, connector_type_hint)
            if doc is not None:
                yield doc

    # ── Format-specific parsers ────────────────────────────────────────

    def _process_text_file(
        self,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> NormalizedDocument | None:
        """Read a plain text / markdown file as a single document."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc

        if not content.strip():
            return None

        content = content.strip()

        # Try to extract title from first markdown heading
        title = file_path.stem.replace("-", " ").replace("_", " ").title()
        if content.startswith("# "):
            first_line = content.split("\n", 1)[0]
            title = first_line.lstrip("# ").strip() or title

        try:
            rel_path = str(file_path.resolve())
        except ValueError:
            rel_path = file_path.name

        return NormalizedDocument(
            external_id=f"file-import:{workspace_id}:{_path_digest(file_path)}",
            content=content,
            author=None,
            source_url=file_path.resolve().as_uri(),
            created_at=None,
            metadata={
                "title": title,
                "source_type": "file_import",
                "file_name": file_path.name,
                "file_path": rel_path,
                "file_ext": file_path.suffix,
                "connector_type_hint": connector_type_hint,
                "authority_weight": _authority_weight_for_hint(connector_type_hint),
            },
        )

    def _process_csv(
        self,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> Iterator[NormalizedDocument]:
        """Parse CSV — each row becomes a document."""
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc

        if not raw.strip():
            return

        delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return

        fieldnames = reader.fieldnames or []

        for idx, row in enumerate(rows):
            lines = []
            for key, value in row.items():
                if key and value:
                    lines.append(f"{key}: {value}")
            content = "\n".join(lines)
            if not content.strip():
                continue

            title = ""
            if fieldnames:
                title = row.get(fieldnames[0], "") or ""

            try:
                rel_path = str(file_path.resolve())
            except ValueError:
                rel_path = file_path.name

            yield NormalizedDocument(
                external_id=f"csv-import:{workspace_id}:{_path_digest(file_path)}:row-{idx}",
                content=content.strip(),
                author=None,
                source_url=file_path.resolve().as_uri(),
                created_at=None,
                metadata={
                    "title": title or file_path.stem,
                    "source_type": "csv_import",
                    "file_name": file_path.name,
                    "file_path": rel_path,
                    "row_index": idx,
                    "connector_type_hint": connector_type_hint,
                    "authority_weight": _authority_weight_for_hint(connector_type_hint),
                    "csv_title": title,
                },
            )

    def _process_json(
        self,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> Iterator[NormalizedDocument]:
        """Parse JSON — supports top-level array or JSONL."""
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc

        if not raw.strip():
            return

        if file_path.suffix.lower() in (".jsonl", ".jsonlines"):
            yield from self._process_jsonl(raw, file_path, workspace_id, connector_type_hint)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            yield from self._process_jsonl(raw, file_path, workspace_id, connector_type_hint)
            return

        if isinstance(data, list):
            for idx, item in enumerate(data):
                doc = self._json_value_to_document(
                    item,
                    file_path,
                    workspace_id,
                    connector_type_hint,
                    idx,
                )
                if doc is not None:
                    yield doc
        elif isinstance(data, dict):
            doc = self._json_value_to_document(
                data,
                file_path,
                workspace_id,
                connector_type_hint,
                0,
            )
            if doc is not None:
                yield doc

    def _process_jsonl(
        self,
        raw: str,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> Iterator[NormalizedDocument]:
        """Parse JSONL (one JSON object per line)."""
        for idx, line in enumerate(raw.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc = self._json_value_to_document(
                item,
                file_path,
                workspace_id,
                connector_type_hint,
                idx,
            )
            if doc is not None:
                yield doc

    @staticmethod
    def _json_value_to_document(
        value: object,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
        index: int,
    ) -> NormalizedDocument | None:
        """Convert a JSON value to a NormalizedDocument."""
        if isinstance(value, str):
            content = value.strip()
            if not content:
                return None
            title = content[:80]
        elif isinstance(value, dict):
            lines = []
            for key, val in value.items():
                if val is not None:
                    lines.append(f"{key}: {_flatten_value(val)}")
            content = "\n".join(lines)
            if not content.strip():
                return None
            title = value.get("title", "") or value.get("name", "") or file_path.stem
            if not isinstance(title, str):
                title = str(title)
        elif isinstance(value, list):
            content = "\n".join(str(v) for v in value)
            if not content.strip():
                return None
            title = file_path.stem
        else:
            content = str(value).strip()
            if not content:
                return None
            title = content[:80]

        try:
            rel_path = str(file_path.resolve())
        except ValueError:
            rel_path = file_path.name

        return NormalizedDocument(
            external_id=f"json-import:{workspace_id}:{_path_digest(file_path)}:{index}",
            content=content.strip(),
            author=None,
            source_url=file_path.resolve().as_uri(),
            created_at=None,
            metadata={
                "title": title,
                "source_type": "json_import",
                "file_name": file_path.name,
                "file_path": rel_path,
                "json_index": index,
                "connector_type_hint": connector_type_hint,
                "authority_weight": _authority_weight_for_hint(connector_type_hint),
            },
        )

    def _process_html(
        self,
        file_path: Path,
        workspace_id: str,
        connector_type_hint: str,
    ) -> Iterator[NormalizedDocument]:
        """Parse HTML — strip tags and use text content."""
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc

        if not raw.strip():
            return

        import re

        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", raw, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else file_path.stem

        try:
            rel_path = str(file_path.resolve())
        except ValueError:
            rel_path = file_path.name

        yield NormalizedDocument(
            external_id=f"html-import:{workspace_id}:{_path_digest(file_path)}",
            content=text,
            author=None,
            source_url=file_path.resolve().as_uri(),
            created_at=None,
            metadata={
                "title": title,
                "source_type": "html_import",
                "file_name": file_path.name,
                "file_path": rel_path,
                "connector_type_hint": connector_type_hint,
                "authority_weight": _authority_weight_for_hint(connector_type_hint),
            },
        )


def _authority_weight_for_hint(connector_type_hint: str) -> float:
    """Return a reasonable authority weight for a connector type hint."""
    weights = {
        "local": 0.85,
        "notion": 0.95,
        "zoom": 0.90,
        "gong": 0.90,
        "github": 0.86,
        "gdrive": 0.88,
        "slack": 0.75,
        "generic": 0.50,
    }
    return weights.get(connector_type_hint.lower(), 0.50)


def _flatten_value(value: object) -> str:
    """Flatten a JSON value to a string for display."""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(_flatten_value(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}={_flatten_value(v)}" for k, v in value.items())
    return str(value)


def _path_digest(file_path: Path) -> str:
    return hashlib.sha1(str(file_path.resolve()).encode("utf-8")).hexdigest()
