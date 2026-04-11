"""Base importer abstractions.

An *importer* reads files from a local path (directory or archive) and
yields :class:`~app.connectors.base.NormalizedDocument` instances.
Importers are synchronous — they perform file I/O and parsing, never
network calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from app.connectors.base import NormalizedDocument


class ImporterError(Exception):
    """Raised when an importer encounters an unrecoverable problem."""


class BaseImporter(ABC):
    """Abstract base for file-based importers.

    Subclasses implement ``ingest`` which walks the provided *source_path*
    and yields ``NormalizedDocument`` instances.
    """

    @abstractmethod
    def ingest(self, source_path: Path, **options: object) -> Iterator[NormalizedDocument]:
        """Walk *source_path* and yield :class:`NormalizedDocument` instances.

        Parameters
        ----------
        source_path : Path
            Path to a directory or file to import from.
        **options
            Importer-specific options (e.g. channel filters, date ranges).
        """
        ...

    @classmethod
    def validate_source(cls, source_path: Path) -> tuple[bool, str | None]:
        """Quick sanity check — returns ``(ok, error_message)``.

        The default implementation checks that the path exists.
        Subclasses should override for more specific validation.
        """
        if not source_path.exists():
            return False, f"Path does not exist: {source_path}"
        return True, None
