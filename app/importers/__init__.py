"""Zero-auth importers — turn manual exports into SourceDocument rows.

Importers parse files that a user has already exported from their tools
(Notion markdown directories, Slack export ZIPs, arbitrary files) and
yield ``NormalizedDocument`` instances that the ingestion pipeline can
consume.
"""

from app.importers.notion import NotionDirectoryImporter
from app.importers.slack import SlackExportImporter
from app.importers.generic import GenericFileScanner

__all__ = [
    "NotionDirectoryImporter",
    "SlackExportImporter",
    "GenericFileScanner",
]
