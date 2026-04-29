from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


class ImporterError(Exception):
    """Raised when an import operation fails."""


@dataclass
class NormalizedDocument:
    external_id: str
    content: str
    author: str | None
    source_url: str | None
    created_at: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".json", ".jsonl", ".jsonlines",
    ".csv", ".tsv",
    ".html", ".htm",
    ".xml", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".sh",
}
_SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".pyc",
    ".db", ".sqlite", ".sqlite3",
    ".lock", ".DS_Store",
}
_IGNORED_DIR_NAMES = {".git", ".hg", "__pycache__", "node_modules", "venv", ".venv", "build", "dist"}
_MAX_FILE_SIZE = 10 * 1024 * 1024


class GenericFileScanner:
    @classmethod
    def validate_source(cls, source_path: Path) -> tuple[bool, str | None]:
        if not source_path.exists():
            return False, f"Path does not exist: {source_path}"
        if source_path.is_file():
            ext = source_path.suffix.lower()
            if ext in _SKIP_EXTENSIONS:
                return False, f"Unsupported file type: {ext}"
        return True, None

    def ingest(self, source_path: Path) -> Iterator[NormalizedDocument]:
        if source_path.is_file():
            yield from self._process_file(source_path)
        elif source_path.is_dir():
            yield from self._walk_directory(source_path)
        else:
            raise ImporterError(f"Not a file or directory: {source_path}")

    def _walk_directory(self, dir_path: Path) -> Iterator[NormalizedDocument]:
        for entry in sorted(dir_path.rglob("*")):
            if not entry.is_file() or entry.name.startswith("."):
                continue
            if any(part in _IGNORED_DIR_NAMES for part in entry.parts):
                continue
            ext = entry.suffix.lower()
            if ext in _SKIP_EXTENSIONS or ext not in _TEXT_EXTENSIONS:
                continue
            try:
                yield from self._process_file(entry)
            except Exception:
                continue

    def _process_file(self, file_path: Path) -> Iterator[NormalizedDocument]:
        if file_path.stat().st_size > _MAX_FILE_SIZE:
            raise ImporterError(f"File too large: {file_path}")
        ext = file_path.suffix.lower()
        if ext in (".csv", ".tsv"):
            yield from self._process_csv(file_path)
        elif ext in (".json", ".jsonl", ".jsonlines"):
            yield from self._process_json(file_path)
        else:
            doc = self._process_text_file(file_path)
            if doc is not None:
                yield doc

    def _process_text_file(self, file_path: Path) -> NormalizedDocument | None:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc
        if not content.strip():
            return None
        content = content.strip()
        title = file_path.stem.replace("-", " ").replace("_", " ").title()
        if content.startswith("# "):
            title = content.split("\n", 1)[0].lstrip("# ").strip() or title
        return NormalizedDocument(
            external_id=f"file:{_path_digest(file_path)}",
            content=content,
            author=None,
            source_url=file_path.resolve().as_uri(),
            created_at=None,
            metadata={"title": title, "file_name": file_path.name},
        )

    def _process_csv(self, file_path: Path) -> Iterator[NormalizedDocument]:
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc
        if not raw.strip():
            return
        delimiter = "\t" if file_path.suffix.lower() == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
        for idx, row in enumerate(reader):
            lines = [f"{k}: {v}" for k, v in row.items() if k and v]
            content = "\n".join(lines)
            if not content.strip():
                continue
            yield NormalizedDocument(
                external_id=f"csv:{_path_digest(file_path)}:row-{idx}",
                content=content.strip(),
                author=None,
                source_url=file_path.resolve().as_uri(),
                created_at=None,
                metadata={"title": file_path.stem, "row_index": idx},
            )

    def _process_json(self, file_path: Path) -> Iterator[NormalizedDocument]:
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc
        if not raw.strip():
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(data, list):
            for idx, item in enumerate(data):
                doc = self._json_to_doc(item, file_path, idx)
                if doc is not None:
                    yield doc
        elif isinstance(data, dict):
            doc = self._json_to_doc(data, file_path, 0)
            if doc is not None:
                yield doc

    @staticmethod
    def _json_to_doc(value: object, file_path: Path, index: int) -> NormalizedDocument | None:
        if isinstance(value, str):
            content = value.strip()
            if not content:
                return None
            title = content[:80]
        elif isinstance(value, dict):
            lines = [f"{k}: {v}" for k, v in value.items() if v is not None]
            content = "\n".join(lines)
            if not content.strip():
                return None
            title = value.get("title", "") or value.get("name", "") or file_path.stem
            if not isinstance(title, str):
                title = str(title)
        else:
            return None
        return NormalizedDocument(
            external_id=f"json:{_path_digest(file_path)}:{index}",
            content=content.strip(),
            author=None,
            source_url=file_path.resolve().as_uri(),
            created_at=None,
            metadata={"title": title},
        )


def _path_digest(file_path: Path) -> str:
    return hashlib.sha1(str(file_path.resolve()).encode("utf-8")).hexdigest()
