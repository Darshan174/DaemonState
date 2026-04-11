"""Notion directory importer.

Parses a directory exported from Notion (via the Notion desktop app
"Export" feature).  Notion exports produce a flat or nested directory
of ``.md`` and ``.csv`` files along with an ``.html`` export option.

This importer focuses on the ``.md`` text export format which is the
most parseable for our ingestion pipeline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from app.connectors.base import NormalizedDocument
from app.importers.base import BaseImporter, ImporterError

# Match a Notion page title at the top of an exported .md file:
#   "# Page Title\n\n"  or  "# Page Title  \n\n"
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Match CSV files from Notion database exports — we handle them
# separately as structured rows.
_DATABASE_CSV_RE = re.compile(r".*\.csv$", re.IGNORECASE)


class NotionDirectoryImporter(BaseImporter):
    """Import Notion markdown exports from a directory."""

    @classmethod
    def validate_source(cls, source_path: Path) -> tuple[bool, str | None]:
        if not source_path.exists():
            return False, f"Path does not exist: {source_path}"
        if not source_path.is_dir():
            return False, f"Notion export must be a directory: {source_path}"
        # Check for at least one .md file
        md_files = list(source_path.rglob("*.md"))
        if not md_files:
            return False, f"No .md files found in {source_path}"
        return True, None

    def ingest(
        self,
        source_path: Path,
        *,
        workspace_id: str = "unknown",
    ) -> Iterator[NormalizedDocument]:
        """Walk the export directory and yield one document per page.

        Each ``.md`` file becomes a single ``NormalizedDocument``.
        Database CSV files are skipped in this first pass (they require
        row-level parsing that is handled separately).
        """
        if not source_path.is_dir():
            raise ImporterError(f"Not a directory: {source_path}")

        md_files = sorted(source_path.rglob("*.md"))
        if not md_files:
            return  # no documents to yield

        for md_file in md_files:
            try:
                doc = self._parse_markdown_file(md_file, workspace_id)
            except Exception:
                # Skip unparseable files — they will be logged by the
                # service layer.
                continue
            if doc is not None:
                yield doc

    # ── Private helpers ────────────────────────────────────────────────

    def _parse_markdown_file(self, file_path: Path, workspace_id: str) -> NormalizedDocument | None:
        """Parse a single exported Notion .md file."""
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ImporterError(f"Cannot read {file_path}: {exc}") from exc

        if not raw.strip():
            return None

        title = self._extract_title(raw, file_path)
        # Remove the "# Title" heading from the content body to avoid duplication
        content = self._strip_title_heading(raw)
        if not content.strip():
            return None

        # Build relative path for provenance
        try:
            rel_path = str(file_path.relative_to(file_path.parent.parent))
        except ValueError:
            rel_path = file_path.name

        return NormalizedDocument(
            external_id=f"notion-import:{workspace_id}:{file_path.stem}",
            content=content.strip(),
            author=None,  # Notion exports don't include author info
            source_url=None,
            created_at=None,
            metadata={
                "page_title": title,
                "source_type": "notion_import",
                "file_name": file_path.name,
                "file_path": rel_path,
                "authority_weight": 0.95,  # Notion authority weight
            },
        )

    @staticmethod
    def _extract_title(raw: str, file_path: Path) -> str:
        """Extract the page title from the first heading, or use the filename."""
        match = _TITLE_RE.search(raw)
        if match:
            return match.group(1).strip()
        # Fallback: use the file stem
        return file_path.stem.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _strip_title_heading(raw: str) -> str:
        """Remove the first '# Title' line from the markdown content."""
        # Split on first double newline to remove the title
        parts = raw.split("\n\n", 1)
        if len(parts) == 2 and _TITLE_RE.match(parts[0]):
            return parts[1]
        return raw
